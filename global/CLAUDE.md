# Global working agreement

Project `CLAUDE.md` facts win conflicts. Orchestrate: scouts handle read-only questions; workers handle writers/long work via `delegate.py` (agent-coordination § Delegate), in parallel without asking.

Read `workflow-contracts/contracts.md` first; perform its deployment-readiness preflight at deployment entry/resume.

Tenant = what varies per install. § Tenancy `none` disables tenant rules.

## Engineering
- Depth, not breadth: meet the professional quality bar using primary authorized evidence, appropriate tools and independent verification. Read `workflow-contracts/behavior.md` for execution; preserve scope, privacy and permission gates. Execute the task; rewrite prompts only when asked.
- Plug-and-play: a new tenant or project adopts any change by config alone: no code or prompt edit, no branching on tenant or environment names. Varying values are layered config (global > tenant > narrower); tenant logic never enters shared code.
- System lens: before changing code, name its callers, callees, and data and config owners.
- Fix at the most central point; refine existing skills and helpers before adding new ones. Keep instructions compact and cohesive across orchestrator and worker roles.
- Minimum code: nothing speculative, no impossible-state handling; atomic functions; flag files past ~500 lines. Fail loudly; no silent fallbacks.
- Match surrounding style; explain only non-obvious choices.
- Scope: every changed line traces to the request; remove only your own orphans; mention unrelated dead code.
- Prompts (if the project ships them): shared text holds logic, per-install facts come via variables; harden an existing line before adding one; drop conflicting or redundant lines; never show end users internal tool names.

## Safety
- After interruption or compaction, reread the latest task id, revision, exclusions and next action before acting or answering; completed grants are history.
- Production data is read-only unless asked. A script, job, backfill or migration that writes to production asserts its target first; writes in normal request handlers are exempt. Allow-list DDL; migrations are idempotent with a down path.
- Secrets: env or gitignored config only, never in source, URLs, logs, screenshots or sub-agent prompts. Strip PII before third-party LLM calls.
- Shared external config (webhooks, DNS, vendor dashboards): additive changes only, snapshot first.
- Look before overwriting or deleting. Outward or irreversible actions need the user's go-ahead (contracts.md § Consent); a review verdict or a bare "continue" is not one.

## Git
- Only `/implement`, workers included, commits code: on task branches, or on `<base>` in trunk flow (contracts.md `<flow>`). `/test-review` commits its log entry and `/deploy` its record commits. Nothing else commits unless asked.
- Push a task branch or open a draft PR when asked or for tracked tasks; push to `<base>`, merge and deploy only via `/deploy`.
- Commit and PR messages describe only the change.

## Verification
- Define success first; each step gets a `Done when`. Bug fixes start with a reproducing test.
- Run tests and linters before calling anything done; diff failure sets against `<base>`.
- Long output: use `mktemp`; report summary and failing ids; remove by run end.
- Mock only external APIs; prefer the project's real test services.
- Verify the artifact (deployed content, written row), not the exit code.
- Verified = checked this session against the real thing; memory and docs are leads. State freshness.
- Evidence: an empty result proves nothing; state n and timezone.
- Blocked after `Attempts before blocked` tries: record attempts; move on.

## Stages
Which skill does what, and how each starts the next: contracts.md § Chain. No tracked changes before `/implement` runs on an approved plan or fix.
- Ambiguity: `/blueprint` asks when readings differ materially; `/implement` decides and logs routine choices, and stops on anything outside the plan.
