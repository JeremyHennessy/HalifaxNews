from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, stable_id

URL = "https://www.nshealth.ca/service-statuses-closures-and-cancellations"
SOURCE = "Nova Scotia Health · urban HRM service disruptions"
STATUS_MARKERS = {"disruption", "advisory", "emergency notice"}
LOCALITY_RE = re.compile(r"^\(([^()]+),\s*NS\)$", re.I)
URBAN_HRM_TERMS = (
    "halifax", "dartmouth", "bedford", "lower sackville", "sackville", "cole harbour",
    "eastern passage", "timberlea", "tantallon", "fall river", "hammonds plains", "spryfield",
)


def _is_urban_hrm(locality: str, facility: str) -> bool:
    text = f"{locality} {facility}".lower()
    return any(term in text for term in URBAN_HRM_TERMS)


def _status_blocks(html: str) -> list[dict]:
    """Parse the public status list using its text sequence, independent of CSS classes."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    tokens = [clean_text(value) for value in main.stripped_strings if clean_text(value)]
    starts = [i for i, token in enumerate(tokens) if token.lower() in STATUS_MARKERS]
    rows: list[dict] = []

    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else min(len(tokens), start + 80)
        block = tokens[start:end]
        locality_index = None
        locality = None
        for idx, token in enumerate(block[1:15], start=1):
            match = LOCALITY_RE.match(token)
            if match:
                locality_index = idx
                locality = clean_text(match.group(1))
                break
        if locality_index is None or not locality:
            continue
        facility = clean_text(block[locality_index - 1]) if locality_index >= 2 else ""
        if not facility:
            continue
        service = clean_text(block[locality_index + 1]) if locality_index + 1 < len(block) else "Health service"
        body = block[locality_index + 2:]
        # Footer / navigation text can trail the last card. It is harmless but not useful.
        trimmed: list[str] = []
        for token in body:
            if token.lower().startswith("for emergencies, call") or token.lower() == "back to top":
                break
            trimmed.append(token)
        description = clean_text(" ".join(trimmed))
        rows.append({
            "status": block[0].title(),
            "facility": facility,
            "locality": locality,
            "service": service or "Health service",
            "description": description,
        })
    return rows


def parse_html(html: str, observed_at: datetime | None = None) -> list[Incident]:
    observed_at = observed_at or datetime.now(timezone.utc)
    reported = iso_utc(observed_at) or ""
    incidents: list[Incident] = []

    for item in _status_blocks(html):
        if not _is_urban_hrm(item["locality"], item["facility"]):
            continue
        text = clean_text(
            f"{item['status']} · {item['facility']} · {item['service']} · {item['description']}"
        )
        lower = text.lower()
        emergency_department = "emergency department" in lower or "urgent care" in lower
        closure = any(term in lower for term in ("closed", "closure", "cancelled", "canceled", "unavailable"))
        severity = 3 if emergency_department and closure else 2
        title = f"{item['facility']} — {item['service']} {item['status'].lower()}"
        incidents.append(Incident(
            id=f"nshealth-status-{stable_id(item['facility'], item['service'], text)}",
            source=SOURCE,
            source_url=URL,
            title=title,
            summary=text[:1000],
            category="EMS",
            subtype="health_service_disruption",
            reported_at=reported,
            source_kind="official",
            confidence="official",
            status="active",
            location_text=f"{item['facility']}, {item['locality']}, NS",
            severity=severity,
            siren_score=0,
            signals=["official_health_service_status"],
            metadata={
                "currently_active": True,
                "facility": item["facility"],
                "locality": item["locality"],
                "service": item["service"],
                "status_type": item["status"],
                "observed_status_at": reported,
                "source_timestamp_missing": True,
            },
        ))
    return incidents


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        all_rows = _status_blocks(res.text)
        # The live page normally publishes a count. If it says statuses exist but
        # our generic parser sees none, fail visibly rather than emit a false zero.
        page_text = clean_text(BeautifulSoup(res.text, "html.parser").get_text(" ", strip=True))
        count_match = re.search(r"\b(\d+)\s+Service Status(?:es)?", page_text, re.I)
        if count_match and int(count_match.group(1)) > 0 and not all_rows:
            raise ValueError("Nova Scotia Health lists active statuses but none could be parsed")
        return parse_html(res.text)

    return guarded_fetch(
        SOURCE,
        URL,
        "official",
        run,
        notes="Current Nova Scotia Health disruptions/advisories filtered to urban HRM facilities; provincial non-HRM closures are excluded.",
    )
