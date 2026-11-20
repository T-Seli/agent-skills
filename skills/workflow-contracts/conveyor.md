# Conveyor: the belt

The one home for the belt. Lanes, receipts, records, cards, feeds, flow and knowledge are machine-readable in [conveyor.json](conveyor.json); standing permissions in `authorizations.json` at the repo root; numbers in contracts.md § Defaults. Issue mechanics: [issues.md](issues.md); question rounds: [decisions.md](decisions.md).

## Roles
| Who | Does | Never does |
|---|---|---|
| AI | Specs, code, tests, review, judging monitor evidence | Bookkeeping, counting, moving cards by hand, deciding it is approved |
| Scripts | Gates, limits, board, records, cleanup checks | Judgment calls |
| The user | Direction, decisions and approvals, all at the coordinator | Typing in workers, chores, starting sessions |

A fixed rule, count, state change or check is a script; judgment is a skill; a direction or a go is a question to the user.

## Scope and registry
The belt acts only on its registry: the sessions named in `Owner:` and `Claimed:` receipts on belt issues, open or closed, as `local_<uuid>` for a desktop session or a plain uuid for a headless worker, which ends by itself and is never archived (conveyor.json `registry`). A guard allows a session none of whose belt issues is open and unparked, denies one with such an issue, and asks about a session no belt issue names; it searches by id, never lists every issue.

## Labels
One `lane:<name>`, one `domain:<name>`, one `kind:<name>` and, once sorted, one `size:S|M|L` per open belt issue. Priority `prio:now|next|later` is separate from lane `next`. `hold` stops forward moves; `needs-human` waits for the user; `parked` and `stalled` free the slot. A gate needing a missing belt label creates it: additive only, one receipt.

## Lanes
Every move is `issues-cli lane <n> <lane>`: it checks the entry rule and refuses loudly, naming each missing receipt. Forward moves skip no lane after `next`; a move back needs `--reason`.

| Lane | Entry receipts | Called at |
|---|---|---|
| `inbox` | `Captured:` | `capture`, `feed` |
| `backlog` | `domain`, `kind`, `size` labels | `issues-cli sort <n>` (`--dry-run` prints) |
| `next` | `Owner:`, `domain`, `Done when:` | `publish` |
| `in-progress` | `Claimed:`, brief; size S or M; Build below limit | implement Start |
| `in-review` | `implement: done`, linked PR | implement done |
| `ready-to-release` | `Reviewed: <head> YES` on the PR's head, `Reviewer:` ≠ `Claimed:` session | test-review YES |
| `monitoring` | `Approved:`, `deploy:` (or `Pushed:` where every Deploy target is a branch), `Rollback:`, two `Scheduler:` ids | `run-approved` |
| `closed` | both `Monitor verdict:` lines, both schedules deleted, `Learned:`; or `No release:` and `Learned:` when nothing landed | monitor end, `close` |

## Receipts
Gates read receipts only from the issue: body, labels, linked PR and comments. A command that writes a `log.md` line also posts it on the issue; `lane --log <log.md>` copies a stage's lines there before checking. `run-approved` posts its lines on every train issue. Each gate command also writes one timeline line:

`Conveyor: <UTC time> · <command> · <from> → <to> · head <sha|-> · tests <ref|-> · skills <release id> · schedules <ids|->`

Only commands write receipts; the AI writes only a station's judgment fields. A receipt is never edited: a wrong one gets a `Correction:`. No gate treats `Decision:` or `Asked for more` as a go: the only go is `Approved:`.

## Approvals
`safeguard-cli run-approved <kind> <id> --digest <d>` is the only route for a go. Each kind maps to one fixed code path; the record carries parameters only, including the targets' current refs as `rollback`, inside the digest. It refuses on each `action_record.refusals` reason, `not-ready` included (a train issue not in `ready-to-release` on its PR head). `release` merges and pushes branches and writes `Pushed:`, never `deploy:`; any other target is refused until a project names deploy targets. A failure after the claim appends `Failed:`.

`skills-install` runs from an export of the recorded tree and writes the settings snippet file, never applying it. The belt never runs a gated action that has no kind (a production data write, a customer-facing send, a consent or legal change): it stays with the user's own word in the executing session under contracts.md § Consent.

## Questions
Three kinds: bookkeeping (never asked; `authorizations.json`), go and choice. `issues-cli ask <n> --kind go|choice` writes the ten-field `detail` to the issue and prints the `short` form (conveyor.json `card`): one plain question, at most three sentences and 45 words, one link; no issue or PR numbers, commit ids, branch names, field labels or test counts.

A go's kind, id and digest prefix show in the detail and the permission dialog. "Tell me more" records `Asked for more` and opens the detail. An unanswered card never decides; past its box it stays first on the user's list.

## Station contract
**Input:** the issue plus the brief `issues-cli brief <n>` renders (body, decisions, the domain's knowledge pages with verified dates). **Output:** the existing `log.md` entry and its tokens (contracts.md § Task log) plus the release id. **Gate:** `issues-cli lane`.

## Flow
Limits, time boxes and the train timetable are in contracts.md § Defaults, counted over the registry only. The sweep names the next items by `prio:now`, `next`, `later`, then deadline, then age; `publish` moves them and writes the full spec. Drain before fill: Build pulls nothing while Review is full. `issues-cli dispatch [--dry-run]` starts owned `next` items ([issues.md](issues.md)).

`issues-cli park <n> --until <date|event:name> --why <text>` writes the hand-over, frees the slot and sets `parked`; the sweep un-parks it when due. Past its time box with no receipt it is `stalled`; neither counts toward a limit. L is split before Build; after 2 NO reviews the next step is a choice card.

## Feeds
Each source is one entry in conveyor.json `feeds.entries`; the project's `feeds.json`, then the machine config's `feeds`, override it by id. A scheduled small-model run fetches and pipes rows to `issues-cli feed <id>`, which keys, dedupes, captures and never closes; a disabled feed refuses.

## Sweep
`issues-cli sweep` reads GitHub, git, disk, test slots, the denial log and the registry (a worker is `working` only while a job runs), and prints questions waiting on the user, lane counts against limits, the backlog line, `Coming to you next`, parked items with age, one line per violation, and the weekly batch. It writes only the un-park, stall mark, spool flush, fallback start (at most one per sweep, none without a free test slot) and knowledge `log`, each with a receipt.

## Independent review
The outside reviewer is asked first (`Review requested:`). With no verdict on the exact head after `Review fallback`, the sweep starts a fresh-context reviewer; its verdict counts. A late NO reopens the item (`needs-human` if released).

## Knowledge
`agent_skills.knowledge` serves the brain and every repo wiki; checkouts come from `knowledge_stores` in `~/.config/agent-skills/workers.json`. With no brain mapping, reads serve the wiki and say `brain: not configured on this machine`; `record`, `collect` and `log` refuse loudly; `decide` still writes `Decision:` on the issue and the sweep records the row once mapped. The module owns all git in a store: callers read history through `changes`. Close needs `Learned:` `none`, `lesson: <text>`, `answered: <q> => <a>` or `page-fix: <path>: <text>`; outside review is off for the brain.

## Long-lived sessions
`issues-cli resume` prints the board plus changes since the last `Checkpoint:` line, which it writes (conveyor.json `resume`). SessionStart hands it to the sessions in machine config `roles`; PreCompact prints it for the summary. After a compaction the board outranks the summary.

## Layout and permissions
Installed code finds contract data and the release id only through `agent_skills.layout` (conveyor.json `layout`). `authorizations.json` lists each standing action: bookkeeping `allow`, a go `ask`, `deny` refused; `install.sh` renders it for Claude and Codex and the user installs it.
