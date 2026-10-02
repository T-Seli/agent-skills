import unittest

from agent_skills.session_registry import (accept_result, archive_eligibility,
                                           checkpoint_takeover, delegate_user_session, enroll,
                                           reconcile_migration, register, status)
from agent_skills.task_contract import checkpoint, packet

H = "a" * 64


def sample():
    return packet(task_id="t-1", revision=1, owner="w-1", scope="Review",
                  exclusions=[], baseline="abc", deliverables=["report"],
                  acceptance=[{"id": "a1", "check": "evidence"}], context_refs=[],
                  source_hashes={"skill": H}, package_hashes={"skill": H},
                  stop_conditions=["changed"], escalation_conditions=["blocked"])


def observed(value, origin="assistant", surface="cloud-terminal"):
    return register(value, session_id="s-1", host="cloud", surface=surface,
                    creator="assistant" if origin == "assistant" else "user",
                    origin_owner=origin, operator="assistant" if origin == "assistant" else "human",
                    resume_ref="host session s-1", workspace_ref="repo abc")


class RegistryTests(unittest.TestCase):
    def test_takeover_requires_quiescence_checkpoint_and_human_release(self):
        value = sample()
        entry = observed(value)
        saved = checkpoint(value, next_safe_action="continue", uncertain_side_effects=[], sources_fresh=True)
        for options in ({"stopped": False}, {"state_verified": False},
                        {"pending_effects": ["unknown send"]}):
            result, verdict = checkpoint_takeover(entry, value, saved, **{
                "expected_generation": 1, "stopped": True, "state_verified": True,
                "pending_effects": [], **options})
            self.assertEqual((result, verdict), (entry, "hold-and-reconcile"))
        handed, verdict = checkpoint_takeover(entry, value, saved, expected_generation=1,
                                               stopped=True, state_verified=True, pending_effects=[])
        self.assertEqual((handed["operator"], handed["origin_owner"], verdict),
                         ("human", "assistant", "handed-off"))
        self.assertEqual(checkpoint_takeover(handed, value, saved, expected_generation=2,
                                            stopped=True, state_verified=True,
                                            pending_effects=[])[1], "human-release-required")
        resumed, verdict = checkpoint_takeover(handed, value, saved, expected_generation=2,
                                               stopped=True, state_verified=True,
                                               pending_effects=[], human_release=True)
        self.assertEqual((resumed["operator"], resumed["generation"], verdict),
                         ("assistant", 3, "handed-off"))
        self.assertEqual(checkpoint_takeover(entry, value, saved, expected_generation=2,
                                            stopped=True, state_verified=True,
                                            pending_effects=[])[1], "stale")

    def test_user_desktop_delegation_keeps_origin_and_archive_gate(self):
        value = sample()
        entry = observed(value, "user", "desktop")
        self.assertEqual(delegate_user_session(entry, explicit_request=False,
                                               expected_generation=1)[1], "not-authorized")
        delegated, verdict = delegate_user_session(entry, explicit_request=True, expected_generation=1)
        self.assertEqual((verdict, delegated["origin_owner"], delegated["operator"]),
                         ("delegated", "user", "assistant"))
        delegated["completion"] = "accepted"
        self.assertEqual(archive_eligibility(delegated, host_archive_verified=True,
                                             restore_verified=True, no_pending_dispatch=True,
                                             no_pending_effects=True, state_preserved=True),
                         "user-archive-authorization-required")

    def test_registry_rejects_duplicate_task_and_host_session(self):
        value = sample()
        entry = observed(value)
        registry = enroll({}, entry)
        with self.assertRaises(ValueError):
            enroll(registry, entry)
        with self.assertRaises(ValueError):
            enroll(registry, {**entry, "task_id": "other"})

    def test_late_result_completion_and_archive(self):
        value = sample()
        entry = observed(value)
        self.assertEqual(accept_result(entry, value, generation=0, session_id="s-1",
                                       completion="claimed")[1], "stale-or-foreign")
        self.assertEqual(accept_result(entry, value, generation=1, session_id="other",
                                       completion="claimed")[1], "stale-or-foreign")
        self.assertEqual(accept_result(entry, value, generation=1, session_id="s-1",
                                       completion="accepted")[1], "verification-required")
        verified, _ = accept_result(entry, value, generation=1, session_id="s-1",
                                    completion="verified")
        accepted, _ = accept_result(verified, value, generation=1, session_id="s-1",
                                    completion="accepted")
        args = dict(host_archive_verified=True, restore_verified=True, no_pending_dispatch=True,
                    no_pending_effects=True, state_preserved=True)
        self.assertEqual(archive_eligibility(verified, **args), "acceptance-required")
        self.assertEqual(archive_eligibility(accepted, **args), "eligible-for-reviewed-archive")
        self.assertEqual(archive_eligibility(accepted, **{**args, "restore_verified": False}),
                         "hold-and-reconcile")
        self.assertEqual(status(accepted)["resume_ref"], "host session s-1")

    def test_migration_reconciles_both_sessions_and_fences_old_output(self):
        value = sample()
        entry = observed(value)
        saved = checkpoint(value, next_safe_action="continue", uncertain_side_effects=[], sources_fresh=True)
        args = dict(expected_generation=1, old_stopped=True, new_host="local",
                    new_session_id="s-2", new_resume_ref="local session s-2",
                    state_preserved=True, effects_reconciled=True, identity_verified=True)
        self.assertEqual(reconcile_migration(entry, value, saved,
                                             **{**args, "old_stopped": False})[1],
                         "hold-and-reconcile")
        migrated, verdict = reconcile_migration(entry, value, saved, **args)
        self.assertEqual((verdict, migrated["generation"], migrated["origin_owner"]),
                         ("migrated", 2, "assistant"))
        self.assertEqual(accept_result(migrated, value, generation=1, session_id="s-1",
                                       completion="claimed")[1], "stale-or-foreign")
        user_entry = observed(value, "user", "desktop")
        self.assertEqual(reconcile_migration(user_entry, value, saved, **args)[1],
                         "user-migration-authorization-required")


if __name__ == "__main__":
    unittest.main()
