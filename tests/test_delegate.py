"""delegate.py with a fake claude and caffeinate: launch, receipt, wake, ledger limits, lost runs, grants."""
import contextlib
import copy
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
            self.assertEqual(receipt['keep_awake'], 'launched-unverified')

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


class CriticalProtectionTests(unittest.TestCase):
    """Real delegate functions; injected native boundary, no assertions/models."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        spec = importlib.util.spec_from_file_location('critical_delegate', DELEGATE)
        self.d = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.d)
        self.clock = datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc)
        self.start_clock = self.clock
        self.real_sleep, self.real_monotonic = time.sleep, time.monotonic
        self.k = self.d.keep_awake
        self.real_owner_status = self.k.status
        stamp = self.k.stamp
        identity = dict(pid=51001, started='fixture-start', executable='/usr/bin/caffeinate')
        supervisor = dict(pid=51002, started='fixture-start', executable='fixture-python')
        self.receipt = dict(kind='owned-keep-awake',task_id='support-task',owner='owner',
            host_id='boot',generation='g1',approval_ref='user:embedding',foreground_ref='retained:handle',
            authorized_until_utc=stamp(self.clock+timedelta(seconds=120)),segment_seconds=30,check_seconds=1,
            state='running',pid=identity['pid'],process_identity=identity,supervisor_identity=supervisor,
            assertion_ref='assertion-1',expires_at_utc=stamp(self.clock+timedelta(seconds=30)),
            consumers=[],observation=dict(observed_at_utc=stamp(self.clock),host_id='boot',
                process=identity,supervisor=supervisor,assertion=dict(pid=identity['pid'],id='assertion-1',
                kind='PreventUserIdleSystemSleep',remaining_seconds=30),power={'source':'AC Power'}))
        self.args = argparse_namespace = type('Args', (), {})()
        argparse_namespace.critical_protection_receipt = str(self.dir/'owner.json')
        argparse_namespace.critical_until_utc = stamp(self.clock+timedelta(seconds=90))
        argparse_namespace.critical_authority_ref = 'user:embedding'
        self.patch(self.d, 'now', side_effect=lambda:self.clock)
        self.patch(self.d, 'source_pin', return_value='fixture:source')
        self.patch(self.k, 'status', side_effect=self.native_status)
        self.reuse = self.patch(self.k, 'reuse', side_effect=self.acknowledge)
        self.patch(self.k.Native, 'start_assertion', side_effect=AssertionError('unexpected acquisition'))
        self.patch(self.d.time, 'monotonic', side_effect=lambda:(self.clock-self.start_clock).total_seconds())
        self.patch(self.d.time, 'sleep', side_effect=self.advance)
        critical=self.d.critical_spec(self.args,'critical-task','d1','fixture:source')
        self.params=dict(task_id='critical-task',dispatch_id='d1',critical=critical,depth=1,
            cwd=str(self.dir),env={'set':{},'unset':[]},route={},grant=None,timeout_seconds=2,
            argv=[sys.executable,'-c', 'print(\'{"type":"result","is_error":false,"structured_output":'
                  '{"status":"answered","summary":"fixture","commit":"","tests":"","need":""}}\')'])
        (self.dir/'params.json').write_text(json.dumps(self.params))
        (self.dir/'prompt.md').write_text('Harmless test-owned Python worker; no model calls.')
        (self.dir/'supervisor.json').write_text(json.dumps({'supervisor_pid':os.getpid(),'worker_pid':None,
                                                          'started_at':stamp(self.clock)}))

    def patch(self, obj, name, **kwargs):
        patcher=mock.patch.object(obj,name,**kwargs); value=patcher.start();self.addCleanup(patcher.stop);return value

    def advance(self, seconds): self.clock += timedelta(seconds=seconds)

    def native_status(self, path):
        r=copy.deepcopy(self.receipt)
        r['observation']['observed_at_utc']=self.k.stamp(self.clock)
        if r['observation'].get('assertion'):
            r['observation']['assertion']['remaining_seconds']=max(0,min(r['segment_seconds'],int(
                (self.k.utc(r['expires_at_utc'])-self.clock).total_seconds())))
        r['assessment']=self.k.assess(r,now=self.k.stamp(self.clock),owner=r['owner'])
        return r

    def acknowledge(self, path, *, consumer, task_id, until_utc):
        self.receipt['consumers'].append(dict(consumer=consumer,consumer_task_id=task_id,
            generation=self.receipt['generation'],until_utc=until_utc,readback_at_utc=self.k.stamp(self.clock)))
        return self.admit_without_ack(path,consumer=consumer,task_id=task_id,until_utc=until_utc)

    def admit_without_ack(self, path, *, consumer, task_id, until_utc):
        queued={k:self.receipt[k] for k in ('owner','generation','host_id','task_id')}
        queued.update(operation='retain-consumer',consumer=consumer,consumer_task_id=task_id,
                      until_utc=until_utc,requested_at_utc=self.k.stamp(self.clock))
        return dict(state='queued-not-executed',receipt=str(path),request=queued)

    def protection(self): return self.d.CriticalProtection(self.params,self.dir)

    def renew_grant(self):
        self.receipt['pid']+=1
        self.receipt['process_identity']={**self.receipt['process_identity'],'pid':self.receipt['pid']}
        self.receipt['observation']['process']=copy.deepcopy(self.receipt['process_identity'])
        self.receipt['assertion_ref']='assertion-successor'
        self.receipt['observation']['assertion'].update(pid=self.receipt['pid'],id='assertion-successor')
        self.receipt['expires_at_utc']=self.k.stamp(self.clock+timedelta(seconds=30))

    def supervise(self, *, on_launch=None):
        self.update=self.patch(self.d.tasks,'update',return_value={'status':'ready-for-review'})
        self.patch(self.d.tasks,'load',return_value={'status':'ready-for-review'})
        self.patch(self.d.tasks,'receive')
        self.patch(self.d,'feedback')
        original=subprocess.Popen
        calls=[]
        def launch(argv,**kwargs):
            calls.append(argv)
            self.assertEqual(self.protection().view()['gate'],'open')
            # Subprocess.wait must use real time while the harmless real child runs.
            self.d.time.sleep, self.d.time.monotonic = self.real_sleep, self.real_monotonic
            child=original(argv,**kwargs)
            if on_launch:on_launch()
            return child
        self.patch(self.d.subprocess,'Popen',side_effect=launch)
        self.d.supervise(self.dir)
        return json.loads((self.dir/'receipt.json').read_text()),calls

    def test_all_critical_flags_are_required_together(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.d.main(['start','--prompt-file','unused','--critical-until-utc','2026-10-21T23:01:00Z'])
        self.assertEqual(caught.exception.code,2)

    def test_authority_and_utc_window_are_exact(self):
        for field,value in [('critical_authority_ref','user:other'),
                ('critical_until_utc',self.k.stamp(self.clock)),
                ('critical_until_utc',self.k.stamp(self.clock+timedelta(seconds=121)))]:
            args=copy.copy(self.args);setattr(args,field,value)
            with self.subTest(field=field,value=value),contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()),self.assertRaises(SystemExit):
                self.d.critical_spec(args,'critical-task','d1','fixture:source')

    def test_exact_acknowledgment_opens_gate_without_acquisition(self):
        p=self.protection();result=p.prepare()
        self.assertEqual(result['gate'],'open')
        self.assertEqual(result['acknowledged_until_utc'],self.receipt['expires_at_utc'])
        self.assertEqual(self.reuse.call_count,1)
        self.k.Native.start_assertion.assert_not_called()

    def test_admission_without_acknowledgment_never_launches_worker(self):
        self.reuse.side_effect=self.admit_without_ack
        receipt,calls=self.supervise()
        self.assertEqual(calls,[]);self.assertEqual(receipt['outcome'],'protection-held')
        self.assertFalse(receipt['worker_started'])
        self.assertIn('timeout',receipt['keep_awake']['failure']['reason'])
        self.assertEqual(self.update.call_args.args[-1],'not-sent')
        self.assertEqual(self.reuse.call_count,1)

    def test_pending_conflict_is_not_retried_or_rebound(self):
        self.reuse.side_effect=FileExistsError('existing pending request')
        with self.assertRaises(self.d.ProtectionHold):self.protection().prepare()
        self.assertEqual(self.reuse.call_count,1)

    def test_every_owner_and_source_binding_is_pinned(self):
        for field,value in [('task_id','wrong'),('owner','wrong'),('generation','wrong'),
                ('host_id','wrong'),('approval_ref','wrong'),('foreground_ref','wrong'),
                ('kind','legacy'),('supervisor_identity',{'pid':77777,'started':'other','executable':'other'}),
                ('authorized_until_utc',self.k.stamp(self.clock+timedelta(seconds=100)))]:
            before=self.receipt[field];self.receipt[field]=value
            with self.subTest(field=field),self.assertRaises(self.d.ProtectionHold):self.protection().prepare()
            self.receipt[field]=before
        for field in ('task_id','dispatch_id','source_pin'):
            p=self.protection();p.spec=copy.deepcopy(p.spec);p.spec[field]='wrong'
            with self.subTest(field=field),self.assertRaises(self.d.ProtectionHold):p.prepare()

    def test_wrong_task_generation_or_shorter_ack_does_not_close_extension(self):
        p=self.protection();p.prepare();old=p.ack_end
        self.advance(26)
        self.renew_grant()
        self.reuse.side_effect=self.admit_without_ack
        p.tick();self.assertIsNotNone(p.pending_end)
        for field,value in [('consumer_task_id','wrong'),('generation','wrong'),('until_utc',old)]:
            row=dict(consumer=p.spec['consumer'],consumer_task_id=p.spec['task_id'],generation='g1',
                     until_utc=p.pending_end,readback_at_utc=self.k.stamp(self.clock));row[field]=value
            self.receipt['consumers'].append(row)
            self.assertEqual(p.tick()['acknowledged_until_utc'],old)
        self.acknowledge('unused',consumer=p.spec['consumer'],task_id=p.spec['task_id'],until_utc=p.pending_end)
        self.assertEqual(p.tick()['gate'],'open');self.assertNotEqual(p.ack_end,old)

    def test_no_refresh_without_newer_grant_and_expiry_holds(self):
        p=self.protection();p.prepare();self.advance(26)
        p.tick();self.assertEqual(self.reuse.call_count,1)
        self.advance(5);self.assertEqual(p.tick()['gate'],'HOLD')

    def test_stale_future_or_wrong_historical_receipt_never_prepares(self):
        original=self.native_status
        for change in ('stale','future','legacy'):
            def invalid(path):
                r=original(path)
                if change=='legacy':r['kind']='legacy'
                else:r['observation']['observed_at_utc']=self.k.stamp(self.clock+timedelta(
                    seconds=-121 if change=='stale' else 1))
                r['assessment']=self.k.assess(r,now=self.k.stamp(self.clock),owner=r['owner'])
                return r
            with self.subTest(change=change),mock.patch.object(self.k,'status',side_effect=invalid), \
                    contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                self.d.critical_spec(self.args,'critical-task','d1','fixture:source')

    def test_change_between_handshake_and_worker_launch_is_not_sent(self):
        original=self.d.CriticalProtection.prepare
        def prepare_then_loss(protection):
            result=original(protection);self.receipt['observation']['assertion']=None;return result
        with mock.patch.object(self.d.CriticalProtection,'prepare',prepare_then_loss):
            receipt,calls=self.supervise()
        self.assertEqual(calls,[]);self.assertEqual(receipt['outcome'],'protection-held')
        self.assertEqual(self.update.call_args.args[-1],'not-sent')

    def test_timeout_remains_business_timeout_without_signaling_protection_owner(self):
        self.params['timeout_seconds']=.05
        self.params['argv']=[sys.executable,'-c','import time; time.sleep(2)']
        (self.dir/'params.json').write_text(json.dumps(self.params))
        receipt,calls=self.supervise()
        self.assertEqual(receipt['outcome'],'timeout');self.assertEqual(len(calls),1)
        self.assertEqual(receipt['keep_awake']['gate'],'open')
        self.k.Native.start_assertion.assert_not_called()

    def test_unacknowledged_extension_does_not_outlive_old_consumer(self):
        p=self.protection();p.prepare();self.advance(26);self.renew_grant()
        self.reuse.side_effect=self.admit_without_ack
        p.tick();self.advance(5)
        self.assertEqual(p.tick()['gate'],'HOLD')
        self.assertIsNotNone(p.pending_end)

    def test_long_same_grant_refreshes_ack_freshness_without_extending_end(self):
        self.receipt['segment_seconds']=300
        self.receipt['authorized_until_utc']=self.k.stamp(self.clock+timedelta(seconds=600))
        self.receipt['expires_at_utc']=self.k.stamp(self.clock+timedelta(seconds=300))
        self.args.critical_until_utc=self.receipt['expires_at_utc']
        self.params['critical']=self.d.critical_spec(self.args,'critical-task','d1','fixture:source')
        p=self.protection();p.prepare();end=p.ack_end
        for _ in range(2):
            self.advance(61);p.tick();p.tick()
            self.assertEqual(p.view()['gate'],'open')
            self.assertEqual(p.ack_end,end)
            self.assertEqual(p.ack_read_at,self.k.stamp(self.clock))
        self.assertEqual(self.reuse.call_count,3)

    def test_missing_worker_is_business_unavailable_with_verified_protection(self):
        self.params['argv']=[str(self.dir/'missing-worker')]
        (self.dir/'params.json').write_text(json.dumps(self.params))
        receipt,calls=self.supervise()
        self.assertEqual(receipt['outcome'],'unavailable')
        self.assertEqual(receipt['keep_awake']['gate'],'open')
        self.assertEqual(len(calls),1)
        self.assertEqual(self.update.call_args.args[-1],'not-sent')

    def test_exact_end_cannot_borrow_freshness_from_a_shorter_row(self):
        p=self.protection();p.prepare()
        exact=copy.deepcopy(self.receipt['consumers'][-1])
        shorter={**exact,'until_utc':self.k.stamp(self.clock+timedelta(seconds=20))}
        for seconds in (-121,1):
            self.receipt['consumers']=[{**exact,'readback_at_utc':self.k.stamp(
                self.clock+timedelta(seconds=seconds))},shorter]
            # Generic reuse is fresh via the shorter row; this exact-end claim must hold.
            self.assertEqual(self.native_status('unused')['assessment']['state'],'verified-now')
            self.assertEqual(p.view()['gate'],'HOLD')

    def test_fresh_but_pre_request_row_does_not_acknowledge_pending_refresh(self):
        self.receipt['segment_seconds']=300
        self.receipt['authorized_until_utc']=self.k.stamp(self.clock+timedelta(seconds=600))
        self.receipt['expires_at_utc']=self.k.stamp(self.clock+timedelta(seconds=300))
        self.args.critical_until_utc=self.receipt['expires_at_utc']
        self.params['critical']=self.d.critical_spec(self.args,'critical-task','d1','fixture:source')
        p=self.protection();p.prepare();old=p.ack_read_at
        self.advance(61);self.reuse.side_effect=self.admit_without_ack
        p.tick();p.tick()
        self.assertIsNotNone(p.pending_end)
        self.assertEqual(p.ack_read_at,old)
        self.advance(11);self.assertEqual(p.tick()['gate'],'HOLD')

    def test_ack_during_probes_must_follow_actual_admission_timestamp(self):
        self.receipt['segment_seconds']=300
        self.receipt['authorized_until_utc']=self.k.stamp(self.clock+timedelta(seconds=600))
        self.receipt['expires_at_utc']=self.k.stamp(self.clock+timedelta(seconds=300))
        self.args.critical_until_utc=self.receipt['expires_at_utc']
        self.params['critical']=self.d.critical_spec(self.args,'critical-task','d1','fixture:source')
        p=self.protection();p.prepare();old=p.ack_read_at;self.advance(61)
        def delayed_admission(path,**kwargs):
            self.acknowledge(path,**kwargs)  # older request's row appears during fresh probes
            self.advance(1)
            return self.admit_without_ack(path,**kwargs)
        self.reuse.side_effect=delayed_admission
        p.tick();p.tick()
        self.assertIsNotNone(p.pending_end);self.assertEqual(p.ack_read_at,old)
        self.acknowledge(p.spec['receipt'],consumer=p.spec['consumer'],task_id=p.spec['task_id'],until_utc=p.pending_end)
        p.tick();self.assertIsNone(p.pending_end)
        self.assertEqual(p.ack_read_at,self.k.stamp(self.clock))

    def test_default_owner_cadence_gets_bounded_handshake_and_freshness_margin(self):
        self.receipt.update(segment_seconds=300,check_seconds=60,
            authorized_until_utc=self.k.stamp(self.clock+timedelta(seconds=600)),
            expires_at_utc=self.k.stamp(self.clock+timedelta(seconds=300)))
        self.args.critical_until_utc=self.receipt['expires_at_utc']
        self.params['critical']=self.d.critical_spec(self.args,'critical-task','d1','fixture:source')
        self.reuse.side_effect=self.admit_without_ack
        def owner_poll(seconds):
            self.advance(seconds)
            if (self.clock-self.start_clock).total_seconds()>=60 and not self.receipt['consumers']:
                self.acknowledge(*self.reuse.call_args.args,**self.reuse.call_args.kwargs)
        self.d.time.sleep.side_effect=owner_poll
        p=self.protection();self.assertEqual(p.prepare()['gate'],'open')
        self.assertEqual(p.wait_seconds,65)
        self.assertGreaterEqual((self.clock-self.start_clock).total_seconds(),60)
        self.advance(31);p.tick();self.assertIsNotNone(p.pending_end)
        self.advance(29)
        self.acknowledge(*self.reuse.call_args.args,**self.reuse.call_args.kwargs)
        self.assertEqual(p.tick()['gate'],'open');self.assertIsNone(p.pending_end)

    def test_slow_owner_missing_ack_is_bounded_before_dispatch(self):
        self.receipt.update(segment_seconds=300,check_seconds=60,
            authorized_until_utc=self.k.stamp(self.clock+timedelta(seconds=600)),
            expires_at_utc=self.k.stamp(self.clock+timedelta(seconds=300)))
        self.args.critical_until_utc=self.receipt['expires_at_utc']
        self.params['critical']=self.d.critical_spec(self.args,'critical-task','d1','fixture:source')
        self.reuse.side_effect=self.admit_without_ack
        with self.assertRaises(self.d.ProtectionHold):self.protection().prepare()
        elapsed=(self.clock-self.start_clock).total_seconds()
        self.assertGreaterEqual(elapsed,65);self.assertLess(elapsed,65.2)
        self.assertEqual(self.reuse.call_count,1)

    def test_new_grant_queues_extension_promptly_and_short_coverage_still_holds(self):
        p=self.protection();p.prepare();self.advance(5);self.renew_grant()
        self.reuse.side_effect=self.admit_without_ack
        p.tick();self.assertIsNotNone(p.pending_end)  #25seconds remain, not only5
        self.advance(26);self.assertEqual(p.tick()['gate'],'HOLD')

    def test_producer_publishes_successor_before_post_renewal_pause(self):
        from test_keep_awake import Fake,request
        backend=Fake();path=self.dir/'producer.json';observed=[]
        def observer(b):
            if any(row[0]=='terminate' for row in b.log):
                saved=json.loads(path.read_text());newest=max(b.handles)
                self.assertEqual(saved['pid'],newest,'reader still sees released old PID after renewal')
                self.assertEqual(saved['events'][-1]['kind'],'bounded-renewal')
                observed.append(newest)
        backend.callback=observer
        req=request(backend,seconds=9,segment=4)
        self.assertEqual(self.k.Supervisor(req,path,backend=backend).run(),0)
        self.assertGreater(len(observed),0)

    def test_producer_successor_is_visible_during_old_assertion_cleanup(self):
        from test_keep_awake import Fake,request
        path=self.dir/'cleanup-boundary.json';checked=[];outer=self
        class Boundary(Fake):
            def assertion_absent(self,pid):
                newest=max(self.handles)
                if pid!=newest and self.handles[newest].poll() is None:
                    current=outer.real_owner_status(path,backend=self)
                    outer.assertEqual(current['pid'],newest)
                    outer.assertEqual(current['assessment']['state'],'verified-now')
                    checked.append(newest)
                return super().assertion_absent(pid)
        b=Boundary();self.assertEqual(self.k.Supervisor(request(b,seconds=9,segment=4),path,backend=b).run(),0)
        self.assertGreater(len(checked),0)

    def test_owner_status_retries_only_a_same_contract_successor(self):
        from test_keep_awake import Fake,request
        b=Fake();path=self.dir/'read-race.json';req=request(b,seconds=10,segment=4)
        runner=self.k.Supervisor(req,path,backend=b)
        receipt={**req,'kind':'owned-keep-awake','generation':'g','state':'running',
                 'supervisor_identity':b.process(os.getpid()),'freshness_seconds':120}
        runner._acquire(receipt);self.k._save(path,receipt);old=runner.grants[-1]
        b.tick=1;successor=copy.deepcopy(receipt);runner._acquire(successor)
        observe=b.observe;calls=[]
        def race(snapshot):
            calls.append(snapshot['pid'])
            if len(calls)==1:
                self.k._save(path,successor);runner._stop_grant(*old)
            return observe(snapshot)
        try:
            with mock.patch.object(b,'observe',side_effect=race):
                current=self.real_owner_status(path,backend=b)
            self.assertEqual(current['assessment']['state'],'verified-now')
            self.assertEqual(calls,[old[0].pid,successor['pid']])
            runner._stop_grant(*runner.grants[-1]);calls.clear()
            with mock.patch.object(b,'observe',side_effect=lambda r:(calls.append(r['pid']) or observe(r))):
                lost=self.real_owner_status(path,backend=b)
            self.assertEqual(lost['assessment']['state'],'coverage-lost');self.assertEqual(len(calls),1)
        finally:
            for grant in runner.grants:runner._stop_grant(*grant)

    def test_owner_status_does_not_retry_into_a_different_owner_contract(self):
        path=self.dir/'changed-contract.json';self.k._save(path,self.receipt)
        class Changed(self.k.Native):
            def now(inner):return self.clock
            def observe(inner,receipt):
                self.k._save(path,{**receipt,'owner':'different-owner'})
                return copy.deepcopy(self.receipt['observation'])
        current=self.real_owner_status(path,backend=Changed())
        self.assertEqual(current['owner'],'owner')
        self.assertEqual(current['assessment']['state'],'unknown')
        self.assertEqual(current['observation']['probe_error'],'receipt-contract-changed')

    def test_native_probe_pid_power_and_owner_loss_hold(self):
        for change in ('pid','assertion','power','probe'):
            run=self.dir/change;run.mkdir()
            p=self.d.CriticalProtection(self.params,run);p.prepare();saved=copy.deepcopy(self.receipt)
            obs=self.receipt['observation']
            if change=='pid':obs['process']={**obs['process'],'started':'reused'}
            if change=='assertion':obs['assertion']=None
            if change=='power':obs['power']['source']='Battery Power'
            if change=='probe':obs['probe_error']='denied'
            self.assertEqual(p.tick()['gate'],'HOLD',change)
            self.receipt=saved

    def test_recheck_before_popen_and_critical_path_has_no_caffeinate(self):
        receipt,calls=self.supervise()
        self.assertEqual(receipt['outcome'],'done');self.assertEqual(len(calls),1)
        self.assertEqual(receipt['keep_awake']['gate'],'open')
        self.assertNotIn('caffeinate',calls[0]);self.k.Native.start_assertion.assert_not_called()

    def test_running_business_result_survives_coverage_loss(self):
        def loss():self.receipt['observation']['supervisor']=None
        receipt,calls=self.supervise(on_launch=loss)
        self.assertEqual(receipt['outcome'],'done');self.assertEqual(len(calls),1)
        self.assertEqual(receipt['keep_awake']['gate'],'HOLD')
        self.assertEqual(receipt['keep_awake']['state'],'coverage-lost')
        self.assertIn('failure',receipt['keep_awake'])

    def test_loss_in_final_readback_remains_sticky_after_later_positive_probe(self):
        p=self.protection();p.prepare()
        good=self.native_status('unused');bad=copy.deepcopy(good)
        bad['observation']['supervisor']=None
        with mock.patch.object(self.k,'status',side_effect=[good,bad]):
            result=p.tick()
        self.assertEqual(result['state'],'coverage-lost');self.assertIn('failure',result)
        self.assertEqual(p.tick()['gate'],'HOLD')

    def test_status_and_wait_freshen_protection_without_rewriting_business(self):
        receipt,_=self.supervise()
        original=(self.dir/'receipt.json').read_bytes()
        self.receipt['observation']['supervisor']=None
        self.patch(self.d,'runs',return_value=[self.dir]);self.patch(self.d,'latest_run',return_value=self.dir)
        self.patch(self.d,'run_state',return_value='done')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.d.main(['status'])
        self.assertEqual(json.loads(out.getvalue())['keep_awake_current']['state'],'coverage-lost')
        out=io.StringIO()
        with contextlib.redirect_stdout(out),self.assertRaises(SystemExit) as caught:
            self.d.main(['wait','critical-task','--timeout','1'])
        self.assertEqual(caught.exception.code,1)
        value=json.loads(out.getvalue());self.assertEqual(value['outcome'],'done')
        self.assertEqual(value['keep_awake_current']['gate'],'HOLD')
        self.assertEqual(original,(self.dir/'receipt.json').read_bytes())


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
