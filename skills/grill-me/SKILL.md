---
name: grill-me
description: 'Stress-test a plan or idea through dependency-ordered decision questions in the owning worker session. Use for grill me, interview me, or unresolved design choices. Research facts first; shared understanding does not authorize implementation or release.'
argument-hint: '[plan, idea or decision]'
---

# Grill me

Read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md` and `${CLAUDE_SKILL_DIR}/../workflow-contracts/decisions.md` first. Use the existing task and owner.

## Inputs
Use args, then the explicitly bound current task/plan, then the conversation. Say which supplied the goal; never choose an unrelated newest draft.

Reconcile the current request and settled decisions. Resolve available facts yourself first, map material choices to prerequisite IDs, and ask only ready, consequential questions, each with a recommended answer, in rounds of `Question round size` per contracts.md § Defaults (proposed until the user sets it). Wait for answers to dependent choices while continuing independent authorized work. Preserve answer provenance and supersession in the existing task record.

Keep technical decisions in the owning worker; route broad priority and scope choices to the parent. Provide a verified session route when the user wants to answer there; never invent one or create another owner. Respect a preference to answer on the current surface.

Finish an explicit interview with a concise understanding check, open/deferred decisions and the acceptance criteria; for a big implementation (contracts.md § Chain) also the test seams to confirm, so blueprint writes the spec without re-interviewing. Understanding confirmation is not execution approval. Continue only actions already authorized for their exact scope; do not automatically commit, publish, install, deploy, send, clean up or start another workflow.

## Report (≤6 lines)
Report the settled scope, the next ready question IDs or confirmed understanding, and the current owner/next action. Do not repeat questions already answered unless a named changed assumption invalidates them.
