# Coordination state contract

Use one durable record per work item. The compact envelope below supplements the local status fields in `tasks.md`; native hosts may store equivalent fields in their task details.

## Active task contract

- `user_goal`, `constraints`, `priority_source_ref`: the current human outcome and its authoritative source.
- `canonical_issue_ref`, `canonical_owner`: the one issue/card and execution owner responsible for action.
- `active_deliverable`: `{id, revision, acceptance_ref, environment, changed_criteria, next_action, source_ref, requested_artifact, readback_ref, history_readback}`; revisions increase monotonically and an exact replay preserves state.
- `obligations`: displaced acknowledged deliverables retained as `queued` or `superseded`, with reason and source. Never silently drop one.

The existing brief projects active, displaced and completed subdeliverables separately: `{id, revision, owner, task_id, requested_artifact, artifact_ref, authority_ref, source_ref, latest_receipt, gates, material_facts}`. Two subdeliverables under one owner/task retain their own scope and gates; caller validation cannot close a separate source patch. Preserve original decision and authority references when displacing work. Do not create another registry or copy transcripts into the brief. Legacy records with missing bindings remain labeled unknown until reconciled.

For local records, `bind_task_contract(..., authority_ref, artifact_ref, gates)` pins this scope into the existing active contract and digest. `acknowledge_task_contract(..., decision_source_ref)` must name the original changed-criterion source, and `current_task_binding` carries that reference into the result. A wrong historical inner deliverable stays rejected even when the outer task matches; preserve actual effects and route recovery to the existing owner.

Only one deliverable is active. Changed criteria require a new revision. Before accepting worker progress on it, require a readback naming its ID, revision, changed criteria, environment and next action. Old results remain evidence but are labeled stale.

## Evidence cursor

For each source, retain `{last_consumed_receipt, observed_at}`. On resumption, page until that receipt is found before asking for progress or declaring evidence missing. If pagination ends first, report a coverage gap. A displayed summary, notification badge or process exit is not the cursor.

## Decisions and exposure

Keep ranked independent decisions separate from evidence: `[{id, rank, scope, target, prerequisites, mechanism, exposure_frequency, technical_risk, observed_impact, conditional_impact, business_decision, activation_state, priority_source_ref}]`. Conditional risk is not observed harm; low exposure does not erase impact; a technical recommendation does not decide a business tradeoff.

## Split state

Track independently:

- execution: `not-started | awaiting-dispatch | awaiting-readback | admitted | running | pause-requested | paused | blocked | awaiting-reconciliation | finished`;
- acceptance: `unreviewed | rejected | ready | verified | accepted`;
- user delivery: `not-delivered | delivered`, with an artifact and receipt; history publication: `not-published | published-unverified | readback-verified`;
- deployment: exact head, final-diff digest, scope, revision, lock owner, pause state and release-gate reasons;
- display sync per surface: `current | stale | unknown`, plus a receipt when current.

A pause request becomes effective only after the canonical execution owner confirms it. Release requires the current revision readback, matching recorded approval and scope, exact accepted head and final-diff identity, expected owner lock and any required pause receipt. Deployment success is not functional acceptance, and stale display does not change canonical state. A failed card write leaves display sync `stale` or `unknown` until a successful readback. Reconcile the latest authenticated task decision before updating a view or dispatching again; older summaries cannot restore superseded scope. Track promised replies, holds and manual/customer follow-through as separate existing gates/obligations, with owner and next action, so implementation or deployment cannot hide them. Use the current matrix/artifact identity from `workflow-contracts/behavior.md`.

## Material return loop

Keep useful facts inline, each with `{fact, source_ref, evidence_level}`, and the obligation's remaining gates. On a callback, read the latest exact worker result, page deeper only for missing or conflicting evidence, reconcile the brief, and answer from current scope. An inaccessible artifact link leaves inline facts usable but its unseen contents unverified.

For a changed dependency criterion, carry the original decision source and revision to the same owner/task. Record separately: admission; source-bound worker acknowledgment; matching result; parent read receipt and answer. `reconcile_parent_readback` checks the current binding, original decision source and exact result receipt before recording parent consumption. It neither accepts the artifact nor authenticates host authorship. A new revision invalidates the old loop; message delivery alone never closes it. Native consumption needs an actual supported host receipt, separately from these local library calls. Label server timestamps and reported clocks separately; do not infer consumption latency from gaps.

## Watches and milestones

A watch starts from `{watch_id, scope, digest, observed_at, source_ref}` and emits only on a changed digest or a stated deadline; an actual current wake/readback receipt is required to call it armed, and zero traffic is inconclusive. Milestones sent to the designated history owner are sanitized summaries of a contract revision/readback, decision, material blocker, release gate or acceptance result. `history_outbox` advances only through `pending → locally-appended → view-rendered → index-updated → published → readback-verified`; those stages carry receipts and never imply acceptance. They carry evidence references, never raw sessions, transcripts, secrets or customer data.
