# Review on two axes

Read by `/implement` spec mode once every ticket is merged. It raises code quality before the release gate; test-review stays the gate and is unchanged. Two read-only `scout` sub-agents run in parallel, in one message, each on a fresh context, so neither axis masks the other.

## Fixed point
Fixed = `git merge-base origin/<base> <integration tip>` after a fetch per contracts.md § Git (no remote: `<base>`). Pass both axes the diff command `git diff <fixed>...<tip>` and `git log --oneline <fixed>..<tip>`. Check the ref resolves and the diff is non-empty before launching.

## Standards
Sources, by path: project `CLAUDE.md`, global `CLAUDE.md` § Engineering, any coding-standards or contributing doc the project names, and the smell baseline below pasted in full. Brief: "Report per file and hunk (a) each breach of a documented standard, citing the file and rule: these can be hard; (b) each baseline smell you see, named and quoted: always a judgement call. A documented standard overrides the baseline. Skip what lint enforces. Stay within the review cap (contracts.md § Defaults `Spec mode`)."

Smell baseline, what → fix:
- Mysterious name → rename; no honest name means the design is murky.
- Duplicated code across hunks → extract the shared shape.
- Feature envy: reaches into another module's data more than its own → move it to that data.
- Data clumps: fields that keep travelling together → one type.
- Primitive obsession: a string or number standing in for a domain concept → a small type.
- Repeated switches on the same value → one shared map.
- Shotgun surgery: one logical change scattered over many files → gather it in one module.
- Divergent change: one file edited for unrelated reasons → split it.
- Speculative generality: hooks or parameters the spec does not need → delete them.
- Message chains: long navigation the caller should not depend on → one call that hides the walk.
- Middle man: mostly delegates onward → call the target directly.
- Refused bequest: ignores most of what it inherits → composition.

## Spec
Sources, by path: `DRAFT/plan.md` and every ticket's acceptance criteria in `DRAFT/action-items.md`. Brief: "Report (a) requirements or acceptance criteria missing or partial; (b) behavior nobody asked for (scope creep); (c) criteria that look implemented but wrong. Quote the plan or ticket line for each. Stay within the review cap (contracts.md § Defaults `Spec mode`)." No plan: skip this axis and say so.

## Aggregate
- Write both reports verbatim under `## Standards` and `## Spec` in `DRAFT/review.md`. Do not merge or rerank across the axes.
- Open each cited line. Accept every hard standards breach and spec finding you can show, and a smell only when its fix stays inside the plan (contracts.md § Plan scope). Mark each finding accepted or rejected, with one line why.
- Summary line: findings per axis and the worst within each, never one winner across them. No accepted findings: no fixer.
