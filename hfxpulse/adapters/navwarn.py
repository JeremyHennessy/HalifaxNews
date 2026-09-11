from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

SEARCH_URL = "https://nis.ccg-gcc.gc.ca/public/rest/messages/en/search"
SOURCE = "Canadian Coast Guard Halifax NAVWARNs"
HALIFAX_TERMS = (
    "halifax harbour", "halifax harbor", "bedford basin", "halifax", "dartmouth",
    "macdonald bridge", "mackay bridge",
)
ID_RE = re.compile(r"\bNW-[A-Z]-\d{4}-\d{2}\b", re.I)
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\s+UTC\b", re.I)


def _recent(value: str, now: datetime, hours: int = 96) -> bool:
    dt = parse_datetime(value)
    if not dt:
        return False
    return dt >= now.astimezone(timezone.utc) - timedelta(hours=hours)


def _severity(text: str) -> int:
    lower = text.lower()
    if any(term in lower for term in ("distress", "search and rescue", "person overboard", "drifting hazard", "navigation prohibited", "closed to navigation")):
        return 3
    if any(term in lower for term in ("restricted", "diving", "bridge", "construction", "marine works", "dredging", "unlit", "removed from position")):
        return 2
    return 1


def _halifax_related(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in HALIFAX_TERMS)


def parse_html(html: str, now: datetime | None = None) -> list[Incident]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    by_id: dict[str, Incident] = {}

    # The server-rendered result page includes table rows in its export view.
    # Header positions can change, so identify rows by NAVWARN ID/date patterns.
    for tr in soup.select("tr"):
        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in tr.select("th,td")]
        if not cells:
            continue
        row_text = clean_text(" | ".join(cells))
        id_match = ID_RE.search(row_text)
        date_match = DATE_RE.search(row_text)
        if not id_match or not date_match or not _halifax_related(row_text):
            continue
        nav_id = id_match.group(0).upper()
        date_text = date_match.group(0)
        if not _recent(date_text, now):
            continue

        # Prefer the cell after the date as title when possible; otherwise use
        # the first meaningful text fragment that is not the ID/date.
        title = "Halifax navigational warning"
        for idx, cell in enumerate(cells):
            if DATE_RE.search(cell) and idx + 1 < len(cells):
                candidate = clean_text(cells[idx + 1])
                if candidate and not ID_RE.fullmatch(candidate):
                    title = candidate
                    break
        if title == "Halifax navigational warning":
            for cell in cells:
                if cell and not ID_RE.search(cell) and not DATE_RE.search(cell) and len(cell) > 5:
                    title = cell
                    break

        link = tr.select_one('a[href*="/message/"]')
        source_url = urljoin(SEARCH_URL, link.get("href")) if link else f"{SEARCH_URL}?q=Halifax&status=PUBLISHED"
        reported = iso_utc(parse_datetime(date_text)) or ""
        by_id[nav_id] = Incident(
            id=f"navwarn-{stable_id(nav_id)}",
            source=SOURCE,
            source_url=source_url,
            title=title,
            summary=row_text[:900],
            category="MARINE",
            subtype="navigational_warning",
            reported_at=reported,
            source_kind="official",
            confidence="official",
            status="active",
            location_text="Halifax Harbour / approaches",
            lat=44.65,
            lon=-63.57,
            location_precision="marine_area",
            severity=_severity(row_text),
            signals=["official_navigational_warning"],
            raw_ids=[nav_id],
            metadata={"navwarn_id": nav_id, "currently_active": True},
        )

    return list(by_id.values())


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(
            SEARCH_URL,
            params={"q": "Halifax", "status": "PUBLISHED", "sortBy": "DATE", "maxHits": 100},
            timeout=25,
        )
        res.raise_for_status()
        return parse_html(res.text)

    return guarded_fetch(
        SOURCE,
        f"{SEARCH_URL}?q=Halifax&status=PUBLISHED",
        "official Canadian Coast Guard",
        run,
        notes="Recent published NAVWARNs mentioning Halifax/Bedford Basin; older standing marine notices are excluded from the incident timeline.",
    )
