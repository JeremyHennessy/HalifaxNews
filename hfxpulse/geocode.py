from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from hfxpulse.adapters.base import session
from hfxpulse.models import Incident

NOMINATIM = "https://nominatim.openstreetmap.org/search"


def cache_key(location: str) -> str:
    # Keep the street type and municipality: ATLANTIC ST, DARTMOUTH and
    # ATLANTIC ST, HALIFAX are different places. Never read legacy stripped keys.
    tokens = re.findall(r"[A-Z0-9]+", location.upper())
    return "v2:" + " ".join(tokens) if tokens else ""


def _query(location: str) -> str:
    # Source text may name any HRM community. Do not append a conflicting city.
    return f"{location.replace(' / ', ' AND ')}, Nova Scotia, Canada"


def enrich(rows: list[Incident], cache_path: Path, max_new: int = 6) -> dict[str, dict]:
    """Add approximate coordinates with a persistent cache.

    Disabled when HFXPULSE_GEOCODE=0. New network lookups are deliberately capped and
    serialized to respect the public Nominatim service. Source location text is never replaced.
    """
    for row in rows:
        if row.location_precision == "approximate_geocode" and (
            not row.location_text or row.metadata.get("geocode_key") != cache_key(row.location_text)
        ):
            # Retained observations can already carry the old ambiguous result.
            # Invalidate derived geometry even when new lookups are disabled.
            row.lat = row.lon = None
            row.location_precision = None
            row.metadata.pop("geocode_key", None)
    if os.getenv("HFXPULSE_GEOCODE", "1") in {"0", "false", "False"}:
        return {}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    except Exception:
        cache = {}

    cache = {key: value for key, value in cache.items() if key.startswith("v2:")}
    new_count = 0
    s = session()
    for row in rows:
        if row.lat is not None or row.lon is not None or not row.location_text:
            continue
        # Only geocode municipal incident-style locations, not prose-heavy titles.
        key = cache_key(row.location_text)
        if not key:
            continue
        cached = cache.get(key)
        if cached:
            row.lat = cached.get("lat")
            row.lon = cached.get("lon")
            row.location_precision = "approximate_geocode"
            row.metadata["geocode_key"] = key
            continue
        if new_count >= max_new:
            continue
        query = _query(row.location_text)
        try:
            response = s.get(NOMINATIM, params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "ca"}, timeout=15)
            response.raise_for_status()
            matches = response.json()
            if matches:
                lat = float(matches[0]["lat"])
                lon = float(matches[0]["lon"])
                # Guard against a bad geocoder match far outside HRM.
                if 44.3 <= lat <= 45.1 and -64.2 <= lon <= -62.9:
                    cache[key] = {"lat": lat, "lon": lon, "precision": "approximate_geocode", "query": query}
                    row.lat, row.lon, row.location_precision = lat, lon, "approximate_geocode"
                    row.metadata["geocode_key"] = key
        except Exception:
            pass
        new_count += 1
        time.sleep(1.05)

    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return cache
