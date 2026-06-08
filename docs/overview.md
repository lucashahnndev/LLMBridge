# Docs

This directory gathers the human layer of the project: explanation, context,
evidence, planning, decisions, and legacy.

## Index

- [contracts/overview.md](./contracts/overview.md): documentation that explains contracts without replacing the spec;
- [policies/overview.md](./policies/overview.md): human documentation for governance and usage;
- [reports/overview.md](./reports/overview.md): evidence, audits, and validation;
- [plans/overview.md](./plans/overview.md): migrations, phases, and future work;
- [guides/overview.md](./guides/overview.md): practical guides and playbooks;
- [decisions/overview.md](./decisions/overview.md): approved and closed decisions;
- [concepts/overview.md](./concepts/overview.md): concepts and evolution models;
- [legacy/overview.md](./legacy/overview.md): replaced history or material outside the active base.

## How to read

- use `docs/` to understand the project's human context;
- use `agent/specs/` to read the normative contract;
- use `agent/policy/` to read the agent's durable rules;
- use `agent/overview.md` to understand the operational workspace;
- when a doc grows to the point of becoming a rule, consider migrating it to
  `.spec` and `.stat`;
- when a doc cites a file that is not `.md`, use the explicit file path; do
  not create a new note to represent it in Obsidian.

## Related contracts

- [../agent/specs/overview.md](../agent/specs/overview.md)
- [../agent/specs/project.spec.md](../agent/specs/project.spec.md)
- [../agent/specs/project.stat.md](../agent/specs/project.stat.md)

## Relation to the convention

- [../project.overview.md](../project.overview.md) is the root overview for agent-oriented navigation;
- [../project.update.md](../project.update.md) is the update index for already installed projects;
- [../agent-start-here.md](../agent-start-here.md) is the agent entry point;
- [../agent/policy/overview.md](../agent/policy/overview.md) concentrates durable policies;
- [../agent/specs/overview.md](../agent/specs/overview.md) concentrates normative contracts;
- [../agent/overview.md](../agent/overview.md) concentrates the operational workspace;
- `docs/` complements with human context and conceptual continuity;
- when in doubt between contract and explanation, read the corresponding spec first.

## Related

- [concepts/overview.md](./concepts/overview.md)
- [../agent/overview.md](../agent/overview.md)
