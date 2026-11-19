# Engineering coordination with the shared skills

Read [roles](roles.md) for role/reread alignment; startup briefs and the session lifecycle: the on-demand [engineering coordinator guide](../../../ENGINEERING-COORDINATOR.md).

An engineering coordinator is a worker at a higher scope: its artifact may be an
integrated plan, verified readiness packet or handoff; narrower workers own the
implementation slices. Both levels use the same shared skills and authority
rules, with no second catalog or parallel workflow.

## Keep the next action focused

Pick the next procedure from the skill index and load its body and references
on demand, never every skill. Reuse a body loaded from the same
release in this context; reread after a material source change or context loss.
A fresh worker still needs its relevant instructions.
Use `prime-context` for entry, `agent-coordination` for owned execution and result
consumption, `grill-me` for material decisions, and `handoff` for succession.
The owning worker uses `blueprint`, `action-items`, `implement`, `tdd` and
`test-review` at its artifact's scope; the same procedures serve both levels. Use
`approval-handoff` only for a concrete blocker; `task-history` only with its
configured record owner.

Keep a compact current summary in the existing task record (goal, owner, revision, workspace/head, artifact, latest receipt, gate, next action, evidence cursor) and consume each finished result once per [state](state.md#coordinator-follow-through).
After a compaction, `issues-cli resume` comes first: state no fact about a session, PR, approval or owner before reading it.
For a user-designated GitHub queue, reconcile the current issue and linked PRs
per `../../workflow-contracts/references/github-queue.md`. Keep the primary
coordinator and independent reviewer roles; any host or paired runtime consumes
the same packet and authority, with no new dispatcher.
Latest authenticated user instructions supersede only their actual scope;
old manual-only defaults do not prove a present execution limit.

`TASKS.md` is a view of the canonical project queue, never a second tracker; its verified record owner persists rows under actual authority and unknown coverage stays unknown. Board, STOP and release-card formats: the guide.

## Worker capacity
Up to 10 working sessions at once. Each may take a larger scope and nest workers; those, scouts and reviewers count toward `max_live`, disk and test slots. Before starting or nesting, check the disk floor and a free test slot (workspace-and-train.md). A refused start waits; the coordinator never takes the work over.

## Apply specs and verification at the right level

Bind each worker to the current accepted specification, ticket, agreed seams and
observable done-when checks. Small deterministic fixes keep the one-line-plan
path, with no large spec just to coordinate them.
In implement's spec mode, stay thin: consume receipts and use its merger/reviewer
owners; a generic worker-limit fallback never authorizes taking their work.
Distinguish logical prerequisites from shared files, compute, ownership, priority
and release gates. Keep the exact hold reason and independent work visible.

Check adherence by supported invocation/source-read and artifact receipts: a
skill name in a prompt or a plan file on disk is no proof it was followed, and
missing invocation evidence is unknown, not noncompliance.
Separate test-first assertion failure, regression proof on a base, mutation
sensitivity and import/collection failure; never relabel one or invent a missing
worker receipt. Inspect the exact accepted artifact and current head;
component checks do not prove a different consumer, deployment or live outcome.

## Reduce waste without weakening checks

Give each worker the relevant task slice and shared evidence pointers, not the
whole conversation. Local tool profiles serve only genuinely local
work; connector-dependent work stays on a capable route. Tools and skills are
different controls; host profiles are no security boundary.
Honor the user's model/effort policy, verified from runtime output. Reuse
unchanged source/environment-bound test and review evidence rather than rerun a
full suite for a status report. Required composed and release checks still run
when their artifact or prerequisites change.

Measure child startup, parent overhead and whole-task usage separately
(input/cache/output and actual model where available); report retries, held
launches and missing cost metadata apart. CLI dollar amounts and cached-input
totals do not prove subscription quota use; never attribute a weekly limit to
one mechanism without account-wide evidence.
Workspace hygiene and the draft-PR release train: [workspace-and-train](workspace-and-train.md).
