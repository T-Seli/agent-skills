# Research-backed v0 decisions (2026-10-02)

This is a local review candidate. No active profile was installed, no worker was
launched by the catalog, and no Dot loading was inferred from this code.

| Area | Adopted in v0 | Deferred and why |
| --- | --- | --- |
| Portable package | Bounded, inert catalog discovery; strict JSON keys, contained regular files, no symlinks, package resource hashes and stale-bundle checks. Hashes identify bytes, not trusted authors. | Running bundled scripts, hooks, remote fetches or an automatic installer; those create authority and side effects beyond preview. |
| Host contracts | Catalog-qualified proposed export names and explicit per-host loading status. Layer names stay catalog concepts. | Automatic host export and native activation pending an isolated real-host check. Claude's enterprise/personal/project precedence differs from the generic client guidance; Codex duplicate names can coexist. |
| Task evidence | Revisioned packet, one execution owner, exact source/package pins, checkpoint, completion evidence and structured milestone records. All are pure local data transformations. | Live Dot synchronization or dispatch. An unknown external outcome requires reconciliation with the target before retry. |
| Evaluation | Case/trial schemas separate implicit selection from explicit execution, record observable results and safety invariants, and support paired review against incumbent or no-target-skill. | Paid native trials, universal outcome thresholds and a large benchmark. No fixture proves live model behavior. |
| Improvement | Proposal and paired results end at human review, with hashes binding candidate, baseline and evaluator. | Automatic acceptance, grader modification by candidate, production rollout. Rollback means restoring the exact approved bundle, not selecting a similar name. |

## Source checks

- [Agent Skills format](https://agentskills.io/specification) permits optional scripts and `allowed-tools`, but `allowed-tools` is preapproval rather than isolation. Our v0 reads and hashes those resources without executing them.
- [Claude Code skill loading](https://code.claude.com/docs/en/skills) documents enterprise over personal over project for duplicate names, live skill text refresh, dynamic `!` commands, and permission grants from `allowed-tools`. The catalog rejects dynamic shell metadata and authority fields for native packages.
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents) describes versioned agent and fork behavior. Worker-owned subagents are a host capability to verify, not a universal prohibition or guarantee.
- [Anthropic's agent evaluation guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) distinguishes outcome checks and evidence from a model's own claim. [OpenAI's skill eval guide](https://developers.openai.com/blog/eval-skills) includes negative selection cases and baseline comparisons. That supports separate selection counts and paired behavioral review.
- [SLSA artifact verification](https://slsa.dev/spec/v1.2/verifying-artifacts) motivates pinning the exact artifact and its dependencies; a digest match alone does not establish provenance or policy approval.

## Review and native test gate

The unit suite checks local contracts only. A separate 2026-10-02 synthetic
project test observed Codex CLI 0.149.0 load the qualified `company-blueprint`
skill explicitly and implicitly, with the implicit command trace opening
`SKILL.md` and its references. After CLI login, Claude Code CLI 2.1.287 also
loaded it explicitly and implicitly; the implicit trace records a `Skill` tool
call. The Claude run used project settings and an empty strict MCP list with
code execution and edits denied. `--restricted` hid the project skill in a
separate negative probe. For Dot,
first identify a supported skill installation or import mechanism and test a
snapshot; MCP skill import must not be described as live repo loading. Record
host version, profile path, invocation, observed loading evidence and outcome.
Do not touch the active profile or claim production readiness from the local
tests.
