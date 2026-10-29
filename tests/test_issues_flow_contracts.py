"""Tracked tasks: issues are created, claimed, linked to a draft PR and closed on landing (workflow-contracts issues.md)."""
from pathlib import Path
import os
import unittest

ROOT = Path(__file__).resolve().parents[1]
def text(path): return (ROOT / path).read_text(encoding='utf-8')
ISSUES = 'skills/workflow-contracts/issues.md'


class OneHome(unittest.TestCase):
    def test_issues_md_holds_the_rules(self):
        rules = text(ISSUES)
        for rule in ('§ Map `Issues`', 'lands a code change', 'sub-issue', 'blocked-by', '## Parent', '## What to build',
                     '## Acceptance criteria', 'ready-for-agent', 'issues-cli', 'claim', '--approved',
                     'working copy', 'issue-text.md', 'Trunk flow', 'ICLI close', 'Closes #', 'draft PR', 'gh pr ready', 'never touch', 'Approved:'):
            self.assertIn(rule, rules)

    def test_contracts_template_and_global_point_to_it(self):
        git = text('skills/workflow-contracts/contracts.md').split('## Git', 1)[1].split('\n## ', 1)[0]
        self.assertIn('[issues.md](issues.md)', git)
        self.assertIn('- Issues:', text('skills/workflow-contracts/project-CLAUDE-template.md'))
        self.assertIn('or for tracked tasks', text('global/CLAUDE.md'))

    def test_entrypoint_is_bound_to_the_release(self):
        cli = ROOT / 'skills/workflow-contracts/scripts/issues-cli'
        self.assertTrue(os.access(cli, os.X_OK))
        self.assertIn('agent_skills.issues_cli', cli.read_text())


class StagesUseIt(unittest.TestCase):
    def test_each_stage_has_its_one_hook(self):
        hooks = {
            'skills/blueprint/SKILL.md': ('issues.md', '`#<n>`'),
            'skills/implement/SKILL.md': ('issues.md', 'ICLI publish', 'ICLI claim', 'Closes'),
            'skills/implement/references/spec-mode.md': ('issues.md', 'ICLI tick'),
            'skills/test-review/SKILL.md': ('gh pr ready',),
            'skills/deploy/SKILL.md': ('issues.md', 'closed', 'ICLI close'),
            'skills/agent-coordination/references/worker-execution.md': ('`Issue: #<n>`', 'never touch'),
        }
        for path, needles in hooks.items():
            for needle in needles:
                self.assertIn(needle, text(path), f'{path} lacks {needle}')


if __name__ == '__main__':
    unittest.main()
