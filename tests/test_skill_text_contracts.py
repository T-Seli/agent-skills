"""Shared skill text: handoff route/session lines, question cadence default and consent scope."""
import re
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


if __name__ == '__main__':
    unittest.main()
