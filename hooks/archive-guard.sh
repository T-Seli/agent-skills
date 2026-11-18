#!/bin/sh
# Claude PreToolUse (matcher: mcp__ccd_session_mgmt__archive_session): the belt registry is the sessions in
# `Owner:` and `Claimed:` receipts on open belt issues (conveyor.json `registry`). Allows one whose claimed issues
# are all closed or parked, denies one with unfinished work or a plain-uuid headless worker, asks about anything
# outside the registry. `session_id` "self" means the calling session. A guard that cannot load or errors denies.
python3 -I -B -c '
import json, os, sys
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1]))))  # the release this link points into
    from agent_skills import closeout
except Exception as exc:  # noqa: BLE001 - fail closed and say why
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                      "permissionDecisionReason": f"Guard cannot load, refused: {type(exc).__name__}: {exc}"}}))
    sys.exit(0)
sys.exit(closeout.guard_hook(closeout.archive_decision))
' "$0" || { echo "archive-guard failed to run; refused" >&2; exit 2; }
