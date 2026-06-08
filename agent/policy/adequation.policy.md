# Adequation Policy

- this policy guides the post-install adequation mode of the convention;
- use it when the repository has already received `standard` and needs to be aligned with the usage contract;
- do not make large structural changes without going through the phases and approvals below;
- treat each phase as a reusable checkpoint;
- the goal is to leave the repository ready for the agent to work with less noise and fewer assumptions.

## Default flow

1. verify the bootstrap;
2. align the graph and vault exclusions;
3. map noise, artifacts, and loose files;
4. ask for approval to organize the repository;
5. organize the approved repository;
6. map documentation that needs to become contract or state;
7. ask for approval to create or adjust context and specs;
8. create or adjust context, specs, stats, and linking;
9. ask for approval to consolidate and commit;
10. record the result in `.stat`.

## Standard handoff

After the bootstrap, the agent should end the first message in a short and
predictable way. The recommended format is:

```text
I installed the convention, aligned the graph and the .gitignore, and read the update index and adequation roadmap.
Can I start phase 2: inventory of noise, artifacts, and loose files?
```

If approved, the agent moves to the inventory.
If not approved, the agent stops and waits for new instructions.

Before leaving each phase, the agent should repeat the same pattern:

- summarize what was found;
- list created or changed files;
- show `git status --short`;
- say what it plans to do in the next phase;
- ask for approval before changing structure, moving files, or deleting artifacts.

## Phase 1: bootstrap

- confirm that `agent-start-here.md` was read;
- confirm that `project.overview.md` was read;
- confirm that `project.update.md` was read when the project already has the convention installed;
- confirm that `README.md` and `agent/policy/overview.md` were read when they exist;
- apply the recommended `graph.json` when the project uses Obsidian;
- align the project `.gitignore` for known local noise;
- create or align `project.overview.md` and other minimal documentation entry points when they are missing, if that is within scope.

## Phase 2: inventory

- list loose files, temporary files, caches, artifacts, notes, reports, and legacy docs;
- classify each item as:
  - keep;
  - investigate;
  - move;
  - rename;
  - delete;
  - preserve;
- do not run cleanup without explicit approval.

## Phase 3: organization

- move artifacts to the correct directories;
- remove approved noise;
- align the operational workspace;
- preserve useful history and evidence.

## Phase 4: context and contracts

- identify which documents are already contracts;
- identify which documents need to become `.spec` / `.stat`;
- identify which documents are just explanation, evidence, or legacy;
- propose links between docs, specs, stats, and policies by domain and function.

## Phase 5: consolidation

- update `.stat` with real progress;
- record `trace_id` when there is a relevant change;
- if there is a commit, record the message and hash after the commit;
- make it clear what was done, what is still pending, and what needs a decision.

## Approval

Before moving between phases, show:

- inventory or proposal summary;
- created or changed files;
- `git status --short`;
- doubts and pending decisions.

## Core rule

- adequation exists to make the repository compatible with the convention;
- do not turn adequation into arbitrary refactoring;
- do not skip approval when the phase involves structural change.

## Related

- [README.md](../../README.md)
- [../../project.overview.md](../../project.overview.md)
- [../../project.update.md](../../project.update.md)
- [overview.md](overview.md)
- [../workspace.policy.md](workspace.policy.md)
- [../specs/overview.md](../specs/overview.md)
- [../specs/project.stat.md](../specs/project.stat.md)
