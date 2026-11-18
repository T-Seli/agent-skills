#!/bin/sh
# Claude PreToolUse (matcher: mcp__scheduled-tasks__delete_scheduled_task|Bash): deny deleting a schedule whose
# deploy entry lacks its `Monitor verdict:` (first schedule first-traffic, second 24 h), and deny
# `issues-cli lane <n> monitoring` unless the issue's task log holds two `Scheduler:` ids on its newest deploy.
# Any other tool call (arming a monitor included) passes untouched. A guard error denies.
exec python3 -I -B -c '
import os, sys
root = os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1])))  # the release this hook link points into
sys.path.insert(0, root)
from agent_skills import closeout
sys.exit(closeout.guard_hook(closeout.monitor_decision))
' "$0"
