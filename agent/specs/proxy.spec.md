# Proxy Spec

This spec defines the request-routing and translation contract for the unified LLM proxy.

## Contract

- the proxy accepts a provider-agnostic request shape compatible with OpenAI-style chat completions;
- the `model` value is normalized as `provider/model-name`;
- the proxy resolves the provider prefix to a driver;
- each driver translates the normalized request into the provider-native API shape;
- each driver translates the provider-native response back into the normalized response shape;
- the proxy may also expose an Anthropic-compatible `/v1/messages` adapter that maps Anthropic-style requests into the same internal routing core and maps the response back into Anthropic-style output;
- the routing core must remain protocol-neutral so the same provider/model and queue resolution rules can serve OpenAI-style and Anthropic-style public adapters;
- the proxy must not leak provider-specific request details to the client-facing contract;
- the proxy should preserve tool-calling structure, tool-call IDs, message ordering, finish reason, response intent, and route metadata across protocol conversions;
- the proxy uses a richer canonical internal IR that keeps messages, tools, routing target, generation settings, attachments, metadata, telemetry, and optimization policy separated;
- optional metadata cleanup may compress or drop non-essential provider noise before the payload reaches the model adapter, but this behavior must be explicitly enabled, must be policy-driven, and must never remove routing or tool semantics;
- the Google adapter must build Gemini native `generateContent` requests from the canonical IR instead of routing through an internal OpenAI-like payload, while still accepting OpenAI-like and Anthropic-compatible public requests at the edge;
- when a public streaming request targets Google, the proxy may use a non-stream native Gemini request and return a normalized SSE stream at the edge until native `streamGenerateContent` is fully validated;
- the Google adapter should strip provider-transport noise such as `thinking`, `context_management`, `output_config`, `metadata`, and similar envelope-only fields before the request reaches Gemini, while preserving the conversation body and tool semantics;
- the Google adapter must compact tool schemas into Gemini-compatible `functionDeclarations`, preserving usable properties and required fields while dropping unsupported JSON Schema keywords that cause upstream `400` failures;
- the Google adapter must not replay historical tool calls from Anthropic/OpenAI/Ollama clients as Gemini native `functionCall`/`functionResponse` parts unless those parts originated from Gemini and include valid Gemini `thoughtSignature` data; foreign historical tool calls/results must be rendered as compact text context while future callable tools remain declared through `functionDeclarations`;
- optional per-request trace capture may persist the raw client payload, canonical IR, provider payload, provider response, and final normalized result as a redacted JSON artifact for debugging and comparison;
- when a provider returns `429`, the proxy treats the failure as a rate-limit event and retries with another eligible key when available;
- retry behavior must stop when the configured attempt or eligibility limit is reached;
- if no eligible key remains, the proxy returns the upstream failure in a controlled way.
- the proxy may also accept `queue/{queue-name}` as a higher-level routing alias that resolves to an ordered list of `provider/model-name` candidates;
- queue resolution must preserve `provider/model-name` as the real provider route and must only add orchestration above it;
- queue strategies may reorder candidates by fixed priority, latency, or history-backed score, but they must still fall back to the real provider/model routes beneath them;
- queue-level fallback must advance to the next candidate when the current candidate fails for a retryable upstream reason or exhausts its quota;
- queue routing must not replace the provider/model contract; it wraps it.
- public adapters must preserve telemetry fields that identify the source protocol, sink protocol, selected route kind, resolved route, queue name, and tool-calling behavior.
- queue orchestration must separate three different decisions:
  - availability is decided at `key/provider/model`;
  - priority is decided at `provider/model`;
  - key distribution is decided at `key`;
- the request executor must not recalculate queue ranking, key eligibility, or balancing rules during the hot path; it must consume an already prepared ordered candidate list;
- when the public route targets `queue/{queue-name}`, the system must:
  - resolve candidate `provider/model` routes configured on the queue;
  - discard `key/provider/model` combinations that are disabled, blocked, or cooling down;
  - sort `provider/model` routes by rank;
  - balance eligible keys inside each `provider/model`;
  - deliver a flat ordered fallback list to the executor;
- when the public route targets a direct `provider/model`, the system must not rank across models, but it must still balance eligible keys for that exact route;
- `cooldown_until` is a reactive availability field at `key/provider/model` and must be derived from explicit upstream retry signals such as `Retry-After` headers or provider-specific `Please retry in ...` messages;
- cooldown must never participate in the rank formula;
- upstream `429` with explicit retry must update `cooldown_until` at `key/provider/model` rather than permanently degrading the route;
- upstream `401` and `403` must disable or block `key/provider/model` without degrading the parent `provider/model` rank, because those failures usually describe authentication, permission, billing, or model-access problems tied to the key;
- upstream `404` that clearly indicates model absence or unsupported capability may degrade or disable `provider/model`, while `404` caused by key-specific access restrictions may disable only `key/provider/model`;
- upstream `400` caused by payload incompatibility must not automatically degrade `provider/model`; it must be classified as adapter or request compatibility failure until proven otherwise;
- recurrent `5xx` or similar upstream transient failures may temporarily degrade `provider/model` rank, but that degradation is separate from cooldown and must decay independently;
- rank at `provider/model` must be a normalized decimal composition that may consider latency, transient error pressure, and manual base degradation;
- keys inside a given `provider/model` must be distributed preventively by balanced selection, such as least-used, `in_flight_count` ascending, `last_used_at` ascending, round-robin, or an equivalent deterministic strategy that avoids repeatedly selecting the same key first;
- key balancing and cooldown serve different goals:
  - cooldown is reactive after the provider already refused a request;
  - key balancing is preventive and aims to reduce avoidable `429` concentration;
- if all otherwise valid candidates for a route are cooling down, the proxy must return `429` and compute `Retry-After` from the smallest recoverable `cooldown_until` across the unavailable candidates;
- if all candidates are disabled or blocked without known temporal recovery, the proxy must return a structural route-unavailable style error instead of `429`;
- after each request completes, the proxy must emit a post-request classification event that updates operational state outside the hot path;
- the post-request classifier may run in background after the client response is sent, but it must still be responsible for refreshing:
  - `cooldown_until`;
  - disabled or blocked flags;
  - provider/model latency and error rank inputs;
  - per-key balancing metadata such as `last_used_at`, `in_flight_count`, and optional soft reservation state;
- the next request must consume a materialized queue snapshot produced from the latest committed operational state rather than recalculating the whole decision tree during execution;
- the request path should read the materialized snapshot cache and avoid rebuilding the full candidate order unless a cold-miss bootstrap fallback is unavoidable.
- `ProviderKeyModelCooldown` may still exist for compatibility during migration, but the proxy hot path must treat `provider_key_route_states` as the source of truth for availability and exhaustion decisions.

## Scope notes

- routing by provider prefix is a contract, not an implementation detail;
- the provider registry can grow without changing the client-facing API shape;
- failover is transparent only while another eligible key exists.
- queue aliases are a product-level orchestration layer, not a replacement for provider/model routing;
- the queue layer can evolve independently from the provider drivers and key-rotation rules.

## Related

- [project.spec](project.spec.md)
