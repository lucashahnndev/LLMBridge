# Proxy Stat

Last update date: 2026-06-11

## Current state

- a public OpenAI-style chat completions route now exists at `/v1/chat/completions`;
- the request model is validated and the `model` field is parsed as `provider/model-name`;
- the proxy now also resolves `queue/{queue-name}` aliases to ordered provider/model candidates before executing a route;
- the proxy contract now includes an Anthropic-compatible `/v1/messages` adapter that reuses the same internal routing core;
- the proxy telemetry contract now records protocol-in/protocol-out, route kind, resolved route, queue name, and tool-calling state;
- the architecture and docs now describe a richer canonical IR that preserves tool calls, ordering, and response intent while allowing optional metadata cleanup;
- the Google adapter now sends non-stream requests through Gemini native `generateContent` from the canonical IR, avoiding an internal OpenAI-like hop for Google targets;
- Google streaming requests now use the same native canonical-to-Gemini payload path and return a normalized SSE stream from the proxy edge;
- the Google adapter now compacts Gemini tool schemas into native `functionDeclarations`, filtering unsupported JSON Schema keys while preserving tool semantics;
- the Google adapter now strips provider-transport noise such as `thinking`, `context_management`, `output_config`, and `metadata` before sending requests upstream, while keeping the message/tool payload intact;
- the Google adapter now renders foreign historical tool calls/results as text context instead of native Gemini `functionCall`/`functionResponse`, because Gemini rejects replayed function history without valid provider-issued `thoughtSignature` data;
- an optional per-request trace artifact can now record raw client input, canonical IR, provider payloads, provider responses, and final normalized output in redacted JSON files;
- app-token authentication is required for proxy requests;
- provider-key selection and retry-on-`429` behavior are implemented at the scaffold level;
- usage logging is recorded for proxy requests;
- streaming chat-completions requests are proxied as `text/event-stream`;
- the route format keeps `provider/model-name` as the real provider route while `queue/{queue-name}` acts as an orchestration alias;
- Anthropic-compatible public routing is now available and maps into the same internal route resolver.
- the architectural redesign for queue routing is now specified:
  - availability at `key/provider/model`;
  - rank at `provider/model`;
  - preventive balance at `key`;
- the proxy contract now also requires a post-request background classifier to refresh cooldown, disable state, latency inputs, error inputs, and balancing metadata outside the request hot path.
- the new operational source of truth is `provider_key_route_states`; the legacy `ProviderKeyModelCooldown` table remains only for compatibility during migration.

## Pending items

- replace the current Google SSE bridge with true Gemini `streamGenerateContent` once native stream payloads and chunk semantics are fully validated;
- refine provider-specific driver translation rules as upstream integrations are exercised;
- expand integration tests as new providers, adapters, or queue behaviors are added;
- document Claude Code usage now that the Anthropic adapter and telemetry fields are in place;
- decide whether canonical IR cleanup policies should become configurable per route or per app token;
- decide whether trace capture should eventually support per-route retention windows or sampling knobs;
- tune retry/backoff defaults against real provider behavior.
- implement the new queue and direct-route execution flow against the redesigned contract;
- introduce materialized candidate preparation so the executor consumes prefiltered and preordered lists;
- wire provider-specific retry parsing into `cooldown_until` updates at `key/provider/model`;
- split route-level rank data from key-level operational availability data;
- define how direct `provider/model` routes expose structural exhaustion versus temporary cooldown exhaustion.

## Evidence / validation

- proxy contract extracted from the product brief;
- provider abstraction and translation rules recorded;
- FastAPI route scaffold implemented for `/v1/chat/completions`;
- app-token auth and provider-key rotation scaffold implemented;
- streaming proxy support implemented for `stream=true`;
- Anthropic-compatible `/v1/messages` adapter added and covered by backend unit tests;
- backend syntax validated with `python3 -m py_compile`.
- backend unit tests cover token helpers, proxy parsing helpers, and the driver registry.
- focused tests now cover canonical IR, Google native tool-calling payload generation, proxy Google tool-calling normalization, and Gemini replay payload helpers.
- replay validation against a real Gemini trace returned HTTP 200 after foreign tool history was compacted to text context while callable tools stayed available as Gemini `functionDeclarations`.
- trace capture still needs end-to-end validation on streaming Anthropic responses.

## Commit tracking

- trace_id: `awc-20260607-1624`
- commit status: not done
- hash (optional, after the commit):
- message:
- summary:

## Open risks or doubts

- provider-specific edge cases may require additional driver notes later;
- response normalization may need a separate data-contract spec once the payloads exist;
- streaming responses are enabled as a raw pass-through scaffold, but they still need integration validation.
- queue aliases are implemented in the backend, but the admin UI still needs a dedicated queue editor before operators can manage them comfortably.
- the Anthropic adapter is implemented and the protocol-aware telemetry fields are now stored on UsageLog records.
- the current implementation still mixes queue-candidate scoring, key eligibility, and cooldown behavior more tightly than the redesigned contract allows.

## Related

- [proxy.spec](proxy.spec.md)
