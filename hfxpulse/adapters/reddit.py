from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, session
from hfxpulse.models import Incident, SourceHealth, utc_now_iso
from hfxpulse.util import clean_text, infer_category, infer_text_siren_score, keyword_hit, stable_id

KEYWORDS = (
    "sirens", "siren", "police", "rcmp", "fire", "ambulance", "ehs", "smoke", "crash", "collision", "closed",
    "closure", "downtown", "barrington", "spring garden", "waterfront", "lower water", "quinpool", "robie", "emergency",
    "evacu", "coast guard", "rescue", "helicopter", "ert", "swat", "weapon", "bridge", "traffic", "detour", "ferry",
    "boats", "search and rescue", "hazmat", "explosion", "bang", "power outage", "water main"
)
HRM_TERMS = (
    "halifax", "dartmouth", "bedford", "sackville", "cole harbour", "tantallon", "timberlea", "spryfield", "hrm",
    "barrington", "spring garden", "lower water", "quinpool", "robie", "waterfront", "macdonald", "mackay"
)
SUBREDDITS = (
    ("halifax", False),
    ("NovaScotia", True),
)


def parse_payload(payload, subreddit: str, require_hrm: bool = False) -> list[Incident]:
    rows: list[Incident] = []
    children = (((payload or {}).get("data") or {}).get("children") or [])
    for child in children:
        p = (child or {}).get("data") or {}
        title = clean_text(p.get("title"))
        body = clean_text(p.get("selftext"))
        combined = f"{title} {body}"
        if not keyword_hit(combined, KEYWORDS):
            continue
        if require_hrm and not keyword_hit(combined, HRM_TERMS):
            continue
        created = p.get("created_utc")
        if not created:
            continue
        reported = datetime.fromtimestamp(float(created), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        permalink = p.get("permalink") or ""
        category = infer_category(combined, "COMMUNITY")
        rows.append(Incident(
            id=f"reddit-{subreddit.lower()}-{stable_id(p.get('id'), title)}",
            source=f"r/{subreddit}",
            source_url=f"https://www.reddit.com{permalink}",
            title=title,
            summary=body[:500] if body else "Community report — not independently verified.",
            category=category,
            subtype="community_report",
            reported_at=reported,
            source_kind="community",
            confidence="unverified",
            severity=1,
            siren_score=infer_text_siren_score(combined, reported, "community"),
            signals=["community_report", "unverified"],
            raw_ids=[str(p.get("id"))] if p.get("id") else [],
            metadata={"score": p.get("score"), "num_comments": p.get("num_comments"), "subreddit": subreddit},
        ))
    return rows


def fetch() -> AdapterResult:
    rows: dict[str, Incident] = {}
    failures: list[str] = []
    successes = 0
    s = session()
    for subreddit, require_hrm in SUBREDDITS:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=100&raw_json=1"
        try:
            res = s.get(url, timeout=20, headers={"Accept": "application/json"})
            res.raise_for_status()
            parsed = parse_payload(res.json(), subreddit, require_hrm=require_hrm)
            successes += 1
            rows.update({row.id: row for row in parsed})
        except Exception as exc:
            failures.append(f"r/{subreddit}: {type(exc).__name__}: {exc}")
    return AdapterResult(
        incidents=list(rows.values()),
        health=SourceHealth(
            source="Reddit Halifax-area communities",
            url="https://www.reddit.com/r/halifax/new/",
            authority="community",
            status="ok" if successes else "error",
            checked_at=utc_now_iso(),
            fetched_at=utc_now_iso() if successes else None,
            records=len(rows),
            error="; ".join(failures[:2]) if failures and not successes else None,
            notes=f"{successes}/{len(SUBREDDITS)} subreddits reachable. Public post text only; author identity is not stored.",
        ),
    )
