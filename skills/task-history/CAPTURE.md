# Structured checkpoint intake

`checkpoint_capture.py` accepts one explicit, task-authorized checkpoint from a trusted host adapter. The input JSON contains `authorization_ref`, the current `expected_digest`, the staged task binding, and a complete event whose task, owner, kind, summary, approval and source evidence match that binding. `agent-coordination/scripts/tasks.py:history_checkpoint_packet` builds the packet from the owned task outbox. The intake validates the event with the central writer, checks the current record owner, and appends under the writer's lock. An identical retry returns `duplicate`.

Example: `skills/task-history/scripts/history-cli capture --repo <isolated-history-root> <checkpoint.json>`.

The host is responsible for proving that the authorization reference came from the user or an authorized task configuration, assigning one stable task ID and record owner, supplying sanitized metadata at task checkpoints, and reconciling the remote journal before invocation. The script never reads chats or sessions, installs a hook, renders a view, updates the index, commits, pushes, or publishes. A successful local append is only the first stage of durable capture.

Before enabling automatic invocation, verify a supported host checkpoint API, redaction, remote publication of journal/view/index, and fresh consumer readback. Preserve the installed native adapter pin until reviewed rollout.
