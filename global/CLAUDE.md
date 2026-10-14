# Global working agreement

The project `CLAUDE.md` holds project facts and wins conflicts. Orchestrate: delegate reading, searching and bulk writing to sub-agents (`scout` for read-only questions), in parallel.

Read `workflow-contracts/contracts.md` first for shared names, contracts and defaults. At deployment-related task entry/resume, perform its deployment-readiness preflight.

Tenant = whatever varies per install (customer, site, deployment). § Tenancy `none` ⇒ tenant rules don't apply.

## Engineering
- Plug-and-play: a new tenant or project adopts any change by config alone: no code or prompt edit, no branching on tenant or environment names. Varying values are layered config (global > tenant > narrower); tenant logic never enters shared code.
- System lens: before changing code, name its callers, callees, and data and config owners.
- Fix at the most central point; refine existing skills and helpers before adding new ones. Keep instructions compact and cohesive across orchestrator and worker roles.
- Minimum code: nothing speculative, no impossible-state handling. Atomic functions; flag files past ~500 lines. Fail loudly: no silent fallbacks.
- Match surrounding style; comments state only the non-obvious why.
- Scope: every changed line traces to the request; remove only your own orphans; mention unrelated dead code.
- Prompts (if the project ships them): shared text holds logic, per-install facts come via variables; harden an existing line before adding one; drop conflicting or redundant lines; never show end users internal tool names.

## Safety
- After interruption or compaction, reread the latest task id, revision, exclusions and next action before acting or answering; completed grants are history.
- Production data is read-only unless asked. A script, job, backfill or migration that writes to production asserts its target first; writes in normal request handlers are exempt. Allow-list DDL; migrations are idempotent with a down path.
- Secrets: env or gitignored config only, never in source, URLs, logs, screenshots or sub-agent prompts. Strip PII before third-party LLM calls.
- Shared external config (webhooks, DNS, vendor dashboards): additive changes only, snapshot first.
- Look before overwriting or deleting. Outward or irreversible actions need the user's go-ahead (contracts.md § Consent); a review verdict or a bare "continue" is not one.

## Git
- Only `/implement` commits code: on its task branch, or on `<base>` when the project's flow is trunk (contracts.md `<flow>`). `/test-review` commits its log entry and `/deploy` its record commits. Nothing else commits unless asked.
- Push, merge, deploy only via `/deploy`; open a PR only when the user asks (`/deploy PR`). Fetching follows contracts.md § Git.
- Commit and PR messages describe only the change.

## Verification
- Define success first; each step gets a `Done when`. Bug fixes start with a reproducing test.
- Run tests and linters before calling anything done; diff failure sets against `<base>`.
- Long test or build output: a `mktemp` file, deleted by run end; read and log only its summary and failing ids.
- Mock only external APIs; prefer the project's real test services.
- Verify the artifact (deployed content, written row), not the exit code.
- Verified = checked this session against the real thing; memory and docs are leads. State data freshness.
- Evidence: an empty result proves nothing; state n and timezone.
- Blocked after `Attempts before blocked` tries (contracts.md § Defaults): record what you tried; move on.

## Stages
Which skill does what, and how each starts the next: contracts.md § Chain. No tracked changes before `/implement` runs on an approved plan or fix.
- Ambiguity: `/blueprint` asks when readings differ materially; `/implement` decides and logs routine choices, and stops on anything outside the plan.
