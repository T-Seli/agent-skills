# Conveyor: the belt

The one home for the belt: roles, lanes, receipts, station contract, limits and sweep. Lanes and receipt formats are machine-readable in [conveyor.json](conveyor.json); standing permissions in `authorizations.json` at the repo root; the numbers in contracts.md § Defaults `Lane limits`. Issue mechanics stay in [issues.md](issues.md); decisions and question rounds in [decisions.md](decisions.md).

## Roles
| Who | Does | Never does |
|---|---|---|
| AI | Thinking and complex building: specs, code, tests, review, judging monitor evidence | Bookkeeping, counting, moving cards by hand, deciding it is approved |
| Scripts | Consistency and tracking: gates, limits, board, records, cleanup checks | Judgment calls |
| The user | Direction, decisions and approvals, all at the coordinator | Typing in workers, chores, housekeeping |

A new rule that is fixed, a count, a state change or a check is a script; one that needs judgment is a skill; a choice of direction or a go is a question to the user.

## Scope
The belt acts only on sessions and worktrees in its own registry (started by the coordinator or `delegate.py`). The user's own side sessions are outside it: never archived, messaged, cleaned up or counted against lane limits. Machine limits (test slots, disk) read real load, so a side session's test run holds a slot like any other.

## Labels
Each open belt issue carries exactly one `lane:<name>`, one `domain:<name>` and, once sorted, one `size:S|M|L`. Priority is `prio:now`, `prio:next` or `prio:later`, separate from the lane `next`. Modifiers: `hold` (no gate moves it forward) and `needs-human` (waits for the user). `ready-for-agent` folds into `lane:backlog`.

## Lanes
Every move is `issues-cli lane <n> <lane>`, which checks the entry rule against receipts and refuses loudly, naming each missing one. Forward moves skip no lane after `next`. A move back (a review NO, a failed deploy) is allowed with a `--reason`, which becomes its receipt.

| Lane | Entry rule: receipts the gate reads | Called at |
|---|---|---|
| `inbox` | `capture`: verbatim text, source link, UTC time | `issues-cli capture` |
| `backlog` | `domain`, `size` labels | the sort pass |
| `next` | owner assigned, `domain`, `Done when:` line; room in `next` | `issues-cli publish` or the sweep's pull |
| `in-progress` | `claim`, `brief`; Build below its limit (the last slot only for `prio:now`) | implement's Start record |
| `in-review` | `implement: done` on a head, a linked PR | implement's done record |
| `ready-to-release` | `Reviewed: <head> YES` where head = the PR's current head, from the independent review | test-review on YES |
| `monitoring` | `Approved:`, `deploy:`, `Rollback:`, two `Scheduler:` ids | deploy, via `safeguard-cli run-approved` |
| `closed` | a final `monitor:` verdict, a `Learned:` line (§ Knowledge) | monitor's end |

## Receipts
Each gate command (`capture`, `prio`, `lane`, `decide`, `brief`, `ask`, `run-approved`) writes one timeline line, on the issue and in the task's `log.md`:

`Conveyor: <UTC time> · <command> · <from> → <to> · head <sha|-> · tests <ref|-> · skills <sha> · schedules <ids|->`

Only commands write these lines. The AI writes only the judgment fields that already exist at a station's record step (What changed, Decisions (why), Watch for). A receipt is never edited: a wrong one gets `Correction: <receipt link> · <field> was <wrong> · is <right>`, and gates read the correction in its place. Formats and patterns: conveyor.json `receipts`.

## Station contract
Same for every skill. **Input:** the issue plus the fixed brief `issues-cli brief <n>` renders (issue body, recorded decisions, the knowledge pages for its `domain:*` label with their verified dates), so a station can be rerun from the issue alone. **Output:** the existing `log.md` entry with its parsed tokens (contracts.md § Task log) plus the skills release sha. **Gate:** `issues-cli lane`, which reads that output.

## Limits and pull
Limits are counted over belt-registry sessions and open belt issues only; numbers in contracts.md § Defaults, which a project's § Defaults may override by the same label. One Build slot stays free for `prio:now`. When `next` has room the sweep pulls from `backlog`: `prio:now`, then `prio:next`, then `prio:later`; inside a level by deadline, then oldest first. The full spec is written only when an item is about to enter `next`. A release train is frozen when its GO is asked; a PR that turns ready later waits for the next train.

## Independent review
The outside reviewer is asked first, and the request time is recorded on the issue. With no verdict on the exact head after `Review fallback` (contracts.md § Defaults), the sweep starts a fresh-context reviewer session running test-review on that head, and its verdict counts as the independent review. A late outside verdict on the same head is still read; a late NO reopens the item (`needs-human` if already released). No session polls.

## Sweep
`issues-cli sweep` reads GitHub, git, disk, test slots, the denial log and the belt registry, and prints the board:
- The count of questions waiting on the user (the opening line of the orchestrator output style), then one line each.
- Lane counts against limits; `Backlog: N (now a · next b · later c) · oldest unsorted Xh`.
- `Coming to you next`: one line per item in `in-review` or `ready-to-release`, so a question is never the first mention of its goal.
- One line per violation: reviewed head ≠ PR head; a lane over its limit; `monitoring` without two schedule ids; `inbox` unsorted over 24 h; a capture spool older than 15 minutes; a review request past the fallback with no reviewer started; a belt session refused, waiting on an unanswered question, or with no result.
- Weekly: `backlog` items over 30 days, as one batch question (keep, drop or bump); question counts against the baseline in decisions.md.
It changes nothing except the pull, spool flush and fallback start, each a receipt.

## Knowledge
§ Map `Knowledge` names stores logically: the brain as `<owner/repo>` and this repo's wiki directory. Each store's local checkout comes from `knowledge_stores` in `~/.config/agent-skills/workers.json`; a missing entry fails loudly. The tool is the Python module `agent_skills.knowledge`, shipped in this release and imported by `issues-cli` (no subprocess); it serves the brain and every wiki alike. Interface (conveyor.json `knowledge`):
- `pages(domain)` for the brief (a domain with no pages is said so) · `find(words)` for sort · `domains()` so `publish` validates the label · `stale()` for the sweep. `pages` and `find` also read `inbox/`, marked pending.
- `record(kind, …)` for `decide` and the `Learned:` collector: one new `inbox/` file per call, never a table edit; only `collect()` edits tables, on demand or daily. Decisions fold without review; lessons, answers and page fixes wait for lint and the local fresh-context review.
- `log(issue, lines)` stores the closed issue's timeline lines verbatim, idempotent per issue, called only by the sweep.
The `domain:*` vocabulary lives in the store's routing table; this file lists none. Close is refused without a `Learned:` line: `none`, `lesson: <text>`, `answered: <question> => <answer>` or `page-fix: <path>: <text>`.

## Permissions
`authorizations.json` is the standing list, one entry per command: `bookkeeping` entries are `allow` and are never asked; `go` entries are `ask` (the user's one click); `deny` entries are refused. `install.sh` renders it into the Claude settings snippet and Codex rules; the user installs it and no session edits settings. Belt commands take no path outside the worktree as an argument: they resolve notes, spool and knowledge locations from config.
