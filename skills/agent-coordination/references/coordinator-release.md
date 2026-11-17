# Coordinator release and traceability

On demand for a coordinator preparing a release; part of the [coordinator guide](../../../ENGINEERING-COORDINATOR.md).

Use [review/observation evidence](skills/workflow-contracts/references/review-evidence.md) to distinguish actual source intervals and freshness from scheduler/task activity, retain finding ownership through acceptance, and verify optimization/consumer-use claims.

**Release bundling** follows behavior.md § Release train. Never ask a worker to mark a member PR ready; tell release owners to bundle, and request no extra runs for member PRs (draft PRs skip only workflows that exclude drafts; verify per repository, and never cancel a mandatory or security check). The landed merge commit is reviewed with `/test-review` before deploy (tree equal to the tested head), so the reviewed and deployed commit are one, deployed with one deploy-record id in a gap between send rounds.

The board shows the release PR with its members inside it. Check CI runs per release from `gh run list` (report measured numbers, not a promised bound) and that the landed tree equals the tested head tree.

Keep small releases proportionate to risk. Reuse evidence only when bound to the exact artifact/base, relevant paths, dependencies, configuration, toolchain, environment, acceptance criteria, and command. Record why each check is reused or rerun. Changes to those inputs invalidate affected evidence; use focused, impact-driven checks for new or unresolved risk rather than repeating every suite just to refresh status. Retain required canonical aggregate checks and independent review, safety, approval, target-readiness, release, and rollback gates.

Satisfy a required check or request a scoped workflow change; never silently skip it. Reused, skipped, blocked, and not-run checks are never newly passed. State remaining checks and their owner so already authorized release steps can proceed promptly. This guidance grants no automatic release or deployment authority.

Name one release owner per actual target; other owners hand it reviewed source. Prefer one release card per target/candidate: exact source and merged SHA/tree, included repository-qualified issues/PRs and their real acceptance gates, tests and independent review on that artifact, readiness/approval states, ordered actions, logs, rollback and required monitors/owners/deadlines (or explicit not-applicable/pending). Prefer a single reviewed command or native permission request only when a safe supported route exists.

Keep required split handoffs, action-time approval, user-only steps and safety boundaries; do not collapse them into a generic question or an unreviewed wrapper. A wrapper must be separately authorized, stop on failure and preserve uncertainty. Freeze the presented card's candidate/scope; later changes require affected review/readiness/consent reconciliation, not automatic new authority. Off-main operation requires its actual authorized reconcile-to-main disposition, not a forced main mutation. Source/box-state claims cite actual receipts.

Follow issues.md: use `Refs <owner/repo>#<n>` until an issue's stronger gate is met; an implementation-scoped issue may close at its stated implementation/merge gate. Merge alone never discharges actual deployment, monitoring, acceptance or human obligations. No automatic release/deployment authority is added.

Release card template (retain actual pending gates; details may link to readable evidence):

```text
Release/target/owner: <key · actual target · verified executor>
Candidate/source: <repository · base · full SHA/tree · source revision>
Includes/gates: <repository-qualified items · each actual acceptance gate>
Evidence: <commands/inputs/results · independent review of this artifact>
Readiness/approval: <verified, pending or blocked · exact consent/action-time route>
Plan/command: <ordered supported steps · safe command or required split handoffs>
Rollback/observability: <restore artifact · logs · required monitor owner/deadline or N/A/pending>
Disposition: <remaining obligations · next owner/action/checkpoint · no automatic authority>
```

When GitHub is the designated shared queue, use the existing issue/thread and owners. Carry repository-qualified issue, commit and PR references, actual branch/head/base, accepted spec/decision revision, executor session, verification and next action. A label-only queue misses external contracts; bare numbers can silently reference the wrong repository. Use [issue rules](skills/workflow-contracts/issues.md), [work trace](skills/workflow-contracts/references/work-trace.md) and [queue reconciliation](skills/workflow-contracts/references/github-queue.md).

One authorized writer publishes material updates after reconciling current remote facts; workers return evidence to that owner. Suppress identical updates and reconcile uncertain writes before retrying. Linking is not permission to comment, close, push or merge. Independent review checks the exact accepted artifact and source. Keep test-first red, base regression, mutation sensitivity and import failures distinct; a missing receipt remains missing. Use host-native links where supported and recoverable IDs otherwise, never invented URLs.
