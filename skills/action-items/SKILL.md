---
name: action-items
description: 'Turn a plan or a pasted list of feedback or tasks into a numbered checklist, each item sized, ordered and with a done-when check. Runs by itself after blueprint. Use for "action items", "checklist", "what do I need to do". Not for shortening an answer.'
argument-hint: "[text, file path, or \"plan\"]"
---

# Action Items

Turn the source into items the user can approve and tick off, and that `/implement` can execute one commit each. **Read-only:** the only file written is `action-items.md`, and only when the source is a plan. **No sub-agents, ever.** First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names and draft folders are per it.

## Inputs (first that exists; standalone: say which in one line)
1. Args: pasted text, a file path, or `plan`.
2. The plan draft for this task, when blueprint started this skill (per contracts.md § Chain) or the user refers to the plan: `plan.md` in its draft folder.
3. A feedback or outstanding list the user pasted earlier in the conversation.

## Build the items
1. Pull every action out of the source, excluding its Out of scope section. Add none of your own: if the source doesn't say how to fix something, write "Fix not decided yet" and list it under Decisions.
2. Size by work, not importance. **S**: one obvious change. **M**: needs a why and a check. **L**: several parts, or more than a day: give it 2–5 steps; more than 5 → split it into items.
3. Order by dependency, then value. Per `${CLAUDE_SKILL_DIR}/../workflow-contracts/decisions.md`, use meaningful behavior slices carrying the decision/spec revision, owner and prerequisite IDs; unresolved decisions block only dependent slices.
4. Code items keep the paths from the source; `/implement` needs them. Tag an item `parallel-safe` when no other open item touches its files. A bug's reproduction test and its fix are one item. For a wide mechanical migration, consider expand, migrate in bounded batches, then contract; preserve compatibility and dependency checks at each boundary.
5. Every item and step gets a `Done when` that a person or a test can check. "It works" is not a check.
6. **Tickets** (a big implementation, contracts.md § Chain): add `Tickets: <n>` to the page header, and every item is a ticket:
   - A tracer bullet: a narrow but complete path through every layer it touches (data, logic, interface, tests), demoable or testable on its own. Never one horizontal layer ("all migrations", "all tests").
   - Sized for one fresh worker context: the plan, the ticket and the files in `Where` are all it needs to read. No L tickets: split them. Prefactoring ("make the change easy") is its own first ticket; its acceptance is the existing tests staying green.
   - `after #k` lists only the tickets that truly block it; number tickets blockers first. `parallel-safe` is dropped: each ticket gets its own worktree.
   - `Done when` becomes acceptance checkboxes, one per behavior, each observable at a seam named in the plan's `## Verify`.
7. For behavior changes, carry the current approved matrix/source identity per `${CLAUDE_SKILL_DIR}/../workflow-contracts/behavior.md`; retain existing capabilities, producer paths, exceptions and per-task approval boundaries. Split implementation, deployment, observed behavior and promised manual follow-through into their relevant completion checks. Keep unsent replies, holds and deferrals open with their owner and next action.

## Item format
```
- [ ] **<N>. <What to do, as a plain verb phrase>** · <S|M|L> · after #<k> · needs D<id> · parallel-safe
  - Why: <the problem in one sentence, with a real example from the source if it has one>
  - Where: `<path or module>`
  - Done when: <observable check>
    - [ ] <step> — Done when: <check>          (L items only)
```
Drop what doesn't apply: `Where` only for code, `after` only when something blocks it. An obvious S item can be the title line plus `Done when`.

## Page
```
Revision: <plan/source revision> · settled <decision IDs> · open <decision IDs> · owner <existing owner>
<1–2 sentences: how many items, which are quickest, anything urgent.>

<items; group under short bold headers only past ~6 items>

**Decisions / blockers**            (only if there are any)
- [ ] Decide <k>: <choice> (default: <x>)
- [ ] Ask <who>: <question>
```

## Writing rules
- Plain words for someone on a phone who hasn't seen the code; one sentence per line. Paths are the only jargon allowed, and only in `Where`.
- Examples must be real (a date, an input, what actually happened). Never invent one; drop it if the source has none.
- On a re-run, reconcile the latest authenticated decision before preserving old scope. Keep numbers and verified completion; revise superseded items with their decision source, retaining deferrals and holds. Tick only the condition actually satisfied; an implementation check cannot tick an unsent reply or unobserved behavior.
- Don't start the work.

## Report
Source is a plan: write the list to `action-items.md` next to `plan.md` (overwrite your own earlier version, keeping its numbers). Otherwise: chat only. Then one of two outputs:
- **After blueprint** (started per contracts.md § Chain): print only the summary line without its suffix, then the numbered decisions (`<k>. <choice> — default: <x>`; tickets add `Breakdown: <n> tickets, frontier #<ids>: are the blocking edges right, and should any be merged or split? — default: as written`), then name open `D<id>` choices and held items. Say `building now` only for ready items already authorized; otherwise ask approval for the specifically ready scope. Never treat a default as an answer. Nothing else; the list stays in the file.
- **Standalone** (a pasted list, a file, or "action items"): the page, then the summary line last, within the action-items cap in contracts.md § Report. Over it → drop `Why` lines, then collapse S items to their title line.

Summary line: `<n> items (<x> S, <y> M, <z> L) · <path written | chat only>`, plus ` · building now` or ` · say "approved" to build` when the source is a plan.
