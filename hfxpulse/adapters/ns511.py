from __future__ import annotations

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://511.novascotia.ca/list/events/traffic"
SOURCE = "511 Nova Scotia"
HRM_TERMS = (
    "halifax", "dartmouth", "bedford", "sackville", "timberlea", "tantallon", "hammonds plains",
    "highway 111", "highway 102", "circumferential", "macdonald bridge", "mackay bridge"
)


def parse_text_report(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    for table in soup.find_all("table"):
        headers = [clean_text(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
        if not {"type", "roadway", "description"}.issubset(set(headers)):
            continue
        for tr in table.find_all("tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            if len(cells) < 3:
                continue
            data = dict(zip(headers, cells))
            kind = data.get("type", "Traffic event")
            roadway = data.get("roadway", "")
            desc = data.get("description", "")
            combined = f"{roadway} {desc}".lower()
            if not any(term in combined for term in HRM_TERMS):
                continue
            when = data.get("last updated") or data.get("start time")
            dt = parse_datetime(when)
            if not dt:
                continue
            summary = " · ".join(x for x in (roadway, desc) if x)
            rows.append(
                Incident(
                    id=f"511-{stable_id(kind, roadway, desc, data.get('start time'))}",
                    source=SOURCE,
                    source_url=URL,
                    title=f"{kind}: {roadway}" if roadway else kind,
                    summary=summary,
                    category="TRAFFIC",
                    subtype=kind.lower().replace(" ", "_"),
                    reported_at=iso_utc(dt) or "",
                    location_text=roadway or None,
                    severity=2,
                    signals=["official_road_event"],
                    metadata={"start_time": data.get("start time"), "anticipated_end": data.get("anticipated end time")},
                )
            )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        page_text = clean_text(soup.get_text(" ", strip=True)).lower()
        if "traffic events" not in page_text:
            raise ValueError("511 traffic text-report page did not contain the expected Traffic Events heading")
        return parse_text_report(res.text)

    return guarded_fetch(
        SOURCE,
        URL,
        "official",
        run,
        notes="Official traffic-event text report. Zero parsed rows can legitimately mean there are no listed HRM traffic events at collection time.",
    )
