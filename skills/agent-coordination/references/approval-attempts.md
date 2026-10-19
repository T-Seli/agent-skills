# Approval-attempt evidence

Use `agent_skills.approval_attempts` at explicit supported caller boundaries.
`approval-record <task-local.jsonl> <receipt.json>` and `approval-report <journal>`
are safeguard_cli subcommands. Neither sends, approves, retries nor publishes.
The JSONL sink is append-only under a lock and fsync; new files use mode 0600.
A corrupt/incomplete journal stops collection without truncating evidence.

One stable action ID binds owner, target, operation name, revision and exact
scope reference/hash. Each actual invocation gets an attempt ID; each later
observation gets a receipt ID and UTC observation time. Use retry_of for a known
same-action retry. New scope/target needs a new action ID. Replayed identical
receipt IDs deduplicate; changed content under an old ID fails. Never represent
an actual second invocation as a duplicate first invocation.

Approval contains the original source reference, channel and provenance. Keep
reviewer result/reason code/reason reference independent from delivery,
admission, execution and final verification. A successful send proves delivery
only. A completed command does not expose the reviewer's internal decision;
keep that field unknown unless an explicit review receipt is available.

At a supported call boundary, collect a before/after observation with stable IDs
and sanitized references. On a denied call, retain the denial, exact affected
operation and reason reference, then stop that action. On cancellation or
transport loss, retain the prior approval and mark outcome unknown until the
same invocation is reconciled. A changed user decision never edits old evidence.
No collector retry advice grants authority or overrides action-time review.

`execution_observation` maps existing workers.RunResult state/exit/time without
reading its stdout/stderr. Timeout remains unknown; exit zero leaves verification
pending. An explicit caller must persist it; no runner is silently wrapped.

There is no general native approval interception API verified here. The local
CLI is an explicit collection interface, not automatic coverage of every app or
worker. Native adapters must prove successful and failed capture at their real
boundary before claiming adoption. Do not read private session storage.

Only schema fields are accepted: IDs, scope hash/reference, bounded reason codes,
states and source references. Caller sanitization is still mandatory: opaque
references must not embed secrets, customer records, prompts or private reasoning.
Raw reviewer reasoning is excluded; retain its operational reason via a sanitized
code and accessible evidence reference. No new central registry is created.
Existing task-history capture can reference this local receipt after its own
authorization, owner/digest and publication checks.

Measure distinct actions, attempts, retries and explicit unknown coverage.
Separate permission rejection, source/target-specific security gates, stale
scope, accepted permission with failed delivery, transport failures, execution
failures and verified outcomes. Never optimize for fewer denials alone; measure
wrongly repeated asks, missing evidence, duplicate actions and recovery time.
