---
name: system-audit
description: 'Run a bounded independent read-only audit of agent coordination, workspace navigation, verified failures, guards, evidence, decision friction and release boundaries. Use for a system audit or scheduled audit run; never changes the audited system.'
argument-hint: '<time window, scope and prior audit reference>'
---

# System audit

First read `${CLAUDE_SKILL_DIR}/../agent-coordination/references/independent-reviewer.md`, `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`, [references/reviewers.md](references/reviewers.md) and `${CLAUDE_SKILL_DIR}/../task-history/SKILL.md` for the owner-bound proposal contract. This is an independent read-only audit, not an implementation, approval, performance score or authority transfer. The human owns priorities and consequential decisions; the orchestrator owns reconciliation and synthesis; workers own task-local investigation.

Apply [review evidence](../workflow-contracts/references/review-evidence.md): actual source coverage, accountable/execution owner separation, acceptance loops, optimization counterevidence and observed consumer adoption. Reuse existing findings rather than status-only replacement work.

## Inputs

Use, in order: explicit time window and scope in the request · current canonical task records and owner receipts · prior audit artifact and acceptance checks · available read-only host records. Declare the required evidence surfaces for that scope before synthesis; each is `observed`, `unavailable`, `not-checked` or explicitly `not-applicable` with a receipt. An omitted or unavailable prerequisite prevents complete coverage without authorizing new access. If time window or scope is absent, use the current task and the preceding 24 hours, label that default, and do not broaden it. Cover every material contract revision, blocker, decision, handoff, release gate and acceptance event in-window; for unchanged in-flight work, sample at most three records deterministically by oldest evidence cursor and report the denominator. State every unavailable surface and resulting coverage limit.

## Reconcile before review

List canonical work items, execution owners, active deliverable revisions, in-flight work and evidence cursors. Do not interrupt, resume, archive, message or alter an active session. A direct user instruction to a worker remains authoritative within its verified scope; compare it with the current task contract instead of treating it as interference. Page supported records to the last consumed receipt before calling context missing. Protected or unsupported cross-session data stays unread; never use session files, credentials or exports as a workaround.

Check whether each material item is discoverable through one canonical task, owner and supported thread/workspace reference, with accurate status, pending decision, next authorized action, receipt-checked links and artifact provenance. A stale or duplicate surface is a navigation finding and closure-readiness recommendation, not authority to rename, move, archive or create another registry. Missing host metadata is a coverage gap; never infer it from a folder or thread ID.

## Independent review

Launch up to four read-only reviewers in parallel, within contracts.md limits, using the distinct angle packets in `reviewers.md`. Give each only the declared window, scope, sanitized task identities, primary evidence references and known coverage limits—not prior findings or another reviewer's conclusions. Reviewers must not coordinate with one another, contact third parties, modify state or infer facts from missing access. If sub-agents are unavailable, run the same angle packets sequentially and label independence unavailable.

Each finding states: evidence and claim level · impact on the user's goal · counterevidence · root cause, hypothesis or known platform limitation · minimal remedy · regression risk · one observable acceptance test. Incomplete evidence is a coverage finding, not a cause. Measure only supported outcomes: repeated context requests, duplicate investigation, missed evidence, time blocked on a specific decision, false blockers and successful handoffs. Never invent productivity scores, rank people or infer user performance.

## Failure and guard ledger

Audit every meaningful failed, rejected or blocked operation in-window when a primary receipt verifies it, including messaging operations, deployments, context handoffs, local executor disconnects, release races, invalid tool arguments, unsupported models/operations and progress hidden by incomplete reads. A generic error without evidence establishing its class remains a coverage finding; do not count or diagnose it as a verified incident.

For each verified occurrence record: stable incident/failure keys · operation and target · UTC time · exact failure class and receipt · user impact · authenticated already-approved scope or explicit authorization state · retries and evidence attempted · exact next supported action and owner · whether that step is human-only · repeat-of identity · prevention check, state and receipt. Use exactly one current class: legitimate policy limit · missing/incorrect approval provenance · unavailable tool · stale session placement or ID · transport/offline failure · unsupported operation · invalid arguments · implementation defect. Deduplicate identical occurrence IDs and group true repeats by stable failure key, operation, target and class; never hide the repeat count.

Authorization and capability are separate. Once an authenticated direct user message covers the same operation, target and scope, replace any missing-approval blocker with the verified current capability/transport/session/tool blocker. Do not ask for approval again and do not claim the handoff or operation succeeded. An unavailable tool, unsupported placement read and stale-session send are separate receipt-backed occurrences even when they block one user goal.

Recommend only the mapped supported remedy: respect a policy limit, repair approval provenance, restore a tool, refresh session placement/ID, reconcile before a bounded transport retry, use a supported operation, correct arguments or fix an implementation defect. State a concrete human-only step separately when the platform exposes no agent action. Never recommend bypassing, disabling, overriding or routing around a guard, denial or security boundary. Track a prevention check as passed/failed only with a receipt; a later repeat after a pass is a regression, while no observed repeat in one window is not proof of permanent prevention.

## Human unlocks

Against the user's actual daily task-list receipt, identify a small set of human-owned decisions that can unlock meaningful ready work. For each record the canonical task and owner · human effort (`quick`, `short` or `extended`) · readiness receipts and safety state · risk · downstream impact (`high`, `medium` or `low`) with its task-list/evidence basis · downstream work unlocked · UTC deadline · dependencies and shared resources · exact decision wording · already-authorized independent work that can continue in parallel. Never infer impact or priority from task count, worker utilization or apparent idleness.

Recommend at most three decisions, ordered by the user's daily priority, deadline, readiness/risk, receipt-backed downstream impact and then human effort. Preserve the full canonical daily unlock list in the artifact, including not-ready records and ready records beyond the display limit; never create two decision records for one task. A quick decision is never recommended merely because it is easy: the work must be actually ready, safe and supported by receipts. Never make or pressure a business decision, invent work to keep agents busy, change ownership, or launch duplicate work. Keep already-authorized independent work flowing under its recorded owner while a longer design decision proceeds; the audit reports that concurrency but does not dispatch it.

## Synthesis

Reconcile reviewer disagreement against primary receipts. Keep unresolved conflicts visible and lower confidence; do not vote facts into existence. Deduplicate by the stable mechanism key, scope and acceptance test—not a reviewer-local finding ID—and retain every ID as an alias with its evidence. Equivalent new IDs are one recurrence, contradictory assertions remain disputed, and distinct scopes remain separate. For an unchanged repeated finding, report its prior ID and current acceptance-test state instead of proposing it again. Rank a small improvement list by user-goal impact, evidence strength, reversibility and regression risk; preserve independent decisions separately. A recurring audit proposes bounded changes with acceptance tests and held-out missing/blocked/unseen fixtures; it never self-approves, requires a change every run or turns zero traffic into a pass.

Produce a concise user brief and a durable sanitized artifact at the configured task-artifact path (else return it inline without inventing a path). Its envelope is `{schema_version, audit_id, revision, scope_ref, window, prior_artifact_ref, record_owner, history_base:{revision,digest}, synthesis, failure_ledger, human_unlock_plan, history_publication:"proposed-not-appended"}`; findings retain stable IDs, current evidence windows and acceptance state, `failure_ledger` contains the deduplicated verified occurrence groups and prevention state, and `human_unlock_plan` preserves readiness, ownership and non-automation. Reuse the canonical task record for live state and task-history for durable milestones; do not create another queue, scorecard or authority layer. Prepare owner-bound proposed history events against the freshly read owner/revision/digest; do not append. No finding or unlock self-approves a change. Skill edits, deployments, production changes, access expansion and external messages require a separate authorized step. A caller may schedule this skill, but one audit run never creates or duplicates its schedule.

## Report (≤10 lines)

Window/scope · evidence coverage and limits · strongest verified finding · verified failure/guard count with repeats and prevention state · unresolved disagreement · prior improvements and acceptance state · up to three remedies with acceptance tests · human-only step or `None` · artifact/proposed-history owner/state · next authorized step.
