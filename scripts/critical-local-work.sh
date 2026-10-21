#!/bin/sh
# Keep the machine awake only while one explicitly wrapped local command runs.
set -eu

usage() {
  echo "usage: $0 <task-id> <seconds: 1..14400> -- <command> [args...]" >&2
  exit 2
}

[ "$#" -ge 4 ] || usage
task_id=$1
seconds=$2
shift 2
[ "$1" = -- ] || usage
shift
[ "$#" -gt 0 ] || usage
case "$task_id" in ''|*[!A-Za-z0-9._-]*) usage ;; esac
case "$seconds" in ''|*[!0-9]*) usage ;; esac
[ "$seconds" -ge 1 ] && [ "$seconds" -le 14400 ] || usage
command -v caffeinate >/dev/null 2>&1 || { echo "caffeinate unavailable" >&2; exit 69; }
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
RELEASE_ROOT=$(CDPATH= cd -P "$SCRIPT_DIR/.." && pwd)
# Keep this foreground executor alive; no nohup/disown or background supervisor.
# The native assertion watches the supervisor and has its own finite timeout.
exec python3 -I -B -c '
import runpy, sys
root = sys.argv.pop(1)
sys.path.insert(0, root)
runpy.run_module("agent_skills.keep_awake", run_name="__main__")
' "$RELEASE_ROOT" "$task_id" "$seconds" -- "$@"
