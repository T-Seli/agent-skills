---
name: test-review
description: 'Answer "is this ready to deploy?" for the current work, a PR or a commit range: tests first, then each commit. Says YES, or NO with blockers only; read-only. Use for "ready?", "review PR 12", "review the commits". Not for style cleanups or edits.'
argument-hint: "[tests | PR <n> | PR URL | branch | commit range]"
---

# Test review

Decide one thing: is this ready to deploy? Strictly read-only: no code or test edits, code commits, rebases or merges; fixes go through `/implement`. Its only writes: its log entry (§ Log), `gh pr ready <PR>` on an authorized readiness YES for a tracked draft PR (`${CLAUDE_SKILL_DIR}/../workflow-contracts/issues.md` **Ready**: never an advisory draft review, never a release-member PR), and its own temp worktrees and test services. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, `DRAFT`, `TASK`, temp worktrees, record commits, "outside the plan" and the defaults named below are per it.

For an explicitly authorized non-Git prototype review, use [portable execution proof](../workflow-contracts/references/execution-proof.md) before resolving Git paths: bind base/final content manifests, scoped checks and an allowed review receipt. Keep independence and unmet gates; do not invent commits or call a prototype pass deployment acceptance.

Apply [Documentation currency](../workflow-contracts/behavior.md#documentation-currency): check the exact candidate's `Doc impact:` disposition and actual changed guidance/links against verified decisions and artifacts. Missing disposition or stale/conflicting authority in this scope is a finding; route corrections to the owner, never edit in review.

## Inputs (first that exists; name it and its head sha in one line first)
1. Args: `PR <n>`, `#<n>` or a PR URL → **PR mode**; `sweep` → **PR sweep**; a branch → it against `UP`; a commit range → those commits. A leading `tests` → **Tests mode**.
2. The current task branch `<type>/<slug>`.
3. The conversation: a branch, PR or range named earlier.
4. Discovery: `HEAD`, ranged per `<flow>` below.

`UP` = `origin/<base>` after `git fetch` (contracts.md § Git); no remote: `<base>`. Range = `$BASE..<head>`, `<head>` = `HEAD` unless an input names one:
- Branch flow, a branch or a PR: `BASE=$(git merge-base UP <head>)` (a PR: its own base in place of `<base>`). A PR's diff must be a subset of `merge-base(integration branch, head)..head`, the integration branch being the plan's recorded target; a stacked base is retargeted to it before merge, then the subset is rechecked.
- Trunk flow (`HEAD` on `<base>`): `BASE` = the sha in the newest `deploy:` heading of any task or draft log; else `origin/<base>`; else the newest `Reviewed:` sha, so the range starts at the first commit after it; none: ask for a range and stop.

Empty committed range with no worktree changes: say so and stop. A worktree candidate first needs a complete manifest: `~/.agents/skills/workflow-contracts/scripts/safeguard-cli manifest <repo> --include <each new source path> --exclude-private <each private untracked path>` (the installed release's helper; never a bare module or stale `PYTHONPATH`). Resolve every untracked name explicitly; nonzero exit blocks review. Record its digest and rerun just before approval or release; any change invalidates review. A worktree review stays provisional until the exact source is committed and reviewed; never read private payloads into the manifest. PR targets need the git host CLI from CLAUDE.md § Map (read the PR, fetch its head); no CLI: review the branch if it exists here.
Intent per commit: its action item in `TASK/action-items.md` (the log's `implement: <item>` entry names its sha); else the PR body; else the commit message. No approved plan: blocker 6 is skipped.

**Tests mode** (`/test-review tests`): run **Tests** only, then reply with the report's Tests line. No commit review, verdict, log or chain.

Use [research evidence](../workflow-contracts/references/research.md) for claim/source and installed-version checks, and [review evidence](../workflow-contracts/references/review-evidence.md) for real coverage, owner/acceptance and optimization claims.

For UI/frontend or visualization changes, load [ui-design](../ui-design/SKILL.md) and compare the exact rendered artifact, interaction/state matrix and accessible alternatives with the selected design packet. Offline: compose `company.test-review company.ui-design`; automated checks alone are not visual or human acceptance. Production today, the base for a change users see: `${CLAUDE_SKILL_DIR}/../workflow-contracts/data-access.md` § Live app.

New customer-facing text that breaks [plain language](../workflow-contracts/references/plain-language.md) is advice in the report, never a blocker.

## 1. Tests (before reading any code)
Check the current decision/spec revision, domain invariants, exclusions and each slice’s user-visible acceptance per `${CLAUDE_SKILL_DIR}/../workflow-contracts/decisions.md`. Reopened assumptions invalidate only affected evidence; passing checks never resolve unanswered user choices.
Classify changed paths and risk first. Small prompt/KB/instruction fixes get semantic synthetic cases and producer-path checks per `${CLAUDE_SKILL_DIR}/../workflow-contracts/behavior.md`; exact generated wording is no acceptance oracle. Reuse evidence only after comparing its source, tests, dependencies and environment, citing the comparison. Never repeat paid/live simulations merely for freshness; new external runs need scoped authority. Consent, integrity, exact-source and shared-release checks still apply.
For hosted checks and automated or draft review, load [hosted-review.md](references/hosted-review.md): a green check name alone is insufficient, and sweep draft exclusions change only by its separate opt-in.
One `scout` runs this; for a **small change** (one S item and ≤50 changed lines outside tests, or config/copy only) run it yourself, reusing implement's logged results when they match. Either returns ≤150 words: commands, pass/fail per side, new failing ids, red/green per fix test. Commands: CLAUDE.md § Run & test; output per global CLAUDE.md § Verification. Test services only where that section defines them, with run-unique resource names and ports, torn down after.
Codex: run these steps in this session; its scout follows a read-only workflow under the parent's permissions.
Temp worktrees: contracts.md; list leftovers, never prune another run's path.
1. **Branch:** reuse implement's logged results when the command matches and `git diff --quiet <logged head sha> <head> -- ':(top,exclude)<tasks>'` passes. An instruction-only change may reuse earlier code-test evidence on compared relevant paths plus fresh bounded semantic checks, naming paths and limits. Else run the applicable suite where the head is checked out (or a temp worktree at it), with project-required aggregate release checks, recording sorted failing ids.
2. **Base:** reuse logged results for the same base sha and command. Else run `safeguard-cli disk-check "$MAIN" <the worktree path below> "$(git -C "$MAIN" rev-parse --path-format=absolute --git-common-dir)"` (main, destination and Git dir volumes; proceed only on exit 0, any other exit or no helper: start nothing, say why), choose one run-unique id and `git worktree add --detach --lock --reason "test-review <run-id>" "$MAIN/.claude/worktrees/_base-$(git rev-parse --short $BASE)-<run-id>" $BASE`, run the setup, copy in the branch's tests if § Run & test says tests are not tracked by git, run the suite, record failures.
3. **New failures** = branch minus base. Rerun each once on both sides; one that flips is flaky, not new.
4. **Instruction fix proof:** compare base and candidate on neutral realistic scenarios without giving evaluators the desired answer; assess decisions and retained constraints, not identical prose. If base already passes, report preserved behavior, not an invented regression. **Code fix proof** (branch `fix/…` or any `fix` commit): in the base worktree, `git checkout <head> -- <new or changed test files>` (untracked: copy them) and run only those. Each must fail there on an assertion and pass on the branch. A compile, import or collection error at the base is "not shown".
5. Before removal, restore the checked-out tests in the base worktree (`git restore --source=HEAD --staged --worktree -- <files>`; delete copied untracked ones). For each temp worktree this run made, run `~/.agents/skills/workflow-contracts/scripts/safeguard-cli cleanup "$MAIN" <path> --base <base> --run-id <run-id> --completion-accepted --no-pending-effects` (add `--rebuildable <dir>` per § Run & test `Worktree setup`). Only an eligible result permits `git worktree unlock` (when `unlock: true`) and non-force removal; keep and report any other path. Then list what the deploy sweep would remove (apply only where deploy authority exists).

## 2. Commits
Check each commit (skip record commits) against its intent and callers. Up to `Parallel sub-agents` `scout`s get the range, the intents and § Blockers verbatim, and return only blockers (≤150 words, `<short sha> <path:line> — what breaks, for whom — fix`, or "none"):
- **Callers** (a small change: check them yourself): callers and consumers of every changed symbol, signature, return shape, table, field or config key; return those the change breaks and any second path for the same data it missed.
- **Safety** (blockers 3–4) and **Scope** (blockers 2, 5, 6): for a range over `Review fan-out above`; smaller, check these yourself.
Open each returned line; keep only listed blockers you can show. For visual acceptance, inspect the exact fixture and whole requested surface against the production reference; metadata or an HTTP success is not artifact proof.

## Blockers
Report only these: no nice-to-haves, style, refactor or dedupe suggestions, no "consider". Unsure it is a blocker? Drop it. Greps run over `ADDED` = `git diff -U0 $BASE <head> -- ':(top,exclude)<tasks>' | grep '^+[^+]'`, minus test paths, docs and fixtures; a hit is a lead until you open the line.
1. **Tests:** a new failure vs base, or a fix whose test does not fail on base and pass on the branch.
2. **Wrong or breaking:** the commit does not do what its action item says, a completion claim lacks its Done when evidence, an open item is omitted from Not done, or a caller or consumer breaks.
3. **Security:** a secret in code, logs or URLs (`grep -inE "(api[_-]?key|secret|token|passw|bearer|private[_-]?key)[\"']?\s*[:=]\s*[\"'][^\"']{8,}"`, `-----BEGIN`, provider key prefixes, newly tracked env or credential files); PII (phone, email, name, address) sent to a third party or LLM; an auth check removed or bypassable.
4. **Production data:** a script, job, backfill or migration writing to production without asserting its target (writes in normal request handlers are exempt); DDL (`CREATE|ALTER|DROP|TRUNCATE`) outside the migration dirs; a migration that is not idempotent or has no down path; a wrong tenant or database target.
5. **Tenant or environment logic in shared code:** a tenant name, alias or id from CLAUDE.md § Tenancy, or `prod|production|staging`, in shared code outside config; branching on either (`grep -nE "(==|!=|===|!==|\bin\b|case|switch).*[\"'](prod|production|staging)[\"']"`, and the same with tenant names); a hard-coded tenant, agent or job-type id, or an id added to a list or branched on by name where registration or config would do; a per-install name, brand, phone number or agent display name in shared content (prompts, tool descriptions, templates, copy); a prompt grown past its ratchet or failing the project's prompt lint (behavior.md § Agent prompts). § Tenancy `none`: environment names only.
6. **Unplanned:** anything outside the plan (compare `git diff --name-only $BASE <head>` with the plan, its Out of scope and action items).

## Log
Before a release-ready YES or § Chain, persist the review evidence: `test-review: <YES|NO>` per contracts.md, holding `Reviewed: <head sha> <YES|NO>`, exact tree/manifest identity, the Tests line and relevant reused-evidence comparison. Read the saved receipt back and verify its `Reviewed:` SHA is the current candidate head. A failed/unconfirmed log write is a recording gap, not release evidence; use an authorized task-local equivalent if the normal log is unavailable, otherwise hold any release-ready YES, the chain and release; a NO or blocker report may still print, marked unsaved. Never rerun tests solely to repair receipt storage.
- PR mode: append to `$MAIN/.claude/drafts/<date>-pr-<n>/log.md` (or the newest existing `drafts/*-pr-<n>/`) for `/deploy`; no commit.
- `TASK` on the branch: append to `TASK/log.md` and make a record commit of only that file, subject `review <slug>`.
- Otherwise: append to `DRAFT/log.md`.
- Tracked task: the entry also holds `Reviewer: session <id> · head <head sha> · <outside|fallback>`; on a YES run `~/.agents/skills/workflow-contracts/scripts/issues-cli lane <n> ready-to-release --log <log.md>` (it refuses when this session holds the claim).

## PR sweep
For a scheduled run. `python3 "${CLAUDE_SKILL_DIR}/scripts/pr_sweep.py" pending` prints one JSON line per open non-draft PR head/base/policy with no authenticated verdict yet (none: report `nothing pending` and stop). For each, in its `checkout`, run **PR mode** on that head, then post the report with `pr_sweep.py post --repo <repo> --pr <n> --sha <head_sha> --base <base_sha> --policy <policy> --verdict YES|NO --body-file <report file>`. Shadow mode keeps the local report (`posted: false` is not publication). A refused or uncertain post waits for supported readback, never a blind retry. Migration and single-publisher limits: hosted-review.md. Never approve, merge, deploy or edit the PR; a failed review posts nothing.

## PR mode
Same review for a PR, plus its summary line in the report and its own log (§ Log). Post the report as a PR comment only if the user asks or the PR sweep runs this, then only through `${CLAUDE_SKILL_DIR}/scripts/pr_sweep.py post` (one authenticated comment per head/base/policy on the configured publisher host; `pr_sweep.authorization` in the agent-skills config is the user's standing approval). Never approve, request changes or merge.

## Report (readable markdown for someone who hasn't seen the code; never a fenced block)
Print a release-ready YES only after the exact-head § Log receipt is saved and read back; a NO or blocker report may be printed without it. Deploy or the implementation loop follows only a saved receipt, whose reference the report includes; a chat YES alone is not release evidence. Caps per contracts.md § Report. These lines, in order; nothing else:

1. PR mode only: **What it does:** two plain sentences, the problem and then the change, from the PR body and diff.
2. **Ready to deploy: YES.** or **Not ready to deploy: <k> blocker(s).** plus a short clause, e.g. "each needs a small fix".
3. NO only, one line per blocker: **<n>. <what breaks, as a plain headline>.** What happens, for whom, and the evidence (test output, live data with n, a line you opened) · [<path>:<line>](<path>:<line>) (+ short sha in a multi-commit range) · Fix: <one line>
4. **Tests:** <n> pass on the branch. New failures vs `<base>`: <k> (name them, or "none"). <m> other failures also fail on base. Fix proof: <ok | n/a (why) | not shown: <test>>. Clean: <the checks that found nothing, e.g. callers, secrets, tenant logic, scope>.
5. **Next:** YES: deploying now (go-ahead given) or "say deploy". NO: next step per contracts.md § Chain.

With the persisted exact-candidate review receipt available, follow contracts.md § Chain: YES → deploy if a go-ahead was given, else ask once; NO → the implement loop.

A fenced, paste-ready block only on request (e.g. a PR comment).

Central history per contracts.md § Task log (`History: not configured` when off), keeping the project log and approval/review gates.
