import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_skills.test_gate import decide, runs_tests  # noqa: E402

CLI = "/release/skills/workflow-contracts/scripts/safeguard-cli"


class RunsTestsTests(unittest.TestCase):
    def test_test_suite_commands_are_recognized(self):
        for command in ("npm test", "npm --prefix server test", "cd server && npm run test:diff", "pnpm t",
                        "FOO=1 yarn run test:unit", "node --test server/test", "npx vitest run", "pytest -q",
                        "python3 -m unittest discover -s tests", "go test ./...", "cargo test", "env CI=1 jest",
                        "git status; npm run test 2>&1 | tail -5"):
            self.assertTrue(runs_tests(command), command)

    def test_other_commands_pass(self):
        for command in ("grep -rn test src", "npm install", "npm run build", "node server.mjs", "cat test.log",
                        "git commit -m 'npm test passes'", "python3 -m json.tool x.json", "ls tests"):
            self.assertFalse(runs_tests(command), command)


class DecideTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def event(self, command, tool="Bash"):
        return {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(self.repo)}

    def test_bare_suite_is_denied_with_the_wrapped_command(self):
        reason = decide(self.event("npm run test:diff"), CLI)
        self.assertIn(f"{CLI} test-slot 'npm run test:diff'", reason)
        self.assertIn("--weight 2", reason)

    def test_wrapped_unrelated_and_non_bash_calls_pass(self):
        self.assertIsNone(decide(self.event(f"{CLI} test-slot 'npm test'"), CLI))
        self.assertIsNone(decide(self.event("npm run build"), CLI))
        self.assertIsNone(decide(self.event("npm test", tool="Read"), CLI))

    def test_a_project_whose_runner_slots_itself_runs_bare(self):
        (self.repo / "CLAUDE.md").write_text("## Run & test\n- Test slot: `runner` (the runner slots each suite)\n")
        self.assertIsNone(decide(self.event("npm test"), CLI))
        (self.repo / "CLAUDE.md").write_text("## Run & test\n- Test slot: `agent`\n")
        self.assertIsNotNone(decide(self.event("npm test"), CLI))


class HookScriptTests(unittest.TestCase):
    def test_linked_hook_denies_through_the_release_it_points_into(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "test-gate.sh"
            link.symlink_to(ROOT / "hooks" / "test-gate.sh")
            event = {"tool_name": "Bash", "tool_input": {"command": "npm test"}, "cwd": tmp}
            out = subprocess.run([str(link)], input=json.dumps(event), capture_output=True, text=True,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(out.returncode, 0, out.stderr)
        decision = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn(f"{ROOT}/skills/workflow-contracts/scripts/safeguard-cli test-slot 'npm test'",
                      decision["permissionDecisionReason"])

    def test_settings_snippet_registers_the_gate_for_bash(self):
        hooks = json.loads((ROOT / "settings.snippet.json").read_text())["hooks"]["PreToolUse"]
        self.assertIn({"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/test-gate.sh",
                                                     "timeout": 10}]}, hooks)
