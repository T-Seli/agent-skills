# Synthetic fixtures: identities and timestamps below are fabricated; no live source references.
import unittest

from agent_skills.approval_handoff import (authorization_check, retry_after_denial,
                                          transcript_evidence, worker_handoff,
                                          direct_confirmation_route, terms_from_platform_response,
                                          blocker_route, direct_worker_handoff,
                                          should_present_handoff)


def approval():
    return transcript_evidence(verified_human=True, source="messaging", platform="connected-chat",
                               channel_id="D0000000000",
                               thread_id="1000900381.889079", message_id="1000930156.088969",
                               user_id="example-user", exact_message="Approve deploy of revision 2 to staging only",
                               action="deploy", target="staging", scope="revision 2",
                               constraints=["staging only"], task_id="task-7", revision=2)


class ApprovalHandoffTests(unittest.TestCase):
    def test_platform_pending_terms_are_extracted_without_retaining_raw_response(self):
        import json
        parts = [{'action': 'deploy', 'target': 'production', 'scope': 'one commit',
                  'wording': 'Approve deployment?'}]
        raw = json.dumps({'task': {'id': 'task-7', 'session': 'session-1', 'pending': parts},
                          'unrelated_private_data': 'never retain'})
        result = terms_from_platform_response(raw, task_field='task.id',
                    session_field='task.session', parts_field='task.pending', source_ref='platform-read:fixture')
        self.assertEqual(result['parts'], parts)
        self.assertNotIn('never retain', repr(result))
        with self.assertRaises(ValueError):
            terms_from_platform_response(raw, task_field='task.id', session_field='task.session',
                                         parts_field='task.missing', source_ref='platform-read:fixture')

    def test_direct_route_follows_failed_relay_but_preserves_one_evidence_retry(self):
        base = dict(denial_reason='missing-authorization', evidence_check='covered-by-original-user-message',
                    prior_evidence_retries=0, direct_confirmation_required=True, verified_relay_failed=True,
                    new_sufficient_evidence=True)
        self.assertEqual(direct_confirmation_route(**base), 'retry-once-with-transcript-evidence')
        self.assertEqual(direct_confirmation_route(**{**base, 'prior_evidence_retries': 1}),
                         'handoff-direct-confirmation')
        self.assertEqual(direct_confirmation_route(**{**base, 'new_sufficient_evidence': False}),
                         'handoff-direct-confirmation')
        self.assertEqual(direct_confirmation_route(**{**base, 'verified_relay_failed': False,
                                                       'prior_evidence_retries': 1}), 'stop-and-report-platform-denial')
        self.assertEqual(direct_confirmation_route(**{**base, 'denial_reason': 'policy-denied',
                                                       'prior_evidence_retries': 1}), 'stop-and-report-platform-denial')

    def check(self, evidence, **changes):
        return authorization_check(evidence, **{**dict(task_id="task-7", revision=2,
            action="deploy", target="staging", scope="revision 2",
            constraints=["staging only"]), **changes})

    def test_valid_scoped_approval_is_carried_as_evidence(self):
        evidence = approval()
        self.assertEqual(self.check(evidence), "covered-by-original-user-message")
        packet = worker_handoff(evidence)
        self.assertEqual(packet["transcript_evidence"]["exact_message"],
                         "Approve deploy of revision 2 to staging only")
        self.assertEqual(packet["transcript_evidence"]["message_id"], "1000930156.088969")
        self.assertEqual(packet["transcript_evidence"]["platform"], "connected-chat")
        self.assertEqual(self.check(evidence, action_time_approval_required=True),
                         "platform-action-time-review-required")

    def test_insufficient_scope_and_third_party_relay_fail(self):
        evidence = approval()
        self.assertEqual(self.check(evidence, scope="all environments"),
                         "scope-or-constraints-out-of-scope")
        self.assertEqual(self.check(evidence, constraints=[]), "scope-or-constraints-out-of-scope")
        with self.assertRaises(ValueError):
            transcript_evidence(**{**dict(verified_human=False, source="messaging", platform="connected-chat",
                channel_id="C", thread_id="T", message_id="M", user_id="bot",
                exact_message="User said yes", action="deploy", target="staging",
                scope="revision 2", constraints=[], task_id="task-7", revision=2)})

    def test_changed_target_revision_and_material_change_fail(self):
        evidence = approval()
        self.assertEqual(self.check(evidence, target="production"), "action-or-target-out-of-scope")
        self.assertEqual(self.check(evidence, revision=3), "stale-task")
        self.assertEqual(self.check(evidence, material_change=True),
                         "material-change-requires-review")

    def test_altered_or_unsealed_evidence_fails_closed(self):
        for field, value in (("approved_target", "production"),
                             ("exact_message", "Approve everything"),
                             ("material_constraints", []), ("message_id", "changed")):
            with self.subTest(field=field):
                evidence = approval()
                evidence[field] = value
                self.assertEqual(self.check(evidence, **({"target": value} if field == "approved_target" else {})),
                                 "missing-or-changed-integrity-evidence")
                with self.assertRaises(ValueError):
                    worker_handoff(evidence)
        evidence = approval()
        evidence.pop("evidence_sha256", None)
        self.assertEqual(self.check(evidence), "missing-or-changed-integrity-evidence")
        with self.assertRaises(ValueError):
            worker_handoff(evidence)

    def test_integrity_is_consistency_not_authentication(self):
        evidence = approval()
        self.assertIn("evidence_sha256", evidence)
        self.assertEqual(len(evidence["evidence_sha256"]), 64)
        evidence["unexpected"] = object()
        self.assertEqual(self.check(evidence), "missing-or-changed-integrity-evidence")
        evidence = approval()
        evidence["original_user_verified"] = False
        self.assertEqual(self.check(evidence), "missing-authenticated-evidence")

    def test_denied_retry_is_bounded_to_one_evidence_attempt(self):
        self.assertEqual(retry_after_denial(denial_reason="missing-authorization",
                         evidence_check=self.check(approval()), prior_evidence_retries=0),
                         "retry-once-with-transcript-evidence")
        for reason, check, count in (("missing-authorization", self.check(approval()), 1),
                                     ("policy-denied", self.check(approval()), 0),
                                     ("missing-authorization", "stale-task", 0)):
            self.assertEqual(retry_after_denial(denial_reason=reason, evidence_check=check,
                                               prior_evidence_retries=count),
                             "stop-and-report-platform-denial")

    def test_blocker_classes_do_not_turn_capability_gaps_into_approval_requests(self):
        self.assertEqual(blocker_route(blocker_kind='disconnected-compute'),
                         'report-disconnected-compute')
        self.assertEqual(blocker_route(blocker_kind='unsupported-tool'),
                         'report-unsupported-tool')
        self.assertEqual(blocker_route(blocker_kind='missing-evidence'),
                         'collect-missing-evidence')
        self.assertEqual(blocker_route(blocker_kind='denied-authority'),
                         'stop-and-report-denied-authority')

    def test_existing_authority_is_relayed_before_direct_session_handoff(self):
        self.assertEqual(blocker_route(blocker_kind='missing-permission',
                         evidence_check='covered-by-original-user-message', relay_supported=True,
                         relay_attempted=False, direct_session_required=True),
                         'relay-exact-authorization')
        self.assertEqual(blocker_route(blocker_kind='missing-permission',
                         evidence_check='covered-by-original-user-message', relay_supported=True,
                         relay_attempted=True, direct_session_required=True),
                         'handoff-direct-session-approval')

    def handoff(self, **changes):
        values = dict(blocker_kind='wrong-execution-surface', direct_session_required=True,
                      verified_session=True, verified_title=True, verified_workspace=True,
                      platform='codex', task_title='Synthetic release review', task_id='task-7',
                      session_id='session-1', workspace='local workspace', action='publish',
                      target='reviewed source', scope='revision 2 only', revision=2,
                      wording='Approve publishing revision 2 only.', source_ref='platform:read-1',
                      current_surface='desktop', session_link='https://example.invalid/session-1',
                      link_platform='codex', link_verified=True)
        return direct_worker_handoff(**{**values, **changes})

    def test_direct_worker_handoff_has_verified_identity_and_surface_compatible_navigation(self):
        desktop = self.handoff()
        self.assertEqual(desktop['link'], 'https://example.invalid/session-1')
        self.assertIn('Synthetic release review', desktop['navigation'])
        for surface in ('ios', 'messaging'):
            packet = self.handoff(current_surface=surface)
            self.assertIsNone(packet['link'])
            self.assertIn('desktop', packet['navigation'])
        self.assertIsNone(self.handoff(session_link='javascript:invalid')['link'])
        with self.assertRaises(ValueError):
            self.handoff(verified_workspace=False)

    def test_duplicate_handoff_is_suppressed_but_a_new_revision_is_not(self):
        first = self.handoff()
        self.assertTrue(should_present_handoff(first, []))
        self.assertFalse(should_present_handoff(first, [first['fingerprint']]))
        refreshed = self.handoff(source_ref='platform:read-2',
                                 wording='Please approve publishing revision 2 only.')
        self.assertFalse(should_present_handoff(refreshed, [first['fingerprint']]))
        changed = self.handoff(revision=3, scope='revision 3 only',
                               wording='Approve publishing revision 3 only.')
        self.assertTrue(should_present_handoff(changed, [first['fingerprint']]))


if __name__ == "__main__":
    unittest.main()
