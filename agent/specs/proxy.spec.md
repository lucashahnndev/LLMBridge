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
- when a provider returns `429`, the proxy treats the failure as a rate-limit event and retries with another eligible key when available;
- retry behavior must stop when the configured attempt or eligibility limit is reached;
- if no eligible key remains, the proxy returns the upstream failure in a controlled way.
- the proxy may also accept `queue/{queue-name}` as a higher-level routing alias that resolves to an ordered list of `provider/model-name` candidates;
- queue resolution must preserve `provider/model-name` as the real provider route and must only add orchestration above it;
- queue strategies may reorder candidates by fixed priority, latency, or history-backed score, but they must still fall back to the real provider/model routes beneath them;
- queue-level fallback must advance to the next candidate when the current candidate fails for a retryable upstream reason or exhausts its quota;
- queue routing must not replace the provider/model contract; it wraps it.
- public adapters must preserve telemetry fields that identify the source protocol, sink protocol, selected route kind, resolved route, queue name, and tool-calling behavior.

## Scope notes

- routing by provider prefix is a contract, not an implementation detail;
- the provider registry can grow without changing the client-facing API shape;
- failover is transparent only while another eligible key exists.
- queue aliases are a product-level orchestration layer, not a replacement for provider/model routing;
- the queue layer can evolve independently from the provider drivers and key-rotation rules.

## Related

- [project.spec](project.spec.md)
