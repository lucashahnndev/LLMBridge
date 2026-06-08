# Observability Spec

This spec defines metrics and alerting for the gateway.

## Contract

- the system exposes global operational metrics such as average latency, total requests, success rate, and key-pool state;
- the system exposes per-project consumption metrics for app tokens;
- the dashboard must distinguish global health from per-project usage;
- key lifecycle transitions that matter operationally must be observable;
- critical key events trigger Telegram notifications;
- the alert set includes cooldown entry, invalidation, billing failure, and a full-pool cooldown condition for a provider.

## Scope notes

- observability covers dashboards, counters, and alerts;
- it does not define the provider routing algorithm;
- alert transport is part of the contract even if the implementation changes later.

## Related

- [project.spec](project.spec.md)
