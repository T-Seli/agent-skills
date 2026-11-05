import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestSlotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.procs = []
        self.addCleanup(lambda: [p.kill() for p in self.procs if p.poll() is None])
        self.configure({"test_slots": 1})

    def configure(self, config):
        (self.tmp / "workers.json").write_text(json.dumps(config))

    def start(self, command, *args):
        env = dict(os.environ, AGENT_SKILLS_CONFIG=str(self.tmp / "workers.json"),
                   AGENT_SKILLS_TEST_SLOTS=str(self.tmp / "slots"), PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.Popen([sys.executable, "-m", "agent_skills.safeguard_cli", "test-slot", *args, command],
                                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(proc)
        return proc

    def holding(self, command="exec sleep 60"):
        proc = self.start(command)
        deadline = time.time() + 10
        while time.time() < deadline:
            if any(path.read_text() for path in (self.tmp / "slots").glob("slot-*.lock")):
                return proc
            time.sleep(0.05)
        self.fail("holder never took a slot: " + (proc.stderr.read() if proc.poll() is not None else ""))

    def test_second_run_waits_until_the_first_exits(self):
        first = self.holding("exec sleep 2")
        marker = self.tmp / "ran"
        second = self.start(f"touch {marker}")
        time.sleep(0.7)
        self.assertIsNone(first.poll())
        self.assertFalse(marker.exists())
        self.assertEqual(second.wait(timeout=15), 0)
        self.assertTrue(marker.exists())

    def test_killing_the_holder_frees_the_slot_within_two_seconds(self):
        first = self.holding()
        os.kill(first.pid, signal.SIGKILL)
        first.wait()
        started = time.time()
        second = self.start("true", "--wait-seconds", "10")
        self.assertEqual(second.wait(timeout=15), 0, second.stderr.read())
        self.assertLess(time.time() - started, 4)

    def test_timeout_exits_75_and_lists_the_holder(self):
        first = self.holding()
        second = self.start("true", "--wait-seconds", "1")
        self.assertEqual(second.wait(timeout=15), 75)
        err = second.stderr.read()
        self.assertIn(str(first.pid), err)
        self.assertIn("exec sleep 60", err)

    def test_default_is_two_slots_and_stderr_names_the_source(self):
        self.configure({})
        self.holding()
        self.holding()
        third = self.start("true", "--wait-seconds", "1")
        self.assertEqual(third.wait(timeout=15), 75)
        self.assertIn("2 slots (default)", third.stderr.read())

    def test_invalid_slot_count_is_an_error_not_a_default(self):
        for bad in (0, "two", True):
            self.configure({"test_slots": bad})
            proc = self.start("true")
            self.assertEqual(proc.wait(timeout=15), 1, bad)
            self.assertIn("test_slots", proc.stderr.read())

    def test_command_exit_status_passes_through(self):
        self.assertEqual(self.start("exit 3").wait(timeout=15), 3)

    def wait_gone(self, pid, seconds=3):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.05)
        return False

    def test_run_ends_and_slot_frees_when_its_caller_dies(self):
        pidfile = self.tmp / "sleep.pid"
        env = dict(os.environ, AGENT_SKILLS_CONFIG=str(self.tmp / "workers.json"),
                   AGENT_SKILLS_TEST_SLOTS=str(self.tmp / "slots"), PYTHONDONTWRITEBYTECODE="1")
        inner = f"sleep 300 & echo $! > {pidfile}; wait"
        caller = subprocess.Popen(["/bin/sh", "-c", f"{sys.executable} -m agent_skills.safeguard_cli test-slot '{inner}'; true"],
                                  cwd=ROOT, env=env, stderr=subprocess.DEVNULL)
        self.procs.append(caller)
        deadline = time.time() + 10
        while not (pidfile.exists() and pidfile.read_text().strip()) and time.time() < deadline:
            time.sleep(0.05)
        sleeper = int(pidfile.read_text())
        self.addCleanup(lambda: subprocess.run(["kill", "-9", str(sleeper)], stderr=subprocess.DEVNULL))
        os.kill(caller.pid, signal.SIGKILL)
        caller.wait()
        self.assertTrue(self.wait_gone(sleeper), "the run outlived its caller")
        self.assertEqual(self.start("true", "--wait-seconds", "3").wait(timeout=15), 0)

    def test_terminating_test_slot_ends_the_whole_run(self):
        pidfile = self.tmp / "sleep.pid"
        holder = self.holding(f"sleep 300 & echo $! > {pidfile}; wait")
        deadline = time.time() + 10
        while not (pidfile.exists() and pidfile.read_text().strip()) and time.time() < deadline:
            time.sleep(0.05)
        sleeper = int(pidfile.read_text())
        self.addCleanup(lambda: subprocess.run(["kill", "-9", str(sleeper)], stderr=subprocess.DEVNULL))
        holder.terminate()
        self.assertEqual(holder.wait(timeout=10), 128 + signal.SIGTERM)
        self.assertTrue(self.wait_gone(sleeper), "SIGTERM left the run's background process alive")

    def test_background_leftovers_end_when_the_command_finishes(self):
        pidfile = self.tmp / "sleep.pid"
        self.assertEqual(self.start(f"sleep 300 & echo $! > {pidfile}").wait(timeout=15), 0)
        sleeper = int(pidfile.read_text())
        self.addCleanup(lambda: subprocess.run(["kill", "-9", str(sleeper)], stderr=subprocess.DEVNULL))
        self.assertTrue(self.wait_gone(sleeper), "a background process outlived the finished run")
