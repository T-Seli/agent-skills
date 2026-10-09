"""End-to-end synthetic producer/publisher/consumer lifecycle with failure injections."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HISTORY_SKILL = ROOT / "skills" / "task-history"
COORDINATION = ROOT / "skills" / "agent-coordination" / "scripts" / "tasks.py"
sys.path.insert(0, str(HISTORY_SKILL))
import checkpoint_capture
import history
import markdown

spec = importlib.util.spec_from_file_location("lifecycle_tasks", COORDINATION)
tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tasks)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


class CoordinationHistoryLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = self.root / "owner"
        self.owner.mkdir()
        git(self.owner, "init", "-q")
        git(self.owner, "config", "user.email", "fixture@example.invalid")
        git(self.owner, "config", "user.name", "Fixture")
        git(self.owner, "remote", "add", "origin",
            "https://github.com/T-Seli/agent-task-history.git")

    def event(self, event_id):
        return {"schema_version": 1, "event_id": event_id,
                "task_id": "fixture-lifecycle", "session_id": "fixture-session",
                "revision": 1, "record_owner": "fixture-owner",
                "execution_owner": "fixture-worker",
                "at_utc": "2026-10-09T03:00:00Z",
                "observed_at_utc": "2026-10-09T03:00:00Z",
                "kind": "start", "status": "active",
                "summary": "Synthetic lifecycle fixture",
                "scope": "Exercise one sanitized task-history lifecycle.",
                "excluded_scope": "No production data or external messages.",
                "approval_ref": "fixture-approval",
                "source_ref": "fixture:revision-1",
                "next_step": "Render, index, publish and read back the fixture.",
                "open_checks": ["fresh reader readback"]}

    def test_owner_append_bundle_publish_fresh_readback_and_resumed_worker(self):
        record = tasks.new_task(
            "fixture-lifecycle", "synthetic", worker_kind="local", owner="assistant",
            repo="example/repo", worktree="fixture",
            history_capture={"record_owner": "fixture-owner",
                             "authorization_ref": "fixture-approval",
                             "history_repo": str(self.owner)})
        record, event_id = tasks.stage_history_checkpoint(
            record, source_id="start-revision-1", transition="start",
            summary="Synthetic lifecycle fixture", evidence_refs=["fixture:revision-1"])
        event = self.event(event_id)
        packet = {"authorization_ref": "fixture-approval",
                  "expected_digest": history.digest(
                      self.owner / "events" / "fixture-lifecycle.jsonl"),
                  "event": event}
        appended = checkpoint_capture.capture(self.owner, packet)
        duplicate = checkpoint_capture.capture(self.owner, packet)
        self.assertEqual((appended["result"], duplicate["result"]),
                         ("appended", "duplicate"))
        self.assertEqual(appended["digest"], duplicate["digest"])

        with self.assertRaisesRegex(ValueError, "published index"):
            markdown.write(self.owner, "fixture-lifecycle")
            checkpoint_capture.verify_publication(
                self.owner, task_id="fixture-lifecycle", event_id=event["event_id"],
                expected_digest=appended["digest"], reader_ref="owner-before-publish")

        (self.owner / "INDEX.md").write_text(
            "# Tasks\n\n| Task | View | Events |\n|---|---|---|\n"
            "| Fixture | [View](views/fixture-lifecycle.md) | "
            "[Events](events/fixture-lifecycle.jsonl) |\n", encoding="utf-8")
        git(self.owner, "add", "events/fixture-lifecycle.jsonl",
            "views/fixture-lifecycle.md", "INDEX.md")
        git(self.owner, "commit", "-qm", "test: publish lifecycle fixture")

        remote = self.root / "publisher.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.owner, "remote", "add", "publisher", str(remote))
        git(self.owner, "push", "-q", "publisher", "HEAD:main")

        reader = self.root / "reader"
        subprocess.run(["git", "clone", "-q", "--branch", "main", str(remote), str(reader)],
                       check=True)
        git(reader, "remote", "set-url", "origin",
            "https://github.com/T-Seli/agent-task-history.git")
        history.initialize(reader)
        readback = checkpoint_capture.verify_publication(
            reader, task_id="fixture-lifecycle", event_id=event["event_id"],
            expected_digest=appended["digest"], reader_ref="fresh-clone:fixture")
        self.assertEqual((readback["revision"], readback["record_owner"]),
                         (1, "fixture-owner"))

        self.assertTrue(event_id.startswith("coord-"))
        for stage, receipt in (
                ("locally-appended", "append:fixture"),
                ("view-rendered", "view:fixture"),
                ("index-updated", "index:fixture"),
                ("published", "push:fixture")):
            record = tasks.mark_history_checkpoint(
                record, event_id=event_id, stage=stage, receipt_ref=receipt,
                **({"digest_value": appended["digest"]} if stage == "locally-appended" else {}))
        record = tasks.consume_history_readback(
            record, task_id="fixture-lifecycle", record_owner="fixture-owner",
            revision=readback["revision"], digest_value=readback["digest"],
            event_ids=[event_id], readback_ref=readback["reader_ref"])
        record = tasks.bind_task_contract(
            record, user_goal="Resume from canonical history", constraints=["synthetic only"],
            priority_source_ref="fixture:priority", canonical_issue_ref="fixture:lifecycle",
            canonical_owner="fixture-worker", deliverable_id="fixture-artifact", revision=1,
            acceptance_ref="fixture:acceptance", environment="local-test",
            changed_criteria="Consume the current canonical revision.",
            next_action="Run the synthetic fixture.", source_ref="fixture:revision-1",
            requested_artifact="fixture-report")
        record = tasks.acknowledge_task_contract(
            record, deliverable_id="fixture-artifact", revision=1,
            changed_criteria="Consume the current canonical revision.",
            next_action="Run the synthetic fixture.", environment="local-test",
            receipt_ref="worker:resume-readback", history_revision=1,
            history_digest=readback["digest"])
        active = record["coordination"]["active_deliverable"]
        self.assertEqual(active["history_readback"]["digest"], readback["digest"])


if __name__ == "__main__":
    unittest.main()
