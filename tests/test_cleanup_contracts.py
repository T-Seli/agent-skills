"""Skill text for worktree ownership marks, cleanup unlock rules and the machine-wide test cap."""
import json
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


class WorktreeSweep(unittest.TestCase):
    def test_deploy_cleans_other_worktrees_with_the_sweep(self):
        others = next(l for l in text('skills/deploy/SKILL.md').splitlines() if l.startswith('2. **Others**'))
        self.assertRegex(others, r'safeguard-cli.* sweep .*--apply')

    def test_prime_context_reports_the_dry_run_count_and_never_applies(self):
        stale = next(l for l in text('skills/prime-context/SKILL.md').splitlines() if '**Stale**' in l)
        self.assertRegex(stale, r'sweep .*dry run')
        self.assertNotIn('--apply', stale)

    def test_contracts_exempts_the_sweep_from_never_deleted_by_a_skill(self):
        stale = next(l for l in text(CONTRACTS).splitlines() if l.startswith('- **Stale**'))
        self.assertIn('sweep', stale)

    def test_example_config_lists_worktree_lease_files(self):
        config = json.loads(text('agent_skills/delegate_config.example.json'))
        self.assertEqual(config['worktree_lease_files'], [])


class TestSlotRoute(unittest.TestCase):
    def test_contracts_routes_run_and_test_commands_through_the_slot(self):
        line = next(l for l in text(CONTRACTS).splitlines() if l.startswith('- Sections, read by name'))
        self.assertIn("safeguard-cli test-slot '<cmd>'", line)
        self.assertIn('75', line)

    def test_example_config_sets_the_default_slot_count(self):
        self.assertEqual(json.loads(text('agent_skills/delegate_config.example.json'))['test_slots'], 2)
