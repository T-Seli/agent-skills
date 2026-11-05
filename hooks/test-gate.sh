#!/bin/sh
# Claude PreToolUse (Bash): deny a bare test-suite command and name the test-slot command to run instead.
exec python3 -I -B -c '
import os, sys
root = os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1])))  # the release this hook link points into
sys.path.insert(0, root)
from agent_skills.test_gate import main
sys.exit(main(os.path.join(root, "skills/workflow-contracts/scripts/safeguard-cli")))
' "$0"
