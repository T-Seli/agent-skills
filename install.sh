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
BACKUP="$HOME/.claude/backup-$(date +%Y%m%d-%H%M%S)"

run() { echo "$*"; [ "$DRY" = 1 ] || "$@"; }

# link <source> <target>: back up a real file or folder at <target>, then symlink it.
link() {
  [ -e "$1" ] || { echo "missing source: $1" >&2; exit 1; }
  run mkdir -p "$(dirname "$2")"
  if [ -e "$2" ] && [ ! -L "$2" ]; then
    run mkdir -p "$BACKUP"
    run mv "$2" "$BACKUP/"
  fi
  run ln -sfn "$1" "$2"
}

# build <target> <source>...: back up a real file at <target> (a symlink is just
# replaced), then write the sources into it, each without its YAML frontmatter.
# A copy, not a link: Codex reads one file, so rerunning install.sh refreshes it.
build() {
  t=$1; shift
  for s in "$@"; do [ -e "$s" ] || { echo "missing source: $s" >&2; exit 1; }; done
  run mkdir -p "$(dirname "$t")"
  if [ -L "$t" ]; then
    run rm "$t"
  elif [ -e "$t" ] && [ "$(head -1 "$t")" != "$(head -1 "$1")" ]; then  # not our own earlier build
    run mkdir -p "$BACKUP"
    run mv "$t" "$BACKUP/"
  fi
  echo "build $t from: $*"
  [ "$DRY" = 1 ] && return
  for s in "$@"; do
    awk 'NR == 1 && $0 == "---" { fm = 1; next } fm && $0 == "---" { fm = 0; next } !fm' "$s"
    echo
  done > "$t"
}

# Claude Code
if [ "$TARGET" = all ] || [ "$TARGET" = claude ]; then
for d in "$R"/skills/*/; do link "${d%/}" "$HOME/.claude/skills/$(basename "$d")"; done
for f in "$R"/agents/*.md; do link "$f" "$HOME/.claude/agents/$(basename "$f")"; done
for f in "$R"/output-styles/*.md; do link "$f" "$HOME/.claude/output-styles/$(basename "$f")"; done
for f in "$R"/hooks/*.sh; do run chmod +x "$f"; link "$f" "$HOME/.claude/hooks/$(basename "$f")"; done
link "$R/global/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
fi

# Codex
if [ "$TARGET" = all ] || [ "$TARGET" = codex ]; then
for d in "$R"/skills/*/; do link "${d%/}" "$HOME/.agents/skills/$(basename "$d")"; done
for f in "$R"/codex/agents/*.toml; do link "$f" "$HOME/.codex/agents/$(basename "$f")"; done
build "$HOME/.codex/AGENTS.md" "$R/codex/AGENTS.md" "$R/global/CLAUDE.md" \
  "$R/output-styles/orchestrator.md" "$R/codex/compatibility.md"
fi

# Links left from an older layout that now point at nothing.
for l in "$HOME"/.claude/workflow "$HOME"/.claude/skills/* "$HOME"/.agents/skills/*; do
  case "$l:$TARGET" in
    "$HOME"/.claude/*:codex|"$HOME"/.agents/*:claude) continue ;;
  esac
  if [ -L "$l" ] && [ ! -e "$l" ]; then
    case "$(readlink "$l")" in "$R"/*) run rm "$l" ;; esac
  fi
done

echo "Settings are not edited by this script. Merge by hand:"
echo "  Claude: $R/settings.snippet.json into ~/.claude/settings.json"
echo "  Codex:  add $R/codex/hooks/session-start.py as a SessionStart hook in ~/.codex/hooks.json, then trust it with /hooks"
