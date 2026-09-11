from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.models import Incident
from hfxpulse.util import haversine_km, normalized_place, parse_datetime


def _close_in_time(a: Incident, b: Incident, minutes: int = 60) -> bool:
    da = parse_datetime(a.reported_at)
    db = parse_datetime(b.reported_at)
    if not da or not db:
        return False
    return abs((da - db).total_seconds()) <= minutes * 60


def _close_in_place(a: Incident, b: Incident) -> bool:
    if None not in (a.lat, a.lon, b.lat, b.lon):
        return haversine_km(a.lat, a.lon, b.lat, b.lon) <= 0.8
    pa = normalized_place(a.location_text)
    pb = normalized_place(b.location_text)
    if not pa or not pb:
        return False
    a_tokens = set(pa.split())
    b_tokens = set(pb.split())
    return len(a_tokens & b_tokens) >= 1


def correlate(rows: list[Incident]) -> None:
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a.source == b.source or not _close_in_time(a, b) or not _close_in_place(a, b):
                continue
            a.related_ids.append(b.id)
            b.related_ids.append(a.id)

    by_id = {r.id: r for r in rows}
    for row in rows:
        official_sources = {row.source} if row.source_kind == "official" else set()
        for rid in row.related_ids:
            other = by_id.get(rid)
            if other and other.source_kind == "official":
                official_sources.add(other.source)
        if len(official_sources) >= 2:
            row.confidence = "corroborated"
            if "corroborated_official_sources" not in row.signals:
                row.signals.append("corroborated_official_sources")
