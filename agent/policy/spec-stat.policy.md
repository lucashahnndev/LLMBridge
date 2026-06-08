# Spec / Stat Policy

- `.spec` is durable contract;
- `.stat` is live state;
- every active `.spec` must have a `.stat`;
- `agent/specs/` concentrates the normative contracts that guide changes in the project;
- `docs/` may reference specs, but it does not replace `agent/specs/` as the main contract source;
- `.stat` does not replace Git, but it can reference `trace_id` and, after the commit, the hash for traceability;
- `.spec` does not record progress;
- `.stat` does not redefine contract;
- specs need a clear domain;
- overly generic specs should be split;
- update `.spec` when the contract changes;
- update `.stat` when the state changes.

## Related

- [../specs/overview.md](../specs/overview.md)
- [../specs/project.spec.md](../specs/project.spec.md)
- [../specs/project.stat.md](../specs/project.stat.md)
- [linking.policy.md](linking.policy.md)
