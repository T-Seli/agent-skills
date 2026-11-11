---
name: tdd
description: 'Build one ticket or fix test-first: red, then green, one vertical slice per cycle, tests only at the plan''s agreed seams. Implement uses it for every code item and each ticket worker runs it. Use for "TDD", "test-first", "red-green". Not for reviewing, or for adding tests after the code.'
argument-hint: "[ticket ref or behavior]"
---

# TDD (red → green, one slice at a time)

Git is not a prerequisite for test-first code work; bind non-Git baseline/source evidence and allowed artifact paths per [portable execution proof](../workflow-contracts/references/execution-proof.md). An infrastructure/import failure is still not behavior-red proof.

First read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`. The rules below make the loop produce tests worth keeping; apply them on every cycle, not after.

## Inputs (first that exists; say which in one line)
1. Args: a ticket (`<draft folder>/action-items.md #<N>`) or a behavior.
2. The ticket named in the brief or the current action item, with its plan's `## Verify` seams.
3. The conversation.
4. Discovery: the current branch's draft folder (contracts.md § Folders).

A **seam** is the public interface a test drives: you observe behavior there without reaching inside. Test only at the seams the plan agreed. A plan without seams: use the nearest public interface the existing tests already drive. A ticket that needs a new seam: a worker reports it as a blocker, since it is outside the plan (contracts.md § Plan scope).

## A good test
- Drives behavior through the public interface at an agreed seam and survives a refactor that keeps behavior. Its name says what the caller gets, not how.
- Takes expected values from an independent source: a known literal, a worked example, the plan or ticket. Never recompute them the way the code does.
- Mocks per global CLAUDE.md § Verification, never the project's own modules; time and randomness are passed in, not mocked.
- Uses the plan's domain terms.

## Anti-patterns (each means rewrite the test)
- **Implementation-coupled:** mocks internal collaborators, tests private functions, asserts call counts or order, or verifies through a side channel (reading a table instead of reading back through the interface).
- **Tautological:** passes by construction: the expected value is the same computation, a constant compared with itself, or output captured from the code under test.
- **Horizontal:** all tests first, then all code. Tests written ahead verify imagined behavior and lock in structure before the code teaches you anything.

## Loop
1. **Red.** One test for the next acceptance criterion or behavior. Run it with the one-test or one-file command from § Run & test (none: the smallest command it lists). It must fail on an assertion, for the reason you expect; an import, compile or collection error is not red. Keep the failure line. Deliberately breaking completed code proves mutation sensitivity, not that this test preceded the implementation; label it separately. Missing red evidence remains unverified rather than being reconstructed as a worker receipt.
2. **Green.** Only enough code to pass it: no branches, parameters or features for later tests.
3. Rerun the file: the new test and the earlier ones pass.
4. Next criterion → **Red**. For a bug, the reproducing test is the first red.

- One seam, one test, one minimal change per cycle.
- Refactoring is not part of the red → green cycle. Do it once the item is green, behavior unchanged, tests kept green; in spec mode a prefactor ticket or the review's fixer does it. Exception: a test that cannot go green without it, kept to that need.
- Stuck at one red after `Attempts before blocked` tries: stop, keep the failing test and its output, report it.
- Every criterion green: run § Run & test `Fast tests` once (a ticket worker: after merging the integration tip) and compare failing ids with the baseline your caller recorded (none recorded: run the full suite on the base first).

Inside `/implement` its log entry carries this report. Standalone, append `tdd: <ticket or behavior>` per contracts.md § Task log.

## Report (≤5 lines)
```
Built <ticket or behavior>: <n> slices, each red → green
Criteria: <criterion → test, red line>; …   (each criterion once, semicolon-separated)
Tests: <fast tests result>; vs baseline: no new failures | new: <ids>
Seams: <seams used> · new seam needed: none | <proposal>
Not done: <criterion — why>        (omit if none)
```
