# Issue completion evidence

`issues-cli tick` and `close` require `--evidence-file <JSON>`. Existing calls
without it refuse. First run `ICLI prepare-evidence --repo <repo> --number <n>`
(or `--draft DRAFT` for a task) into a task-local JSON file. The template has blank
authority and unverified proof; populate only independently inspected receipts.
Refresh after ticking because the issue body hash changes. Never activate before
callers and receipts are migrated. The supplied receipt has this structure (example values are synthetic):

```json
{
  "version": 1,
  "repo": "owner/repo",
  "authority_ref": "original-user-approval-reference",
  "issues": {
    "123": {
      "body_sha256": "SHA256-of-exact-current-UTF8-body",
      "criteria": [
        {"number": 1, "text": "Exact criterion text", "status": "verified",
         "evidence_ref": "stable-test-or-acceptance-receipt"}
      ],
      "closure": {"status": "verified", "evidence_ref": "closure-gate-receipt"}
    }
  },
  "deployment": {
    "sha": "full-40-character-deployed-commit",
    "status": "verified", "target": "verified-target",
    "receipt_ref": "deployment-receipt", "observed_at": "source-UTC-time"
  }
}
```

Each issue entry also requires `work_record` per [work-trace.md](work-trace.md):
actual owner/session, source issue, branch/full commit/PR, decisions, verification,
separate outcome states and next action. The preparer leaves it unverified.

Criterion ordinals count every checkbox within `## Acceptance criteria`, including
already checked entries, in order. Tick accepts any proved subset and changes only
those boxes. Changed body hash, text, duplicate/unknown number, missing authority
reference or unverified criterion refuses. It rereads before writing to detect
concurrent edits. This narrows a race; GitHub CLI body editing has no atomic
compare-and-swap. Preserve concurrent human work and reconcile any uncertain write.

Close requires the full deployed SHA, target/time/receipt and matching exact-body
proof for every criterion of every open task issue; all boxes must already be
checked and each closure gate must have verified evidence. It preflights the entire
batch and rereads before effects; an ineligible issue holds the batch. Existing
closed issues are not reopened or relabeled. Issues with no structured acceptance
section need an authorized criterion reconciliation first, not fabricated proof.

Receipts bind supplied claims and reject missing/stale records; the helper cannot
independently authenticate their human authority or deployment target. The owning
session must inspect original approval and actual receipts. Remote issue writes
are not an atomic transaction; after a later network failure or concurrent edit,
report earlier confirmed closures and reconcile remaining state before retrying.
Do not synthesize completion evidence merely to satisfy this schema.
