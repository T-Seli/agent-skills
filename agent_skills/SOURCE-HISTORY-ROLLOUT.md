# Source, history, and closeout contract (review draft)

This branch adds offline checks. It does not materialize source on a cloud worker, install skills, change a saved cloud environment, or delete a branch/worktree.

## Source bootstrap and readiness

The caller must supply an existing, authorized checkout. Transfer of private source and choice of a durable cross-machine source require a separate decision. On the Mac, the current checkout is the source; on a fresh cloud worker, provision the same reviewed snapshot first by an approved mechanism. Do not treat an empty `.agents` or `.codex` mount as an installation. An empty, unborn project directory is simply not a source checkout.

After the source exists, run `python3 -m agent_skills.source_readiness <source-root> --expected-commit <40-char-commit>`. Save its JSON receipt with the task, then run `python3 -m agent_skills.source_readiness <source-root> --receipt <receipt.json>` at handoff or restart. A mismatch, dirty checkout, missing required file, or absent checkout fails closed. The receipt binds the full Git commit/tree and hashes the entry files. `--home <worker-home>` additionally checks installed Claude/Codex symlink targets. It does not prove that a running host loaded the skill; a native load check is still required after activation. Before rollout, choose and authorize the source transport, check it in a fresh cloud worker, review `./install.sh --dry-run`, install only in an idle window, and verify native loading. Keep the prior source snapshot for rollback.

## Task history

`agent_skills.history.append(root, entry)` writes one JSONL file per task under a caller-chosen **private** state directory (0700), with private files (0600), a lock, fsync, and duplicate event-id check. The caller chooses storage; the framework does not provision or sync a service. Keep this outside the source repo and project reference docs. One event has `event_id`, `task_id`, `revision`, UTC `at`, `kind`, short `summary`, and evidence `refs`. The API limits length and shape but cannot detect every secret; the caller must redact summaries and refs and must not store full transcripts. The existing `skills/agent-coordination/scripts/tasks.py` record remains the live task state; `skills/workflow-contracts/contracts.md` § Task log remains the local implementation-stage log. History records a compact timeline and superseded decisions. This follows the separation of chronological implementation logs and current reference docs, and the established task-folder/handoff pattern, without copying project-specific conventions into the generic core.

## Handoff, completion, cleanup

`handoff_gate` requires the pinned packet/checkpoint to match the current revision and fresh sources, with uncertain effects reconciled. `completion_gate` requires evidence for every acceptance criterion, then separate owner verification and human acceptance. It never infers either from a worker claim. `cleanup_gate` is read-only. It requires accepted completion, no pending effects, a registered clean worktree on the expected branch, and a branch commit merged into the checked-out local base. It returns an eligibility result, never removes anything. Recheck remote state and approvals before any actual deletion in a future, separately authorized rollout.

## Remaining real-world gates

- Select and authorize a private, durable source distribution path. The local receipt does not solve Mac-to-cloud persistence.
- Materialize source in a fresh cloud worker; verify commit, package links and native skill load there. No live cloud activation has been run.
- Select where private task-history files live and how they are backed up or synced. This change stores no live task history.
- Review and approve installation, merge/push, saved environment edits, and any cleanup action separately.
