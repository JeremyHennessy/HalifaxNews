# Collection freshness diagnostics

`collection_run` records actual collector invocation/completion clocks, monotonic elapsed time, and the gap from the previous snapshot generation to this collection start. Missing/invalid prior clocks remain unknown; future clocks are flagged and do not become a negative gap. This is not an authenticated scheduler receipt or proof of public deployment.

A five-minute cron expression is a request, not evidence of five-minute collection. Inspection on 2026-11-15 found successful scheduled runs at 2026-11-14 19:52, 23:38 and 2026-11-15 03:05 UTC; push-triggered runs also occurred. These observations do not establish why intervening scheduled runs were absent. Pages successfully deployed the 04:09 refresh commit at 04:10, so a Pages failure was not demonstrated for that run. This change does not alter schedules or promise lower latency.

The port cruise collector remains access-blocked (HTTP 403 observed). The canonical Port Halifax page also returned 403 during research; no alternate-host bypass, identity disguise, or retry loop was added. This patch does not claim to restore that feed. It prevents an HTTP-200 denial/unrecognized page from becoming a healthy zero, requires one recognizable schedule table, reads the dedicated passenger column, and requires a complete explicit calendar date rather than guessing a year or day from a partial date. Supporting yearless schedules requires verified season context, which is currently absent. A failed source remains unknown, not proof of no cruise calls.

No police, closure lifecycle, severity or incident classification rules change.
