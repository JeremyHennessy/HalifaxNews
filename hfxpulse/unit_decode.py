from __future__ import annotations

import re
from typing import Any

# HRFE's public CRA/Standards-of-Cover tables expose unit identifiers such as
# DC02, E02, A03, Q05, TCT12, PC1E and PCV1E. The rules below translate the
# identifier shape while preserving the raw dispatch code for auditability.
SPECIAL_CODES: dict[str, dict[str, str]] = {
    "JRCC": {
        "label": "Joint Rescue Coordination Centre Halifax",
        "kind": "external_agency",
        "confidence": "verified",
    },
    "PCC": {
        "label": "Platoon Captain Core",
        "kind": "command",
        "confidence": "verified",
    },
    "PCR": {
        "label": "Platoon Captain Rural",
        "kind": "command",
        "confidence": "inferred",
    },
    "PCE": {
        "label": "Platoon Captain East",
        "kind": "command",
        "confidence": "inferred",
    },
    "PCW": {
        "label": "Platoon Captain West",
        "kind": "command",
        "confidence": "inferred",
    },
}

UNIT_PATTERNS = (
    (re.compile(r"^DC0*(\d+)$", re.I), "District Chief {n}", "command", "verified"),
    (re.compile(r"^FB0*(\d+)$", re.I), "Fire Boat {n}", "marine", "verified"),
    (re.compile(r"^STN0*(\d+)$", re.I), "Station {n} assignment", "station", "verified"),
    (re.compile(r"^TCT0*(\d+)$", re.I), "Tactical Unit {n}", "specialty", "verified"),
    (re.compile(r"^HM0*(\d+)$", re.I), "HazMat Unit {n}", "specialty", "verified"),
    (re.compile(r"^PCV(\d+)([EW])$", re.I), "Platoon Captain Volunteer {n} {dir}", "command", "verified"),
    (re.compile(r"^PC(\d+)([EW])$", re.I), "Platoon Captain {n} {dir}", "command", "verified"),
    (re.compile(r"^EA0*(\d+)$", re.I), "Engine {n} Alpha", "apparatus", "verified"),
    (re.compile(r"^E0*(\d+)A$", re.I), "Engine {n} Alpha", "apparatus", "verified"),
    (re.compile(r"^E0*(\d+)$", re.I), "Engine {n}", "apparatus", "verified"),
    (re.compile(r"^Q0*(\d+)$", re.I), "Quint {n}", "apparatus", "verified"),
    (re.compile(r"^A0*(\d+)$", re.I), "Aerial {n}", "apparatus", "verified"),
    (re.compile(r"^R0*(\d+)$", re.I), "Rescue {n}", "apparatus", "verified"),
    (re.compile(r"^T0*(\d+)$", re.I), "Tanker {n}", "apparatus", "verified"),
    (re.compile(r"^RB0*(\d+)$", re.I), "Rescue Boat {n}", "marine", "verified"),
    (re.compile(r"^B0*(\d+)$", re.I), "Boat {n}", "marine", "verified"),
    (re.compile(r"^U0*(\d+)$", re.I), "Utility {n}", "support", "verified"),
    (re.compile(r"^L0*(\d+)$", re.I), "Ladder {n}", "apparatus", "verified"),
    (re.compile(r"^P0*(\d+)$", re.I), "Platform {n}", "apparatus", "verified"),
)

PLURALS = {
    "District Chief": "District Chiefs",
    "Engine": "Engines",
    "Quint": "Quints",
    "Aerial": "Aerials",
    "Rescue": "Rescues",
    "Tanker": "Tankers",
    "Fire Boat": "Fire Boats",
    "Station": "Stations",
}


def decode_unit(code: str) -> dict[str, Any]:
    raw = (code or "").strip().upper()
    if not raw:
        return {"code": raw, "label": raw, "kind": "unknown", "confidence": "unknown"}

    if raw == "FB1":
        return {
            "code": raw,
            "label": "Fire Boat 1 (Kjipuktuk)",
            "kind": "marine",
            "confidence": "verified",
        }

    if raw in SPECIAL_CODES:
        return {"code": raw, **SPECIAL_CODES[raw]}

    for pattern, template, kind, confidence in UNIT_PATTERNS:
        match = pattern.fullmatch(raw)
        if not match:
            continue
        groups = match.groups()
        n = str(int(groups[0])) if groups and groups[0].isdigit() else (groups[0] if groups else "")
        direction = ""
        if len(groups) > 1:
            direction = {"E": "East", "W": "West"}.get(groups[1].upper(), groups[1])
        return {
            "code": raw,
            "label": template.format(n=n, dir=direction).strip(),
            "kind": kind,
            "confidence": confidence,
        }

    return {
        "code": raw,
        "label": f"Unit {raw}",
        "kind": "unknown",
        "confidence": "unknown",
    }


def decode_response(response: str) -> list[dict[str, Any]]:
    return [decode_unit(code) for code in (response or "").split() if code.strip()]


def display_label(unit: dict[str, Any]) -> str:
    label = str(unit.get("label") or unit.get("code") or "")
    return f"{label} (inferred)" if unit.get("confidence") == "inferred" else label


def _natural_join(items: list[str]) -> str:
    values = [item for item in items if item]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _compact_assets(decoded: list[dict[str, Any]]) -> list[str]:
    grouped: dict[str, list[str]] = {}
    standalone: list[str] = []
    group_patterns = {
        "Engine": re.compile(r"^Engine (\d+)$"),
        "Quint": re.compile(r"^Quint (\d+)$"),
        "Aerial": re.compile(r"^Aerial (\d+)$"),
        "Rescue": re.compile(r"^Rescue (\d+)$"),
        "Tanker": re.compile(r"^Tanker (\d+)$"),
        "Fire Boat": re.compile(r"^Fire Boat (\d+)(?: \(Kjipuktuk\))?$"),
        "Station": re.compile(r"^Station (\d+) assignment$"),
    }

    for unit in decoded:
        if unit["kind"] in {"command", "external_agency"}:
            continue
        label = unit["label"]
        matched = False
        for name, pattern in group_patterns.items():
            found = pattern.fullmatch(label)
            if not found:
                continue
            grouped.setdefault(name, []).append(found.group(1))
            matched = True
            break
        if not matched:
            standalone.append(display_label(unit))

    parts: list[str] = []
    for name in ("Engine", "Fire Boat", "Quint", "Aerial", "Rescue", "Tanker", "Station"):
        numbers = grouped.get(name, [])
        if not numbers:
            continue
        noun = name if len(numbers) == 1 else PLURALS[name]
        if name == "Fire Boat" and numbers == ["1"]:
            parts.append("Fire Boat 1 (Kjipuktuk)")
        elif name == "Station":
            parts.append(f"Station {_natural_join(numbers)} assignment" + ("s" if len(numbers) > 1 else ""))
        else:
            parts.append(f"{noun} {_natural_join(numbers)}")
    parts.extend(standalone)
    return parts


def build_response_summary(incident_type: str, response: str) -> str:
    decoded = decode_response(response)
    if not decoded:
        return ""

    kind = (incident_type or "").upper()
    if any(term in kind for term in ("SALT WATER", "WATER RESCUE", "MARINE")):
        prefix = "Marine rescue response"
    elif "STRUCTURE" in kind:
        prefix = "Structure-fire response"
    elif any(term in kind for term in ("COLLISION", "RESCUE")):
        prefix = "Rescue response"
    elif "MEDICAL" in kind:
        prefix = "Medical first-response"
    else:
        prefix = "Emergency response"

    assets = _compact_assets(decoded)
    commands = [display_label(u) for u in decoded if u["kind"] == "command"]
    external = [display_label(u) for u in decoded if u["kind"] == "external_agency"]

    sentence = f"{prefix}: {_natural_join(assets)}" if assets else prefix
    if commands:
        sentence += f", under {_natural_join(commands)}"
    if external:
        sentence += f", with {_natural_join(external)} coordination"
    unknown = [u["code"] for u in decoded if u["kind"] == "unknown"]
    if unknown:
        sentence += f". Additional dispatch code{'s' if len(unknown) != 1 else ''}: {_natural_join(unknown)}"
    return sentence.rstrip(".") + "."


def decoded_unit_text(response: str) -> str:
    return " · ".join(f"{u['code']} — {display_label(u)}" for u in decode_response(response))
