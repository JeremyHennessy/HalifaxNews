from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import requests

from hfxpulse.models import Incident, SourceHealth, utc_now_iso


USER_AGENT = "HFXPulse/0.1 (+public local-intelligence aggregator; contact via project repository)"


@dataclass
class AdapterResult:
    incidents: list[Incident] = field(default_factory=list)
    health: SourceHealth | None = None


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    return s


def guarded_fetch(source: str, url: str, authority: str, fn: Callable[[], list[Incident]], notes: str | None = None) -> AdapterResult:
    checked = utc_now_iso()
    try:
        rows = fn()
        return AdapterResult(
            incidents=rows,
            health=SourceHealth(
                source=source,
                url=url,
                authority=authority,
                status="ok",
                checked_at=checked,
                fetched_at=utc_now_iso(),
                records=len(rows),
                notes=notes,
            ),
        )
    except Exception as exc:
        return AdapterResult(
            incidents=[],
            health=SourceHealth(
                source=source,
                url=url,
                authority=authority,
                status="error",
                checked_at=checked,
                records=0,
                error=f"{type(exc).__name__}: {exc}",
                notes=notes,
            ),
        )
