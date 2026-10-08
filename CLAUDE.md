# agent-skills

Shared agent skills: an authored core, supported Claude Code and Codex adapters,
and a draft Dot workflow. Project and machine facts stay outside the shared core.

## Map
- Entry points: `skills/*/SKILL.md` — the skills · `global/CLAUDE.md` — the global working agreement · `install.sh` — links everything into `~/.claude`, `~/.agents` and `~/.codex`
- Core modules: `skills/workflow-contracts/` — shared names, files, log format and defaults · `hooks/` — Claude hooks · `codex/` — Codex adapter, agent and hook
- Governing docs: `README.md` — design rules and budgets
- Generated or vendored (never edit): none
- Remotes: configure only after private destination and sharing review
- Task records: none (task folders stay in local drafts; records name real projects, and this repo is meant to be shared)
- Commits: `<type>(<scope>): <summary>` · attribution: `Co-Authored-By` trailer
- Git host CLI: use the host's supported CLI after connection

## Run & test
- Install: `./install.sh` (`--dry-run` lists the links without changing anything)
- Run locally: none (skills load at the next session start)
- Tests: full `tests/check.sh && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'` (~1s) · one test: none · list failing ids: the lines it prints
- Prompt checks: none
- Fast tests: `tests/check.sh && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'`
- Tests live in: `tests/` (tracked by git: yes)
- Lint / typecheck: `sh -n hooks/*.sh install.sh` · `python3 -m py_compile codex/hooks/*.py`
- CI: none
- Test baseline: clean
- Test services: none
- Worktree setup: none

## Deploy
- Deploy doc: `README.md` § Install
- Base branch: `main` · Release branch: `main` · Protected: `main`
- Flow: `branch` (the main checkout is live, so edits happen in a task worktree)
- PR merge style: ff
- Release: per-merge
- Trigger: manual
- Skip-deploy marker: none
- Targets: local installation after review in an idle window
- Deployed version → commit: `git -C <main checkout> rev-parse main`
- Pre-deploy checks: `tests/check.sh`
- Rollback: return to the previously installed source snapshot, rerun the selected installer, and restore any backed-up local files
- Kill switch: none
- Window: between sessions (a running session keeps the skill text it already loaded)

## Observe
- Logs: none
- Errors / crashes: session transcripts under `~/.claude/projects/` and Codex threads
- Dashboards / alerts: none
- Lookup: none
- Database checks: none
- User feedback: the user, in chat
- Traffic timing: the next session that uses a changed skill
- Rollout: none
- Recheck window: default
- Timezones: logs local · rechecks scheduled in this machine's zone

## Tenancy
- Tenants: none

## Gotchas
- Installed symlinks can make edits live at once. Edit in an isolated worktree, and switch installed links only in an idle window.

## Defaults
