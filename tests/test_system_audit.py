import unittest

from agent_skills.system_audit import audit_artifact, finding, synthesize


SOURCES = [{'source': 'task-record', 'state': 'observed', 'receipt_ref': 'task:receipt-4'}]


def item(**changes):
    values = dict(finding_id='cursor-pagination', finding_key='evidence-cursor',
                  angle='execution-context', claim_level='observed',
                  cause_basis='observed-root-cause', confidence='high',
                  assertion='pagination-incomplete', evidence_window='2026-10-07/2026-10-08',
                  scope_ref='task:scope-1', evidence_refs=['task:receipt-2'],
                  impact='A result could be missed.', counterevidence='The latest page was read.',
                  minimal_remedy='Page to the last consumed receipt.',
                  regression_risk='An extra bounded read.',
                  acceptance_test='A replay finds the prior receipt before reporting no result.',
                  conclusion='Pagination stopped before the prior receipt.',
                  outcome_signal='missed-evidence')
    return finding(**{**values, **changes})


class SystemAuditTests(unittest.TestCase):
    def test_incomplete_evidence_is_a_coverage_gap_not_an_observed_cause(self):
        with self.assertRaises(ValueError):
            item(evidence_refs=[])
        gap = item(claim_level='coverage-gap', evidence_refs=[],
                   cause_basis='not-established', confidence='low',
                   conclusion='The protected source was unavailable.')
        unavailable = [{'source': 'protected-session', 'state': 'unavailable',
                        'receipt_ref': 'capability:not-exposed'}]
        self.assertEqual(synthesize([gap], source_manifest=unavailable)['coverage_complete'], False)
        with self.assertRaises(ValueError):
            synthesize([], source_manifest=[])

    def test_conflicting_reviewers_remain_disputed(self):
        left = item()
        right = item(angle='capability-release', assertion='pagination-complete',
                     conclusion='The source was fully paginated.',
                     evidence_refs=['task:receipt-3'])
        result = synthesize([left, right], source_manifest=SOURCES)
        self.assertEqual(result['findings'][0]['state'], 'disputed')
        self.assertEqual(result['findings'][0]['reviewer_count'], 2)

        prior = item()
        with_prior = synthesize([left, right], source_manifest=SOURCES,
                                prior_findings=[prior])
        self.assertEqual(with_prior['findings'][0]['state'], 'disputed')
        self.assertEqual(with_prior['unchanged'], [])

    def test_repeated_unchanged_audit_reuses_prior_finding(self):
        prior = item(acceptance_state='failed', acceptance_receipt='audit:test-1')
        current = item(evidence_refs=['task:new-receipt'], evidence_window='next-day',
                       minimal_remedy='Equivalent remedy phrased differently.',
                       acceptance_state='failed', acceptance_receipt='audit:test-2')
        result = synthesize([current], source_manifest=SOURCES, prior_findings=[prior])
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['unchanged'][0], {
            'finding_key': 'evidence-cursor', 'prior_finding_id': 'cursor-pagination',
            'evidence_windows': ['next-day'], 'current_evidence_refs': ['task:new-receipt'],
            'acceptance_states': ['failed'], 'acceptance_receipts': ['audit:test-2']})

    def test_coverage_and_acceptance_claims_require_receipts(self):
        with self.assertRaises(ValueError):
            synthesize([], source_manifest=[{'source': 'task-record', 'state': 'observed',
                                             'receipt_ref': None}])
        with self.assertRaises(ValueError):
            item(acceptance_state='passed')
        with self.assertRaises(ValueError):
            item(acceptance_state='invented')

    def test_direct_user_worker_instruction_requires_source_and_scope(self):
        verified = item(direct_user_instruction=True, source_authenticated=True,
                        scope_matches=True, conclusion='Instruction is authoritative in scope.')
        self.assertEqual(verified['claim_level'], 'observed')
        unverified = item(direct_user_instruction=True, source_authenticated=False,
                          scope_matches=True)
        self.assertEqual(unverified['claim_level'], 'coverage-gap')
        self.assertEqual((unverified['source_authenticated'], unverified['scope_matches']),
                         (False, True))

    def test_cross_session_restriction_is_a_known_limit(self):
        limited = item(angle='capability-release', claim_level='known-platform-limit',
                       cause_basis='known-platform-limit', confidence='high',
                       evidence_refs=['capability:read-not-exposed'],
                       conclusion='Cross-session body reading is not exposed.')
        self.assertEqual(limited['claim_level'], 'known-platform-limit')

    def test_durable_artifact_binds_scope_window_history_base_and_proposal_state(self):
        synthesis = synthesize([item()], source_manifest=SOURCES)
        artifact = audit_artifact(
            audit_id='audit-20261008', revision=1, scope_ref='task:scope-1',
            window_start='2026-10-07T00:00:00Z', window_end='2026-10-08T00:00:00Z',
            prior_artifact_ref=None, record_owner='history-owner', history_revision=7,
            history_digest='a' * 64, synthesis=synthesis)
        self.assertEqual(artifact['history_publication'], 'proposed-not-appended')
        self.assertEqual(artifact['history_base']['revision'], 7)


if __name__ == '__main__':
    unittest.main()
