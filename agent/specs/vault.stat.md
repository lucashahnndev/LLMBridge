# Vault Stat

Last update date: 2026-06-07

## Current state

- vault rules have been extracted from the product brief;
- secret storage is defined as encrypted at rest;
- token reveal requires an explicit security step;
- no implementation data exists yet.

## Pending items

- choose the encryption scheme and key management approach;
- define audit-log storage for reveal events;
- add tests when the vault exists in code.

## Evidence / validation

- ProviderKey fields and lifecycle states recorded;
- masking and reveal requirements recorded.

## Commit tracking

- trace_id: `awc-20260607-1624`
- commit status: not done
- hash (optional, after the commit):
- message:
- summary:

## Open risks or doubts

- the exact re-authentication flow can still evolve during UI design;
- operational secrets for the local master key are intentionally unspecified for now.

## Related

- [vault.spec](vault.spec.md)
