import unittest

from agent_skills.task_contract import (assess_completion, checkpoint, consume_milestone,
                                        milestone, packet, resume_check, validate_checkpoint,
                                        validate_packet)

H = "a" * 64


def sample():
    return packet(task_id="work-7", revision=2, owner="worker-1", scope="Review code",
                  exclusions=["deployment"], baseline="commit abc", deliverables=["review"],
                  acceptance=[{"id": "a1", "check": "review has evidence"}], context_refs=[],
                  source_hashes={"core:SKILL.md": H}, package_hashes={"core:SKILL.md": H},
                  stop_conditions=["scope changed"], escalation_conditions=["blocked"])


class TaskContractTests(unittest.TestCase):
    def test_scope_change_cancellation_and_unknown_effect_block_resume(self):
        value = sample()
        saved = checkpoint(value, next_safe_action="continue", uncertain_side_effects=[], sources_fresh=True)
        self.assertEqual(resume_check(value, saved, current_revision=2, sources_fresh=True)["decision"],
                         "eligible-for-owner-review")
        for options in ({"current_revision": 3}, {"sources_fresh": False}, {"canceled": True}):
            self.assertEqual(resume_check(value, saved, **{**{"current_revision": 2,
                                                               "sources_fresh": True}, **options})["decision"],
                             "hold-and-reconcile")
        with self.assertRaises(ValueError):
            checkpoint(value, next_safe_action="retry", uncertain_side_effects=["unknown send"], sources_fresh=True)

    def test_completion_and_milestone_are_evidence_not_acceptance(self):
        value = sample()
        report = {"task_id": "work-7", "revision": 2, "packet_sha256": value["packet_sha256"],
                  "criterion_evidence": {"a1": {"reference": "review.json", "check_result": "pass",
                                                "commit": "abc", "environment": "local"}}}
        self.assertEqual(assess_completion(value, report)["status"], "evidence-complete-awaiting-acceptance")
        event = milestone(value, event_id="e1", kind="completion", reported_status="done",
                          verified_status="unverified", evidence_refs=["review.json"])
        state = {"task_id": "work-7", "revision": 2, "packet_sha256": value["packet_sha256"]}
        state, status = consume_milestone(state, event)
        self.assertEqual(status, "owner-check-needed")
        self.assertEqual(consume_milestone(state, event)[1], "duplicate")
        self.assertEqual(consume_milestone(state, {**event, "revision": 1})[1], "stale-or-foreign")

    def test_packet_tamper_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_packet({**sample(), "scope": "Deploy"})

    def test_malformed_missing_future_and_stale_checkpoints_are_held(self):
        value = sample()
        saved = checkpoint(value, next_safe_action="retry", uncertain_side_effects=[], sources_fresh=True)
        variants = [{**saved, "sources_fresh": False},
                    {key: item for key, item in saved.items() if key != "sources_fresh"},
                    {**saved, "revision": 3}, {**saved, "revision": 1},
                    {**saved, "task_id": "other"}, {**saved, "bundle_sha256": "b" * 64},
                    {**saved, "packet_sha256": "b" * 64},
                    {**saved, "next_safe_action": "deploy"},
                    {**saved, "uncertain_side_effects": ["unknown send"]},
                    {**saved, "checkpoint_sha256": "b" * 64},
                    {**saved, "unexpected": True}]
        for altered in variants:
            with self.subTest(altered=altered):
                self.assertEqual(resume_check(value, altered, current_revision=2,
                                              sources_fresh=True)["decision"], "hold-and-reconcile")
                with self.assertRaises(ValueError):
                    validate_checkpoint(value, altered)
        stale = checkpoint(value, next_safe_action="retry", uncertain_side_effects=[], sources_fresh=False)
        self.assertEqual(resume_check(value, stale, current_revision=2,
                                      sources_fresh=True)["decision"], "hold-and-reconcile")
        uncertain = checkpoint(value, next_safe_action="reconcile",
                               uncertain_side_effects=["unknown send"], sources_fresh=True)
        self.assertEqual(resume_check(value, uncertain, current_revision=2,
                                      sources_fresh=True)["decision"], "hold-and-reconcile")


if __name__ == "__main__":
    unittest.main()
