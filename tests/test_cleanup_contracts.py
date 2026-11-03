"""Skill text for worktree ownership marks, cleanup unlock rules and the machine-wide test cap."""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
def text(path): return (ROOT / path).read_text(encoding='utf-8')
CONTRACTS = 'skills/workflow-contracts/contracts.md'


class WorktreeOwnership(unittest.TestCase):
    def test_implement_locks_its_worktree_with_an_owner_reason(self):
        self.assertIn('worktree add --lock --reason "<agent> <branch> <UTC time>"', text('skills/implement/SKILL.md'))

    def test_test_review_locks_and_cleans_its_temp_base_by_run_id(self):
        review = text('skills/test-review/SKILL.md')
        self.assertIn('--lock --reason "test-review <run-id>"', review)
        self.assertRegex(review, r'cleanup .*--run-id <run-id>')
        self.assertRegex(review, r'restore.*tests')

    def test_deploy_unlocks_on_the_gate_and_deletes_branches_only_on_ancestor(self):
        deploy = text('skills/deploy/SKILL.md')
        self.assertIn('`unlock: true`', deploy)
        self.assertIn('`merge: ancestor`', deploy)
        self.assertIn('--rebuildable', deploy)

    def test_contracts_and_template_name_the_run_id_and_rebuildable_dirs(self):
        self.assertIn('--run-id', next(l for l in text(CONTRACTS).splitlines() if l.startswith('- Temp worktrees')))
        self.assertIn('; rebuildable: <dirs>', text('skills/workflow-contracts/project-CLAUDE-template.md'))
