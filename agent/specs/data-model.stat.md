# Data Model Stat

Last update date: 2026-06-11

## Current state

- the persistent model has been extracted from the product brief into a dedicated spec;
- the system now has a named contract for provider keys, app tokens, and usage logs;
- the model now has an initial SQLAlchemy async scaffold in code;
- the public schema rules for masking and controlled reveal are now explicit;
- the Pydantic schema layer is now scaffolded in code;
- the first CRUD API routes for the data model now exist in code.
- the architectural contract now requires explicit separation between provider/model priority state and key/provider/model operational availability state.
- the legacy `ProviderKeyModelCooldown` table is now considered deprecated compatibility storage, while `provider_key_route_states` is the operational source of truth.

## Pending items

- define migrations when implementation begins;
- validate the final field names against the first real endpoints.
- decide the final persistent shape for:
  - provider/model rank inputs;
  - key/provider/model cooldown and disable state;
  - balancing metadata such as `in_flight_count`, `last_used_at`, and optional reservation timestamps.

## Evidence / validation

- ProviderKey, AppToken, and UsageLog were formalized as the three core entities;
- masking and peek behavior were captured as schema contracts;
- persistence and analytics roles were separated cleanly.
- backend/app/database/models.py now contains the first SQLAlchemy model scaffold;
- backend/app/database/session.py and backend/app/database/bootstrap.py now connect the async engine to startup.
- backend/app/schemas/ now contains the initial Pydantic schema layer.
- backend/app/routes/provider_keys.py, backend/app/routes/app_tokens.py, and backend/app/routes/usage_logs.py now expose the first CRUD surface.

## Commit tracking

- trace_id: `awc-20260607-1624`
- commit status: not done
- hash (optional, after the commit):
- message:
- summary:

## Open risks or doubts

- the exact database column types may still be refined during implementation;
- dashboard summary payloads may later need to be split if reporting grows;
- usage-log cardinality could become large and may require indexing decisions later;
- the API routes now exist, but they still need real authentication, validation, and business rules layered on top.
- the current first-pass schema does not yet express the full redesigned split between rank state and key availability state.

## Related

- [data-model.spec](data-model.spec.md)
