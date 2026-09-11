from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.halifax.ca/home/news?category=25"
SOURCE = "Halifax Regional Police"
DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"\d{1,2},\s+\d{4}(?:\s*(?:-\s*)?\d{1,2}:\d{2}\s*(?:AM|PM))?",
    re.I,
)


def _nearest_dated_context(link) -> tuple[str, re.Match | None]:
    node = link.parent
    last = clean_text(link.get_text(" ", strip=True))
    for _ in range(8):
        if node is None:
            break
        last = clean_text(node.get_text(" ", strip=True))
        match = DATE_RE.search(last)
        if match:
            return last, match
        node = node.parent
    return last, None


def parse_hrp_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        title = clean_text(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if len(title) < 12 or "/home/news/" not in href:
            continue
        full = urljoin(URL, href)
        if full in seen:
            continue
        context, date_match = _nearest_dated_context(link)
        if not date_match:
            continue
        dt = parse_datetime(date_match.group(0))
        if not dt:
            continue
        seen.add(full)
        reported = iso_utc(dt) or ""
        lower = f"{title} {context}".lower()
        severity = 2 if any(w in lower for w in ("closure", "weapon", "firearm", "collision", "evac", "shoot", "stabb")) else 1
        rows.append(Incident(
            id=f"hrp-{stable_id(full)}",
            source=SOURCE,
            source_url=full,
            title=title,
            summary=context[:700],
            category="POLICE",
            subtype="media_release",
            reported_at=reported,
            source_kind="official",
            confidence="official",
            severity=severity,
            signals=["official_release"],
        ))
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        rows = parse_hrp_html(res.text)
        if not rows:
            raise ValueError("HRP news page fetched but no dated police release links were parsed")
        return rows

    return guarded_fetch(SOURCE, URL, "official", run, notes="Official HRP releases; useful for context/corroboration but often slower than dispatch feeds.")
