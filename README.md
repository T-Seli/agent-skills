# Shared agent skills

This repository is being generalized from its Claude Code/Codex workflow
origin. The authored core remains at `skills/` and `global/`; adapter maps are
under `packages/claude`, `packages/codex`, and `packages/dot`. The Dot adapter is
only a proposal until its supported installation interface is verified.
Existing installed links keep their current targets throughout this migration.
The [architecture overview](architecture.html) shows the human, dot, workers,
subagents and shared guidance in one diagram.
This repository starts from a reviewed, history-free source snapshot; Git tracks subsequent versions.

## Daily v0 use
The local selector is an offline aid; it does not start an agent or send a message.
Run `python3 -m agent_skills catalog` for the small index, then
`python3 -m agent_skills select --role worker "review change"`.
`python3 -m agent_skills load --role worker company.test-review` loads that
body and only its declared dependencies, with hashes to recheck freshness.
`compose --role worker company.blueprint company.test-review` combines up to
three explicit skills and deduplicates shared dependencies.
`python3 -m agent_skills evaluate` runs selection fixtures. A local
`handoff` command prepares evidence references and a next step with
`delivery: not sent`; the existing native coordination skill owns any
authorized worker dispatch or message. Project and profile examples are in
`agent_skills/examples/`. Model tiers are hints, not model choices.
To prepare a revisioned packet, place its task fields in a local JSON spec and
run `python3 -m agent_skills packet --role worker --spec task.json company.handoff`.
Pass the resulting JSON to `handoff --packet-file packet.json` with the same
`--work-item` ID. These commands print data; they do not dispatch. See
[v0 research decisions](agent_skills/RESEARCH-DECISIONS.md) for the evidence
contract, host limitations and the next native verification step.
For a real project, pass `--project-root /path/to/project --project
.agent-skills/project.json`; its body, facts and evidence stay in that
project. Handoffs use relative `project:` evidence references and source
hashes, never local absolute paths.
Private preferences can live outside this repo using `--profile-root
/path/to/private-config --profile profile.json`; the shared catalog remains
unchanged.

## Release reconciliation

`agent_skills/release-targets.json` is the one declared target set for a reviewed
immutable release. At task entry, resume, reconnect, pre-activation or post-activation,
record sanitized installed, loaded and behavior-verification observations in a
task-local JSON file, then run:

`./skills/workflow-contracts/scripts/safeguard-cli reconcile agent_skills/release-targets.json <state.json>`

The read-only gate fails until every required target matches the same commit and
tree, has a rollback reference, and has receipt-backed load and behavior checks.
It reports drift and the next bounded action. Active tasks keep their loaded pin;
new workers use the approved pin, with no forced restart or silent mid-operation
switch. Saved-cloud publication remains an explicit Edit/Republish UI step and
needs a fresh-task receipt. Built-in instructions and tool grants are outside
this user-owned release target set. The gate never fetches, installs, publishes,
changes access, or schedules background work.

For one explicitly approved maintenance action, a lifecycle owner can run
`./skills/workflow-contracts/scripts/safeguard-cli maintain-release <manifest.json> <state.json> <request.json>`. The request binds one action, authorization reference,
immutable source/commit/tree, lifecycle checkpoint, expected and observed approval
reviewer mode, and action parameters. `fast-forward-main` requires a fresh fetched
SHA equal to the approved commit, an exact deploy-lock owner, a clean tracked and
non-ignored worktree, an ancestor-only update and a final race check. It never
fetches, stages, lists ignored paths or removes ignored content.
`activate-local-release` accepts only native targets for which reconciliation
returned `install-approved-release-at-safe-checkpoint`, verifies the immutable
release pin, byte/mode-identical tracked tree against an exact clean source
checkout, absence of extra release entries, and rollback references, then invokes
that release's transactional installer. Its receipt still requires post-activation load and behavior
reconciliation; it never changes settings or hook trust, restarts a runtime,
publishes cloud state, or claims system-wide adoption.

The adapter is callable at task-entry, resume, reconnect, pre-activation and
post-activation checkpoints because it binds the checkpoint in both state and
request. The current hosts do not expose a supported automatic lifecycle callback
that supplies this structured request plus reviewer-mode readback. Therefore the
adapter is a tested operation invoked by the owning workflow, not a daemon or an
automatic updater. Missing reviewer-mode evidence blocks mutation as unverified;
it is not treated as manual approval or bypassed by starting another session.

Before treating a fetched `main` as the next release candidate, run `git fetch`
and then `safeguard_cli main-sync` with the exact repository, base, fetched SHA
and deploy-lock path. It requires an exact clean local/remote match, permits but
does not enumerate ignored content, and rejects tracked or non-ignored untracked
changes and any active lock; it never pulls or activates newer source.
For an improvement, `propose` writes a JSON proposal to stdout; keep it in
a private task folder. `review-proposal <file>` runs its fixture and reports
whether human review is needed. Neither command edits or promotes a skill.

An isolated synthetic project test on 2026-10-02 observed Codex CLI 0.149.0
and Claude Code CLI 2.1.287 load a qualified project skill both explicitly and
implicitly. Claude's implicit trace includes a `Skill` tool call. Live Dot
loading and handoff remain unverified. No active profiles were changed. Next
iteration: evaluate selection on real reviewed tasks, verify Dot's supported
adapter, then propose specific
skill changes with regression fixtures and human review. Pin accepted changes
as commits and retain the prior commit for rollback. No automatic promotion.

A workflow system for Claude Code and Codex, shared by every project on a machine. Reusable skills cover a change from briefing to production monitoring, backed by one global `CLAUDE.md`, one shared contracts file, one output style, one read-only sub-agent and one session-start hook. The framework is the shared code; each project's own `CLAUDE.md` is its config. A project plugs in by filling the standard sections (listed in `skills/workflow-contracts/contracts.md`; fields in `skills/workflow-contracts/project-CLAUDE-template.md`). **If onboarding a project needs a skill edit, the skill is wrong.**

## Pipeline
```
prime-context → blueprint → action-items → [user approves] → implement → test-review → deploy → monitor
                   ↑                                                                             │
                   └──────────── findings become a new draft (-r2) with action items ────────────┘
```
A big implementation (contracts.md § Chain) runs grill-me first, writes action items as tickets, and implements in spec mode: one worker per ticket off an integration branch, a merger, a two-axis review and one fixer, then test-review as usual.
Each skill starts from the user's plain words and starts the next one itself; the routing and the chain live in `skills/workflow-contracts/contracts.md` § Chain. Outward actions (push, merge, deploy) need the user's go-ahead as defined in § Consent; one plain request can cover the whole chain, and without it the agent asks once. No tracked file in a repo changes before `/implement` runs on an approved plan or fix. `/handoff` moves in-flight work to a fresh session at any point. The plan skill is named `blueprint` so it doesn't collide with Claude Code's built-in plan mode.

## Components
| File | Owns | Loads |
|---|---|---|
| `global/CLAUDE.md` | Engineering principles, prompts, safety, git, verification, ambiguity, tenant definition | Always |
| `skills/workflow-contracts/contracts.md` | Layers, names, project sections, folders, stage line and chain, consent, report caps, log format and parsed tokens, record commits, "outside the plan", scheduler, defaults | Read by every skill at start |
| `output-styles/orchestrator.md` | How replies to the user are written | Always (main session only) |
| `agents/scout.md` | How a read-only explorer searches and reports | Description always; body when delegated |
| `tests/check.sh` | Budgets, banned names, invocation, contracts path, template fields | Before every commit |
| `hooks/session-start.sh` | Git snapshot: fetch, `<base>` vs origin, dirty count, worktrees, pending drafts | On startup, resume, clear, compact |
| `codex/AGENTS.md` | Codex header: precedence, skill list, chain and consent pointers | Built into `~/.codex/AGENTS.md` with global `CLAUDE.md`, the output style body and `codex/compatibility.md` |
| `codex/compatibility.md` | Tool, sub-agent, worktree, scheduler and hook translations for Codex | Always in Codex (via the built `AGENTS.md`) |
| `codex/agents/scout.toml` | The scout for Codex, brief inline, sandboxed read-only | Description always; body when delegated |
| `codex/hooks/` | Codex session-start snapshot | On session start, once trusted with `/hooks` |
| `CLAUDE.md` | This repo's own project facts (it is a project like any other) | When working in this repo |
| `install.sh` | Links everything into Claude Code and Codex and builds `~/.codex/AGENTS.md`; idempotent | Run on install and after each deploy |
| `settings.snippet.json` | Turns on the style and the hook; lets skills read `skills/workflow-contracts/` | Merged once at install |
| `skills/workflow-contracts/project-CLAUDE-template.md` | Every project field, with `none` options | On demand (onboarding) |
| `skills/prime-context` | Repo briefing, stale-work list, newest handoff | Description always; body on invoke |
| `skills/grill-me` | Dependency-ordered technical decision interview in the owning session | Description always; shared decision contract on invoke |
| `skills/blueprint` | Angles, rubric scoring, proposal format, bug-evidence mode | Description always; body on invoke; `references/` read by the scout for bugs |
| `skills/action-items` | Action-item format | Description always; body on invoke |
| `skills/implement` | One-line plans, sync, locked worktree, collision check, env setup, per-item commits, resume; spec mode (one worker per ticket, merger, two-axis review, one fixer) in `references/` | Description always; body on invoke |
| `skills/tdd` | Red → green per vertical slice at the plan's agreed seams; good-test rules and anti-patterns | Description always; body on invoke |
| `skills/test-review` | Ready-to-deploy YES/NO: tests vs base first, fix proof, per-commit blocker check; `tests` and PR modes | Description always; body on invoke |
| `skills/deploy` | Lock, review gate, push, staged targets, 3-way sync, record commit, cleanup, rechecks; PR, local, release and rollback modes in `references/modes.md` | Description always; body on invoke; outward steps need § Consent |
| `skills/monitor` | Recheck against live traffic, alert, keep or disable the schedule, `-r2` follow-ups | Description always; body on invoke |
| `skills/handoff` | Mid-task transfer prompt, saved to the handoffs folder | Description always; body on invoke |
| `skills/agent-coordination` | Work items across worker sessions and the orchestrator assistant: durable local task records, worker adapters, one thread per item, correlated replies | Description always; body on invoke |
| `skills/approval-handoff` | Classify worker blockers, relay matching scoped authority, and route an actual direct-session approval with verified navigation and wording | Description always; body on invoke |
| `skills/system-audit` | Bounded independent read-only review of coordination outcomes, workspace navigation, verified failures/guards, human unlocks, evidence coverage, decision friction and release boundaries | Description always; body on invoke; scheduler is owned by the caller |
| `skills/task-history` | Sanitized owner-bound milestone evidence, deterministic views and resumption | Description always; body on invoke |
| `skills/ask-assistant` | Old name; routes to agent-coordination | Description always; body on invoke |

## How stages connect
Stages pass work through draft folders, task folders and log entries; `skills/workflow-contracts/contracts.md` defines all of them, including the defaults (attempts, windows, caps). Each skill also runs alone, in any repo: its Inputs section lists the sources it tries, and it never fails because an earlier stage was skipped.

## Install
Run `./install.sh` from your clone (`--dry-run` first to see the links). `--target=claude` or `--target=codex` selects one adapter; the default `--target=all` preserves the existing behavior. It links the skills, agents, output style, hooks and global `CLAUDE.md` into `~/.claude`, and the skills and Codex agent into `~/.agents` and `~/.codex`. It builds `~/.codex/AGENTS.md` from `codex/AGENTS.md`, global `CLAUDE.md`, the output style and `codex/compatibility.md`, since Codex reads one file. It backs up any real file it replaces. Rerun it after pulling changes; it is idempotent and refreshes the built file.

`scripts/critical-local-work.sh <task-id> <seconds> -- <command>` wraps one explicitly chosen critical local command with macOS `caffeinate -i`. The assertion ends when the command exits and expires after at most four hours. It never changes persistent power or security settings. The caller must choose the actual critical command and task ID; session startup does not activate it automatically. A local assertion cannot keep cloud work running or recover a sleeping Mac.

Migration: keep the existing `skills/` and `global/` paths until every installed link has been reviewed. Test each adapter with `--dry-run` on the intended machine, then install only after reviewing backups and settings in an idle window. Roll back by returning to the previously installed source and rerunning the matching installer target; restore any backed-up real files before restarting tools. The published source starts from a reviewed clean snapshot. Earlier local Git history remains private. Review access and source changes before wider sharing.

Then merge settings by hand: `settings.snippet.json` into `~/.claude/settings.json` (append where arrays already exist), and the Codex hooks into `~/.codex/hooks.json`, trusting them with `/hooks`. Restart both tools. Check: `/output-style` marks Orchestrator, `/hooks` lists the hooks, `/context` lists `~/.claude/CLAUDE.md`, `/agents` lists `scout`.

## Onboard a project
1. Copy `skills/workflow-contracts/project-CLAUDE-template.md` to the repo root as `CLAUDE.md`, or merge its sections into the existing one.
2. Fill each field with facts; move existing project notes into the matching section; move long runbook detail into the docs the sections point to. A field that doesn't apply gets `none`; never delete a section. `Targets: none` ends the pipeline at `/deploy` (a merge).
3. Replace `AGENTS.md` with the pointer at the bottom of the template.
4. Run `/prime-context`. Any `Add to CLAUDE.md § …` line in a report names a fact still missing.

## Add a skill
- Frontmatter: `name`, a `description` ≤300 chars (what + trigger phrases, no overlap with another skill), `argument-hint`. No `disable-model-invocation`: every skill starts from plain words. Outward steps (push, deploy, messages) run only with the user's go-ahead per contracts.md § Consent.
- Its first instruction: read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`. Use its names and defaults; define nothing it already defines.
- `## Inputs`, tried in order: args › task folder › conversation › discovery. Say what it is working from in one line.
- Standalone: it never fails because an earlier stage was skipped.
- If it acts on a task, it appends a `<stage>:` log entry per contracts.md.
- It ends with `## Report (≤N lines)`.
- Add a row to Components above, the skill to the routing and chain in contracts.md § Chain, and it to the skill list in `codex/AGENTS.md`.

## Change the framework
- Edit here and commit. Never patch a skill per project, and never edit `~/.claude`, `~/.agents` or `~/.codex` copies (they are symlinks into this repo, or built from it by `install.sh`).
- Each topic has exactly one home (table above); reference it, never restate it. Skills refer to their own steps by bold name, never by number, and never to another skill's steps.
- Changing a parsed token (contracts.md § Task log, including the `/monitor` args in scheduled prompts): readers accept both the old and the new form for one `Monitor window`, so logs and scheduled tasks written before the change still parse. No version marker.
- Budgets: global `CLAUDE.md` ≤ 600 words, `skills/workflow-contracts/contracts.md` ≤ 90 lines, project `CLAUDE.md` ≤ 1,000 words, output style ≤ 25 lines, scout ≤ 25 lines, each `SKILL.md` ≤ 100 lines, each `references/` file ≤ 80 lines, skill description ≤ 300 chars. Check with `wc -w` / `wc -l`.
- No project, tenant, company, stack, vendor, person, machine or model names in any file here; point to project facts by section ("the command in `CLAUDE.md` § Run & test").

## Source and task-history readiness draft

The offline [source, history and closeout contract](agent_skills/SOURCE-HISTORY-ROLLOUT.md) adds read-only source/version checks, a private append-only task timeline, and handoff/completion/cleanup eligibility checks. It has no source transfer, cloud activation, installation, or deletion side effects. Run the tests with `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_source_history_closeout`.

The [coordination state contract](skills/agent-coordination/references/state.md#local-operating-checkpoints) documents local obligation, monitor and correction checkpoints plus execution context and Git/test provenance. `python3 -m agent_skills.safeguard_cli task-status <record.json>` renders their current state without changing the record. These library interfaces require caller adoption; they do not install hooks, launch observers or enforce native host behavior.
