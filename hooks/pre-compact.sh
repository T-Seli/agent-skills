#!/bin/sh
# Claude PreCompact (matcher: none): for a session named in workers.json `roles` (conveyor.json `resume.hooks`),
# prints the `issues-cli resume` picture headed "Keep these exactly:" for the summary; other sessions print nothing.
# Info only: never blocks, always exits 0; a failed resume or lookup prints a WARNING line.
python3 -I -B -c '
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1]))))  # the release this link points into
from agent_skills.closeout import resume_picture
picture = resume_picture(json.load(sys.stdin))
if picture is not None:
    print("Keep these exactly:\n" + picture)
' "$0" || echo "WARNING: pre-compact resume hook failed; read issues-cli resume before stating any fact about a session, PR, approval or owner."
exit 0
