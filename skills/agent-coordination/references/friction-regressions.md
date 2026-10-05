# Sanitized orchestration regression examples

These examples summarize user-visible mismatches reported to the orchestrator on 2026-10-05. Source reference: restricted thread `01a0fd76-51a9-72b5-be36-1d2b78e68011`. They contain no raw conversation or customer payload. The issue is reported; a root cause is not established. Each prevention check remains **unverified** until a new task exercises it.

| Reported issue | Impact or rework | Scoped correction | Prevention check |
| --- | --- | --- | --- |
| An onboarding task drifted into adjacent Sales work. | The answer crossed the assigned scope and required redirection. | Restate the approved onboarding target and exclude the Sales change. | Dispatch preflight names the exact target and exclusions; return check rejects adjacent work. |
| A worker repeated a stale preflight instead of following the documented EIC route. | Investigation was repeated and the prescribed next step was delayed. | Read the current runbook and take or report the documented EIC route within authorization. | Preflight records the runbook revision and prescribed route; return check confirms the route was addressed. |
| A five-CSR request received an older multi-workspace and phone-log response. | The user had to restate the actual request. | Re-dispatch the five-CSR task with its own completion criteria. | Return check compares the worker answer against the current request, not a prior task. |
| A reminder about a named work item was too broad. | The user could not tell which specific action was due. | Name the exact action, target, and timing in the reminder. | Review the reminder against its authorized action before sending. |
| A Slack mail link was formatted as a command. | The link was confusing or unusable. | Use the platform's supported link formatting. | Render a sanitized test message and verify the link target and display text. |

When recording a live task, use one `feedback` event for each issue with its own stable event ID, `source_ref`, and evidence state. Keep this table as regression prompts, not as independent verification or blanket authorization. Preserve the original task event and append any correction. After a prevention check runs, append its result with a precise evidence reference; only propose a reusable skill change through a separately reviewed proposal.
