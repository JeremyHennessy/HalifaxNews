from __future__ import annotations

import html as html_lib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, session
from hfxpulse.models import Incident, SourceHealth, utc_now_iso
from hfxpulse.util import clean_text, infer_category, infer_text_siren_score, iso_utc, keyword_hit, parse_datetime, stable_id

KEYWORDS = (
    "sirens", "siren", "police", "rcmp", "fire", "ambulance", "ehs", "smoke", "crash", "collision", "closed",
    "closure", "downtown", "barrington", "spring garden", "waterfront", "lower water", "quinpool", "robie", "emergency",
    "evacu", "coast guard", "rescue", "helicopter", "ert", "swat", "weapon", "bridge", "traffic", "detour", "ferry",
    "boats", "search and rescue", "hazmat", "explosion", "bang", "power outage", "water main", "gunshot", "shots"
)
HRM_TERMS = (
    "halifax", "dartmouth", "bedford", "sackville", "cole harbour", "tantallon", "timberlea", "spryfield", "hrm",
    "barrington", "spring garden", "lower water", "quinpool", "robie", "waterfront", "macdonald", "mackay"
)
SUBREDDITS = (("halifax", False), ("NovaScotia", True))


def _row(subreddit: str, post_id: str, title: str, body: str, reported: str, permalink: str, require_hrm: bool, metadata: dict | None = None) -> Incident | None:
    combined = f"{title} {body}"
    if not keyword_hit(combined, KEYWORDS):
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
        row = _row(subreddit, str(p.get("id") or ""), title, body, reported, url, require_hrm, {"score": p.get("score"), "num_comments": p.get("num_comments")})
        if row:
            rows.append(row)
    return rows


def _strip_html(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", html_lib.unescape(value or "")))


def parse_rss(data: bytes, subreddit: str, require_hrm: bool = False) -> list[Incident]:
    root = ET.fromstring(data)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    rows: list[Incident] = []
    for entry in root.findall("a:entry", ns):
        title = clean_text(entry.findtext("a:title", default="", namespaces=ns))
        body = _strip_html(entry.findtext("a:content", default="", namespaces=ns) or entry.findtext("a:summary", default="", namespaces=ns))
        when = entry.findtext("a:updated", default="", namespaces=ns) or entry.findtext("a:published", default="", namespaces=ns)
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
        row = _row(subreddit, entry_id, title, body, iso_utc(dt) or "", link or f"https://www.reddit.com/r/{subreddit}/new/", require_hrm, {"transport": "rss"})
        if row:
            rows.append(row)
    return rows


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
