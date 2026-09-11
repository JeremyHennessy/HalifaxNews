from __future__ import annotations

import re

from hfxpulse.adapters.base import AdapterResult, session
from hfxpulse.adapters.hrfe import parse_hrfe_text
from hfxpulse.models import Incident, SourceHealth, utc_now_iso

API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
PROFILE_BASE = "https://bsky.app/profile"
SOURCE = "HRFE incident mirror · Bluesky"
ACTORS = ("hrfeincidents.bsky.social", "hrfe.bsky.social")


def parse_mirror_post(text: str, actor: str) -> list[Incident]:
    # Mirrors prepend a feed label before the stable HRFE public fields.
    body = re.sub(r"^\s*HRFE\s+Incident\s+Feed\s*", "", text or "", flags=re.I)
    rows = parse_hrfe_text(body)
    for row in rows:
        call = (row.metadata or {}).get("call_number") or (row.raw_ids[0] if row.raw_ids else "")
        row.id = f"hrfe-mirror-{str(call).lower()}" if call else row.id.replace("hrfe-", "hrfe-mirror-", 1)
        row.source = SOURCE
        row.source_url = f"{PROFILE_BASE}/{actor}"
        row.source_kind = "secondary"
        row.confidence = "secondary"
        row.signals = [s for s in row.signals if s != "official_dispatch"] + ["hrfe_feed_mirror", "linked_dispatch_signal"]
        row.metadata = {**row.metadata, "mirror_actor": actor, "upstream": "HRFE public incident RSS/feed"}
    return rows


def fetch() -> AdapterResult:
    s = session()
    rows: dict[str, Incident] = {}
    successes = 0
    failures: list[str] = []
    for actor in ACTORS:
        try:
            res = s.get(API, params={"actor": actor, "limit": 100, "filter": "posts_no_replies"}, timeout=20)
            res.raise_for_status()
            successes += 1
            for item in (res.json() or {}).get("feed", []):
                post = (item or {}).get("post") or {}
                record = post.get("record") or {}
                text = record.get("text") or ""
                parsed = parse_mirror_post(text, actor)
                for row in parsed:
                    uri = post.get("uri") or ""
                    if uri:
                        rkey = uri.rsplit("/", 1)[-1]
                        row.source_url = f"{PROFILE_BASE}/{actor}/post/{rkey}"
                        row.raw_ids = list(dict.fromkeys(row.raw_ids + [uri]))
                    rows[row.id] = row
        except Exception as exc:
            failures.append(f"{actor}: {type(exc).__name__}: {exc}")

    return AdapterResult(
        incidents=list(rows.values()),
        health=SourceHealth(
            source=SOURCE,
            url=f"{PROFILE_BASE}/{ACTORS[0]}",
            authority="secondary automated mirror",
            status="ok" if successes else "error",
            checked_at=utc_now_iso(),
            fetched_at=utc_now_iso() if successes else None,
            records=len(rows),
            error="; ".join(failures[:2]) if failures and not successes else None,
            notes=(
                f"{successes}/{len(ACTORS)} HRFE mirror accounts reachable. Primary mirror states it republishes the HRFE RSS incident feed "
                "and may lag by up to five minutes. Not operated by HRFE."
            ),
        ),
    )
