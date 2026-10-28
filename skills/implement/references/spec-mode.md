# Spec mode: one worker per ticket

Read by `/implement` when the action items are tickets (`Tickets: <n>` in the page header; a big implementation per contracts.md § Chain). This session becomes a thin orchestrator: it keeps the ticket graph, dispatches workers, has merges done by a merger and runs the review. It edits no code and reads no worker diffs. Ticket workers, the merger and the fixer commit as part of this `/implement` run. Workers start per agent-coordination `references/worker-execution.md` § Delegate; their route follows its § Select and pin.

## State lives in files
- Spec: `DRAFT/plan.md`; its `## Verify` names the agreed seams. Tickets: `DRAFT/action-items.md`, one item per ticket with `after #k` edges and acceptance checkboxes. Notes: `DRAFT/notes.md`, exploration facts several workers need. Baseline: `DRAFT/baseline.txt`, the sorted failing test ids from **Setup**. Only the orchestrator writes these.
- Ticket events go to `DRAFT/log.md` (`implement: #<N> merged <short sha>`); a ticket is ticked only after its merge lands. A fresh session resumes from these files, `git worktree list` and `delegate.py status`.
- **Frontier** = open tickets whose `after` tickets are all merged and whose `needs D<id>` decisions are settled.

## Setup
1. **Steps** run as usual through **Start record**. Branch flow: the **Branch** worktree `<type>/<slug>` is the **integration branch**. Trunk flow: take `LOCK` as **Workspace** does for trunk, then create the same integration worktree. Write the full-suite failing ids to `DRAFT/baseline.txt`.
2. Tickets need facts that plan `## Facts` lacks: one `scout` gathers them; save its answer to `DRAFT/notes.md`.

## Dispatch (every frontier ticket)
1. Worktree off the integration tip, then the worktree setup from CLAUDE.md § Run & test:
   `git -C "$MAIN" worktree add --no-track -b <type>/<slug>-t<N> "$MAIN/.claude/worktrees/<slug>-t<N>" <type>/<slug>`
2. Task id `<slug>-t<N>`; the orchestrator writes its contract file (§ Delegate). Brief within contracts.md § Defaults `Spec mode`: the tuple and route line, exclusions and the `Approved:` line inline; for the rest, pointers rather than pasted text: "Read `DRAFT/plan.md`, ticket #<N> in `DRAFT/action-items.md`, `DRAFT/notes.md`; baseline `DRAFT/baseline.txt`" as absolute paths. Then these steps:
   1. Check `git merge-base --is-ancestor <type>/<slug> HEAD`; else stop.
   2. Run `/tdd` for ticket #<N>. Touch only what the ticket needs; anything outside it is a blocker to report, not an edit.
   3. Commit on the ticket branch per § Map's convention: one commit, tests with the code.
   4. Merge the integration tip (`git merge <type>/<slug>`), resolve conflicts within the ticket's scope, then run `Fast tests` once; a failure not in the baseline blocks.
   5. Return within the receipt cap: status, head sha, each acceptance criterion → its test and red line, the Tests line, open questions.
3. `delegate.py start --task-id <slug>-t<N> --contract-file <file> --prompt-file <brief> --cwd <ticket worktree>`, then `delegate.py wait` in the background. Refused for a worker limit: dispatch it after the next receipt; merges go first.

## Merge
- On each `ready` receipt, check every acceptance criterion has a named test that went red then green (a prefactor ticket: the existing tests covering the moved code stay green). Then the **merger** (task id `<slug>-merger`, started on the first merge and resumed with `start --resume` after; it is the only worker in the integration worktree, so merges run one at a time) runs `git merge --no-ff <type>/<slug>-t<N>` and `Fast tests`, compares with the baseline and returns within the receipt cap. The orchestrator then removes the merged ticket worktree without `--force` and deletes its branch with `git branch -d`. A non-trivial conflict or a new failure: it aborts the merge and reports; the ticket goes back to its worker (`start --resume --task-id <slug>-t<N>`).
- Merged: tick it, log it, recompute the frontier and dispatch newly ready tickets at once. A blocked ticket holds only its dependents.

## Review, fix, finish
1. All tickets merged: review per `references/review-axes.md` on the integration branch.
2. Accepted findings go to **one fixer** (task id `<slug>-fix-r<k>`) in a fresh ticket worktree off the integration tip, briefed with the path to `DRAFT/review.md`. It fixes them all, test-first where behavior changes, and merges like a ticket. A test-review NO inside the plan goes to the next fixer round the same way (contracts.md § Chain counts the rounds).
3. **Finish** runs on the integration branch once the merger is idle. Trunk flow: after a **Clean check**, the orchestrator fast-forwards local `<base>` to the integration tip (`git -C "$MAIN" merge --ff-only <type>/<slug>`); this is trunk's usual commit onto `<base>`, nothing is pushed, and anything but a fast-forward stops. Then the orchestrator removes the clean integration worktree (`git worktree unlock`, then `git worktree remove` without `--force`); branch flow leaves it to `/deploy` cleanup. test-review follows per contracts.md § Chain.
4. Worktrees of tickets left unmerged are listed for the user, never removed.

## Stay thin
- Read receipts, never diffs; one log line per ticket event.
- Hand off at contracts.md § Defaults `Spec mode`: run `/handoff` naming `DRAFT`, the frontier and running task ids, then ask the starter (agent-coordination § Roles) for the successor orchestration session with it. Running workers keep going; the new session collects their receipts.
