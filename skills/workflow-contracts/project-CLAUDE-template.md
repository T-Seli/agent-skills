# <Project name>

<One sentence: what this system does and who depends on it.>

<!-- Framework skills read the sections below by name (the list is in the workflow-contracts skill's contracts.md): never rename or delete one. Facts only; a rule here overrides a framework rule only where it names the rule it replaces (contracts.md § Layers). A field that doesn't apply says `none`. Keep this file ≤1,000 words; put detail in the docs it points to. HTML comments like this one are stripped before Claude loads the file, so they cost no context. Keep each field label as written: the session-start hook reads the backticked value of `Base branch`. -->

## Map
<!-- Where things live and how the repo records work. One line each. -->
- Entry points: `<path>` — <what starts here>
- Core modules: `<path>` — <what it owns>
- Governing docs: `<path>` — <what it rules on>
- Generated or vendored (never edit): `<path>`
- Remotes: canonical `<remote>` · push `<remote>` (fork: <how changes reach canonical>) | `origin` only
- Task records: `tasks` | none (task folders stay in local drafts; nothing is recorded in git)
- Commits: <convention, e.g. `<type>(<scope>): <summary>`> · attribution: <trailer policy, or none>
- Git host CLI: `<command>` | none
- Issues: `<owner/repo>`, … (repos where implement publishes every code-changing task as an issue; workflow-contracts issues.md; works in either flow) | none

## Run & test
<!-- Exact commands a fresh session can paste, plus what a fresh worktree needs before they work. -->
- Install: `<command>`
- Run locally: `<command>`
- Tests: full `<command>` (~<duration>) · one test `<command>` · list failing ids `<command>`
- Prompt checks: <how to prove a prompt or agent-config change: a replay of past conversations, an eval command, or fixtures; where each agent's size budget and agnostic check live> | none
- Fast tests: `<command>` (the per-change check; the full suite runs at start and end) | none
- Test slot: `runner` (the test runner wraps each suite it starts in `safeguard-cli test-slot`, so agents run test commands bare) | `agent` (agents wrap each test command)
- Tests live in: `<path>` (tracked by git: yes | no)
- Lint / typecheck: `<command>`
- CI: <how to read a commit's checks> | none
- Test baseline: <known failures on the base branch, or "clean">
- Test services: <databases, queues or emulators the tests need, and the start command> | none
- Worktree setup: <env files to copy; dependency dirs and large gitignored dirs (.claude/drafts, node_modules) to symlink to the main checkout, never copy> then `<install command>`; rebuildable: <dirs>

## Deploy
<!-- Enough for /deploy to ship, prove, and roll back every target without guessing. -->
- Deploy doc: `<path>` (authoritative)
- Base branch: `<branch>` · Release branch: `<branch>` (stages: `<a>` → `<b>`) · Protected: `<branches>`
- Flow: trunk (commit on the base branch in the main checkout) | branch (a task branch in its own worktree; use when edits to the main checkout go live at once)
- PR merge style: ff | merge | squash (for PRs opened on request)
- Release: per-merge (each merge deploys) | batched (tags, registries, app stores: `/deploy release` ships; <how>)
- Trigger: <manual `<command>` | auto on push to `<branch>` | none>
- Skip-deploy marker: <text in a commit message that stops an automatic deploy> | none
- Targets: <one line each: name — kind `deploy` (ship code) or `sync` (push prompts or config to a provider) — command — check that proves it landed, e.g. bindings and versions unchanged> | none (the pipeline ends at the merge)
- Deployed version → commit: <how each target reports what is live (sha, tag, build number, registry version) and how that maps to a commit>
- Pre-deploy checks: <drift check on the target, build-env sanity checks>
- Rollback: <command or steps per target> | forward-fix only
- Kill switch: <flag or config that turns a change off without a deploy> | none
- Window: <when deploying is safe, or "any time">

## Observe
<!-- How to tell whether production is healthy after a change, and when traffic will prove it. -->
- Logs: `<command or URL>`
- Errors / crashes: <error tracker, crash reports, or a log query>
- Dashboards / alerts: <where>
- Lookup: <entity → database/schema.table, key, joins, time column, trace order; or the path of a recipes file> | none
- Database checks: <the read-only SQL tool and its targets; how a tenant resolves to its database; the large tables to explain first> | none
- User feedback: <support inbox, reviews, feedback tracker> | none
- Traffic timing: <when real traffic exercises each path, e.g. business hours, nightly batch>
- Rollout: <phased percentages and how to read the current stage> | none
- Recheck window: <how long rechecks run, when not the default>
- Timezones: logs <zone> · database <zone> · traffic <zone> · rechecks scheduled in <zone, default this machine's>

## Tenancy
<!-- Tenant = whatever varies per install; single install or library: `none`. Keeps every change config-only. -->
- Tenants: <name — aliases and ids, one per tenant | a command or query that lists them, plus aliases> | none
- Tenant config lives in: `<path or table>`
- Layering: <global > tenant > narrower scope; which layer wins where>
- Add a tenant: <steps, all config>
- Tenant-specific prompts or content: `<path>`

## Gotchas
<!-- Traps that cost real time. One line each: date, trap, what to do instead. -->
- <YYYY-MM-DD> <trap> → <what to do instead>

## Defaults
<!-- Optional. Override a default from contracts.md § Defaults (workflow-contracts skill) with the same label, e.g. "- Monitor window: 7 days". Leave empty to keep them all. -->

<!-- AGENTS.md example (for tools that read AGENTS.md instead of CLAUDE.md):
```markdown
# AGENTS.md
Project instructions live in `CLAUDE.md` in this directory. Read it first; it is the single source.
```
-->
