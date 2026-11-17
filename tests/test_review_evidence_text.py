"""Review evidence rule: PR diff scope and hosted green check as test evidence."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def text(path): return (ROOT / path).read_text(encoding='utf-8')
def flat(path): return re.sub(r'\s+', ' ', text(path))
SKILL = 'skills/test-review/SKILL.md'
HOSTED = 'skills/test-review/references/hosted-review.md'


class ReviewEvidenceText(unittest.TestCase):
    def test_pr_diff_must_be_subset_of_merge_base_and_stack_retargeted(self):
        t = flat(SKILL)
        self.assertIn('diff must be a subset of `merge-base..head`', t)
        self.assertIn('retargeted to the integration branch before merge', t)

    def test_hosted_green_on_exact_head_replaces_local_rerun_of_same_suite(self):
        t = flat(HOSTED)
        self.assertIn('green hosted check on the exact head SHA', t)
        self.assertIn('replaces rerunning that same suite locally', t)
        self.assertNotIn('Matching evidence may replace the same aggregate run', t)

    def test_hosted_evidence_limits_stay(self):
        t = flat(HOSTED)
        for limit in ('no hosted check exists', 'a different SHA', 'excludes the changed area',
                      'consent, deploy or monitoring'):
            self.assertIn(limit, t)

    def test_size_budgets_and_banned_names(self):
        self.assertLessEqual(len(text(SKILL).splitlines()), 100)
        self.assertLessEqual(len(text(HOSTED).splitlines()), 80)
        self.assertNotIn('Sl' + 'ack', text(SKILL) + text(HOSTED))


if __name__ == '__main__':
    unittest.main()
