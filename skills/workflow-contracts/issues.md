# Issues: tracked tasks

The one home for issue tracking. Skills cite it; they never restate it. Implement publishes every PR-bound task in a repo the project CLAUDE.md § Map `Issues` names (`<owner/repo>`, more than one allowed). Any task whose `plan.md` records `Issue: <owner/repo>#<n>` (written by the helper, or from an issue input) is tracked, and the steps below apply to it. Neither: no issue steps, said once in the report. It needs the `gh` CLI signed in. Every call below goes through the release-bound helper, spelled exactly `~/.agents/skills/workflow-contracts/scripts/issues-cli` and unquoted (`ICLI` below), so one permission rule can allow it; `--dry-run` prints each write instead of making it.

## Which work
- Anything that ends in a PR gets one issue when its plan or one-line plan is approved. A question, investigation or blueprint Answer that changes no code gets none.
- Branch flow lands a tracked task through one PR whose `Closes` lines close its issues. Trunk flow has no PR: nothing closes them automatically, so `/deploy` closes them by hand after its record (**Close**).
- A big implementation (contracts.md § Chain) gets a spec issue plus one sub-issue per ticket, with blocked-by links for each `after #k`.
- A task that starts from an issue (`#<n>` or its URL as the input) uses that issue as its spec: blueprint reads it, and the plan's header records `Issue: <owner/repo>#<n>` so nothing new is created for it.

## Format
- Spec issue: the plan in the reader's words, under `## Problem Statement`, `## Solution`, `## User Stories` (big implementations), `## Acceptance criteria` and `## Out of scope`; label `ready-for-agent` when the repo has it. A single-task issue uses `## What to build` and `## Acceptance criteria`. No file paths, internal tool names or customer data in titles or bodies.
- Ticket sub-issue: the session writes `issue-text.md` in the draft, one `## <n>. <title>` section per ticket with a plain what-to-build paragraph and `- [ ]` criteria a person can check, never copied from the worker ticket. The helper adds `## Parent` and `## Blocked by` (from `action-items.md`) and refuses a ticket without its section.

## Files stay the working copy
- `plan.md` and `action-items.md` are what sessions and workers read; issues are the published copy. The helper writes `Issue: <owner/repo>#<n>` under the plan's title and `· issue #<n>` on each ticket line, so a rerun creates nothing.
- A person's later edit to an issue does not change a running ticket; it reaches the plan only through **Iterate** in blueprint.

## Who and when
- Only the session running the task acts on issues: the orchestration session for a big implementation, else the session running `/implement`. Ticket workers, the merger and the fixer never touch issues; their brief carries `Issue: #<n>`.
- **Publish** at implement's Start record: write the spec or task body to a scratch file, then (tickets: after writing `issue-text.md`) `ICLI publish --repo <owner/repo> DRAFT --title "<title>" --body-file <file> [--label ready-for-agent]`. Tickets publish in the same call.
- **Claim** right after: `ICLI claim --repo <owner/repo> <n> --branch <type>/<slug>`. It assigns the signed-in user and leaves one comment naming the branch and session (the desktop session id from the environment, else the CLI one). It refuses an issue assigned to someone else (ask the user; never take it over) and one filed by someone else unless the user OK'd claiming it (`--approved`).
- **Draft PR** (branch flow) at the first push of the task branch: title = the plan's title; body = the plan's one-line goal, then `ICLI closes DRAFT` (`Closes #<spec>` plus one `Closes #` per ticket). One task, one PR; a big implementation opens it from its integration branch.
- **Tick** after each ticket merge: `ICLI tick --repo <owner/repo> <ticket n>`.
- **Ready** (branch flow) at test-review YES: `gh pr ready <PR>`.
- **Close** when the task lands, never earlier. Branch flow: `/deploy` pushes the reviewed sha to `<base>` as usual, then checks that the PR shows merged and each `Closes` issue shows closed; one still open is reported, never closed by hand. Trunk flow: after the deploy record, `ICLI close --repo <owner/repo> DRAFT --sha <short sha>` closes each of the task's issues still open with "Deployed in <sha>.", the spec last.

## Consent
- The first live issue in a repo needs the user's explicit go-ahead, recorded as `Approved:` per contracts.md § Consent.
- After that, approving a plan or ticket breakdown covers publishing its issues, and claiming, commenting, ticking, the draft PR and closing the task's own issues after its deploy record are routine.
- Always ask first: claiming an issue someone else holds or filed, editing any issue the task did not create, and publishing in a repo neither § Map `Issues` nor the user names.
