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

# caffeinate ignores -t when it runs the command itself, so it watches this shell's pid, which exec
# hands to the command (keeping its stdin): the assertion ends when the command exits (-w) or the
# window passes (-t), whichever is first.
caffeinate -i -t "$seconds" -w $$ &
exec "$@"
