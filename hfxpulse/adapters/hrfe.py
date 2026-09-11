from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, infer_siren_score, iso_utc, parse_datetime, stable_id

URL = "https://www.halifax.ca/safety-security/fire-emergency/hrfe-incident-feed"
SOURCE = "Halifax Regional Fire & Emergency"

# The feed has changed presentation over time. Parse the stable public labels instead of DOM classes.
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


def parse_hrfe_text(text: str) -> list[Incident]:
    text = clean_text(text)
    rows: list[Incident] = []
    for match in BLOCK_RE.finditer(text):
        kind = clean_text(match.group("type")).upper()
        location = clean_text(match.group("location")).upper()
        call = clean_text(match.group("call")).upper()
        response = clean_text(match.group("response")).upper()
        dt = parse_datetime(match.group("date"))
        reported_at = iso_utc(dt)
        if not reported_at:
            continue
        category = _category(kind)
        metadata = {"call_number": call, "response": response}
        row = Incident(
            id=f"hrfe-{call.lower()}",
            source=SOURCE,
            source_url=f"{URL}#{call}",
            title=kind.title(),
            summary=f"{location} · Responding: {response}",
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
        rows.append(row)
    # De-duplicate on call number in case mobile/desktop markup repeats content.
    return list({r.id: r for r in rows}.values())


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        # Drop scripts/styles so embedded labels do not get polluted by JS strings.
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        rows = parse_hrfe_text(soup.get_text(" ", strip=True))
        if not rows:
            raise ValueError("HRFE page fetched but no incident blocks matched the expected public labels")
        return rows

    return guarded_fetch(
        SOURCE,
        URL,
        "official",
        run,
        notes="Official dispatch feed. Location is intentionally street/intersection level, not an exact person location.",
    )
