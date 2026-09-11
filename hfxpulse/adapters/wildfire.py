from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import DOWNTOWN_CENTER, clean_text, haversine_km, iso_utc, parse_datetime, stable_id

QUERY_URL = "https://services.arcgis.com/txWDfZ2LIgzmw5Ts/ArcGIS/rest/services/cwfis_active_fires_updated_view/FeatureServer/0/query"
SOURCE_URL = "https://cwfis.cfs.nrcan.gc.ca/interactive-map"
SOURCE = "CWFIS active wildfires near Halifax"

# Broad Nova Scotia envelope first, then a Halifax-distance filter.  This keeps
# the collector useful for smoke/emergency context without importing national noise.
NS_BOUNDS = (43.2, 47.2, -66.7, -59.4)  # south, north, west, east
MAX_HALIFAX_DISTANCE_KM = 250.0


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        # CWFIS commonly publishes YYYYMMDD in this view.
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    dt = parse_datetime(text)
    return iso_utc(dt) if dt else None


def _stage(value: str | None) -> tuple[str, str]:
    raw = clean_text(value)
    code = raw.upper().replace("_", " ").strip()
    mapping = {
        "OC": "out of control",
        "OUT OF CONTROL": "out of control",
        "BH": "being held",
        "BEING HELD": "being held",
        "UC": "under control",
        "UNDER CONTROL": "under control",
        "OUT": "out",
    }
    return raw, mapping.get(code, raw.lower() or "active")


def parse_payload(payload: dict, observed_at: datetime | None = None) -> list[Incident]:
    observed_at = observed_at or datetime.now(timezone.utc)
    rows: list[Incident] = []

    for feature in payload.get("features", []):
        attrs = (feature or {}).get("attributes") or {}
        lat = _number(attrs.get("lat"))
        lon = _number(attrs.get("lon"))
        if lat is None or lon is None:
            continue
        south, north, west, east = NS_BOUNDS
        if not (south <= lat <= north and west <= lon <= east):
            continue

        distance = round(haversine_km(lat, lon, *DOWNTOWN_CENTER), 1)
        if distance > MAX_HALIFAX_DISTANCE_KM:
            continue

        raw_stage, stage = _stage(attrs.get("stage_of_control"))
        if stage == "out":
            continue

        name = clean_text(attrs.get("firename")) or f"Active fire #{attrs.get('ObjectId', 'unknown')}"
        agency = clean_text(attrs.get("agency")) or "CWFIS"
        hectares = _number(attrs.get("hectares"))
        response = clean_text(attrs.get("response_type")) or None
        reported = _date(attrs.get("startdate")) or iso_utc(observed_at) or ""

        size_text = f" · {hectares:g} ha" if hectares is not None else ""
        response_text = f" · response {response}" if response else ""
        summary = (
            f"CWFIS lists {name} as {stage}{size_text}, approximately {distance:g} km from downtown Halifax"
            f"{response_text}."
        )
        severity = 3 if stage == "out of control" else 2 if stage == "being held" else 1
        rows.append(Incident(
            id=f"cwfis-{stable_id(agency, name, lat, lon)}",
            source=SOURCE,
            source_url=SOURCE_URL,
            title=f"Wildfire: {name}",
            summary=summary,
            category="EMERGENCY",
            subtype="wildfire_context",
            reported_at=reported,
            source_kind="official",
            confidence="official",
            status="active",
            location_text=f"{name}, Nova Scotia",
            lat=lat,
            lon=lon,
            location_precision="reported_fire_point",
            severity=severity,
            signals=["official_active_wildfire"],
            raw_ids=[str(attrs.get("ObjectId"))] if attrs.get("ObjectId") is not None else [],
            metadata={
                "currently_active": True,
                "agency": agency,
                "stage_of_control": stage,
                "stage_raw": raw_stage,
                "hectares": hectares,
                "response_type": response,
                "distance_km": distance,
                "observed_at": iso_utc(observed_at),
            },
        ))
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(
            QUERY_URL,
            params={
                "where": "1=1",
                "outFields": "agency,firename,lat,lon,startdate,hectares,stage_of_control,response_type,ObjectId",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=25,
        )
        res.raise_for_status()
        payload = res.json()
        if payload.get("error"):
            raise RuntimeError(f"CWFIS ArcGIS query error: {payload['error']}")
        return parse_payload(payload)

    return guarded_fetch(
        SOURCE,
        SOURCE_URL,
        "official federal wildfire data",
        run,
        notes="CWFIS active-fire records within 250 km of downtown Halifax; out/extinguished records are excluded.",
    )
