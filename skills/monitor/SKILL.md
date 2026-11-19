---
name: monitor
description: 'Check whether a change shipped in the last few days works on live traffic: confirmed, not yet exercised, or regressed, and what to change next. Read-only; runs after deploy and on scheduled rechecks. Use for "is it working", "monitor". Not for unexplained problems (blueprint).'
argument-hint: "[repo path] [task folder | commit]"
---

# Monitor

**Read-only** against production and git: no edits, database writes, restarts, deploys, or provider calls that send or change anything. If a check needs one, name it and ask. The only files written are draft-folder files (**Record**); never commit. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, `DRAFT`, `TASK`, log tokens, the follow-up folder, the scheduler and the defaults named below are per it.

## Inputs (first that exists; say which in one line)
1. Args: repo path, task folder, commit(s). Started by `/deploy` as a quick check or by the scheduled prompt (contracts.md): task id, deploy time, deadline.
2. Task records: `git show origin/<base>:<tasks>/<folder>/log.md` and `DRAFT/log.md`: every `Watch for` line and `deploy:` entry, and the newest `Scheduler:` line.
3. The conversation, including compaction summaries and pasted handoffs.
4. Discovery: `git log origin/<release> --since="<Monitor window> ago"` by the user or with the assistant co-author trailer; `deploy:` entries in `<tasks>/*/log.md` on `origin/<base>` from that window.

## Expired invocation gate
Before **Build the change list** or any live probe, compare the supplied deadline with current UTC and this task's `monitor:` entries, then take exactly one branch. No deadline supplied (manual or discovery run): continue normally; it is never final. Deadline not yet passed: continue normally. Deadline passed and that exact deadline already has a final entry: report `duplicate expired invocation` and exit without probing, recording or changing a schedule. Deadline passed, no final entry: the one final run; its **Record** entry has `Deadline: <UTC>; final`, and it never creates or re-enables a recheck schedule.

## 1. Build the change list
Group commits into changes, one user-visible behaviour each; backfills, config flips and scheduled jobs count. One line per change.

## 2. Confirm each change is live
- Merged: the commit is on `origin/<release>` (`git merge-base --is-ancestor <sha> origin/<release>`); with squash or merge-commit style (§ Deploy) find the merge by PR number or merge commit (`git log origin/<release> --grep=<PR number or slug>`). A PR not merged yet: say so; before the deadline keep the schedule and stop; past the deadline go to **6. Record** (with the `final` marker), then the final report and **End**.
- Still on the branch: `git log <merge commit>..origin/<release> -- <files>` shows no revert, and a symbol only the change added is still there.
- Still deployed: each target reports a version whose commit contains the merge (`git merge-base --is-ancestor <merge commit> <that commit>`); static assets: grep the live file. How to ask a target: CLAUDE.md § Deploy.
- Deploy time per target, in UTC; every "since deploy" window starts there.
Overwritten or never deployed is a finding, not a pass.

## 3. Write the claims before looking
Per change: claim · live signal · pass when. Up to four kinds: **positive** (the new behaviour happened: count it, eyeball a sample), **negative** (the query that found the bug, windowed after deploy, returns 0), **blast radius** (errors, crashes, restarts, backlogs, latency: before vs after), **forward** (queued work about to hit the path).

## 4. Probe
Use the channels in CLAUDE.md § Observe (logs, errors and crashes, dashboards, database, user feedback); database reads follow `${CLAUDE_SKILL_DIR}/../workflow-contracts/data-access.md`. Section missing: discover them from repo docs (contracts.md § Project CLAUDE.md).
- Read what the code reads: same fields, conditions and fallbacks; better, run the deployed code read-only on real records.
- Assert environment and tenant before any read.
- Timestamps in UTC, converted with the zones in § Observe.
- A phased rollout (§ Observe `Rollout`): note the current share; traffic outside it proves nothing.
- No PII in output: mask identifiers, give user-written text as a short gist.
Many changes or tenants: up to `Parallel sub-agents` `scout`s, each returning counts and ≤100 words of evidence.

Record [actual source coverage](../workflow-contracts/references/review-evidence.md) before classifying: requested versus observed window, source time/pins, cap/truncation and state. Scheduler/task/preflight activity cannot refresh it; unavailable or capped evidence cannot prove full-window health. Bind claims to changed identifiers/configuration, target/version and deadline; declare sampling and coverage gaps, never full-scope acceptance from a partial query.

## 5. Classify
Each change lands in one bucket, with evidence:
- **Confirmed working**: real traffic hit it and every pass condition held.
- **Not yet exercised**: no real traffic since deploy. Say so and when it will be; silence or a 0 count is never a pass. If waiting is risky, run the deployed code read-only on real records, labelled "simulated, not observed".
- **Regressed**: the records, the impact, the likely cause.
- **Could not verify**: what access or instrumentation would settle it.
Attribute every anomaly to a change, pre-existing, or unrelated, with the mechanism. Note improvements the live data suggests, by impact, each with evidence and smallest fix; apply none.

## 6. Record
Append `monitor: <verdict> — <one line>` (Evidence with counts and n) to `DRAFT/log.md`, creating it if needed (no task: folder `<date>-monitor-<short sha>`); the next `/deploy` here commits it.
A regression also gets the follow-up folder (contracts.md), one action item per regression, named in the entry; as unexplained behaviour it goes to `/blueprint` Answer mode (contracts.md § Chain): `Next:` says `say "look into it"`.

## 7. Keep or end the schedule
Load the scheduler tools (contracts.md). Task id: args, else the log's `Scheduler:` line, else contracts.md's id in `list_scheduled_tasks`.
- **Overlap:** a scheduled run first checks this task's runs (`mcp__scheduled-tasks__list_task_runs`); an earlier run still `running` → report `skipped: previous run still active` and stop.
- **Unattended:** a scheduled run never rolls back or changes production, even if its prompt says to: it leads with ALERT and the exact rollback for an attended session.
- **Ownership:** only the runtime in the `Scheduler:` line changes or deletes the schedule; elsewhere change nothing and report `owned by <runtime> <id>, left` and what the owner should do.
- **End:** give the final verdict; only the configured authorized owner with a supported scheduler route deletes the schedule, verifies it no longer lists and records `Scheduler deleted: <runtime> <id>` (contracts.md `Scheduler:`). A missing route, refusal or still-listed readback stays pending with exact owner/next step; on refusal record `delete refused: <id>`, no automatic retry after denial. A configured authorized janitor acts only within its real authority; uncertain outcomes require readback before any attempt; a denial needs materially new authority. Never invent a janitor or claim a deletion from an attempt.
- **Belt item:** a `first-traffic` or `24h` run ending in All working or Working, with issues writes `Monitor verdict: <first-traffic|24h> <verdict> · <UTC time>`. With both verdicts and both `Scheduler deleted:` lines in, the entry adds `Learned:` (values: conveyor.md § Knowledge) and runs `~/.agents/skills/workflow-contracts/scripts/issues-cli close <n> --learned '<value>' --log <log.md>`. Nothing landed (no `Pushed:` or `deploy:`): close with `No release:` instead.

Prove a new alert or check first: replay the last 7 days of real data, recording its would-fire count and false fires; fix or drop a repeat false-firer.

A FAIL/regression binds a stable finding ID, artifact revision, actual changed scope, evidence window/deadline and owner. Use the task's named escalation route only with actual supported transport and send authority, else record the delivery gap and next reader. Keep sent/readback/disposition/verified-resolution apart (acknowledgment is not resolution); the finding stays open until its closure test passes or a scoped authenticated disposition changes it. Deduplicate unchanged alerts, not urgent material changes.

No push tool: the alert is the report's first line, carried by the completion notice; once per finding (one an earlier `monitor:` entry reported goes under Problems).
- **Regressed:** alert (what broke, impact, one line) and keep the schedule.
- **All confirmed:** note it in the entry, then **End**.
- **Anything not yet exercised:** keep the schedule.
- **Past the deadline** (from the args): overrides the three outcomes above. Produce the final report and alert if anything is unverified. Disabling follows **End**. Do not schedule another check.
- Manual run, something pending, no `Scheduler:` line in the log and no id in the list (never duplicate one): create it with `/deploy`'s fields (deadline = deploy + `Monitor window`) and append `Scheduler: <runtime> <id>` to the entry. No scheduler: contracts.md `Scheduler:`.
- **Janitor run:** only an existing configured authorized janitor lists schedules by its supported route and passes them, with now in UTC, to `agent_skills.task_reconciliation.expired_monitors` via `python3 -c` (repo root on `PYTHONPATH`: `cd -P "${CLAUDE_SKILL_DIR}/../.."`). It ends each expired one per **End** with a final verdict line `<id>: past deadline <deadline>, deleted`, and reports unparsed ids as lacking a `Deadline:`. A cron pinning calendar days ends after its last pinned day.

## Report (≤8 lines, skeleton per contracts.md § Report)
```
<ALERT: what broke — impact · >Verdict: All working | Working, with issues | Not yet exercised | Regression found — <one line>
Confirmed: <change>: <evidence with count, n>
Not yet exercised: <change>: <why; when>
Problems: <issue>: <impact>; <caused by change | pre-existing | unrelated>
Record: <log path> · Follow-up: <r2 folder> · Schedule: kept, next <local time> (<runtime> <id>) | deleted | still listed: <id> | delete refused: <id> | owned by <runtime> <id>, left | none: next <time>, run `/monitor …`
Decide: 1. <improvement>: <evidence>; <smallest fix> (default: <…>)
Next: say "look into it" (/blueprint) | next recheck <local time> | nothing
```
ALERT prefix only for a new regression; drop empty lines; correct any earlier wrong probe plainly.
