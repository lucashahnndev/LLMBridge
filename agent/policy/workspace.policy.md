# Workspace Policy

- `agent/` is operational workspace;
- `tmp` stores temporary files;
- `prints` stores screenshots and test images;
- `reports` stores reports and textual evidence;
- `scripts` stores helper scripts;
- `test` stores small tests;
- `note` stores internal notes;
- `agent/.gitignore` ignores temporary operational content by default; `agent/specs/`, `agent/policy/`, `agent/scripts/`, and `agent/test/` remain versioned; if something in `tmp`, `prints`, `reports`, or `note` becomes durable evidence, promote it to the correct location before versioning.
- `agent/prints/` stores screenshots, test images, visual evidence, and temporary agent validations; `docs/` stores human/official documentation; `docs/screenshots/` should exist only if the images are part of real human documentation.
- the workspace is not official documentation;
- nothing there becomes contract by accident;
- temporary files should be cleaned up or promoted;
- do not spread files outside the workspace.

## Related

- [../specs/overview.md](../specs/overview.md)
- [../specs/project.stat.md](../specs/project.stat.md)
