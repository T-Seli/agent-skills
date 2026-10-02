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

# caffeinate owns and cleans up the assertion when its child exits, even on failure.
# -t is a separate upper bound if the child outlives the planned critical window.
exec caffeinate -i -t "$seconds" "$@"
