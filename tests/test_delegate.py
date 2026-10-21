"""delegate.py with a fake claude and caffeinate: launch, receipt, wake, ledger limits, lost runs, grants."""
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DELEGATE = ROOT / "skills" / "agent-coordination" / "scripts" / "delegate.py"
BASE_DENY = json.loads((ROOT / "guard" / "worker-settings.json").read_text())["permissions"]["deny"]
REMOTE = ("Bash(ssh:", "Bash(scp:", "Bash(rsync")
RELEASE = {"grant_hours": 12, "repos": {"acme/app": {"base": "main", "targets": {
    "github-main": {"commands": ["git push origin HEAD:main"]},
    "prod": {"commands": ["scripts/deploy.sh", "git push origin HEAD:main"], "hosts": ["deploy@203.0.113.7"],
             "credentials": ["aws"]},
    "db": {"commands": ["scripts/migrate.sh"], "credentials": ["databases"]}}}}}
QUOTE = '"yes, ship it to main and prod"'

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time
argv = sys.argv[1:]
prompt = sys.stdin.read()
cap = os.path.join(os.environ["FAKE_DIR"], "claude-%d.json" % os.getpid())
json.dump({"argv": argv, "prompt": prompt, "env": {k: os.environ.get(k) for k in (
    "AGENT_SKILLS_DEPTH", "AGENT_SKILLS_TASK_ID", "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE",
    "AWS_ACCESS_KEY_ID", "PGPASSFILE", "DATABASE_URL", "AGENT_SKILLS_GRANT")}}, open(cap, "w"))
sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else argv[argv.index("--resume") + 1]
print(json.dumps({"type": "system", "subtype": "init", "model": "fixture-claude", "session_id": sid}), flush=True)
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
print(json.dumps({"type": "result", "session_id": sid, "is_error": False, "total_cost_usd": 0.01,
                  "num_turns": 2, "permission_denials": [
                      {"tool_name": "Bash", "tool_input": {"command": "TOKEN=x git push origin main"}}],
                  "structured_output": json.loads(os.environ.get("FAKE_REPORT") or json.dumps(
                      {"status": "ready", "summary": "did it", "commit": "abc123",
                       "tests": "3 passed", "need": "", "action": "", "target": ""}))}))
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

    def release_setup(self, url="https://github.com/acme/app.git"):
        subprocess.run(["git", "init", "-q", str(self.work)], check=True)
        subprocess.run(["git", "-C", str(self.work), "remote", "add", "origin", url], check=True)
        self.write_config(release=RELEASE)

    def log(self, *lines):
        path = self.dir / "log.md"
        path.write_text("\n".join(["## build", *lines, "- tests: 3 passed"]) + "\n")
        return path

    @staticmethod
    def approved(steps="build, review, deploy, monitor", targets="github-main, prod", at=None,
                 source="session s-1 message m-12", quote=QUOTE):
        at = at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        return " · ".join([f"Approved: {steps}", targets, at, source, quote])

    def release(self, task_id, log, targets, env=None):
        return self.start("--task-id", task_id, "--approved-log", str(log), "--targets", targets, env=env)

    def test_start_returns_at_once_and_wait_returns_the_receipt(self):
        began = time.time()
        started = self.start("--task-id", "t-1", env={"AGENT_SKILLS_GRANT": '{"repo": "acme/app"}'})
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
        self.assertIsNone(receipt["grant"])

        call = self.captured()
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")
        route = json.loads(self.config.read_text())["policy"]["claude"]["ordinary"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], str(route["max_cost_usd"]))
        self.assertEqual(argv[argv.index("--max-turns") + 1], str(route["max_turns"]))
        self.assertEqual(argv[argv.index("--model") + 1], "fixture-claude")
        guard = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
        self.assertIn("worker-guard.py", guard["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
        self.assertNotIn("Bash(git push:*)", guard["permissions"]["deny"])
        self.assertEqual(guard["permissions"]["deny"], BASE_DENY)
        self.assertIsNone(call["env"]["AGENT_SKILLS_GRANT"])
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

    def test_a_read_only_worker_answers_without_claiming_ready(self):
        answer = {"status": "answered", "summary": "3 files", "commit": "", "tests": "", "need": "",
                  "action": "", "target": ""}
        self.assertEqual(self.start("--task-id", "q-1", env={"FAKE_REPORT": json.dumps(answer)}).returncode, 0)
        waited = self.delegate("wait", "q-1", "--timeout", "30")
        receipt = json.loads(waited.stdout)
        self.assertEqual((waited.returncode, receipt["outcome"], receipt["report"]["status"],
                          receipt["record_status"], receipt["bookkeeping_error"]), (0, "done", "answered", "answered", None))
        record = json.loads((self.dir / "state" / "q-1.json").read_text())
        self.assertEqual((record["coordination"]["execution_state"], record["evidence"]), ("finished", None))

    def test_release_flags_go_together(self):
        log = self.log(self.approved())
        for extra in (("--targets", "github-main"), ("--approved-log", str(log))):
            with self.subTest(extra=extra[0]):
                failed = self.start("--task-id", "half", *extra)
                self.assertEqual(failed.returncode, 2)
                self.assertIn("go together", failed.stderr)

    def test_release_refuses_an_unverified_approval_before_any_record(self):
        self.release_setup()
        at = datetime.now(timezone.utc)
        minute = "%Y-%m-%d %H:%MZ"
        cases = [
            ("no Approved: line", [], "github-main", None),
            ("4 fields", [" · ".join(self.approved().split(" · ")[:4])], "github-main", None),
            ("not deploy", [self.approved(), self.approved(steps="build, review, deployment")], "github-main", None),
            ("not YYYY-MM-DD HH:MMZ", [self.approved(at=at.strftime("%Y-%m-%dT%H:%MZ"))], "github-main", None),
            ("not YYYY-MM-DD HH:MMZ", [self.approved(at=at.strftime("%Y-%m-%d ") + "9:05Z")], "github-main", None),
            ("in the future", [self.approved(at=(at + timedelta(minutes=10)).strftime(minute))], "github-main", None),
            ("older than grant_hours 12", [self.approved(at=(at - timedelta(hours=13)).strftime(minute))],
             "github-main", None),
            ("no source", [self.approved(source="")], "github-main", None),
            ("exact words", [self.approved(quote="ship it")], "github-main", None),
            ("exact words", [self.approved(quote='""')], "github-main", None),
            ("not in the approval", [self.approved(targets="github-main")], "github-main,prod", None),
            ("not configured for acme/app", [self.approved(targets="github-main, staging")],
             "github-main,staging", None),
            ("restores only aws", [self.approved(targets="db")], "db", None),
            ("top-level session", [self.approved()], "github-main", {"AGENT_SKILLS_DEPTH": "1"}),
        ]
        for n, (reason, lines, targets, env) in enumerate(cases):
            with self.subTest(reason=reason, n=n):
                refused = self.release(f"r-{n}", self.log(*lines), targets, env=env)
                self.assertEqual(refused.returncode, 3, refused.stderr)
                self.assertIn(reason, json.loads(refused.stdout)["refused"])
                self.assertFalse((self.dir / "state" / f"r-{n}.json").exists())

    def test_release_names_the_repo_from_https_and_ssh_origins(self):
        self.release_setup()
        self.write_config(release={**RELEASE, "repos": {}})
        log = self.log(self.approved())
        for url in ("https://github.com/acme/app.git", "https://github.com/acme/app", "git@github.com:acme/app.git",
                    "ssh://git@github.com/acme/app.git", str(self.dir / "acme" / "app")):
            with self.subTest(url=url):
                subprocess.run(["git", "-C", str(self.work), "remote", "set-url", "origin", url], check=True)
                refused = self.release("r-url", log, "github-main")
                self.assertEqual(refused.returncode, 3, refused.stderr)
                reason = json.loads(refused.stdout)["refused"]
                self.assertIn("not an owner/name URL" if url.startswith("/") else
                              "no release.repos entry for acme/app", reason)

    def test_a_verified_approval_hands_the_worker_its_grant(self):
        self.release_setup()
        at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        expires = (datetime.strptime(at, "%Y-%m-%d %H:%MZ") + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%MZ")
        log = self.log(self.approved(at=at))
        for task_id, targets, commands, hosts in (
                ("rel-1", "github-main", ["git push origin HEAD:main"], []),
                ("rel-2", "github-main,prod", ["git push origin HEAD:main", "scripts/deploy.sh"],
                 ["deploy@203.0.113.7"])):
            with self.subTest(targets=targets):
                started = self.release(task_id, log, targets)
                self.assertEqual(started.returncode, 0, started.stderr)
                waited = self.delegate("wait", task_id, "--timeout", "30")
                self.assertEqual(waited.returncode, 0, waited.stdout + waited.stderr)
                names = targets.split(",")
                grant = {"repo": "acme/app", "base": "main", "targets": names, "commands": commands, "hosts": hosts,
                         "expires": expires, "task_id": task_id, "source": "session s-1 message m-12"}
                call = self.captured()
                self.assertEqual(call["env"]["AGENT_SKILLS_GRANT"], json.dumps(grant, separators=(",", ":")))
                receipt = json.loads(waited.stdout)
                self.assertEqual(receipt["grant"], {"repo": "acme/app", "base": "main", "targets": names,
                                                    "expires": expires, "source": "session s-1 message m-12"})
                params = (Path(json.loads(started.stdout)["run_dir"]) / "params.json").read_text()
                self.assertNotIn("ship it", params + waited.stdout)

                aws = "prod" in names  # only prod lists aws credentials
                self.assertEqual(call["env"]["AWS_ACCESS_KEY_ID"], "AKIAEXAMPLE" if aws else None)
                self.assertEqual(call["env"]["AWS_SHARED_CREDENTIALS_FILE"] == "/dev/null", not aws)
                self.assertEqual(call["env"]["AWS_CONFIG_FILE"] == "/dev/null", not aws)
                self.assertIsNone(call["env"]["DATABASE_URL"])
                self.assertEqual(call["env"]["PGPASSFILE"], "/dev/null")

                argv = call["argv"]
                deny = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())["permissions"]["deny"]
                self.assertIn("Bash(ssh:*)", BASE_DENY)
                self.assertEqual(deny, [d for d in BASE_DENY if not d.startswith(REMOTE)] if hosts else BASE_DENY)
                self.assertIn("Bash(psql:*)", deny)  # a grant never reopens database clients

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
