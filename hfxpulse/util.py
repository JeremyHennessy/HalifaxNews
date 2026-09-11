from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser

HALIFAX_TZ = ZoneInfo("America/Halifax")
DOWNTOWN_CENTER = (44.6488, -63.5752)


def stable_id(*parts: object) -> str:
    joined = "|".join(str(p or "").strip().lower() for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:18]


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def parse_datetime(value: str | None, default_tz=HALIFAX_TZ) -> datetime | None:
    if not value:
        return None
    text = clean_text(value)
    for fn in (date_parser.parse, parsedate_to_datetime):
        try:
            dt = fn(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=default_tz)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371.0
    p1 = math.radians(a_lat)
    p2 = math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def normalized_place(text: str | None) -> str:
    if not text:
        return ""
    value = text.upper()
    value = re.sub(r"\b(HALIFAX|DARTMOUTH|NOVA SCOTIA|NS)\b", "", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    stop = {"ST", "STREET", "RD", "ROAD", "AVE", "AVENUE", "DR", "DRIVE", "BLVD", "LANE", "LN"}
    tokens = [t for t in value.split() if t and t not in stop]
    return " ".join(tokens[:8])


def apparatus_count(response: str | None) -> int:
    if not response:
        return 0
    tokens = [t for t in re.split(r"\s+", response.strip()) if t]
    # Station markers are not responding apparatus.
    return len([t for t in tokens if not t.upper().startswith("STN")])


def infer_siren_score(category: str, subtype: str | None, reported_at: str, metadata: dict | None = None) -> int:
    subtype_u = (subtype or "").upper()
    category_u = category.upper()
    score = 0
    if category_u in {"FIRE", "RESCUE", "EMS"}:
        score += 30
    if "STRUCTURE" in subtype_u:
        score += 35
    elif "COLLISION" in subtype_u or "MVC" in subtype_u:
        score += 28
    elif "RESCUE" in subtype_u:
        score += 26
    elif "HAZMAT" in subtype_u:
        score += 22
    elif "VEHICLE FIRE" in subtype_u or "OUTSIDE FIRE" in subtype_u:
        score += 20
    elif "ALARM" in subtype_u:
        score += 15
    elif "MEDICAL" in subtype_u:
        score += 10
    elif "INVESTIGATION" in subtype_u:
        score += 6

    response = (metadata or {}).get("response")
    score += min(20, apparatus_count(response) * 4)

    dt = parse_datetime(reported_at)
    if dt:
        age_m = max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 60)
        if age_m <= 15:
            score += 18
        elif age_m <= 45:
            score += 12
        elif age_m <= 90:
            score += 6
    return min(100, score)


def keyword_hit(text: str, words: Iterable[str]) -> bool:
    u = text.upper()
    return any(w.upper() in u for w in words)
