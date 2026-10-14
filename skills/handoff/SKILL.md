---
name: handoff
description: 'Write a paste-ready prompt so a fresh session can continue this work: goal, decisions, done vs verified, open questions, key files, git state, next step. Use for "hand off", "new session", "before compacting", or when context is nearly full. Not for briefing (prime-context).'
---

# Handoff

Write one prompt a new session can paste and act on with no memory of this one. Read-only apart from the saved copy. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, `DRAFT`, `TASK`, the handoffs folder and `Handoffs kept` are per it. When a session runs long or compaction nears, offer `/handoff` in one line; run it when the user agrees or asks.

## Inputs (first that exists; say which in one line)
1. Args: the goal or focus to hand off.
2. The task folder → **task mode**: the branch is `<type>/<slug>` and `TASK` exists in this worktree, or a `DRAFT` was written or read this session. Note its last `log.md` heading and which action items are ticked; don't re-read files already in context.
3. The conversation → **conversation mode**: it is the only record, so the block must carry everything.
4. Discovery: git state, always (**Capture git state**).

## Steps
1. **Capture git state.** Run these now, never from memory. Not a git repo → `Git: not a repo`, and skip **Save**.
   ```
   GIT_TERMINAL_PROMPT=0 git fetch --quiet || echo "fetch failed: origin may be stale"
   git rev-parse --abbrev-ref HEAD; git rev-parse --show-toplevel
   git worktree list --porcelain | sed -n '1s/^worktree //p'            # MAIN
   git status --porcelain | wc -l | tr -d ' '                           # uncommitted
   git rev-list --left-right --count "<base>...origin/<base>"           # ahead, behind
   git rev-list --count '@{u}..HEAD' 2>/dev/null || echo "no upstream"  # unpushed here
   git log --oneline -3
   ```
   Name the worktree path only when `--show-toplevel` differs from MAIN.
2. **Sort every claim** into one bucket:
   - done + verified: checked this session against the real thing; cite the command and result;
   - done + unverified: never exercised, or believed but not checked; say how to confirm. Built ≠ deployed ≠ proven;
   - not started.
   Carry the current approved behavior matrix per `${CLAUDE_SKILL_DIR}/../workflow-contracts/behavior.md`, with exact source/artifact identity, producer paths, exceptions and the one owner/next-action pointer. Keep promised replies, holds and manual/customer steps open separately from implementation, deployment and behavior acceptance.
3. **Mark every decision** `(user)` when the user made or approved it, else `(proposed, awaiting user)`; never upgrade one. Abandoned approaches go under Decisions as `Rejected:` with why, so they aren't retried.
4. **Fill the template.**
   - Task mode: line 1 points at the folder. Add only what it lacks: work after its last log entry, unlogged decisions, the half-done item.
   - Conversation mode: fill every section from the conversation. State conclusions reached at real cost (a root cause, a measurement) so they aren't re-derived.
   - Drop empty sections; never pad.
   - A next step that needs the user (deploy, approve, …) is written `awaiting user: <deploy | approve | …>`, never as an order to act.
5. **Check the block.**
   - Length: the whole report fits the handoff cap in contracts.md § Report (lines and words). Over it → cut detail and point to files.
   - Content: no secrets, tokens, customer data or pasted logs and code; reference the file or command instead.
   - Format: no code fences inside; commands go in backticks.
   - Self-contained: no "as discussed"; name every file, branch and command. Verify the destination can read the artifact through its supported surface; otherwise inline essentials and label inaccessible detail. Count the actual block: <=40 lines and <=450 words, including inline matrix rows.
6. **Save** the block's contents to `$MAIN/.claude/drafts/handoffs/<date>-<slug>.md` in both modes (conversation mode: slug from the goal). Read a file of the same name before replacing it. Then keep only the newest `Handoffs kept` files there (`ls -t`), deleting the older ones. Keep `.claude/drafts/` excluded per contracts.md.

## Report (cap per contracts.md § Report)
At most one line of text, the block, then `Saved: <path>` if saved. Nothing else. The near-compaction offer stays one line.

## Template
```
Continue <slug or goal in a few words> in <repo> (<MAIN path>). First: <read <TASK path>/log.md and action-items.md | run `git status` in <worktree path>>. Don't redo anything marked done.
Goal: <one or two sentences: what and why>
Decisions:
- <choice> — <why> (user)
- <choice> — <why> (proposed, awaiting user)
- Rejected: <approach> — <why; don't retry> (user | proposed, awaiting user)
State:
- Done + verified: <change> — <command → result>
- Done + unverified: <change or belief> — confirm by <check>
- Not started: <item>
Open questions for the user: <question — options, which you'd pick> | none
Current contract: <matrix artifact/revision/source identity; approved behavior, exceptions and producer paths; inline essentials if inaccessible>
Open completion conditions: <implementation / deployment / observed behavior / promised manual follow-through; owner, hold and next action>
Key files: <path:line — why it matters>, …
Git (run <UTC time>): branch <name> (<n unpushed | no upstream>) · <base> vs origin: ahead <n>, behind <n> · <n> uncommitted · worktree <path | main checkout>
Recent commits: <sha subject> · <sha subject> · <sha subject>
Next: <one action> — Done when: <observable check> | awaiting user: <deploy | approve | …> — <what they are asked to approve>
Guardrails (max 5, from CLAUDE.md and this session; the user's words verbatim):
- <constraint the next step could break>
```

Central history: when a private task-history checkout is configured, follow `/task-history` for sanitized milestone evidence and handoff. Preserve the project log and existing approval/review gates.
