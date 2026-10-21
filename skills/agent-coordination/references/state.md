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

## Local operating checkpoints

Use the existing record/store APIs with `record_checkpoint` for priority, blocker, next action and due time; displaced obligations keep that checkpoint and owner. `record_watch_checkpoint` and `record_watch_result` record due times and actual wake/readback evidence against the baseline. They create no schedule or process. Overdue checks mean continuation is unverified; they do not prove process death. Historical completed checks remain visible separately from current arming and functional acceptance.

Watch ownership remains pinned to the recorded execution owner when the outer task changes owner. Automatic watch ownership transfer is unsupported; reconcile the actual existing observer and its receipts before adopting a new owner. A baseline reset is not proof that an observer transferred or started.

`record_claim` appends explicit corrections naming the superseded claim receipt; briefs omit precisely referenced displaced facts. Use per-fact references: the helper cannot infer contradictions in arbitrary prose. Decision replacements preserve history and reject previously superseded sources. Neither interface authenticates a source or grants authority.

`record_execution_context` scopes sanitized host, shell, executable, identity and configuration references to labeled probe receipts. `capture_provenance` binds the existing Git code-state digest to a caller-supplied test receipt. Reconcile actual probe/test evidence separately; these interfaces do not run it. Inspect a saved record read-only with `python3 -m agent_skills.safeguard_cli task-status <record.json>`. The same projection feeds `communication_brief` and `attention`; native callers must explicitly invoke it. Local fresh/resumed consumers do not establish native host or model adoption.
# Bounded recovery assessment

`python3 -m agent_skills.safeguard_cli task-reconcile snapshot.json --now <UTC>`
reads only the explicit snapshot. Supply `expected_task_ids`, `records`, and
`observations`; each observation binds task ID, revision, decision source,
observation time and expiry. A bounded inventory can establish completeness only
relative to its supplied expected IDs, not all conversations. Exact canonical
`required_operations` and `forbidden_operations` expose intersections; the caller
must resolve broad natural-language restrictions before constructing this envelope.
The assessment never dispatches, treats approval as delivery, or closes a task.

For critical local launch/resume/handoff, use the existing task's bounded owned protection: `safeguard-cli keep-awake status <receipt>` freshly verifies host/boot, supervisor and assertion PID/start/executable, assertion ID/timeout and AC. Legacy receipts remain receipt-only; observation freshness is at most 120 seconds, independently of the grant expiry. Unknown/denied probes or battery/unknown power hold dependent critical steps; they prove neither sleep nor shutdown.
Use one canonical existing task artifact directory and its recorded owner first. `keep-awake reuse <receipt> --consumer <owner> --task-id <task> --until-utc <UTC>` queues a bounded reference; wait for the foreground owner's consumer readback, then recheck status. No ownership/control transfers. Same task/owner/host serializes across receipt names; stale/conflicting records require reconciliation, never duplicate acquisition or stale-lock deletion.
Without suitable coverage, explicitly invoke `keep-awake acquire <request.json> <new-receipt.json>` in a retained supported foreground executor. Request binds task_id, owner, host_id (read-only `keep-awake host`), approval_ref, foreground_ref, authorized_until_utc, segment_seconds (1..14400) and check_seconds (1..60). These fields reference existing scoped authority, not a new grant. Retain/poll that execution handle; no nohup, disown, daemon or detached fallback. The command wrapper retains its task/duration/command interface; its ephemeral receipt is not durable handoff evidence.
Only the supervisor renews within the immutable authorized UTC/monotonic end: verify the successor before releasing its own old Popen child. Native whole-second timeouts round by less than 1 second; the supervisor clamps to the exact authorized end. `keep-awake renew|release <receipt> --owner <owner> --generation <generation>` queues control, not completion. Recheck its acknowledgment/current assertion; release respects acknowledged unexpired consumers. Missing handles or observations remain unknown; parent-turn completion is not support-executor completion.
Before side effects and every handoff, consume a new status/readback (normally checked each 60 seconds); an old receipt with a future expiry is not fresh. Reuse never extends the user's window. Expiry/cancel/completion releases only proven own children and verifies process exit plus assertion absence; failed cleanup stays explicit. No unrelated PID/group signals, persistent power/display/security settings, credential/access change, or indefinite wake. Real Mac/host-turn lifecycle qualification requires its own bounded harmless scratch window; fake tests or installed source alone do not prove it.
For explicitly critical delegation, select `delegate.py start` with the three `--critical-*` inputs in worker-execution.md. It pins the existing foreground owner's contract, requests an exact bounded task/dispatch consumer acknowledgment, rechecks before worker launch and omits the legacy detached assertion. Fresh `keep_awake_current` gates new critical work separately from historical `keep_awake` and business outcome. Admission or queued extension is not verified coverage; original authorization and the current acknowledged grant both bound reuse. A first observed coverage failure remains a HOLD. Ordinary/default delegation still launches its separate legacy assertion and reports only `launched-unverified`; it remains unqualified for critical acceptance and must not be combined with this supervisor as a fallback. No current process is migrated or stopped. Whole-host-turn continuity, automatic recovery, enforcement of every worker side effect and broad route adoption remain unqualified until directly supported.
`task-reconcile` remains pure: supply the current observation in `keep_awake` with `critical_execution: true`; it assesses evidence only, never acquires, renews, releases or grants permission. Keep admission, current protection, business results and cleanup separate. If coverage is lost, hold new dependent critical actions and reconcile the existing command's result rather than replaying or killing business work.

On transport loss, distinguish app connection status, executor admission and
actual CLI result. Record each layer's timestamp and diagnostic. Reconcile the
existing command's exit/output before retrying an uncertain launch. Do not infer
sleep from a disconnected transport or loop indefinitely on reconnection.
