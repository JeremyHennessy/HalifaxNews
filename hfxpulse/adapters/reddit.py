from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, keyword_hit, stable_id

URL = "https://www.reddit.com/r/halifax/new.json?limit=60&raw_json=1"
SOURCE = "r/halifax community"
KEYWORDS = (
    "sirens", "police", "fire", "ambulance", "smoke", "crash", "collision", "closed", "closure", "downtown",
    "barrington", "spring garden", "waterfront", "quinpool", "rob ie", "robie", "emergency", "evacu"
)


def parse_payload(payload) -> list[Incident]:
    rows: list[Incident] = []
    children = (((payload or {}).get("data") or {}).get("children") or [])
    for child in children:
        p = (child or {}).get("data") or {}
        title = clean_text(p.get("title"))
        body = clean_text(p.get("selftext"))
        if not keyword_hit(f"{title} {body}", KEYWORDS):
            continue
        created = p.get("created_utc")
        if not created:
            continue
        reported = datetime.fromtimestamp(float(created), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        permalink = p.get("permalink") or ""
        rows.append(
            Incident(
                id=f"reddit-{stable_id(p.get('id'), title)}",
                source=SOURCE,
                source_url=f"https://www.reddit.com{permalink}",
                title=title,
                summary=body[:350] if body else "Community report — not independently verified.",
                category="COMMUNITY",
                subtype="community_report",
                reported_at=reported,
                source_kind="community",
                confidence="unverified",
                severity=1,
                signals=["community_report", "unverified"],
                raw_ids=[str(p.get("id"))] if p.get("id") else [],
                # Do not persist author identity; it is not needed for the product purpose.
                metadata={"score": p.get("score"), "num_comments": p.get("num_comments")},
            )
        )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=20, headers={"Accept": "application/json"})
        res.raise_for_status()
        return parse_payload(res.json())

    return guarded_fetch(
        SOURCE,
        URL,
        "community",
        run,
        notes="Unverified context only. Community posts never upgrade an incident to confirmed status and author identities are not stored.",
    )
