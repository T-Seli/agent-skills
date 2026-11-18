"""Conveyor T3 hooks: denial log, archive guard, monitor id guard, and the belt-only cleanup sweep."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_skills import closeout  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class BeltCase(unittest.TestCase):
    """A temp agent-coordination store holding belt and side-session records."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.state = self.tmp / "state"
        self.state.mkdir()
        patcher = mock.patch.dict(os.environ, {"AGENT_COORDINATION_STATE": str(self.state)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self, task_id, session_id, *, owner="assistant", status="verified-done", worktree=None):
        (self.state / f"{task_id}.json").write_text(json.dumps({
            "task_id": task_id, "status": status, "worktree": worktree and str(worktree),
            "worker": {"kind": "claude", "session_id": session_id, "owner": owner, "state": "done"}}))

    def hook(self, name, event):
        done = subprocess.run([str(ROOT / "hooks" / name)], input=json.dumps(event), capture_output=True,
                              text=True, env={**os.environ, "AGENT_COORDINATION_STATE": str(self.state)})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["hookSpecificOutput"] if done.stdout.strip() else None


class ArchiveGuardTests(BeltCase):
    def setUp(self):
        super().setUp()
        self.record("belt-done", "s-done")
        self.record("belt-open", "s-open", status="ready-for-review")
        self.record("side", "s-side", owner="human")

    def archive(self, target, caller="s-coordinator"):
        return self.hook("archive-guard.sh", {"hook_event_name": "PreToolUse", "session_id": caller,
                                              "tool_name": "mcp__ccd_session_mgmt__archive_session",
                                              "tool_input": {"session_id": target, "reason": "done"}})

    def test_only_a_verified_done_belt_session_is_archived(self):
        self.assertIsNone(self.archive("s-done"))
        self.assertIsNone(self.archive("self", caller="s-done"))
        for target, why in (("s-open", "not verified-done"), ("s-side", "outside the belt registry"),
                            ("s-unknown", "outside the belt registry"), ("self", "outside the belt registry")):
            denied = self.archive(target)
            self.assertEqual(denied["permissionDecision"], "deny", target)
            self.assertIn(why, denied["permissionDecisionReason"], target)

    def test_a_guard_error_denies(self):
        (self.state / "broken.json").write_text("{")
        self.assertEqual(self.archive("s-done")["permissionDecision"], "deny")


class BeltSweepTests(BeltCase):
    def test_sweep_removes_only_belt_registry_worktrees(self):
        main = self.tmp / "main"
        main.mkdir()
        git(main, "init", "-q", "-b", "main")
        (main / "a.txt").write_text("a\n")
        git(main, "add", "a.txt")
        git(main, "commit", "-qm", "a")
        belt, side = self.tmp / "belt", self.tmp / "side"
        git(main, "worktree", "add", "-q", "-b", "feat/belt", str(belt))
        git(main, "worktree", "add", "-q", "-b", "feat/side", str(side))
        self.record("belt-task", "s-belt", worktree=belt)
        self.record("side-task", "s-side", owner="human", worktree=side)
        report = closeout.sweep(main, base="main", apply=True, active_seconds=0, belt_only=True)
        self.assertEqual(report["removed"], [str(belt)])
        self.assertIn({"worktree": str(side), "reason": "outside the belt registry"}, report["kept"])
        self.assertTrue(side.is_dir())
        self.assertIn("feat/side", git(main, "branch", "--list", "feat/side"))


class DenialLogTests(BeltCase):
    def test_a_refused_worker_leaves_a_line_the_sweep_reads(self):
        self.record("belt-task", "s-worker", status="running")
        self.record("side", "s-side", owner="human")
        for session in ("s-worker", "s-side"):
            self.assertIsNone(self.hook("denial-log.sh", {
                "hook_event_name": "PermissionDenied", "session_id": session, "cwd": "/w", "tool_name": "Bash",
                "tool_use_id": "toolu_1", "tool_input": {"command": "TOKEN=x /bin/rm -rf secret-dir"}}))
        lines = closeout.denial_log().read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn("secret", "".join(lines))
        [seen] = closeout.belt_denials()
        self.assertEqual((seen["session_id"], seen["tool"], seen["head"], seen["tasks"]),
                         ("s-worker", "Bash", "rm", ["belt-task"]))


class MonitorIdGuardTests(BeltCase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "CLAUDE.md").write_text("## Map\n- Task records: none (local drafts only)\n")
        self.task = self.repo / ".claude" / "drafts" / "2026-11-18-thing"
        self.task.mkdir(parents=True)
        (self.task / "plan.md").write_text("# Thing\nIssue: o/r#7\n")
        self.log("## 2026-11-18 20:00Z — deploy: abc1234 to prod\nRollback: prod: v1\n")

    def log(self, text):
        with open(self.task / "log.md", "a") as handle:
            handle.write(text)

    def call(self, tool, given):
        return self.hook("monitor-id-guard.sh", {"hook_event_name": "PreToolUse", "session_id": "s",
                                                 "cwd": str(self.repo), "tool_name": tool, "tool_input": given})

    def delete(self, task_id):
        return self.call("mcp__scheduled-tasks__delete_scheduled_task", {"taskId": task_id})

    def lane(self, issue):
        return self.call("Bash", {"command": f"~/.agents/skills/workflow-contracts/scripts/issues-cli lane {issue} "
                                             "monitoring"})

    def test_lane_monitoring_needs_two_schedule_ids(self):
        self.log("Scheduler: claude mon-first\n")
        self.assertIn("1 `Scheduler:` id(s)", self.lane(7)["permissionDecisionReason"])
        self.assertIn("no task plan records", self.lane(8)["permissionDecisionReason"])
        self.log("Scheduler: claude mon-24h\n")
        self.assertIsNone(self.lane(7))
        self.assertIsNone(self.call("Bash", {"command": "issues-cli lane 7 in-review"}))

    def test_a_monitor_is_deleted_only_after_its_verdict(self):
        self.log("Scheduler: claude mon-first\nScheduler: claude mon-24h\n")
        for task_id in ("mon-first", "mon-24h", "mon-unknown"):
            self.assertEqual(self.delete(task_id)["permissionDecision"], "deny", task_id)
        self.log("Monitor verdict: first-traffic All working · 2026-11-18 21:00Z\n")
        self.assertIsNone(self.delete("mon-first"))
        self.assertIn("no recorded verdict", self.delete("mon-24h")["permissionDecisionReason"])
        self.log("Monitor verdict: 24h All working · 2026-11-19 20:00Z\n")
        self.assertIsNone(self.delete("mon-24h"))

    def test_other_calls_pass_untouched(self):
        self.assertIsNone(self.call("mcp__scheduled-tasks__create_scheduled_task", {"taskId": "anything"}))
        self.assertIsNone(self.call("Read", {"file_path": "/x"}))


if __name__ == "__main__":
    unittest.main()
