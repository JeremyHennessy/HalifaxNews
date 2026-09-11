# Verification status

Build checkpoint: initial HFX Pulse MVP package.

## Confirmed in the build environment

- Python source compiles successfully.
- JavaScript passes `node --check`.
- Seven unit tests pass:
  - HRFE public-label incident parsing;
  - HRFE collision classification;
  - 511 Traffic Events table parsing and HRM filtering;
  - Environment Canada Atom parsing;
  - two-official-source correlation;
  - community reports cannot create official corroboration;
  - street normalization.
- Collector adapters are independently guarded: one adapter exception produces a Source Health error instead of stopping the complete run.
- Generated data writes atomically through a temporary file.
- Community ingestion does not retain Reddit usernames.

## Not yet confirmed

- Live end-to-end adapter compatibility from a networked runtime. The current build environment cannot resolve external internet hosts, so it cannot truthfully validate the live HRFE/HRP/GTFS/511/etc. responses.
- A visual browser acceptance screenshot. The available headless Chromium process did not complete reliably in this environment.
- GitHub Pages deployment. No target repository was specified, and the connected GitHub tooling can write to existing repositories but cannot create a new repository.
- Minute-level freshness. GitHub Actions includes a five-minute schedule, but scheduled Actions are best-effort and can be delayed.

## First deployment acceptance gate

Do not call the app live/verified until all of the following pass from the deployment environment:

1. `python scripts/collect.py` completes.
2. Source Health is inspected source by source; an all-green workflow alone is insufficient.
3. At least one real HRFE incident is compared field-by-field with the official incident page.
4. A real 511 event (when available) is compared with the Traffic Events text report.
5. GTFS-Realtime alerts decode without protobuf/schema errors.
6. Generated timestamps are source event times where provided, not rebuild times.
7. Desktop and iPhone layouts are visually checked.
8. GitHub Pages serves `public/data/incidents.json` without caching it stale.
9. The refresh workflow is observed for at least 24 hours to measure actual schedule delay and scraper stability.
