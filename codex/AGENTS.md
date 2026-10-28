# Shared workflow for Codex

This file is built by `install.sh`: this header, then the shared working
agreement, the reply style and the Codex notes. Edit the sources, not the copy.

- Project `AGENTS.md`, project `CLAUDE.md` and explicit user instructions win
  over this shared workflow, per contracts.md § Layers.
- Read the project's `CLAUDE.md` when it exists; Codex does not load it.
- Skills: `$prime-context`, `$grill-me`, `$blueprint`, `$action-items`, `$implement`, `$tdd`,
  `$test-review`, `$deploy`, `$monitor`, `$handoff`, `$agent-coordination`, `$approval-handoff`, `$system-audit`. Each starts from the
  user's plain words and starts the next one itself, per contracts.md § Chain.
  Deploy runs once the user has given a go-ahead, per contracts.md § Consent.
- To start a Claude worker, run `~/.agents/skills/agent-coordination/scripts/delegate.py start`
  (worker-execution.md § Delegate); never hand-write `claude -p`.
- When relevant, read the project's Claude memory index read-only; treat it as
  unverified leads and check them against current files and data.
