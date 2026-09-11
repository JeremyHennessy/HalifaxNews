from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import HALIFAX_TZ, clean_text, infer_category, iso_utc, stable_id

URL = "https://www.smu.ca/alert/"
SOURCE = "Saint Mary's University alerts"
LOCATION = "Saint Mary's University, Halifax"
NORMAL_PHRASES = (
    "saint mary's is operating as usual",
    "saint mary’s is operating as usual",
    "operating as usual",
)


def parse_html(html: str, now: datetime | None = None) -> list[Incident]:
    now = now or datetime.now(HALIFAX_TZ)
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    text = clean_text(main.get_text(" ", strip=True))
    lower = text.lower()
    if any(phrase in lower for phrase in NORMAL_PHRASES):
        return []

    # Pick the first meaningful alert/status heading rather than navigation or signup copy.
    ignored = {"alert information", "announcement channels", "smu channels", "homburg centre channels"}
    title = "Saint Mary's operational alert"
    for node in main.find_all(["h1", "h2", "h3"]):
        candidate = clean_text(node.get_text(" ", strip=True))
        if not candidate or candidate.lower() in ignored:
            continue
        if any(term in candidate.lower() for term in ("alert", "closed", "closure", "cancel", "delay", "emergency", "weather", "security", "evac")):
            title = candidate
            break

    summary = text[:900]
    category = infer_category(f"{title} {summary}", "EMERGENCY")
    if category == "COMMUNITY":
        category = "EMERGENCY"
    reported = iso_utc(now) or ""
    return [Incident(
        id=f"smu-alert-{stable_id(title, summary[:240])}",
        source=SOURCE,
        source_url=URL,
        title=title,
        summary=summary,
        category=category,
        subtype="campus_operational_alert",
        reported_at=reported,
        source_kind="official",
        confidence="official",
        status="active",
        location_text=LOCATION,
        lat=44.6307,
        lon=-63.5786,
        location_precision="campus",
        severity=3 if any(term in lower for term in ("emergency", "evacuation", "security incident", "shelter in place")) else 2,
        signals=["official_campus_alert"],
        metadata={"currently_active": True, "observed_status_at": reported, "source_timestamp_missing": True},
    )]


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
        notes="Saint Mary's current closure/interruption page; normal operating status produces zero events.",
    )
