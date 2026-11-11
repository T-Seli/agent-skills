import copy
import unittest
from agent_skills.observation_evidence import assess_coverage
from agent_skills.system_audit import monitoring_verdict


def evidence():
    return {'requested': {'start': '2026-11-06T12:00:00Z', 'end': '2026-11-06T12:15:00Z'},
            'observed': {'start': '2026-11-06T12:00:00Z', 'end': '2026-11-06T12:15:00Z'},
            'source_observed_at_utc': '2026-11-06T12:15:00Z', 'source_identity': 'source:revision-1',
            'runtime_identity': 'reader:revision-1', 'state': 'verified', 'cap_seconds': None,
            'truncated': False, 'max_source_age_seconds': 60, 'receipt_ref': 'read:source-1'}


class SourceCoverageTests(unittest.TestCase):
    def verdict(self, value, now='2026-11-06T12:15:10Z'):
        return monitoring_verdict(wake_receipt='wake:1', readback_receipt='read:task',
            expires_at_utc='2026-11-06T13:00:00Z', observed_at_utc=now,
            traffic_count=2, functional_results=[True], coverage=value)

    def test_full_window_and_five_second_cap_are_distinct(self):
        p=evidence(); self.assertEqual(self.verdict(p)['functional_acceptance'], 'passed')
        p['observed']['end']='2026-11-06T12:00:05Z'; p['cap_seconds']=5
        result=self.verdict(p)
        self.assertEqual(result['source_coverage']['state'], 'partial')
        self.assertEqual(result['functional_acceptance'], 'unverified')

    def test_unavailable_truncated_missing_identity_or_stale_source_cannot_pass(self):
        for change in ({'state':'blocked','observed':None}, {'state':'failed'}, {'state':'unknown'},
                       {'truncated':True}, {'source_identity':None}):
            p={**evidence(), **change}
            self.assertEqual(self.verdict(p)['functional_acceptance'], 'unverified')
        p=evidence();before=copy.deepcopy(p)
        result=self.verdict(p, '2026-11-06T12:30:00Z')
        self.assertEqual(result['source_coverage']['reason'], 'source observation stale')
        self.assertEqual(p,before)

    def test_impossible_cap_or_naive_timestamp_refuses(self):
        p=evidence();p['cap_seconds']=5
        with self.assertRaises(ValueError):self.verdict(p)
        p=evidence();p['source_observed_at_utc']='2026-11-06T12:15:00'
        with self.assertRaises(ValueError):self.verdict(p)
