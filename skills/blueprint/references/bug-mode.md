# Bug mode: evidence first

Whoever gathers bug evidence reads this file: blueprint itself in Answer mode, the scout in Plan mode. Return the items below alongside the usual answer.

## Timeline (Answer mode: one entity, alert or incident)
Find the entity with the project's § Observe `Lookup`; read-only queries (per `workflow-contracts/data-access.md`), logs and the code path only.
- **Events, in order**, one per line: `<time> — <what happened> — <source>` (row id, log line or `path:line`). All times in one timezone, named once.
- **What happened · when · why**, one line each, each marked proven or inferred.
- **n** for any claim about more than one record (e.g. "3 of 40 calls since 09-28 UTC"). An empty result proves nothing: say what was searched, where and over which window.
- **Others hit:** other entities on the same path, with n, or "not checked".
- **Fix:** the one change the evidence pins, its size S/M/L, or "no fix needed".

## Return (both modes)
1. **Reproduction.** The smallest input, steps or query that shows the symptom, with observed vs expected output. Not reproducible → say so, and what access would make it so.
2. **Trace.** The chain trigger → mechanism → symptom, read end to end through the code path, one `path:line` per link.
3. **Since when, and who else.** First bad commit or date if findable (`git log -S`, `git blame`); other callers that hit the same path.
4. **One ruled-out alternative.** The next most plausible cause, and the evidence against it.

## Evidence ladder
Prefer, in order: the code path read end to end > raw data (logs, query rows, timestamps) > derived artifacts (summaries, dashboards, status labels, LLM-written fields, prior write-ups). A derived artifact is a claim about the data; fetch the underlying record before resting a conclusion on it.

## Traps
- **Correlation as cause.** Two things moving together is not a mechanism. Name the mechanism or mark it inferred.
- **Conflation.** Two tenants, environments, code paths, or IDs from different namespaces treated as one. Check that identifiers share a namespace before joining on them.
- **First plausible story.** Not root cause until an alternative is ruled out.
- **Mixed clocks.** Log, database and user-reported times in different zones. Convert before ordering events.

## Root-cause bar
Call it the root cause only when every link of the trace is proven. Otherwise write "root cause not established" and give the leading hypothesis, marked inferred, with what would settle it.
