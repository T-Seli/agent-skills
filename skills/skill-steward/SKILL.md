---
name: skill-steward
description: 'Choose, evaluate and improve shared skills from observed task outcomes. Use for skill feedback, skill selection design, regression fixtures or reviewed skill changes.'
argument-hint: '<skill, observation and expected behavior>'
---

# Skill steward

Read `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md` first. Use the
local catalog as a compact index; load only the selected skill body and its
declared dependencies. Treat catalog matches as suggestions, not authority.

1. Qualify the task and the owner role. If no skill clearly fits, explain the
   gap instead of forcing a match. Choose the smallest useful combination.
2. At a retrospective per `${CLAUDE_SKILL_DIR}/../workflow-contracts/decisions.md`, compare requested outcomes with actual evidence, unresolved obligations and counterevidence; propose the smallest correction. Preserve the current body hash, observed behavior, evidence references and
   expected behavior in a change proposal. Do not paste private transcripts or
   credentials into the proposal.
3. Prefer an executable check for a mechanical recurring failure; use guidance for judgment calls. Add a regression fixture that shows the intended selection or behavior.
   Compare it with the current version and run relevant tests.
4. Ask a human reviewer to decide whether the evidence warrants a change.
   A proposed or passing change is not automatically adopted.
5. Commit an accepted change separately, pin its commit for users, and keep the
   prior commit as the rollback point. Recheck outcomes after use.

Report the proposal, evidence, tests, review decision and pinned versions.
No message, install, deploy or model change follows merely from a proposal.
