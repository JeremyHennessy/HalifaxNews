from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Incident:
    id: str
    source: str
    source_url: str
    title: str
    summary: str
    category: str
    reported_at: str
    source_kind: str = "official"
    confidence: str = "official"
    subtype: str | None = None
    updated_at: str | None = None
    status: str = "active"
    location_text: str | None = None
    lat: float | None = None
    lon: float | None = None
    location_precision: str | None = None
    severity: int = 1
    siren_score: int = 0
    seriousness_score: int = 0
    source_class: str = "unknown"
    event_type: str | None = None
    canonical_location: str | None = None
    neighbourhood: str | None = None
    cluster_id: str | None = None
    evidence_count: int = 1
    source_count: int = 1
    evidence: list[dict[str, Any]] = field(default_factory=list)
    priority_score: int = 0
    priority_band: str = "low"
    impact_scope: str = "local"
    attention_reasons: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    raw_ids: list[str] = field(default_factory=list)
    related_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceHealth:
    source: str
    url: str
    authority: str
    status: str
    checked_at: str
    fetched_at: str | None = None
    records: int = 0
    error: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
