"""Conveyor T3 hooks: denial log, archive guard, monitor id guard, resume hooks and the belt-only cleanup sweep.

The belt registry is read from receipts on open belt issues (conveyor.json `registry`), served here by a fake gh."""
import json
import os
import shutil
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
UUID = "{0}{0}{0}{0}{0}{0}{0}{0}-{0}{0}{0}{0}-{0}{0}{0}{0}-{0}{0}{0}{0}-{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}"
DONE, OPEN, OWNER, SIDE = (f"local_{UUID.format(c)}" for c in "abcd")
HEADLESS = UUID.format("e")
FAKE_GH = """#!/bin/sh
case "$*" in
  "issue list --state open"*) exec cat "$FAKE_GH_ISSUES" ;;
  *) echo "fake gh: unexpected call: $*" >&2; exit 1 ;;
esac
"""


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


def issue(number, labels, *comments):
    return {"number": number, "labels": [{"name": name} for name in labels],
            "comments": [{"author": {"login": "u"}, "body": body} for body in comments]}


class BeltCase(unittest.TestCase):
    """A temp git repo whose fake gh serves belt issues, plus a temp agent-coordination state dir."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(FAKE_GH)
        (bin_dir / "gh").chmod(0o755)
        self.issues_file = self.tmp / "issues.json"
        self.env = {"AGENT_COORDINATION_STATE": str(self.tmp / "state"), "FAKE_GH_ISSUES": str(self.issues_file),
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "CLAUDE_CODE_HOST_SESSION_ID": ""}
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.serve()

    def serve(self, *issues):
        self.issues_file.write_text(json.dumps(list(issues)))

    def hook(self, path, event, **env):
        done = subprocess.run([str(path)], input=json.dumps(event), capture_output=True, text=True,
                              cwd=self.repo, env={**os.environ, **env})
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def guard(self, name, event, **env):
        out = self.hook(ROOT / "hooks" / name, {"hook_event_name": "PreToolUse", "cwd": str(self.repo), **event},
                        **env)
        return json.loads(out)["hookSpecificOutput"] if out.strip() else None


class ArchiveGuardTests(BeltCase):
    def setUp(self):
        super().setUp()
        self.serve(
            issue(1, ["lane:in-progress"], f"Claimed: branch `feat/a` · session {OPEN}"),
            issue(2, ["lane:in-progress", "parked"], f"Claimed: branch `feat/b` · session {DONE}",
                  f"Claimed: branch `feat/e` · session {HEADLESS}"),
            issue(3, ["lane:next"], f"Owner: someone · session {OWNER} · 2026-11-18 20:00Z"),
            issue(4, ["kind:bug"], f"Claimed: branch `feat/x` · session {SIDE}"))

    def archive(self, target, caller=HEADLESS, **env):
        return self.guard("archive-guard.sh", {"session_id": caller, "tool_name": "mcp__ccd_session_mgmt__archive_session",
                                               "tool_input": {"session_id": target, "reason": "done"}}, **env)

    def test_a_registry_session_with_every_claimed_issue_parked_or_closed_is_archived(self):
        self.assertIsNone(self.archive(DONE))
        self.assertIsNone(self.archive("self", CLAUDE_CODE_HOST_SESSION_ID=DONE))

    def test_a_registry_session_with_unfinished_work_is_denied(self):
        for target, number in ((OPEN, "#1"), (OWNER, "#3")):
            denied = self.archive(target)
            self.assertEqual(denied["permissionDecision"], "deny", target)
            self.assertIn(number, denied["permissionDecisionReason"])

    def test_anything_outside_the_registry_asks(self):
        for target in (SIDE, "local_not-a-session", f"local_{UUID.format('f')}"):
            asked = self.archive(target)
            self.assertEqual(asked["permissionDecision"], "ask", target)
            self.assertIn("outside the belt registry", asked["permissionDecisionReason"])

    def test_a_headless_worker_is_never_archived(self):
        denied = self.archive(HEADLESS)
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertIn("headless worker", denied["permissionDecisionReason"])

    def test_a_guard_error_denies(self):
        self.issues_file.unlink()
        denied = self.archive(DONE)
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertIn("Guard error", denied["permissionDecisionReason"])

    def test_a_guard_that_cannot_load_denies(self):
        for name in ("archive-guard.sh", "monitor-id-guard.sh"):
            orphan = self.tmp / "orphan" / "hooks" / name
            orphan.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / "hooks" / name, orphan)
            out = self.hook(orphan, {"hook_event_name": "PreToolUse", "session_id": DONE, "cwd": str(self.repo),
                                     "tool_name": "x", "tool_input": {}})
            decided = json.loads(out)["hookSpecificOutput"]
            self.assertEqual(decided["permissionDecision"], "deny", name)
            self.assertIn("cannot load", decided["permissionDecisionReason"])


class MonitorIdGuardTests(BeltCase):
    def setUp(self):
        super().setUp()
        self.comments = ["Scheduler: claude monitor-repo-first", "Scheduler: claude monitor-repo-24h"]
        self.serve(issue(5, ["lane:monitoring"], *self.comments))

    def add(self, line):
        self.comments.append(line)
        self.serve(issue(5, ["lane:monitoring"], *self.comments))

    def call(self, tool, given, cwd=None):
        return self.guard("monitor-id-guard.sh", {"session_id": DONE, "tool_name": tool, "tool_input": given,
                                                  **({"cwd": str(cwd)} if cwd else {})})

    def create(self, task_id, description="Recheck abc1234. Deadline: 2026-11-21T20:00Z", cwd=None):
        return self.call("mcp__scheduled-tasks__create_scheduled_task",
                         {"taskId": task_id, "description": description, "cronExpression": "0 9 * * *"}, cwd)

    def delete(self, task_id):
        return self.call("mcp__scheduled-tasks__delete_scheduled_task", {"taskId": task_id})

    def test_create_allows_only_a_repo_monitor_id_with_a_deadline(self):
        self.assertIsNone(self.create("monitor-repo-new-thing"))
        self.assertIsNone(self.create("monitor-Repo-new-thing"))
        nowhere = self.tmp / "nowhere"
        nowhere.mkdir()
        for asked in (self.create("monitor-other-thing"), self.create("cleanup-repo-thing"),
                      self.create("monitor-repo-"), self.create("monitor-repo-thing", "Recheck abc1234"),
                      self.create("monitor-repo-thing", "Deadline: soon"), self.create("monitor-repo-x", cwd=nowhere)):
            self.assertEqual(asked["permissionDecision"], "ask")

    def test_delete_waits_for_each_schedules_verdict(self):
        for task_id in ("monitor-repo-first", "monitor-repo-24h"):
            self.assertEqual(self.delete(task_id)["permissionDecision"], "deny", task_id)
        self.add("Monitor verdict: first-traffic All working · 2026-11-18 21:00Z")
        self.assertIsNone(self.delete("monitor-repo-first"))
        self.assertIn("#5", self.delete("monitor-repo-24h")["permissionDecisionReason"])
        self.add("Monitor verdict: 24h Working, with issues · 2026-11-19 20:00Z")
        self.assertIsNone(self.delete("monitor-repo-24h"))

    def test_delete_of_any_other_id_asks(self):
        self.assertEqual(self.delete("monitor-repo-unknown")["permissionDecision"], "ask")
        self.serve(issue(6, ["kind:bug"], "Scheduler: claude monitor-repo-first"))
        self.assertEqual(self.delete("monitor-repo-first")["permissionDecision"], "ask")

    def test_bash_and_other_tools_pass_untouched(self):
        header = (ROOT / "hooks" / "monitor-id-guard.sh").read_text()
        self.assertNotIn("Bash", header)
        self.assertIsNone(self.call("Bash", {"command": "issues-cli lane 5 monitoring"}))
        self.assertIsNone(self.call("Read", {"file_path": "/x"}))


class DenialLogTests(BeltCase):
    def test_a_refused_belt_session_leaves_a_line_the_sweep_reads(self):
        self.serve(issue(1, ["lane:in-progress"], f"Claimed: branch `feat/a` · session {OPEN}"))
        for host in (OPEN, SIDE):
            self.assertEqual(self.hook(ROOT / "hooks" / "denial-log.sh", {
                "hook_event_name": "PermissionDenied", "session_id": HEADLESS, "cwd": "/w", "tool_name": "Bash",
                "tool_use_id": "toolu_1", "tool_input": {"command": "TOKEN=x /bin/rm -rf secret-dir"}},
                CLAUDE_CODE_HOST_SESSION_ID=host), "")
        lines = closeout.denial_log().read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn("secret", "".join(lines))
        [seen] = closeout.belt_denials(self.repo)
        self.assertEqual((seen["session_id"], seen["tool"], seen["head"], seen["issues"]), (OPEN, "Bash", "rm", [1]))


class BeltSweepTests(BeltCase):
    def test_sweep_removes_only_worktrees_of_claimed_branches(self):
        (self.repo / "a.txt").write_text("a\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-qm", "a")
        belt, side = self.tmp / "belt", self.tmp / "side"
        git(self.repo, "worktree", "add", "-q", "-b", "feat/belt", str(belt))
        git(self.repo, "worktree", "add", "-q", "-b", "feat/side", str(side))
        self.serve(issue(1, ["lane:in-review"], f"Claimed: branch `feat/belt` · session {OPEN}"),
                   issue(2, ["kind:bug"], f"Claimed: branch `feat/side` · session {SIDE}"))
        report = closeout.sweep(self.repo, base="main", apply=True, active_seconds=0, belt_only=True)
        self.assertEqual(report["removed"], [str(belt)])
        self.assertIn({"worktree": str(side), "reason": "outside the belt registry"}, report["kept"])
        self.assertTrue(side.is_dir())


class ResumeHookTests(BeltCase):
    """SessionStart adds `issues-cli resume` for a session named in workers.json roles; PreCompact prints it."""

    def setUp(self):
        super().setUp()
        self.home = self.tmp / "home"
        cli = self.home / ".agents" / "skills" / "workflow-contracts" / "scripts" / "issues-cli"
        cli.parent.mkdir(parents=True)
        cli.write_text('#!/bin/sh\n[ "$*" = resume ] || exit 3\necho "Board: in-progress 1/8"\necho "Questions: none"\n')
        cli.chmod(0o755)
        self.cli = cli
        config = self.tmp / "workers.json"
        config.write_text(json.dumps({"roles": {"coordinator": OWNER, "release_owner": DONE}}))
        self.roles_env = {"HOME": str(self.home), "AGENT_SKILLS_CONFIG": str(config)}

    def run_hook(self, name, host, event_name):
        return self.hook(ROOT / "hooks" / name, {"hook_event_name": event_name, "session_id": HEADLESS,
                                                 "cwd": str(self.repo)}, CLAUDE_CODE_HOST_SESSION_ID=host,
                         **self.roles_env)

    def test_session_start_adds_resume_only_for_a_role_session(self):
        for host in (OWNER, DONE):
            out = self.run_hook("session-start.sh", host, "SessionStart")
            self.assertIn("Board: in-progress 1/8", out)
            self.assertIn("Git snapshot for repo", out)
        out = self.run_hook("session-start.sh", SIDE, "SessionStart")
        self.assertNotIn("Board:", out)
        self.assertIn("Git snapshot for repo", out)

    def test_pre_compact_prints_the_resume_picture_to_keep(self):
        out = self.run_hook("pre-compact.sh", OWNER, "PreCompact")
        self.assertEqual(out.splitlines()[0], "Keep these exactly:")
        self.assertIn("Board: in-progress 1/8\nQuestions: none", out)
        self.assertEqual(self.run_hook("pre-compact.sh", SIDE, "PreCompact"), "")

    def test_a_failed_resume_is_said_loudly(self):
        self.cli.write_text("#!/bin/sh\necho 'gh: offline' >&2\nexit 1\n")
        for name, event_name in (("session-start.sh", "SessionStart"), ("pre-compact.sh", "PreCompact")):
            self.assertIn("issues-cli resume failed (exit 1): gh: offline", self.run_hook(name, OWNER, event_name))


class LayoutRuleTests(unittest.TestCase):
    def test_contract_paths_come_only_from_layout(self):
        self.assertNotIn("__file__", (ROOT / "agent_skills" / "closeout.py").read_text())


if __name__ == "__main__":
    unittest.main()
