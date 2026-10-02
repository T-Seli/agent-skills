# V0 data contracts

Catalog entries have exactly: `id`, `layer` (meta/company/project),
`summary`, `phrases`, `roles`, `body`, and `requires`. Paths are relative
to this repository and must resolve inside it. Project bindings use the same
entry shape relative to an explicitly supplied project root; project source
paths stay inside that root. Personal and team profiles can use a separate
explicit profile root and supply only model-tier aliases;
actual models are chosen through the current native adapter catalog.

The runtime validates fields and source paths. `select` returns a catalog
choice, `load` returns only its body and declared dependencies with hashes,
and `handoff` returns metadata with no message delivery or approval.
Change proposals pin the canonical proposal fields, complete source and package
hashes, evidence bytes and fixture bytes. Review rechecks those pins before
evaluation; a passing evaluation makes one ready for human review, never
automatic adoption. Hashes detect staleness and ordinary mutation, not author
identity or trust.
Native names shown in the index are proposed qualified export names. No host
export or collision resolution runs in v0; installed hosts keep their own
precedence. Dependencies are flat Markdown references (no skill-to-skill
dependency graph), bounded and checked for presence. Native packages also
pin hashes for references and scripts without loading their content.
