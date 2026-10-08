# Independent reviewer packets

Use four reviewers at most. Each receives the same declared window, scope, canonical task list, primary evidence and coverage limits, plus only its assigned angle. Prior findings are withheld until synthesis to avoid anchoring. All work is read-only.

## A — intake and contracts

Check intake/triage, canonical ownership, active deliverable revisions, superseded obligations, worker readback and stale-result handling. Look for duplicate work or task drift. Do not judge execution quality outside the bound contract.

## B — execution and context

Check worker execution receipts, questions returned to the orchestrator, evidence cursors, pagination and supported cross-session retrieval. Distinguish missing evidence, unsupported surfaces and disconnected compute. Do not inspect protected session storage or infer a cause from absence.

## C — decisions and human friction

Check whether broad priorities remained with the human, whether questions were concrete and deduplicated, and whether direct user-to-worker instructions were honored within verified scope. Measure repeated context requests, duplicate investigation, false blockers and time blocked on a specific decision only when receipts support them. Do not score people or activity volume.

## D — capabilities and release boundaries

Check platform/tool limits, approval relay, direct-session handoffs, split execution/acceptance/display state, final-diff and owner-lock release gates, watches and owner-bound history proposals. Separate authorization from capability, decision from exposure, deployment from acceptance and known limits from hypotheses.

## Finding schema

Return a list with: stable `finding_id` and `finding_key`, `angle`, structured `assertion`, `claim_level` (`observed`, `hypothesis`, `known-platform-limit`, `coverage-gap`), `cause_basis`, `confidence`, `scope_ref`, `evidence_window`, `evidence_refs`, `impact`, `counterevidence`, `minimal_remedy`, `regression_risk`, `acceptance_test` and state. Evidence references must be precise and sanitized. A reviewer may return no finding.

## Synthesis rules

- Missing evidence cannot support an observed root cause.
- Conflicting structured assertions sharing a stable finding ID remain `disputed` until primary evidence resolves them; prose differences alone do not create conflict.
- An unchanged mechanism, scope and acceptance test reuses the prior finding ID while recording the new evidence window and test state.
- A direct human instruction is checked for authentic source and current scope; it is not downgraded because it bypassed an orchestration preference.
- Cross-session restrictions are coverage limits unless a supported read receipt proves retrieval.
- Remedies remain proposals until separately authorized.
