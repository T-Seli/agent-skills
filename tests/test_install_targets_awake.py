import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TargetAndAwakeTests(unittest.TestCase):
    def test_installed_safeguard_entrypoint_binds_the_linked_release_from_an_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as cwd:
            env = dict(os.environ, HOME=home)
            installed = subprocess.run([str(ROOT / "install.sh"), "--target=codex"],
                                       env=env, capture_output=True, text=True)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            stale = Path(cwd) / "stale"
            for package, message in ((stale / "agent_skills", "stale PYTHONPATH imported"),
                                     (Path(cwd) / "agent_skills", "stale CWD imported")):
                package.mkdir(parents=True)
                (package / "__init__.py").write_text("")
                (package / "safeguard_cli.py").write_text(
                    f"raise SystemExit({message!r})\n")
            (stale / "sitecustomize.py").write_text(
                "import agent_skills.safeguard_cli\n"
                "raise SystemExit('stale sitecustomize imported')\n")
            (Path(cwd) / "json.py").write_text(
                "raise SystemExit('caller CWD dependency imported')\n")
            entrypoint = Path(home) / ".agents/skills/workflow-contracts/scripts/safeguard-cli"
            head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.strip()
            status_before = subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all"],
                check=True, capture_output=True, text=True).stdout
            result = subprocess.run(
                [str(entrypoint), "release", str(ROOT), head, head], cwd=cwd,
                env={**env, "PYTHONPATH": str(stale)}, capture_output=True, text=True)
            status_after = subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all"],
                check=True, capture_output=True, text=True).stdout
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'"reviewed_commit": "{head}"', result.stdout)
            self.assertEqual(status_after, status_before)
            self.assertNotIn("stale PYTHONPATH imported", result.stderr)
            self.assertNotIn("stale CWD imported", result.stderr)
            self.assertNotIn("stale sitecustomize imported", result.stderr)
            self.assertNotIn("caller CWD dependency imported", result.stderr)

        with tempfile.TemporaryDirectory() as home:
            missing = Path(home) / ".agents/skills/workflow-contracts/scripts/safeguard-cli"
            with self.assertRaises(FileNotFoundError):
                subprocess.run([str(missing), "--help"], check=False)

    def _transaction_entries(self, home):
        return list(Path(home).glob(".claude/backup-*/transaction/entry-*"))

    def _entry_for(self, home, target):
        for entry in self._transaction_entries(home):
            if entry.is_dir() and (entry / "path").read_text().strip() == str(target):
                return entry
        return None

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

    def test_install_is_single_owner_idempotent_atomic_and_preserves_user_edit(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home)
            command = [str(ROOT / "install.sh"), "--target=codex"]
            first = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            guidance = Path(home) / ".codex/AGENTS.md"
            before, inode = guidance.read_text(), guidance.stat().st_ino
            backup_count = len(list((Path(home) / ".claude").glob("backup-*")))
            second = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(guidance.stat().st_ino, inode)
            self.assertIn("content already current", second.stdout)
            self.assertEqual(len(list((Path(home) / ".claude").glob("backup-*"))), backup_count)
            self.assertIn("install transaction: no changes", second.stdout)

            guidance.write_text(before + "\nuser edit with the same first line\n")
            third = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(third.returncode, 0, third.stderr)
            backups = [
                entry / "original"
                for entry in self._transaction_entries(home)
                if entry.is_dir()
                and (entry / "path").read_text().strip() == str(guidance)
                and (entry / "type").read_text().strip() == "original"
            ]
            self.assertEqual(len(backups), 1)
            self.assertIn("user edit with the same first line", backups[0].read_text())
            self.assertEqual(guidance.read_text(), before)

            unchanged = guidance.read_text()
            failed_env = dict(env, AWK=shutil.which("false"))
            failed = subprocess.run(command, env=failed_env, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(guidance.read_text(), unchanged)
            self.assertIn("install incomplete at codex", failed.stderr)

        with tempfile.TemporaryDirectory() as home:
            lock = Path(home) / ".agent-skills-install.lock"
            lock.mkdir()
            (lock / "owner").write_text("other-owner\n")
            denied = subprocess.run([str(ROOT / "install.sh"), "--target=codex"],
                                    env=dict(os.environ, HOME=home), capture_output=True, text=True)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("other-owner", denied.stderr)
            self.assertFalse((Path(home) / ".agents").exists())

    def test_failed_fresh_install_rolls_back_all_targets_and_keeps_receipt(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, AWK=shutil.which("false"))
            result = subprocess.run([str(ROOT / "install.sh"), "--target=codex"],
                                    env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(home) / ".agents").exists())
            self.assertFalse((Path(home) / ".codex").exists())
            receipts = list(Path(home).glob(".agent-skills-install-failure-*"))
            self.assertEqual(len(receipts), 1)
            self.assertTrue(list(receipts[0].glob("entry-*/path")))
            self.assertIn("rolling back install transaction", result.stderr)

    def test_custom_symlink_is_backed_up_and_restored_on_later_failure(self):
        with tempfile.TemporaryDirectory() as home:
            home_path = Path(home)
            custom_source = home_path / "custom-agent-coordination"
            custom_source.mkdir()
            target = home_path / ".agents/skills/agent-coordination"
            target.parent.mkdir(parents=True)
            target.symlink_to(custom_source)

            env = dict(os.environ, HOME=home)
            success = subprocess.run([str(ROOT / "install.sh"), "--target=codex"],
                                     env=env, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertNotEqual(os.readlink(target), str(custom_source))
            entry = self._entry_for(home, target)
            self.assertIsNotNone(entry)
            self.assertEqual((entry / "type").read_text().strip(), "symlink")
            self.assertEqual((entry / "link").read_text().strip(), str(custom_source))

        with tempfile.TemporaryDirectory() as home:
            home_path = Path(home)
            custom_source = home_path / "custom-agent-coordination"
            custom_source.mkdir()
            target = home_path / ".agents/skills/agent-coordination"
            target.parent.mkdir(parents=True)
            target.symlink_to(custom_source)
            env = dict(os.environ, HOME=home, AWK=shutil.which("false"))
            failed = subprocess.run([str(ROOT / "install.sh"), "--target=codex"],
                                    env=env, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertTrue(target.is_symlink())
            self.assertEqual(os.readlink(target), str(custom_source))
            self.assertFalse((home_path / ".codex").exists())

    def test_claude_install_seeds_the_worker_config_once(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home)
            command = [str(ROOT / "install.sh"), "--target=claude"]
            first = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            config = Path(home) / ".config/agent-skills/workers.json"
            example = ROOT / "agent_skills/delegate_config.example.json"
            self.assertEqual(config.read_text(), example.read_text())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            config.write_text('{"edited": true}\n')
            again = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(config.read_text(), '{"edited": true}\n')

    def test_critical_wrapper_bounds_assertion_and_returns_child_status(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "caffeinate"
            fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\n")
            fake.chmod(0o755)
            capture = Path(temp) / "args"
            env = dict(os.environ, PATH=f"{temp}:{os.environ['PATH']}", CAPTURE=str(capture))
            script = str(ROOT / "scripts" / "critical-local-work.sh")
            result = subprocess.run([script, "task-1", "60", "--", "/bin/sh", "-c", "exit 7"], env=env)
            self.assertEqual(result.returncode, 7)
            for _ in range(50):  # caffeinate runs beside the command; give it a moment to record
                if capture.exists() and capture.read_text().count("\n") >= 5:
                    break
                time.sleep(0.05)
            args = capture.read_text().splitlines()
            self.assertEqual(args[:4], ["-i", "-t", "60", "-w"])
            self.assertTrue(args[4].isdigit())
            piped = subprocess.run([script, "task-1", "60", "--", "cat"], env=env, input=b"brief\n",
                                   capture_output=True)
            self.assertEqual(piped.stdout, b"brief\n")
            for value in ("0", "14401", "oops"):
                result = subprocess.run([script, "task-1", value, "--", "/bin/true"],
                                        env=env, capture_output=True)
                self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
