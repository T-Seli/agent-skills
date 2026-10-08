# Coordination state contract

Use one durable record per work item. The compact envelope below supplements the local status fields in `tasks.md`; native hosts may store equivalent fields in their task details.

## Active task contract

- `user_goal`, `constraints`, `priority_source_ref`: the current human outcome and its authoritative source.
- `canonical_issue_ref`, `canonical_owner`: the one issue/card and execution owner responsible for action.
- `active_deliverable`: `{id, revision, acceptance_ref, environment, changed_criteria, next_action, source_ref, readback_ref}`; revisions increase monotonically and an exact replay preserves state.
- `obligations`: displaced acknowledged deliverables retained as `queued` or `superseded`, with reason and source. Never silently drop one.

Only one deliverable is active. Changed criteria require a new revision. Before accepting worker progress on it, require a readback naming its ID, revision, changed criteria, environment and next action. Old results remain evidence but are labeled stale.

## Evidence cursor

For each source, retain `{last_consumed_receipt, observed_at}`. On resumption, page until that receipt is found before asking for progress or declaring evidence missing. If pagination ends first, report a coverage gap. A displayed summary, notification badge or process exit is not the cursor.

## Decisions and exposure

Keep ranked independent decisions separate from evidence: `[{id, rank, scope, target, prerequisites, mechanism, exposure_frequency, technical_risk, observed_impact, conditional_impact, business_decision, activation_state, priority_source_ref}]`. Conditional risk is not observed harm; low exposure does not erase impact; a technical recommendation does not decide a business tradeoff.

## Split state

Track independently:

- execution: `not-started | awaiting-dispatch | awaiting-readback | admitted | running | pause-requested | paused | blocked | finished`;
- acceptance: `unreviewed | rejected | ready | verified | accepted`;
- deployment: exact head, final-diff digest, scope, revision, lock owner, pause state and release-gate reasons;
- display sync per surface: `current | stale | unknown`, plus a receipt when current.

A pause request becomes effective only after the canonical execution owner confirms it. Release requires the current revision readback, matching recorded approval and scope, exact accepted head and final-diff identity, expected owner lock and any required pause receipt. Deployment success is not functional acceptance, and stale display does not change canonical state.

## Watches and milestones

A watch starts from `{watch_id, scope, digest, observed_at, source_ref}` and emits only on a changed digest or a stated deadline. Milestones sent to the designated history owner are sanitized summaries of a contract revision/readback, decision, material blocker, release gate or acceptance result. They carry evidence references, never raw sessions, transcripts, secrets or customer data.
