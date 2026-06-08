# Admin Spec

This spec defines the administrative access and client-token contract.

## Contract

- the administrative panel is protected by authenticated access;
- administrative sessions use JWTs with configurable expiration;
- administrators can create internal app tokens for local projects or applications;
- each app token is associated with a name, project context, environment, and optional requests-per-minute limit;
- the admin surface must support management of the main product domains without exposing raw provider secrets by default.

## Scope notes

- the admin surface is for management, not for provider translation;
- app tokens are distinct from external provider keys;
- environment labels such as `development`, `staging`, and `production` are part of the token metadata contract.

## Related

- [project.spec](project.spec.md)
