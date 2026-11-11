# Scoped skill agents

Use these optional profiles for local engineering work. Keep `scout` for work
that needs connected data; do not silently trim its tools without usage evidence.
The installer links Claude definitions in `agents/` and copies regular Codex
TOML definitions from `codex/agents/` for standalone discovery. Shared procedures remain in `skills/*/SKILL.md`.

| Role | Agent | Skill loaded when needed |
| --- | --- | --- |
| Local exploration | `local-scout` | Relevant research skill, if any |
| Review | `skill-reviewer` | `test-review` |
| Implementation | `skill-implementer` | `implement`, then `tdd` as applicable |

Give a fresh agent the goal, repository/workspace, exact source/base, acceptance
criteria, permitted side effects and evidence destination. Do not pass a full
conversation when a bounded brief suffices. Missing connector work returns to
the parent. Agent selection does not authorize publication or deployment.

## Claude Code

Select the agent by its exact name on the Agent tool (`subagent_type`), for example
`skill-reviewer`. Retain `Skill` for on-demand workflows, `WebFetch` and
`WebSearch` for documentation, and `TaskStop` for owned background commands.
Use `rg` through Bash for local searches. Reviewer Write is for permitted
review artifacts, not edits to the candidate.

The explicit `tools` field filters out unlisted tools, including MCP tools.
Avoid preloading every skill with `skills:`: that injects their bodies at startup.
A skill with `context: fork` must name the intended `agent:` explicitly to use
its profile; invoking a different forked skill does not inherit this profile.
Keep Claude-only fork metadata in a Claude adapter rather than shared SKILL.md.
Start a fresh session after installing agents. Main-session tools stay unchanged.

## Codex

Ask Codex to spawn the named custom agent with a bounded brief. The TOML profiles
disable apps and plugins, and use the directly installed `.agents/skills` core.
Plugin-only skills are unavailable in these profiles; select a normal agent when
one is required. Verify local skill discovery before relying on the profile.

Codex does not expose Claude's agent `tools:` allowlist. Custom agents inherit
parent permissions and configured MCP servers; the feature flags do not remove
arbitrary MCP servers. For a connector-free worker, use a supported separately
configured parent session with no MCP servers, not invented per-agent settings.
Configure any required sandbox on the parent. Instructions alone do not enforce
read-only behavior. Do not change trust, credentials or permissions to test this.

Use one declaration route. Explicit legacy `[agents.name]` entries plus the
standalone alias can produce duplicate-role warnings; installation holds on
colliding registrations. Review a conditional migration; preserve unrelated config.
For an isolated CLI experiment, `codex exec --ignore-user-config` keeps existing
auth/rules but omits user configuration. Reapply the required model, reviewer and
read-only sandbox; supply one canonical role file explicitly (not a symlink).
For example, replace `/absolute/release`:
```sh
codex exec --ignore-user-config -s read-only -c 'agents.local-scout.config_file="/absolute/release/codex/agents/local-scout.toml"' \
  -c 'agents.local-scout.description="Local source-only explorer"' \
  'Spawn one local-scout to answer the bounded local question in this brief.'
```
The tested CLI 0.160.1 needed normal persistence for child context; `--ephemeral`
failed with `no rollout found for thread id`. Project-local configuration may
also be disabled in an untrusted folder. Do not change trust to force a test.

## Measure before adopting

Use supported output from owned experiment sessions or authorized exported
records. Do not scan private session stores. Record version, source, effective
tool inventory, actual calls and first-assistant input plus cache-read/cache-write
tokens. Compare identical tasks and parent configuration. Report parent and child
usage separately, and both for full-workflow cost. A startup reduction does not
establish full-ticket savings. Missing auth or runtime usage means unmeasured,
not zero. Tool lists and hooks are context controls, not security boundaries.

References: [Claude agents](https://code.claude.com/docs/en/sub-agents),
[Claude skills](https://code.claude.com/docs/en/skills),
[Codex agents](https://developers.openai.com/codex/agent-configuration/subagents).
