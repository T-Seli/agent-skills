"""Mechanical output accounting and delivered contracts, not native behavior proof."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent_skills import Catalog
from agent_skills import evaluation_contract

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = 'skills/workflow-contracts/references/execution-proof.md'


class ReportMeasurement(unittest.TestCase):
    def measure(self, text, **limits):
        function = getattr(evaluation_contract, 'measure_report', None)
        self.assertTrue(callable(function), 'shared report cap measurement unavailable')
        return function(text, **limits)

    def test_full_reply_counts_headings_and_table_cells(self):
        result = self.measure('# Choice\n| Option | Result |\n| A | Saved |', max_words=5)
        self.assertEqual(result['words'], 5)
        self.assertTrue(result['within_caps'])
        self.assertFalse(self.measure(' '.join(['word'] * 251), max_words=250)['within_caps'])

    def test_line_and_word_limits_both_apply_without_trimming(self):
        result = self.measure('one\n\ntwo\n', max_words=2, max_lines=2)
        self.assertEqual(result, {'words': 2, 'lines': 3, 'within_caps': False})

    def test_apostrophes_hyphens_and_unicode_sequences(self):
        self.assertEqual(self.measure("Don't re-run café 42")['words'], 4)

    def test_empty_text_and_exact_boundary(self):
        self.assertEqual(self.measure('', max_words=0, max_lines=0),
                         {'words': 0, 'lines': 0, 'within_caps': True})
        self.assertTrue(self.measure('one two', max_words=2)['within_caps'])

    def test_invalid_limits_and_text_fail_explicitly(self):
        for value in [True, -1, 1.5, '250']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.measure('text', max_words=value)
        with self.assertRaises(ValueError):
            self.measure(None)


class ExecutionProofDelivery(unittest.TestCase):
    def test_affected_phases_deliver_one_shared_contract(self):
        catalog = Catalog(ROOT)
        for phase in ['company.blueprint', 'company.implement', 'company.tdd',
                      'company.test-review', 'company.ui-design']:
            with self.subTest(phase=phase):
                packet = catalog.load(phase, role='worker')
                sources = [s['path'] for s in packet['sources']]
                self.assertIn(REFERENCE, sources)
                self.assertEqual(sources.count(REFERENCE), 1)
        composed = catalog.compose(['company.implement', 'company.ui-design'], role='worker')
        self.assertEqual([s['path'] for s in composed['sources']].count(REFERENCE), 1)

    def test_targeted_cases_use_existing_semantic_contract(self):
        from agent_skills.evaluation_contract import validate_case
        path = ROOT / 'agent_skills/evaluations/execution-proof.json'
        self.assertTrue(path.is_file(), 'targeted regression scenarios missing')
        cases = json.loads(path.read_text())['cases']
        self.assertEqual(len(cases), 6)
        for case in cases:
            self.assertTrue(validate_case(case))
            packet = Catalog(ROOT).compose(case['required_skills'], role='worker')
            self.assertIn(REFERENCE, {s['path'] for s in packet['sources']})

    def test_contract_drift_invalidates_loaded_packet_and_review_policy(self):
        from agent_skills.github_migration import policy_identity
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            catalog = Catalog(root)
            packet = catalog.load('company.implement', role='worker')
            before = policy_identity(root)[0]
            path = root / REFERENCE
            path.write_text(path.read_text() + '\nChanged synthetic acceptance.\n')
            self.assertFalse(catalog.fresh(packet))
            self.assertNotEqual(policy_identity(root)[0], before)


if __name__ == '__main__':
    unittest.main()
