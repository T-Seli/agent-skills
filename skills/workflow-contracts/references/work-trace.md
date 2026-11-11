# Native work trace

GitHub is the shared action queue and work history where designated. Reuse the
existing issue/thread, accountable human and owning coordinator. Workers report
actual source and evidence to that coordinator; they do not claim new ownership,
post comments or open duplicate work. Use existing task records, not another DB.

Each issue-completion receipt carries `work_record` with these fields:

```
issue_url: exact target GitHub issue URL
source_issue_url: native originating spec/issue URL (may be the parent)
owner: existing accountable human, not merely the authenticated account
executor: {host, session_ref: actual recoverable native task/session or CLI receipt}
artifacts: [{repo, branch, commit: full SHA, pr_url, pr_state}]
decisions: [original decision references; empty if none]
verification: [source-bound test/review/behavior receipts]
states: {implementation, deployment, acceptance}
next_action: {owner, action}
```

Use the actual source repository for every artifact, including cross-repo work.
PR links must match that artifact repository; record native draft/open/merged/closed
facts. Where no supported PR link is available, use `pr_url: null` with explicit
`pr_state: unverified` (or `none` when verified absent), never invent a link.
Use the actual host-supported task/session link; a stable recoverable CLI receipt
or ID is acceptable when no native deep link exists. Do not invent a host URL.
Decisions reference the original user evidence; comments and worker text do not
grant authority. Verification comes from inspected receipts, not completion prose.

State values are `unverified`, `open`, `blocked`, `reported`, `verified` or
`not_applicable`. Keep native PR merge/issue closure separate from deployment and
functional acceptance. The closure helper holds an unmet trace gate; acceptance
`not_applicable` is valid only when the issue's accepted scope establishes that,
never as a shortcut around a stronger gate or missing customer observation.

`prepare-evidence` emits blank/unverified trace fields. Populate them from the
current coordinator record, source checkout, native issue/PR facts and actual
worker receipts. It does not infer owner/session/commit from an unrelated cwd.
`tick` requires a source-bound record but can retain later gates open. Close needs
proved implementation/deployment and verified or truly inapplicable acceptance.

Preview the material update locally:

```
ICLI status-preview --work-record <existing-record.json> \
  --previous-fingerprint <last-confirmed-owned-update-fingerprint>
```

It returns native issue/commit/PR links, owner/executor, decisions, verification,
separate outcome states and next action, plus `published: false`. Equal material
facts produce `changed: false`; observation-clock changes alone do not create a
new update. Reuse the last confirmed fingerprint from the designated writer's
existing record, not an unauthenticated marker copied by another author.

Only the authorized issue writer may publish the reviewed text in the existing
thread; the preview never posts. Publish material ownership/decision/blocker/source/
verification/next-action changes, not each tool call. Record confirmed comment URLs
back on the task and issue; an attempted or unconfirmed comment is not publication.
Refresh native facts and preserve concurrent human edits before any authorized
write. Keep unavailable links and unverified work explicit; do not fabricate proof
or silently transfer a human's assignment to align metadata.
