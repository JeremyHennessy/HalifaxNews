from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, stable_id

SERVICE = "https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/ArcGIS/rest/services/Street_Closures_Active/FeatureServer/0"
PUBLIC_URL = "https://catalogue-hrm.opendata.arcgis.com/"
SOURCE = "HRM active street closures"


def _dt_ms(value):
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, timezone.utc)
    except Exception:
        return None


def parse_payload(payload: dict, now: datetime | None = None) -> list[Incident]:
    now = now or datetime.now(timezone.utc)
    rows: list[Incident] = []
    for feature in (payload or {}).get("features", []):
        a = (feature or {}).get("attributes") or {}
        street = clean_text(str(a.get("STREET_NAME") or ""))
        from_st = clean_text(str(a.get("FROM_STR") or ""))
        to_st = clean_text(str(a.get("TO_STR") or ""))
        if not street:
            continue
        start = _dt_ms(a.get("START_DATE"))
        end = _dt_ms(a.get("END_DATE"))
        # Layer is advertised as active, but honour explicit future/expired dates if present.
        if start and start > now:
            continue
        if end and end < now:
            continue
        modified = _dt_ms(a.get("MODDATE")) or _dt_ms(a.get("ADDDATE")) or start or now
        closure_type = clean_text(str(a.get("CLOSURE_TYPE") or "Street closure"))
        stage = clean_text(str(a.get("CLOSURE_STAGE") or ""))
        comments = clean_text(str(a.get("COMMENTS") or ""))
        permit = clean_text(str(a.get("PERMIT_NO") or ""))
        location = street
        if from_st and to_st:
            location = f"{street} — {from_st} to {to_st}"
        elif from_st:
            location = f"{street} at {from_st}"
        bits = [closure_type]
        if stage:
            bits.append(stage)
        if comments:
            bits.append(comments)
        if a.get("START_TIME") or a.get("END_TIME"):
            bits.append(f"Time: {clean_text(str(a.get('START_TIME') or ''))}–{clean_text(str(a.get('END_TIME') or ''))}")
        oid = a.get("GLOBALID") or a.get("OBJECTID") or f"{street}-{permit}"
        rows.append(Incident(
            id=f"hrm-closure-{stable_id(oid)}",
            source=SOURCE,
            source_url=PUBLIC_URL,
            title=f"Active street closure — {street}",
            summary=" · ".join(x for x in bits if x)[:900],
            category="TRAFFIC",
            subtype=closure_type or "street_closure",
            reported_at=iso_utc(modified) or iso_utc(now) or "",
            source_kind="official",
            confidence="official",
            status="active",
            location_text=location,
            severity=1,
            siren_score=0,
            signals=["active_street_closure", "planned_or_permitted_road_impact"],
            raw_ids=[str(permit or oid)],
            metadata={
                "currently_active": True,
                "closure_stage": stage,
                "permit_no": permit,
                "start_at": iso_utc(start) if start else None,
                "end_at": iso_utc(end) if end else None,
                "detour_url": a.get("DETOUR_URL"),
            },
        ))
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(
            f"{SERVICE}/query",
            params={"f": "json", "where": "1=1", "outFields": "*", "returnGeometry": "false", "orderByFields": "MODDATE DESC"},
            timeout=20,
        )
        res.raise_for_status()
        payload = res.json() or {}
        if payload.get("error"):
            raise ValueError(f"ArcGIS query error: {payload['error']}")
        return parse_payload(payload)

    return guarded_fetch(
        SOURCE,
        SERVICE,
        "official open data",
        run,
        notes="HRM's active planned/permitted street-closure layer. Useful context for blocked roads and unusual response routing; not an emergency feed.",
    )
