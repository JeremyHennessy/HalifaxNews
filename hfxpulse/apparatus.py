from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from hfxpulse.util import clean_text

# Expansions are intentionally conservative. "confirmed" entries are directly supported
# by public HRFE/Canadian SAR nomenclature. "inferred" entries are stable call-sign
# expansions supported by matching HRFE apparatus/role names but not by a published HRFE codebook.
_EXACT: dict[str, dict[str, str]] = {
    "JRCC": {
        "label": "Joint Rescue Coordination Centre Halifax",
        "short": "JRCC Halifax",
        "kind": "federal_sar",
        "certainty": "confirmed",
    },
    "PCE": {
        "label": "Platoon Captain East",
        "short": "Platoon Captain East",
        "kind": "command",
        "certainty": "inferred",
    },
    "PCW": {
        "label": "Platoon Captain West",
        "short": "Platoon Captain West",
        "kind": "command",
        "certainty": "inferred",
    },
}


def _number(raw: str) -> str:
    try:
        return str(int(raw))
    except (TypeError, ValueError):
        return raw


def decode_unit(code: str) -> dict[str, str]:
    raw = clean_text(code).upper().strip(",;")
    if not raw:
        return {"code": "", "label": "", "short": "", "kind": "unknown", "certainty": "unknown"}
    if raw in _EXACT:
        return {"code": raw, **_EXACT[raw]}

    patterns: tuple[tuple[str, str, str, str], ...] = (
        (r"DC(\d{1,2})", "District Chief {n}", "District Chief {n}", "command"),
        (r"E(\d{1,2})(?:A|ALPHA)?", "Engine {n}", "Engine {n}", "engine"),
        (r"Q(\d{1,2})", "Quint {n}", "Quint {n}", "quint"),
        (r"A(\d{1,2})", "Aerial {n}", "Aerial {n}", "aerial"),
        (r"FB(\d{1,2})", "Fire Boat {n}", "Fire Boat {n}", "fire_boat"),
        (r"RB(\d{1,2})", "Rescue Boat {n}", "Rescue Boat {n}", "rescue_boat"),
        (r"R(\d{1,2})", "Rescue {n}", "Rescue {n}", "rescue"),
        (r"T(\d{1,2})", "Tanker {n}", "Tanker {n}", "tanker"),
        (r"U(\d{1,2})", "Utility {n}", "Utility {n}", "utility"),
        (r"TCT(\d{1,2})", "Tactical {n}", "Tactical {n}", "tactical"),
        (r"TAC(\d{1,2})", "Tactical {n}", "Tactical {n}", "tactical"),
        (r"STN(\d{1,2})", "Station {n} personnel / station response", "Station {n} personnel", "station"),
    )
    for pattern, label, short, kind in patterns:
        m = re.fullmatch(pattern, raw)
        if m:
            n = _number(m.group(1))
            return {
                "code": raw,
                "label": label.format(n=n),
                "short": short.format(n=n),
                "kind": kind,
                "certainty": "confirmed" if kind != "station" else "inferred",
            }

    m = re.fullmatch(r"PCV(\d+)([EW])", raw)
    if m:
        side = "East" if m.group(2) == "E" else "West"
        n = _number(m.group(1))
        return {
            "code": raw,
            "label": f"Volunteer Platoon Captain {n} {side}",
            "short": f"Volunteer Platoon Captain {n} {side}",
            "kind": "command",
            "certainty": "inferred",
        }

    m = re.fullmatch(r"PC(\d+)([EW])", raw)
    if m:
        side = "East" if m.group(2) == "E" else "West"
        n = _number(m.group(1))
        return {
            "code": raw,
            "label": f"Platoon Captain {n} {side}",
            "short": f"Platoon Captain {n} {side}",
            "kind": "command",
            "certainty": "inferred",
        }

    return {"code": raw, "label": raw, "short": raw, "kind": "unknown", "certainty": "unknown"}


def decode_response(response: str | None) -> list[dict[str, str]]:
    if not response:
        return []
    return [decode_unit(token) for token in re.split(r"\s+", clean_text(response)) if token]


def _natural_join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def _plural_group(kind: str, units: list[dict[str, str]]) -> str | None:
    if len(units) < 2:
        return None
    nums = []
    for unit in units:
        m = re.search(r"(\d+)$", unit["short"])
        if not m:
            return None
        nums.append(m.group(1))
    names = {
        "engine": "Engines",
        "quint": "Quints",
        "aerial": "Aerials",
        "tanker": "Tankers",
        "rescue": "Rescues",
        "utility": "Utilities",
        "tactical": "Tactical units",
        "fire_boat": "Fire Boats",
        "rescue_boat": "Rescue Boats",
    }
    prefix = names.get(kind)
    if not prefix:
        return None
    return f"{prefix} {_natural_join(nums)}"


def compact_labels(units: list[dict[str, str]]) -> list[str]:
    by_kind: dict[str, list[dict[str, str]]] = defaultdict(list)
    order: list[str] = []
    for unit in units:
        kind = unit["kind"]
        if kind not in by_kind:
            order.append(kind)
        by_kind[kind].append(unit)
    labels: list[str] = []
    for kind in order:
        group = by_kind[kind]
        plural = _plural_group(kind, group)
        if plural:
            labels.append(plural)
        else:
            labels.extend(u["short"] for u in group)
    return labels


def response_summary(incident_type: str | None, response: str | None) -> str | None:
    units = decode_response(response)
    if not units:
        return None
    text = clean_text(incident_type).lower()
    kinds = {u["kind"] for u in units}
    if "salt water" in text or "fresh water" in text or "water rescue" in text or "fire_boat" in kinds or "JRCC" in {u["code"] for u in units}:
        lead = "Marine search-and-rescue response"
    elif "structure fire" in text:
        lead = "Structure-fire response"
    elif "hazmat" in text:
        lead = "Hazardous-material response"
    elif "collision" in text or "mvc" in text:
        lead = "Collision / rescue response"
    elif "medical" in text:
        lead = "Medical-assistance response"
    elif "alarm" in text:
        lead = "Fire-alarm response"
    elif "fire" in text:
        lead = "Fire response"
    else:
        lead = "Emergency response"
    return f"{lead} involving {_natural_join(compact_labels(units))}."


def enrich_response_metadata(metadata: dict[str, Any], incident_type: str | None = None) -> dict[str, Any]:
    response = clean_text(str((metadata or {}).get("response") or ""))
    if not response:
        return metadata
    units = decode_response(response)
    metadata["decoded_response"] = units
    metadata["response_summary"] = response_summary(incident_type, response)
    metadata["response_resource_count"] = len(units)
    metadata["response_unknown_codes"] = [u["code"] for u in units if u["certainty"] == "unknown"]
    return metadata
