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
1. **Capture git state.** Run these now, never from memory. Not a git repo → `Git: not a repo`, drop `Recent commits`, and skip **Save**.
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
3. Carry the active deliverable and current question frontier per `${CLAUDE_SKILL_DIR}/../workflow-contracts/decisions.md`: settled/open IDs, dependencies, source/revision, owner and verified session route. Older completed handoffs remain historical and cannot replace the active request. **Mark every decision** `(user)` when the user made or approved it, else `(proposed, awaiting user)`; never upgrade one. Abandoned approaches go under Decisions as `Rejected:` with why, so they aren't retried.
   Carry the route and session: source session and its single owner; requested model/effort (and ceiling); observed model and effort, or `unknown` when the host doesn't expose them (never copy the requested value); the environment readiness receipt (environment, auth context, ref, age), missing access and limits. `Session:` says `fresh` by default: the next session never resumes, continues or takes over a session owned elsewhere. Write `authorized resume` only when the single owner resumes its own session under recorded authority, naming both. When the user takes over, write `human takeover` with the documented route, continuity (same session, local copy or diff only), exact ID kind, the user's command and checks, and the release state from agent-coordination worker-execution.md § Human takeover and handback; a pending or unknown state means the assistant still holds the writer role and the user waits. A handoff starts no new workers.
4. **Fill the template.**
   - Task mode: line 1 points at the folder. Add only what it lacks: work after its last log entry, unlogged decisions, the half-done item.
   - Conversation mode: fill every section from the conversation. State conclusions reached at real cost (a root cause, a measurement) so they aren't re-derived.
   - Drop empty sections; never pad.
   - A next step that needs the user (deploy, approve, …) is written `awaiting user: <deploy | approve | …>`, never as an order to act.
5. **Check the block.**
   - Length: the whole report fits the handoff cap in contracts.md § Report (lines and words). Over it → cut detail and point to files.
   - Content: no secrets, tokens, customer data or pasted logs and code; reference the file or command instead.
   - Format: plain text only, because the block is often pasted after a command, which rejects anything else: no code fences, backticks, bold or other inline formatting, no links or URLs, no @-mentions, and no word that starts with "/" (write paths as ~/… or repo-relative). Put commands in double quotes.
   - Self-contained: no "as discussed"; name every file, branch and command. Verify the destination can read the artifact through its supported surface; otherwise inline essentials and label inaccessible detail. Count the actual block: <=40 lines and <=450 words, including inline matrix rows.
6. **Save** the block's contents to `$MAIN/.claude/drafts/handoffs/<date>-<slug>.md` in both modes (conversation mode: slug from the goal). Read a file of the same name before replacing it. Preserve older handoffs; retention cleanup needs separately authorized scope. Keep `.claude/drafts/` excluded per contracts.md.

## Report (cap per contracts.md § Report)
At most one line of text, the block, then `Saved: <path>` if saved. Nothing else. The near-compaction offer stays one line.

## Template
```
Continue <slug or goal in a few words> in <repo> (<MAIN path as ~/…>). First: <read <TASK path>/log.md and action-items.md | run "git status" in <worktree path>>. Don't redo anything marked done.
Goal: <one or two sentences: what and why>
Active request: <latest authenticated instruction/source/revision; historical completed work excluded>
Decisions:
- <choice> — <why> (user)
- <choice> — <why> (proposed, awaiting user)
- Rejected: <approach> — <why; don't retry> (user | proposed, awaiting user)
State:
- Done + verified: <change> — <command → result>
- Done + unverified: <change or belief> — confirm by <check>
- Not started: <item>
Decision frontier: <settled/open IDs, prerequisites, sources; supersedes old choice only within named scope>
Open questions for the user: <question — options, which you'd pick; understanding is not execution approval> | none
Current contract: <matrix artifact/revision/source identity; approved behavior, exceptions and producer paths; inline essentials if inaccessible>
Open completion conditions: <implementation / deployment / observed behavior / promised manual follow-through; owner, hold and next action>
Key files: <path:line — why it matters>, …
Route & access: source <session> owned by <owner> · requested <model>/<effort> (ceiling <effort | none>) · observed <model | unknown>/<effort | unknown> · environment <id>, auth context <ref>, readiness <ref, age | none> · missing: <list | none> · limits: <list | none>
Session: fresh (owner <owner> keeps <session>; do not resume, continue or take it over) | authorized resume of <session> by its owner <owner> (<authority ref>) | human takeover of <session> (<route>, <continuity>; run "<command>" after <checks>; state <pending | released | handed back>)
Git (run <UTC time>): branch <name> (<n unpushed | no upstream>) · <base> vs origin: ahead <n>, behind <n> · <n> uncommitted · worktree <path | main checkout> | not a repo
Recent commits (git repos only): <sha subject> · <sha subject> · <sha subject>
Next: <one action> — Done when: <observable check> | awaiting user: <deploy | approve | …> — <what they are asked to approve>
Guardrails (max 5, from CLAUDE.md and this session; the user's words verbatim):
- <constraint the next step could break>
```

Central history: when a private task-history checkout is configured, follow `/task-history` for sanitized milestone evidence and handoff. Preserve the project log and existing approval/review gates.
