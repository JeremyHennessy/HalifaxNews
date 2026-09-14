from __future__ import annotations

import copy
import html
import re
from datetime import datetime, timezone

from hfxpulse.models import Incident
from hfxpulse.unit_decode import build_response_summary, decode_response, decoded_unit_text
from hfxpulse.util import clean_text, haversine_km, infer_category, normalized_place, parse_datetime, stable_id

CATEGORIES = {
    "FIRE", "RESCUE", "EMS", "POLICE", "TRAFFIC", "TRANSIT", "UTILITY",
    "WEATHER", "EMERGENCY", "EVENT", "MARINE", "COMMUNITY",
}

SOURCE_CLASS_ALIASES = {
    "official": "first_party",
    "official_archive": "first_party",
    "first-party": "first_party",
    "first_party": "first_party",
    "news": "news",
    "reported": "news",
    "community": "community",
    "secondary": "secondary",
    "automated": "secondary",
    "listing": "listing",
    "event": "listing",
}

NEIGHBOURHOODS = {
    "DOWNTOWN": ("BARRINGTON", "ARGYLE", "GRANVILLE", "HOLLIS", "LOWER WATER", "SPRING GARDEN", "SACKVILLE", "DUKE", "GEORGE", "SCOTIA SQUARE", "PURDYS", "PURDY"),
    "NORTH END": ("GOTTINGEN", "AGRICOLA", "NORTH ST", "HYDROSTONE", "ALMON", "YOUNG ST"),
    "SOUTH END": ("SOUTH PARK", "INGLIS", "MORRIS", "UNIVERSITY", "YOUNG AVE", "POINT PLEASANT"),
    "WEST END": ("QUINPOOL", "OXFORD", "CONNAUGHT", "CHEBUCTO"),
    "DARTMOUTH": ("DARTMOUTH", "ALDERNEY", "PORTLAND ST", "WYSE", "DARTMOUTH CROSSING"),
}

PUBLIC_SAFETY_TERMS = (
    "collision", "crash", "fire", "smoke", "emergency", "hospital", "traffic light",
    "traffic signal", "bridge", "police", "evacuation", "critical infrastructure",
)


def _strip_html(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(text)


def _term(text: str, value: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(value.lower())}(?!\w)", text.lower()))


def source_class(row: Incident) -> str:
    raw = clean_text(row.source_kind).lower().replace(" ", "_")
    if raw in SOURCE_CLASS_ALIASES:
        return SOURCE_CLASS_ALIASES[raw]
    conf = clean_text(row.confidence).lower()
    if conf in {"official", "corroborated"}:
        return "first_party"
    if conf == "reported":
        return "news"
    if conf == "listing":
        return "listing"
    if conf == "unverified":
        return "community"
    return "secondary"


def event_type(row: Incident) -> str:
    category = row.category.upper()
    if category == "EVENT" or source_class(row) == "listing":
        return "public_event"
    text = " ".join(filter(None, (row.title, row.summary, row.subtype or "", row.location_text or ""))).lower()
    phrase_rules = (
        ("evacuation", ("evacuation", "evacuate", "shelter in place")),
        ("structure_fire", ("structure fire", "building fire", "apartment fire")),
        ("fire_alarm", ("alarm activation", "alarm sounding", "alarms")),
        ("hazmat", ("hazmat", "gas leak", "chemical spill", "propane leak")),
        ("water_rescue", ("water rescue", "salt water incident", "fresh water incident", "person in water", "missing swimmer", "drowning")),
        ("collision", ("collision", "crash", "mvc", "rollover", "vehicle collision")),
        ("shooting", ("shooting", "shots fired", "gunshot")),
        ("weapon_incident", ("weapon", "armed person", "stabbing")),
        ("road_closure", ("road closed", "road closure", "full closure", "street closure", "bridge closed")),
        ("power_outage", ("power outage", "without power", "customers affected")),
        ("water_disruption", ("water main", "water outage", "boil water", "water service")),
        ("weather_warning", ("warning", "watch", "storm surge", "hurricane", "thunderstorm")),
        ("transit_disruption", ("detour", "route cancelled", "route canceled", "service disruption", "ferry")),
    )
    for label, terms in phrase_rules:
        if any(term in text for term in terms):
            return label
    if any(_term(text, token) for token in ("ert", "swat")) or any(term in text for term in ("tactical", "barricaded", "police operation")):
        return "police_operation"
    defaults = {
        "FIRE": "fire_incident", "RESCUE": "rescue_incident", "EMS": "medical_response",
        "POLICE": "police_incident", "TRAFFIC": "traffic_disruption", "TRANSIT": "transit_disruption",
        "UTILITY": "utility_disruption", "WEATHER": "weather_alert", "EMERGENCY": "public_emergency",
        "EVENT": "public_event", "MARINE": "marine_activity", "COMMUNITY": "community_report",
    }
    return defaults.get(category, "local_signal")


def infer_neighbourhood(row: Incident) -> str | None:
    text = f"{row.location_text or ''} {row.title or ''} {row.summary or ''}".upper()
    for name, terms in NEIGHBOURHOODS.items():
        if any(term in text for term in terms):
            return name
    return None


def _enrich_response(row: Incident) -> None:
    metadata = row.metadata
    response = clean_text(str(metadata.get("response") or ""))
    if not response:
        return
    decoded = metadata.get("decoded_units") or decode_response(response)
    metadata["decoded_units"] = decoded
    metadata.setdefault("decoded_unit_text", decoded_unit_text(response))
    metadata.setdefault("response_summary", build_response_summary(row.subtype or row.title, response))
    # Compatibility alias used by the normalized-event UI.
    metadata["decoded_response"] = [
        {
            "code": item.get("code"),
            "label": item.get("label"),
            "kind": item.get("kind"),
            "certainty": "inferred" if item.get("confidence") == "inferred" else ("unknown" if item.get("confidence") == "unknown" else "confirmed"),
        }
        for item in decoded
    ]
    metadata["response_unknown_codes"] = [item.get("code") for item in decoded if item.get("confidence") == "unknown"]


def normalize_observations(rows: list[Incident]) -> None:
    for row in rows:
        row.title = _strip_html(row.title) or "Untitled local signal"
        row.summary = _strip_html(row.summary)
        row.location_text = _strip_html(row.location_text) or None
        row.subtype = _strip_html(row.subtype) or None
        row.source = _strip_html(row.source) or "Unknown source"
        row.category = clean_text(row.category).upper()
        if row.category not in CATEGORIES:
            row.category = infer_category(f"{row.title} {row.summary}")
        row.status = clean_text(row.status).lower() or "active"
        if row.status in {"closed", "ended", "cleared", "inactive"}:
            row.status = "resolved"
        elif row.status not in {"active", "resolved", "monitoring"}:
            row.status = "active"
        row.source_class = source_class(row)
        row.event_type = event_type(row)
        row.canonical_location = normalized_place(row.location_text) or None
        row.neighbourhood = infer_neighbourhood(row)
        row.related_ids = list(dict.fromkeys(row.related_ids or []))
        row.signals = list(dict.fromkeys(row.signals or []))
        row.raw_ids = list(dict.fromkeys(row.raw_ids or []))
        row.metadata = dict(row.metadata or {})
        _enrich_response(row)


def _customers(row: Incident) -> int:
    value = (row.metadata or {}).get("customers")
    try:
        return max(0, int(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def suppress_noise(rows: list[Incident]) -> list[Incident]:
    kept: list[Incident] = []
    for row in rows:
        if row.category == "UTILITY" and row.event_type == "power_outage":
            customers = _customers(row)
            text = f"{row.title} {row.summary} {row.location_text or ''}".lower()
            safety_related = any(term in text for term in PUBLIC_SAFETY_TERMS)
            if 0 < customers < 100 and not safety_related:
                continue
        kept.append(row)
    return kept


def _minutes_apart(a: Incident, b: Incident) -> float | None:
    da, db = parse_datetime(a.reported_at), parse_datetime(b.reported_at)
    if not da or not db:
        return None
    return abs((da - db).total_seconds()) / 60


def _location_match(a: Incident, b: Incident) -> bool:
    if None not in (a.lat, a.lon, b.lat, b.lon):
        try:
            if haversine_km(float(a.lat), float(a.lon), float(b.lat), float(b.lon)) <= 0.65:
                return True
        except (TypeError, ValueError):
            pass
    pa, pb = a.canonical_location or "", b.canonical_location or ""
    if not pa or not pb:
        return False
    ta, tb = set(pa.split()), set(pb.split())
    shared = ta & tb
    return bool(shared) and (len(shared) >= 2 or min(len(ta), len(tb)) == 1)


def _headline_tokens(row: Incident) -> set[str]:
    text = f"{row.title} {row.subtype or ''}".upper()
    tokens = re.findall(r"[A-Z0-9]{3,}", text)
    stop = {"HALIFAX", "NOVA", "SCOTIA", "WITH", "FROM", "THIS", "THAT", "THE", "AND", "FOR", "INCIDENT", "UPDATE"}
    return {token for token in tokens if token not in stop}


def _headline_similarity(a: Incident, b: Incident) -> float:
    ta, tb = _headline_tokens(a), _headline_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _family(category: str) -> str:
    if category in {"FIRE", "RESCUE", "EMS"}:
        return "emergency_response"
    if category in {"POLICE", "TRAFFIC"}:
        return "public_safety"
    return category


def _call_number(row: Incident) -> str | None:
    value = (row.metadata or {}).get("call_number")
    return clean_text(str(value)) if value else None


def _same_event(a: Incident, b: Incident) -> bool:
    if a.id == b.id:
        return True
    # Calendar/promotional listings are context records, not incident evidence.
    if a.source_class == "listing" or b.source_class == "listing":
        return False
    # Individual GTFS alerts are operational records. Sharing a neighbourhood,
    # event type, and collection window does not make two route/trip alerts the
    # same real-world event. Exact duplicate IDs were already handled above.
    if a.category == "TRANSIT" or b.category == "TRANSIT":
        if a.category != "TRANSIT" or b.category != "TRANSIT":
            return False
        if a.source == b.source == "Halifax Transit GTFS-Realtime":
            return False
    ca, cb = _call_number(a), _call_number(b)
    if ca and cb and ca == cb:
        return True
    age = _minutes_apart(a, b)
    if age is None or age > 180:
        return False
    same_family = _family(a.category) == _family(b.category)
    same_type = a.event_type == b.event_type
    place = _location_match(a, b)
    similarity = _headline_similarity(a, b)
    if age <= 90 and place and same_type:
        return True
    if age <= 45 and place and same_family and similarity >= 0.18:
        return True
    if age <= 120 and same_type and similarity >= 0.30:
        return True
    if age <= 180 and similarity >= 0.58:
        return True
    return False


def _pick_representative(group: list[Incident]) -> Incident:
    source_rank = {"first_party": 5, "news": 4, "secondary": 3, "community": 2, "listing": 1}
    return max(group, key=lambda row: (row.priority_score, row.seriousness_score, source_rank.get(row.source_class, 0), bool(row.location_text), len(row.summary or "")))


def _evidence(row: Incident) -> dict:
    return {
        "id": row.id,
        "source": row.source,
        "source_url": row.source_url,
        "source_class": row.source_class,
        "confidence": row.confidence,
        "reported_at": row.reported_at,
        "title": row.title,
    }


def cluster_events(rows: list[Incident]) -> list[Incident]:
    if not rows:
        return []
    parent = list(range(len(rows)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    ordered = sorted(range(len(rows)), key=lambda i: parse_datetime(rows[i].reported_at) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    for pos, i in enumerate(ordered):
        a = rows[i]
        da = parse_datetime(a.reported_at)
        for j in ordered[pos + 1:]:
            b = rows[j]
            db = parse_datetime(b.reported_at)
            if da and db and (da - db).total_seconds() > 3 * 3600:
                break
            if _same_event(a, b):
                union(i, j)

    grouped: dict[int, list[Incident]] = {}
    for i, row in enumerate(rows):
        grouped.setdefault(find(i), []).append(row)

    events: list[Incident] = []
    for group in grouped.values():
        rep = copy.deepcopy(_pick_representative(group))
        evidence = sorted((_evidence(row) for row in group), key=lambda x: x["reported_at"], reverse=True)
        unique_sources = list(dict.fromkeys(row.source for row in group))
        classes = list(dict.fromkeys(row.source_class for row in group))
        reported = [parse_datetime(row.reported_at) for row in group]
        reported = [value for value in reported if value]
        rep.reported_at = max(reported).replace(microsecond=0).isoformat().replace("+00:00", "Z") if reported else rep.reported_at
        first_reported = min(reported).replace(microsecond=0).isoformat().replace("+00:00", "Z") if reported else rep.reported_at
        call = next((_call_number(row) for row in group if _call_number(row)), None)
        original_ids = [row.id for row in group]
        # Include one stable member ID as a collision-resistant tiebreaker. Two
        # unrelated singleton listings can share type/location/hour, and two
        # distinct incident groups can occasionally share the same semantic key.
        key_parts = (
            call or rep.event_type,
            rep.canonical_location or rep.neighbourhood or rep.title,
            first_reported[:13],
            min(original_ids),
        )
        rep.cluster_id = f"evt-{stable_id(*key_parts)}"
        rep.id = rep.cluster_id
        rep.evidence = evidence
        rep.evidence_count = len(group)
        rep.source_count = len(unique_sources)
        rep.source = unique_sources[0] if len(unique_sources) == 1 else f"{len(unique_sources)} sources"
        rep.source_class = classes[0] if len(classes) == 1 else "mixed"
        rep.related_ids = original_ids
        rep.seriousness_score = max(row.seriousness_score for row in group)
        evidence_bonus = min(10, max(0, len(unique_sources) - 1) * 3)
        rep.priority_score = min(100, max(row.priority_score for row in group) + evidence_bonus)
        if rep.priority_score >= 80:
            rep.priority_band = "critical"
        elif rep.priority_score >= 60:
            rep.priority_band = "high"
        elif rep.priority_score >= 40:
            rep.priority_band = "elevated"
        elif rep.priority_score >= 20:
            rep.priority_band = "moderate"
        else:
            rep.priority_band = "low"
        rep.siren_score = max(row.siren_score for row in group)
        rep.attention_reasons = list(dict.fromkeys(reason for row in group for reason in row.attention_reasons))[:8]
        rep.metadata = dict(rep.metadata or {})
        rep.metadata.update({"first_reported_at": first_reported, "source_names": unique_sources, "source_classes": classes})
        response_row = next((row for row in group if (row.metadata or {}).get("response")), None)
        if response_row:
            for key in ("response", "decoded_units", "decoded_unit_text", "decoded_response", "response_summary", "response_unknown_codes", "call_number"):
                value = (response_row.metadata or {}).get(key)
                if value not in (None, "", []):
                    rep.metadata[key] = value
        if len(unique_sources) >= 2:
            rep.confidence = "corroborated"
        events.append(rep)

    events.sort(key=lambda row: (row.priority_score, parse_datetime(row.reported_at) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return events
