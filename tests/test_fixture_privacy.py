"""Scoped source-fixture guard; not a universal secret scanner or live validation."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ('test_approval_handoff.py', 'test_hub.py', 'test_nav.py', 'test_system_audit.py',
            'test_agent_coordination.py')
UUID = re.compile(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', re.I)
SYNTHETIC_UUID = re.compile(r'00000000-0000-4000-8000-[0-9]{12}')


class FixturePrivacy(unittest.TestCase):
    def test_public_regression_guide_retains_private_provenance_without_identifier(self):
        body = (ROOT/'skills/agent-coordination/references/friction-regressions.md').read_text()
        self.assertIn('privately retained provenance reference', body)
        self.assertEqual(UUID.findall(body), [])

    def test_fixture_identifiers_are_explicitly_synthetic_and_format_valid(self):
        for name in FIXTURES:
            body = (ROOT/'tests'/name).read_text()
            with self.subTest(file=name):
                self.assertIn('Synthetic fixtures:', body)
                self.assertEqual(re.findall(r'\b01[0-9a-f]{6}\b', body, re.I), [])
                for value in UUID.findall(body):
                    self.assertRegex(value, SYNTHETIC_UUID)
                for value in re.findall(r'\b[CDG][A-Z0-9]{10,}\b', body):
                    if any(c.isdigit() for c in value):
                        self.assertEqual(value, 'D0000000000')

    def test_timestamp_and_permalink_fixtures_use_the_declared_synthetic_epoch(self):
        for name in FIXTURES:
            tree = ast.parse((ROOT/'tests'/name).read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                value = node.value
                if isinstance(value, str):
                    seconds = re.findall(r'(?<![A-Za-z0-9])([0-9]{10})(?:\.[0-9]{1,6})?(?![0-9])', value)
                    seconds += re.findall(r'p([0-9]{10})[0-9]{6}(?![0-9])', value)
                elif type(value) in (int, float) and 1_000_000_000 <= value < 10_000_000_000:
                    seconds = [str(int(value))]
                else:
                    continue
                for second in seconds:
                    with self.subTest(file=name, line=node.lineno):
                        self.assertTrue(second.startswith('100'), 'fixture epoch must be synthetic')


if __name__ == '__main__':
    unittest.main()
