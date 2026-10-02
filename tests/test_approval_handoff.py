import unittest

from agent_skills.approval_handoff import (authorization_check, retry_after_denial,
                                          transcript_evidence, worker_handoff)


def approval():
    return transcript_evidence(verified_human=True, source="messaging", platform="connected-chat",
                               channel_id="D0C5GPRESBG",
                               thread_id="1790900381.889079", message_id="1790930156.088969",
                               user_id="example-user", exact_message="Approve deploy of revision 2 to staging only",
                               action="deploy", target="staging", scope="revision 2",
                               constraints=["staging only"], task_id="task-7", revision=2)


class ApprovalHandoffTests(unittest.TestCase):
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
        self.assertEqual(packet["transcript_evidence"]["message_id"], "1790930156.088969")
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


if __name__ == "__main__":
    unittest.main()
