---
name: deploy
description: 'Ship reviewed work once the user has given a go-ahead ("deploy", "merge and deploy", or a request that included it): push, deploy or sync every target, prove each landed, record it, then start monitoring. Without a go-ahead it asks once. Not for questions about deploys.'
argument-hint: "[task folder | branch | PR | release | rollback]"
---

# Deploy

Get the reviewed sha onto `<base>` and every target, prove it landed, record it, and start monitoring. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, `<flow>`, `DRAFT`, `TASK`, `LOCK`, consent, record commits, the scheduler, the report and the defaults named below are per it.

## Inputs (first that exists; say which in one line)
1. Args: a task folder, slug or branch; `PR <n>` → deploy that reviewed PR, its task folder being the newest `drafts/*-pr-<n>/`; `PR` alone, `release` or `rollback` → that mode.
2. Trunk flow: the pending task whose newest `Reviewed:` line says YES. Branch flow: the current branch and `TASK/log.md`.
3. The conversation.
4. Discovery: `<base>` (trunk) or the current branch (branch) against `origin/<base>`.

**Go-ahead.** Per contracts.md § Consent: given now or earlier in the same request, or an `Approved:` receipt for this task: proceed without asking. Not given: print the plan (**Print the plan**) and ask once, "Deploy this?"; a scheduled prompt or handoff only reports `awaiting user: deploy`. An outstanding candidate follows `${CLAUDE_SKILL_DIR}/../workflow-contracts/behavior.md` § Release train.

**Modes.** PR (args `PR` only: the user asked for a PR), Local (no remote), Release (args `release`) and Rollback (args `rollback`): read only that mode in `${CLAUDE_SKILL_DIR}/references/modes.md` and follow it. § Deploy `Release: batched` or `Targets: none`: run the steps below but skip **Targets**, **Recheck times**, **Deploy**, **Verify**, the target part of **3-way sync**, and **Rechecks**; the task ends at the merge (batched: `/deploy release` ships it later).

## 1. Read the runbook
One `scout`: "Read CLAUDE.md § Deploy and every doc it points to. Return ≤300 words: each target with its kind (`deploy` or `sync`), command, landing check, how it reports its deployed version and maps it to a commit, drift check, rollback and kill switch; trigger, skip-deploy marker, window, and the stages from `<base>` to `<release>`; every contradiction with § Deploy or with this brief." Where the runbook disagrees with this skill, it wins; say so. Section missing: contracts.md § Project CLAUDE.md.

## 2. Preflight (read-only)
A failing check is reported in one line and asked about; nothing else stops the run.
1. **Task.** More than one pending folder has a YES and no later `deploy:` entry, and the request doesn't say which: ask which.
2. **Review.** The newest `Reviewed:` line in `TASK/log.md`, else `DRAFT/log.md`, gives `<sha>`. No review, a NO, or a release candidate SHA other than the exact reviewed `<sha>`: run `/test-review` on that exact candidate first (§ Chain). An unreviewed descendant is rejected even if it contains `<sha>`; never silently advance the release ref. Report the reviewed commit and tree and the candidate commit and tree by running `~/.agents/skills/workflow-contracts/scripts/safeguard-cli release <repo> <reviewed-sha> <candidate-sha>` (the installed release's helper); a missing entrypoint blocks shipping, never falling back to a bare module or stale `PYTHONPATH`.
3. **Base.** `git fetch origin`; `git merge-base --is-ancestor origin/<base> <sha>` fails: the base moved. Rebase, re-review, then continue; conflicts: ask. Reconcile target-specific live identity through the project-supported read route; do not assume a target Git checkout or remote layout. For Git-mapped targets, a live SHA outside the intended release lineage needs a target-owner reconciliation disposition before overwrite; other targets use their actual artifact/version mapping. An unknown mapping holds only that target, not independent preparation; never reset a target to manufacture lineage.
4. **Lock.** `LOCK` held by another agent: ask. Stale: say its owner and age, and break it only when the user says to.
5. **Checkout.** Branch flow: HEAD is not `<base>` or a protected branch; main-checkout uncommitted files this deploy would overwrite: ask. Trunk flow: the main checkout is on `<base>` with no one else's uncommitted changes. Never stash or discard.
6. **Targets.** Each § Deploy `Targets` entry with its kind and landing check; read each one's deployed version (its rollback ref) and current health and error rate (the pre-deploy reading). Before the first target changes, write one task-local rollback receipt: `~/.agents/skills/workflow-contracts/scripts/safeguard-cli rollback-capture <task-local-path> --task <task-id> --release <sha> --repository <repo> --target <name=old-ref>` for every target; nonzero exit blocks shipping; retries reuse, never overwrite, that first receipt; a missing or unreadable receipt after partial failure stops the run. Drift (hand patches, config changed in place): ask before overwriting it.

Then **Recheck times**: from § Observe `Traffic timing` and `Timezones`, when real traffic will exercise this change; up to `Rechecks per day` a day, in this machine's local time. Deadline: deploy + `Monitor window`. A small change (test-review's definition) gets one recheck at the first real-traffic time and a deadline just after it.

## 3. Print the plan, then proceed
≤6 lines: repo and `<flow>`; `<base>` (and each stage up to `<release>` if it differs); the reviewed sha and its commit count; each target with its kind; rollback ref per target; recheck times. With a go-ahead, run to the end, stopping only where a step says so.

For the scope summary use `${CLAUDE_SKILL_DIR}/../workflow-contracts/behavior.md`: added customer-flow steps, exceptions/deferred work, reply holds and each task's exact approval boundary; source publication, target installation, fresh-runtime load and observed behavior acceptance stay separate. Update only declared, supported entries; another personal adapter or saved-environment owner gets an exact validated patch/source-pin handoff, not an assumed installation.

## 4. Ship
1. **Lock.** Already yours (trunk flow, taken by `/implement`): verify the exact owner line before refreshing its time. Else `mkdir "$LOCK"` (fails: stop). Owner line per contracts.md. Every successful exit from here runs **Release the lock**; a failed target keeps it. Never recursively remove a lock.
2. **Push only the reviewed sha.** `git push origin <sha>:<base>`. Rejected: the base moved; handle it as in **Base**. Where the base requires pull requests (the push is refused), land the release PR with a merge commit; then run `/test-review` on that landed merge commit (its tree must equal the tested release-branch head's), so the reviewed sha is the deploy sha, with one deploy-record id.
3. **Deploy** every target per § Deploy, one at a time, keeping the actual output: kind `deploy` ships the code (Trigger automatic: wait for that run); kind `sync` pushes the prompts or config at `<sha>` to its provider. Stages (`<release>` differs from `<base>`, or § Deploy lists stages): promote one stage at a time and pass **Verify** on each first.
4. **Verify** each target by its landing check. Kind `deploy` also: its reported version maps to the exact reviewed commit and tree (`~/.agents/skills/workflow-contracts/scripts/safeguard-cli release <repo> <reviewed-sha> <deployed-sha>`; nonzero exit fails verification); report both tree IDs and reject an unreviewed descendant; the live artifact holds a string only this change has; health and error rate since deploy are no worse than the pre-deploy reading (a failure present before the deploy is noted, not a failed target); a fronting CDN serves the new asset. Kind `sync`: the provider holds the content at `<sha>`, with bindings and versions as the check expects.
   Health/version checks prove deployment only: unobserved behavior keeps its acceptance gate and promised manual follow-through, under monitor within scope; never manufacture traffic or paid simulations.
5. **A failed target.** Stop: append to `DRAFT/log.md` which targets run new code and which old, with their rollback refs; keep `LOCK`; report. The user's "rollback" (Rollback mode) or "continue deploy" (resume at the failed target) is consent for that step.
6. **Rechecks.** For required observation within actual scope/authority, reconcile the existing authorized monitor owner and supported scheduler route, then create the schedule per contracts.md `Scheduler:` (a belt item gets two: `first-traffic` at the first real-traffic time, `24h` a day after deploy): `title` "Monitor <slug>", `description` with the short sha and `Deadline:`, `cronExpression` at the **Recheck times**, `prompt` = the scheduled prompt, `notifyOnCompletion: true`; reuse an existing task, never duplicate it. Bind it to the actual changed scope (identifiers, configuration, target/version), evidence window and deadline. A required monitor unavailable, unarmed or unauthorized: keep observation/acceptance pending with owner/next check and report the deployment result separately; never call an executed deployment unshipped or invent a scheduler capability. A not-applicable check needs a scope-based reason.
7. **Record**: one record commit on top of HEAD, in this worktree (trunk: the main checkout). `<tasks>` is `none`: append the entry to `DRAFT/log.md` and skip the rest of this step.
   - Append `deploy: <short sha> to <targets>` to `TASK/log.md` (a new `TASK` starts from `DRAFT/log.md`): What changed, Evidence (each target and the commit it runs), `Rollback:` (ref per target), one `Scheduler: <runtime> <id>` per schedule, `History: <event id> | not configured` (contracts.md § Task log), Watch for.
   - Belt item: the go ran as `~/.agents/skills/workflow-contracts/scripts/safeguard-cli run-approved release <id> --digest <d>`, which merges, pushes and writes `Pushed:` and `Rollback:`; a § Deploy `Targets` entry that is not a branch ships only on the user's own go-ahead, and this `deploy:` entry is its receipt. Then `~/.agents/skills/workflow-contracts/scripts/issues-cli lane <n> monitoring --log <log.md>`.
   - Carry pending draft logs: each `$MAIN/.claude/drafts/<name>/log.md` whose `<tasks>/<name>/` is on `origin/<base>`, or that is its folder's only file and holds only `monitor:` entries, is appended to `<tasks>/<name>/log.md` (created if needed).
   - `git add` only those `log.md` files, commit, `git push origin HEAD:<base>` (rejected: fetch, rebase the record commit alone, retry, up to `Attempts before blocked` times).
   - Once pushed (Local mode: committed), delete every draft `log.md` carried, and each of those folders left empty.
8. **Local base.** Branch flow: repeat **Checkout**, then `git -C <that worktree> merge --ff-only origin/<base>` (or `git fetch origin <base>:<base>` if no worktree has it checked out). Overlap now: skip, naming the files.
9. **3-way sync.** `git rev-parse <base>` = `git rev-parse origin/<base>`; each target runs a commit that contains `<sha>`, and only record commits follow it (`git diff --quiet <that commit> origin/<base> -- ':(top,exclude)<tasks>'`). Report any mismatch. Tracked task (`plan.md` has `Issue:`): per `${CLAUDE_SKILL_DIR}/../workflow-contracts/issues.md` **Close**, verify merged/closed facts apart from deployment and acceptance; report unexpected open or early-closed issues without forcing state. Trunk flow: `ICLI prepare-evidence --repo <repo> --draft DRAFT`, fill actual deployment and criterion/closure receipts, then `ICLI close --repo <repo> DRAFT --sha <full sha> --evidence-file <receipt.json>` only when every affected issue meets its gate; open observation and human obligations stay. Report actual results, not intended state.

## 5. Clean up
1. **This task** (branch flow). In the task worktree: `ExitWorktree(action: "keep")` (load via ToolSearch); on failure keep and list the worktree and branch. After a fresh fetch, run `~/.agents/skills/workflow-contracts/scripts/safeguard-cli cleanup "$MAIN" <path> --base <base> --branch <branch> --completion-accepted --no-pending-effects --remote-base <fresh-origin-base-sha>` and include `--lock-path "$LOCK" --expected-lock-owner '<exact owner line>'` when a lock exists and one `--rebuildable <dir>` per `rebuildable:` entry in § Run & test `Worktree setup`. Only an eligible result permits `git worktree unlock` of this task's worktree when it says `unlock: true` (implement locked it), non-force removal, then `git branch -d` only when it says `merge: ancestor`; any refusal keeps both. Never unlock another task's worktree, use `-D`, delete a branch on a `no-op` proof, or remove unique commits.
2. **Others** (behavior.md § Release train). Run `~/.agents/skills/workflow-contracts/scripts/safeguard-cli sweep "$MAIN" --base <base> --apply` (`--rebuildable` as in step 1). It removes, without force, each other worktree that passes the cleanup check and no live session holds, and deletes a branch only on `merge: ancestor`. List its `held` and `kept` entries with their reasons; foreign locks, unknown owners or missing acceptance mean keep. Print `df -h /` before and after. List drafts older than `Active-work window` with a merged outcome as archive candidates (target `~/Developer/worktree-archive`); move them only with the user's go-ahead.
3. **Release the lock.** Verify its exact owner line is still yours, remove only its owner file, then remove the empty lock directory. A mismatch or nonempty directory is kept, reported.

## 6. Chain to monitor
Per contracts.md § Chain, after the report: § Observe `Traffic timing` says real traffic already reaches the change → start `/monitor <MAIN> <TASK> <sha>` now as a quick check. Otherwise the rechecks cover it.

## Report (≤6 lines, per contracts.md § Report)
```
Deployed <short sha> (<n> commits) to <base> and <targets> at <UTC time> | Stopped: <which check or target> — <why>
Verified: <target> ✓ <check> · … · sync local = origin = deployed ✓ | <mismatch>
Rollback: <target>: <ref> · … · Record: <short sha> (+ <k> carried logs) · Kept: <name — reason>
Rechecks: <local times> (<runtime> <id>) | not scheduled: next <time>, run `/monitor <MAIN> <TASK> <sha>`
Decide: 1. <question> (default: <answer>)
Next: /monitor quick check | first recheck <time> | say "rollback" or "continue deploy"
```

Central history: contracts.md § Task log; the project log and existing approval/review gates stay.
