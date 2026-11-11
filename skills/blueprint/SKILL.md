---
name: blueprint
description: 'Look into anything unexplained and decide what to do, read-only: a question, bug, alert or trace gets a short answer; a feature, list or real fix gets one plan. Use for "look into", "why did", "plan this", "don''t edit yet". Not for code review (test-review) or checking a shipped change (monitor).'
argument-hint: "[bug, feature, question, or list]"
---

# Blueprint (look into, then plan)

Answer a question, or turn a problem into one recommended, verifiable plan. **Read-only:** the only file written is Plan mode's `plan.md`. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, draft folders, pending, the chain, consent, report caps and the defaults named below are per it.

For a behavior change in either mode, read `${CLAUDE_SKILL_DIR}/../workflow-contracts/behavior.md`: reconcile the latest user decision and carry the current matrix/source identity, existing capabilities, producer paths, exceptions and decision-brief fields. Apply [current research](../workflow-contracts/references/research.md) for every substantive blueprint in either mode: record the research decision, dynamically retrieve decision-relevant current primary evidence or give a proportional skip reason, and bind its packet to the Answer/spec; explicit research never silently skips.

For UI/frontend or visualization choices, also load [ui-design](../ui-design/SKILL.md): compare distinct directions against the existing product, carry the selected design/research packet into the plan, and preserve unresolved user choices. Offline: compose `company.blueprint company.ui-design`; a Markdown link alone does not load its references.
## Contract
- No repo edits, no git mutations, no state-changing calls (database writes, restarts, deploys, mutating APIs). Reads, read-only queries and logs are fine. Scratch files go in the session scratchpad, else a `mktemp -d` dir removed at the end.
- Something urgent turns up → lead the reply with it and wait. Naming a fix is in scope; applying it is not. Blueprint stays read-only whatever the reply; what runs next, and on which words, is per contracts.md § Chain and § Consent.

## Inputs (first that exists; say which in one line)
1. Args; an issue `#<n>` or its URL is read as the spec per `${CLAUDE_SKILL_DIR}/../workflow-contracts/issues.md`, and `plan.md` records it under the title as `Issue: <owner/repo>#<n>`. 2. A plan for this topic: a pending draft with `plan.md`, or `TASK/plan.md` on the current branch → revise it (**Iterate**). A follow-up `-rN` folder without `plan.md` → **Answer** mode, its regression as the input. 3. The conversation. 4. Discovery: project CLAUDE.md sections, git state, repo docs.

## Mode (picked by the input)
- **Answer**: a question, bug report, alert, or trace of one entity (lead, call, job, record), or any fix whose evidence pins one S change, however many entities it spans. Evidence and a short answer; no agents, no `plan.md`.
- **Plan**: a feature, a list (feedback lists included), a fix that isn't S, or **Iterate**. Scout, architects, `plan.md`.

## Answer mode
1. **State the question** in one sentence. A reported cause is a hypothesis, not a fact.
2. **Gather evidence** yourself: the project's § Observe `Lookup` for the entity, read-only queries per `${CLAUDE_SKILL_DIR}/../workflow-contracts/data-access.md`, logs, the code path. A bug, alert or trace follows `${CLAUDE_SKILL_DIR}/references/bug-mode.md`, Timeline included.
3. **Reply** (Answer report). The fix is S (one obvious change the evidence pins) → end with the `Fix:` line; implement it now if a go-ahead was already given (contracts.md § Consent), else stop for "fix it". The fix isn't S → end with `Fix: needs a plan` and switch to Plan mode, reusing these facts: the scout fills only what is missing.

## Plan mode
1. **State the question** in one sentence. A reported cause is a hypothesis, not a fact. For material ambiguity use `${CLAUDE_SKILL_DIR}/../workflow-contracts/decisions.md`: research facts first, ask prerequisite-ready choices in the owning worker, and preserve settled decisions. Clear authorized work needs no extra interview, except a big implementation (contracts.md § Chain): it runs `/grill-me` first unless one already settled its design, and the settled answers are the chosen approach, so no architects. Found to be L only from the scout's facts: stop and grill before any architect runs.
2. **Classify**: bug · feature · architecture · list (feedback lists use `list`). Pick a `<slug>` and `<type>`.
3. **Scout.** One `scout` sub-agent gathers the facts every architect needs, so no architect re-surveys the repo. Ask for, with `path:line` and proven/inferred marks:
   - where the behavior lives; its callers and callees; who owns its data and config (§ Map, § Tenancy);
   - existing helpers or modules that could be reused or extended;
   - how it is run, tested, deployed and observed (§ Run & test, § Deploy, § Observe);
   - bug: "read `${CLAUDE_SKILL_DIR}/references/bug-mode.md` and follow it";
   - list: items grouped into clusters by shared files or cause, each sized S/M/L.
   Skip the scout only when these facts are already in this conversation.
4. **Architects.** Launch in parallel, in one message. **Cap: `Parallel sub-agents` architects; with the scout, never over 5.**

   | Class | Architects | Angles, one each |
   |---|---|---|
   | bug | 3 | minimal fix · root cause · stress-test |
   | feature | 3 | minimal fix · config-driven & generalized · stress-test (+ redesign if it reshapes a module) |
   | architecture | 4 | minimal fix · config-driven & generalized · redesign · stress-test |
   | list | ≤4 | one per cluster needing a design choice, angle: root cause; S clusters take their fix straight from the scout |

   § Tenancy is `none`: root cause replaces config-driven & generalized. Nothing to choose (one obvious S change the scout already pinned, or an approach the user or brief already chose) → no architects; say so. Use agent type `Plan` (built-in, cannot edit; Codex: a read-only default subagent). Angles:
   - **Minimal fix**: the smallest change that fully solves it.
   - **Root cause**: fix the mechanism, at its most central point.
   - **Config-driven & generalized**: the behavior becomes config or data, so a new tenant or project adopts it with no code edit.
   - **Redesign**: what you would build today, plus the migration path.
   - **Stress-test**: attack the obvious answer (how it fails, what it misses), then propose the version that survives.

   Prompt, with only that architect's angle:
   > You are the <angle> architect: <angle line>. Read-only. Question: <question>. Facts: <scout facts, verbatim>. Work from the facts; open only the files your angle needs and cite `path:line` for anything new.
   > Return ≤250 words under exactly these headings: Approach (≤3 lines) · Files/modules · Adoption (how a new tenant/project turns it on, or "n/a") · System fit (callers, callees, data/config owners) · Risks · Verify (steps, each with a Done when; a fix includes a test that fails before and passes after) · Size S/M/L.

   No status messages between launch and the report; wait for every agent (contracts.md § Report).
5. **Score** each proposal against global CLAUDE.md § Engineering and § Safety.
   - Disqualify any proposal that breaks a rule there. Where § Tenancy lists tenants, also disqualify one whose adoption by a new tenant needs a code, prompt or per-tenant file edit. Its rejection line names the rule.
   - Rank the rest: config-only adoption > fixes the cause at the central point > reuses existing code > smallest change > lowest risk > sharpest verify plan. A narrow request ranks the smallest complete fix first; the generalized version becomes a later item.
   - Pick the top one, or merge compatible parts (e.g., minimal fix now, generalized version as a later item). Stress-test objections that still stand become Risks or Open decisions.
6. **Write** `plan.md` in a new draft folder `$MAIN/.claude/drafts/<date>-<slug>/`:
   ```
   # <title>
   Type: <type> · Slug: <slug> · Class: <class> · Base: <branch, only if not the project's> · Updated: <UTC>
   ## Question
   ## Facts            proven / inferred / unknown, each with path:line or source; current research decision/packet and version fit
   ## Current behavior matrix   identity, existing capability, approved rows, producer paths, exceptions; per behavior.md; include domain terms, decision IDs/sources and observable acceptance per decisions.md
   ## Recommendation   approach, and why it won (a list gets one subsection per cluster)
   ## Changes          file or module → what changes; a prompt: size before → after and the agnostic check (behavior.md § Agent prompts)
   ## Adoption · ## System fit · ## Risks · ## Out of scope
   ## Rejected         one line each: angle — why
   ## Open decisions   question + your default
   ## Verify           Seams (big implementation): <public interfaces tests drive, highest existing first; each: what it catches, what it misses; prior-art test> · Behavior boundary: <where the outcome is observed> · 1. <step> — Done when: <observable check>
   ## Revisions        <UTC> — what changed and why
   ```
7. **Reply** (Plan report), then start action-items per contracts.md § Chain.
8. **Iterate.** When the user refines, edit `plan.md` in place and add a Revisions line; do not fan out again. Re-run architects (reusing § Facts) only when the direction changes: the user rejects the recommendation, or new facts break the question. Re-run the scout only when facts are wrong or missing.

## Answer report (≤5 lines, skeleton per contracts.md § Report)
```
<the answer: what happened, when, why — 1 line>
<≤3 facts, each proven or inferred, with n and timezone>
Fix: <one line> — say "fix it"      (or "Fix: needs a plan"; no fix needed → omit)
```

## Plan report (≤12 lines, skeleton per contracts.md § Report)
```
Working from: <input>
Recommend: <approach> — <why it won>      (≤2 lines)
Rejected: <angle> — <why>; <angle> — <why>
Verify: <the 1–3 checks that prove it works> · Seams: <seams to confirm>
Size: <S/M/L> · Draft: <path to plan.md>
Decide: 1. <question>? Default: <default>   (one line each, or "none")
Next: action-items follows within existing scope; build only dependency-ready items with scoped authority. Resolve material open choices without treating defaults as accepted.
```
Put any `Add to CLAUDE.md § <section>: <fact>` line (for a section the scout had to discover) above `Next:`. Never end on a line that asks for nothing.
