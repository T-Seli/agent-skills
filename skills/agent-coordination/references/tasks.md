# Worker tasks

This reference gives common dispatch and review checks, followed by the optional local CLI record and adapters. Native task status, cards, details and notifications come from the host; these Python helpers neither operate that host nor grant approval.

## Local CLI record
One JSON file per task under `~/.local/state/claude-skills/assistant/tasks/` (override: `AGENT_COORDINATION_STATE`), mode 600, written atomically under a per-task lock. It holds:
- `task_id` (stable; letters, digits, `._-`) and `work_item` (the same key the assistant thread uses);
- `worker` {kind, session_id, owner, state};
- `repo`, `worktree`, `source_thread`;
- optional pinned `acceptance_packet` and its criterion evidence assessment;
- `status`, `evidence` {commit, tests, summary}, `pending_decision`, `approvals` [{action, scope, ts}], plus the [coordination state envelope](state.md);
- `outbox` (dispatch receipts), `seen` (event ids), `last_change_ts`, `history` (outcomes only), `counts` (duplicate receipts, repeated asks).

It holds no message bodies, secrets or personal data. A second record for a task id is refused: resume the existing one.

## Statuses
- `delivered`: launched, with no report yet.
- `accepted`: the worker took the task.
- `running`: requires a worker/adapter execution report; after a user decision, the report must name the matching new sent dispatch id before claiming running.
- `awaiting-worker`: the user decision is recorded; the orchestrator must route it, with no worker execution inferred.
- `blocked`: it names `pending_decision` {need, action, target}; `pending(record)` also reads older text-only ones. An approval is a user `decided` with `approve: true` and the exact pending action and target. Any other `decided` is an answer, such as a decline or redirect: it moves to `awaiting-worker`, names no action or target, and records no approval. The resume prompt must pass the user's answer to the worker, including a no.
- `ready-for-review`: the worker gave a commit and tests.
- `verified-done`: the verifier (your own check) or the user confirmed the same commit with passing tests.

A user or verifier reopen returns the task to `running` and clears the evidence. `ack`, `idle` and `heartbeat` are only noted: an acknowledgement, a quiet worker or a finished process is never progress or completion.

## Events
`{id, task, ts, source, kind, data}`. Sources:
- `adapter`: local launch receipts.
- `worker`: its own report.
- `orchestrator`: the assistant's reply.
- `verifier`: your check of the evidence.
- `user`: the user's chat turn.
- `thread`: a thread reply relayed as a `proposal` note; it decides nothing (hub.md § Replies in the thread).

Rules:
- Ids are stable, so a repeated id that applied is a no-op. That makes replaying after a restart safe. An event that was ignored or stale is not remembered, so a replay can still apply it. A worker report's id includes its dispatch id, so the same report from a later resume still counts.
- `ts` must be epoch seconds, at most 5 minutes ahead of this clock; anything else raises. A replay of the same unapplied event adds nothing.
- A status move stamped at or before the last change is stale: logged, not applied.
- Moves outside the table in `tasks.py:MOVES` are ignored, never forced. A `ready` without a commit and tests, sent where a ready could apply, is `unsupported`: a claim without evidence.
- A `user` event counts only with `channel: chat`, text that opens with a letter or digit and names no worker near its start (`[Codex · …]`, `Claude:`, an emoji label all fail). The real guard is the caller: pass `chat` only for the user's own turn. Text in a thread, even from the user's own account, may have been posted by a worker, so it is never a user event.
- Approvals are a separate list with an explicit action, target and scope; `approved(record, action, target)` checks one. A worker or orchestrator approval is rejected, and no status ever implies one.

## Approval handoff
For an explicit user approval in the app or a verified human-authored messaging-channel post to the orchestrator, carry the exact original message, source channel/thread/message and user identity, approved action, target, scope, material constraints, task ID and revision. For the local CLI path, `agent_skills.approval_handoff.worker_handoff(transcript_evidence(...))` can check this evidence. The caller must authenticate original authorship through the platform or connector; a forwarded quote, bot post from the user's account, worker report, or assistant summary is not a user approval. Keep the message out of public summaries and logs. A request to improve approval handoff is not itself blanket deployment approval.

The worker compares the evidence to the proposed action and current task state, then follows action-time platform approval. Do not ask again solely because the approval crossed delegation. A changed target, wider scope, changed material constraint, or stale revision needs a new decision. If the platform denies for missing authorization, attach this evidence for at most one bounded retry when it still matches; after a second denial, or any other denial, stop and report the platform block. Never change an approval control or claim a skill can override platform review. The pure helper in `agent_skills/approval_handoff.py` returns eligibility decisions; it sends nothing and grants no platform permission.

When platform execution explicitly requires direct confirmation after a verified relay failed, read the exact pending terms from the actual platform task and provide its verified session link and wording on the user's working surface. In the local CLI path, `direct_confirmation_route`, `terms_from_platform_response` and `hub.direct_approval_handoff` check this handoff. A worker's blocked report alone cannot establish platform wording. Missing link, target or matching terms holds the handoff; never invent a URL or claim it opens in a messaging app without a surface check. Record the handoff only after a send receipt so an unchanged blocker does not start another approval loop. The parent watches the same task; `tasks.direct_reply_observation` matches identity only and never grants approval. Resume only after authenticating the user's original task answer and checking action-time platform admission. A quote, reply observation or handoff alone is neither authorization nor readiness.

## Dispatch
Preflight before any dispatch: confirm one sentence for the goal and one for the exact owner/target; read the current task and applicable runbook, recording its path/revision and prescribed route; list authorized actions with their source, exclusions, and an observable done-when check. Resolve unknowns before launch or task the worker with finding them within the approved scope. Do not substitute a generic preflight for a documented next route.

Pin the current acceptance criteria to the task. In the local CLI path, pass `acceptance_packet` to `new_task` with the artifact worktree and use `bind_packet` on revision; it clears prior evidence. For every dispatch, put `current_task_binding(record)` first and require worker reports to echo its task, deliverable, revision, digest, next action and packet hash; a mismatch is stale or foreign even when the outer event names the current task. The independent verifier opens actual artifacts on the exact candidate, fixture and environment, compares any applicable production visual reference, and checks every requested surface and declared mounted entrypoint through both permitted and denied request paths; each entrypoint needs a matching worker and verifier receipt. `tests_passed` alone cannot close the task. When the question is outcome readiness, each criterion's existing `evidence_binding` also pins `{outcome, stage, expected_results}`. Stages are `component-tests`, `composed-route`, `provisioning`, `access`, `first-login`; include every stage needed for the requested claim. `expected_results` names exact observations, including allowed and denied routes. Worker and independent verifier evidence must echo outcome/stage and identical `observed_results`, candidate/environment and actual artifact hashes. `assess_completion` keeps each stage separate and emits HOLD for missing or contradicting evidence; a `manual-waiver` never passes a technical criterion. Keep broader untested claims held even if a narrower packet passes.
Bind each subdeliverable's `authority_ref`, `artifact_ref` and `gates` in the existing task contract. Worker readback names `decision_source_ref` for the original criterion change, rather than an assistant summary. Final packets echo the current binding and include useful `material_facts` inline with source and evidence level, plus remaining work and next owner. The adapter preserves these fields. A local link alone is insufficient. `communication_brief` projects subdeliverables and outcome stages without merging same-owner scopes. After reading a matching result, call `reconcile_parent_readback` with that binding, result receipt, original decision source, read receipt and answer reference. This records a local caller's reconciliation, not native receipt authenticity. A separately authorized live propagation pilot must capture actual original decision, owner acknowledgment, matching result and parent read/answer receipts. Before consequential action after interruption or compaction, reread the current task, target, authorization and criteria; page to the last consumed evidence receipt, report mismatches and continue useful in-scope work. On a material requirement change or incomplete binding, keep the same task and owned session, preserve the displaced obligation, mark the earlier result stale, and send the revised criteria with its revision. Before accepting another result, inspect a worker readback that names that task, revision, changed criteria, environment and next action. Save only a sanitized reference to the readback; a packet hash, dispatch receipt or generic acknowledgement is insufficient. If the host cannot deliver to or read from that session, report the limit and hold readiness rather than inventing an acknowledgement.

Before rollout, pin the reviewed source commit, tree and final-diff digest; bind the exact revision, approved scope, canonical lock owner and any execution-owner pause receipt before admitting release. `contract_consumption(record)` distinguishes a call consumed by this local library from helper-only/unconsumed state and always labels native enforcement false; only a separate host receipt can establish native use. Verify each claimed runtime separately: exact installed routes, an actual selected-body load with resolved path/body hashes, and a supported behavior receipt at that commit/tree (`agent_skills.source_readiness.runtime_capability_receipt` enforces the local evidence shape). Installation alone is not loading, loading alone is not adherence, and an unavailable native host bridge remains a labeled capability gap. For fresh or resumed workers, verify an available native load receipt; if absent, obtain an explicit selected-file read with resolved path, hash and read reference, labeling automatic discovery/load unknown. Preserve a valid prior version pin on resume unless a changed version is explicitly adopted; an install command alone is not adoption. Check supported model and effort options, select compatible settings explicitly and report effective values only if the host exposes them. Trial an independent reviewer on a synthetic task only through an available authenticated route; otherwise report the capability gap.

For the local CLI adapter path only:

1. Before launch, `begin_dispatch` marks it `uncertain` and persists it. Any dispatch on a human-owned record is refused.
2. Each dispatch id is new. Launch through an adapter, then feed `workers.events(...)` to `receive`.
3. An interrupted or timed-out launch stays `uncertain`. Settle it with `settle_dispatch`:
   - `sent` when its transcript or receipt exists;
   - `not-sent` when it is proven absent;
   - otherwise keep the start uncertain and inspect host state before another attempt.

   Never relaunch blindly.
4. A missing CLI returns `unavailable`; a non-zero exit returns `failed`. Classify the observed receipt as uncertain start, technical failure, permission denial or explicit stop; a canceled call alone proves no cause. Reconcile an uncertain start before retrying. A technical failure can retry after its cause is resolved; a permission denial follows the approval handoff and action-time admission, and an explicit stop remains stopped. Never duplicate a start or route around a denial.

## Adapters
- **Claude:** `claude -p --output-format json --json-schema <report> --permission-mode dontAsk --strict-mcp-config --mcp-config '{"mcpServers":{}}'`. This adapter supplies no preapproved tool grant or MCP server. These flags are not a process sandbox; do not assume they restrict every local capability. A fresh launch passes `--session-id <uuid>`, so `Claude.launched` can find the transcript later; a resume passes `--resume <id>`. The report comes back in `structured_output`.
- **Codex:** First call `Codex.write_schema(<task-owned-file>)`; `REPORT_SCHEMA` is Claude's schema, not Codex's strict wire schema. Then `codex exec --json --ignore-user-config -C <dir> -s read-only --output-schema <file> [-m <model>]`. Every wire property is required; binding fields stay non-nullable (empty strings and revision0 only for an unbound task), unused optional fields are null, and evidence reports are JSON-encoded objects decoded by `Codex.parse` before existing validation. Config/connectors/plugins are not inherited; auth still works. Pass a model verified with `codex debug models`; without `-m` the built-in default applies. Resume uses `resume <thread_id> <prompt>`. The thread id appears only in output, so interrupted fresh launches stay uncertain. The experimental app-server is not used.
- **Model and tool choices** come from private config, never from this repo.
- **Limits:** these start or resume sessions this layer owns. Nothing here controls a running interactive desktop or terminal session, and nothing archives one.

## Verify before closing
Compare the worker report with the current goal, owner/target, runbook route, approval, exclusions and complete done-when checks. Return old or adjacent work for correction. Inspect actual artifacts and run relevant checks on the exact candidate. For a native task, record verified state and evidence in supported task details and confirm its status/details receipt; if unavailable, report verification without claiming host closure. For the local CLI path, confirm the commit in the record's worktree and task branch, run project tests, then send the matching `verified` event. Neither path treats a worker ready claim or deployment success as functional acceptance.
