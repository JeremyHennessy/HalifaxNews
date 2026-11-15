from __future__ import annotations

from datetime import datetime
import re

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import HALIFAX_TZ, clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.portofhalifax.ca/cruise/cruise-schedule/"
SOURCE = "Port of Halifax cruise schedule"


def parse_html(html: str, now: datetime | None = None) -> list[Incident]:
    now = now or datetime.now(HALIFAX_TZ)
    soup = BeautifulSoup(html, "html.parser")
    # A 200 denial/error page is not proof there are no scheduled calls.
    tables = []
    for table in soup.select("table"):
        header = table.find("tr")
        labels = [clean_text(cell.get_text(" ", strip=True)).casefold() for cell in header.find_all(["th", "td"], recursive=False)] if header else []
        if len(labels) >= 4 and labels[:4] == ["date", "vessel", "cruise line", "passengers"]:
            tables.append(table)
    if len(tables) != 1:
        raise ValueError("Cruise schedule table missing or ambiguous; coverage unknown")
    rows: list[Incident] = []
    for tr in tables[0].select("tr")[1:]:
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.select("th,td")]
        if not cells:
            continue
        if len(cells) < 4:
            raise ValueError("Malformed cruise schedule row; coverage unknown")
        row_text = " | ".join(cells)
        # Never let the host year silently turn an undated schedule into today.
        if not re.fullmatch(r"(?:[A-Za-z]+\s+\d{1,2},?\s+(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/(?:19|20)\d{2})", cells[0]):
            raise ValueError("Cruise row full calendar date not explicit; coverage unknown")
        dt = parse_datetime(cells[0])
        if dt is None:
            raise ValueError("Cruise row date invalid; coverage unknown")
        dt = dt.astimezone(HALIFAX_TZ)
        if not dt or dt.date() != now.date():
            continue
        vessel = cells[1] if len(cells) > 1 else "Cruise vessel"
        passengers = cells[3] if cells[3].replace(",", "").isdigit() else None
        summary = row_text
        rows.append(Incident(
            id=f"port-cruise-{stable_id(now.date(), vessel, row_text)}",
            source=SOURCE,
            source_url=URL,
            title=f"Cruise ship in Halifax today — {vessel}",
            summary=summary[:700],
            category="MARINE",
            subtype="cruise_call",
            reported_at=iso_utc(now) or "",
            source_kind="event",
            confidence="listing",
            location_text="Halifax waterfront",
            severity=0,
            siren_score=0,
            signals=["port_activity"],
            metadata={"passengers": passengers} if passengers else {},
        ))
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        return parse_html(res.text)
    return guarded_fetch(SOURCE, URL, "official schedule", run, notes="Same-day cruise calls provide crowd/traffic context; they are not emergency incidents.")