---
name: monitor
description: 'Check whether a change shipped in the last few days works on live traffic: confirmed, not yet exercised, or regressed, and what to change next. Read-only; runs after deploy and on scheduled rechecks. Use for "is it working", "monitor". Not for unexplained problems (blueprint).'
argument-hint: "[repo path] [task folder | commit]"
---

# Monitor

**Read-only** against production and git: no edits, database writes, restarts, deploys, or provider calls that send or change anything. If a check needs one, name it and ask. The only files written are draft-folder files (**Record**); never commit. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, `DRAFT`, `TASK`, log tokens, the follow-up folder, the scheduler and the defaults named below are per it.

## Inputs (first that exists; say which in one line)
1. Args: repo path, task folder, commit(s). Started by `/deploy` as a quick check (per contracts.md § Chain) or by the scheduled prompt (contracts.md): task id, deploy time, deadline.
2. Task records: `git show origin/<base>:<tasks>/<folder>/log.md` and `DRAFT/log.md`. Every `Watch for` line, every `deploy:` entry, and the newest `Scheduler: <runtime> <id>` line.
3. The conversation, including compaction summaries and pasted handoffs.
4. Discovery: `git log origin/<release> --since="<Monitor window> ago"` by the user or with the assistant co-author trailer; `deploy:` entries in `<tasks>/*/log.md` on `origin/<base>` from that window.

## 1. Build the change list
Group commits into changes, one user-visible behaviour each. Backfills, config flips and scheduled jobs are changes too. One line per change.

## 2. Confirm each change is live
- Merged: the commit is on `origin/<release>` (`git merge-base --is-ancestor <sha> origin/<release>`). With squash or merge-commit style (§ Deploy), find the merge by its PR number or merge commit (`git log origin/<release> --grep=<PR number or slug>`); a squash merge leaves no branch sha there. A PR not merged yet: say so, keep the schedule, stop.
- Still on the branch: `git log <merge commit>..origin/<release> -- <files>` shows no revert, and a symbol that exists only because of the change is still there.
- Still deployed: each target reports a version whose commit contains the merge (`git merge-base --is-ancestor <merge commit> <that commit>`); for static assets, fetch the live file and grep it. How to ask a target: CLAUDE.md § Deploy.
- Deploy time per target, in UTC. Every "since deploy" window starts there.
Overwritten or never deployed is a finding, not a pass.

## 3. Write the claims before looking
Per change: claim · live signal · pass when. Up to four kinds: **positive** (the new behaviour happened: count it, eyeball a sample), **negative** (the query that found the bug, windowed after deploy, returns 0), **blast radius** (errors, crashes, restarts, backlogs, latency: before vs after), **forward** (queued work that will hit the path soon).

## 4. Probe
Use the channels in CLAUDE.md § Observe (logs, errors and crashes, dashboards, database, user feedback); database reads follow `${CLAUDE_SKILL_DIR}/../workflow-contracts/data-access.md`. Section missing: discover them from repo docs and end with `Add to CLAUDE.md § Observe: <fact>`.
- Read what the code reads: same fields, conditions and fallbacks. Better: run the deployed code read-only on real records.
- Assert the environment and tenant before reading anything.
- Timestamps in UTC, converted with the zones in § Observe.
- A phased rollout (§ Observe `Rollout`): note the current share; traffic outside it proves nothing.
- No PII in output: mask identifiers, give user-written text as a short gist.
Many changes or tenants: up to `Parallel sub-agents` `scout`s, each returning counts and ≤100 words of evidence.

## 5. Classify
Each change lands in one bucket, with evidence:
- **Confirmed working**: real traffic hit it and every pass condition held.
- **Not yet exercised**: no real traffic has hit it since deploy (common on a quick check). Say so and when it will be; never turn silence or a 0 count into a pass. If waiting is risky, run the deployed code read-only on real records and label it "simulated, not observed".
- **Regressed**: the records, the impact, the likely cause.
- **Could not verify**: what access or instrumentation would settle it.
Attribute every anomaly as caused by a change, pre-existing, or unrelated, with the mechanism either way. Note improvements the live data suggests, ranked by impact, each with its evidence and smallest fix. Never apply one.

## 6. Record
Append `monitor: <verdict> — <one line>` (Evidence with counts and n) to `DRAFT/log.md`, creating it if needed. With no task, the folder is `<date>-monitor-<short sha>`. The next `/deploy` in this repo commits the entry.
On a regression, also create the follow-up folder (contracts.md) with one action item per regression, and name it in the entry. It is the record; the regression is unexplained behaviour, so it goes to `/blueprint` Answer mode (per contracts.md § Chain): `Next:` says `say "look into it"`, and blueprint reads the follow-up folder.

## 7. Keep or end the schedule
Load the scheduler tools (contracts.md). Task id: from the args, else the log's `Scheduler:` line, else the id per contracts.md in `list_scheduled_tasks`.
- **Ownership:** only the runtime named in the `Scheduler:` line updates or deletes the schedule. Running in the other runtime: change nothing; report `owned by <runtime> <id>, left` and what the owner should do.
- **Delete:** delete, then verify per contracts.md § Scheduler. Still listed: report `still exists: <id>`, log it, never `deleted`.

There is no push tool: the alert is the report's first line, which the task's completion notice carries. Alert once per finding: if an earlier `monitor:` entry already reported it, list it under Problems without leading with it.
- **Regressed:** alert (what broke, impact, one line) and keep the schedule.
- **All confirmed:** note it in the entry and call `delete_scheduled_task({ taskId })`.
- **Anything not yet exercised:** keep the schedule.
- **Past the deadline** (from the args): final report, delete the task, alert if anything is unverified.
- Manual run, something pending, nothing scheduled: first check the log for a `Scheduler:` line and the list for the id, so none is duplicated. Neither exists: create it with `/deploy`'s fields (recheck times, deadline = deploy + `Monitor window`) and append `Scheduler: <runtime> <id>` to the entry. Scheduler unavailable: end with the next recheck time and the command (contracts.md).

## Report (≤8 lines, skeleton per contracts.md § Report)
```
<ALERT: what broke — impact · >Verdict: All working | Working, with issues | Not yet exercised | Regression found — <one line>
Confirmed: <change>: <evidence with count, n>
Not yet exercised: <change>: <why; when>
Problems: <issue>: <impact>; <caused by change | pre-existing | unrelated>
Record: <log path> · Follow-up: <r2 folder> · Schedule: kept, next <local time> (<runtime> <id>) | deleted | still exists: <id> | owned by <runtime> <id>, left | none: next <time>, run `/monitor …`
Decide: 1. <improvement>: <evidence>; <smallest fix> (default: <…>)
Next: say "look into it" (/blueprint) | next recheck <local time> | nothing
```
The ALERT prefix only for a new regression. Drop empty lines. If an earlier probe of yours was wrong, correct it here plainly.
