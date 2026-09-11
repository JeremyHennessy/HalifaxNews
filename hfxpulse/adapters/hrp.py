from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.halifax.ca/home/news?category=25"
SOURCE = "Halifax Regional Police"

POLICE_TERMS = (
    "police", "collision", "road closure", "weapons", "firearm", "emergency", "missing", "arrest",
    "traffic", "investigation", "bomb", "suspicious", "evacuation", "downtown", "waterfront"
)


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
        seen.add(full)
        container = link.find_parent(["article", "li", "div"]) or link.parent
        context = clean_text(container.get_text(" ", strip=True) if container else title)
        date_match = re.search(
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM))?",
            context,
            re.I,
        )
        dt = parse_datetime(date_match.group(0)) if date_match else None
        if not dt:
            continue
        reported = iso_utc(dt)
        text = f"{title} {context}".lower()
        severity = 2 if any(w in text for w in ("closure", "weapon", "firearm", "collision", "evac")) else 1
        rows.append(
            Incident(
                id=f"hrp-{stable_id(full)}",
                source=SOURCE,
                source_url=full,
                title=title,
                summary=context[:500],
                category="POLICE",
                subtype="media_release",
                reported_at=reported or "",
                severity=severity,
                signals=["official_release"],
            )
        )
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
