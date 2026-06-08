# Vault Spec

This spec defines how provider keys are stored, protected, and revealed.

## Contract

- every external provider key is a first-class `ProviderKey` object;
- a `ProviderKey` includes `id`, `label` or `name`, `description`, `provider`, `encrypted_token`, `status`, `blocked_until`, and `failure_count`;
- the real provider token must be stored encrypted at rest;
- the user interface must mask tokens by default;
- revealing a token in plain text requires an explicit security re-authentication or an equivalent consent step;
- reveal actions must be logged;
- the key lifecycle includes `ACTIVE`, `COOLDOWN`, `SUSPENDED_BILLING`, and `INVALID` states;
- a cooldown state is time-bounded by `blocked_until`;
- repeated failures increase `failure_count` and can move the key out of active rotation.

## Scope notes

- the vault protects secrets and tracks key lifecycle;
- it does not define the HTTP proxy routing rules;
- masking and reveal are security behavior, not just UI decoration.

## Related

- [project.spec](project.spec.md)
