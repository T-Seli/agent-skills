# Data access (production, read-only)

How any skill reads production data. Tools, servers and tables come from the project, never from here.

## Where the recipe comes from, in order
1. The project's `CLAUDE.md` § Observe `Database checks` (the read-only SQL tool, its targets, how a tenant resolves to its database) and `Lookup` (entity → tables, or a recipes file it points to; read that file).
2. Nothing there: discover with the tool's schema listing (describe before guessing columns), use what works, and end the report with `Add to CLAUDE.md § Observe: <fact>`.

## Habits
- Resolve the tenant or database once, then name it in the answer and the log.
- Describe a table before using columns you have not seen this session; that also catches a stale recipe.
- Explain before a query on a large table or a large tenant; narrow the filter or use an index if the plan is a full scan.
- Every query has a time window and a LIMIT. Use parameters for values.
- Work in UTC; convert once, with the tenant's zone, and name it.
- Quote n and the timezone with every count. 0 rows is a finding to explain, never a pass.
- Report ids, counts and short gists. Never paste phone numbers, emails, names, addresses or transcripts into chat, logs, plans or handoffs.
- Read-only always. A needed write goes to the user as a decision (contracts.md § Consent).
- A scout gets the database, the recipe and the question in its brief, and returns counts and ids, not rows.
- When the task or dispatch declares a database or connector capability, brief the scout once a readiness check passes for it in the scout's own environment and auth context (worker-execution.md); a missing, stale or mismatched declared capability blocks that dispatch and is reported as a gap. The receipt records an earlier authorized observation and never grants access; capabilities the task does not declare don't gate it. Never probe or create access to find out.
