"""Shared skill text: handoff route/session lines, question cadence default and consent scope."""
import re
import json
import os
import subprocess
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
def text(path): return (ROOT / path).read_text(encoding='utf-8')
CONTRACTS = 'skills/workflow-contracts/contracts.md'


class HandoffTemplate(unittest.TestCase):
    def template(self):
        return re.search(r'## Template\n```\n(.*?)```', text('skills/handoff/SKILL.md'), re.S).group(1)

    def test_route_access_and_session_lines_are_in_the_template(self):
        lines = self.template().splitlines()
        route = next(x for x in lines if x.startswith('Route & access:'))
        for field in ('owned by', 'requested', 'ceiling', 'observed <model | unknown>/<effort | unknown>',
                      'auth context', 'readiness', 'missing:', 'limits:'):
            self.assertIn(field, route)
        session = next(x for x in lines if x.startswith('Session:'))
        self.assertIn('fresh', session)
        self.assertIn('authorized resume', session)
        self.assertIn('do not resume, continue or take it over', session)

    def test_filled_non_git_handoff_fits_the_cap_with_unknown_effort(self):
        filled = []
        for line in self.template().splitlines():
            if line.startswith('Recent commits'):
                continue  # dropped outside a git repo
            if line.startswith('Route & access:'):
                line = ('Route & access: source s-1 owned by worker-a · requested claude-opus-5-5/medium (ceiling high)'
                        ' · observed claude-opus-5-5/unknown · environment normal-mac, auth context mac-user,'
                        ' readiness readiness:normal-mac 10m · missing: db:fixture · limits: effort not exposed')
            filled.append(re.sub(r'<[^>]*>', 'fixture value', line))
        block = '\n'.join(filled)
        self.assertIn('/unknown', block)
        self.assertLessEqual(len(filled), 40)
        self.assertLessEqual(len(block.split()), 450)


class DataAccessReadiness(unittest.TestCase):
    def test_scout_readiness_gate_applies_only_to_declared_capabilities(self):
        habits = text('skills/workflow-contracts/data-access.md').split('## Habits', 1)[1]
        line = next(x for x in habits.splitlines() if 'readiness' in x)
        self.assertNotIn('Brief a scout only after', line)  # unconditional gate on every scout
        self.assertIn('declares', line)
        for kept in ('missing, stale or mismatched', 'never grants', 'Never probe or create access'):
            self.assertIn(kept, line)


class QuestionsAndConsent(unittest.TestCase):
    def test_round_size_is_a_proposed_configurable_default(self):
        defaults = text(CONTRACTS).split('## Defaults', 1)[1]
        line = next(x for x in defaults.splitlines() if x.startswith('- Question round size:'))
        self.assertIn('1–3', line)
        self.assertIn('proposed', line)
        for path in ('skills/workflow-contracts/decisions.md', 'skills/grill-me/SKILL.md'):
            body = text(path)
            self.assertIn('`Question round size`', body)
            self.assertNotIn('normally one to three', body)

    def test_bare_approval_and_named_steps_do_not_conflict(self):
        body = text(CONTRACTS)
        self.assertNotIn('applies only to its concrete pending action', body)
        self.assertNotIn('to the end of the chain', body)
        consent = body.split('## Consent', 1)[1].split('##', 1)[0]
        self.assertIn('covers the concrete pending gated step', consent)
        self.assertIn('covers every step it names', consent)
        self.assertIn("don't ask again or per step", consent)


class DepthNotBreadth(unittest.TestCase):
    def test_global_rule_and_shared_contract_reach_the_execution_detail(self):
        global_rule = text('global/CLAUDE.md')
        self.assertIn('Depth, not breadth', global_rule)
        self.assertIn('workflow-contracts/behavior.md', global_rule)
        self.assertIn('then [behavior.md](behavior.md)', text(CONTRACTS))
        self.assertLessEqual(len(global_rule.split()), 600)
        self.assertLessEqual(len(text(CONTRACTS).splitlines()), 90)

    def test_original_rewrite_request_is_preserved_with_its_scope_boundary(self):
        body = text('skills/workflow-contracts/behavior.md')
        original = "I want a deeper version of this task, not a bigger one. Before rewriting it: (1) say what a top professional in this field would do here that I’m not asking for; (2) name the rawest material they would start from instead of what has already been digested for me; (3) name the specific methods and tools they would use; (4) say what, other than you or me, would show the result is right. Then rewrite my prompt to ask for exactly that."
        self.assertIn(original, body)
        for boundary in ('Rewrite a prompt only when asked', 'primary evidence',
                         'independent observable check', 'never probe denied access',
                         'Preserve privacy, exclusions, settled decisions and all permission gates'):
            self.assertIn(boundary, body)

    def test_every_catalog_consumer_actually_loads_the_shared_rule(self):
        catalog = json.loads(text('agent_skills/catalog.json'))
        for skill in catalog['skills']:
            for role in skill['roles']:
                with self.subTest(skill=skill['id'], role=role):
                    run = subprocess.run(
                        ['python3', '-m', 'agent_skills', 'load', '--role', role, skill['id']],
                        cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    sources = json.loads(run.stdout)['sources']
                    detail = [s for s in sources if s['path'] == 'skills/workflow-contracts/behavior.md']
                    self.assertEqual(len(detail), 1)
                    self.assertIn('## Depth, not breadth', detail[0]['content'])

    def test_isolated_installer_delivers_rule_and_detail_to_both_adapters(self):
        with tempfile.TemporaryDirectory() as home:
            run = subprocess.run([str(ROOT / 'install.sh')], cwd=ROOT,
                                 env=dict(os.environ, HOME=home), capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            for global_path, skills_path in (
                ('.claude/CLAUDE.md', '.claude/skills'),
                ('.codex/AGENTS.md', '.agents/skills'),
            ):
                with self.subTest(adapter=global_path):
                    self.assertIn('Depth, not breadth', (Path(home) / global_path).read_text())
                    self.assertIn('workflow-contracts/behavior.md', (Path(home) / global_path).read_text())
                    contracts = Path(home) / skills_path / 'workflow-contracts'
                    self.assertIn('then [behavior.md](behavior.md)', (contracts / 'contracts.md').read_text())
                    self.assertEqual((contracts / 'behavior.md').read_text(),
                                     text('skills/workflow-contracts/behavior.md'))


if __name__ == '__main__':
    unittest.main()
