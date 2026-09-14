from __future__ import annotations

import html as html_lib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, session
from hfxpulse.models import Incident, SourceHealth, utc_now_iso
from hfxpulse.util import clean_text, infer_category, infer_text_siren_score, iso_utc, keyword_hit, parse_datetime, stable_id

# Community collection stays broad, but place names are context rather than incident
# evidence. This prevents ordinary posts such as "adult ballet downtown" from
# becoming emergency signals simply because they mention downtown Halifax.
SIGNAL_TERMS = (
    "sirens", "siren", "police", "rcmp", "fire truck", "fire trucks", "fire department", "structure fire", "smoke",
    "ambulance", "paramedic", "ehs", "crash", "collision", "accident", "road closed", "road closure", "street closed",
    "bridge closed", "blocked off", "emergency", "coast guard", "rescue", "helicopter", "ert", "swat",
    "weapon", "search and rescue", "hazmat", "explosion", "gunshot", "gunshots", "shots fired", "power outage",
    "water main break", "watermain break", "flooding", "fire boat", "fire boats", "incident response", "detour in place",
)
SIGNAL_PREFIXES = ("evacu",)
QUESTION_TERMS = (
    "what happened", "what's happening", "what is happening", "what's going on", "what is going on", "anyone know",
    "does anyone know", "why are there", "what was that", "any idea what", "does anybody know",
)
LOCATION_TERMS = (
    "halifax", "dartmouth", "bedford", "sackville", "cole harbour", "tantallon", "timberlea", "spryfield", "hrm",
    "downtown", "barrington", "spring garden", "waterfront", "lower water", "upper water", "quinpool", "robie",
    "gottingen", "hollis", "brunswick", "citadel", "argyle", "cogswell", "south end", "north end", "macdonald",
    "mackay", "bridge", "harbour",
)
HRM_TERMS = LOCATION_TERMS
SUBREDDITS = (("halifax", False), ("NovaScotia", True))


def _bounded_hit(text: str, term: str) -> bool:
    """Match a complete word or phrase, never a substring inside another word."""
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I))


def _incident_hit(text: str) -> bool:
    value = (text or "").lower()
    if any(_bounded_hit(value, term) for term in SIGNAL_TERMS):
        return True
    if any(re.search(rf"(?<!\w){re.escape(prefix)}\w*", value, re.I) for prefix in SIGNAL_PREFIXES):
        return True
    return any(term in value for term in QUESTION_TERMS) and any(term in value for term in LOCATION_TERMS)


def _row(subreddit: str, post_id: str, title: str, body: str, reported: str, permalink: str, require_hrm: bool, metadata: dict | None = None) -> Incident | None:
    combined = f"{title} {body}"
    if not _incident_hit(combined):
        return None
    if require_hrm and not keyword_hit(combined, HRM_TERMS):
        return None
    return Incident(
        id=f"reddit-{subreddit.lower()}-{stable_id(post_id, title)}",
        source=f"r/{subreddit}",
        source_url=permalink,
        title=title,
        summary=body[:700] if body else "Community report — not independently verified.",
        category=infer_category(combined, "COMMUNITY"),
        subtype="community_report",
        reported_at=reported,
        source_kind="community",
        confidence="unverified",
        severity=1,
        siren_score=infer_text_siren_score(combined, reported, "community"),
        signals=["community_report", "unverified"],
        raw_ids=[post_id] if post_id else [],
        metadata={"subreddit": subreddit, **(metadata or {})},
    )


def parse_payload(payload, subreddit: str, require_hrm: bool = False) -> list[Incident]:
    rows: list[Incident] = []
    children = (((payload or {}).get("data") or {}).get("children") or [])
    for child in children:
        p = (child or {}).get("data") or {}
        title = clean_text(p.get("title"))
        body = clean_text(p.get("selftext"))
        created = p.get("created_utc")
        if not title or not created:
            continue
        reported = datetime.fromtimestamp(float(created), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        permalink = p.get("permalink") or ""
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        row = _row(
            subreddit,
            str(p.get("id") or ""),
            title,
            body,
            reported,
            url,
            require_hrm,
            {"score": p.get("score"), "num_comments": p.get("num_comments"), "transport": "json"},
        )
        if row:
            rows.append(row)
    return rows


def _self_post_body(content_html: str) -> str:
    """Extract user-authored self-post text without persisting feed author metadata."""
    if not content_html:
        return ""
    soup = BeautifulSoup(html_lib.unescape(content_html), "html.parser")
    body = soup.select_one(".md")
    return clean_text(body.get_text(" ", strip=True)) if body else ""


def parse_rss(data: bytes, subreddit: str, require_hrm: bool = False) -> list[Incident]:
    root = ET.fromstring(data)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    rows: list[Incident] = []
    for entry in root.findall("a:entry", ns):
        title = clean_text(entry.findtext("a:title", default="", namespaces=ns))
        content_html = entry.findtext("a:content", default="", namespaces=ns) or entry.findtext("a:summary", default="", namespaces=ns) or ""
        body = _self_post_body(content_html)
        when = entry.findtext("a:published", default="", namespaces=ns) or entry.findtext("a:updated", default="", namespaces=ns)
        dt = parse_datetime(when)
        if not title or not dt:
            continue
        link = ""
        for node in entry.findall("a:link", ns):
            href = clean_text(node.attrib.get("href"))
            if href and "reddit.com" in href:
                link = href
                break
        entry_id = clean_text(entry.findtext("a:id", default="", namespaces=ns)) or link
        raw_id = entry_id.removeprefix("t3_") if entry_id else stable_id(link, title)
        row = _row(
            subreddit,
            raw_id,
            title,
            body,
            iso_utc(dt) or "",
            link or f"https://www.reddit.com/r/{subreddit}/new/",
            require_hrm,
            {"transport": "rss"},
        )
        if row:
            rows.append(row)
    return rows


def parse_atom(data: bytes | str, subreddit: str = "halifax", require_hrm: bool = False) -> list[Incident]:
    """Backward-compatible name for the public Reddit Atom parser."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return parse_rss(payload, subreddit, require_hrm=require_hrm)


def fetch() -> AdapterResult:
    rows: dict[str, Incident] = {}
    failures: list[str] = []
    successes = 0
    transports: list[str] = []
    s = session()
    for subreddit, require_hrm in SUBREDDITS:
        json_url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=100&raw_json=1"
        rss_url = f"https://www.reddit.com/r/{subreddit}/new/.rss?sort=new"
        parsed = None
        try:
            res = s.get(json_url, timeout=15, headers={"Accept": "application/json"})
            res.raise_for_status()
            parsed = parse_payload(res.json(), subreddit, require_hrm=require_hrm)
            transports.append(f"r/{subreddit}:json")
        except Exception as json_exc:
            try:
                res = s.get(rss_url, timeout=15, headers={"Accept": "application/atom+xml,application/xml,text/xml,*/*"})
                res.raise_for_status()
                parsed = parse_rss(res.content, subreddit, require_hrm=require_hrm)
                transports.append(f"r/{subreddit}:rss")
            except Exception as rss_exc:
                failures.append(f"r/{subreddit}: json {type(json_exc).__name__}; rss {type(rss_exc).__name__}: {rss_exc}")
        if parsed is not None:
            successes += 1
            rows.update({row.id: row for row in parsed})

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
            notes=f"{successes}/{len(SUBREDDITS)} subreddits reachable via {', '.join(transports) or 'no transport'}. JSON is preferred; Atom/RSS is the fallback. Usernames are not persisted.",
        ),
    )
