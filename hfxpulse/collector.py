from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hfxpulse.adapters import (
    bluesky, bridges, downtown_events, emergency_ns, hfxgov_bluesky, hrfe, hrfe_mirror, hrfe_open_data, hrm_news, hrp,
    marine_weather, navwarn, newsfeeds, ns511, ns_power, nshealth_status, port_cruise, rcmp, reddit, smu_alert,
    street_closures, transit, water, water_alerts, weather, wildfire,
)
from hfxpulse.correlation import correlate
from hfxpulse.geocode import enrich as geocode_enrich
from hfxpulse.models import Incident, SourceHealth, utc_now_iso
from hfxpulse.news_context import attach_news_context
from hfxpulse.normalization import cluster_events, normalize_observations, suppress_noise
from hfxpulse.scoring import score_incidents
from hfxpulse.util import parse_datetime

ADAPTERS = [
    hrfe.fetch,
    hrfe_mirror.fetch,
    hrfe_open_data.fetch,
    transit.fetch,
    hrp.fetch,
    hrm_news.fetch,
    rcmp.fetch,
    hfxgov_bluesky.fetch,
    bluesky.fetch_official_and_local,
    bluesky.fetch_search,
    ns511.fetch,
    street_closures.fetch,
    bridges.fetch,
    water.fetch,
    water_alerts.fetch,
    weather.fetch,
    marine_weather.fetch,
    navwarn.fetch,
    emergency_ns.fetch,
    wildfire.fetch,
    ns_power.fetch,
    nshealth_status.fetch,
    reddit.fetch,
    newsfeeds.fetch,
    downtown_events.fetch,
    smu_alert.fetch,
    port_cruise.fetch,
]

# These collectors are current-state snapshots, not append-only historical feeds.
# A healthy zero/missing row means the old item is no longer active. A failed
# collector must never be interpreted as resolution.
SNAPSHOT_SOURCES = {
    water_alerts.SOURCE,
    marine_weather.SOURCE,
    navwarn.SOURCE,
    wildfire.SOURCE,
    nshealth_status.SOURCE,
    smu_alert.SOURCE,
}


def _read_existing(path: Path) -> list[Incident]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [Incident(**row) for row in payload.get("incidents", [])]
    except Exception:
        return []


def _apply_snapshot_lifecycle(
    existing: list[Incident], fresh: list[Incident], health: list[SourceHealth]
) -> list[Incident]:
    """Resolve vanished snapshot rows only when that source refreshed successfully.

    If a snapshot source fails, previously-active rows become ``monitoring`` with
    unverified freshness instead of being falsely cleared or left labelled fresh.
    """
    status_by_source = {item.source: item.status for item in health}
    fresh_ids = {row.id for row in fresh}
    checked = utc_now_iso()
    adjusted: list[Incident] = []

    for row in existing:
        if row.source not in SNAPSHOT_SOURCES or row.id in fresh_ids:
            adjusted.append(row)
            continue

        source_status = status_by_source.get(row.source)
        if source_status == "ok":
            resolved = copy.deepcopy(row)
            resolved.status = "resolved"
            resolved.updated_at = checked
            resolved.metadata = dict(resolved.metadata or {})
            resolved.metadata["currently_active"] = False
            resolved.metadata["resolved_by_snapshot_absence"] = True
            resolved.metadata.pop("freshness_unverified", None)
            adjusted.append(resolved)
        elif source_status == "error" and (row.metadata or {}).get("currently_active") is True:
            uncertain = copy.deepcopy(row)
            uncertain.status = "monitoring"
            uncertain.updated_at = checked
            uncertain.metadata = dict(uncertain.metadata or {})
            uncertain.metadata["freshness_unverified"] = True
            adjusted.append(uncertain)
        else:
            adjusted.append(row)

    return adjusted


def _retain_history(existing: list[Incident], fresh: list[Incident], hours: int = 48) -> list[Incident]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    merged = {row.id: row for row in existing}
    merged.update({row.id: row for row in fresh})
    kept = []
    for row in merged.values():
        dt = parse_datetime(row.reported_at)
        if row.metadata.get("currently_active") is True or (dt and dt >= cutoff):
            kept.append(row)
    return kept


def _revalidate_retained_rows(rows: list[Incident]) -> list[Incident]:
    """Apply current source-quality rules to retained history as well as fresh data."""
    kept: list[Incident] = []
    for row in rows:
        if row.source_kind == "news" and not newsfeeds.relevant_news_item(row.title, row.summary):
            continue
        # Reddit observations are retained for up to 48 hours. Re-run the current
        # incident matcher so rows admitted by an older looser substring rule do
        # not survive after the parser is corrected.
        if row.source.startswith("r/") and row.source_kind == "community":
            if not reddit._incident_hit(f"{row.title} {row.summary}"):
                continue
        kept.append(row)
    return kept


def _run_adapters() -> tuple[list[Incident], list[SourceHealth]]:
    fresh: list[Incident] = []
    health: list[SourceHealth] = []
    with ThreadPoolExecutor(max_workers=min(10, len(ADAPTERS))) as pool:
        futures = {pool.submit(adapter): adapter for adapter in ADAPTERS}
        for future in as_completed(futures):
            adapter = futures[future]
            try:
                result = future.result()
                fresh.extend(result.incidents)
                if result.health:
                    health.append(result.health)
            except Exception as exc:
                health.append(SourceHealth(
                    source=getattr(adapter, "__module__", repr(adapter)).rsplit(".", 1)[-1],
                    url="",
                    authority="unknown",
                    status="error",
                    checked_at=utc_now_iso(),
                    error=f"Unhandled adapter error: {type(exc).__name__}: {exc}",
                ))
    return fresh, health


def collect(output: Path) -> dict:
    fresh, health = _run_adapters()
    existing = _apply_snapshot_lifecycle(_read_existing(output), fresh, health)
    rows = _revalidate_retained_rows(_retain_history(existing, fresh))
    cache_path = output.parents[2] / "data" / "geocode_cache.json"
    normalize_observations(rows)
    rows = suppress_noise(rows)
    geocode_enrich(rows, cache_path)
    correlate(rows)
    score_incidents(rows)
    events = cluster_events(rows)
    attach_news_context(events, rows)
    rows.sort(key=lambda row: parse_datetime(row.reported_at) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    health.sort(key=lambda item: (item.status != "error", item.source.lower()))

    payload = {
        "schema_version": 4,
        "generated_at": utc_now_iso(),
        "history_hours": 48,
        "collector_count": len(ADAPTERS),
        "incidents": [row.to_dict() for row in rows],
        "events": [row.to_dict() for row in events],
        "event_count": len(events),
        "observation_count": len(rows),
        "source_health": [item.to_dict() for item in health],
        "disclaimer": "Broad public-information aggregator. Sources can be delayed, wrong or incomplete. Provenance is shown on every signal. For emergencies call 911.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(output)
    return payload
