from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import HALIFAX_TZ, clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.porthalifax.ca/cruise/cruise-schedule/"
SOURCE = "Port of Halifax cruise schedule"


def parse_html(html: str, now: datetime | None = None) -> list[Incident]:
    now = now or datetime.now(HALIFAX_TZ)
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    for tr in soup.select("tr"):
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.select("th,td")]
        if len(cells) < 3:
            continue
        row_text = " | ".join(cells)
        dt = None
        for cell in cells[:2]:
            parsed = parse_datetime(cell)
            if parsed:
                dt = parsed.astimezone(HALIFAX_TZ)
                break
        if not dt or dt.date() != now.date():
            continue
        vessel = cells[1] if len(cells) > 1 else "Cruise vessel"
        passengers = next((c for c in cells if c.replace(",", "").isdigit() and int(c.replace(",", "")) > 100), None)
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
