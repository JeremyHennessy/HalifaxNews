from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hfxpulse.adapters import emergency_ns, hfxgov_bluesky, hrfe, hrp, ns511, ns_power, reddit, transit, water, weather
from hfxpulse.correlation import correlate
from hfxpulse.geocode import enrich as geocode_enrich
from hfxpulse.models import Incident, SourceHealth, utc_now_iso
from hfxpulse.util import parse_datetime

ADAPTERS = [hrfe.fetch, transit.fetch, hrp.fetch, hfxgov_bluesky.fetch, ns511.fetch, water.fetch, weather.fetch, emergency_ns.fetch, ns_power.fetch, reddit.fetch]


def _read_existing(path: Path) -> list[Incident]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [Incident(**row) for row in payload.get("incidents", [])]
    except Exception:
        return []


def _retain_history(existing: list[Incident], fresh: list[Incident], hours: int = 48) -> list[Incident]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    merged = {r.id: r for r in existing}
    merged.update({r.id: r for r in fresh})
    kept = []
    for row in merged.values():
        dt = parse_datetime(row.reported_at)
        if dt and dt >= cutoff:
            kept.append(row)
    return kept


def collect(output: Path) -> dict:
    fresh: list[Incident] = []
    health: list[SourceHealth] = []
    for adapter in ADAPTERS:
        result = adapter()
        fresh.extend(result.incidents)
        if result.health:
            health.append(result.health)

    existing = _read_existing(output)
    rows = _retain_history(existing, fresh)
    cache_path = output.parents[2] / "data" / "geocode_cache.json"
    geocode_enrich(rows, cache_path)
    correlate(rows)
    rows.sort(key=lambda r: parse_datetime(r.reported_at) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    payload = {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "history_hours": 48,
        "incidents": [r.to_dict() for r in rows],
        "source_health": [h.to_dict() for h in health],
        "disclaimer": "Public-information aggregator. May be delayed or incomplete. For emergencies call 911.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(output)
    return payload
