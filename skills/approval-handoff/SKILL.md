---
name: approval-handoff
description: 'Resolve a worker action blocked on permission or execution surface: relay existing scoped authorization first, or point the user to one verified worker session with exact copy-ready approval terms. Not for ordinary blockers or access workarounds.'
argument-hint: '<blocked task or worker receipt>'
---

# Approval handoff

First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`, especially § Consent, then the current task's `agent-coordination` record. This skill structures a blocker; it does not grant approval, send a message, resume a user-owned session, create access or weaken a guard.

## Establish the blocker

Read the actual platform/task receipt and classify exactly one:

- `missing-permission`: the action is otherwise supported but lacks scoped authorization;
- `denied-authority`: the platform or user denied the action;
- `wrong-execution-surface`: approval must be entered in the owning worker session;
- `missing-evidence`: readiness, identity, revision or scope proof is incomplete;
- `unsupported-tool`: the required operation is not exposed;
- `disconnected-compute`: the selected worker environment is offline or unreachable.

Do not infer `missing-permission` from difficulty, timeout, cancellation, tool absence or disconnection. A denial stays denied. Missing evidence is gathered; unsupported tools and disconnected compute are capability states, not reasons to ask for approval.

## Relay before direct confirmation

Authenticate any existing original user instruction and compare its task, revision, action, target, scope and constraints with the pending action. If it covers the action and the host supports a relay, pass it once through the prescribed approval-evidence route and reconcile the result. A relay is evidence, not a new user turn or platform approval.

Offer a direct-session handoff only after a verified platform receipt says direct confirmation is required, or the verified action is on the wrong execution surface. Never bypass a denial, repeat an unchanged relay, create credentials, broaden persistent access or alter permission controls.

## Build the handoff

Read the current native task/session and verify every field:

- desktop app: `Claude Code` or `Codex`;
- searchable task title, exact task ID, exact session/thread ID and workspace;
- exact action, target, scope, current revision, prerequisites and material constraints;
- one-line copy-ready approval or decision wording;
- source receipt proving the direct-session requirement.

Never guess a title, ID, workspace, link or wording. Include a session link only when the host verified it and the current surface can open that exact app/session. On mobile or messaging surfaces, omit incompatible links and say which desktop app to open, what title to search, and which ID/workspace to confirm.

Suppress an identical handoff already shown for the same task/revision/action/scope. A changed revision, target or scope is a new decision. Keep independent decisions separate even when presenting a ranked summary.

## Pause and resume

A requested pause is not effective until the execution owner confirms it with a receipt. After approval, the orchestrator still checks platform admission and requires a current worker readback before claiming resumed execution. Approval never establishes deployment readiness, completion or acceptance.

## Report (≤8 lines)

Blocker class and evidence · relay outcome · exact app/title/task/session/workspace · compatible link or desktop navigation · exact action/target/scope/revision · copy-ready wording · pause state · next owner. If direct confirmation is not actually required, state the real missing evidence or capability instead of sending the user to a worker session.

Central history: send only a sanitized material blocker/handoff milestone to the designated record owner when authorized. Never copy the user message, worker transcript or private session data into shared history.
