# HFX Pulse

HFX Pulse is a near-real-time Halifax local-intelligence dashboard built around one practical question: **“I hear sirens / see a closure / notice something unusual downtown — what public signals can explain it right now?”**

The product deliberately collects broadly. First-party dispatch/operational sources, news, automated mirrors, public social posts, Reddit, utilities, traffic, event listings and harbour context are all eligible. **Source quality is shown as provenance; it is not used to hide useful signals by default.**

## Product rules

1. **Broad collection, explicit provenance.** First-party, news, secondary, event and community signals can all appear in the default timeline.
2. **No invented certainty.** A community/news item is never silently converted into a confirmed incident. `corroborated` is reserved for independent first-party records that align in place and time.
3. **Unknown stays unknown.** A failed collector is visible in Source Health. Failure never becomes “0 incidents.”
4. **No unnecessary person tracking.** The Reddit collector does not persist usernames. The app is about incidents and public context, not identifying people involved.
5. **Source time wins.** When a source provides an event/publication timestamp, the collector preserves it instead of substituting the scrape time.
6. **Independent failures.** Every source adapter is isolated; one broken website does not take down the collection run.
7. **Not a 911 service.** Public feeds can be delayed, incomplete or wrong.

## Current collector surface

The MVP has **18 collector paths** covering:

- Halifax Regional Fire & Emergency live incident feed;
- HRFE Incident Initial Response open-data layer;
- Halifax Regional Police releases;
- RCMP Nova Scotia releases filtered to HRM;
- Halifax Transit GTFS-Realtime alerts;
- 511 Nova Scotia traffic events;
- Halifax Harbour Bridges traffic/closure page;
- Halifax Water notices;
- Environment Canada Halifax alerts;
- Emergency Info Nova Scotia;
- Nova Scotia Power outage context;
- HRM official Bluesky;
- Halifax Fire / Transit / Events, Halifax Noise and automated HRFE Bluesky accounts;
- broad public Bluesky searches for Halifax sirens/fire/police/ambulance/crash/emergency terms;
- `r/halifax` and HRM-relevant `r/NovaScotia` posts;
- Global Halifax plus Google News, Bing News, CityNews and Waterfront Media RSS/feed attempts;
- Downtown Halifax same-day event listings;
- Port of Halifax same-day cruise schedule context.

The canonical source registry is `config/sources.json`. Runtime compatibility is shown in the app’s Source Health panel.

## “Likely siren activity”

This is a transparent ranking heuristic, not a declaration of cause. Direct dispatch data receives the strongest weight. Community, news and social text can also contribute when it explicitly mentions sirens, police, fire, ambulance/EHS, rescue, collision, weapons or similar emergency activity, but their maximum score is deliberately lower than a strong direct HRFE dispatch.

If no recent downtown signal scores above zero, the UI says the cause is **unknown**. That is not evidence that nothing happened.

## Architecture

```text
PUBLIC WEB / FEEDS / SOCIAL / COMMUNITY
        ↓
18 independent adapters (parallel fetch)
        ↓
normalized Incident schema + SourceHealth
        ↓
48-hour retention + approximate geocode cache
        ↓
place/time correlation + siren likelihood
        ↓
public/data/incidents.json (atomic write)
        ↓
static PWA: timeline + map + filters + source health
```

The browser does not scrape third parties directly. GitHub Actions runs the collector server-side and GitHub Pages only serves the normalized static output.

## Local verification

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q hfxpulse scripts tests
node --check public/assets/app.js
HFXPULSE_GEOCODE=0 python scripts/collect.py
python -m http.server 8000 -d public
```

## GitHub automation

- `.github/workflows/ci.yml` runs unit/syntax checks and a real network source-compatibility smoke test on branches and pull requests. HRFE and Halifax Transit are critical-path sources for merge readiness; other source failures remain visible but do not block the entire app.
- `.github/workflows/refresh.yml` refreshes the generated dataset every five minutes on `main`, validates the code, and commits data only when changed.
- `.github/workflows/pages.yml` deploys `public/` to GitHub Pages whenever app/data content changes.

GitHub scheduled workflows are **best-effort**, so `*/5 * * * *` is not a guaranteed five-minute SLA. If measured latency is not good enough after a soak test, move ingestion to a minute-level Azure job/function and leave Pages as the presentation layer.

## Data boundaries

- HRFE open data documents a display-time offset issue. HFX Pulse preserves its supplied timestamp and does **not** guess a correction.
- Nova Scotia Power uses a secondary machine-readable helper for ingestion while linking incident cards to the official outage map.
- Reddit/Bluesky community searches are intentionally broad and can contain incorrect or speculative statements; provenance labels are part of the product contract.
- Approximate geocoding never replaces the original source location text. Set `HFXPULSE_GEOCODE=0` to disable new network geocoding.
