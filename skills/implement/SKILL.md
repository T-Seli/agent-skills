---
name: implement
description: 'Build an approved plan or fix: code, prompt or config changes, tested and committed one item at a time per the project''s flow. Use when the user says "approved", "fix it", "do it", or gives a concrete edit. Not before approval, and not for reviewing or shipping.'
argument-hint: "[draft folder | slug | one-line instruction]"
---

# Implement

Turn approved action items into tested changes in the authorized isolated workspace. Commit only when the user-approved workflow covers it; no shared-branch synchronization, publication or cleanup follows automatically. When the user or the brief asks to share, push the task branch (`git push -u origin <type>/<slug>`) and open a draft PR; that is sharing, not a release. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, `<flow>`, `LOCK`, `DRAFT`, `TASK`, pending, record commits and the defaults named below are per it. No remote: `origin/<base>` below means `<base>`.

## Inputs (first that exists; say which in one line)
1. Args: a draft folder or slug; any other text is a one-line instruction → **One-line plan**.
2. The explicit Draft/task path in the current conversation or handoff, verified against the active goal and decision revision. Without a named path, reuse only a unique matching task record; multiple matches need one choice. Never select merely the newest pending draft or an unrelated completed task.
3. Approved in this conversation: a plan and action items → write them to a new draft folder first; a single instruction, or "fix it" after a blueprint Answer's `Fix:` line → **One-line plan**.
4. None: ask once, "No approved plan found. Paste the action items or a one-line instruction, or run /blueprint first?", and stop.

Consent is scoped user authority per contracts.md § Consent. Use `${CLAUDE_SKILL_DIR}/../workflow-contracts/decisions.md` for decision dependencies: an interview answer confirms a choice, not unrelated implementation or release. `/implement` must bind a concrete action and target. `<type>` and `<slug>` come from the `plan.md` header, else the folder name and items.

**One-line plan** (a single approved instruction with no draft): create a new draft folder `<date>-<slug>` holding a two-line `plan.md` (`# <goal>`, then `Done when: <check>`) and a one-item `action-items.md` in the /action-items item format, whose `Where` names every file the change needs (read the code first to find them). Then start **Steps**, including **Deployment readiness** when applicable.

**Item kinds:** code | prompt | config, from the paths in the item's `Where`. A prompt item (a prompt, knowledge base or agent config) records a before/after diff of the changed text under What changed in its log entry, and runs § Run & test `Prompt checks` in **Loop** step 2: in addition to `Fast tests` when it also touches code, instead of them otherwise.

**Clean check** (trunk): `git -C "$MAIN" status --porcelain` shows no changes outside the current item's paths and pending `log.md` changes. Else stop and name the other paths.

**Resume**: bind the latest authenticated task, decision/source revision and open items before choosing a draft. Complete applicable **Deployment readiness**, inspect the owned workspace and preserve dirty files. Do not automatically rebase, reset or switch branches. Branch: enter the verified existing owned worktree by its path; verify its branch/source before editing. Trunk: reacquire the owned LOCK and run Clean check. Reuse baseline evidence only when source and environment match, otherwise run affected checks. Do not rerun Sync on resume; continue Loop from the first ready authorized item.

## Steps
0. **Deployment readiness.** Before deployment-related implementation starts or resumes, perform contracts.md's read-only deployment-readiness preflight. Reuse still-current source-bound evidence; retain unknown/blocked checks and continue independent authorized work. Readiness never adds deployment approval or permissions.
1. **Sync.** No remote: skip. Else `git fetch origin`, then `git rev-list --left-right --count <base>...origin/<base>`:
   - Behind only: record source freshness and use the specifically authorized base. Do not fast-forward shared branches automatically; hold a dependent base change until its scope is established, and continue independent work.
   - Ahead or diverged: stop and name the local-only commits.
2. **Collision check.** For every other worktree (`git worktree list --porcelain`) and every local branch committed to within `Active-work window` and not merged into `origin/<base>`: changed files = `git diff --name-only origin/<base>...<branch>` plus that worktree's `git status --porcelain`. Intersect with the files the plan and action items name. Overlap: name the exact paths and owners; hold dependent edits until ownership is resolved. Preserve unrelated changes and continue nonconflicting authorized work.
3. **Workspace.**
   - **Branch.** Create the worktree with git so the branch name and base are exact:
     ```
     git -C "$MAIN" worktree add --lock --no-track -b <type>/<slug> "$MAIN/.claude/worktrees/<slug>" origin/<base>
     ```
     Then load `EnterWorktree` via ToolSearch (`select:EnterWorktree,ExitWorktree`) and call `EnterWorktree(path: "$MAIN/.claude/worktrees/<slug>")`. Don't use `EnterWorktree(name)`: its branch name and base depend on user settings. Tool unavailable: work there with absolute paths. Run the worktree setup from CLAUDE.md § Run & test (files to copy or symlink, install, test services). Verify: `git branch --show-current` is `<type>/<slug>` and `git merge-base --is-ancestor origin/<base> HEAD` passes.
   - **Trunk.** No worktree: work in `MAIN` with absolute paths; `git -C "$MAIN" branch --show-current` must be `<base>`, else stop. Take `LOCK`: `mkdir` it and write `owner` = `<agent> <branch> <UTC time>`. It exists with another owner: stop and name the owner, and say if it is stale (never delete it); yours (**Resume**): rewrite the time. Then run the **Clean check** for the first item.
   - Run the full test suite once. Its failing test ids are the baseline.
4. **Start record.** Reuse the bound existing task record. Append source identity, authorized scope, baseline results and collision decisions. Copy or commit only explicitly scoped task files when the workflow authorizes it; preserve drafts and unrelated content, with no automatic deletion.
5. **Loop**, one action item at a time, in the order given:
   1. Verify the item's prerequisites and `needs D<id>` decisions are settled at the current revision; hold only dependent items and never take an unanswered default. Make the change. Touch only what the item needs. A bug's reproduction test and its fix go in the same commit.
   2. Run § Run & test `Fast tests` (not defined: the full suite), or `Prompt checks` per **Item kinds**. A failure not in the baseline set blocks the commit. Blocked after `Attempts before blocked` tries: preserve the failed candidate and diagnostics, log it under Not done, and stop edits/tests in that shared worktree so failures cannot contaminate later items. Continue only independent read-only work or an already-authorized isolated workspace with a clean bound baseline. Cleanup or restoration requires its own scope; never delete files automatically.
   3. Trunk: run the **Clean check**. Stage only this item's paths plus pending `log.md` changes (`git add <paths>`, never `-A`). If commits are authorized, commit per § Map's convention (default `<type>(<scope>): <item in plain words>`); trunk commits on `<base>`.
   4. Append a log entry `implement: <item>` with the commit's short sha. It rides in the next commit.
   - **Parallel** only for items tagged `parallel-safe` whose prerequisites are verified complete at the current decision/source revision (and committed when the authorized workflow requires commits): up to `Parallel sub-agents` sub-agents edit the workspace at once, on disjoint files, with no git commands. Each returns ≤100 words: files changed, what, open questions. Then test and commit each item separately as above. Everything else runs sequentially.
   - Anything outside the plan (contracts.md § Plan scope): stop and ask.
6. **Finish.** Run the full suite. Append `implement: done` (Evidence: test command, base sha, head sha, failing ids vs baseline; Watch for: what monitoring should check on live traffic). When authorized, record commit with subject `implementation log for <slug>` (`<tasks>` is `none`: no commit). Branch: stay in the worktree. Trunk: keep `LOCK`; `/deploy` cleanup releases it. Print the report, then start test-review per contracts.md § Chain.

## Report (≤6 lines, per contracts.md § Report)
```
Implemented <slug>: <n>/<m> items, <k> commits on <type>/<slug> at <worktree> | on <base>
Tests: <passed>/<total>; vs baseline: no new failures | new: <ids>
Not done: <item — why> · Collisions: <branch: files>   (omit empty parts; omit the line if both are)
Decide: 1. <question> (default: <choice>)               (omit if none)
Next: test-review, starting now
```
If § Run & test was missing, end with `Add to CLAUDE.md § Run & test: <fact>`.

Central history: when it is configured (contracts.md § Task log), follow `/task-history` for sanitized milestone evidence and handoff; otherwise the log entry says `History: not configured`. Preserve the project log and existing approval/review gates.
