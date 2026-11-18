#!/bin/sh
# Claude PermissionDenied (matcher: none, every tool): log-only. Appends one JSON line per auto-mode refusal
# (time, session id as receipts name it, cwd, tool, the command's first word, tool_use_id) to closeout.denial_log(),
# the agent-coordination state dir (AGENT_COORDINATION_STATE); `issues-cli sweep` reads it via
# closeout.belt_denials(), which keeps only belt registry sessions. Rule and hook denials do not fire this event.
# It never changes the decision; an error exits 1 with the reason.
exec python3 -I -B -c '
import json, os, sys
root = os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1])))  # the release this hook link points into
sys.path.insert(0, root)
from agent_skills.closeout import record_denial
record_denial(json.load(sys.stdin))
' "$0"
