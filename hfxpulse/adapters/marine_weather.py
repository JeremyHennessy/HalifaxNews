from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import HALIFAX_TZ, clean_text, iso_utc, parse_datetime, stable_id

URL = "https://weather.gc.ca/marine/forecast_e.html?mapID=15&siteID=06000"
SOURCE = "Environment Canada · Halifax Harbour marine warnings"
LOCATION = "Halifax Harbour and Approaches"

ISSUED_RE = re.compile(
    r"Issued\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?\s*(?:ADT|AST)?\s*\d{1,2}\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})",
    re.I,
)


def _warning_blocks(soup: BeautifulSoup):
    for heading in soup.find_all(["h2", "h3", "h4"]):
        title = clean_text(heading.get_text(" ", strip=True))
        if "warning" not in title.lower() or "in effect" not in title.lower():
            continue
        yield heading, title


def parse_html(html: str, now: datetime | None = None) -> list[Incident]:
    now = now or datetime.now(HALIFAX_TZ)
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()

    for heading, title in _warning_blocks(soup):
        parent = heading.find_parent(["section", "article", "div"]) or heading.parent
        context = clean_text(parent.get_text(" ", strip=True) if parent else title)
        # Limit giant page containers while retaining the issued time and warning explanation.
        if len(context) > 1400:
            pieces = [title]
            node = heading.find_next_sibling()
            for _ in range(8):
                if node is None:
                    break
                pieces.append(clean_text(node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node)))
                node = node.find_next_sibling()
            context = clean_text(" ".join(pieces))

        issued = None
        match = ISSUED_RE.search(context)
        if match:
            issued = parse_datetime(match.group(1))
        reported = iso_utc(issued) if issued else iso_utc(now)
        key = f"{title}|{reported[:13] if reported else now.date().isoformat()}"
        if key in seen:
            continue
        seen.add(key)
        lower = context.lower()
        severity = 3 if any(term in lower for term in ("storm warning", "hurricane force", "freezing spray warning")) else 2
        rows.append(Incident(
            id=f"marine-warning-{stable_id(key)}",
            source=SOURCE,
            source_url=URL,
            title=title,
            summary=context[:900],
            category="MARINE",
            subtype="marine_weather_warning",
            reported_at=reported or iso_utc(now) or "",
            source_kind="official",
            confidence="official",
            status="active",
            location_text=LOCATION,
            lat=44.65,
            lon=-63.56,
            location_precision="marine_area",
            severity=severity,
            signals=["official_marine_warning"],
            metadata={"currently_active": True, "marine_area": LOCATION},
        ))
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        return parse_html(res.text)

    return guarded_fetch(
        SOURCE,
        URL,
        "official",
        run,
        notes="Environment Canada warnings specifically for Halifax Harbour and Approaches; emits no row when no warning is in effect.",
    )
