# Commit Safety Policy

- run `git status --short` before proposing or making a commit;
- review the diff;
- if the project uses Git, relevant changes should end with `.stat` updated; when approved, they should also end with a clean and coherent commit;
- use a short and stable `trace_id` to tie the change before the commit;
- recommended `trace_id` format: `awc-YYYYMMDD-HHMM-xxxx`, in UTC, with short alphanumeric `xxxx`;
- record the `trace_id` in `.stat` and also in the commit message or commit body;
- `.stat` may record the hash after the commit, but it does not depend on it to exist;
- if the commit is not made, `.stat` should record the reason and the trace state;
- do not mix files outside the stage scope into the commit;
- do not commit secrets, `.env`, dumps, snapshots, or sensitive logs;
- do not commit temporary files by accident;
- prefer small commits per stage;
- if needed, separate contract change, implementation, and cleanup.

## Related

- [../specs/project.stat.md](../specs/project.stat.md)
- [spec-stat.policy.md](spec-stat.policy.md)
