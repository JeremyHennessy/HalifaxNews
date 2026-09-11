from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import HALIFAX_TZ, clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.porthalifax.ca/cruise/cruise-schedule/"
FALLBACK_URL = "https://www.portofhalifax.ca/cruise/cruise-schedule/"
SOURCE = "Port of Halifax cruise schedule"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36 HFXPulse/0.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
    "Cache-Control": "no-cache",
}


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
                # The official schedule often publishes MM-DD without a year.
                if len(cell) <= 5 and cell.replace("-", "").isdigit():
                    dt = dt.replace(year=now.year)
                break
        if not dt or dt.date() != now.date():
            continue
        vessel = cells[1] if len(cells) > 1 else "Cruise vessel"
        passengers = next((c for c in cells if c.replace(",", "").isdigit() and int(c.replace(",", "")) > 100), None)
        rows.append(Incident(
            id=f"port-cruise-{stable_id(now.date(), vessel, row_text)}",
            source=SOURCE,
            source_url=URL,
            title=f"Cruise ship in Halifax today — {vessel}",
            summary=row_text[:700],
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
        errors: list[str] = []
        for url in (URL, FALLBACK_URL):
            try:
                s = session()
                s.headers.update(BROWSER_HEADERS)
                res = s.get(url, timeout=25, allow_redirects=True)
                res.raise_for_status()
                rows = parse_html(res.text)
                return rows
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
        raise RuntimeError("; ".join(errors))

    return guarded_fetch(
        SOURCE,
        URL,
        "official schedule",
        run,
        notes="Official Port of Halifax same-day cruise calls provide crowd/traffic context; they are event context, not emergency incidents. Current and legacy official hosts are tried independently.",
    )
