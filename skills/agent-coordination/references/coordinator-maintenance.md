# Coordinator maintenance and review

On demand; part of the [coordinator guide](../../../ENGINEERING-COORDINATOR.md).

## Primary-role validation cases
This decision table supports guide/contract validation, not live runtime enforcement. Decisions describe the primary’s permitted route, not new authority for an execution owner.

| Case | Decision | Required disposition |
| --- | --- | --- |
| Read-only investigation or evidence inspection | READ | Within authorized evidence scope and stronger phase limits. |
| Edit files or mutate Git or GitHub | DELEGATE | Verified execution owner with scoped authority. |
| Run tests, release or operate production | DELEGATE | Verified execution owner and applicable approval/resource gates. |
| Spec-mode record/worktree/tick/publish/fast-forward/cleanup mutation | DELEGATE | Scoped execution owner; preserve thin primary orchestration. |
| Completed result; unresolved obligations; next owner/action missing | HOLD | Consume/disposition result and assign the authorized next step or sourced wait; do not abandon it. |
| Completed result; authorized follow-up assigned with owner/checkpoint | RECONCILE | Obtain source-bound acknowledgment and later outcome/readback. |
| Whole outcome verified complete; all obligations dispositioned | CLOSE | Explicit evidence-bound terminal closure; do not invent endless next work. |
| Deliberate approval/access/dependency wait with owner/checkpoint | RETAIN | Keep the legitimate hold; no unsolicited resume or replacement worker. |
| Unknown inventory or overdue/idle lane without current result | INSPECT | Read supported live inventory/results; preserve uncertainty, not an assumed failure or dispatch grant. |

## Independent reviewer checkpoint

Apply [documentation currency](skills/workflow-contracts/behavior.md#documentation-currency): reconcile cross-channel decision evidence and verified changes into canonical links/records through the actual document owner. Review identifies stale/conflicting guidance; workers update scoped docs and return doc-impact evidence or a reasoned not-applicable disposition. Summaries are not approval, and consolidation preserves useful rationale, history and unresolved decisions.

At each authorized reviewer checkpoint, inspect the primary’s actual live inventory and durable checkpoints through supported read-only routes, then reconcile material results against the existing canonical shared queue and resources. State whether coverage actually includes user-owned primary coordinator sessions: a watcher limited to assistant-created workers does not establish that coverage. Mark uncovered or unobserved lanes explicitly.

Use the queue schema above and [state](skills/agent-coordination/references/state.md), [decisions](skills/workflow-contracts/decisions.md) and [review evidence](skills/workflow-contracts/references/review-evidence.md); reuse current specs, artifacts, receipts and shared-resource owners instead of creating a parallel tracker or service. Preserve stable IDs, source/revision identity, known owners, next action/checkpoint, dependency and approval state, observation time/coverage and intentional waits.

Surface stale tasks, unconsumed results and unresolved or aging decisions, approvals and grill-me questions with their actual age/impact or explicit unknowns; silence alone is not evidence of inactivity.

When private findings conflict with a positive review on the same exact revision, retain the findings and both source receipts in the existing authorized record, preserve sharing restrictions, and reconcile the discrepancy through the responsible owner. A positive status must not erase unresolved evidence or close its dependent acceptance gate.

The reviewer challenges evidence and reports through a supported authorized route; it does not silently take over, reassign work, mutate external systems or start a watcher. A finding does not grant permission. The primary consumes the finding, acknowledges and dispositions it, and verifies the matching resolution/readback in the existing queue; sending or acknowledging a message alone is not closure. Respect current communication authority, reader ownership and bounded checkpoints.

Missing read/wake/persistence capability remains a reported gap with a named next reader/checkpoint, never an always-on delivery guarantee or a reason to restart a deliberate wait.

## Maintain the guide with the skills revision

Keep canonical rules in the linked contracts, not copied here. When changing a referenced skill, schema, adapter or workflow, assess the affected guide sections in the same reviewed change: update them, or record why they remain accurate in its review evidence. Reconcile the guide against the actual skills revision in the same reviewed change; never relabel old tests, runtime loads or approval receipts as checks of the new revision. Record the guide's exact commit/tree in the task's review packet outside this reusable document.

Validate relative links and meaningful anchors, framework budgets, applicable repository checks and semantic scenarios: startup, underspecified work, missing skills, missed updates, uncertain launch, approval waits, competing writers, handoff, unsafe cleanup and changed-skill maintenance. Independent review must distinguish proposed guidance from supported runtime behavior. Refresh affected source/package/policy evidence; installation, saved-environment publication and loaded-session adoption are separate authorized operations. No automatic updater is installed.

At startup and after compaction, ask: is this the intended task and owner; what source and skills are actually loaded; what is verified versus reported; which independent work is ready; which decisions/approvals remain; who reads the next result; and what is the exact stopping condition? Retrieve details only where they change the next action. The guide describes intended practice, not proof that any historical session complied.
