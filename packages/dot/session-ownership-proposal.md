# Cloud-first session ownership proposal

Status: design for review, 2026-10-02. No worker launch, Desktop bridge, or archive route is activated by this document. The existing local rollout remains the baseline.

## Decision

Dot keeps the work-item record and coordinates one accountable task-owning worker. Use a cloud terminal worker session when its supported interface supplies durable identity, evidence, and human/orchestrator terminal resume. Use a Mac worker when the task needs its local filesystem, hardware, authentication, or GUI, or when the cloud route cannot pass the gates below. A manual Desktop session is initially human-operated; Dot can coordinate it after an explicit delegation, but cannot silently acquire or write to it. The human makes final decisions and retains direct access to workers. Assistant-created sessions may be migrated after reconciliation; user-created sessions are never migration or archive candidates without an explicit request covering that action.

The task packet binds a stable task ID and revision, one owner, scope and exclusions, baseline, acceptance criteria, pinned skill bundle, and references. The record also names the execution surface, host, session ID, worktree or cloud workspace, last verified checkpoint, and evidence. A prepared packet is not a dispatched task. An owner-reported completion is not accepted completion.

## Ownership and transitions

The private work-item record separates `origin_owner` (`assistant` or `user`) from current `operator` (`assistant` or `human`). It has one write operator at a time, with a host, session ID, revision, and increasing ownership generation. It also records `pending_dispatch`, last receipt, source freshness, and an explicit `held` reason. Treat the generation as a fencing value in every later report: an older or canceled worker result is evidence to inspect, never authority to resume or overwrite work. A changed scope, packet hash, bundle hash, or revision requires a new reviewed packet.

1. **Prepare:** validate the packet and target, pin the bundle and baseline, and record the intended owner. This creates no session.
2. **Dispatch:** use only a verified host adapter. Persist an attempt ID before sending. Record the session ID and receipt after observing them. An unknown outcome stays uncertain until the host's session list, transcript, or worktree proves sent or unsent; reconcile before retry.
3. **Human takeover of a terminal worker:** request a checkpoint, ask the worker to stop, and verify quiescence on the actual host. Capture the session ID, transcript location, worktree/branch/commit, dirty files, pending external effects, approvals, and next steps. Advance the generation and hand the same session to the human only if that host's supported interactive attach/resume path has been tested. The terminal must show the exact registered session/resume identity. If the worker cannot be stopped or the identity cannot be verified, hold the item with no second writer.
4. **Resume orchestration:** the human explicitly releases the session, records work and unresolved effects, and the orchestrator checks the current revision, hashes, host session state, and workspace state before resuming. A changed baseline or unclear side effect goes to review. A user-created Desktop session becomes orchestratable only through a separately verified adapter and explicit delegation; its origin stays user-owned and it gains no implicit archive authority.
5. **Migrate an assistant-created session:** stop the old writer, reconcile pending effects and dispatch receipts, preserve the checkpoint and workspace, then verify the destination session identity and resume reference. Advance the ownership generation only after both endpoints agree. A late result from the old session is stale evidence.
6. **Review/close:** map every acceptance criterion to an artifact, check, commit or snapshot, environment, and any unknown. Independently verify what the host permits. Keep owner claims distinct from verified evidence and human acceptance.

One-writer ownership is a protocol, not a claim that a local record can lock a remote agent. Until a host can confirm stop and resume semantics, it is safer to hold the work item than to launch another writer against the same target.

## Host capability gate

For each adapter, record host and version, discovery path, launch/attach/resume/archive modes, terminal session visibility to the human and orchestrator, identity and receipt evidence, ability to stop a writer, and the date and result of a native test. Capability labels are `documented`, `observed`, `verified for this route`, or `unavailable`; documentation alone does not make a route active. Desktop visibility is an additional route, not a prerequisite for assistant-created cloud terminal workers.

| Route | Current evidence | Decision now |
| --- | --- | --- |
| Dot's own cloud workspace and ordinary tools | Durable task context was observed in this task; no Dot worker adapter was verified. | Design target for the private record; do not imply automatic synchronization or worker launch. |
| Standalone Codex app-server in this cloud workspace | Initial read-only runtime-home launch failed. A fresh writable runtime home later passed initialize/exit; account status remained unauthenticated, with no model or worker run. | Initialization observed only; hold dispatch and terminal takeover claims. |
| Standalone Claude CLI in this cloud workspace | CLI was absent. | Unavailable here. |
| Native Codex cloud task | [Codex cloud documentation](https://learn.chatgpt.com/docs/cloud) describes review and continuation across web, mobile, and desktop. The exact task/ownership route was not tested here. | Candidate for a separate native trial; no automatic takeover promise. |
| Native Claude cloud task | [Claude sessions](https://code.claude.com/docs/en/sessions) distinguishes session surfaces and documents resume behavior. | Candidate for a separate native trial; verify the particular cloud-to-Desktop route. |
| Local Claude CLI to Desktop | [Claude Desktop](https://code.claude.com/docs/en/desktop) documents `/desktop` and `claude --desktop --resume` for eligible local sessions, with limits for cloud/SSH/WSL and already-open sessions. | Documented fallback, requiring a native test on the Mac before an orchestrated takeover. |
| Codex CLI resume | [Codex CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli) document terminal resume by session ID. | Terminal continuity only; Desktop visibility is unverified. |

Cloud execution must first pass its network/authentication policy and file access checks. The current checkpoint lacks an authenticated worker session; effective network policy still needs review for the required additional domain. Do not broaden access as part of this proposal.

## Milestones and archive

Report a short structured update when a blocker clears, scope changes, a result is verified or deployed, a monitor reaches a verdict, and work completes. Each report includes task ID/revision, owner/session, status, changed facts, evidence links or hashes, source and verification level, pending decision, and next checkpoint. The orchestrator reconciles these reports into the work-item record and asks the owner about stale state. Generating a report does not assert live synchronization.

Archive only after accepted completion, no unresolved dispatch or external effect, and a verified recovery path. User-created sessions require separate explicit archive authorization even if delegated or idle. Save the task packet and revisions, host/session IDs, transcript or export location, milestone and acceptance evidence, branch and commit, a recoverable snapshot of uncommitted files, pending decisions, and archive timestamp. Use the host's supported archive operation; preserve the ability to restore the exact bundle and workspace state. If archive outcome is unknown, inspect the host before retrying. A restore drill must recover the session reference, task record, and Git state before calling the route safe.

## Portable integration contract

`agent_skills/session_registry.py` supplies pure register, status, delegation, checkpoint takeover, migration reconciliation, result, and archive eligibility operations. It performs no host calls, file writes, or automatic transitions. The native cloud worker owns the adapter: it must verify actual session creation and resume identity before `register`, persist the resulting record atomically, supply current packet/checkpoint and host observations to each transition, and expose `status` with the terminal resume reference to the human. It must also persist dispatch attempts before sending, reconcile unknown outcomes against native receipts, stop the old writer before takeover or migration, and reject old-generation output. Only its supported host API may launch, attach, archive, or restore. The UI inventory must preserve `origin_owner` separately from `operator` and request explicit delegation or archive authorization for user-created sessions. This keeps one registry definition rather than duplicating lifecycle logic in the runtime.

The native adapter's observation should include its runtime home, startup time, initialized state, account/auth state, exit code, thread and turn IDs when present, and independently verified visibility/takeover state. These are evidence fields, not inferred capabilities. The current cloud app-server initialize/exit was observed with a fresh writable runtime home, but account status was unauthenticated and no worker/model run or terminal takeover was verified. The runtime must hold dispatch until its own authenticated session path and resume checks pass; it must not copy credentials to make the contract appear ready.

## Acceptance gates for an implementation

1. Confirm cloud host/version, policy, session creation, identity, receipt, human and orchestrator terminal visibility, stop, attach/resume, and archive through supported native mechanisms. Test a disposable task with no business side effects.
2. Test duplicate dispatch, unknown send, stale and late result after revision change, ownership conflict, interruption during takeover, and failed authentication/network. No case may create two concurrent writers or mark a claim as accepted evidence.
3. Demonstrate human terminal takeover and release of the **same** session on the selected host. Separately test explicit delegation and later coordination of a user-created Desktop session; retain user origin and archive gate. Desktop continuity is not required for assistant-created terminal sessions.
4. Demonstrate evidence mapping and a lossless archive/restore drill, including dirty files and pending effects. Record actual skill selection/loading evidence separately from these lifecycle tests.

The next native test is a disposable cloud worker task after effective network policy is reviewed and available, followed by verifying its session ID and whether the user and the orchestrator can each open and resume that exact terminal session. Keep the Mac fallback and Desktop delegation gate separate until each route passes its own test.
