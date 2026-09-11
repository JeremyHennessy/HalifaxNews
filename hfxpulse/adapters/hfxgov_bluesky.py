from __future__ import annotations

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, keyword_hit, parse_datetime, stable_id

ACTOR = "hfxgov.bsky.social"
URL = f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor={ACTOR}&limit=60&filter=posts_no_replies"
PROFILE = f"https://bsky.app/profile/{ACTOR}"
SOURCE = "Halifax Regional Municipality · Bluesky"
KEYWORDS = (
    "emergency", "evac", "fire", "police", "collision", "crash", "road closed", "closure", "traffic",
    "flood", "storm", "water", "outage", "smoke", "alert", "shelter", "transit", "detour", "bridge",
    "downtown", "barrington", "spring garden", "waterfront"
)


def parse_payload(payload) -> list[Incident]:
    rows: list[Incident] = []
    for item in (payload or {}).get("feed", []):
        post = (item or {}).get("post") or {}
        record = post.get("record") or {}
        text = clean_text(record.get("text"))
        if not text or not keyword_hit(text, KEYWORDS):
            continue
        when = record.get("createdAt") or post.get("indexedAt")
        dt = parse_datetime(when)
        if not dt:
            continue
        uri = post.get("uri") or ""
        rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
        link = f"{PROFILE}/post/{rkey}" if rkey else PROFILE
        lower = text.lower()
        if any(k in lower for k in ("fire", "smoke")):
            category = "FIRE"
        elif any(k in lower for k in ("police", "collision", "crash")):
            category = "POLICE"
        elif any(k in lower for k in ("transit", "bus", "ferry")):
            category = "TRANSIT"
        elif any(k in lower for k in ("road", "traffic", "bridge", "closure", "detour")):
            category = "TRAFFIC"
        else:
            category = "EMERGENCY"
        rows.append(
            Incident(
                id=f"hfxgov-{stable_id(uri, when)}",
                source=SOURCE,
                source_url=link,
                title=text[:120] + ("…" if len(text) > 120 else ""),
                summary=text,
                category=category,
                subtype="official_social_update",
                reported_at=iso_utc(dt) or "",
                severity=2,
                signals=["official_social_update"],
                raw_ids=[uri] if uri else [],
            )
        )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=20)
        res.raise_for_status()
        return parse_payload(res.json())

    return guarded_fetch(
        SOURCE,
        PROFILE,
        "official",
        run,
        notes="Official HRM social updates filtered to disruption/public-safety terms. HRM directs residents to this account during emergency events.",
    )
