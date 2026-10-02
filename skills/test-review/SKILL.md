---
name: test-review
description: 'Answer "is this ready to deploy?" for the current work, a PR or a commit range: tests first, then each commit. Says YES, or NO with blockers only; read-only. Use for "ready?", "review PR 12", "review the commits". Not for style cleanups or edits.'
argument-hint: "[tests | PR <n> | PR URL | branch | commit range]"
---

# Test review

Decide one thing: is this ready to deploy? Strictly read-only: no code or test edits, code commits, rebases or merges; fixes go through `/implement`. Its only writes: its log entry (§ Log), and the temp worktrees and test services it makes and removes. First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`: names, `DRAFT`, `TASK`, temp worktrees, record commits, "outside the plan" and the defaults named below are per it.

## Inputs (first that exists; name it and its head sha in one line first)
1. Args: `PR <n>`, `#<n>` or a PR URL → **PR mode**; a branch → it against `UP`; a commit range → those commits. A leading `tests` → **Tests mode**.
2. The current task branch `<type>/<slug>`.
3. The conversation: a branch, PR or range named earlier.
4. Discovery: `HEAD`, ranged per `<flow>` below.

`UP` = `origin/<base>` after `git fetch` (contracts.md § Git); no remote: `<base>`. Range = `$BASE..<head>`, `<head>` = `HEAD` unless an input names one:
- Branch flow, a branch or a PR: `BASE=$(git merge-base UP <head>)` (a PR: its own base in place of `<base>`).
- Trunk flow (`HEAD` on `<base>`): `BASE` = the sha in the newest `deploy:` heading of any task or draft log; else `origin/<base>`; else the newest `Reviewed:` sha, so the range starts at the first commit after it; none: ask for a range and stop.

Empty: say so and stop. Uncommitted changes are not reviewed. PR targets need the git host CLI from CLAUDE.md § Map (read the PR, fetch its head); no CLI: review the branch if it exists here.
Intent per commit: its action item in `TASK/action-items.md` (the log's `implement: <item>` entry names its sha); else the PR body; else the commit message. No approved plan: blocker 6 is skipped.

**Tests mode** (`/test-review tests`): run **Tests** only, then reply with the report's Tests line. No commit review, verdict, log or chain.

## 1. Tests (before reading any code)
One `scout` runs this and returns ≤150 words: commands, pass/fail per side, new failing ids, red/green per fix test. Commands come from CLAUDE.md § Run & test; output per global CLAUDE.md § Verification. Test services only if that section defines them, with resource names and ports unique to this run; tear them down after.
Codex: run these steps in this session itself; its scout is sandboxed read-only.
Temp worktrees (contracts.md): first `git worktree prune` and remove leftovers. Each one this run makes is removed on every exit, stop or error included.
1. **Branch:** reuse implement's logged results when the command matches and `git diff --quiet <logged head sha> <head> -- ':(top,exclude)<tasks>'` passes. Else run the full suite where the head is checked out (else in a temp worktree at it). Record the sorted failing ids.
2. **Base:** reuse logged results for the same base sha and command. Else `git worktree add --detach "$MAIN/.claude/worktrees/_base-$(git rev-parse --short $BASE)" $BASE`, run the setup, copy in the branch's tests if § Run & test says tests are not tracked by git, run the suite, record failures.
3. **New failures** = branch minus base. Rerun each once on both sides; one that flips is flaky, not new.
4. **Fix proof** (branch `fix/…` or any `fix` commit): in the base worktree, `git checkout <head> -- <new or changed test files>` (untracked: copy them) and run only those. Each must fail there on an assertion and pass on the branch. A compile, import or collection error at the base is "not shown".
5. `git worktree remove --force` the temp worktrees.

## 2. Commits
Check each commit (skip record commits) against its intent and callers. Up to `Parallel sub-agents` `scout`s get the range, the intents and § Blockers verbatim, and return only blockers (≤150 words, `<short sha> <path:line> — what breaks, for whom — fix`, or "none"):
- **Callers** (always): callers and consumers of every changed symbol, signature, return shape, table, field or config key; return those the change breaks and any second path for the same data it missed.
- **Safety** (blockers 3–4) and **Scope** (blockers 2, 5, 6): for a range over `Review fan-out above`; smaller, check these yourself.
Open each returned line; keep only listed blockers you can show.

## Blockers
Report only these: no nice-to-haves, style, refactor or dedupe suggestions, no "consider". Unsure whether it is a blocker? It is not: drop it. Greps run over `ADDED` = `git diff -U0 $BASE <head> -- ':(top,exclude)<tasks>' | grep '^+[^+]'`, minus test paths, docs and fixtures; a hit is a lead until you open the line.
1. **Tests:** a new failure vs base, or a fix whose test does not fail on base and pass on the branch.
2. **Wrong or breaking:** the commit does not do what its action item says, or breaks a caller or consumer.
3. **Security:** a secret in code, logs or URLs (`grep -inE "(api[_-]?key|secret|token|passw|bearer|private[_-]?key)[\"']?\s*[:=]\s*[\"'][^\"']{8,}"`, `-----BEGIN`, provider key prefixes, newly tracked env or credential files); PII (phone, email, name, address) sent to a third party or LLM; an auth check removed or bypassable.
4. **Production data:** a script, job, backfill or migration writing to production without asserting its target (writes in normal request handlers are exempt); DDL (`CREATE|ALTER|DROP|TRUNCATE`) outside the migration dirs; a migration that is not idempotent or has no down path; a wrong tenant or database target.
5. **Tenant or environment logic in shared code** (it breaks plug-and-play): a tenant name, alias or id from CLAUDE.md § Tenancy, or `prod|production|staging`, in shared code outside config; branching on either (`grep -nE "(==|!=|===|!==|\bin\b|case|switch).*[\"'](prod|production|staging)[\"']"`, and the same with tenant names); a hard-coded tenant value or list; a per-install name in shared content (prompts, templates, copy). § Tenancy `none`: environment names only.
6. **Unplanned:** anything outside the plan (compare `git diff --name-only $BASE <head>` with the plan and action items).

## Log
Entry `test-review: <YES|NO>` per contracts.md, holding `Reviewed: <head sha> <YES|NO>` and the Tests line.
- PR mode: append to `$MAIN/.claude/drafts/<date>-pr-<n>/log.md` (the newest existing `drafts/*-pr-<n>/` if any), so `/deploy` finds it. No commit.
- `TASK` on the branch: append to `TASK/log.md` and make a record commit of only that file, subject `review <slug>`.
- Otherwise: append to `DRAFT/log.md`.

## PR mode
Same review for a PR, plus its summary line in the report and its own log (§ Log). Post the report as a PR comment only if the user asks; never approve or request changes.

## Report (readable markdown for someone who hasn't seen the code; never a fenced block)
Print it in full before any other action (the log entry, a deploy the user already asked for, the implement loop). Caps per contracts.md § Report. These lines, in order; nothing else:

1. PR mode only: **What it does:** two plain sentences, the problem and then the change, from the PR body and diff.
2. **Ready to deploy: YES.** or **Not ready to deploy: <k> blocker(s).** plus a short clause, e.g. "each needs a small fix".
3. NO only, one line per blocker: **<n>. <what breaks, as a plain headline>.** What happens, for whom, and the evidence (test output, live data with n, a line you opened) · [<path>:<line>](<path>:<line>) (plus the short sha when the range has more than one commit) · Fix: <one line>
4. **Tests:** <n> pass on the branch. New failures vs `<base>`: <k> (name them, or "none"). <m> other failures also fail on base. Fix proof: <ok | n/a (why) | not shown: <test>>. Clean: <the checks that found nothing, e.g. callers, secrets, tenant logic, scope>.
5. **Next:** YES: deploying now (go-ahead given) or "say deploy". NO: what happens next per contracts.md § Chain.

Then write the log entry, then follow contracts.md § Chain: YES → deploy if a go-ahead was given, else ask once; NO → the implement loop.

Use a fenced, paste-ready block only when the user asks for one (e.g. to post as a PR comment).
