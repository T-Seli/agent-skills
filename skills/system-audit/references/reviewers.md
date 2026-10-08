# Independent reviewer packets

Use four reviewers at most. Each receives the same declared window, scope, canonical task list, primary evidence and coverage limits, plus only its assigned angle. Prior findings are withheld until synthesis to avoid anchoring. All work is read-only.

## A — intake and contracts

Check intake/triage, canonical ownership, active deliverable revisions, superseded obligations, worker readback and stale-result handling. Look for duplicate work or task drift. Do not judge execution quality outside the bound contract.

## B — execution and context

Check worker execution receipts, questions returned to the orchestrator, evidence cursors, pagination and supported cross-session retrieval. Inspect receipt-backed transport/offline failures, executor disconnects, stale session placement/IDs, invalid arguments and progress hidden by short reads. Distinguish missing evidence, unsupported surfaces and disconnected compute. A generic error without class evidence is a coverage gap, not a verified incident. Do not inspect protected session storage or infer a cause from absence.

## C — decisions and human friction

Check whether broad priorities remained with the human, whether questions were concrete and deduplicated, and whether direct user-to-worker instructions were honored within verified scope. When authenticated approval becomes sufficient, require the blocker to move from approval provenance to the receipt-backed current capability; reject another approval request or a false claim that forwarding succeeded. Compare ready human unlocks with the actual daily task-list receipt, deadlines, risks and dependencies. Check for avoidable idle chains or missed launch opportunities, but never infer value from task count or utilization. Measure repeated context requests, duplicate investigation, false blockers and time blocked on a specific decision only when receipts support them. Do not score people or activity volume.

## D — capabilities and release boundaries

Check platform/tool limits, approval relay, direct-session handoffs, failed/rejected deployments, release pause races, split execution/acceptance/display state, final-diff and owner-lock release gates, watches and owner-bound history proposals. Classify each verified guard or failure, its exact supported remedy and any human-only step. Confirm recommendations never bypass or disable a denied action. Separate authorization from capability, decision from exposure, deployment from acceptance and known limits from hypotheses.

## Finding schema

Return a list with: stable `finding_id` and `finding_key`, `angle`, structured `assertion`, `claim_level` (`observed`, `hypothesis`, `known-platform-limit`, `coverage-gap`), `cause_basis`, `confidence`, `scope_ref`, `evidence_window`, `evidence_refs`, `impact`, `counterevidence`, `minimal_remedy`, `regression_risk`, `acceptance_test` and state. Evidence references must be precise and sanitized. A reviewer may return no finding.

## Synthesis rules

- Missing evidence cannot support an observed root cause.
- Conflicting structured assertions sharing a stable finding ID remain `disputed` until primary evidence resolves them; prose differences alone do not create conflict.
- An unchanged mechanism, scope and acceptance test reuses the prior finding ID while recording the new evidence window and test state.
- A direct human instruction is checked for authentic source and current scope; it is not downgraded because it bypassed an orchestration preference.
- Cross-session restrictions are coverage limits unless a supported read receipt proves retrieval.
- Remedies remain proposals until separately authorized.
- Identical occurrence IDs deduplicate; distinct receipt-backed repeats remain one failure group with an explicit occurrence count.
- A prevention pass needs a receipt. Any later same-key occurrence is reported as recurrence after pass rather than silently treated as fixed.
- Human unlock recommendations require readiness/safety receipts, preserve canonical owners, contain no automatic decisions, and deduplicate already-authorized parallel work.
