from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, stable_id

# Secondary public read-only aggregator. The official NSP outage map remains the evidence link.
URL = "https://outagemap.hfxdeploy.com/api/outages"
OFFICIAL_URL = "https://outagemap.nspower.ca/external/default.html"
SOURCE = "Nova Scotia Power outages"
CORE_TERMS = ("downtown", "halifax peninsula", "south end", "north end", "spring garden", "barrington", "waterfront")
SAFETY_CAUSES = ("vehicle", "collision", "fire", "emergency", "public safety", "police", "storm", "tree on line")


def _iter_outages(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("outages", "data", "features", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def _customer_count(value) -> int:
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = clean_text(str(value or "")).replace(",", "")
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else 0


def parse_payload(payload, min_customers: int | None = None) -> list[Incident]:
    rows: list[Incident] = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    threshold = min_customers if min_customers is not None else int(os.getenv("HFXPULSE_POWER_MIN_CUSTOMERS", "100"))
    for item in _iter_outages(payload):
        props = item.get("properties", item) if isinstance(item, dict) else {}
        area = clean_text(str(props.get("area") or props.get("location") or props.get("municipality") or props.get("region") or ""))
        area_lower = area.lower()
        if area and not any(place in area_lower for place in ("halifax", "dartmouth", "bedford", "sackville", "timberlea", "spryfield")):
            continue
        customers_raw = props.get("customers") or props.get("customersAffected") or props.get("custs")
        customers = _customer_count(customers_raw)
        cause = clean_text(str(props.get("cause") or "Cause under investigation"))
        cause_lower = cause.lower()
        core = any(term in area_lower for term in CORE_TERMS)
        safety_related = any(term in cause_lower for term in SAFETY_CAUSES)
        # HFX Pulse is an incident-intelligence app, not an outage-map clone.
        # Keep broad/significant outages and safety-related outages; suppress tiny routine clusters.
        if customers < threshold and not safety_related and not (core and customers >= max(25, threshold // 2)):
            continue
        oid = str(props.get("id") or props.get("outageId") or stable_id(area, customers, cause))
        lat = props.get("lat") or props.get("latitude")
        lon = props.get("lon") or props.get("longitude")
        try:
            lat = float(lat) if lat is not None else None
            lon = float(lon) if lon is not None else None
        except (TypeError, ValueError):
            lat = lon = None
        summary = cause
        if customers:
            summary = f"{customers:,} customers affected · {cause}"
        rows.append(
            Incident(
                id=f"nsp-{stable_id(oid)}",
                source=SOURCE,
                source_url=OFFICIAL_URL,
                title=f"Power outage{f' — {area}' if area else ''}",
                summary=summary,
                category="UTILITY",
                subtype="power_outage",
                reported_at=now,
                location_text=area or None,
                lat=lat,
                lon=lon,
                location_precision="outage_area" if lat is not None else None,
                severity=2,
                signals=["secondary_machine_feed", "official_map_available", "impact_threshold_passed"],
                raw_ids=[oid],
                metadata={"secondary_feed": URL, "customers": customers, "cause": cause, "minimum_customers": threshold},
            )
        )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=20)
        res.raise_for_status()
        return parse_payload(res.json())

    result = guarded_fetch(
        SOURCE,
        URL,
        "secondary",
        run,
        notes="Machine-readable helper linked to the official NSP map. Routine small outages are suppressed; threshold defaults to 100 customers.",
    )
    for row in result.incidents:
        row.source_kind = "secondary"
        row.confidence = "secondary"
    return result
