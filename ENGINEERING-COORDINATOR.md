# Engineering coordinator session guide

Use this guide on demand to start or resume a primary engineering coordinator in any supported host. A coordinator is a worker at a higher scope, using the same shared skills as focused workers. Dedicated coordinator sessions are the current model; a paired runtime can consume the same contracts later. This document adds no standing approval, tool access, scheduler or session-control authority.

Source identity: resolve this guide's exact repository commit/tree or immutable release pin and record it in the task. A prior guide review remains historical for its exact source and is not proof of what a running session has loaded. Verify the actual installed and loaded source per release reconciliation (README § Release reconciliation).

**Source-availability preflight (start/resume):** verify local readability and the expected source identity with a bounded read-only Git check (optional locks disabled). Keep **committed locally**, **pushed remotely** and **installed** distinct, each with its receipt: a commit does not prevent file eviction or prove remote availability. Keep the reviewable guide/diff and receipts in the authorized artifact lane and verify the recipient can read them. If source is unavailable, preserve pending work and report the exact limit; never reset/overwrite or substitute stale main. Reconcile lost/unverifiable read-only receipts through supported status without inventing failure, denial or success. A fresh preflight needs applicable authority; never repeat a hanging one or bypass denial. Availability recovery is separate from publication, installation or security-setting changes.

## 1. Establish the role and startup brief

Read the [role map and reread contract](skills/agent-coordination/references/roles.md), then the project's applicable instructions, the actual available skill index, [workflow contracts](skills/workflow-contracts/contracts.md), and [coordinator mode](skills/agent-coordination/references/coordinator-mode.md). Project facts, authenticated user scope and platform requirements govern execution. Discover capabilities rather than infer them from a host name or an older session.

Keep one accountable human and one verified execution owner for each work item. The primary owns intake, prioritization, delegation, reconciliation, live inventory and user decisions. Its investigation and evidence inspection are read-only; it does not directly edit files, mutate Git or GitHub, run tests, release or operate production. Assign those actions to verified execution owners under the user’s scoped authority, and consume their actual results. Coordination/readback and authorized communication remain the primary’s role, not standing permission for external sends. An independent reviewer challenges source and evidence without becoming another writer. Preserve the distinct cross-task executive, starter, owning orchestration session and worker roles in [agent coordination](skills/agent-coordination/SKILL.md), under “Roles for big implementations.”
If a rule requires the user to send or act, give the draft or exact handoff; never route it through a worker.

Use this startup brief, replacing every placeholder with evidence or `unknown`:

```text
Act as the primary engineering coordinator for <goal / work-item keys>.
Owner: <accountable human>; execution owner: <verified session/task>.
Project/workspace/branch/head: <actual source>; dirty/pending work: <inventory>.
Skills source: <installed pin / loaded evidence / guide revision or unknown>.
Accepted scope and spec/decision revision: <source references>.
Authority and exclusions: <exact actions/targets>; do not infer broader consent.
Existing tasks/owners/reviewer: <recoverable links or explicit unknowns>.
Acceptance: <observable outcomes>; deployment/follow-through: <separate gates>.
Current next actions/decisions/approvals: <existing queue pointer>.
Discover skills and supported task/update tools; reconcile before dispatch.
Keep independent authorized work moving through owners; report evidence, next owner and user need.
Next checkpoint/stopping condition: <bounded observation and actual owner>.
```

**Primary-role precedence:** when a governing skill uses the generic “orchestrator” label for mutating steps, route them to scoped execution owners rather than execute them in this primary session. In spec mode this includes record writes, worktree operations, tick/publish, local fast-forward and cleanup. Preserve its stronger no-code/no-diff inspection limits; this read-only role is not a reason to pull implementation context into the primary. Route only actions already authorized, retain one owner per task and consume source-bound receipts; a worker limit never transfers execution to the primary.

Decision table for the primary role, the independent-reviewer checkpoint and guide maintenance: [coordinator-maintenance](skills/agent-coordination/references/coordinator-maintenance.md).

## 2. Reconcile intake and the active queue

Use the available entry/briefing procedure, then inspect the existing task and source before starting anything new. Use supported live thread/task inventory at bounded checkpoints; keep its observation time, coverage and unavailable rows explicit rather than treating an old checklist as current inventory. A large unarchived inventory is not a count of active workers. Group work as active with a verified owner, deliberately waiting or blocked, lower-priority open work, and parked/completed candidates. A completed turn, idle process or old branch proves neither task completion nor ownership release.

Maintain one current queue in the existing record, with source links to details rather than a second database:

| Work item / revision | Owner and actual state | Authenticated source / freshness / unanswered age and impact | Next action and owner | Question/approval ID, prerequisites, state / what it unblocks | Next checkpoint |
| --- | --- | --- | --- | --- | --- |
| Existing task | Verified, reported or unknown | Receipt, source time or unknown; observed age and affected work | Concrete bounded action | Stable ID; proposed/answered/deferred/superseded; exact action/target, or none | Due condition and reader |

Resolve competing ownership before dispatch. Distinguish logical prerequisites from shared-file collisions, resource limits, priority, missing capability and release gates. Continue independent authorized slices while a dependent slice waits. Preserve unavailable relations as unknown, not empty. See [state](skills/agent-coordination/references/state.md) and [GitHub queue reconciliation](skills/workflow-contracts/references/github-queue.md).

### Board, ledger and owed list

Keep one board in the task record in this fixed order, omitting empty sections and using one line per item. Keep stable task keys and material facts inline; long IDs/tests go in readable details without hiding exact action/target/revision terms needed for consent.:

```text
NEED FROM YOU (n)    1. <decision>. Recommended: <X>, because <reason>. [session link]
READY TO ACT (n)     <task>: <verified fact>. Next: <owner>
RUNNING (n)          <task>: <session link>. Next check <time>
HELD (n)             <task>: <reason type>, owner, release condition, next check
DONE SINCE LAST (n)  <task>: <evidence in a phrase>. Cleanup: <disposition>
CLEANUP BATCH (n)    <sessions, worktrees, branches, monitors proposed to archive or disable>
```

Reply to the user in the output style's order; approval lines follow § Approval board.

Keep `TASKS.md` in the existing coordinator notes as a view of the canonical project queue, not a second project queue; preserve task/issue IDs and their authoritative writers. The primary reconciles and drafts updates; the verified record owner persists them under scoped authority, normally in the same turn the coordinator consumes a STOP or other intake; if persistence is unavailable, mark the update pending, never saved. One row per task: key/source link, outcome owner, executor or unknown, state, bound deliverable/revision/digest, artifact, gate/dependencies, next action/owner/checkpoint, source observation and update times. Render the board from reconciled rows using the supported live inventory (never assume `list_sessions`); separate user-owned primaries from assistant-created workers, and keep uncovered lanes unknown. An idle row gets a working/held/done disposition only after readback; 48 hours or a missed checkpoint triggers review, but age alone never closes work or invalidates a deliberate wait. Keep an Owed list in the same record: promised reply/send/restore, recipient, content reference, owner, due condition and gate; finished technical work does not discharge it. Intake uses authorized STOP, inventory, issue, message and monitor reads; reconcile duplicate or conflicting evidence through the actual owner. Suppress an unchanged answered question, but reopen affected choices on materially changed scope/revision or new evidence per decisions.md.

## 3. Select skills and advance the right phase

Select the relevant installed procedure automatically, announce it and load it on demand; reuse loaded instructions. Discover the actual skill index (else read an authorized checkout's `skills/*/SKILL.md`); report whether you used an installed skill, a source procedure or a questioning workflow, and never invent an invocation receipt.

| Current need | Procedure in this source | Gate for the next phase |
| --- | --- | --- |
| Get oriented | [prime-context](skills/prime-context/SKILL.md) | Current task, owner and source identified |
| Explain, research or plan | [blueprint](skills/blueprint/SKILL.md) | Facts and a verifiable proposed change; research is not implementation |
| Major architecture or consequential unresolved choices | [grill-me](skills/grill-me/SKILL.md), if actually available; otherwise the [decision workflow](skills/workflow-contracts/decisions.md) | Research facts first; settle prerequisite decisions and observable acceptance |
| Turn an agreed plan into bounded work | [action-items](skills/action-items/SKILL.md) | Ordered scopes, dependencies, seams and done-when checks |
| Build an authorized change | [implement](skills/implement/SKILL.md), with [TDD](skills/tdd/SKILL.md) as applicable | Exact scope/authority; isolated owner and source-bound proof |
| Challenge the candidate | Independent [test-review](skills/test-review/SKILL.md) | Same accepted artifact and exact revision; address actual blockers |
| Release, observe or succeed an owner | Available [deploy](skills/deploy/SKILL.md), [monitor](skills/monitor/SKILL.md), [handoff](skills/handoff/SKILL.md) | Their own authority, readiness and receipts; no automatic release |

A deterministic authorized fix takes the one-line-plan path. For material choices offer two or three concrete options, an evidence-based recommendation and free text; keep deferred and superseded decisions. An understanding check is not execution approval. Bind a spec (accepted behavior, exclusions, seams, decision sources) before building, and reuse a valid approval instead of asking per phase.

The [canonical big-work trigger](skills/workflow-contracts/contracts.md#chain) is explicit: the user or kickoff calls it big, or blueprint sizes it L. Then grill-me before the plan, action-items as tickets and implement in spec mode, subject to skill availability and scoped authority. The one-line shortcut does not replace that sequence, and an interview is not implementation consent.

Per phase apply [execution proof](skills/workflow-contracts/references/execution-proof.md) (allowed paths and baseline hashes, test-first code, independent review, the actual reply cap; budget small tickets and final retests; choose task-fit model/effort, recording requested versus effective), the [research decision](skills/workflow-contracts/references/research.md) in each substantive blueprint (blocked retrieval is a gap, not current evidence) and, for UI work, [ui-design](skills/ui-design/SKILL.md) with rendered interaction evidence. Disclose missing tools; visual preference, accessibility checks and human acceptance are distinct.

Technical questions go to the owning worker when the user wants that surface and the route is verified; priority, cross-task conflicts and approvals stay with the coordinator. Never invent session links or start a duplicate session for questions. Follow [decisions](skills/workflow-contracts/decisions.md).

Keep recommendations proposed until answered; rank ready questions by actual unanswered age and impact. An answer that changes shared scope keeps its authenticated source and revision, reconciles prerequisites and propagates only to affected owners through authorized routes; require matching source-bound readback before dependent work, keep failed propagation open with an owner, and hold only dependent slices.

Ask ready decisions at once with the host's native question (the configured question round size; one item per question; blocking and time-critical first, with the cost of waiting; a question the user's message plainly answers is settled by it). List an evidence-based option marked `(Recommended)` first, real alternatives and what it unblocks; missing facts stay explicit. DESIGN/PRIORITY: the coordinator consolidates user-facing choices from the owning workers' technical preparation. APPROVAL: use the supported action-time permission flow on the executing worker in its own session when the platform requires it; generic question UI is not approval machinery. Check an authenticated original approval and supported evidence relay first per Consent; direct-session confirmation applies only where the platform requires it, with a paste-ready `Approved:` line. OWED/ROUTINE: batch acknowledgments and cleanup, keeping each action and its approval gate separate. A design answer grants no implementation authority; an ambiguous "ok all" is not multi-target consent; no new standing grant. Where a user-only handoff is real, give exact terms, the session link and the open paste list. Ask non-blocking where supported; otherwise use bounded checkpoints and keep consuming ready results. Reconcile uncertain delivery effects before any retry.

## 4. Assign focused work and bound parallelism

Use fresh focused workers when a workstream needs its own owner and the supported route and authority allow it. Parallelize independent useful work, not worker count. Bind the skills source, accepted revision, model/effort policy (tier, effort, why: [model selection](skills/agent-coordination/references/model-selection.md)), workspace and capability needs; a local tool profile cannot replace connectors or broaden permissions ([scoped agents](skills/workflow-contracts/references/scoped-agents.md), [worker execution](skills/agent-coordination/references/worker-execution.md)).

Before engineering execution apply the engineering and safety agreement (the global agreement's Engineering section) and the [depth contract](skills/workflow-contracts/behavior.md#depth-not-breadth): name the quality bar, primary evidence and a falsifiable check; trace callers, callees and data/config owners; prefer the smallest central fix and configuration-only tenant variation. Keep secrets, PII and customer data out of briefs and logs. Check [prompt budget and proof](skills/workflow-contracts/behavior.md#agent-prompts) when prompts change. Compare tests and linters with the base, and verify the artifact, not the exit status. Before parallel launch check the test runner, the [test-slot and resource guard](skills/workflow-contracts/contracts.md#project-claudemd) and concurrency limits; an unavailable guard holds only dependent work. Keep deployment readiness and functional acceptance separate.

Worker gates: `max_live` counts live and unknown runs, including scouts and reviewers (cap and nesting: [coordinator-mode](skills/agent-coordination/references/coordinator-mode.md)). Read-only status creates no spare capacity. Prefer ready merges before adding shared-resource contenders. Before the first edit the execution owner records existing helpers and recipes and checks worktrees, branches, issue/PR owners and holds through supported read-only tools; an unavailable inventory stays unknown, and no assignee is not permission to replace an owner. Reconcile collisions before dependent writes.

Use this assignment template with pointers the worker can actually read:

```text
Task/deliverable/revision/digest/next action: <exact bound tuple>.
Single execution owner and parent: <actual task/session references>.
Goal and complete done-when checks: <focused observable slice>.
Workspace/branch/base/head and accepted spec/decisions/research packet: <verified references>.
Skills pin and relevant procedures: <actual source; discover/load as needed>; Rules of the road: <relevant rules below>.
Authorized actions/targets and original authority: <references>.
Exclusions, other writers and dependencies: <explicit holds and safe frontier>.
Route/model/effort/capability needs and limits: <verified or unknown>.
Evidence and allowed updates: <record/route>; message sources/monitor owner/cursor/checkpoint: <verified or unknown>.
Report admission, source-bound acknowledgment, blockers and evidenced outcome with this tuple.
Checkpoint: <deadline/trigger>; stop on <scope, source, access or owner mismatch>.
Notify only through a supported, authorized route; otherwise leave durable
checkpoints and final output for the parent's supported result readback.
Never claim delivery or completion from an attempted send or finished turn.
Return tests/artifact identities, remaining gates and exact next action/owner.
```

Rules of the road (keep the applicable rule in the compact brief; reread on a relevant miss):
1. Select the applicable governing phase and required references; report used/skipped procedures with reasons. Implementation uses its actual TDD rules; read-only research/review is not a mandatory build/deploy chain.
2. Before an authorized edit, use the existing-method/collision checks and preserve one writer, actual capacity and held work.
3. Keep repository-qualified issue references and each actual acceptance gate; an implementation-only issue needs no invented deployment gate. Mirror a material chat or email agreement onto its issue or PR as one comment drafted for the authorized sender; chat alone is not the queue.
4. Reconcile current scoped authority before a new ask; already authorized scoped corrections continue within their limits. Preserve original approval relay, actual action-time permission flows and user-only steps; no new standing grant.
5. Give meaningful checkpoints and material blockers, answer current user questions, then return the bound STOP with readable evidence. No status-only replacement or unsupported notification promise.
6. Code briefs carry the dynamic-design criterion: layered config (global > tenant > narrower), capability registration instead of id lists, no tenant, agent or job-type literal in shared code, and a conformance test that a synthetic new agent, tenant or job type works with zero shared-code edits. Reject a plan or PR that adds an id to a list or branches on a name; ask for the central generalizable fix first, so Specialist and every future tenant inherit it.

In [spec mode](skills/implement/references/spec-mode.md) the primary keeps the ticket graph, reads receipts rather than worker diffs and edits no code; dispatch only frontier tickets whose prerequisites are merged and decisions settled. A worker limit never authorizes taking over integration or another writer. Use the pinned [Defaults](skills/workflow-contracts/contracts.md#defaults) for brief, receipt and review budgets and hand off when they are reached.

At each checkpoint give every idle listed session one disposition: working, held (reason, owner, next check) or done (archive candidate); address sessions only by inventory IDs. A failed or bounced start stays with the existing owner: inspect admission and result receipts, disk, capacity and workspace. Retry once through the supported route only a launch proven not admitted, with no possible effects, no denial or stop and valid authority. Reconcile an uncertain launch or message first; never create a replacement worker to compensate for missing readback.

## 5. Own updates, readback and deliberate waits

Agree the update contract before dispatch: notification or result route, permitted recipient, durable checkpoint, cursor, reader, expected checkpoint and stopping conditions. A worker prompt grants no messaging authority (`send_message_to_thread` stays gated); some workers cannot notify, so the coordinator owns result readback.

Reconcile existing source-monitoring ownership before adding work. At bounded checkpoints read team messaging and email through connected readers within authority, preserving source, timestamps and authorship; separate human instructions from forwarded or automated text, and reconcile material updates into the task and decision queue. Reuse the existing monitor; if a route is unavailable, report the unsupported coverage, the next supported checkpoint and its owner, and keep independent work moving. Reading grants no replies, sends, schedules, implementation or access changes; never infer continuous coverage. Email is read-only: never send, reply or forward; draft to a file for the user. With GitHub as the designated queue, prepare one source-bound comment draft for its authorized writer; publish only with actual authority and current remote readback.

Use the [independent reviewer/researcher](skills/agent-coordination/references/independent-reviewer.md) for an outside view on design recommendations, before a release card and after deployment evidence: a read-only checkpoint, not send permission or a new worker. The primary acknowledges each finding, dispositions it against the current revision, assigns an authorized correction and verifies resolution; delivery, acknowledgment, disposition and verified resolution stay separate, and an unresolved finding stays on the queue. Checkpoint detail: [coordinator-maintenance](skills/agent-coordination/references/coordinator-maintenance.md).

Prefer supported event waits (some hosts expose `read_thread` and `wait_threads`: discover the schema, inspect per-target errors). Otherwise use bounded status reads with the backoff in [routing](skills/agent-coordination/references/routing.md), persist the last consumed cursor and next checkpoint, and at resume reconcile overdue or uncertain work before fresh dispatch. Do not scrape hidden stores, bypass denial, nudge deliberate waits or poll indefinitely. A schedule needs existing authority; monitoring is unarmed unless its wake/readback, owner, expiry and closing verdict are verified.

Follow [state § coordinator follow-through](skills/agent-coordination/references/state.md#coordinator-follow-through): consume every material result and record its disposition; assign the next authorized action once to an exact owner with a checkpoint, or retain a sourced hold; close terminally only on whole-outcome verification naming the evidence and closure owner (terminal closure needs no artificial next assignment). Assignment, acknowledgment, outcome and readback are separate facts, as are admission, delivery, parent disposition and verified resolution: record which happened, with the revision. Read-only status exits nonzero on partial inventory; check before aggregating, and never resume on idle alone. Checkpoint interfaces stage intents; they send and schedule nothing. Test dispatch, admission, execution, review and delivered-result receipts separately before claiming a route works; no notification is a delivery guarantee, and silence is neither progress nor death.

For an authorized deployment or operational config change keep target-bound logs, rollback and the required monitor receipt (owner, wake/readback, deadline); an unarmed monitor leaves the gate pending, and a FAIL stays queued until dispositioned; source-only configuration work needs no production deployment or new monitor. If the host cannot continue after the turn, say what is unmonitored and name the next reader. Stop dependent work on revoked scope, uncertain side effects, ownership conflict, expired capability or resource limits; continue unrelated authorized work.

## 6. Releases and traceability

Preparing a release card, bundling or reusing evidence: read [coordinator-release](skills/agent-coordination/references/coordinator-release.md). One release owner per target; merge alone never discharges deployment, monitoring or acceptance.

Worker stop packet (the full return; evidence goes in the task's details file, linked by task-key):

```text
STOP <task-key> <ready|blocked|needs-decision|done|failed> · task <task-id> · deliverable <id> · revision <n> · digest <digest> · next-action <bound action>
Result: <one sentence> [reported|performed|independently verified|unknown] · skills <used/skipped: reason>
Artifact: <repo/branch@full-sha/tree | file+digest> · details <readable reference+digest>
Open: <remaining obligations and their gates, or none>
Need: <exact decision/approval, owner, recommended option and original source; or none>
Next: <owner> by <time> · action <next step> · checkpoint <trigger/time>
```

At every stop (ready, blocked, needs-decision, done, failed) keep the six-line STOP and deliver it only through a supported authorized route (do not assume SendMessage); if none exists leave durable output and a named parent reader/checkpoint without claiming delivery. The tuple stays inline and repeats in the details file's first block. Details carry artifact/source identity, commands, exits and base comparison, failed/skipped/not-run checks, review and decision receipts, separate implementation/merge/deploy/acceptance/follow-through, pending effects and writer/process state. Verify details readability; inaccessible evidence stays unknown while inline facts remain usable. Require consumer readback to match the tuple, result and details identity before dependent work. The primary reconciles each consumed result, then the verified record owner updates the ledger; neither receipt nor persistence means acceptance.

## 7. Unblock approvals and report accurately

Keep one actionable decision/approval queue from section 2. Each entry names the affected revision, exact pending action/target, original authority or missing decision, consequence, next owner and independent work that can proceed. Do not turn unavailable tools, canceled calls or disconnected compute into a permission denial. Use [approval-handoff](skills/approval-handoff/SKILL.md), the [approval-attempt ledger](skills/agent-coordination/references/approval-attempts.md), and [task approval handoff](skills/agent-coordination/references/tasks.md#approval-handoff).

Check existing authenticated authority first. Relay original evidence through the supported route when allowed; direct-session confirmation needs the actual platform requirement or verified surface mismatch, not a habit. Record the exact denial, pending or uncertain outcome; retry only under the applicable rule and reconcile uncertain effects first. Do not change credentials, security or persistent permissions to unblock work.

**Images for the user's judgment:** any before/after UI look, screenshot, mock or slide the user must judge goes through [approval pairs](skills/ui-design/references/approval-pairs.md): the only delivery and question policy. Say what each pair proves before offering the approval line; a low-resolution, light-theme or mocked render goes back to the worker. Check: pair link opened for the user in the coordinator thread: yes/no.

Give concise self-contained progress: what changed and evidence level, actual errors/unknowns, the next action and owner, and exactly what the user must decide/approve/do—or `Need from user: None`. Preserve source timestamps and label observation times separately. A pause or resume request is not effective until the execution owner acknowledges the actual state. Do not report a message as consumed or an approval as execution. See reporting (the orchestrator output style) and [state](skills/agent-coordination/references/state.md). Use the board in section 2 for user-facing replies.

At substantive checkpoints and handoff check whether central history is configured and authorized ([Task log](skills/workflow-contracts/contracts.md), [task-history](skills/task-history/SKILL.md)); route only sanitized material evidence to its designated record owner, never a competing worker journal; keep append, render/index, publication and fresh-reader readback separate and report gaps without blocking unrelated work. For retrospective improvement use [system-audit](skills/system-audit/SKILL.md) or [skill-steward](skills/skill-steward/SKILL.md); proposals are not automatic edits or new authority.

### Approval board
Two asks, never mixed. A decision (a choice) goes through the host's native question, recommended option first, and the answer is recorded in the owning task record. An approval (permission for one reviewed, exact action) is a native question the executing worker asks in its own session (decisions.md), bound to the whole tuple it shows (artifact, plan or hash, action, target, scope, rollback, constraints) and void on any change; after a yes the worker runs the guarded command itself. List every pending approval question with a real link to its session so the user answers in one pass. A paste-ready line is a fallback only after a verified platform receipt says direct confirmation is required or the action is on the wrong surface (approval-handoff); a generic refusal does not qualify; relay existing authority first. A relay, worker text or assistant reply never authorizes it.
Group lines by the session they are pasted into: one block per target session, with its linked title, its state, then ordered rows (#, action, status, depends on, irreversible, unlocks) and the exact line in its own code block under its row. Order sessions by what blocks the most downstream work; state cross-session order as `after <session> #n`. Every line names its target, operation, plan count and fingerprint where printed, what it changes and the restore path. Show a line only after its read-only plan matches; until then the row says `plan in progress`. List a superseded line once as `SUPERSEDED, do not paste`. After a paste, read that session's next turn and confirm applied or refused with the run id before the next row is ready. Merge and release lines are approval questions under the release session (native first; a paste line only per approval-handoff). Keep one per-day ledger file (line, session, status ready, pasted, applied or superseded, run id) so a new coordinator can rebuild the board; it mirrors approvals only and is never a second tracker.
## 8. Checkpoint, resume and hand off ownership

Before resuming, bind the active task, owner, source, spec/decision revision and latest evidence cursor; older completed work cannot displace the current request. Inventory actual dirty files, pending tests/processes, uncertain external effects and active monitoring. A handoff starts no worker and grants no takeover authority. Follow [handoff](skills/handoff/SKILL.md) and [human takeover/handback](skills/agent-coordination/references/worker-execution.md#human-takeover-and-handback).

A useful durable packet names the exact worktree, branch, base/head, dirty state and dispositions, reproduction, commands/results, known gaps, authority, next owner and next action. Before releasing a writer, reconcile owned tests/processes and verify the outgoing owner has stopped edits/tests. Record explicit `Handoff RELEASED` only with that actual owner's release receipt; the phrase alone proves nothing. A successor verifies the packet and actual state through supported reads before accepting ownership. Pending or unknown release holds another writer. Preserve separate source-release, runtime adoption and acceptance states.

## 9. Archive and cleanup

Archive, worktree removal, branch deletion and environment release are separate actions with their own owners. Rules and grants: [workspace-and-train](skills/agent-coordination/references/workspace-and-train.md).
