from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, stable_id

# Secondary public read-only aggregator. The official NSP outage map remains the evidence link.
URL = "https://outagemap.hfxdeploy.com/api/outages"
OFFICIAL_URL = "https://outagemap.nspower.ca/external/default.html"
SOURCE = "Nova Scotia Power outages"


def _iter_outages(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("outages", "data", "features", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def parse_payload(payload) -> list[Incident]:
    rows: list[Incident] = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for item in _iter_outages(payload):
        props = item.get("properties", item) if isinstance(item, dict) else {}
        area = clean_text(str(props.get("area") or props.get("location") or props.get("municipality") or props.get("region") or ""))
        if area and "halifax" not in area.lower() and "dartmouth" not in area.lower() and "bedford" not in area.lower():
            continue
        customers = props.get("customers") or props.get("customersAffected") or props.get("custs")
        cause = clean_text(str(props.get("cause") or "Cause under investigation"))
        oid = str(props.get("id") or props.get("outageId") or stable_id(area, customers, cause))
        lat = props.get("lat") or props.get("latitude")
        lon = props.get("lon") or props.get("longitude")
        try:
            lat = float(lat) if lat is not None else None
            lon = float(lon) if lon is not None else None
        except (TypeError, ValueError):
            lat = lon = None
        summary = cause
        if customers is not None:
            summary = f"{customers} customers affected · {cause}"
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
                signals=["secondary_machine_feed", "official_map_available"],
                raw_ids=[oid],
                metadata={"secondary_feed": URL, "customers": customers, "cause": cause},
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
        notes="Read-only community API used only as a machine-readable helper. Incident cards link to the official Nova Scotia Power outage map.",
    )
    for row in result.incidents:
        row.source_kind = "secondary"
        row.confidence = "secondary"
    return result
