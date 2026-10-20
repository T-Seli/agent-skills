"""delegate.py with a fake claude and caffeinate: launch, receipt, wake, ledger limits, lost runs."""
import contextlib
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DELEGATE = ROOT / "skills" / "agent-coordination" / "scripts" / "delegate.py"

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time
argv = sys.argv[1:]
prompt = sys.stdin.read()
cap = os.path.join(os.environ["FAKE_DIR"], "claude-%d.json" % os.getpid())
json.dump({"argv": argv, "prompt": prompt, "env": {k: os.environ.get(k) for k in (
    "AGENT_SKILLS_DEPTH", "AGENT_SKILLS_TASK_ID", "AWS_SHARED_CREDENTIALS_FILE", "AWS_ACCESS_KEY_ID",
    "PGPASSFILE", "DATABASE_URL")}}, open(cap, "w"))
sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else argv[argv.index("--resume") + 1]
print(json.dumps({"type": "system", "subtype": "init", "model": "fixture-claude", "session_id": sid}), flush=True)
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
print(json.dumps({"type": "result", "session_id": sid, "is_error": False, "total_cost_usd": 0.01,
                  "num_turns": 2, "permission_denials": [
                      {"tool_name": "Bash", "tool_input": {"command": "TOKEN=x git push origin main"}}],
                  "structured_output": {"status": "ready", "summary": "did it", "commit": "abc123",
                                        "tests": "3 passed", "need": "", "action": "", "target": ""}}))
'''
FAKE_CAFFEINATE = '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_DIR/caffeinate.args"\n'


class DelegateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        for name, body in (("claude", FAKE_CLAUDE), ("caffeinate", FAKE_CAFFEINATE)):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.config = self.dir / "workers.json"
        self.write_config()
        self.work = self.dir / "work"
        self.work.mkdir()
        self.prompt = self.dir / "brief.md"
        self.prompt.write_text("Fix the flaky test in tests/test_x.py and commit.")
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DIR": str(self.dir),
                    "AGENT_SKILLS_CONFIG": str(self.config), "AGENT_COORDINATION_STATE": str(self.dir / "state"),
                    "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE", "DATABASE_URL": "postgres://example",
                    "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("AGENT_SKILLS_DEPTH", None)
        self.env.pop("AGENT_SKILLS_TASK_ID", None)

    def write_config(self, **overrides):
        cfg = json.loads((ROOT / "agent_skills" / "delegate_config.example.json").read_text())
        cfg["policy"]["claude"]["ordinary"]["model"] = "fixture-claude"
        cfg["capabilities"]["claude"]["fixture-claude"] = ["medium", "high"]
        cfg.update(overrides)
        self.config.write_text(json.dumps(cfg))

    def delegate(self, *args, env=None):
        return subprocess.run([sys.executable, str(DELEGATE), *args], capture_output=True, text=True,
                              env={**self.env, **(env or {})})

    def start(self, *extra, env=None, cwd=None):
        return self.delegate("start", "--prompt-file", str(self.prompt), "--cwd", str(cwd or self.work), *extra,
                             env=env)

    def captured(self):
        found = sorted(self.dir.glob("claude-*.json"), key=lambda p: p.stat().st_mtime)
        return json.loads(found[-1].read_text())

    def test_start_returns_at_once_and_wait_returns_the_receipt(self):
        began = time.time()
        started = self.start("--task-id", "t-1")
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertLess(time.time() - began, 2)
        launch = json.loads(started.stdout)
        self.assertEqual((launch["task_id"], launch["depth"]), ("t-1", 1))

        waited = self.delegate("wait", "t-1", "--timeout", "30")
        self.assertEqual(waited.returncode, 0, waited.stdout + waited.stderr)
        receipt = json.loads(waited.stdout)
        self.assertEqual((receipt["outcome"], receipt["report"]["status"], receipt["permission_denials"]),
                         ("done", "ready", 1))
        self.assertEqual(receipt["record_status"], "ready-for-review")
        self.assertIsNone(receipt["bookkeeping_error"])

        call = self.captured()
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")
        route = json.loads(self.config.read_text())["policy"]["claude"]["ordinary"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], str(route["max_cost_usd"]))
        self.assertEqual(argv[argv.index("--max-turns") + 1], str(route["max_turns"]))
        self.assertEqual(argv[argv.index("--model") + 1], "fixture-claude")
        guard = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
        self.assertIn("worker-guard.py", guard["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
        self.assertIn("Bash(git push:*)", guard["permissions"]["deny"])
        self.assertNotIn(self.prompt.read_text(), argv)
        self.assertEqual(call["prompt"], self.prompt.read_text())
        self.assertEqual(call["env"]["AGENT_SKILLS_DEPTH"], "1")
        self.assertEqual(call["env"]["AWS_SHARED_CREDENTIALS_FILE"], "/dev/null")
        self.assertIsNone(call["env"]["AWS_ACCESS_KEY_ID"])
        self.assertIsNone(call["env"]["DATABASE_URL"])
        if sys.platform == "darwin":
            self.assertEqual((self.dir / "caffeinate.args").read_text().split()[:2], ["-i", "-w"])

        spool = [json.loads(l) for l in (self.dir / "state" / "feedback.jsonl").read_text().splitlines()]
        self.assertEqual(spool[0]["kind"], "permission-denial")
        self.assertEqual((spool[0]["tool"], spool[0]["head"]), ("Bash", "git"))
        self.assertNotIn("origin", json.dumps(spool))
        params = json.loads((Path(launch["run_dir"]) / "params.json").read_text())
        self.assertNotIn("postgres://example", json.dumps(params))

        report = json.loads(self.delegate("report", "--days", "1").stdout)
        self.assertEqual((report["runs"], report["outcomes"], report["denials"]), (1, {"done": 1}, {"Bash:git": 1}))

    def test_depth_limit_refuses_before_any_record(self):
        refused = self.start("--task-id", "deep", env={"AGENT_SKILLS_DEPTH": "2"})
        self.assertEqual(refused.returncode, 3)
        self.assertIn("max_depth", json.loads(refused.stdout)["refused"])
        self.assertFalse((self.dir / "state" / "deep.json").exists())

    def test_live_limit_and_one_writer_per_directory(self):
        self.write_config(max_live=2)
        first = self.start("--task-id", "long", env={"FAKE_SLEEP": "4"})
        self.assertEqual(first.returncode, 0, first.stderr)
        same_dir = self.start("--task-id", "second")
        self.assertEqual(same_dir.returncode, 3)
        self.assertIn("one writer", json.loads(same_dir.stdout)["refused"])
        other = self.dir / "other"
        other.mkdir()
        self.write_config(max_live=1)
        full = self.start("--task-id", "third", cwd=other)
        self.assertEqual(full.returncode, 3)
        self.assertIn("max_live", json.loads(full.stdout)["refused"])
        self.assertEqual(self.delegate("wait", "long", "--timeout", "30").returncode, 0)

    def test_killed_supervisor_is_settled_as_lost(self):
        started = json.loads(self.start("--task-id", "doomed", env={"FAKE_SLEEP": "30"}).stdout)
        run = Path(started["run_dir"])
        for _ in range(50):
            sup = json.loads((run / "supervisor.json").read_text())
            if sup["worker_pid"]:
                break
            time.sleep(0.1)
        os.kill(sup["supervisor_pid"], signal.SIGKILL)
        os.killpg(sup["worker_pid"], signal.SIGKILL)
        time.sleep(0.3)
        settled = self.delegate("reconcile")
        self.assertEqual(json.loads(settled.stdout.splitlines()[0])["settled"], "lost")
        waited = self.delegate("wait", "doomed", "--timeout", "5")
        self.assertEqual((waited.returncode, json.loads(waited.stdout)["outcome"]), (1, "lost"))

    def test_missing_config_fails_naming_the_path(self):
        self.config.unlink()
        failed = self.start("--task-id", "x")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn(str(self.config), failed.stderr)


class SandboxLivenessTests(unittest.TestCase):
    """A sandbox that denies signals and `ps` can't tell whether a run lives; it must never settle it lost."""

    DENIED_PS = (subprocess.CompletedProcess(["ps"], 1, "", "ps: Operation not permitted\n"),
                 PermissionError(1, "Operation not permitted", "ps"))

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.work = self.dir / "work"
        self.work.mkdir()
        self.run_dir = self.dir / "state" / "runs" / "t-live" / "d1"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "supervisor.json").write_text(json.dumps(
            {"supervisor_pid": 424242, "worker_pid": 424243, "started_at": "2026-10-19T00:00:00Z"}))
        (self.run_dir / "params.json").write_text(json.dumps({"cwd": str(self.work), "depth": 1}))
        cfg = json.loads((ROOT / "agent_skills" / "delegate_config.example.json").read_text())
        (self.dir / "workers.json").write_text(json.dumps(cfg))
        (self.dir / "brief.md").write_text("Run ls.")
        spec = importlib.util.spec_from_file_location("delegate_under_test", DELEGATE)
        self.delegate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.delegate)
        env = mock.patch.dict(os.environ, {"AGENT_COORDINATION_STATE": str(self.dir / "state")})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("AGENT_SKILLS_DEPTH", None)

    def call(self, ps, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        ps_mock = {"side_effect": ps} if isinstance(ps, Exception) else {"return_value": ps}
        with mock.patch.object(self.delegate.os, "kill", side_effect=PermissionError(1, "denied")), \
                mock.patch.object(self.delegate.subprocess, "run", **ps_mock), \
                mock.patch.object(self.delegate.subprocess, "Popen", side_effect=AssertionError("launched")), \
                mock.patch.object(self.delegate, "CONFIG", self.dir / "workers.json"), \
                mock.patch.object(self.delegate.time, "sleep"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.delegate.main(list(argv))
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def test_reconcile_and_wait_never_settle_unknown_liveness_as_lost(self):
        for ps in self.DENIED_PS:
            with self.subTest(ps=type(ps).__name__):
                code, out, err = self.call(ps, "reconcile")
                self.assertFalse((self.run_dir / "receipt.json").exists())
                self.assertNotEqual(code, 0)
                self.assertEqual(json.loads(out.splitlines()[0])["settled"], "liveness-unknown")
                self.assertIn("liveness unknown", err)

                code, out, err = self.call(ps, "wait", "t-live", "--timeout", "1")
                self.assertFalse((self.run_dir / "receipt.json").exists())
                self.assertEqual((code, json.loads(out)["state"]), (3, "unknown"))
                self.assertIn("liveness unknown", err)

    def test_a_run_of_unknown_liveness_still_holds_its_directory(self):
        code, out, _ = self.call(self.DENIED_PS[0], "start", "--prompt-file", str(self.dir / "brief.md"),
                                 "--cwd", str(self.work), "--task-id", "t-second")
        self.assertEqual(code, 3)
        self.assertIn("one writer", json.loads(out)["refused"])


if __name__ == "__main__":
    unittest.main()
