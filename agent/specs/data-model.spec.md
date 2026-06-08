# Data Model Spec

This spec defines the persistent entities and public data-shape contracts for the system.

## Contract

- the persistent model centers on `ProviderKey`, `AppToken`, and `UsageLog`;
- `ProviderKey` is the external-secret entity for provider API keys;
- `AppToken` is the internal client-token entity for local projects or apps;
- `UsageLog` is the request-level audit and metrics entity that ties usage to both app and provider context;
- the model must support provider-key rotation, cooldown expiry, invalidation, and billing suspension states;
- the model must support per-app consumption tracking and global operational analytics;
- the model must preserve enough information to calculate latency, token usage, retry behavior, and rotation events;
- admin-facing payloads must never expose raw provider secrets by default;
- provider-key reveal requires an explicit security step and must be represented as a distinct request/response contract;
- the data model must be compatible with async database access and local SQLite storage in the first implementation.

## Entity contract

### ProviderKey

- identity and metadata: `id`, `name` or `label`, `description`, `provider`;
- secret storage: `encrypted_token`;
- lifecycle state: `status`, `blocked_until`, `failure_count`;
- timestamps: created and updated timestamps;
- relation: one provider key can be referenced by many usage records.

### AppToken

- identity and metadata: `id`, `name`, `environment`;
- authorization secret: `token`;
- lifecycle state: `is_active`;
- throttling metadata: optional `rpm_limit`;
- timestamps: created timestamp;
- relation: one app token can be referenced by many usage records.

### UsageLog

- request context: `app_token_id`, optional `provider_key_id`, `model_requested`, `provider_used`;
- volume metrics: `prompt_tokens`, `completion_tokens`, `total_tokens`;
- performance metrics: `latency_ms`;
- request outcome: `status_code`, `was_rotated`, optional `error_message`;
- timestamp: created timestamp;
- relation: each usage log belongs to one app token and optionally one provider key.

## Schema contract

- create schemas may accept clear-text provider tokens only at creation time;
- list and response schemas for provider keys must expose a masked token rather than the raw secret;
- a provider-key peek schema must require an explicit admin re-authentication or equivalent consent field;
- app-token creation may omit the actual token value from the request, because the backend can generate it;
- app-token response schemas may expose the token only under controlled administrative conditions;
- dashboard schemas must expose global metrics and per-project metrics as distinct payloads.

## Scope notes

- this spec defines persistence-facing shape, not business logic routing;
- proxy selection rules live in `proxy.spec.md`;
- secret handling rules live in `vault.spec.md`;
- admin session rules live in `admin.spec.md`;
- the API may add helper fields, but it must preserve the contract above.

## Related

- [project.spec](project.spec.md)
