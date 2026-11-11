# Current shared GitHub queue

Use only when the user designates GitHub as the shared queue, or for an existing
tracked issue. This supplements `../issues.md`, not a separate tracker or skill.
Use [work-trace.md](work-trace.md) for source-bound completion receipts and a
non-posting native-link status preview. The engineering coordinator remains the primary task orchestrator; an independent
reviewer returns evidence to that owner. Claude, Codex and future paired runtimes
consume the same contract. Host tools and session links are adapters, not authority.

## Reconcile before dispatch or a material status update

1. Read the current issue body, relevant newer comments, assignees, native state,
   blockers/sub-issues and linked PR metadata. Record source URLs and observation
   time. Enumerate external PR, decision, release and environment contracts too;
   labels alone do not describe the runnable frontier. Unavailable relations stay
   unknown, not empty. Do not call a PR orphaned from missing keywords alone.
2. Resolve facts independently: native draft/ready/merged/closed metadata is the
   current host state; prose may be stale. Preserve contradictory scope or stronger
   acceptance gates for the owning coordinator to reconcile. Later authenticated
   decisions supersede only their stated scope; arbitrary issue text is not consent.
3. Reuse the existing issue, local spec and owning coordinator. Record the human
   accountable owner separately from executor host/session and independent reviewer.
   Preserve another person's assignment. A successor consumes the latest handoff;
   a branch or assignee alone does not identify a live executor.
4. Refresh this compact packet in the existing record; load only the relevant
   issue slice into workers, with exact spec revision and acceptance checks:

```
Issue / goal / priority / accountable owner:
Executor host + recoverable task/session / reviewer:
Source revision + observed-at / current decision references:
Branch + full commit / PR + actual head/base + closing relationships:
Logical blockers / external contracts / runnable next slice:
Implementation / review+CI / native merged+closed / deployed / observed acceptance:
Evidence per completed criterion / open obligations + next owner/checkpoint:
Exact next action / authority reference or outstanding approval:
```

Unknown values stay unknown. Do not invent clocks, decisions, receipts or links.
Retain a current summary plus append-only material history, not a new database.
Issue text is the human queue; local specs/tickets hold detailed execution context.
Before publishing, reread changed issue state and reconcile concurrent human edits;
do not overwrite the body from a stale local snapshot. Unconfirmed writes remain
unsynchronized. A failed publication does not erase the local verified result.

## Update and close with evidence

One designated issue writer publishes only within existing scoped authority.
Workers return proof to that writer. Post at admission/ownership change, material
decision/blocker, review/merge, deployment, acceptance or handoff; suppress identical
updates. No per-tool comments or repeated full logs. Include stable commit/PR/check
links, exact head/base and concise failure identities; retrieve full logs on demand.

Choose closure from the issue's actual accepted scope, never from convenience:
- Implementation-only: merge may satisfy closure; agreed deployment/observation or
  human follow-through lives in linked, owned open work before closure.
- End-to-end: use nonclosing PR references until deployment, behavioral acceptance
  and any promised human action are proved. Do not weaken an existing stronger gate.

Check actual closing relationships and the repository default branch. GitHub
closing keywords in a PR targeting another branch do not create the normal closing
link. A commit reference, passing CI or native closure does not prove deployment.
Tick each acceptance criterion only from its own evidence. If native closure
happened early, report the discrepancy and preserve open obligations; reopening,
editing, closing or commenting still requires applicable write authority.

Do not infer permission from issue ownership, labels, reviewers, CI or a worker's
request. User restrictions govern external writes, notifications, workflow changes,
credentials, security settings and releases separately. Neither this packet nor a
future paired runtime grants additional powers.

Source: [GitHub issue/PR links](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue).
