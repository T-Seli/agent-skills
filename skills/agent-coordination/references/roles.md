# Role map and reread contract

Roles describe accountability, not host names, tool profiles or new authority.
Bind the actual role, task/deliverable/revision/digest, exact source, owner,
accepted criteria and supported read/send/wake/persistence capabilities first.
One outcome owner remains accountable; overlapping tools do not transfer ownership.

| Role | Canonical Markdown guidance | Owns and returns |
| --- | --- | --- |
| Primary coordinator | [coordinator mode](coordinator-mode.md), [session guide](../../../ENGINEERING-COORDINATOR.md) | Intake, priorities, delegation, reconciliation, user decisions; source-bound dispositions and next owner/checkpoint. Investigation is read-only; verified execution owners perform mutations/tests/releases. Spec mode remains thin. |
| Execution worker | [worker execution](worker-execution.md), applicable governing skill | One scoped artifact; bound acknowledgment, checkpoints, blockers, exact result/tests and next action. No scope/permission expansion or second writer. |
| Independent reviewer/researcher | [independent review](independent-reviewer.md), test-review or system-audit or blueprint as applicable | Independent evidence, alternatives, findings and limits; not implementation, approval or ownership takeover. |
| Cross-task executive / starter | agent-coordination SKILL.md, Roles for big implementations | Priorities/conflicts or verified session admission; neither silently becomes the task's executor or grants authority. |
| Record owner | [coordinator mode](coordinator-mode.md), task-history when configured | Authorized sanitized persistence and separate render/publication/readback receipts; not execution ownership or a parallel queue. |
| Release/monitor owner | deploy/monitor and project instructions, [state](state.md) | Exact target/candidate, actual readiness/consent, rollback and bounded observation verdict; no inferred schedule or release permission. |

At startup, resume or compaction, read this map and the current role's guidance.
Reread affected guidance on material scope/revision/role change or a relevant miss;
recover current authority, source identity, held obligations and evidence cursor
before consequential work. Reuse unchanged procedure bodies already in context;
load only applicable skills and required references, not every role's full history.
If unavailable, report the missing source and hold dependent work; never silently
substitute stale installed text or claim a role/read receipt from a prompt name.

Input: current task/source/authority, accepted artifact and criteria, original
user decisions, current owner/hold and evidence pointers. Output: exact binding,
used/skipped procedures with reasons, reported/performed/verified distinctions,
remaining gates, next owner/action/checkpoint and matching readback. A role change
requires explicit scoped assignment and acknowledgment; it never grants new access.
The guide's STOP/details carry these facts without a new registry or dispatcher.

Adapter names and catalog roles are capability hints, not one-to-one role identities.
A connector-dependent reviewer needs an authorized capable host; do not force it
into a tool-limited local profile. Guidance/tests do not prove native adoption.
