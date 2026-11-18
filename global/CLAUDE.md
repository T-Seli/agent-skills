# Global working agreement

Project `CLAUDE.md` facts win conflicts. Orchestrate: scouts read; workers write or run long via `delegate.py`.

Read `workflow-contracts/contracts.md` first; perform its deployment-readiness preflight at deployment entry/resume.

Tenant = what varies per install; § Tenancy `none` disables tenant rules.

## Engineering
- Depth, not breadth: meet the professional quality bar with primary authorized evidence and independent verification (`workflow-contracts/behavior.md`); keep scope, privacy and permission gates. Rewrite prompts only when asked.
- Plug-and-play: a new tenant or project adopts any change by config alone: no code or prompt edit, no branching on tenant or environment names. Varying values are layered config (global > tenant > narrower).
- System lens: before changing code, name its callers, callees and data/config owners.
- Fix at the most central point; refine existing skills and helpers before adding new ones.
- Minimum code: nothing speculative, no impossible-state handling; atomic functions; flag files past ~500 lines. Fail loudly, no silent fallbacks.
- Match surrounding style; explain only non-obvious choices. Every changed line traces to the request; remove only your own orphans; mention unrelated dead code.
- Prompts: budgeted, concise, agnostic, one home per tool, proven by simulation (`workflow-contracts/behavior.md` § Agent prompts).

## Safety
- After interruption or compaction reread the task id, revision, exclusions and next action; completed grants are history.
- Production data is read-only unless asked. A script, job, backfill or migration writing to production asserts its target first (request handlers are exempt). Allow-list DDL; migrations are idempotent with a down path.
- Secrets: env or gitignored config only, never in source, URLs, logs, screenshots or sub-agent prompts. Strip PII before third-party LLM calls.
- Shared external config (webhooks, DNS, vendor dashboards): additive changes only, snapshot first.
- Look before overwriting or deleting. Outward or irreversible actions need the user's go-ahead (contracts.md § Consent), not a review verdict or a bare "continue".

## Git
- Only `/implement`, workers included, commits code: on task branches, or on `<base>` in trunk flow (contracts.md `<flow>`). `/test-review` commits its log entry, `/deploy` its records; nothing else unless asked.
- Push a task branch or open a draft PR when asked or for tracked tasks; push to `<base>`, merge and deploy only via `/deploy`.
- Commit and PR messages describe only the change.

## Verification
- Define success first; each step gets a `Done when`. Bug fixes start with a reproducing test.
- Run tests and linters before calling anything done; diff failures against `<base>`.
- Long output: `mktemp`; report the summary and failing ids; remove it by run end.
- Mock only external APIs; prefer the project's real test services.
- Verify the artifact (deployed content, written row), not the exit code.
- Verified = checked this session against the real thing; memory and docs are leads. Evidence: an empty result proves nothing; state n, timezone and freshness.
- After `Attempts before blocked` tries record them and move on.

## Coordination
- Never send, reply to or forward email: write a draft. Other sends need the user's exact-text yes; policy-allowed assistant reports need none (agent-coordination).
- Workers start only via `delegate.py`, in auto mode, never default. Before starting or nesting one: ≥10 GB free disk, ≤2 `test:diff` runs machine-wide, one writer per directory; a refused start waits.
- Merge, deploy and install need the user's native go on the exact head; drafts per test-review.

## Stages
Skill order: contracts.md § Chain. No tracked changes before `/implement` runs on an approved plan or fix.
- Ambiguity: `/blueprint` asks when readings differ materially; `/implement` decides and logs routine choices, and stops on anything outside the plan.
