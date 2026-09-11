from __future__ import annotations

from urllib.parse import quote

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, infer_category, infer_text_siren_score, iso_utc, keyword_hit, parse_datetime, stable_id

API = "https://public.api.bsky.app/xrpc"
KEYWORDS = (
    "sirens", "siren", "police", "rcmp", "fire", "ambulance", "ehs", "smoke", "crash", "collision",
    "closed", "closure", "downtown", "barrington", "spring garden", "waterfront", "lower water", "quinpool",
    "robie", "emergency", "evacu", "coast guard", "rescue", "helicopter", "ert", "swat", "weapon", "bridge",
    "traffic", "detour", "ferry", "transit", "outage", "flood", "storm", "hazmat"
)

AUTHOR_SOURCES = (
    ("hfx-fire.bsky.social", "Halifax Fire · Bluesky", "official", "official"),
    ("hfxtransit.bsky.social", "Halifax Transit · Bluesky", "official", "official"),
    ("hfxevents.bsky.social", "Halifax Events · Bluesky", "official", "official"),
    ("halifaxnoise.bsky.social", "Halifax Noise · Bluesky", "community", "unverified"),
    ("hrfe.bsky.social", "HRFE automated mirror · Bluesky", "secondary", "secondary"),
    ("hrfeincidents.bsky.social", "HRFE Incidents automated mirror · Bluesky", "secondary", "secondary"),
)

SEARCH_QUERIES = (
    'Halifax sirens', 'Halifax fire', 'Halifax police', 'Halifax ambulance', 'downtown Halifax emergency',
    'Halifax crash', 'Halifax Coast Guard', 'Halifax smoke', 'Lower Water Halifax', 'Barrington Halifax closure'
)


def _post_link(post: dict) -> str:
    uri = post.get("uri") or ""
    actor = ((post.get("author") or {}).get("handle") or "")
    rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
    return f"https://bsky.app/profile/{actor}/post/{rkey}" if actor and rkey else "https://bsky.app/"


def _to_incident(post: dict, source: str, source_kind: str, confidence: str, prefix: str) -> Incident | None:
    record = post.get("record") or {}
    text = clean_text(record.get("text"))
    if not text or not keyword_hit(text, KEYWORDS):
        return None
    when = record.get("createdAt") or post.get("indexedAt")
    dt = parse_datetime(when)
    if not dt:
        return None
    reported = iso_utc(dt) or ""
    author = (post.get("author") or {}).get("handle") or None
    uri = post.get("uri") or ""
    category = infer_category(text, "COMMUNITY" if source_kind == "community" else "EMERGENCY")
    return Incident(
        id=f"{prefix}-{stable_id(uri, when, text)}",
        source=source if not author or prefix != "bsky-search" else f"Bluesky · @{author}",
        source_url=_post_link(post),
        title=text[:140] + ("…" if len(text) > 140 else ""),
        summary=text,
        category=category,
        subtype="social_post",
        reported_at=reported,
        source_kind=source_kind,
        confidence=confidence,
        severity=2 if category in {"FIRE", "RESCUE", "EMS", "POLICE", "EMERGENCY"} else 1,
        siren_score=infer_text_siren_score(text, reported, source_kind),
        signals=[f"{source_kind}_social"],
        raw_ids=[uri] if uri else [],
        metadata={"handle": author} if author else {},
    )


def _fetch_author(actor: str, source: str, source_kind: str, confidence: str) -> AdapterResult:
    profile = f"https://bsky.app/profile/{actor}"
    endpoint = f"{API}/app.bsky.feed.getAuthorFeed"

    def run() -> list[Incident]:
        res = session().get(endpoint, params={"actor": actor, "limit": 75, "filter": "posts_no_replies"}, timeout=20)
        res.raise_for_status()
        rows = []
        for item in (res.json() or {}).get("feed", []):
            row = _to_incident((item or {}).get("post") or {}, source, source_kind, confidence, f"bsky-{stable_id(actor)}")
            if row:
                rows.append(row)
        return rows

    return guarded_fetch(source, profile, source_kind, run, notes="Bluesky author feed filtered to Halifax disruption and public-safety terms.")


def fetch_official_and_local() -> AdapterResult:
    incidents: list[Incident] = []
    failures: list[str] = []
    successes = 0
    for actor, source, source_kind, confidence in AUTHOR_SOURCES:
        result = _fetch_author(actor, source, source_kind, confidence)
        if result.health and result.health.status == "ok":
            successes += 1
        elif result.health:
            failures.append(f"{actor}: {result.health.error}")
        incidents.extend(result.incidents)
    status = "ok" if successes else "error"
    from hfxpulse.models import SourceHealth, utc_now_iso
    health = SourceHealth(
        source="Bluesky local accounts",
        url="https://bsky.app/",
        authority="mixed",
        status=status,
        checked_at=utc_now_iso(),
        fetched_at=utc_now_iso() if successes else None,
        records=len(incidents),
        error="; ".join(failures[:3]) if failures and not successes else None,
        notes=f"{successes}/{len(AUTHOR_SOURCES)} configured accounts reachable; includes official, community and automated mirrors.",
    )
    return AdapterResult(incidents=incidents, health=health)


def fetch_search() -> AdapterResult:
    endpoint = f"{API}/app.bsky.feed.searchPosts"

    def run() -> list[Incident]:
        rows: dict[str, Incident] = {}
        s = session()
        for query in SEARCH_QUERIES:
            res = s.get(endpoint, params={"q": query, "limit": 40, "sort": "latest"}, timeout=20)
            res.raise_for_status()
            for post in (res.json() or {}).get("posts", []):
                row = _to_incident(post or {}, "Bluesky community search", "community", "unverified", "bsky-search")
                if row:
                    rows[row.id] = row
        return list(rows.values())

    return guarded_fetch(
        "Bluesky community search",
        f"{endpoint}?q={quote('Halifax sirens')}",
        "community",
        run,
        notes="Broad public search across multiple Halifax emergency/disruption queries. Posts are unverified context unless independently corroborated.",
    )
