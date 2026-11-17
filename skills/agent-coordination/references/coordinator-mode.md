# Engineering coordination with the shared skills

Read [roles](roles.md) for role/reread alignment. For startup briefs and the full session lifecycle, use the on-demand [engineering coordinator guide](../../../ENGINEERING-COORDINATOR.md).

An engineering coordinator is a worker at a higher level of scope. Its artifact
may be an integrated plan, verified readiness packet or handoff; narrower workers
own the implementation slices. Use the same shared skills and authority rules
at both levels, not a second catalog or a parallel workflow.

## Keep the next action focused

Use the existing skill index to select the next procedure, then load its body and
needed references on demand. Do not preload every skill. Reuse a body already
loaded from the same release within this context; reread after a material source
change or context loss. A fresh worker still needs its relevant instructions.
Use `prime-context` for entry, `agent-coordination` for owned execution and result
consumption, `grill-me` for material decisions, and `handoff` for succession.
The owning worker uses `blueprint`, `action-items`, `implement`, `tdd` and
`test-review` at the scope of its artifact. These are shared procedures, not
separate coordinator and implementer skill sets. Use `approval-handoff` only for
a concrete blocker; `task-history` only with its configured record owner.

Keep a compact current summary in the existing task record (goal, owner, revision, workspace/head, artifact, latest receipt, gate, next action, evidence cursor) and consume each finished result once per [state](state.md#coordinator-follow-through).
For a user-designated GitHub queue, reconcile the current issue and linked PRs
per `../../workflow-contracts/references/github-queue.md`. Preserve the primary
engineering coordinator and independent reviewer roles; either host or a future
paired runtime consumes the same packet and authority, without a new dispatcher.
Latest authenticated user instructions supersede only their actual scope;
historical manual-only defaults are not proof of a present execution limit.

`TASKS.md` is a view of the canonical project queue, never a second tracker; its verified record owner persists rows under actual authority and unknown coverage stays unknown. Board, STOP and release-card formats: the guide.

## Worker capacity
Up to 10 working sessions at once. Each may take a larger scope and start nested workers; nested workers, scouts and reviewers count toward `max_live`, disk and test slots. Before starting or nesting, check the disk floor and a free test slot (workspace-and-train.md). A refused start waits; the coordinator never takes the work over.

## Apply specs and verification at the right level

Bind each worker to the current accepted specification, ticket, agreed seams and
observable done-when checks. Small deterministic fixes retain the ordinary
one-line-plan path; do not create a large spec merely to coordinate them.
In implement's spec mode, stay thin: consume receipts and use its merger/reviewer
owners. A generic worker-limit fallback does not authorize taking their work.
Distinguish logical prerequisites from shared files, compute, ownership, priority
and release gates. Keep the exact hold reason and independent work visible.

Check actual adherence through supported invocation/source-read and artifact
receipts. A skill name in a prompt or a plan file on disk is not proof it was
followed. Missing invocation evidence is unknown, not proof of noncompliance.
Separate test-first assertion failure, regression proof on a base, mutation
sensitivity and import/collection failure. Never relabel one as another or invent
a missing worker receipt. Inspect the exact accepted artifact and current head;
component checks do not prove a different consumer, deployment or live outcome.

## Reduce waste without weakening checks

Give each worker the relevant task slice and shared evidence pointers, not the
whole coordinator conversation. Use local tool profiles only for genuinely local
work; keep connector-dependent work on a capable route. Tools and skills remain
different controls, and host-specific profiles do not create a security boundary.
Honor the user's current model/effort policy and verify observed settings from
runtime output. Reuse unchanged source/environment-bound test and review evidence;
do not rerun a completed full suite simply to refresh a status report. Required
composed and release checks still run when their artifact or prerequisites change.

Measure child startup, parent overhead and whole-task request usage separately,
including input/cache/output and actual model where available. Report retries,
held launches and missing cost metadata separately. CLI-reported dollar amounts
and cached-input totals do not establish subscription quota consumption. Do not
attribute a weekly limit to one mechanism without account-wide evidence.
Workspace hygiene and the draft-PR release train: [workspace-and-train](workspace-and-train.md).
