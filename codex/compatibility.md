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
- `codex/hooks/session-start.py` puts `issues-cli resume` before the Git snapshot
  for a session named in workers.json `roles`, as the Claude hook does.

## Rules
`install.sh` renders `authorizations.json` into three inert files and applies
none of them; the user does.
- `~/.claude/agent-skills/settings.snippet.json`: Claude rules (`Bash(<match> *)`,
  the mcp tool name, `Edit(<glob>)`) and each guard as a `PreToolUse` hook.
- `~/.codex/agent-skills/conveyor.rules`: per bash entry a `# <id>: <why>` line and
  `prefix_rule(pattern=[<match tokens>], decision="allow")`, with `prompt` for
  ask and `forbidden` for deny. Copy it into `~/.codex/rules/`.
- `~/.codex/agent-skills/hooks.json`: each guard as a `PreToolUse` group running
  the release's `hooks/<guard>.sh`, the Claude hook itself. Merge it into
  `~/.codex/hooks.json` and trust it with `/hooks`.

Every guard hook has a 30-second timeout. An entry with `held` is not rendered.
Apply a guarded allow only together with its hook. Codex rules match command
prefixes only, so these entries have no Codex rule and the working agreement
alone binds there: mcp `no-email-send`, `no-email-draft-send`, `monitor-arm`,
`monitor-delete`, `archive-done`; edit `no-settings-edit`, `no-codex-config-edit`.
Claude-only: the `PermissionDenied` denial log (Codex has no such event). Rules
passed by `--settings` apply without a trust click; project-file rules wait for
folder trust.

## Permission probe
Prepared for the attended session; no worker runs it. It proves the rendered
Claude rules match calls as a session types them. Codex: `conveyor.rules` is
checked for format by tests only.
1. `P=$(mktemp -d)`; from the candidate checkout run
   `./install.sh --target=claude --destination-root="$P/home"`; the file is
   `$P/home/.claude/agent-skills/settings.snippet.json`.
2. `cd "$P" && claude --settings "$P/home/.claude/agent-skills/settings.snippet.json" --setting-sources project`
   (an empty folder, so no user or project rule masks a result).
3. Make each call below exactly as written, one per turn. Answer No to every
   dialog. Record per row the call, the expected and the seen result.

| Kind | Call | Expect |
|---|---|---|
| bash allow | `~/.agents/skills/workflow-contracts/scripts/safeguard-cli disk-check`, typed with `~/` | runs, no dialog |
| bash ask | `~/.agents/skills/workflow-contracts/scripts/safeguard-cli run-approved release probe --digest 0` | dialog; No |
| bash deny | none rendered while `no-merge-outside-release` is held: `gh pr merge 1` | dialog; No |
| mcp allow | none rendered while held: `mcp__scheduled-tasks__create_scheduled_task` | dialog; No |
| mcp deny | `mcp__*__send_email` and `mcp__*__send_draft`: a connected mail server's `send_email` and `send_draft` to `probe@example.invalid` | refused, no dialog |
| path allow | the snippet's `Read(~/.claude/skills/workflow-contracts/**)`: read `~/.claude/skills/workflow-contracts/contracts.md` | reads, no dialog |
| edit deny | an Edit of `~/.claude/settings.json` and of `~/.codex/config.toml` that changes nothing | refused, no dialog |

A row passes only when seen equals expected. A dialog on a deny row is a failed
match. With no mail server connected the mcp deny row is not exercised, not
passed. Delete `$P` afterwards.

## Connections and data
- Verify a connector works before relying on it; configuration alone proves
  nothing.
- Production data is read-only unless the user asks (global § Safety).
- Credentials stay in protected local config: never in files, reports, logs or
  command arguments.
