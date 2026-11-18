# Running the shared skills in Codex

The SKILL.md files and `contracts.md` are the workflow source; this file only
translates tool names. Precedence, the chain, consent, report caps, fetching and
scheduling are defined once in contracts.md (§ Layers, § Chain, § Consent,
§ Report, § Git, § Scheduler); where this file seems to differ, contracts.md wins.

## Names and tools
- `$name` invokes a skill. `/name` in skill text means `$name`, not a Codex
  slash command.
- `${CLAUDE_SKILL_DIR}` = the folder holding the SKILL.md being run. The next
  skill in the chain is `${CLAUDE_SKILL_DIR}/../<next>/SKILL.md` (§ Chain).
- Use the available file, shell and search tools in place of Read, Write, Edit,
  Bash and ToolSearch. Never invent a tool.
- EnterWorktree and ExitWorktree do not exist: pass the worktree's absolute
  path to every shell and file operation instead.

## Sub-agents
- `scout` = the `scout` custom agent; if it cannot be selected, a default
  subagent given the scout brief and told to stay read-only.
- Blueprint's `Plan` agents = read-only default subagents.
- The scout follows a read-only workflow; its permissions come from the parent.
  `$test-review` runs tests in its own session. Set any enforced sandbox there.
- Optional local profiles and their tool/skill limits are described in
  `skills/workflow-contracts/references/scoped-agents.md` in the installed release.
- Sub-agents take no outward action beyond § Consent's task-branch push, draft PR and granted release.

## Scheduling and hooks
- Schedules follow § Scheduler with Codex's automation tool. List existing
  automations first and update a matching id instead of adding a duplicate.
- Fetching follows § Git, in skills and hooks alike.
- Codex hook trust belongs to the user, via `/hooks`. Never bypass it or write
  trust records yourself.

## Rules
`install.sh` renders `authorizations.json` to `~/.codex/agent-skills/rules.toml`
and never applies it; the user does. Each `[[rules]]` has `id`, `tool`, `match`,
`decision` (allow, prompt or forbidden for the modes allow, ask, deny), `why`, a
bash rule's `pattern` (command-prefix tokens) and any `guard`. Each guard is also a
`[[hooks.PreToolUse]]` group running `hooks/<guard>.sh`, the Claude hook itself.
Apply a guarded allow only together with its hook. Claude-only: the
`PermissionDenied` denial log (Codex has no such event). Rules passed by
`--settings` apply without a trust click; project-file rules wait for folder trust.

## Connections and data
- Verify a connector works before relying on it; configuration alone proves
  nothing.
- Production data is read-only unless the user asks (global § Safety).
- Credentials stay in protected local config: never in files, reports, logs or
  command arguments.
