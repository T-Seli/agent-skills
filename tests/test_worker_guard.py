"""The delegated-worker guard: routine work passes, release/production/self-modifying calls block, errors block."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
                        "aws s3 cp s3://bucket/key ./key", "aws s3 cp s3://b/k ./k --quiet --recursive",
                        "git config --get user.email",
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
                        "aws s3 cp ./dist s3://bucket/ --recursive --cache-control max-age=0",
                        "aws s3 sync dist s3://b --delete --exclude index.html",
                        "gh pr merge 12", "gh api -X POST repos/o/r/issues", "gh api repos/o/r/labels -f name=x",
                        "git config core.hooksPath /tmp/h", "git remote set-url origin x",
                        "claude -p 'do it' --dangerously-skip-permissions", "claude -p hi",
                        "codex exec hi", "crontab -l", "launchctl load x.plist", "defaults write com.x k v",
                        "cat .env", "source config/.env.local", "cat ~/.ssh/id_ed25519", "eval 'git push'"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 2)

    def test_observed_false_positives_pass(self):
        # Sanitized from live worker streams (Oct 20): each was blocked before.
        for command in [
                "T=tasks/x && mkdir -p $T && cat > $T/log.md <<'EOF'\nDecisions: build/test/deploy/monitor approved"
                " (parent). This worker builds items 1-3 only; deploy and monitoring stay with the parent session.\n"
                "EOF\ngit add $T && git commit -q -F - <<'EOF'\nrefactor: move ranking (no deploy)\nEOF\ngit log -1",
                "sed -n 90,110p scripts/pre-deploy/health.ts; ls -la /repo/.env 2>&1 | cut -c1-60",
                "cat >> tasks/x/log.md <<'EOF'\nNot done: the release test step still needs .env (worker guard); "
                "parent runs it.\nEOF\ngit add tasks/x/log.md && git commit -q -m \"fix(x): a writer's refusal reaches"
                " the agent\" -m \"it heard \\\"offer to retry\\\" instead\"",
                "rm -f /tmp/tmp.abc /tmp/s/baseline.tap; git worktree list | grep _base; cat >> tasks/x/log.md <<'EOF'\n"
                "Not done: parent runs the dry-runs (both need server/.env and a tenant DB).\nEOF\n"
                "git add tasks/x/log.md && git commit -q -m \"docs(tasks): log\n\nCo-Authored-By: A <a@example.com>\"",
                "cd /repo; git update-ref refs/backup/x 6a75c4f0 && git merge --ff-only 0679aa45 2>&1 | tail -1; "
                "git rev-parse HEAD HEAD^{tree}; ls node_modules .env 2>&1 | head -3",
                "O=/tmp/o; mkdir -p $O; python3 - \"$O\" <<'EOF'\nimport json,sys\nout={\"build\":\"npm run build\",\n"
                "\"deployment\":\"none\"}\njson.dump(out,open(sys.argv[1]+'/receipt.json','w'))\nEOF",
                "git show --stat HEAD | head; ls tasks 2>/dev/null | tail -3; cat ~/.config/agent-skills/workers.json"
                " 2>/dev/null | python3 -c \"import json,sys;print(json.load(sys.stdin).get('repo'))\" 2>&1",
                "grep -n '\"pre-deploy\\|\"predeploy\\|\"deploy' package.json | cut -c1-250; "
                "grep -n \"pre-deploy\\|predeploy\" src/deploy/agent.sh | head -20",
                "grep -n '\"test\\|\"lint' package.json; ls -la node_modules .env 2>&1 | head -3; "
                "grep -n -A8 \"Run & test\" CLAUDE.md | head -20",
                "cd /repo; timeout 8 git fetch origin 2>&1 | tail -2; git rev-parse origin/main main; "
                "ls -la wt/node_modules wt/.env 2>&1 | head -3; ls tasks | grep -E \"alert-proof|booking\"",
                "sed -n 1,6p tasks/x/log.md | cut -c1-300; cat ~/.config/agent-skills/workers.json 2>/dev/null"
                " | grep -o '\"task_history_repo\"[^,}]*'"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 0)

    def test_data_metadata_and_reads_pass(self):
        for command in ["cat ~/.config/agent-skills/workers.json 2>/dev/null", "ls -la .env", "test -f .env",
                        "[ -e .env ] && echo yes", "printf 'see .env docs' >> log.md", "git commit -m \"needs .env\"",
                        "git commit -m \"$(cat <<'EOF'\nfix: don't read .env; deploy stays manual\nEOF\n)\"",
                        "cat >> log.md <<-EOF\n\tparent runs git push; npm run deploy\n\tEOF\ngit status",
                        "# don't push yet\ngit status", "echo hi &>/dev/null", "gh pr list", "gh pr diff 3",
                        "gh pr checks 3", "gh run view 9 --log", "gh run list", "gh api repos/o/r/pulls",
                        "gh api -X GET search/issues -f q=x", "gh release view v1", "aws configure list-profiles"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 0)

    def test_secret_reads_outward_actions_and_code_heredocs_block(self):
        for command in [
                # observed true positive
                "aws configure list-profiles 2>&1 | head; ls ~/.aws 2>&1; grep -c \"^AWS_\" .env 2>/dev/null",
                "grep -o \"^AWS_[A-Z_]*\" .env", "ls ~/.aws", "ls -la ~/.ssh", "cd ~/.aws && cat credentials",
                "aws configure get aws_secret_access_key", "head -3 .env", "less .env", "sed -n 1p .env",
                "awk 1 .env", "source .env", ". ./.env", "cp .env /tmp/x", "base64 .env", "xxd .env", "cat \".env\"",
                "cat \"my dir/.env\"", "X=$(cat .env)", "echo \"$(tail .env)\"", "while read l; do :; done < .env",
                "DOTENV_CONFIG_PATH=.env node app.js",
                "python3 -c \"import subprocess;subprocess.run(['git','-C','x','push'])\"",
                "gh pr comment 1 -b x", "gh pr review 1 --approve", "gh pr edit 1 --title x", "gh pr close 1",
                "gh pr reopen 1", "gh pr ready 1", "gh pr merge 1", "gh issue create -t x", "gh issue comment 1 -b x",
                "gh issue edit 1 --add-label x", "gh issue close 1", "gh release create v1", "gh workflow run ci.yml",
                "gh api --method=PATCH repos/o/r", "gh api -XDELETE repos/o/r/labels/x", "gh api graphql --input q.json",
                "bash -c 'git push'", "npm run deploy", "terraform apply", "helm upgrade x y", "vercel --prod",
                "cat > log.md <<'EOF'\nnotes\nEOF\nnpm run deploy",
                "python3 - <<'EOF'\nimport os\nos.system('git push origin main')\nEOF",
                "bash <<'EOF'\ngit status\ngit push\nEOF", "sh -s <<'EOF'\nnpm run deploy\nEOF",
                "node <<'EOF'\nrequire('child_process').execSync('git push')\nEOF", "cat <<'EOF' | bash\ngit push\nEOF",
                "if true; then git push; fi", "for b in a; do git push; done", "f() { git push; }; f",
                "git \\\npush", "echo \"$(git push)\""]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 2)
        for command in ["echo x > ~/.config/agent-skills/workers.json", "tee ~/.claude/settings.json",
                        "echo x > \"$HOME/.claude/settings.json\"", "cat > ~/.claude/settings.json <<'EOF'\n{}\nEOF"]:
            with self.subTest(command=command):
                self.assertIn("writes to skills", self.guard("Bash", command=command)[1])
        self.assertEqual(self.guard("Read", file_path="~/.aws/config")[0], 2)

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
        self.assertEqual(self.guard("Monitor", command="git push origin main")[0], 2)
        self.assertEqual(self.guard("Monitor", command="tail -f build.log")[0], 0)
        self.assertEqual(self.guard("Read", file_path=".env")[0], 2)
        self.assertEqual(self.guard("Read", file_path="README.md")[0], 0)

    def test_unreadable_input_blocks_and_explains(self):
        code, err = self.guard(b"not json")
        self.assertEqual(code, 2)
        self.assertIn("could not inspect", err)
        code, err = self.bash("git push"), self.guard("Bash", command="git push")[1]
        self.assertIn("report it to your parent as a blocker", err)
        for command in ["echo \"unterminated", "git status 'x", "echo $(ls"]:
            with self.subTest(command=command):
                self.assertIn("could not inspect", self.guard("Bash", command=command)[1])

    def test_settings_deny_rules_parse(self):
        rules = json.loads((ROOT / "guard" / "worker-settings.json").read_text())["permissions"]["deny"]
        self.assertNotIn("Bash(git push:*)", rules)  # the guard decides pushes: task branches yes, base only with a grant
        self.assertIn("Bash(ssh:*)", rules)


class PushAndGrantTests(unittest.TestCase):
    """Sharing pushes the task branch; only a live release grant for this repo reaches its base."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.repo = self.home / "widgets"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        (self.repo / "CLAUDE.md").write_text("## Deploy\n- Base branch: `main` · Release branch: `release` · Protected: `main`, `stable`\n")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
        self.git("checkout", "-q", "-b", "feat/x")
        later = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%MZ")
        self.grant = {"repo": "acme/widgets", "base": "main", "targets": ["prod"], "expires": later,
                      "commands": ["npm run deploy:prod", "aws lambda update-function-code"],
                      "hosts": ["ubuntu@203.0.113.7"], "task_id": "t-1", "source": "chat"}

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def bash(self, command, grant=None):
        env = {k: v for k, v in os.environ.items() if k != "AGENT_SKILLS_GRANT"} | {"HOME": str(self.home)}
        if grant is not None:
            env["AGENT_SKILLS_GRANT"] = grant if isinstance(grant, str) else json.dumps(grant)
        raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.repo)}).encode()
        return subprocess.run([sys.executable, str(GUARD)], input=raw, capture_output=True, env=env).returncode

    def test_task_branch_push_and_draft_pr_pass(self):
        for command in ["git push origin feat/x", "git push -u origin feat/x", "git push --set-upstream origin HEAD",
                        "git push origin HEAD:feat/x", "git push origin feat/x:refs/heads/feat/x",
                        "git push -u origin feat/x --no-verify", "cd . && git push -u origin feat/x",
                        "gh pr create --draft --title t --body b", "gh pr create -d --fill",
                        "git push -u origin feat/x 2>&1", "git push origin feat/x > /tmp/push.txt 2>&1",
                        "cd . && git push -u origin feat/x 2>&1 | tail -3"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 0)

    def test_other_pushes_and_pr_changes_block(self):
        for command in ["git push", "git push origin", "git push origin main", "git push origin feat/x:main",
                        "git push origin feat/x:main 2>&1", "git push origin 2>&1 feat/x:main",
                        "git push origin HEAD:main", "git push upstream feat/x", "git push origin other",
                        "git push -f origin feat/x", "git push --force-with-lease origin feat/x", "git push -uf origin feat/x",
                        "git push origin +feat/x", "git push origin :feat/x", "git push --tags origin feat/x",
                        "git push --follow-tags origin feat/x", "git push --delete origin feat/x", "git push --mirror origin",
                        "git push --all origin", "gh pr create --fill", "gh pr ready 1", "gh pr merge 1",
                        "python3 ~/.claude/skills/agent-coordination/scripts/delegate.py start --approved-log t/log.md --targets prod",
                        "bash -c 'delegate.py start --approved-log=t/log.md'",
                        "git -c remote.origin.push=refs/heads/feat/x:refs/heads/main push origin feat/x",
                        "git -c alias.p=push p origin HEAD:main", "GIT_CONFIG_PARAMETERS=\"'alias.p=push'\" git p origin HEAD:main",
                        "export GIT_CONFIG_COUNT=1; git status", "git -c url.x.insteadOf=y push origin feat/x",
                        "git --config-env=alias.p=V p origin HEAD:main", "python3 delegate.py start --approved x --targets p",
                        "echo '[alias] p = push' >> ~/.gitconfig"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), 2)
        self.assertEqual(self.bash("python3 delegate.py start --prompt-file b.md --cwd ."), 0)

    def test_protected_and_detached_branches_block(self):
        for branch in ("stable", "main"):
            self.git("checkout", "-q", "-B", branch)
            with self.subTest(branch=branch):
                self.assertEqual(self.bash(f"git push -u origin {branch}"), 2)
        self.git("checkout", "-q", "--detach")
        self.assertEqual(self.bash("git push origin HEAD"), 2)
        self.git("checkout", "-q", "feat/x")
        self.git("config", "remote.origin.push", "refs/heads/feat/x:refs/heads/main")
        self.assertEqual(self.bash("git push origin feat/x"), 2)

    def test_a_live_grant_reaches_only_its_base_commands_and_hosts(self):
        for command in ["git push origin HEAD:main", "git push origin abc1234:main", "npm run deploy:prod",
                        "git push origin abc1234:main 2>&1", "git push origin HEAD:main 2>/dev/null",
                        "aws lambda update-function-code --function-name f --zip-file fileb://f.zip",
                        "ssh ubuntu@203.0.113.7 uptime", "ssh -i /tmp/deploy_key -o StrictHostKeyChecking=yes ubuntu@203.0.113.7 ls",
                        "scp dist.tgz ubuntu@203.0.113.7:/tmp/", "git push -u origin feat/x"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command, self.grant), 0)
        self.grant["commands"].append("git push origin HEAD:main")  # git is never granted by prefix
        for command in ["git push --force origin HEAD:main", "git push origin HEAD:release", "git push origin +HEAD:main",
                        "git push origin HEAD:main --force", "git push origin HEAD:main HEAD:release",
                        "git push origin HEAD:main 2>&1 --force", "git push origin HEAD:release > /tmp/o 2>&1",
                        "ssh root@203.0.113.7 uptime", "ssh ubuntu@198.51.100.1", "scp x ubuntu@198.51.100.1:/tmp",
                        "npm run deploy:staging", "aws ec2 terminate-instances --instance-ids i-1", "psql -c 'select 1'",
                        "cat .env", "npm run deploy:prod > ~/.claude/settings.json", "gh pr merge 1"]:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command, self.grant), 2)

    def test_expired_foreign_or_malformed_grants_are_no_grant(self):
        expired = self.grant | {"expires": "2020-01-01T00:00Z"}
        foreign = self.grant | {"repo": "acme/other"}
        for grant in (expired, foreign, "not json", {"repo": "acme/widgets"}):
            with self.subTest(grant=grant):
                self.assertEqual(self.bash("git push origin HEAD:main", grant), 2)
                self.assertEqual(self.bash("npm run deploy:prod", grant), 2)
                self.assertEqual(self.bash("git status", grant), 0)


if __name__ == "__main__":
    unittest.main()
