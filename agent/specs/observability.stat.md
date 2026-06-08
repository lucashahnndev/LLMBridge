# Observability Stat

Last update date: 2026-06-07

## Current state

- global metrics and per-project metrics are part of the product contract;
- Telegram alerts are required for critical key events;
- the first metrics and alert implementation now exists in code;
- the dashboard UI scaffold now exists in code.

## Pending items

- define the dashboard data model;
- define the Telegram message format and rate limits;
- add validation when the observability pipeline exists;
- refine the frontend dashboard interactions and styling.

## Evidence / validation

- alert triggers recorded;
- global and per-project metric tiers recorded;
- Telegram notification requirement recorded.
- backend/app/routes/observability.py now exposes the first dashboard metrics endpoints.
- backend/app/services/metrics.py now computes global and project metrics from SQLite.
- backend/app/services/alerts.py now sends Telegram alerts when configured.
- frontend/src/routes/+page.svelte now consumes auth and metrics endpoints.

## Commit tracking

- trace_id: `awc-20260607-1624`
- commit status: not done
- hash (optional, after the commit):
- message:
- summary:

## Open risks or doubts

- metric cardinality could grow quickly once many app tokens exist;
- the alert transport may need throttling or deduplication rules later.
- the exact dashboard visualization layer is still lightweight and may need refinement later.

## Related

- [observability.spec](observability.spec.md)
