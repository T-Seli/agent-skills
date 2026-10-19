"""The delegated-worker guard: routine work passes, release/production/self-modifying calls block, errors block."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "guard" / "worker-guard.py"


class WorkerGuardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        release = self.home / "Developer" / "release-x"
        (release / "skills" / "monitor").mkdir(parents=True)
        (self.home / ".claude" / "skills").mkdir(parents=True)
        (self.home / ".claude" / "skills" / "monitor").symlink_to(release / "skills" / "monitor")
        self.release = release
        self.repo = self.home / "Developer" / "project"
        self.repo.mkdir()

    def guard(self, tool, **tool_input):
        if isinstance(tool, bytes):
            raw = tool
        else:
            raw = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(self.repo)}).encode()
        p = subprocess.run([sys.executable, str(GUARD)], input=raw, capture_output=True,
                           env={**os.environ, "HOME": str(self.home)})
        return p.returncode, p.stderr.decode()

    def bash(self, command):
        return self.guard("Bash", command=command)[0]

    def test_routine_commands_pass(self):
        for command in ["git status", "git diff --stat", "git log --grep push", "git commit -m wip",
                        "git -C ../other log -3", "python3 -m unittest", "node build.js", "ls -la",
                        "mkdir -p build", "npm test", "rg deploy docs/", "grep -rn 'git push' --include=*.md . | wc -l",
                        "timeout 30 python3 run.py", "aws --region us-west-1 logs tail /x",
                        "aws s3 cp s3://bucket/key ./key", "git config --get user.email",
                        "kubectl get pods", "terraform plan", "cat .env.example", "echo hi > out.txt 2>&1",
                        "claude --version", "claude agents --json --all", "gh pr view 12", "gh release list"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 0)

    def test_release_production_and_escape_commands_block(self):
        for command in ["git push origin main", "git -C repo push", "cd x && git push --force",
                        "bash -c 'git status; git push'", "sh -c \"npm run deploy\"",
                        "python3 -c \"import os; os.system('git push')\"", "./scripts/deploy.sh prod",
                        "npm run deploy:prod", "make deploy", "serverless deploy", "kubectl apply -f x.yaml",
                        "docker push img", "ssh ubuntu@203.0.113.7 uptime", "timeout 9 ssh host",
                        "scp a host:/tmp/a", "rsync -a dist/ host:/srv/", "psql \"$DATABASE_URL\" -c 'select 1'",
                        "aws lambda update-function-code --function-name f", "aws --profile p ec2 terminate-instances",
                        "aws s3 cp ./x s3://bucket/x", "aws s3 rm s3://bucket/x", "gh pr create --fill",
                        "gh pr merge 12", "gh api -X POST repos/o/r/issues", "gh api repos/o/r/labels -f name=x",
                        "git config core.hooksPath /tmp/h", "git remote set-url origin x",
                        "claude -p 'do it' --dangerously-skip-permissions", "claude -p hi",
                        "codex exec hi", "crontab -l", "launchctl load x.plist", "defaults write com.x k v",
                        "cat .env", "source config/.env.local", "cat ~/.ssh/id_ed25519", "eval 'git push'"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 2)

    def test_writes_to_skills_settings_hooks_and_git_config_block(self):
        installed = self.release / "skills" / "monitor" / "SKILL.md"
        for command in [f"echo x >> {installed}", "echo '{}' > ~/.claude/settings.json",
                        "cp hook .git/hooks/pre-commit", "sed -i '' s/a/b/ .git/config",
                        "cd ~/.claude && echo x > settings.json", "ln -s /tmp/h ~/.claude/hooks/h.sh",
                        "echo x >> ~/.zshrc", "mkdir -p ~/Library/LaunchAgents"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 2)
        for tool, path in [("Write", str(installed)), ("Edit", "~/.claude/settings.json"),
                           ("Edit", ".claude/settings.local.json"), ("Write", ".git/hooks/post-checkout"),
                           ("Write", ".mcp.json"), ("Write", str(self.home / ".codex" / "config.toml"))]:
            with self.subTest(tool=tool, path=path):
                self.assertEqual(self.guard(tool, file_path=path)[0], 2)
        self.assertEqual(self.guard("Write", file_path="src/app.py")[0], 0)
        self.assertEqual(self.guard("Read", file_path=".env")[0], 2)
        self.assertEqual(self.guard("Read", file_path="README.md")[0], 0)

    def test_unreadable_input_blocks_and_explains(self):
        code, err = self.guard(b"not json")
        self.assertEqual(code, 2)
        self.assertIn("could not inspect", err)
        code, err = self.bash("git push"), self.guard("Bash", command="git push")[1]
        self.assertIn("report it to your parent as a blocker", err)

    def test_settings_deny_rules_parse(self):
        rules = json.loads((ROOT / "guard" / "worker-settings.json").read_text())["permissions"]["deny"]
        self.assertIn("Bash(git push:*)", rules)


if __name__ == "__main__":
    unittest.main()
