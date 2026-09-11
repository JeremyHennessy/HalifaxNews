from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, stable_id

SITE_URL = "https://emergencyinfo.novascotia.ca/"
SERVICE = "https://services1.arcgis.com/EmwrhKkmuQhTATzU/ArcGIS/rest/services/EmergencyInformation_public_43a3da8a7cb34bd8894d958fc7f2d44d/FeatureServer/0"
SOURCE = "Emergency Info Nova Scotia"


def _date_ms(value) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return iso_utc(datetime.fromtimestamp(float(value) / 1000.0, timezone.utc))
    except Exception:
        return None


def parse_arcgis(payload: dict) -> list[Incident]:
    rows: list[Incident] = []
    for feature in (payload or {}).get("features", []):
        a = (feature or {}).get("attributes") or {}
        status = clean_text(str(a.get("status") or ""))
        # The source is a public-message view; keep anything not explicitly inactive.
        if status.lower() in {"no", "inactive", "false", "0", "none"}:
            continue
        title = clean_text(str(a.get("incidentnm") or a.get("shortmessage") or "Nova Scotia emergency event"))
        short = clean_text(str(a.get("shortmessage") or ""))
        long = clean_text(str(a.get("longmessage") or ""))
        action = clean_text(str(a.get("actionmessage") or "")) if str(a.get("actionrequired") or "").lower() == "yes" else ""
        summary = " · ".join(x for x in (short, long, action) if x)[:1200]
        reported = _date_ms(a.get("EditDate")) or _date_ms(a.get("CreationDate"))
        if not reported:
            continue
        gid = clean_text(str(a.get("GlobalID") or a.get("OBJECTID") or title))
        url = clean_text(str(a.get("url") or "")) or SITE_URL
        rows.append(Incident(
            id=f"nsemergency-{stable_id(gid, title)}",
            source=SOURCE,
            source_url=url,
            title=title,
            summary=summary or title,
            category="EMERGENCY",
            subtype="active_event",
            reported_at=reported,
            source_kind="official",
            confidence="official",
            severity=3,
            signals=["official_active_event", "provincial_emergency"],
            raw_ids=[gid] if gid else [],
            metadata={"status": status, "action_required": a.get("actionrequired"), "action_message": action},
        ))
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(
            f"{SERVICE}/query",
            params={"f": "json", "where": "1=1", "outFields": "*", "returnGeometry": "false", "orderByFields": "EditDate DESC"},
            timeout=20,
        )
        res.raise_for_status()
        payload = res.json() or {}
        if payload.get("error"):
            raise ValueError(f"ArcGIS query error: {payload['error']}")
        return parse_arcgis(payload)

    return guarded_fetch(
        SOURCE,
        SITE_URL,
        "official",
        run,
        notes="Provincial public-message ArcGIS view; avoids website TLS/rendering failures while preserving the same emergency-information source.",
    )
