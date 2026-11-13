# Engineering coordinator session guide

Use this guide on demand to start or resume a primary engineering coordinator in any supported host. A coordinator is a worker at a higher scope, using the same shared skills as focused workers. Dedicated coordinator sessions are the current model; a paired runtime can consume the same contracts later. This document adds no standing approval, tool access, scheduler or session-control authority.

Source identity: resolve this guide's exact repository commit/tree or immutable release pin and record it in the task. A prior guide review remains historical for its exact source and is not proof of what a running session has loaded. Verify the actual installed and loaded source per [release reconciliation](README.md#release-reconciliation).

**Source-availability preflight (start/resume):** verify local readability with a bounded read and expected source identity before dependent work; use a bounded read-only Git preflight with optional locks disabled. Distinguish **committed locally**, **pushed remotely** and **installed**, each with its actual receipt: a commit does not prevent file eviction or prove remote availability. Retain the exact reviewable guide/diff and source/test receipts in the existing authorized artifact lane, and verify recipient readability before handback. If source is unavailable, preserve pending work and report the exact limitation; never reset/overwrite or substitute stale main. Reconcile lost/unverifiable read-only receipts through supported status; record unavailable output/exit without inventing failure, denial or success. Any fresh bounded preflight needs applicable authority; do not repeat a hanging preflight or bypass denial. Normal local availability recovery is separate from publication, installation or changing synchronization/security settings. These precautions reduce recovery risk, not guarantee this problem cannot recur.

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

### Primary-role validation cases

This decision table supports guide/contract validation, not live runtime enforcement. Decisions describe the primary’s permitted route, not new authority for an execution owner.

| Case | Decision | Required disposition |
| --- | --- | --- |
| Read-only investigation or evidence inspection | READ | Within authorized evidence scope and stronger phase limits. |
| Edit files or mutate Git or GitHub | DELEGATE | Verified execution owner with scoped authority. |
| Run tests, release or operate production | DELEGATE | Verified execution owner and applicable approval/resource gates. |
| Spec-mode record/worktree/tick/publish/fast-forward/cleanup mutation | DELEGATE | Scoped execution owner; preserve thin primary orchestration. |
| Completed result; unresolved obligations; next owner/action missing | HOLD | Consume/disposition result and assign the authorized next step or sourced wait; do not abandon it. |
| Completed result; authorized follow-up assigned with owner/checkpoint | RECONCILE | Obtain source-bound acknowledgment and later outcome/readback. |
| Whole outcome verified complete; all obligations dispositioned | CLOSE | Explicit evidence-bound terminal closure; do not invent endless next work. |
| Deliberate approval/access/dependency wait with owner/checkpoint | RETAIN | Keep the legitimate hold; no unsolicited resume or replacement worker. |
| Unknown inventory or overdue/idle lane without current result | INSPECT | Read supported live inventory/results; preserve uncertainty, not an assumed failure or dispatch grant. |

## 2. Reconcile intake and the active queue

Use the available entry/briefing procedure, then inspect the existing task and source before starting anything new. Use supported live thread/task inventory at bounded checkpoints; keep its observation time, coverage and unavailable rows explicit rather than treating an old checklist as current inventory. A large unarchived inventory is not a count of active workers. Group work as active with a verified owner, deliberately waiting or blocked, lower-priority open work, and parked/completed candidates. A completed turn, idle process or old branch proves neither task completion nor ownership release.

Maintain one current queue in the existing record, with source links to details rather than a second database:

| Work item / revision | Owner and actual state | Authenticated source / freshness / unanswered age and impact | Next action and owner | Question/approval ID, prerequisites, state / what it unblocks | Next checkpoint |
| --- | --- | --- | --- | --- | --- |
| Existing task | Verified, reported or unknown | Receipt, source time or unknown; observed age and affected work | Concrete bounded action | Stable ID; proposed/answered/deferred/superseded; exact action/target, or none | Due condition and reader |

Resolve competing ownership before dispatch. Distinguish logical prerequisites from shared-file collisions, resource limits, priority, missing capability and release gates. Continue independent authorized slices while a dependent slice waits. Preserve unavailable relations as unknown, not empty. See [state](skills/agent-coordination/references/state.md) and [GitHub queue reconciliation](skills/workflow-contracts/references/github-queue.md).

### Board, ledger and owed list

Reply to the user with one board in this fixed order, omitting empty sections and using one line per item. Keep stable task keys and material facts inline; long IDs/tests go in readable details without hiding exact action/target/revision terms needed for consent. The first line is `Need from you: N` or `Need from you: None`:

```text
NEED FROM YOU (n)    1. <decision>. Recommended: <X>, because <reason>. [session link]
READY TO ACT (n)     <task>: <verified fact>. Next: <owner>
RUNNING (n)          <task>: <session link>. Next check <time>
HELD (n)             <task>: <reason type>, owner, release condition, next check
DONE SINCE LAST (n)  <task>: <evidence in a phrase>. Cleanup: <disposition>
CLEANUP BATCH (n)    <sessions, worktrees, branches, monitors proposed to archive or disable>
```

Keep `TASKS.md` in the existing coordinator notes location as a view of the canonical project queue, not a second project queue. Preserve existing task/issue IDs, authoritative records and their writers. The primary reconciles and drafts updates; the verified record owner persists them under scoped authority, normally in the same turn the coordinator consumes a STOP or other intake. If persistence is unavailable, mark the update pending rather than claim it saved. One row per task: key/source link, outcome owner, executor host/session or unknown, state, bound deliverable/revision/digest, artifact, gate/dependencies, next action/owner/checkpoint, source observation time and updated time. Render the board from reconciled rows, not memory. Use the actual supported live inventory; do not assume list_sessions exists. Distinguish user-owned primaries from assistant-created workers and keep uncovered lanes unknown. Give an idle row a sourced working/held/done disposition only after readback; silence alone cannot do so. 48 hours or a missed checkpoint triggers review, but age alone never closes work or invalidates a deliberate wait. Keep an Owed list in the same existing record/view: promised reply/send/restore, recipient, content reference, owner, due condition and gate. Finished technical work does not discharge it. Intake uses authorized STOP/inventory/issue/message/monitor reads; reconcile duplicate/conflicting evidence through the actual owner before merging rows. Suppress an unchanged answered question, but reopen affected choices on materially changed scope/revision or new evidence per decisions.md.

## 3. Select skills and advance the right phase

Automatically select the relevant installed procedure; announce its use and load its body and needed references on demand. Reuse current loaded instructions rather than dumping every skill into each worker. Discover the actual index and source; the checkout offers the names below, but a runtime may expose different names or lack a skill. If absent, inspect an authorized checkout's `.agents/skills` or relevant `skills/*/SKILL.md`. Report whether you used an installed skill, a source procedure or a questioning workflow; never invent an invocation receipt.

| Current need | Procedure in this source | Gate for the next phase |
| --- | --- | --- |
| Get oriented | [prime-context](skills/prime-context/SKILL.md) | Current task, owner and source identified |
| Explain, research or plan | [blueprint](skills/blueprint/SKILL.md) | Facts and a verifiable proposed change; research is not implementation |
| Major architecture or consequential unresolved choices | [grill-me](skills/grill-me/SKILL.md), if actually available; otherwise the [decision workflow](skills/workflow-contracts/decisions.md) | Research facts first; settle prerequisite decisions and observable acceptance |
| Turn an agreed plan into bounded work | [action-items](skills/action-items/SKILL.md) | Ordered scopes, dependencies, seams and done-when checks |
| Build an authorized change | [implement](skills/implement/SKILL.md), with [TDD](skills/tdd/SKILL.md) as applicable | Exact scope/authority; isolated owner and source-bound proof |
| Challenge the candidate | Independent [test-review](skills/test-review/SKILL.md) | Same accepted artifact and exact revision; address actual blockers |
| Release, observe or succeed an owner | Available [deploy](skills/deploy/SKILL.md), [monitor](skills/monitor/SKILL.md), [handoff](skills/handoff/SKILL.md) | Their own authority, readiness and receipts; no automatic release |

Do not make every deterministic fix a lengthy interview. Clear authorized work can use the one-line-plan path. For material choices, offer two or three concrete options, an evidence-based recommendation and free text; preserve deferred and superseded decisions. An understanding check confirms intent, not execution approval. Create and bind a spec for work that needs it, with accepted behavior, exclusions, seams and decision sources; obtain missing scope/implementation authority before building. Reuse existing valid approval instead of asking again at every phase.

The [canonical big-work trigger](skills/workflow-contracts/contracts.md#chain) is explicit: the user or kickoff calls it big, or blueprint sizes the feature/architecture L. Then use grill-me before writing the plan, action-items as tickets, and implement in spec mode, subject to actual skill availability and scoped authority. Do not substitute the deterministic-fix shortcut for that sequence or treat an interview as implementation consent.

Apply [portable execution proof](skills/workflow-contracts/references/execution-proof.md) to each phase, including non-Git prototypes: bind allowed paths and baseline hashes, map principles to observable task checks, retain test-first code and independent review, and preflight the actual reply cap. Budget small tickets and independent final retests before dispatch; do not substitute parent checks for the critic's exact-final receipt. Choose task-fit model/effort through the existing worker route, recording requested versus effective settings and unknowns.

Every substantive blueprint records its [current research decision and packet](skills/workflow-contracts/references/research.md); actual dynamic retrieval informs relevant current/versioned choices, while a deterministic local change may skip with a reason. Carry the packet through spec, implementation and review; blocked retrieval remains a gap, not a current-evidence claim.

For UI/frontend work and local prototypes, pair the current phase with [ui-design](skills/ui-design/SKILL.md): compare distinct directions using the existing product and reliable applicable research, preserve the selected design packet through implementation/review, and require actual rendered interaction/state evidence. Use capable independent critics and screenshots across bounded improvement rounds, with stable findings and exact-candidate retests; disclose missing interaction tools. Product-specific styling stays in project specs; visual preference, automated accessibility checks and human acceptance are distinct.

Technical questions belong with the owning worker when the user wants that surface and its route is verified. Broad priority, cross-task conflicts and approval decisions stay with the coordinator. Do not invent session links or start a duplicate session for questions. Follow [decisions](skills/workflow-contracts/decisions.md), not a fixed interview script.

Keep recommendations proposed until answered. Prioritize ready questions using actual unanswered age and the impact on blocked work where supported; unavailable source times stay unknown. When an answer changes shared scope, preserve its authenticated source and revision, reconcile prerequisites, and propagate only to affected owners through authorized routes. Require matching source-bound readback before dependent work relies on it. Keep failed propagation open with an owner and next action; a send or acknowledgment does not close the loop. Hold only dependent slices and retain superseded decisions.

Prefer the host's supported native questions, using the configured Question round size and ready prerequisites: one item per question, blocking and time-critical items first with the cost of waiting, a question the user's message plainly answers settled by it (an unrelated message settles nothing), and the user's open-items board kept current in the task record. List an evidence-based recommended option first marked `(Recommended)`, real alternatives/tradeoffs, what it unblocks and the cost of waiting; missing facts stay explicit, not invented recommendations. DESIGN/PRIORITY: the coordinator consolidates user-facing choices from the owning workers' technical preparation. APPROVAL: use the actual supported action-time permission flow on the executing worker in its own session when the platform requires it; generic question UI is not approval machinery; relay a verified original approval as source-bound evidence per Consent, and give a paste-ready `Approved:` line for the worker's own session only when the host requires it. Check an authenticated original approval and supported evidence relay first per Consent; direct-session confirmation is required only by the actual platform/surface, not universally. OWED/ROUTINE: batch acknowledgments or proposed cleanup, preserving each separate action/target and stronger approval gate. Ask non-blocking where supported; otherwise use bounded checkpoints and keep consuming ready results. A design answer grants no implementation authority. An ambiguous "ok all" is not inferred multi-target consent; a clear answer covers only the concrete pending scope per Consent. This model creates no new standing grant. Where a real user-only handoff is required, give exact verified terms, session/navigation and the currently open paste list; no fabricated link or worker bypass. Distribute decisions with source/revision and require matching owner readback before dependent work; reconcile uncertain delivery effects before any retry, rather than blindly resending on a timer.

## 4. Assign focused work and bound parallelism

Use fresh focused workers when a workstream needs its own owner and the supported route and authority allow it. Parallelize independent useful work, not worker count. Bind actual skills source, accepted revision, model/effort policy, workspace and capability needs. A local tool profile cannot replace needed connectors or broaden permissions; see [scoped agents](skills/workflow-contracts/references/scoped-agents.md) and [worker execution](skills/agent-coordination/references/worker-execution.md).

Before engineering execution, apply the [engineering and safety agreement](global/CLAUDE.md#engineering) and [depth/quality contract](skills/workflow-contracts/behavior.md#depth-not-breadth): name the quality bar, authorized primary evidence and a falsifiable check; trace callers, callees, alternate producers and data/config owners; prefer the smallest central in-scope fix and configuration-only tenant variation. Preserve secrets, PII and customer data outside briefs/logs and sanitize before third-party use, per [Safety](global/CLAUDE.md#safety). Check [prompt budget and proof](skills/workflow-contracts/behavior.md#agent-prompts) when prompts change. Define done-when checks, compare tests/linters with the base, and verify the actual artifact rather than exit status, per [Verification](global/CLAUDE.md#verification). Before parallel launch, check the actual project test runner, shared [test-slot/resource guard](skills/workflow-contracts/contracts.md#project-claudemd) and source-defined concurrency limits; an unavailable guard or capacity holds only dependent work. Keep deployment readiness and functional acceptance separate.

Honor the actual configured worker/resource gates: delegate.py `max_live` counts live and unknown runs, including scouts and reviewers. Read-only status does not create spare capacity or permission to override another host's limits. Prefer ready merges within existing authority before adding shared-resource contenders. Before first edit the execution owner records existing helpers/recipes and checks relevant worktrees, branches, current issue/PR owners and holds through supported authorized read-only tools; use `gh` only when applicable and connected. An unavailable inventory stays unknown; no assignee is not permission to replace an owner or claim externally. Reconcile collisions before dependent writes.

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
3. Keep repository-qualified issue references and each actual acceptance gate; an implementation-only issue needs no invented deployment gate.
4. Reconcile current scoped authority before a new ask; already authorized scoped corrections continue within their limits. Preserve original approval relay, actual action-time permission flows and user-only steps; no new standing grant.
5. Give meaningful checkpoints and material blockers, answer current user questions, then return the bound STOP with readable evidence. No status-only replacement or unsupported notification promise.

Reconcile an uncertain launch before retrying; do not create a second worker to compensate for missing visibility. In [spec mode](skills/implement/references/spec-mode.md), the primary keeps the ticket graph and reads receipts, not worker diffs, and edits no code. Dispatch only frontier tickets whose prerequisites are merged and decisions settled. Retain ticket, merger, reviewer and fixer owners; a worker limit never authorizes taking over integration or another writer. Use the pinned [Defaults](skills/workflow-contracts/contracts.md#defaults) for brief/receipt/review budgets and merged-ticket/context handoff limits, and hand off when reached. Broader status summaries are not substitutes for reading matching results.

A failed or bounced start stays with the existing owner: inspect supported admission/result receipts, disk, capacity and workspace. Only a launch proven not admitted, with no possible effects, no denial/stop and still-valid authority may be retried once through the supported route. An uncertain launch or message must be reconciled first; otherwise record the blocker, owner and next checkpoint. Never create a replacement worker merely to compensate for missing readback.

## 5. Own updates, readback and deliberate waits

Agree the real update contract before dispatch: notification/result API, permitted recipient, durable checkpoint location, cursor, reader, expected checkpoint and stopping conditions. A worker prompt grants no messaging authority. In particular, a tool requiring direct human authorization, such as `send_message_to_thread` where exposed, remains gated. Some workers cannot notify a parent at all; the coordinator owns result readback there.

Reconcile existing source-monitoring ownership before adding work. At bounded checkpoints, use actual connected team-messaging and email readers and supported session routes to read new relevant messages within applicable authority. Preserve source references, original timestamps and authenticated authorship; distinguish human instructions from forwarded or automated text, and reconcile material updates into the current task and decision queue. Reuse the existing authorized monitor/reader rather than duplicate watchers. If a connector or notification route is unavailable, use an authorized existing owner/readback or report the unsupported coverage, next supported checkpoint and its owner. Keep independent authorized work moving. Reading sources or coordinating with a reviewer does not grant blanket replies, external sends, schedules, implementation or account/access changes; never infer continuous coverage or guaranteed delivery.

Reconcile material team-chat/email agreements into the existing canonical task/decision queue. When GitHub is the designated queue, prepare one source-bound comment draft for its authorized writer; publish only with actual scope/authority and current remote readback. No automatic external write or per-tool comment follows from intake.

The independent reviewer supplies scoped findings and source-bound evidence to the primary through a verified, authorized route; execution owners remain unchanged. For logs, suspected missed issues, agent-health observations and GitHub queue reads, use authorized evidence surfaces and label unavailable coverage; reading and reconciliation are distinct from issue/PR writes, and recommendations neither implement themselves nor grant permission. The primary acknowledges receipt, dispositions each finding against the current scope/revision, assigns any authorized correction and verifies its resolution. Keep delivery, acknowledgment, disposition and verified resolution separate. An unresolved finding or failed propagation stays on the existing queue; neither a reviewer message nor its delivery is acceptance or approval.

Use the [independent reviewer/researcher role](skills/agent-coordination/references/independent-reviewer.md) for a scoped outside view on design/grill recommendations, before a release card and after relevant deployment/monitor evidence. This is a review-request checkpoint, not automatic send permission or a mandatory new worker. Reuse the existing owner and actual matching policy/recipient/category/exclusions and supported route; if unavailable, retain a named reader and next bounded check. The reviewer may perform authorized read-only investigation, not implementation or executor takeover. Reconcile its source-bound findings in the canonical queue, preserve positive-review conflicts until resolved, and require disposition and verified resolution separately from delivery. No new schedule, background guarantee, fresh approval for already covered work or user-specific policy is created here.

Prefer supported event waits when available. As a capability-specific example, some local task interfaces expose `read_thread` and `wait_threads`: discover their current schema first. Observed variants allow up to eight targets, per-target cursors and a zero-timeout snapshot; completion or attention may wake a wait while commentary does not, and user input may end it. Inspect per-target errors and read the actual result. These are examples, not universal guarantees or instructions to call an unavailable API.

Without notifications, use authorized supported status/result reads with bounded polling and the backoff/limits in [routing](skills/agent-coordination/references/routing.md). Persist the last consumed cursor and next checkpoint. At resume or a new user turn, reconcile overdue or uncertain work before fresh dispatch. Do not scrape hidden stores, bypass denial, repeatedly nudge deliberate waits or poll indefinitely. A scheduled check needs existing explicit authority and supported setup; this guide creates no schedule. Background monitoring is unarmed unless its actual wake/readback, owner, expiry and closing verdict are verified.

Use the existing [coordinator follow-through projection](skills/agent-coordination/references/state.md#coordinator-follow-through) to reconcile completed results with the current owner, artifact/revision, acceptance, next action and checkpoint. Record assignment, worker acknowledgment, outcome and coordinator readback separately; consume finished review evidence before assigning the next authorized step once or retaining a sourced hold. Read-only status keeps coverage errors and exits nonzero on partial inventory: check its exit before aggregation, and never resume on idle alone.

The current checkpoint interfaces record/stage intents; they do not themselves send or schedule notifications. Verify actual completion/disconnect event and supported readback capability; do not assume a universal idle event or end-to-end delivery. Retain a concrete bounded reader/checkpoint and test dispatch → admission → execution → review → delivered-result receipts separately before claiming the route works.

Consume every material completed worker result and record its disposition. If obligations remain, assign the next authorized action to an exact owner with a checkpoint, or retain a sourced deliberate hold with its reader/next check; completion without that ownership stays open. Close terminally only when the whole scoped outcome and required acceptance/follow-through are verified complete and all obligations are dispositioned, naming the evidence and closure owner. Preserve accepted, delivered, acknowledged and verified distinctions where applicable; a finished turn or delivery receipt cannot substitute for the required state. Explicit terminal closure needs no artificial next assignment.

For an actual authorized deployment or operational config/registry change, retain target-bound execution logs, rollback and required observation/monitor receipts covering the changed scope. A required monitor needs its actual owner, supported wake/readback, task reference and deadline; if unarmed or not authorized, keep that gate pending rather than invent a schedule. A FAIL stays in the shared queue until acknowledged and dispositioned/verified-resolved as required. Source-only configuration work does not automatically need production deployment or a new monitor.

An admission receipt, delivered message, worker acknowledgment, parent disposition and verified resolution are separate facts. Record which happened, with the current revision; readback must match the actual source and result. No notification is a delivery guarantee, and silence is neither progress nor death. If the host cannot continue after the turn, say what is unmonitored and name the next reader/checkpoint instead of promising perpetual work or zero idle time. Stop dependent work at revoked scope, uncertain side effects, ownership conflict, expired capability/monitoring evidence or resource limits; continue unrelated authorized work.

### Independent reviewer checkpoint

Apply [documentation currency](skills/workflow-contracts/behavior.md#documentation-currency): reconcile cross-channel decision evidence and verified changes into canonical links/records through the actual document owner. Review identifies stale/conflicting guidance; workers update scoped docs and return doc-impact evidence or a reasoned not-applicable disposition. Summaries are not approval, and consolidation preserves useful rationale, history and unresolved decisions.

At each authorized reviewer checkpoint, inspect the primary’s actual live inventory and durable checkpoints through supported read-only routes, then reconcile material results against the existing canonical shared queue and resources. State whether coverage actually includes user-owned primary coordinator sessions: a watcher limited to assistant-created workers does not establish that coverage. Mark uncovered or unobserved lanes explicitly. Use the queue schema above and [state](skills/agent-coordination/references/state.md), [decisions](skills/workflow-contracts/decisions.md) and [review evidence](skills/workflow-contracts/references/review-evidence.md); reuse current specs, artifacts, receipts and shared-resource owners instead of creating a parallel tracker or service. Preserve stable IDs, source/revision identity, known owners, next action/checkpoint, dependency and approval state, observation time/coverage and intentional waits. Surface stale tasks, unconsumed results and unresolved or aging decisions, approvals and grill-me questions with their actual age/impact or explicit unknowns; silence alone is not evidence of inactivity.

When private findings conflict with a positive review on the same exact revision, retain the findings and both source receipts in the existing authorized record, preserve sharing restrictions, and reconcile the discrepancy through the responsible owner. A positive status must not erase unresolved evidence or close its dependent acceptance gate.

The reviewer challenges evidence and reports through a supported authorized route; it does not silently take over, reassign work, mutate external systems or start a watcher. A finding does not grant permission. The primary consumes the finding, acknowledges and dispositions it, and verifies the matching resolution/readback in the existing queue; sending or acknowledging a message alone is not closure. Respect current communication authority, reader ownership and bounded checkpoints. Missing read/wake/persistence capability remains a reported gap with a named next reader/checkpoint, never an always-on delivery guarantee or a reason to restart a deliberate wait.

## 6. Preserve traceability and review the same artifact

Use [review/observation evidence](skills/workflow-contracts/references/review-evidence.md) to distinguish actual source intervals and freshness from scheduler/task activity, retain finding ownership through acceptance, and verify optimization/consumer-use claims.

**Release bundling:** every release that ships two or more PRs through a base that requires pull requests is one release branch and one release PR. A single-PR release, the hotfix lane, a direct-push or local mode and a base without the pull-request rule keep their own flow. Never ask a worker to mark an individual member PR ready for release; tell release owners to bundle. Member PRs stay drafts until each is merged into the release branch with its own merge commit (a revert point per PR); conflicts are resolved once, there. Only the release PR is marked ready, after the branch contains `origin/<base>`. Draft PRs skip only the workflows that exclude drafts (verify per repository: `test-diff` does, other required checks may not); never cancel a mandatory or security check, and request no extra runs for member PRs. `test-diff` runs on the combined result and the release PR merges only with no newly failing tests against the base. A PR that breaks the combined run is dropped from the branch and the run repeated. Identity: the landed merge commit is reviewed with `/test-review` before deploy (tree equal to the tested release-branch head), so reviewed and deployed commit are the same. Deploy is that one commit with one deploy-record id, in a gap between send rounds. The board shows the release PR with its members inside it. Before/after check: count CI runs per release from `gh run list` (report measured numbers, not a promised bound); landed tree equals the tested head tree. Cost: a failure in the combined run is attributed by bisect over the merge commits rather than by a per-PR run.

Keep small releases proportionate to risk. Reuse evidence only when bound to the exact artifact/base, relevant paths, dependencies, configuration, toolchain, environment, acceptance criteria, and command. Record why each check is reused or rerun. Changes to those inputs invalidate affected evidence; use focused, impact-driven checks for new or unresolved risk rather than repeating every suite just to refresh status. Retain required canonical aggregate checks and independent review, safety, approval, target-readiness, release, and rollback gates. Satisfy a required check or request a scoped workflow change; never silently skip it. Reused, skipped, blocked, and not-run checks are never newly passed. State remaining checks and their owner so already authorized release steps can proceed promptly. This guidance grants no automatic release or deployment authority.

Name one release owner per actual target; other owners hand it reviewed source. Prefer one release card per target/candidate: exact source and merged SHA/tree, included repository-qualified issues/PRs and their real acceptance gates, tests and independent review on that artifact, readiness/approval states, ordered actions, logs, rollback and required monitors/owners/deadlines (or explicit not-applicable/pending). Prefer a single reviewed command or native permission request only when a safe supported route exists. Keep required split handoffs, action-time approval, user-only steps and safety boundaries; do not collapse them into a generic question or an unreviewed wrapper. A wrapper must be separately authorized, stop on failure and preserve uncertainty. Freeze the presented card's candidate/scope; later changes require affected review/readiness/consent reconciliation, not automatic new authority. Off-main operation requires its actual authorized reconcile-to-main disposition, not a forced main mutation. Source/box-state claims cite actual receipts. Follow issues.md: use `Refs <owner/repo>#<n>` until an issue's stronger gate is met; an implementation-scoped issue may close at its stated implementation/merge gate. Merge alone never discharges actual deployment, monitoring, acceptance or human obligations. No automatic release/deployment authority is added.

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

Worker stop packet (the full return; evidence goes in the task's details file, linked by task-key):

```text
STOP <task-key> <ready|blocked|needs-decision|done|failed> · task <task-id> · deliverable <id> · revision <n> · digest <digest> · next-action <bound action>
Result: <one sentence> [reported|performed|independently verified|unknown] · skills <used/skipped: reason>
Artifact: <repo/branch@full-sha/tree | file+digest> · details <readable reference+digest>
Open: <remaining obligations and their gates, or none>
Need: <exact decision/approval, owner, recommended option and original source; or none>
Next: <owner> by <time> · action <next step> · checkpoint <trigger/time>
```

At every stop (ready, blocked, needs-decision, done, failed), retain the six-line STOP and deliver only through a supported authorized route; do not assume SendMessage exists. If notification is unavailable, leave durable output and a named parent reader/checkpoint without claiming delivery. The bound task/deliverable/revision/digest/next-action tuple stays inline and is repeated in the details file's first block. Details carry exact artifact/source identity, commands/exits/base comparison, failed/skipped/not-run checks, review/decision receipts, separate implementation/merge/deploy/acceptance/follow-through, pending effects and writer/process state. Verify details readability; inaccessible evidence stays unknown while inline facts remain usable. Require consumer readback to match the actual tuple/result/details identity before dependent work. The primary reconciles each consumed result, then its verified record owner updates the ledger/view; neither receipt nor persistence means acceptance.

## 7. Unblock approvals and report accurately

Keep one actionable decision/approval queue from section 2. Each entry names the affected revision, exact pending action/target, original authority or missing decision, consequence, next owner and independent work that can proceed. Do not turn unavailable tools, canceled calls or disconnected compute into a permission denial. Use [approval-handoff](skills/approval-handoff/SKILL.md), the [approval-attempt ledger](skills/agent-coordination/references/approval-attempts.md), and [task approval handoff](skills/agent-coordination/references/tasks.md#approval-handoff).

Check existing authenticated authority first. Relay original evidence through the supported route when allowed; direct-session confirmation needs the actual platform requirement or verified surface mismatch, not a habit. Record the exact denial, pending or uncertain outcome; retry only under the applicable rule and reconcile uncertain effects first. Do not change credentials, security or persistent permissions to unblock work.

Give concise self-contained progress: what changed and evidence level, actual errors/unknowns, the next action and owner, and exactly what the user must decide/approve/do—or `Need from user: None`. Preserve source timestamps and label observation times separately. A pause or resume request is not effective until the execution owner acknowledges the actual state. Do not report a message as consumed or an approval as execution. See [reporting](output-styles/orchestrator.md) and [state](skills/agent-coordination/references/state.md). Use the board in section 2 for user-facing replies.

At substantive checkpoints and handoff, check whether central history is configured and authorized under [Task log](skills/workflow-contracts/contracts.md) and [task-history](skills/task-history/SKILL.md). Route only sanitized material evidence to its existing designated record owner, distinct from the execution owner; workers do not append competing journals. Keep local append, render/index, publication and fresh-reader readback separate, and report gaps without blocking unrelated authorized work. This guidance does not configure or write history. For authorized retrospective improvement, use available [system-audit](skills/system-audit/SKILL.md) or [skill-steward](skills/skill-steward/SKILL.md); proposals are not automatic skill edits or new authority.

## 8. Checkpoint, resume and hand off ownership

Before resuming, bind the active task, owner, source, spec/decision revision and latest evidence cursor; older completed work cannot displace the current request. Inventory actual dirty files, pending tests/processes, uncertain external effects and active monitoring. A handoff starts no worker and grants no takeover authority. Follow [handoff](skills/handoff/SKILL.md) and [human takeover/handback](skills/agent-coordination/references/worker-execution.md#human-takeover-and-handback).

A useful durable packet names the exact worktree, branch, base/head, dirty state and dispositions, reproduction, commands/results, known gaps, authority, next owner and next action. Before releasing a writer, reconcile owned tests/processes and verify the outgoing owner has stopped edits/tests. Record explicit `Handoff RELEASED` only with that actual owner's release receipt; the phrase alone proves nothing. A successor verifies the packet and actual state through supported reads before accepting ownership. Pending or unknown release holds another writer. Preserve separate source-release, runtime adoption and acceptance states.

## 9. Assess archive and cleanup separately

Review parked/completed candidates with the user, using supported inventory and documented host semantics. An archive operation may stop execution or release an environment. Verify its exact target, current owner, recoverable history, durable handoff/acceptance packet, outstanding obligations and reversibility before proposing it. Never archive a user-owned session, assume silence means consent or infer archive authority from completed work. If the route or semantics are unavailable, report the gap and leave it untouched.

Session archive, task closure, worktree removal, branch deletion and environment release are separate actions. Dirty/untracked files, pending work, unresolved acceptance or live environments must have explicit preservation and owner dispositions. Use the read-only [closeout/cleanup eligibility contract](agent_skills/SOURCE-HISTORY-ROLLOUT.md#handoff-completion-cleanup) and applicable project cleanup rules; eligibility is not permission or execution. Do not force-delete, reset, close a live monitor before its verdict or remove a worktree merely to tidy an inventory. This guide performs no archive or cleanup.

Move a row to done only on the whole scoped outcome's evidenced terminal closure or authenticated user disposition; merge/deploy alone is sufficient only if it meets that actual acceptance scope. Record cleanup dispositions separately: session archive, worktree/branch removal and monitor disable are proposed actions with their own owners/authority, not conditions that manufacture endless work. A cleanup batch groups reviewable eligible candidates, never bypasses individual user-only/safety gates or includes user-owned sessions. Preserve dirty, unpushed, live/linked or held resources; pushing or bundling itself needs its actual authority. Existing authorized checkpoints may review idle/merged/past-deadline items; this guide creates no weekly schedule.

## 10. Maintain the guide with the skills revision

Keep canonical rules in the linked contracts, not copied here. When changing a referenced skill, schema, adapter or workflow, assess the affected guide sections in the same reviewed change: update them, or record why they remain accurate in its review evidence. Reconcile the guide against the actual skills revision in the same reviewed change; never relabel old tests, runtime loads or approval receipts as checks of the new revision. Record the guide's exact commit/tree in the task's review packet outside this reusable document.

Validate relative links and meaningful anchors, framework budgets, applicable repository checks and semantic scenarios: startup, underspecified work, missing skills, missed updates, uncertain launch, approval waits, competing writers, handoff, unsafe cleanup and changed-skill maintenance. Independent review must distinguish proposed guidance from supported runtime behavior. Refresh affected source/package/policy evidence; installation, saved-environment publication and loaded-session adoption are separate authorized operations. No automatic updater is installed.

At startup and after compaction, ask: is this the intended task and owner; what source and skills are actually loaded; what is verified versus reported; which independent work is ready; which decisions/approvals remain; who reads the next result; and what is the exact stopping condition? Retrieve details only where they change the next action. The guide describes intended practice, not proof that any historical session complied.
