#!/usr/bin/env python3
"""Verify the actual public dataset, independently of successful workflow status."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_URL = "https://jeremyhennessy.github.io/HalifaxNews/public/data/incidents.json"


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("generated_at must be an ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at is invalid") from exc
    if result.tzinfo is None:
        raise ValueError("generated_at must include a timezone")
    return result.astimezone(timezone.utc)


def validate_publication(payload: object, *, now: datetime,
                         max_age_minutes: float = 20,
                         expected_at: datetime | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("public dataset must be an object")
    generated = timestamp(payload.get("generated_at"))
    age = now - generated
    if age < -timedelta(minutes=5):
        raise ValueError("public generated_at is implausibly in the future")
    if age > timedelta(minutes=max_age_minutes):
        raise ValueError(f"public dataset is stale: {age.total_seconds() / 60:.1f} minutes old")
    if expected_at is not None and generated < expected_at:
        raise ValueError("Pages is still serving a publication older than the collected dataset")
    for key, count_key in (("events", "event_count"), ("incidents", "observation_count")):
        rows = payload.get(key)
        if not isinstance(rows, list) or payload.get(count_key) != len(rows):
            raise ValueError(f"invalid public {key} contract")
    health = payload.get("source_health")
    if not isinstance(health, list) or not health or not all(isinstance(s, dict) for s in health):
        raise ValueError("missing or invalid public source_health")
    return {
        "generated_at": payload["generated_at"],
        "age_minutes": round(max(0, age.total_seconds()) / 60, 1),
        "events": len(payload["events"]),
        "observations": len(payload["incidents"]),
        "sources_ok_at_collection": sum(s.get("status") == "ok" for s in health),
        "sources_total": len(health),
    }


def fetch_publication(url: str) -> object:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("public dataset URL must use HTTPS")
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("freshness_check", str(time.time_ns())))
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    request = Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "HFX-Pulse-freshness-check"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--expected-file", type=Path)
    parser.add_argument("--max-age-minutes", type=float, default=20)
    parser.add_argument("--wait-seconds", type=float, default=0,
                        help="Bounded wait for Pages propagation; default is a single check")
    args = parser.parse_args(argv)
    if args.max_age_minutes <= 0 or not 0 <= args.wait_seconds <= 600:
        parser.error("age must be positive and wait must be between 0 and 600 seconds")
    expected_at = None
    if args.expected_file:
        expected_at = timestamp(json.loads(args.expected_file.read_text())["generated_at"])
    deadline = time.monotonic() + args.wait_seconds
    attempts = 0
    while True:
        if attempts and time.monotonic() >= deadline:
            print("Publication verification deadline reached", file=sys.stderr)
            return 1
        attempts += 1
        try:
            summary = validate_publication(fetch_publication(args.url),
                now=datetime.now(timezone.utc), max_age_minutes=args.max_age_minutes,
                expected_at=expected_at)
            print(json.dumps({"url": args.url, **summary}))
            return 0
        except (ValueError, OSError) as exc:
            if isinstance(exc, HTTPError) and exc.code in (401, 403):
                print(f"Publication access denied; not retrying: {exc}", file=sys.stderr)
                return 1
            print(f"Publication not verified: {exc}", file=sys.stderr)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 1
            time.sleep(min(15, remaining))


if __name__ == "__main__":
    raise SystemExit(main())
