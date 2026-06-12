# Queue, Cooldown, Rank, and Key Distribution Redesign

Status: approved architectural direction, pending implementation

## Objective

The routing core must stop treating availability, priority, and key selection as the same concern.

The redesign separates the system into three distinct decision layers:

- availability is decided by `key/provider/model`;
- priority is decided by `provider/model`;
- key distribution is decided by `key`.

This split exists to make rate-limit handling precise, ranking stable, and request execution cheap.

## Operational source of truth

`provider_key_route_states` is the operational source of truth for:

- `cooldown_until`
- `blocked_until`
- `disabled`
- `disabled_reason`
- balancing metadata such as `last_used_at`, `in_flight_count`, `soft_reserved_until`, and `next_available_at`

`ProviderKeyModelCooldown` remains only as a deprecated compatibility table during migration.

It may still receive mirrored writes from legacy wrappers, but it must not be the hot-path source for:

- queue/provider snapshot filtering
- cooldown exhaustion semantics
- `Retry-After` calculation
- structural availability decisions

## Migration status

The migration is intentionally gradual:

- the executor and snapshot materializer must read from `provider_key_route_states` first;
- the background classifier must update `provider_key_route_states` first;
- legacy wrappers may mirror state into `ProviderKeyModelCooldown` only for compatibility;
- tests may still assert legacy bridge behavior, but the operational outcome must come from the new table;
- `ProviderKeyModelCooldown` is now deprecated and should be treated as a compatibility-only artifact.

## Final architecture

### 1. Availability

Availability is operational and reactive.

It answers:

- can this exact `key/provider/model` be used now?

Availability belongs to `key/provider/model` because rate-limit, permission, billing, and model-access failures frequently affect only one key in one route context.

The minimum availability fields are:

- `cooldown_until`
- `blocked_until`
- `disabled`
- `disabled_reason`

Optional balancing and local-throttling fields may exist in the same operational record:

- `last_used_at`
- `use_count_window`
- `in_flight_count`
- `soft_reserved_until`
- `next_available_at`

### 2. Priority

Priority is logical and comparative.

It answers:

- if several routes are available, which `provider/model` should appear first in the fallback order?

Priority belongs to `provider/model`, not to the key.

The rank must be a normalized decimal composition, for example:

```txt
rank =
  latency_score * weight_latency
+ error_score * weight_error
+ base_degradation * weight_base
```

Where lower values mean higher priority.

Rank may consider:

- normalized latency pressure
- normalized transient upstream instability
- manual base degradation

Rank must not consider:

- per-key cooldown
- per-key disable state
- per-key auth problems

### 3. Key distribution

Key distribution is preventive.

It answers:

- inside one `provider/model`, which eligible key should receive the next request?

Distribution belongs to keys because repeated selection of the first available key creates avoidable RPM concentration.

Acceptable strategies include:

- round-robin
- least-used
- `last_used_at ASC`
- `in_flight_count ASC`

Recommended starting order:

```sql
ORDER BY
  in_flight_count ASC,
  last_used_at ASC NULLS FIRST
```

The purpose is not to change the preferred `provider/model`; it is to spread load across keys within the chosen route.

## Cooldown

Cooldown is not score.

Cooldown is an upstream-imposed temporary unavailability window at `key/provider/model`.

When the provider returns a recoverable retry signal, such as:

```txt
Please retry in 393.337641ms
Please retry in 1.364102686s
Please retry in 8.221904517s
Please retry in 54.895152423s
```

the provider parser must extract the delay, convert it into an absolute timestamp, and save:

```txt
cooldown_until = now + retry_delay
```

This avoids trying to infer whether the provider used RPM, RPD, TPM, or another hidden window. The only operational truth we need is:

```txt
this key/provider/model is unavailable until cooldown_until
```

### Why cooldown never enters rank

Cooldown is temporary availability. Rank is structural preference.

If cooldown affected rank, a model could be pushed down permanently for a short temporary outage, which would distort the queue long after the provider window expired.

## Disabled and blocked state

### 401 and 403

`401` and `403` must not degrade `provider/model`.

They normally indicate:

- invalid key
- missing permission
- billing problem
- blocked project
- no access to that model on that key

So they must disable or block `key/provider/model`, for example:

```txt
disabled = true
disabled_reason = unauthorized | forbidden | billing_required | model_not_allowed
```

or:

```txt
blocked_until = timestamp
```

### 404

`404` must be classified by context:

- if the error means the model truly does not exist or the capability is unsupported upstream, it may degrade or disable `provider/model`;
- if the error means one key lacks access to that model, it should disable only `key/provider/model`.

### 400

`400` caused by payload incompatibility must not automatically degrade the route.

That failure belongs first to:

- adapter compatibility
- request shape
- capability mismatch

Only after classification should the system decide whether a route-level capability should be degraded.

## Request execution contract

The executor must be dumb on purpose.

It must not:

- recalculate rank
- decide balancing
- filter cooldown
- reinterpret disable state

It must only consume an already prepared ordered fallback list.

The heavy logic belongs before or after request execution, not inside the hot path.

### Materialized snapshot cache

The request path should read a materialized route snapshot from cache whenever possible.

- the snapshot is prepared outside the hot path;
- request execution should not sort or filter the full candidate pool;
- background classification and refresh jobs update the cache for the next request;
- cold-miss fallback may exist only as a bootstrap safety net, not as the normal decision path.

## Background classifier

After the client response is completed, the proxy must emit a post-request classification event to a background classifier.

The classifier is responsible for refreshing operational state without forcing the request hot path to do every calculation inline.

The classifier updates:

- `cooldown_until`
- `blocked_until`
- `disabled`
- `disabled_reason`
- provider/model latency inputs
- provider/model error inputs
- `last_used_at`
- `in_flight_count`
- optional balancing hints like `soft_reserved_until` or `next_available_at`

This means:

- request `N` consumes a materialized candidate order;
- request `N` finishes;
- the background classifier updates state;
- request `N+1` sees the new order.

## Queue route behavior

For `queue/{queue_name}`:

1. load the queue's logical `provider/model` candidates;
2. expand each candidate into available `key/provider/model` combinations;
3. discard disabled, blocked, and cooling-down combinations;
4. sort logical `provider/model` candidates by rank;
5. within each `provider/model`, distribute keys by balance strategy;
6. flatten the result into a final ordered fallback list;
7. deliver only the clean list to the executor.

Internal expanded view:

```js
[
  { key: "key1", provider: "google", model: "model1", cooldown_until: null, rank: 0.10 },
  { key: "key2", provider: "google", model: "model1", cooldown_until: null, rank: 0.10 },
  { key: "key3", provider: "google", model: "model1", cooldown_until: "2026-06-11T22:10:00Z", rank: 0.10 }
]
```

Executor view:

```js
[
  { key: "key1", provider: "google", model: "model1" },
  { key: "key2", provider: "google", model: "model1" }
]
```

## Direct provider/model route behavior

For direct `provider/model` routes:

1. do not rank across models, because the route was chosen explicitly;
2. load available keys for that exact route;
3. remove disabled, blocked, or cooling-down keys;
4. balance eligible keys;
5. execute;
6. emit the result to the background classifier.

Direct routes must still distribute across keys and must not pin all traffic to the first key forever.

## Exhaustion semantics

### All candidates in cooldown

If every otherwise valid candidate is in cooldown:

- return `HTTP 429`
- compute `Retry-After` from the smallest recoverable `cooldown_until`

This tells the client the earliest time at which at least one usable `key/provider/model` should exist again.

### All candidates disabled or blocked

If every candidate is structurally unavailable:

- do not return `429`
- return a structural route error such as:
  - `route_unavailable`
  - `config_error`
  - `pool_unavailable`

This communicates that the problem is not temporary quota exhaustion.

## Invariants

The implementation must preserve these invariants:

- cooldown never enters rank
- rank is never stored per key
- `401/403` never degrade `provider/model` directly
- direct `provider/model` routes always balance keys
- named queues always deliver an already filtered and ordered list
- all-cooldown exhaustion returns `429` with the smallest recoverable `Retry-After`
- all-disabled or blocked exhaustion does not return `429`
- the executor never receives candidates in cooldown, disabled, or blocked state
- the background classifier is the component responsible for refreshing operational state after request completion

## Why this redesign matters

Without this split, the system tends to conflate:

- temporary rate-limit windows
- structural model preference
- key-specific auth problems
- distribution fairness

That causes slow recovery, noisy scoring, misleading telemetry, and avoidable `429` concentration.

With the split:

- availability stays precise
- ranking stays meaningful
- keys are spread preventively
- the hot path gets simpler
- queue behavior becomes easier to reason about and test
