#!/bin/sh
# Claude PreToolUse (matcher: mcp__ccd_session_mgmt__archive_session): deny archiving any session that is not
# a belt registry session closeout.archive_check finds verified-done; a user side session is never archived.
# `session_id` "self" means the calling session. A guard error denies.
exec python3 -I -B -c '
import os, sys
root = os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1])))  # the release this hook link points into
sys.path.insert(0, root)
from agent_skills import closeout
sys.exit(closeout.guard_hook(closeout.archive_decision))
' "$0"
