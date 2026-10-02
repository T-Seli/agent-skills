#!/bin/sh
# SessionStart hook: a <=4-line git snapshot added to Claude's context.
# Info only: never blocks, always exits 0, silent outside a git repo.
# <base> and "pending" follow the definitions in the workflow-contracts skill (contracts.md).

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# iCloud offloads files under ~/Documents and ~/Desktop; git then blocks forever on them.
case "$(git rev-parse --show-toplevel 2>/dev/null)" in
  "$HOME"/Documents/*|"$HOME"/Desktop/*)
    echo "WARNING: this repo is in iCloud-synced ~/Documents or ~/Desktop; move it outside iCloud-synced folders." ;;
esac
# Low disk is what makes macOS start offloading files.
df -k "$HOME" | awk 'NR==2 && $4/$2 < 0.15 { printf "WARNING: disk is %d%% full; free space before macOS starts offloading files.\n", 100 - 100*$4/$2 }'
if [ -n "$(find "$(git rev-parse --git-common-dir)" -flags +dataless -print -quit 2>/dev/null)" ]; then
  echo "WARNING: iCloud has offloaded files inside .git; git commands may hang. Snapshot skipped."
  exit 0
fi

# Fetch origin, but give up after ~8s so a slow network never stalls the session.
# (macOS ships no `timeout`, so poll a background job instead.)
fetch_note=""
if git remote get-url origin >/dev/null 2>&1; then
  set -m # own process group, so a timeout also kills fetch's ssh/https helpers
  GIT_TERMINAL_PROMPT=0 git fetch --quiet origin </dev/null >/dev/null 2>&1 &
  pid=$!
  set +m
  i=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$i" -ge 40 ]; then
      kill -TERM -"$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      fetch_note=" (fetch timed out; origin may be stale)"
      break
    fi
    sleep 0.2
    i=$((i + 1))
  done
  if [ -z "$fetch_note" ]; then
    wait "$pid" || fetch_note=" (fetch failed; origin may be stale)"
  fi
fi

main_wt=$(git worktree list --porcelain 2>/dev/null | sed -n '1s/^worktree //p')
main_wt=${main_wt:-$(git rev-parse --show-toplevel)}
repo=$(basename "$main_wt")
# First backticked value on a "- <Field>: `value`" line of the project CLAUDE.md.
field() { sed -n "s/^- $1: *\`\([^\`]*\)\`.*/\1/p" "$main_wt/CLAUDE.md" 2>/dev/null | head -1; }

branch=$(git branch --show-current 2>/dev/null)
[ -n "$branch" ] || branch="detached at $(git rev-parse --short HEAD 2>/dev/null)"
echo "Git snapshot for $repo — branch: $branch"

# <base>: § Deploy "Base branch", else origin/HEAD, else probe main/master and say so.
base=$(field 'Base branch')
if [ -z "$base" ]; then
  base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
  base=${base#origin/}
fi
guess=""
if [ -z "$base" ]; then
  for b in main master; do
    if git rev-parse --verify --quiet "origin/$b" >/dev/null || git rev-parse --verify --quiet "refs/heads/$b" >/dev/null; then
      base=$b
      guess=" (guessed; set CLAUDE.md § Deploy Base branch, or: git remote set-head origin --auto)"
      break
    fi
  done
fi
if [ -z "$base" ]; then
  echo "Base branch: unknown$fetch_note"
elif ! git rev-parse --verify --quiet "origin/$base" >/dev/null; then
  echo "Base $base: no origin/$base, local only$guess$fetch_note"
elif git show-ref --verify --quiet "refs/heads/$base"; then
  set -- $(git rev-list --left-right --count "$base...origin/$base" 2>/dev/null)
  echo "Base $base vs origin/$base: ahead ${1:-?}, behind ${2:-?}$guess$fetch_note"
else
  echo "Base $base: no local branch$guess$fetch_note"
fi

dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
wts=$(git worktree list --porcelain 2>/dev/null | grep -c '^worktree ')
echo "Uncommitted files (incl. untracked): $dirty · linked worktrees: $((wts - 1))"

# Pending drafts: every folder in $MAIN/.claude/drafts/ except handoffs/.
pending=$(for d in "$main_wt/.claude/drafts"/*/; do
  [ -d "$d" ] || continue
  n=$(basename "$d")
  [ "$n" = handoffs ] || echo "$n"
done | sort -r)
if [ -n "$pending" ]; then
  count=$(echo "$pending" | wc -l | tr -d ' ')
  echo "Pending drafts ($count) in .claude/drafts/: $(echo "$pending" | head -3 | paste -sd ',' - | sed 's/,/, /g')"
fi

exit 0
