# Decision interviews and delivery

Use for material design ambiguity, an explicit grill-me request or a big implementation (contracts.md § Chain), not as a mandatory gate for every task. Keep the record in the existing plan/task; no second tracker. Current authenticated task scope takes precedence over old drafts and completed handoffs. Use this for large items, architecture and critical decisions when material choices remain unresolved. Proceed directly with clear deterministic fixes within existing approved scope.

## Research and question rounds

1. Reconcile the goal, existing owner, latest decisions, constraints and source revision. State facts, hypotheses and choices separately. Look up available facts yourself with supported tools; missing access is an evidence gap, not a preference question. Use authorized read-only subagents when the calling workflow requires them; do not create another worker session or owner merely for questions.
2. Map material choices to prerequisite decision IDs. A question is ready only when its prerequisites are settled; dependent questions wait. Continue unrelated authorized work while evidence or answers are pending.
3. Ask only ready questions whose answer changes the outcome, in rounds of contracts.md § Defaults `Question round size` (a proposed default until the user sets it; a project § Defaults overrides it). Number them with stable IDs; explain the consequence, real alternatives and recommended answer. A recommendation is not a decision; silence is not acceptance. Never re-ask an answered question or record an unanswered one as settled. Separate approval requests from design questions, and never turn a go-ahead that already names its steps into per-step approval questions (contracts.md § Consent). Present each question with two or three concrete choices, an evidence-based recommended choice and rationale, and a free-text answer; word it so "yes" accepts the recommendation. Use the native structured question control when supported; otherwise present equivalent numbered choices. Preserve existing publication, deployment and access gates.
4. Record each answer with its authenticated source, scope, owner and revision in the existing task record. Distinguish proposed, answered, deferred and superseded. Retain rejected options and why. Recompute dependencies after answers; reopen only affected choices when new evidence or a later user decision invalidates them.
5. For an explicit interview, summarize the agreed goal, domain terms, behavior/exceptions, remaining assumptions and observable acceptance, then ask whether that captures the user's intent. Finish only when no ready question remains: every branch visited, nothing silently assumed. This confirms understanding only. Already clear, authorized implementation need not undergo another interview or approval round.

## Where the user answers

Technical design questions belong in the existing worker that owns the implementation; cross-task priority, ownership conflicts and broader scope/approval decisions belong with the parent. Respect the user's chosen surface and ability to stay with the parent. Relay original answers only through an authorized supported route; do not convert relays into new permission.

Before pointing the user elsewhere, verify the actual task/session ID, title, host and supported open/resume route. State the one decision's purpose, its question IDs, what it unblocks and what work can continue. Do not invent a link, create another session just for questions or move/interrupt a user session. If the route is unavailable, present the question on the current surface and record the gap.

After a worker answer changes shared scope, preserve its source and revision; notify only affected owners under existing communication authority. Require source-bound readback before dependent work relies on the change. A sent update is not consumption. Keep failed propagation open with its owner and next action, without undoing the user's valid decision or blocking independent work.

## Carry decisions through delivery

Reuse an existing project glossary when available; resolve materially conflicting terms rather than silently renaming them. Use consistent domain names in the existing plan: key terms, entities, states and invariants only when they remove ambiguity. Tie each desired behavior and exclusion to an observable acceptance check. Preserve existing capability and alternate producers per behavior.md; implementation details do not silently redefine the requested outcome.

Build dependency-ordered vertical slices that each demonstrate a meaningful behavior. Every item carries its decision/spec revision, prerequisites, exact scope, owner and acceptance check. Unknown choices block only their dependent slice. Reuse current tests and code; do not mandate arbitrary task counts or a full domain model for a small edit.

Implementation consumes the latest bound task and decision revision, never merely the newest pending draft. Review checks outcome coverage, changed assumptions and counterexamples against that same revision. A successful test, deployment or interview does not authorize a send, release, access change, install or publication.

At handoff/resume preserve the active deliverable, owner, revision, settled and open question IDs, decision sources, rejected options, next action and separate approval/acceptance state. Explicitly label older completed obligations historical so they cannot displace the current request. A later instruction supersedes only the scope it actually changes.

Retrospective: compare promised outcomes with evidence, identify the smallest reusable correction, and retain counterevidence. A proposed skill improvement stays proposed until authorized and tested; source publication, installation, loaded-session adoption and real-task behavior are distinct receipts. Never promise automatic adoption or reopen all settled decisions because a session changed.

Provenance and retained license: see THIRD-PARTY-NOTICES.md at the repository root.
