# Verification status

## November 10, 2026 refresh

The reliability refresh is verified with:

- 74 Python unit/parser/scoring tests, including captured Halifax Water notice cards, publication clock/DST, archive timestamps, duplicate cards, and missing-date boundaries.
- Ten Node refresh regression tests: unchanged stale data, background failures, overlapping requests, malformed and older payloads, recovery, timeouts, future-dated publications, partial rendering failures and the checked-in publication contract.
- Python compile and JavaScript syntax checks.
- Live collection and source-health inspection. HRFE and Halifax Transit must be healthy; an all-green workflow alone is insufficient.

The app preserves source evidence, ignores Reddit author identities, and does not interpret an unavailable source as zero incidents. Water archive rows explicitly identify updated rather than published source times. The 48-hour retention gate still excludes old archive records.

## Release checks

Before claiming deployment, verify the exact remote commit, passing branch CI, successful Pages publication and the live asset/data response. Check the live timeline, filters, refresh control and source-health panel. Local unit tests do not constitute a deployed browser check.

The existing branch-based Pages publisher serves the canonical app at `public/`. The repository root redirects there.

## Known operational limits

- The Port of Halifax schedule has returned HTTP 403. Its source-health error remains visible. No alternate route is used to evade the denial.
- GitHub scheduled Actions are best-effort. Although the workflow requests a five-minute cadence, the last observed scheduled runs on November 8–9 were hours apart. No five-minute service guarantee is established.
- The app's refresh button checks for a newer published JSON dataset. It does not run collectors from the browser.
- Optional adapters can be unhealthy or return legitimately empty results. Source-health counts are observations from their displayed check times, not a promise that every source remains available.
