from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / "skills" / "task-history"
sys.path.insert(0, str(MODULE))
import checkpoint_capture as capture
import history


class CheckpointCaptureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "history"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin",
                        "https://github.com/T-Seli/agent-task-history.git"], check=True)

    def event(self, **changes):
        row = {"schema_version": 1, "event_id": "fixture-start-001", "task_id": "fixture-task",
               "session_id": "fixture-session", "revision": 1, "record_owner": "fixture-owner",
               "at_utc": "2026-10-05T00:00:00Z", "observed_at_utc": "2026-10-05T00:00:00Z",
               "kind": "start", "status": "active", "summary": "Synthetic checkpoint",
               "approval_ref": "task-specific-fixture-approval", "source_ref": "fixture:source-1"}
        return dict(row, **changes)

    def checkpoint(self, event=None, **changes):
        event = event or self.event()
        return dict({"authorization_ref": "task-specific-fixture-approval",
                     "expected_digest": history.digest(self.repo / "events" / "fixture-task.jsonl"),
                     "binding": {"event_id": event["event_id"], "task_id": event["task_id"],
                                 "record_owner": event["record_owner"], "kind": event["kind"],
                                 "summary": event["summary"], "approval_ref": event["approval_ref"],
                                 "evidence_refs": [event["source_ref"]]},
                     "event": event}, **changes)

    def test_append_replay_and_identical_retry(self):
        packet = self.checkpoint()
        first = capture.capture(self.repo, packet)
        second = capture.capture(self.repo, packet)
        self.assertEqual(first["result"], "appended")
        self.assertEqual(second["result"], "duplicate")
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual(history.overview(self.repo, "fixture-task")["events"], 1)

    def test_rejects_missing_authorization_and_owner_change(self):
        packet = self.checkpoint()
        with self.assertRaisesRegex(ValueError, "approval reference"):
            capture.capture(self.repo, self.checkpoint(event=self.event(approval_ref="other")))
        capture.capture(self.repo, packet)
        changed = self.event(event_id="fixture-next-002", revision=2, kind="implementation",
                             record_owner="other")
        changed.pop("status")
        with self.assertRaisesRegex(ValueError, "record owner"):
            capture.capture(self.repo, self.checkpoint(event=changed))

    def test_rejects_event_that_does_not_match_staged_binding(self):
        packet = self.checkpoint()
        packet["event"] = dict(packet["event"], summary="Different summary")
        with self.assertRaisesRegex(ValueError, "staged checkpoint binding"):
            capture.capture(self.repo, packet)

    def test_rejects_stale_digest_and_non_start_first_event(self):
        non_start = self.event(kind="implementation")
        non_start.pop("status")
        with self.assertRaisesRegex(ValueError, "start event"):
            capture.capture(self.repo, self.checkpoint(event=non_start))
        packet = self.checkpoint()
        capture.capture(self.repo, packet)
        next_event = self.event(event_id="fixture-next-002", revision=2, kind="implementation")
        next_event.pop("status")
        with self.assertRaisesRegex(ValueError, "stale checkpoint digest"):
            capture.capture(self.repo, dict(
                self.checkpoint(event=next_event), expected_digest=packet["expected_digest"]))


if __name__ == "__main__":
    unittest.main()
