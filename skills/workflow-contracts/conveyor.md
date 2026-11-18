# Conveyor: the belt

The one home for the belt. Lanes, receipts, action records, decision cards and the knowledge interface are machine-readable in [conveyor.json](conveyor.json); standing permissions in `authorizations.json` at the repo root; numbers in contracts.md § Defaults. Issue mechanics: [issues.md](issues.md); question rounds: [decisions.md](decisions.md).

## Roles
| Who | Does | Never does |
|---|---|---|
| AI | Specs, code, tests, review, judging monitor evidence | Bookkeeping, counting, moving cards by hand, deciding it is approved |
| Scripts | Gates, limits, board, records, cleanup checks | Judgment calls |
| The user | Direction, decisions and approvals, all at the coordinator | Typing in workers, chores, housekeeping |

A fixed rule, count, state change or check is a script; judgment is a skill; a direction or a go is a question to the user.

## Scope
The belt acts only on sessions and worktrees in its registry: the two standing sessions (coordinator, release owner) and those started through `delegate.py`. The user's side sessions are outside it: never archived, messaged, cleaned up or counted against limits. Machine limits (test slots, disk) read real load.

## Labels
One `lane:<name>`, one `domain:<name>` and, once sorted, one `size:S|M|L` per open belt issue. Priority `prio:now|next|later` is separate from lane `next`. `hold` stops forward moves; `needs-human` waits for the user. `ready-for-agent` folds into `lane:backlog`. A gate needing a missing belt label creates it (`domain:` values from the knowledge store): additive only, one receipt.

## Lanes
Every move is `issues-cli lane <n> <lane>`: it checks the entry rule (conveyor.json `lanes`) and refuses loudly, naming each missing receipt. Forward moves skip no lane after `next`; a move back needs `--reason`, its receipt.

| Lane | Entry receipts | Called at |
|---|---|---|
| `inbox` | `Captured:` | `capture` |
| `backlog` | `domain`, `size` labels | sort pass |
| `next` | `Owner:` (written by `publish`), `domain`, `Done when:` | `publish`, sweep pull |
| `in-progress` | `Claimed:`, brief; Build below limit (last slot `prio:now` only) | implement Start |
| `in-review` | `implement: done`, linked PR | implement done |
| `ready-to-release` | `Reviewed: <head> YES` on the PR's current head, `Reviewer:` session ≠ `Claimed:` session | test-review YES |
| `monitoring` | `Approved:`, `deploy:`, `Rollback:`, two `Scheduler:` ids | `run-approved` |
| `closed` | first-traffic and 24 h `Monitor verdict:`, both schedules deleted, `Learned:` | monitor end |

## Receipts
Each gate command writes one timeline line on the issue and in the task's `log.md`:

`Conveyor: <UTC time> · <command> · <from> → <to> · head <sha|-> · tests <ref|-> · skills <sha> · schedules <ids|->`

Only commands write receipts; the AI writes only a station's existing judgment fields (What changed, Decisions (why), Watch for). A receipt is never edited: a wrong one gets a `Correction:` that gates read in its place. `decide` needs the question's link and records the calling session. No gate treats `Decision:` or `Asked for more` as a go: the only go is `Approved:`.

## Approvals
`safeguard-cli run-approved <kind> <id> --digest <d>` is the only route for a go. Each kind in conveyor.json `action_record.kinds` maps to one fixed code path; the record carries parameters only, never a command line. The record names the train's issues and heads, tree, targets, preparer, expiry and digest input; it refuses on each `action_record.refusals` reason and writes `Approved:` with the digest and no quoted words.

`skills-install` writes the settings snippet file and never applies it; settings stay the user's manual step. The belt never runs a gated action that has no kind (a production data write, a customer-facing send, a consent or legal change): it stays with the user's own word in the executing session under contracts.md § Consent until a reviewed change adds a kind.

## Questions
Three kinds: bookkeeping (never asked; covered by `authorizations.json`), go and choice. A go or choice carries the card `issues-cli ask <n> --kind go|choice` builds (conveyor.json `card`: ten fields, ≤12 lines; refused with an empty field or when it opens with a PR number or sha). A go card shows its kind, id and the digest's first 8 characters; its undo comes from the Rollback data. "Tell me more" records `Asked for more` and the question returns.

## Station contract
**Input:** the issue plus the brief `issues-cli brief <n>` renders (body, decisions, the domain's knowledge pages with verified dates), so a station reruns from the issue alone. **Output:** the existing `log.md` entry and its tokens (contracts.md § Task log) plus the skills release sha. **Gate:** `issues-cli lane`.

## Limits and pull
Counted over belt sessions and open belt issues only; numbers in contracts.md § Defaults `Lane limits`, overridable by a project's § Defaults. `next` holds at most as many items as Build has free slots. The sweep pulls `backlog` by `prio:now`, `prio:next`, `prio:later`, then deadline, then age; the full spec is written only on entry to `next`. A train freezes when its GO is asked.

## Independent review
The outside reviewer is asked first (`Review requested:`). With no verdict on the exact head after `Review fallback`, the sweep starts a fresh-context reviewer session running test-review on that head; its verdict counts. A late outside verdict is still read; a late NO reopens the item (`needs-human` if released).

## Sweep
`issues-cli sweep` reads GitHub, git, disk, test slots, the denial log and the registry, and prints:
- questions waiting on the user, one line each; lane counts against limits; `Backlog: N (now a · next b · later c) · oldest unsorted Xh`; `Coming to you next` (items in review or ready to release);
- one line per violation (reviewed head ≠ PR head, lane over limit, `monitoring` without two schedules, inbox unsorted >24 h, spool >15 min, review past fallback, a session refused, waiting or silent);
- weekly, backlog >30 days as one batch question, and question counts.

It writes only the pull, spool flush, fallback start and knowledge `log`, each with a receipt.

## Knowledge
`agent_skills.knowledge` ships in this release and is imported by `issues-cli`; it serves the brain and every repo wiki, pointed at a store by config. § Map `Knowledge` holds logical names (brain `<owner/repo>`, wiki directory); checkouts come from `knowledge_stores` in `~/.config/agent-skills/workers.json`. With no mapping for the brain, reads serve the wiki and say `brain: not configured on this machine`; `record` and `log` refuse loudly.

Functions (conveyor.json `knowledge`): `pages`, `find` (both read pending `inbox/` rows), `domains` for `publish`, `record` (one new inbox file), `collect` (on demand or daily; only it edits tables; decisions fold unreviewed), `log` (idempotent, sweep only), `stale`, `lint`.

Lessons, answers and page fixes merge after lint and the local fresh-context review; outside review is off for the brain by config. `domain:*` values live in the store's routing table. Close needs `Learned:` `none`, `lesson: <text>`, `answered: <q> => <a>` or `page-fix: <path>: <text>`.

## Permissions
`authorizations.json` lists each standing action with its tool: bookkeeping is `allow`, a go is `ask` (one click), `deny` is refused. `install.sh` renders it for Claude and Codex; the user installs it, no session edits settings. Belt commands take no outside path: notes, spool and stores come from config.
