# Agent Workspace

This directory concentrates the agent's working material without polluting the repository root.

## Useful entry points

- [../project.overview.md](../project.overview.md)
- [../project.update.md](../project.update.md)
- [../agent-start-here.md](../agent-start-here.md)
- [policy/overview.md](./policy/overview.md)
- [specs/overview.md](./specs/overview.md)
- [../docs/overview.md](../docs/overview.md)
- [specs/project.spec.md](./specs/project.spec.md)
- [specs/project.stat.md](./specs/project.stat.md)

## Structure

- `policy/`
  - durable rules for agent work;
  - workflow, contract, documentation, and safety conventions.
- `specs/`
  - normative specifications;
  - progress status;
  - `.spec` / `.stat` pairs.
- `prints/`
  - screenshots;
  - temporary support images;
  - visual comparisons.
- `tmp/`
  - test prints;
  - temporary captures;
  - disposable artifacts.
- `reports/`
  - short validation reports;
  - audit summaries;
  - outputs worth keeping organized.
- `scripts/`
  - helper scripts and small automations;
  - test utilities.
- `test/`
  - small tests and support checks;
  - validation drafts.
- `note/`
  - more private agent notes;
  - reasoning drafts;
  - context observations.

## Rules

- keep the rest of the repository clean;
- do not use the root for prints and drafts;
- promote to official documentation only what is stable;
- do not store secrets, tokens, dumps, or sensitive data without an explicit reason.

## Related

- [../agent-start-here.md](../agent-start-here.md)
- [../docs/overview.md](../docs/overview.md)
