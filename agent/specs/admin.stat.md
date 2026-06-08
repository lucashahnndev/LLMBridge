# Admin Stat

Last update date: 2026-06-07

## Current state

- admin access is defined as JWT-based in the contract;
- app tokens are part of the product scope;
- implementation details are still open;
- the backend now exposes JWT login, logout, and admin-auth guard routes.
- the admin panel now exposes a backend runtime settings surface for host/port updates and core resource management.
- the admin panel now exposes provider-key lifecycle actions and app-token enable/disable control.
- the admin panel now also exposes inline editing for provider-key and app-token metadata.
- the admin panel now remembers the active section and current filter state across reloads.
- the admin panel now supports bulk selection and bulk actions for provider keys and app tokens.
- the admin panel now supports an admin-confirmed peek flow for provider-key secrets.
- the admin panel now shows context-rich detail panels for selected provider keys and app tokens.
- the admin panel now auto-refreshes and shows backend health.
- the admin panel now surfaces action feedback through in-app notifications.
- the admin panel now keeps a recent activity timeline in the overview.
- the admin panel now has a more polished hero and summary-card presentation.
- the admin panel now aligns its cards, tables, and detail surfaces into a more cohesive visual system.
- the admin panel now refines typography, focus states, and microinteractions across the dashboard.
- the admin panel now lives in a dedicated `/app` shell with a separate `/login` entry screen.
- the admin panel now has a top bar with operator profile, logout, and theme switching.
- the admin panel now uses a muted gray-and-amber technical visual language instead of a neon SaaS look.
- the admin panel now favors flat layouts, thin borders, tight radii, and minimal visual noise.

## Pending items

- add UI and integration tests when the panel exists.
- add a restart affordance later if runtime configuration changes should be applied without manual service control.

## Evidence / validation

- JWT requirement recorded;
- app-token metadata fields recorded;
- admin boundary separated from provider routing and vault storage.
- backend/app/routes/auth.py now exposes the first admin login surface.
- backend/app/services/auth.py now validates bearer JWTs for protected routes.
- backend/app/routes/auth.py now exposes logout-based JWT revocation.
- backend/app/routes/admin.py now exposes runtime settings for host/port management.
- frontend/src/routes/+page.svelte now includes the runtime settings panel and core resource lists.
- frontend/src/routes/+page.svelte now exposes provider-key lifecycle buttons and app-token toggles.
- frontend/src/routes/+page.svelte now supports inline editing for provider-key and app-token metadata.
- frontend/src/routes/+page.svelte now persists the active section and filter state in local storage.
- frontend/src/routes/+page.svelte now supports bulk selection and bulk actions for provider keys and app tokens.
- frontend/src/routes/+page.svelte now supports an admin-confirmed provider-key peek flow.
- frontend/src/routes/+page.svelte now shows context-rich detail panels for selected provider keys and app tokens.
- frontend/src/routes/+page.svelte now auto-refreshes and shows backend health.
- frontend/src/routes/+page.svelte now surfaces action feedback through in-app notifications.
- frontend/src/routes/+page.svelte now keeps a recent activity timeline in the overview.
- frontend/src/routes/+page.svelte now has a more polished hero and summary-card presentation.
- frontend/src/routes/+page.svelte now aligns cards, tables, and detail surfaces into a more cohesive visual system.
- frontend/src/routes/+page.svelte now refines typography, focus states, and microinteractions across the dashboard.
- frontend/src/routes/login/+page.svelte now provides the dedicated login screen.
- frontend/src/routes/app/+page.svelte now provides the dedicated admin shell.
- frontend/src/routes/app/+page.svelte now provides a top bar with operator profile, logout, and theme switching.

## Commit tracking

- trace_id: `awc-20260607-1624`
- commit status: not done
- hash (optional, after the commit):
- message:
- summary:

## Open risks or doubts

- the exact admin roles and authorization model are not yet specified;
- session storage strategy is intentionally deferred.

## Related

- [admin.spec](admin.spec.md)
