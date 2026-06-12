# Data Model Spec

This spec defines the persistent entities and public data-shape contracts for the system.

## Contract

- the persistent model centers on `ProviderKey`, `AppToken`, and `UsageLog`;
- `ProviderKey` is the external-secret entity for provider API keys;
- `AppToken` is the internal client-token entity for local projects or apps;
- `UsageLog` is the request-level audit and metrics entity that ties usage to both app and provider context;
- the persistent model must also represent:
  - queue-level provider/model priority state;
  - key/provider/model availability state;
  - key-balancing metadata used to avoid preventable request concentration;
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
- provider-level timestamps used by balancing and lifecycle cleanup may exist in related operational tables rather than directly on the base entity;
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

### Queue Provider/Model Priority

- each queue candidate represents a logical `provider/model` route inside a named queue;
- this entity owns queue-local priority inputs such as:
  - `base_degradation`;
  - normalized latency score inputs;
  - normalized transient error score inputs;
  - derived rank or equivalent sortable priority value;
- queue priority state must not be duplicated per key;
- cooldown and key disable state must not live on this entity.

### Key/Provider/Model Availability

- the model must represent operational availability at `key/provider/model`;
- this state must support:
  - `cooldown_until`;
  - `blocked_until`;
  - `disabled`;
  - `disabled_reason`;
  - optional recoverability hints;
- this state may also store balancing metadata such as:
  - `last_used_at`;
  - `use_count_window`;
  - `in_flight_count`;
  - `soft_reserved_until`;
  - `next_available_at`;
- cooldown, block, and disable state must be queryable so the executor never receives ineligible candidates.

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
- the exact table split may evolve, but the contract must preserve the architectural separation:
  - priority at `provider/model`;
  - availability at `key/provider/model`;
  - balancing metadata at `key/provider/model` or an equivalent operational store.
- `ProviderKeyModelCooldown` is deprecated compatibility-only storage and must not be treated as the operational source of truth once `provider_key_route_states` is available.

## Related

- [project.spec](project.spec.md)
