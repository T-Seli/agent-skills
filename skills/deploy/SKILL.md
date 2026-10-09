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

**Go-ahead.** Per contracts.md § Consent. Given, now or earlier in the same request: proceed without asking. Not given: print the plan (**Print the plan**) and ask once, "Deploy this?"; a scheduled prompt or handoff only reports `awaiting user: deploy`.

**Modes.** PR (args `PR` only: the user asked for a PR), Local (no remote), Release (args `release`) and Rollback (args `rollback`): read only that mode in `${CLAUDE_SKILL_DIR}/references/modes.md` and follow it. § Deploy `Release: batched` or `Targets: none`: run the steps below but skip **Targets**, **Recheck times**, **Deploy**, **Verify**, the target part of **3-way sync**, and **Rechecks**; the task ends at the merge (batched: `/deploy release` ships it later).

## 1. Read the runbook
One `scout`: "Read CLAUDE.md § Deploy and every doc it points to. Return ≤300 words: each target with its kind (`deploy` or `sync`), command, landing check, how it reports its deployed version and how that maps to a commit, drift check, rollback and kill switch; trigger, skip-deploy marker, window, and the stages from `<base>` to `<release>`; every contradiction with § Deploy or with this brief." Where the runbook disagrees with this skill, it wins; say so. Section missing: end the report with `Add to CLAUDE.md § Deploy: <fact>`.

## 2. Preflight (read-only)
Run these checks. One that fails is reported in one line and asked about; nothing else stops the run.
1. **Task.** More than one pending folder has a YES and no later `deploy:` entry, and the request doesn't say which: ask which.
2. **Review.** The newest `Reviewed:` line in `TASK/log.md`, else `DRAFT/log.md`, gives `<sha>`. No review, a NO, or a release candidate SHA other than the exact reviewed `<sha>`: run `/test-review` on that exact candidate first (per § Chain), then continue. An unreviewed descendant is rejected even if it contains `<sha>`; do not silently advance the release ref. Report the reviewed commit and tree and the candidate commit and tree by running `python3 -m agent_skills.safeguard_cli release <repo> <reviewed-sha> <candidate-sha>`; nonzero exit blocks shipping.
3. **Base.** `git fetch origin`; `git merge-base --is-ancestor origin/<base> <sha>` fails: the base moved. Rebase, re-review, then continue; conflicts: ask.
4. **Lock.** `LOCK` held by another agent: ask. Stale: say its owner and age, and break it only when the user says to.
5. **Checkout.** Branch flow: HEAD is not `<base>` or a protected branch. Trunk flow: the main checkout is on `<base>` with no one else's uncommitted changes. Branch flow: uncommitted files in the main checkout that this deploy would overwrite: ask. Never stash or discard.
6. **Targets.** Each § Deploy `Targets` entry with its kind and landing check; read each one's deployed version (its rollback ref). Before the first target changes, write one task-local rollback receipt with `python3 -m agent_skills.safeguard_cli rollback-capture <task-local-path> --task <task-id> --release <sha> --repository <repo> --target <name=old-ref>` for every target; nonzero exit blocks shipping; retries reuse that first receipt and must not overwrite it. A missing or unreadable receipt after partial failure stops the run. Drift (hand patches, config changed in place): ask before overwriting it.

Then **Recheck times**: from § Observe `Traffic timing` and `Timezones`, when real traffic will exercise this change; up to `Rechecks per day` a day, in this machine's local time. Deadline: deploy + `Monitor window`.

## 3. Print the plan, then proceed
≤6 lines: repo and `<flow>`; `<base>` (and each stage up to `<release>` if it differs); the reviewed sha and its commit count; each target with its kind; rollback ref per target; recheck times. With a go-ahead, run to the end, stopping only where a step says so.

## 4. Ship
1. **Lock.** Already yours (trunk flow, taken by `/implement`): verify the exact owner line before refreshing its time. Else `mkdir "$LOCK"` (fails: stop). Owner line per contracts.md. Every successful exit from here releases only the exact lock whose owner line is still yours, by removing its owner file and then the empty directory; a failed target keeps it. Never recursively remove a lock.
2. **Push only the reviewed sha.** `git push origin <sha>:<base>`. Rejected: the base moved; handle it as in **Base**.
3. **Deploy** every target per § Deploy, one at a time, keeping the actual output: kind `deploy` ships the code (Trigger automatic: wait for that run); kind `sync` pushes the prompts or config at `<sha>` to its provider. Stages (`<release>` differs from `<base>`, or § Deploy lists stages): promote one stage at a time and pass **Verify** on each first.
4. **Verify** each target by its landing check. Kind `deploy` also: its reported version maps to the exact reviewed commit and tree (`python3 -m agent_skills.safeguard_cli release <repo> <reviewed-sha> <deployed-sha>`; nonzero exit fails verification); report both reviewed and deployed tree IDs, and reject an unreviewed descendant, the live artifact holds a string that exists only in this change, health and error rate since deploy are normal, and a fronting CDN serves the new asset. Kind `sync`: the provider holds the content at `<sha>`, with bindings and versions as the check expects.
5. **A failed target.** Stop: append to `DRAFT/log.md` which targets run new code and which old, with their rollback refs; keep `LOCK`; report. The user's "rollback" (Rollback mode) or "continue deploy" (resume at the failed target) is consent for that step, per contracts.md § Consent.
6. **Rechecks.** Create the schedule per contracts.md § Scheduler: `title` "Monitor <slug>", `description` naming the short sha and the deadline, `cronExpression` at the **Recheck times**, `prompt` = the scheduled prompt, `notifyOnCompletion: true`. It exists already (a redeploy): update it with the same fields.
7. **Record**: one record commit on top of HEAD, in this worktree (trunk: the main checkout). `<tasks>` is `none`: append the entry to `DRAFT/log.md` and skip the rest of this step.
   - Append `deploy: <short sha> to <targets>` to `TASK/log.md` (a new `TASK` starts from `DRAFT/log.md`): What changed, Evidence (each target and the commit it runs), `Rollback:` (ref per target), `Scheduler: <runtime> <id>`, Watch for.
   - Carry pending draft logs: each `$MAIN/.claude/drafts/<name>/log.md` whose `<tasks>/<name>/` is on `origin/<base>`, or that is its folder's only file and holds only `monitor:` entries, is appended to `<tasks>/<name>/log.md` (created if needed).
   - `git add` only those `log.md` files, commit, `git push origin HEAD:<base>` (rejected: fetch, rebase the record commit alone, retry, up to `Attempts before blocked` times).
   - Once pushed (Local mode: committed), delete every draft `log.md` carried, and each of those folders left empty.
8. **Local base.** Branch flow: repeat **Checkout**, then `git -C <that worktree> merge --ff-only origin/<base>` (or `git fetch origin <base>:<base>` if no worktree has it checked out). Overlap now: skip it and name the files.
9. **3-way sync.** `git rev-parse <base>` = `git rev-parse origin/<base>`; each target runs a commit that contains `<sha>`, and only record commits follow it (`git diff --quiet <that commit> origin/<base> -- ':(top,exclude)<tasks>'`). Report any mismatch.

## 5. Clean up
1. **This task** (branch flow). If the session is in the task worktree, load `ExitWorktree` via ToolSearch and call `ExitWorktree(action: "keep")`; if that fails, keep the worktree and branch and list them. After a fresh fetch, run `python3 -m agent_skills.safeguard_cli cleanup "$MAIN" <path> --base <base> --branch <branch> --completion-accepted --no-pending-effects --remote-base <fresh-origin-base-sha>` and include `--lock-path "$LOCK" --expected-lock-owner '<exact owner line>'` when a lock exists. Only an eligible result permits non-force worktree removal followed by `git branch -d`; any refusal keeps both. Never unlock, use `-D`, infer squash equivalence, or remove unique commits.
2. **Others.** List other worktrees, branches and stale-looking temp paths with their owners and reasons. Never prune or remove them automatically; ignored-only content, reused names, detached state, locks, unknown owners or missing acceptance all mean keep.
3. **Release the lock.** Verify its exact owner line is still yours, remove only its owner file, then remove the empty lock directory. A mismatch or nonempty directory is kept and reported.

## 6. Chain to monitor
Per contracts.md § Chain, after the report: § Observe `Traffic timing` says real traffic already reaches the change → start `/monitor <MAIN> <TASK> <sha>` now as a quick check. Otherwise no quick check; the rechecks cover it.

## Report (≤6 lines, per contracts.md § Report)
```
Deployed <short sha> (<n> commits) to <base> and <targets> at <UTC time> | Stopped: <which check or target> — <why>
Verified: <target> ✓ <check> · … · sync local = origin = deployed ✓ | <mismatch>
Rollback: <target>: <ref> · … · Record: <short sha> (+ <k> carried logs) · Kept: <name — reason>
Rechecks: <local times> (<runtime> <id>) | not scheduled: next <time>, run `/monitor <MAIN> <TASK> <sha>`
Decide: 1. <question> (default: <answer>)
Next: /monitor quick check | first recheck <time> | say "rollback" or "continue deploy"
```

Central history: when a private task-history checkout is configured, follow `/task-history` for sanitized milestone evidence and handoff. Preserve the project log and existing approval/review gates.
