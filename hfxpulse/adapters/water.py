from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.halifaxwater.ca/notices-and-news"
SOURCE = "Halifax Water"


def parse_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        title = clean_text(link.get_text(" ", strip=True))
        if len(title) < 10:
            continue
        lower = title.lower()
        if not any(k in lower for k in ("notice", "advisory", "traffic", "water", "service", "repair", "maintenance", "closure")):
            continue
        full = urljoin(URL, link.get("href", ""))
        if full in seen:
            continue
        seen.add(full)
        container = link.find_parent(["article", "li", "div"]) or link.parent
        context = clean_text(container.get_text(" ", strip=True) if container else title)
        m = re.search(r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}", context, re.I)
        dt = parse_datetime(m.group(0)) if m else None
        if not dt:
            continue
        rows.append(
            Incident(
                id=f"water-{stable_id(full)}",
                source=SOURCE,
                source_url=full,
                title=title,
                summary=context[:600],
                category="UTILITY",
                subtype="water_notice",
                reported_at=iso_utc(dt) or "",
                severity=2 if any(k in lower for k in ("emergency", "closure", "outage", "boil")) else 1,
                signals=["official_notice"],
            )
        )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        rows = parse_html(res.text)
        if not rows:
            raise ValueError("Halifax Water page fetched but no dated notices were parsed")
        return rows

    return guarded_fetch(SOURCE, URL, "official", run)
