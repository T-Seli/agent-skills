#!/bin/sh
# Claude PreToolUse (matcher: mcp__scheduled-tasks__create_scheduled_task|mcp__scheduled-tasks__delete_scheduled_task),
# per conveyor.json `registry.monitors`. Create: allows an id `monitor-<repo>-<slug>` whose description carries a
# `Deadline:`, else asks. Delete: allows a `Scheduler:` id on an open belt issue once its verdict is recorded (first id
# first-traffic, second 24 h), denies before, asks for any other id. A guard that cannot load or errors denies.
python3 -I -B -c '
import json, os, sys
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1]))))  # the release this link points into
    from agent_skills import closeout
except Exception as exc:  # noqa: BLE001 - fail closed and say why
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                      "permissionDecisionReason": f"Guard cannot load, refused: {type(exc).__name__}: {exc}"}}))
    sys.exit(0)
sys.exit(closeout.guard_hook(closeout.monitor_decision))
' "$0" || { echo "monitor-id-guard failed to run; refused" >&2; exit 2; }
