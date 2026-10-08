# Structured checkpoint intake

`checkpoint_capture.py` accepts one explicit, task-authorized checkpoint from a trusted host adapter. The input JSON contains `authorization_ref`, the current `expected_digest`, and a complete event whose `approval_ref` matches that authorization. It validates the event with the central writer, checks the current record owner, and appends under the writer's lock. An identical retry returns `duplicate`.

Example: `python3 skills/task-history/checkpoint_capture.py --repo <isolated-history-root> <checkpoint.json>`.

The host is responsible for proving that the authorization reference came from the user or an authorized task configuration, assigning one stable task ID and record owner, supplying sanitized metadata at task checkpoints, and reconciling the remote journal before invocation. The script never reads chats or sessions, installs a hook, renders a view, updates the index, commits, pushes, or publishes. A successful local append is only the first stage of durable capture.

Before enabling automatic invocation, verify a supported host checkpoint API, redaction, remote publication of journal/view/index, and fresh consumer readback. Preserve the installed native adapter pin until reviewed rollout.
