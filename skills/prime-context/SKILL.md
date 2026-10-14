---
name: prime-context
description: 'Where are we: read-only briefing on this repo''s git state, work in flight and the newest handoff, in 10 lines or fewer. Use at session start, after compaction, or for "where are we", "get up to speed". Not for production data or why something happened (blueprint).'
---

# Prime Context

Brief a fresh session on this repo's state and its tasks: never production data. **Read-only:** writes no file; no checkout, stash, pull or push. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, the section list, pending, stale, handoffs and `LOCK` are per it.

## Inputs (first that exists; name it on the Repo line)
1. Args: a topic to focus the briefing on.
2. The task folder for the current branch (`TASK`).
3. The conversation: skip anything already in context; never re-read a loaded file.
4. Discovery: the steps below.

## Steps
1. **Project CLAUDE.md** is already in context; don't re-read it.
   - Check for each section in the contracts.md list. List the missing ones.
   - For deployment-related work, perform contracts.md's read-only deployment-readiness preflight at task entry/resume; include its per-check status and material gaps in Gates/Flags. Unknown or blocked deployment readiness does not stop independent authorized read-only work.
   - Pull out hard gates: authorization rules, forbidden operations, named constraints.
   - If `AGENTS.md` is more than a pointer, read it for gates. Note project `.claude/skills/` that add to or shadow the global skills.
2. **Git state.**
   - If the session-start git snapshot is in context, use it for branch, `<base>` vs origin, dirty count and pending drafts.
   - Always run `git rev-parse --short HEAD; git worktree list`.
   - No snapshot → also run:
     ```
     git fetch --prune --quiet
     git rev-parse --abbrev-ref HEAD; git status --porcelain | wc -l
     git rev-list --left-right --count "<base>...origin/<base>"      # ahead, behind
     ```
3. **Tasks in flight.**
   - Last log entry on every branch that carries a task folder (skip when `<tasks>` is `none`):
     ```
     for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
       for f in $(git diff --name-only "<base>...$b" -- ':(top)<tasks>' | grep '/log\.md$'); do
         echo "$b $f: $(git show "$b:$f" | grep '^## ' | tail -1)"; done; done
     ```
   - Pending drafts: from the snapshot, else list `$MAIN/.claude/drafts/` (not `handoffs/`); note which hold `plan.md`, `action-items.md`, or only `log.md`.
   - Newest handoff: `ls -t "$MAIN/.claude/drafts/handoffs/"*.md 2>/dev/null | head -1`, with its first line. Never list handoffs as pending or stale.
   - **Stale** (contracts.md), listed for the user to decide, never deleted: a draft folder where `find <folder> -type f -mtime -<window in days>` prints nothing; a task worktree whose branch's last commit (`git log -1 --format=%cr <branch>`) is older than the window; a stale `LOCK` (age from its `owner` line).
4. **Memory.** If a memory index is in context, pick ≤3 entries that touch the tasks in flight or recent commits. They are leads, not facts. None → the Memory line says `none`.
5. **Map.**
   - § Map present: spot-check with `ls` that the paths it names exist. All present → use it; no sub-agent.
   - § Map missing, or it names paths that are gone → launch one `scout` in the foreground and wait for it: "Map this repo for a new engineer: what it does, top-level directories and what each owns, entry points, how to run and test it and where that is defined. ≤300 words, no code."
   - § Run & test missing and no scout ran → read the run/test command from the repo's build manifest or README yourself.
6. **Report once**, after the scout (if any) returns; no second briefing. The skill ends there and starts no work; the user's next request routes per contracts.md § Chain.

## Report (cap per contracts.md § Report)
Stale and Memory always print, `none` when empty; drop any other empty line.
```
Repo: <name> — <what it does, one line> · from <input>
Branch: <branch> @ <sha> · <n> uncommitted · <base> vs origin: <in sync | ahead n, behind n> · Worktrees: <path → branch>, … | none
In flight: <branch> — <last log heading>; …     (newest first, max 3)
Pending: <date>-<slug> (plan | plan + items | items | log), … | none · Handoff: <path> — <its first line> | none
Stale: <item — age>, … (yours to keep or remove) | none
Memory: <≤3 entries, marked unverified> | none
Run & test: <command> · Deploy / Observe: <one phrase each, or "missing"> · Gates: <hard gates>
Flags: <on <base> with edits, behind origin, a worktree or branch that collides with likely work, docs that contradict>
Add to CLAUDE.md § <section>: <fact discovered>; … · Missing, not discovered: § <section>, …
Next: <the in-flight step, from its log or the handoff> | what are we working on?
```

Central history: when a private task-history checkout is configured, follow `/task-history` for sanitized milestone evidence and handoff. Preserve the project log and existing approval/review gates.
