from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, infer_siren_score, iso_utc, parse_datetime, stable_id

ITEM_ID = "60335557a750440db720c2b791a4b2a4"
ITEM_URL = f"https://www.arcgis.com/sharing/rest/content/items/{ITEM_ID}?f=json"
PUBLIC_URL = "https://data-hrm.hub.arcgis.com/datasets/HRM::hrfe-incident-initial-response"
SOURCE = "HRFE Incident Initial Response · Open Data"


def _field(fields: list[dict], *needles: str) -> str | None:
    for f in fields:
        hay = f"{f.get('name','')} {f.get('alias','')}".lower().replace("_", " ")
        if all(n.lower() in hay for n in needles):
            return f.get("name")
    return None


def _as_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, timezone.utc)
        except Exception:
            return None
    return parse_datetime(str(value))


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        s = session()
        item = s.get(ITEM_URL, timeout=20)
        item.raise_for_status()
        service_url = (item.json() or {}).get("url")
        if not service_url:
            raise ValueError("ArcGIS item did not expose a feature-service URL")
        schema_res = s.get(f"{service_url.rstrip('/')}/0", params={"f": "json"}, timeout=20)
        schema_res.raise_for_status()
        schema = schema_res.json() or {}
        fields = schema.get("fields") or []
        object_id = schema.get("objectIdField") or _field(fields, "object") or "OBJECTID"
        incident_no = _field(fields, "incident", "number") or _field(fields, "incident", "no")
        street = _field(fields, "street") or _field(fields, "location")
        incident_type = _field(fields, "incident", "type") or _field(fields, "type")
        date_f = _field(fields, "incident", "date") or _field(fields, "date")
        time_f = _field(fields, "incident", "time") or _field(fields, "time")
        response_f = _field(fields, "initial", "response") or _field(fields, "response")
        query = s.get(
            f"{service_url.rstrip('/')}/0/query",
            params={
                "f": "json", "where": "1=1", "outFields": "*", "returnGeometry": "true",
                "orderByFields": f"{object_id} DESC", "resultRecordCount": 200,
            },
            timeout=25,
        )
        query.raise_for_status()
        payload = query.json() or {}
        if payload.get("error"):
            raise ValueError(f"ArcGIS query error: {payload['error']}")
        rows: list[Incident] = []
        for feature in payload.get("features", []):
            a = feature.get("attributes") or {}
            dt = _as_dt(a.get(date_f)) if date_f else None
            if not dt and time_f:
                dt = _as_dt(a.get(time_f))
            if not dt:
                continue
            number = clean_text(str(a.get(incident_no) or "")) if incident_no else ""
            loc = clean_text(str(a.get(street) or "")) if street else ""
            kind = clean_text(str(a.get(incident_type) or "Incident")) if incident_type else "Incident"
            response = clean_text(str(a.get(response_f) or "")) if response_f else ""
            reported = iso_utc(dt) or ""
            upper = kind.upper()
            category = "RESCUE" if any(k in upper for k in ("COLLISION", "MVC", "RESCUE")) else "EMS" if "MEDICAL" in upper else "FIRE"
            geom = feature.get("geometry") or {}
            lon = geom.get("x")
            lat = geom.get("y")
            if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and 44.0 <= float(lat) <= 45.3 and -64.5 <= float(lon) <= -62.5):
                lat = lon = None
            rows.append(Incident(
                id=f"hrfe-open-{stable_id(number or a.get(object_id), loc, kind)}",
                source=SOURCE,
                source_url=PUBLIC_URL,
                title=kind,
                summary=f"{kind}{f' · {loc}' if loc else ''}{f' · Initial response: {response}' if response else ''}",
                category=category,
                subtype=kind,
                reported_at=reported,
                source_kind="official_archive",
                confidence="official",
                location_text=loc or None,
                lat=float(lat) if isinstance(lat, (int, float)) else None,
                lon=float(lon) if isinstance(lon, (int, float)) else None,
                location_precision="source_geometry" if lat is not None and lon is not None else None,
                severity=2,
                siren_score=infer_siren_score(category, kind, reported, {"response": response}),
                signals=["official_open_data", "post_incident_enrichment"],
                raw_ids=[number] if number else [],
                metadata={"response": response, "timestamp_note": "HRM documents a display-time offset issue on this dataset; source timestamp is preserved without correction."},
            ))
        return rows

    return guarded_fetch(
        SOURCE,
        PUBLIC_URL,
        "official open data",
        run,
        notes="Periodic HRFE open-data layer used as a second incident source/enrichment path. Source timestamps are preserved; no guessed offset correction is applied.",
    )
