from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hfxpulse.adapters import (
    bluesky, bridges, downtown_events, emergency_ns, hfxgov_bluesky, hrfe, hrfe_open_data, hrp,
    newsfeeds, ns511, ns_power, port_cruise, rcmp, reddit, transit, water, weather,
)
from hfxpulse.correlation import correlate
from hfxpulse.geocode import enrich as geocode_enrich
from hfxpulse.models import Incident, SourceHealth, utc_now_iso
from hfxpulse.util import parse_datetime

ADAPTERS = [
    hrfe.fetch,
    hrfe_open_data.fetch,
    transit.fetch,
    hrp.fetch,
    rcmp.fetch,
    hfxgov_bluesky.fetch,
    bluesky.fetch_official_and_local,
    bluesky.fetch_search,
    ns511.fetch,
    bridges.fetch,
    water.fetch,
    weather.fetch,
    emergency_ns.fetch,
    ns_power.fetch,
    reddit.fetch,
    newsfeeds.fetch,
    downtown_events.fetch,
    port_cruise.fetch,
]


def _read_existing(path: Path) -> list[Incident]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [Incident(**row) for row in payload.get("incidents", [])]
    except Exception:
        return []


def _retain_history(existing: list[Incident], fresh: list[Incident], hours: int = 48) -> list[Incident]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    merged = {r.id: r for r in existing}
    merged.update({r.id: r for r in fresh})
    kept = []
    for row in merged.values():
        dt = parse_datetime(row.reported_at)
        if dt and dt >= cutoff:
            kept.append(row)
    return kept


def _run_adapters() -> tuple[list[Incident], list[SourceHealth]]:
    fresh: list[Incident] = []
    health: list[SourceHealth] = []
    with ThreadPoolExecutor(max_workers=min(10, len(ADAPTERS))) as pool:
        futures = {pool.submit(adapter): adapter for adapter in ADAPTERS}
        for future in as_completed(futures):
            adapter = futures[future]
            try:
                result = future.result()
                fresh.extend(result.incidents)
                if result.health:
                    health.append(result.health)
            except Exception as exc:
                # Adapters are expected to guard their own failures, but keep a second isolation boundary.
                health.append(SourceHealth(
                    source=getattr(adapter, "__module__", repr(adapter)).rsplit(".", 1)[-1],
                    url="",
                    authority="unknown",
                    status="error",
                    checked_at=utc_now_iso(),
                    error=f"Unhandled adapter error: {type(exc).__name__}: {exc}",
                ))
    return fresh, health


def collect(output: Path) -> dict:
    fresh, health = _run_adapters()
    existing = _read_existing(output)
    rows = _retain_history(existing, fresh)
    cache_path = output.parents[2] / "data" / "geocode_cache.json"
    geocode_enrich(rows, cache_path)
    correlate(rows)
    rows.sort(key=lambda r: parse_datetime(r.reported_at) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    health.sort(key=lambda h: (h.status != "error", h.source.lower()))

    payload = {
        "schema_version": 2,
        "generated_at": utc_now_iso(),
        "history_hours": 48,
        "collector_count": len(ADAPTERS),
        "incidents": [r.to_dict() for r in rows],
        "source_health": [h.to_dict() for h in health],
        "disclaimer": "Broad public-information aggregator. Sources can be delayed, wrong or incomplete. Provenance is shown on every signal. For emergencies call 911.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(output)
    return payload
