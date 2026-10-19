#!/bin/sh
# Link this framework into Claude Code (~/.claude) and Codex (~/.agents, ~/.codex),
# and build ~/.codex/AGENTS.md. Idempotent; rerun after pulling to refresh the build.
# --dry-run prints the actions without changing anything.
# Existing real files or folders at a target path are moved to a dated backup first.
set -eu

R=$(cd "$(dirname "$0")" && pwd)
DRY=0
TARGET=all
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --target=all|--target=claude|--target=codex) TARGET=${arg#--target=} ;;
    *) echo "usage: $0 [--dry-run] [--target=all|claude|codex]" >&2; exit 2 ;;
  esac
done
BACKUP="$HOME/.claude/backup-$(date +%Y%m%d-%H%M%S)-$$"
INSTALL_LOCK="$HOME/.agent-skills-install.lock"
INSTALL_TXN="$HOME/.agent-skills-install-txn-$$"
INSTALL_STAGE=preflight
LOCK_HELD=0
TXN_ACTIVE=0
TXN_CHANGED=0
ENTRY_COUNT=0
DIR_COUNT=0
CURRENT_TEMP=
AWK=${AWK:-awk}

run() { echo "$*"; [ "$DRY" = 1 ] || "$@"; }

record_created_dir() {
  DIR_COUNT=$(expr "$DIR_COUNT" + 1)
  printf '%s\n' "$1" > "$INSTALL_TXN/dir-$DIR_COUNT"
}

# Create a real directory path while recording only directories made by this run.
ensure_dir() {
  d=$1
  if [ -d "$d" ] && [ ! -L "$d" ]; then return; fi
  if [ -e "$d" ] || [ -L "$d" ]; then
    echo "cannot create directory over existing target: $d" >&2
    exit 1
  fi
  p=$(dirname "$d")
  [ "$p" = "$d" ] || ensure_dir "$p"
  d=$1
  if [ "$DRY" = 1 ]; then
    echo "mkdir $d"
  else
    mkdir "$d"
    record_created_dir "$d"
  fi
}

# Snapshot a target once, removing it so its replacement can be installed.
# Symlinks are recorded by their exact link text; real files/directories are moved.
snapshot_target() {
  t=$1
  [ "$DRY" = 0 ] || { echo "snapshot $t"; return; }
  n=1
  while [ "$n" -le "$ENTRY_COUNT" ]; do
    [ "$(cat "$INSTALL_TXN/entry-$n/path")" != "$t" ] || return
    n=$(expr "$n" + 1)
  done
  ENTRY_COUNT=$(expr "$ENTRY_COUNT" + 1)
  e="$INSTALL_TXN/entry-$ENTRY_COUNT"
  mkdir "$e"
  printf '%s\n' "$t" > "$e/path"
  if [ -L "$t" ]; then
    printf '%s\n' symlink > "$e/type"
    readlink "$t" > "$e/link"
    rm -f "$t"
  elif [ -e "$t" ]; then
    printf '%s\n' original > "$e/type"
    mv "$t" "$e/original"
  else
    printf '%s\n' absent > "$e/type"
  fi
  TXN_CHANGED=1
}

remove_replacement() {
  t=$1
  if [ -L "$t" ] || [ -f "$t" ]; then
    rm -f "$t"
  elif [ -d "$t" ]; then
    rmdir "$t"
  elif [ -e "$t" ]; then
    echo "cannot remove unexpected replacement type during rollback: $t" >&2
    return 1
  fi
}

rollback_transaction() {
  echo "rolling back install transaction at $INSTALL_STAGE" >&2
  rollback_status=0
  n=$ENTRY_COUNT
  while [ "$n" -gt 0 ]; do
    e="$INSTALL_TXN/entry-$n"
    t=$(cat "$e/path")
    typ=$(cat "$e/type")
    if ! remove_replacement "$t"; then
      rollback_status=1
      n=$(expr "$n" - 1)
      continue
    fi
    case "$typ" in
      absent) ;;
      symlink)
        if ! ln -s "$(cat "$e/link")" "$t"; then rollback_status=1; fi
        ;;
      original)
        if ! mv "$e/original" "$t"; then rollback_status=1; fi
        ;;
      *)
        echo "unknown rollback entry type for $t: $typ" >&2
        rollback_status=1
        ;;
    esac
    n=$(expr "$n" - 1)
  done
  n=$DIR_COUNT
  while [ "$n" -gt 0 ]; do
    d=$(cat "$INSTALL_TXN/dir-$n")
    if [ -d "$d" ] && [ ! -L "$d" ]; then
      rmdir "$d" 2>/dev/null || rollback_status=1
    fi
    n=$(expr "$n" - 1)
  done
  return "$rollback_status"
}

preserve_failed_transaction() {
  failed="$HOME/.agent-skills-install-failure-$(date +%Y%m%d-%H%M%S)-$$"
  if mv "$INSTALL_TXN" "$failed"; then
    echo "failure receipt: $failed" >&2
    TXN_ACTIVE=0
  else
    echo "failure receipt remains at: $INSTALL_TXN" >&2
  fi
}

commit_transaction() {
  if [ "$TXN_CHANGED" = 0 ]; then
    rm -f "$INSTALL_TXN/entry-count" "$INSTALL_TXN/dir-count"
    rmdir "$INSTALL_TXN"
    TXN_ACTIVE=0
    echo "install transaction: no changes"
    return
  fi
  ensure_dir "$(dirname "$BACKUP")"
  ensure_dir "$BACKUP"
  printf '%s\n' "$ENTRY_COUNT" > "$INSTALL_TXN/entry-count"
  printf '%s\n' "$DIR_COUNT" > "$INSTALL_TXN/dir-count"
  mv "$INSTALL_TXN" "$BACKUP/transaction"
  TXN_ACTIVE=0
  echo "rollback receipt: $BACKUP/transaction"
}

finish() {
  status=$?
  trap - 0
  [ -z "$CURRENT_TEMP" ] || rm -f "$CURRENT_TEMP"
  if [ "$status" != 0 ] && [ "$TXN_ACTIVE" = 1 ]; then
    rollback_transaction || status=1
    preserve_failed_transaction || status=1
  fi
  if [ "$LOCK_HELD" = 1 ]; then
    rm -f "$INSTALL_LOCK/owner" || true
    rmdir "$INSTALL_LOCK" || true
  fi
  if [ "$status" != 0 ]; then
    echo "install incomplete at $INSTALL_STAGE; reconcile every requested adapter before claiming success" >&2
  fi
  exit "$status"
}

if [ "$DRY" = 0 ]; then
  if ! mkdir "$INSTALL_LOCK"; then
    echo "install already owned: $(cat "$INSTALL_LOCK/owner" 2>/dev/null || echo unknown)" >&2
    exit 1
  fi
  LOCK_HELD=1
  printf '%s %s %s\n' "$$" "$TARGET" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$INSTALL_LOCK/owner"
  trap finish 0
  trap 'exit 129' 1
  trap 'exit 130' 2
  trap 'exit 143' 15
  mkdir "$INSTALL_TXN"
  TXN_ACTIVE=1
fi

# link <source> <target>: preserve any changed target, then symlink it.
link() {
  [ -e "$1" ] || { echo "missing source: $1" >&2; exit 1; }
  ensure_dir "$(dirname "$2")"
  if [ -L "$2" ] && [ "$(readlink "$2")" = "$1" ]; then
    echo "keep $2 -> $1"
    return
  fi
  snapshot_target "$2"
  run ln -sfn "$1" "$2"
}

# build <target> <source>...: compose beside <target>, then atomically replace it.
# Every changed target and digest sidecar is retained in the same transaction.
build() {
  t=$1; shift
  for s in "$@"; do [ -e "$s" ] || { echo "missing source: $s" >&2; exit 1; }; done
  ensure_dir "$(dirname "$t")"
  echo "build $t from: $*"
  [ "$DRY" = 1 ] && return
  bt=$(mktemp "$(dirname "$t")/.agent-skills-build.XXXXXX")
  CURRENT_TEMP=$bt
  for s in "$@"; do
    "$AWK" 'NR == 1 && $0 == "---" { fm = 1; next } fm && $0 == "---" { fm = 0; next } !fm' "$s"
    echo
  done > "$bt"
  chmod 644 "$bt"
  if [ -f "$t" ] && [ ! -L "$t" ] && cmp -s "$bt" "$t"; then
    echo "keep $t (content already current)"
    rm -f "$bt"
  else
    snapshot_target "$t"
    mv "$bt" "$t"
  fi
  CURRENT_TEMP=

  set -- $(shasum -a 256 "$t")
  digest=$1
  sidecar="$t.agent-skills.sha256"
  bs=$(mktemp "$(dirname "$t")/.agent-skills-digest.XXXXXX")
  CURRENT_TEMP=$bs
  printf '%s\n' "$digest" > "$bs"
  chmod 644 "$bs"
  if [ -f "$sidecar" ] && [ ! -L "$sidecar" ] && cmp -s "$bs" "$sidecar"; then
    rm -f "$bs"
  else
    snapshot_target "$sidecar"
    mv "$bs" "$sidecar"
  fi
  CURRENT_TEMP=
}

# Claude Code
if [ "$TARGET" = all ] || [ "$TARGET" = claude ]; then
INSTALL_STAGE=claude
for d in "$R"/skills/*/; do link "${d%/}" "$HOME/.claude/skills/$(basename "$d")"; done
for f in "$R"/agents/*.md; do link "$f" "$HOME/.claude/agents/$(basename "$f")"; done
for f in "$R"/output-styles/*.md; do link "$f" "$HOME/.claude/output-styles/$(basename "$f")"; done
for f in "$R"/hooks/*.sh; do [ -x "$f" ] || { echo "hook source is not executable: $f" >&2; exit 1; }; link "$f" "$HOME/.claude/hooks/$(basename "$f")"; done
link "$R/global/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
# delegate.py refuses to start workers without its private config; seed it once, never overwrite.
cfg="$HOME/.config/agent-skills/workers.json"
if [ ! -e "$cfg" ]; then
  ensure_dir "$(dirname "$cfg")"
  run cp "$R/agent_skills/delegate_config.example.json" "$cfg"
  run chmod 600 "$cfg"
fi
INSTALL_STAGE=claude-complete
fi

# Codex
if [ "$TARGET" = all ] || [ "$TARGET" = codex ]; then
INSTALL_STAGE=codex
for d in "$R"/skills/*/; do link "${d%/}" "$HOME/.agents/skills/$(basename "$d")"; done
for f in "$R"/codex/agents/*.toml; do link "$f" "$HOME/.codex/agents/$(basename "$f")"; done
build "$HOME/.codex/AGENTS.md" "$R/codex/AGENTS.md" "$R/global/CLAUDE.md" \
  "$R/output-styles/orchestrator.md" "$R/codex/compatibility.md"
INSTALL_STAGE=codex-complete
fi

# Links left from an older layout that now point at nothing.
for l in "$HOME"/.claude/workflow "$HOME"/.claude/skills/* "$HOME"/.agents/skills/*; do
  case "$l:$TARGET" in
    "$HOME"/.claude/*:codex|"$HOME"/.agents/*:claude) continue ;;
  esac
  if [ -L "$l" ] && [ ! -e "$l" ]; then
    case "$(readlink "$l")" in "$R"/*) snapshot_target "$l" ;; esac
  fi
done

echo "Settings are not edited by this script. Merge by hand:"
echo "  Claude: $R/settings.snippet.json into ~/.claude/settings.json"
echo "  Codex:  add $R/codex/hooks/session-start.py as a SessionStart hook in ~/.codex/hooks.json, then trust it with /hooks"
INSTALL_STAGE=complete
[ "$DRY" = 1 ] || commit_transaction
