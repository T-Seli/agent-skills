import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_skills.closeout import cleanup_gate, completion_gate, handoff_gate
from agent_skills.history import append, read
from agent_skills.source_readiness import compare_receipt, installed_links, source_receipt
from agent_skills.task_contract import checkpoint, packet

H = "a" * 64


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def sample():
    return packet(task_id="task-1", revision=1, owner="worker-1", scope="review",
                  exclusions=["deploy"], baseline="abc", deliverables=["report"],
                  acceptance=[{"id": "a1", "check": "tests pass"}], context_refs=[],
                  source_hashes={"core:SKILL.md": H}, package_hashes={"core:SKILL.md": H},
                  stop_conditions=["scope change"], escalation_conditions=["blocked"])


class SourceHistoryCloseoutTests(unittest.TestCase):
    def test_source_receipt_and_links_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            run("git", "-C", str(root), "init", "-q")
            for name in ("agent_skills/catalog.json", "skills/workflow-contracts/contracts.md",
                         "global/CLAUDE.md", "install.sh"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            run("git", "-C", str(root), "add", ".")
            run("git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
            receipt = source_receipt(root)
            self.assertTrue(compare_receipt(root, receipt)["ready"])
            self.assertFalse(compare_receipt(root / "missing", receipt)["ready"])
            with self.assertRaises(ValueError):
                source_receipt(root, expected_commit=receipt["commit"][:7])
            self.assertFalse(installed_links(root, Path(tmp) / "empty-home")["ready"])
            (root / "install.sh").write_text("changed")
            self.assertFalse(compare_receipt(root, receipt)["ready"])

    def test_history_is_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {"event_id": "e1", "task_id": "task-1", "revision": 1,
                   "at": "2026-10-02T00:00:00Z", "kind": "decision",
                   "summary": "Approved local implementation", "refs": ["chat:123"]}
            self.assertEqual(append(tmp, row), "appended")
            self.assertEqual(stat.S_IMODE((Path(tmp) / "task-1.jsonl").stat().st_mode), 0o600)
            self.assertEqual(append(tmp, row), "duplicate")
            self.assertEqual(read(tmp, "task-1"), [row])
            with self.assertRaises(ValueError):
                append(tmp, {**row, "event_id": "e2", "summary": "secret\nsecond line"})
            with self.assertRaises(ValueError):
                read(tmp, "../escape")
            with self.assertRaises(ValueError):
                append(tmp, {**row, "summary": "different"})
            os.chmod(tmp, 0o755)
            with self.assertRaises(ValueError):
                append(tmp, {**row, "event_id": "e3"})

    def test_handoff_completion_and_cleanup_gate(self):
        value = sample()
        saved = checkpoint(value, next_safe_action="continue", uncertain_side_effects=[], sources_fresh=True)
        self.assertEqual(handoff_gate(value, saved, current_revision=1, sources_fresh=True)["decision"],
                         "eligible-for-owner-review")
        self.assertEqual(handoff_gate(value, saved, current_revision=2, sources_fresh=True)["decision"],
                         "hold-and-reconcile")
        report = {"task_id": "task-1", "revision": 1, "packet_sha256": value["packet_sha256"],
                  "criterion_evidence": {"a1": {"reference": "report", "check_result": "pass",
                                                "commit": "abc", "environment": "local"}}}
        self.assertEqual(completion_gate(value, report)["decision"], "await-owner-or-human-acceptance")
        self.assertEqual(completion_gate(value, report, owner_verified=True, human_accepted=True)["decision"], "accepted")
        with tempfile.TemporaryDirectory() as tmp:
            main, worktree = Path(tmp) / "main", Path(tmp) / "task"
            main.mkdir()
            run("git", "-C", str(main), "init", "-q", "-b", "main")
            (main / "x").write_text("base")
            run("git", "-C", str(main), "add", ".")
            run("git", "-C", str(main), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
            run("git", "-C", str(main), "worktree", "add", "-qb", "feat/test", str(worktree))
            self.assertTrue(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                         completion_accepted=True, no_pending_effects=True)["eligible"])
            (worktree / "x").write_text("changed")
            self.assertFalse(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                          completion_accepted=True, no_pending_effects=True)["eligible"])
            run("git", "-C", str(worktree), "add", ".")
            run("git", "-C", str(worktree), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "change")
            self.assertFalse(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                          completion_accepted=True, no_pending_effects=True)["eligible"])
            run("git", "-C", str(main), "merge", "--ff-only", "feat/test")
            self.assertTrue(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                         completion_accepted=True, no_pending_effects=True)["eligible"])
            self.assertFalse(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                          completion_accepted=False, no_pending_effects=True)["eligible"])
