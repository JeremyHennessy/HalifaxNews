# HFX Pulse

HFX Pulse is an evidence-first, near-real-time local incident dashboard for Halifax. Its core question is simple: **“I hear sirens / see a closure / notice disruption downtown — what public signals explain it right now?”**

It is deliberately not a conventional news reader. The collector prioritizes operational public feeds and then adds slower official context and clearly labelled community observations.

## Product rules

1. **Official is a source property, not a visual style.** An item is official only if it originated from a public authority source.
2. **Corroborated requires two official sources.** A Reddit post cannot turn an official incident into “corroborated.”
3. **Unknown stays unknown.** A failed scraper is shown in Source Health; it does not become “0 incidents.”
4. **No person tracking.** The product stores incident/location information published for public awareness. It intentionally does not store Reddit usernames or attempt to identify people involved.
5. **Source timestamps are preserved.** Collector run time is not substituted for the event time when the source provides one.
6. **Not a 911 service.** Delays and omissions are possible.

## Current source adapters

| Source | Role | Authority | Current implementation |
|---|---|---|---|
| Halifax Regional Fire & Emergency incident feed | Fire/rescue/medical/collision dispatch, response units | Official | Public-label HTML parser |
| Halifax Regional Police releases | Police context/corroboration | Official | News listing parser |
| HRM official Bluesky | Fast municipal emergency/closure context | Official | Public AT Protocol author-feed adapter |
| Halifax Transit GTFS-Realtime Alerts | Detours/disruption/service alerts | Official | GTFS-RT protobuf |
| 511 Nova Scotia | Road incidents/closures/bridge activity | Official | Public Traffic Events text-report table parser |
| Halifax Water notices | Water/road-work/service notices | Official | Notices parser |
| Environment Canada Halifax Metro/West | Weather alerts | Official | Atom feed |
| Emergency Info Nova Scotia | Active provincial emergencies | Official | Active-event page parser |
| Nova Scotia Power | Outage context | Official map + secondary machine helper | Public read-only secondary API, cards link to official outage map |
| r/halifax | Fast community context | Community | New-post JSON keyword filter; always unverified |

Source definitions live in `config/sources.json`.

## “Likely siren activity”

This is a transparent ranking heuristic, not a claim about the cause of a siren. It gives weight to:

- recent HRFE dispatches;
- incident type (structure fire, MVC/rescue, hazmat, alarms, medical assistance);
- number of responding apparatus;
- recency.

The UI says “likely” and shows the score. If no matching recent official signal exists, the UI says the cause is unknown.

## Architecture

```text
PUBLIC SOURCES
  ↓ independent adapters
NORMALIZED Incident schema
  ↓ retain 48h history
CORRELATION + siren score
  ↓ atomic JSON write
public/data/incidents.json
  ↓
STATIC PWA (timeline + filters + map + source health)
```

The browser does not scrape third parties. This avoids CORS dependence and keeps data provenance in one normalized contract.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/collect.py
python -m unittest discover -s tests -v
python -m http.server 8000 -d public
```

Open `http://localhost:8000`.

## GitHub Pages MVP

Two workflows are included:

- `.github/workflows/refresh.yml` collects data every five minutes, tests it, and commits the generated JSON only when changed.
- `.github/workflows/pages.yml` deploys `public/` to GitHub Pages.

**Operational limitation:** scheduled GitHub Actions are best-effort and can run late. Five-minute cron is acceptable for an MVP, but it is not a hard real-time SLA. For a production version intended to explain sirens within 1–2 minutes, run `python scripts/collect.py` from a continuously available scheduler (for example Azure Functions/Container Apps, Cloudflare/worker-backed ingestion, or another minute-level job runner) and publish the normalized JSON/API from there.

## 511 status

The 511 Nova Scotia map is a JavaScript client, but the service also exposes a public **Traffic Events** text-report page. HFX Pulse parses that table rather than guessing an undocumented map API. A valid text-report page with zero HRM rows is treated as a healthy zero; a missing/changed page contract is surfaced as a source-health error.

## Mapping

The UI maps rows that already contain coordinates. HRFE often publishes only a street/intersection for privacy, so those rows are not fabricated onto a precise point. The collector can add `lat/lon` with `location_precision="approximate_geocode"` through a persistent, rate-limited OpenStreetMap Nominatim cache. New lookups are capped at six per run and serialized; set `HFXPULSE_GEOCODE=0` to disable it. The source street text is never replaced.

## Next production sequence

1. Verify the current HRFE DOM/RSS response from the actual deployment runner and lock a parser fixture from a real response.
2. Verify 511 text-report event rows against a real active-event response and add a captured fixture.
3. Run a 24-hour collection soak and inspect source latency, parser misses and duplicate/correlation behaviour.
4. Move collection to a minute-level runtime if five-minute/best-effort GitHub scheduling is too slow.
5. Add opt-in watch zones and notifications only after source freshness is measured.

## Attribution / data boundaries

Halifax municipal data should be attributed under the Open Government Licence — Halifax where applicable. Each incident retains its source URL. Community reports are unverified. Nova Scotia Power machine-readable outage data is treated as secondary helper data, while the official outage map is the presentation/evidence link.
