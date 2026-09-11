#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hfxpulse.collector import collect

if __name__ == "__main__":
    output = ROOT / "public" / "data" / "incidents.json"
    payload = collect(output)
    ok = sum(1 for s in payload["source_health"] if s["status"] == "ok")
    errors = len(payload["source_health"]) - ok
    print(f"Wrote {len(payload['incidents'])} incidents. Sources: {ok} ok, {errors} errors.")
    for source in payload["source_health"]:
        print(f"- {source['source']}: {source['status']} ({source['records']} records){' — ' + source['error'] if source.get('error') else ''}")
