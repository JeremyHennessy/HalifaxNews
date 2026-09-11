from __future__ import annotations

import re
from datetime import datetime, timezone

from hfxpulse.models import Incident
from hfxpulse.util import DOWNTOWN_CENTER, apparatus_count, haversine_km, parse_datetime

DOWNTOWN_TERMS = (
    "downtown", "barrington", "argyle", "granville", "hollis", "lower water", "water st",
    "spring garden", "sackville", "duke", "george", "brunswick", "gottingen", "quinpool",
    "cogswell", "university", "south park", "morris", "inglis", "waterfront", "scotia square",
    "purdy", "citadel", "commons",
)


def _text(row: Incident) -> str:
    return " ".join(x for x in (row.title, row.summary, row.subtype or "", row.location_text or "") if x).lower()


def _has(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _customers(row: Incident) -> int:
    value = row.metadata.get("customers") if row.metadata else None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if value is None:
        match = re.search(r"([\d,]+)\s+(?:customers?|people|homes?)\s+(?:affected|without power)", _text(row))
        if match:
            value = match.group(1)
    try:
        return max(0, int(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def seriousness_score(row: Incident) -> tuple[int, list[str], str]:
    """Intrinsic public-impact score. Evidence confidence is intentionally excluded."""
    text = _text(row)
    category = row.category.upper()
    score = 8
    reasons: list[str] = []
    scope = "local"

    category_base = {
        "FIRE": 34,
        "RESCUE": 38,
        "EMS": 28,
        "POLICE": 32,
        "TRAFFIC": 22,
        "TRANSIT": 12,
        "UTILITY": 12,
        "WEATHER": 20,
        "EMERGENCY": 44,
        "MARINE": 18,
        "EVENT": 4,
        "COMMUNITY": 10,
    }
    score = category_base.get(category, score)

    critical_terms = (
        ("evacuation order", 92, "evacuation order"),
        ("shelter in place", 88, "shelter-in-place"),
        ("active shooter", 95, "active shooter"),
        ("mass casualty", 95, "mass casualty"),
        ("major fire", 85, "major fire"),
        ("wildfire", 76, "wildfire"),
    )
    for term, floor, reason in critical_terms:
        if term in text:
            score = max(score, floor)
            reasons.append(reason)

    if _has(text, "structure fire", "building fire", "apartment fire"):
        score = max(score, 68); reasons.append("structure fire")
    if _has(text, "shooting", "shots fired", "gunshot", "stabbing", "weapon", "armed person"):
        score = max(score, 72); reasons.append("violent/public-safety incident")
    if _has(text, "swat", "ert", "tactical", "barricaded", "hostage"):
        score = max(score, 78); reasons.append("tactical response")
    if _has(text, "hazmat high", "gas leak", "propane leak", "chemical spill"):
        score = max(score, 62); reasons.append("hazardous material")
    elif "hazmat" in text:
        score = max(score, 48); reasons.append("hazmat response")
    if _has(text, "water rescue", "missing swimmer", "person in water", "search and rescue"):
        score = max(score, 62); reasons.append("rescue operation")
    if _has(text, "entrapment", "rollover", "serious collision", "multi-vehicle", "multi vehicle"):
        score = max(score, 58); reasons.append("serious collision")
    elif _has(text, "collision", "crash", "mvc"):
        score = max(score, 36); reasons.append("collision")
    if _has(text, "road closed", "road closure", "bridge closed", "full closure", "all lanes closed"):
        score = max(score, 44); reasons.append("major traffic closure")
    if _has(text, "boil water", "do not consume", "water quality advisory"):
        score = max(score, 48); reasons.append("water safety advisory")
    if _has(text, "severe thunderstorm warning", "tornado warning", "hurricane warning", "storm surge warning"):
        score = max(score, 60); reasons.append("severe weather warning")
    elif "warning" in text and category == "WEATHER":
        score = max(score, 42); reasons.append("weather warning")

    units = apparatus_count(str(row.metadata.get("response", ""))) if row.metadata else 0
    if units >= 8:
        score += 18; reasons.append(f"large emergency response ({units} units)")
    elif units >= 5:
        score += 12; reasons.append(f"multi-unit response ({units} units)")
    elif units >= 3:
        score += 6; reasons.append(f"multiple responding units ({units})")

    customers = _customers(row)
    if category == "UTILITY" and customers:
        if customers >= 10000:
            score = max(score, 68); scope = "citywide"; reasons.append(f"{customers:,} customers affected")
        elif customers >= 3000:
            score = max(score, 54); scope = "multi-neighbourhood"; reasons.append(f"{customers:,} customers affected")
        elif customers >= 1000:
            score = max(score, 44); scope = "neighbourhood"; reasons.append(f"{customers:,} customers affected")
        elif customers >= 250:
            score = max(score, 32); scope = "neighbourhood"; reasons.append(f"{customers:,} customers affected")
        elif customers >= 100:
            score = max(score, 24); reasons.append(f"{customers:,} customers affected")

    if _has(text, "citywide", "region-wide", "regional", "all hrm"):
        scope = "citywide"
        score += 8
    elif _has(text, "multiple neighbourhood", "several neighbourhood"):
        scope = "multi-neighbourhood"
        score += 5

    if row.status == "resolved":
        score = max(0, score - 18)
        reasons.append("resolved")

    score = min(100, max(0, int(round(score))))
    return score, list(dict.fromkeys(reasons))[:6], scope


def _downtown(row: Incident) -> bool:
    if row.lat is not None and row.lon is not None:
        try:
            return haversine_km(float(row.lat), float(row.lon), *DOWNTOWN_CENTER) <= 2.2
        except (TypeError, ValueError):
            pass
    return any(term in _text(row) for term in DOWNTOWN_TERMS)


def priority_score(row: Incident, seriousness: int) -> tuple[int, list[str]]:
    """What deserves attention now: seriousness + recency + downtown relevance + corroboration."""
    score = seriousness * 0.72
    reasons: list[str] = []
    dt = parse_datetime(row.reported_at)
    if dt:
        age_m = max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 60)
        if age_m <= 15:
            score += 18; reasons.append("very recent")
        elif age_m <= 45:
            score += 14; reasons.append("recent")
        elif age_m <= 90:
            score += 9; reasons.append("within 90 minutes")
        elif age_m <= 240:
            score += 5
        elif age_m > 1440:
            score -= 8

    if _downtown(row):
        score += 8
        reasons.append("downtown relevance")

    related = len(set(row.related_ids or []))
    if row.confidence == "corroborated" or related >= 2:
        score += 7; reasons.append("multiple matching signals")
    elif related == 1:
        score += 3; reasons.append("related signal")

    # Source type affects confidence presentation elsewhere, not intrinsic seriousness.
    # Only a tiny priority nudge prevents a stale low-quality report outranking a live dispatch on ties.
    if row.source_kind in {"official", "official_archive"}:
        score += 2

    score = min(100, max(0, int(round(score))))
    return score, reasons


def band(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "elevated"
    if score >= 20:
        return "moderate"
    return "low"


def score_incidents(rows: list[Incident]) -> None:
    for row in rows:
        seriousness, seriousness_reasons, scope = seriousness_score(row)
        priority, priority_reasons = priority_score(row, seriousness)
        row.seriousness_score = seriousness
        row.priority_score = priority
        row.priority_band = band(priority)
        row.impact_scope = scope
        row.attention_reasons = list(dict.fromkeys(seriousness_reasons + priority_reasons))[:8]
