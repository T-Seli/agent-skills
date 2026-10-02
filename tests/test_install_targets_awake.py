import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TargetAndAwakeTests(unittest.TestCase):
    def test_targeted_dry_runs_do_not_cross_install(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home)
            for target, included, omitted in (
                ("claude", "/.claude/skills/", "/.codex/AGENTS.md"),
                ("codex", "/.codex/AGENTS.md", "/.claude/skills/"),
            ):
                result = subprocess.run([str(ROOT / "install.sh"), "--dry-run", f"--target={target}"],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(included, result.stdout)
                self.assertNotIn(omitted, result.stdout)
                self.assertEqual(list(Path(home).iterdir()), [])
            denied = subprocess.run([str(ROOT / "install.sh"), "--dry-run", "--target=dot"],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(denied.returncode, 2)

    def test_critical_wrapper_bounds_assertion_and_returns_child_status(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "caffeinate"
            fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\nshift 3\nexec \"$@\"\n")
            fake.chmod(0o755)
            capture = Path(temp) / "args"
            env = dict(os.environ, PATH=f"{temp}:{os.environ['PATH']}", CAPTURE=str(capture))
            script = str(ROOT / "scripts" / "critical-local-work.sh")
            result = subprocess.run([script, "task-1", "60", "--", "/bin/sh", "-c", "exit 7"], env=env)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(capture.read_text().splitlines()[:3], ["-i", "-t", "60"])
            for value in ("0", "14401", "oops"):
                result = subprocess.run([script, "task-1", value, "--", "/bin/true"],
                                        env=env, capture_output=True)
                self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
