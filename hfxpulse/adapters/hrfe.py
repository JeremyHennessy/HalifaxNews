from __future__ import annotations

import re
from datetime import datetime
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, infer_siren_score, iso_utc, parse_datetime, stable_id

URL = "https://www.halifax.ca/safety-security/fire-emergency/hrfe-incident-feed"
RSS_URL = f"{URL}/rss.xml"
SOURCE = "Halifax Regional Fire & Emergency"

# Historical HTML/text fallback. The official page has changed presentation over time,
# so the live fetch path uses its advertised RSS feed instead of depending on DOM order.
BLOCK_RE = re.compile(
    r"(?P<type>[A-Z][A-Z /&-]{2,50})\s+"
    r"Location:\s*(?P<location>.+?)\s+"
    r"Call Number:\s*(?P<call>HF\d+)\s+"
    r"Response:\s*(?P<response>.+?)\s+"
    r"(?P<date>(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
    re.I | re.S,
)


def _category(kind: str) -> str:
    k = kind.upper()
    if "MEDICAL" in k:
        return "EMS"
    if any(w in k for w in ("COLLISION", "RESCUE")):
        return "RESCUE"
    return "FIRE"


def _incident(kind: str, location: str, call: str, response: str, reported_at: str, source_url: str) -> Incident:
    kind = clean_text(kind).upper()
    location = clean_text(location).upper()
    call = clean_text(call).upper()
    response = clean_text(response).upper()
    category = _category(kind)
    metadata = {"call_number": call, "response": response}
    summary = location
    if response:
        summary += f" · Responding: {response}"
    row = Incident(
        id=f"hrfe-{call.lower()}",
        source=SOURCE,
        source_url=source_url or f"{URL}#{call}",
        title=kind.title(),
        summary=summary,
        category=category,
        subtype=kind,
        reported_at=reported_at,
        location_text=location,
        location_precision="street_or_intersection",
        severity=3 if "STRUCTURE" in kind else 2,
        signals=["official_dispatch", "responding_units"],
        raw_ids=[call],
        metadata=metadata,
    )
    row.siren_score = infer_siren_score(row.category, row.subtype, row.reported_at, metadata)
    return row


def parse_hrfe_text(text: str) -> list[Incident]:
    text = clean_text(text)
    rows: list[Incident] = []
    for match in BLOCK_RE.finditer(text):
        dt = parse_datetime(match.group("date"))
        reported_at = iso_utc(dt)
        if not reported_at:
            continue
        call = clean_text(match.group("call")).upper()
        rows.append(
            _incident(
                match.group("type"),
                match.group("location"),
                call,
                match.group("response"),
                reported_at,
                f"{URL}#{call}",
            )
        )
    return list({r.id: r for r in rows}.values())


def _description_field(description: str, label: str, next_labels: tuple[str, ...]) -> str:
    stops = "|".join(re.escape(value) for value in next_labels)
    pattern = rf"{re.escape(label)}\s*(.+?)(?=\s+(?:{stops})\s*|$)"
    match = re.search(pattern, description, re.I | re.S)
    return clean_text(match.group(1)) if match else ""


def parse_hrfe_rss(data: bytes | str) -> list[Incident]:
    root = ET.fromstring(data)
    rows: list[Incident] = []
    for item in root.findall(".//item"):
        kind = clean_text(item.findtext("title")).upper()
        description_raw = item.findtext("description") or ""
        description = BeautifulSoup(description_raw, "html.parser").get_text(" ", strip=True)
        guid = clean_text(item.findtext("guid")).upper()
        link = clean_text(item.findtext("link"))
        published = clean_text(item.findtext("pubDate"))

        location = _description_field(description, "Location:", ("Call Number:", "Response:"))
        call = _description_field(description, "Call Number:", ("Response:", "Location:"))
        response = _description_field(description, "Response:", ("Location:", "Call Number:"))
        if not call and re.fullmatch(r"HF\d+", guid, re.I):
            call = guid

        call = clean_text(call).upper()
        dt = parse_datetime(published)
        reported_at = iso_utc(dt)
        if not (kind and location and re.fullmatch(r"HF\d+", call, re.I) and reported_at):
            continue

        rows.append(_incident(kind, location, call, response, reported_at, link or f"{URL}#{call}"))

    return list({r.id: r for r in rows}.values())


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(RSS_URL, timeout=25)
        res.raise_for_status()
        rows = parse_hrfe_rss(res.content)
        if not rows:
            raise ValueError("HRFE RSS fetched but no complete incident items were parsed")
        return rows

    return guarded_fetch(
        SOURCE,
        URL,
        "official",
        run,
        notes="Official HRFE RSS dispatch feed. Location is intentionally street/intersection level, not an exact person location.",
    )
