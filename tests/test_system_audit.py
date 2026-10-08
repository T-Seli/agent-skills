import unittest

from agent_skills.system_audit import (audit_artifact, blocker_update, failure_incident,
                                       finding, synthesize, synthesize_failures)


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


def failure(**changes):
    values = dict(incident_id='incident-1', failure_key='transport:message-edit',
                  operation='edit messaging compact header', target='audit thread header',
                  failure_class='transport-offline', source_receipt='tool:message-edit:error-1',
                  occurred_at='2026-10-08T01:00:00Z',
                  user_impact='The requested status was not visible.',
                  authorization_state='not-required', approved_scope=None, approval_ref=None,
                  retries_attempted=['one bounded retry returned the same error'],
                  evidence_attempted=['read the exact tool error receipt'], outcome='failed',
                  next_supported_action='Reconcile message state, then retry once after transport recovery.',
                  owner='audit-orchestrator', next_action_mode='agent-supported',
                  prevention_check='A fixture reports one grouped failure and preserves both receipts.',
                  verified=True)
    return failure_incident(**{**values, **changes})


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
        ledger = synthesize_failures([failure()])
        artifact = audit_artifact(
            audit_id='audit-20261008', revision=1, scope_ref='task:scope-1',
            window_start='2026-10-07T00:00:00Z', window_end='2026-10-08T00:00:00Z',
            prior_artifact_ref=None, record_owner='history-owner', history_revision=7,
            history_digest='a' * 64, synthesis=synthesis, failure_ledger=ledger)
        self.assertEqual(artifact['history_publication'], 'proposed-not-appended')
        self.assertEqual(artifact['history_base']['revision'], 7)
        self.assertEqual(artifact['failure_ledger'][0]['failure_key'], 'transport:message-edit')
        with self.assertRaises(ValueError):
            audit_artifact(audit_id='audit-20261008', revision=1, scope_ref='task:scope-1',
                window_start='2026-10-07T00:00:00Z', window_end='2026-10-08T00:00:00Z',
                prior_artifact_ref=None, record_owner='history-owner', history_revision=7,
                history_digest='a' * 64, synthesis=synthesis, failure_ledger=[failure()])

    def test_failure_ledger_accepts_the_required_verified_classes(self):
        cases = {
            'messaging-generic-retry': 'transport-offline',
            'mac-exec-disconnect': 'transport-offline',
            'release-pause-race': 'implementation-defect',
            'tool-limit-100-vs-50': 'invalid-arguments',
            'unsupported-model': 'unsupported-operation',
            'short-read-dropped-progress': 'implementation-defect',
            'child-tool-disappeared': 'unavailable-tool',
            'unsupported-placement-format': 'stale-session-placement',
            'old-session-not-found': 'stale-session-id',
        }
        for incident_id, failure_class in cases.items():
            with self.subTest(incident_id=incident_id):
                result = failure(incident_id=incident_id, failure_key=incident_id,
                                 failure_class=failure_class,
                                 source_receipt=f'tool:{incident_id}:receipt')
                self.assertEqual(result['failure_class'], failure_class)
                self.assertTrue(result['verified'])
        with self.assertRaises(ValueError):
            failure(verified=False)
        with self.assertRaises(ValueError):
            failure(source_receipt='')
        with self.assertRaises(ValueError):
            failure(occurred_at='not-a-time')

    def test_direct_approval_replaces_approval_blocker_with_current_capability(self):
        prior = failure(
            incident_id='handoff-approval-rejected', failure_key='handoff:alert-tuning',
            operation='forward alert-tuning context', target='verified child task',
            failure_class='missing-approval-provenance',
            authorization_state='missing-provenance',
            source_receipt='child:rejection-2', occurred_at='2026-10-08T01:00:00Z',
            next_supported_action='Authenticate the original scoped user message.')
        current = failure(
            incident_id='handoff-tool-unavailable', failure_key='handoff:alert-tuning-capability',
            operation='forward alert-tuning context', target='verified child task',
            failure_class='unavailable-tool', authorization_state='verified-covered',
            approved_scope='Forward the preserved alert-tuning report to this child only.',
            approval_ref='user-item:01a119bc-44cf-727c-a876-c681e10eefd0',
            source_receipt='child:task-messaging-tool-missing',
            occurred_at='2026-10-08T01:05:00Z',
            next_supported_action='Restore the supported task-messaging capability or report the capability gap.',
            next_action_mode='human-only',
            human_action='Open a supported session that exposes task messaging and resume from the preserved report.')
        transition = blocker_update(prior, current)
        self.assertEqual((transition['decision'], transition['blocker_domain']),
                         ('replace-blocker', 'capability'))
        self.assertFalse(transition['ask_user_to_approve_again'])
        self.assertFalse(transition['claim_operation_succeeded'])
        stale_session = failure(
            incident_id='parent-old-session-not-found', failure_key='handoff:old-session',
            operation='forward alert-tuning context', target='verified older task session',
            failure_class='stale-session-id', authorization_state='verified-covered',
            approved_scope='Forward the preserved alert-tuning report to this child only.',
            approval_ref='user-item:01a119bc-44cf-727c-a876-c681e10eefd0',
            source_receipt='cloud-thread:CloudThreadNotFoundError',
            occurred_at='2026-10-08T01:06:00Z',
            next_supported_action='Refresh the supported session identity before any bounded retry.')
        stale_placement = failure(
            incident_id='placement-format-unsupported', failure_key='handoff:placement-format',
            operation='read alert-tuning task context', target='original task placement',
            failure_class='stale-session-placement', authorization_state='verified-covered',
            approved_scope='Read the original alert-tuning task context for this handoff only.',
            approval_ref='user-item:01a119bc-44cf-727c-a876-c681e10eefd0',
            source_receipt='cloud-thread:unsupported-placement-format-v1',
            occurred_at='2026-10-08T00:59:00Z',
            next_supported_action='Use a supported placement reader or report the placement capability gap.')
        grouped = synthesize_failures([current, stale_session, stale_placement])
        self.assertEqual({x['failure_class'] for x in grouped},
                         {'unavailable-tool', 'stale-session-id', 'stale-session-placement'})
        with self.assertRaises(ValueError):
            failure(failure_class='missing-approval-provenance',
                    authorization_state='verified-covered', approved_scope='same scope',
                    approval_ref='user:item-1')
        with self.assertRaises(ValueError):
            failure(failure_class='unavailable-tool', authorization_state='verified-covered',
                    approved_scope='same scope', approval_ref='user:item-1',
                    next_supported_action='Ask the user for approval again.')
        with self.assertRaises(ValueError):
            failure(failure_class='missing-approval-provenance',
                    authorization_state='incorrect-provenance')
        with self.assertRaises(ValueError):
            failure(failure_class='unavailable-tool',
                    authorization_state='missing-provenance')

    def test_guards_are_respected_and_human_only_steps_are_explicit(self):
        with self.assertRaises(ValueError):
            failure(failure_class='legitimate-policy-limit', authorization_state='policy-denied',
                    next_supported_action='Bypass the policy guard and retry.')
        with self.assertRaises(ValueError):
            failure(next_action_mode='human-only')
        human = failure(next_action_mode='human-only',
                        human_action='Reconnect the supported local executor, then resume the preserved task.')
        self.assertEqual(human['next_action_mode'], 'human-only')
        self.assertEqual(human['remedy_kind'], 'retry-transport-after-reconcile')

    def test_failures_dedupe_identical_receipts_but_count_real_repeats(self):
        first = failure(prevention_state='passed', prevention_receipt='test:transport-recovery-1')
        repeat = failure(incident_id='incident-2', repeat_of='incident-1',
                         source_receipt='tool:message-edit:error-2',
                         occurred_at='2026-10-08T02:00:00Z',
                         prevention_state='failed', prevention_receipt='test:transport-recovery-2')
        grouped = synthesize_failures([repeat, repeat], prior_incidents=[first])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]['occurrence_count'], 2)
        self.assertEqual(grouped[0]['current_occurrence_count'], 1)
        self.assertEqual(grouped[0]['repeat_count'], 1)
        self.assertTrue(grouped[0]['recurrence_after_pass'])
        self.assertEqual(grouped[0]['prevention_status'], 'recurrence-observed-after-pass')
        with self.assertRaises(ValueError):
            synthesize_failures([failure(incident_id='incident-2',
                                         occurred_at='2026-10-08T02:00:00Z')],
                                prior_incidents=[first])
        with self.assertRaises(ValueError):
            synthesize_failures([repeat], prior_incidents=[failure(
                incident_id='incident-2', source_receipt='different-receipt')])

    def test_prevention_results_require_receipts_and_do_not_overclaim(self):
        with self.assertRaises(ValueError):
            failure(prevention_state='passed')
        passed = failure(prevention_state='passed', prevention_receipt='test:fix-1')
        grouped = synthesize_failures([passed])
        self.assertEqual(grouped[0]['prevention_status'],
                         'passed-in-window-no-later-recurrence-observed')


if __name__ == '__main__':
    unittest.main()
