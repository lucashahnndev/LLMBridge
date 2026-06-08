# Linking Policy

- link documents when the relation helps understand contract, dependency, correlation, or continuity;
- every `.spec` must point to its corresponding `.stat`, and every `.stat` must point to its corresponding `.spec`;
- when there is a parent document, a replacement, or a relevant reference, link that too;
- use wikilinks or internal Markdown links for `.md` notes;
- for files that are not `.md` (`.json`, `.jsx`, `.py`, `.ts`, assets, and similar), use an explicit reference to the file with the exact path or literal text; do not use wikilinks to create a new note from them;
- do not force valueless links or impose a numeric limit on useful correlations;
- keep links simple, stable, and easy to follow.

## Related

- [../specs/overview.md](../specs/overview.md)
- [../specs/project.spec.md](../specs/project.spec.md)
- [../specs/project.stat.md](../specs/project.stat.md)
- [spec-stat.policy.md](spec-stat.policy.md)
