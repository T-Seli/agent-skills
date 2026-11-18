"""install.sh renders authorizations.json into the Claude settings snippet and Codex rules, inert."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / "authorizations.json").read_text())
SNIPPET = ".claude/agent-skills/settings.snippet.json"
RULES = ".codex/agent-skills/rules.toml"
CLAUDE_RULE = {"bash": "Bash({}:*)", "mcp": "{}", "edit": "Edit({})"}
CODEX_DECISION = {"allow": "allow", "ask": "prompt", "deny": "forbidden"}
LIVE = [e for e in AUTH["entries"] if "held" not in e]
HELD = [e for e in AUTH["entries"] if "held" in e]
UUID = "{0}{0}{0}{0}{0}{0}{0}{0}-{0}{0}{0}{0}-{0}{0}{0}{0}-{0}{0}{0}{0}-{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}"
ROLE, OTHER = UUID.format("a"), UUID.format("b")


def source(tmp, auth=None, drop=()):
    """A repo root of links to ROOT, with its own hooks/ (minus `drop`) and optionally its own authorizations.json."""
    src = Path(tmp) / "src"
    src.mkdir()
    for p in ROOT.iterdir():
        if p.name not in (".git", "hooks", "authorizations.json"):
            (src / p.name).symlink_to(p)
    (src / "hooks").mkdir()
    for h in ROOT.glob("hooks/*.sh"):
        if h.name not in drop:
            (src / "hooks" / h.name).symlink_to(h)
    if auth is None:
        (src / "authorizations.json").symlink_to(ROOT / "authorizations.json")
    else:
        (src / "authorizations.json").write_text(json.dumps(auth))
    return src


def install(src, dest, *args):
    return subprocess.run([str(src / "install.sh"), f"--destination-root={dest}", *args],
                          env=dict(os.environ, HOME=str(dest)), capture_output=True, text=True)


def rendered(dest):
    snippet = json.loads((Path(dest) / SNIPPET).read_text())
    rules = tomllib.loads((Path(dest) / RULES).read_text())
    return snippet, rules


def commands(groups):
    return {(g["matcher"], h["command"]) for g in groups for h in g["hooks"]}


class RenderTests(unittest.TestCase):
    def test_each_tool_type_and_mode_renders_for_claude_and_codex(self):
        entries = [{"id": f"{tool}-{mode}", "tool": tool, "mode": mode, "kind": "bookkeeping", "why": "w",
                    "match": {"bash": f"tool-{mode} sub", "mcp": f"mcp__srv__{mode}", "edit": f"~/x/{mode}/**"}[tool]}
                   for tool in CLAUDE_RULE for mode in CODEX_DECISION]
        entries[0]["guard"] = "archive-guard"   # bash allow
        entries[3]["guard"] = "monitor-id-guard"  # mcp allow
        with tempfile.TemporaryDirectory() as tmp:
            src = source(tmp, {"version": 9, "entries": entries})
            dest = Path(tmp) / "home"
            dest.mkdir()
            result = install(src, dest)
            self.assertEqual(result.returncode, 0, result.stderr)
            snippet, rules = rendered(dest)
            by_id = {r["id"]: r for r in rules["rules"]}
            self.assertEqual(rules["version"], 9)
            for e in entries:
                with self.subTest(tool=e["tool"], mode=e["mode"]):
                    self.assertIn(CLAUDE_RULE[e["tool"]].format(e["match"]), snippet["permissions"][e["mode"]])
                    r = by_id[e["id"]]
                    self.assertEqual((r["tool"], r["match"], r["decision"]),
                                     (e["tool"], e["match"], CODEX_DECISION[e["mode"]]))
                    self.assertEqual(r.get("pattern"), e["match"].split() if e["tool"] == "bash" else None)
                    self.assertEqual(r.get("guard"), e.get("guard"))
            self.assertIn("Read(~/.claude/skills/workflow-contracts/**)", snippet["permissions"]["allow"])
            claude_hooks = commands(snippet["hooks"]["PreToolUse"])
            codex_hooks = commands(rules["hooks"]["PreToolUse"])
            for matcher, guard in (("Bash", "archive-guard"), ("mcp__srv__allow", "monitor-id-guard")):
                self.assertIn((matcher, f"~/.claude/hooks/{guard}.sh"), claude_hooks)
                self.assertIn((matcher, f"{src}/hooks/{guard}.sh"), codex_hooks)
            self.assertIn(("Bash", "~/.claude/hooks/test-gate.sh"), claude_hooks)
            self.assertEqual(len(codex_hooks), 2)

    def test_every_real_entry_reaches_codex_and_claude_with_hook_parity(self):
        with tempfile.TemporaryDirectory() as dest:
            result = install(ROOT, dest)
            self.assertEqual(result.returncode, 0, result.stderr)
            snippet, rules = rendered(dest)
            self.assertEqual([r["id"] for r in rules["rules"]], [e["id"] for e in LIVE])
            for e in LIVE:
                self.assertIn(CLAUDE_RULE[e["tool"]].format(e["match"]), snippet["permissions"][e["mode"]])
            guarded = {(e["match"], e["guard"]) for e in LIVE if "guard" in e}
            codex_hooks = commands(rules.get("hooks", {}).get("PreToolUse", []))
            self.assertEqual({(m, os.path.basename(c)[:-3]) for m, c in codex_hooks}, guarded)
            self.assertTrue(guarded <= {(m, os.path.basename(c)[:-3])
                                        for m, c in commands(snippet["hooks"]["PreToolUse"])})
            self.assertEqual(commands(snippet["hooks"]["PermissionDenied"]),
                             {("*", "~/.claude/hooks/denial-log.sh")})
            for live in (".claude/settings.json", ".codex/hooks.json", ".codex/config.toml"):
                self.assertFalse((Path(dest) / live).exists(), live)
            again = install(ROOT, dest)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn(f"keep {dest}/{SNIPPET} (content already current)", again.stdout)
            self.assertIn(f"keep {dest}/{RULES} (content already current)", again.stdout)

    def test_dry_run_lists_both_rendered_files_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as dest:
            result = install(ROOT, dest, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"render {dest}/{SNIPPET} from: {ROOT}/authorizations.json", result.stdout)
            self.assertIn(f"render {dest}/{RULES} from: {ROOT}/authorizations.json", result.stdout)
            self.assertEqual(list(Path(dest).iterdir()), [])

    def test_a_missing_hook_fails_the_render_loudly(self):
        guarded = {"version": 2, "entries": [
            {"id": "archive-x", "tool": "mcp", "match": "mcp__a__archive", "kind": "bookkeeping", "mode": "allow",
             "why": "w", "guard": "archive-guard"},
            {"id": "monitor-x", "tool": "mcp", "match": "mcp__a__monitor", "kind": "bookkeeping", "mode": "allow",
             "why": "w", "guard": "monitor-id-guard"}]}
        for target, hook, who in (("claude", "archive-guard.sh", "archive-x"),
                                  ("codex", "monitor-id-guard.sh", "monitor-x"),
                                  ("claude", "denial-log.sh", "settings.snippet.json")):
            for mode in ("--dry-run", "--target=" + target):
                with self.subTest(target=target, hook=hook, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    src = source(tmp, guarded, drop=(hook,))
                    dest = Path(tmp) / "home"
                    dest.mkdir()
                    result = install(src, dest, mode, f"--target={target}")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"render: {who}: hook {src}/hooks/{hook} is missing or not executable",
                                  result.stderr)
                    self.assertFalse((dest / SNIPPET).exists() or (dest / RULES).exists())

    def test_no_held_entry_is_rendered(self):
        self.assertEqual({e["id"] for e in HELD},
                         {"monitor-arm", "monitor-delete", "archive-done", "no-merge-outside-release"})
        with tempfile.TemporaryDirectory() as dest:
            result = install(ROOT, dest)
            self.assertEqual(result.returncode, 0, result.stderr)
            snippet_text = (Path(dest) / SNIPPET).read_text()
            rules_text = (Path(dest) / RULES).read_text()
            for e in HELD:
                with self.subTest(held=e["id"]):
                    self.assertNotIn(e["match"], snippet_text)
                    self.assertNotIn(e["match"], rules_text)
                    self.assertNotIn(json.dumps(e["id"]), rules_text)
                    if "guard" in e:
                        self.assertNotIn(e["guard"], rules_text)

    def test_issues_cli_resume_renders_like_the_other_bookkeeping_entries(self):
        resume = next(e for e in AUTH["entries"] if e["id"] == "issues-resume")
        self.assertEqual((resume["kind"], resume["mode"]), ("bookkeeping", "allow"))
        with tempfile.TemporaryDirectory() as dest:
            result = install(ROOT, dest)
            self.assertEqual(result.returncode, 0, result.stderr)
            snippet, rules = rendered(dest)
            self.assertIn(f"Bash({AUTH['invocation']['issues-cli']} resume:*)", snippet["permissions"]["allow"])
            rule = next(r for r in rules["rules"] if r["id"] == "issues-resume")
            self.assertEqual((rule["tool"], rule["decision"], rule["pattern"]),
                             ("bash", "allow", [AUTH["invocation"]["issues-cli"], "resume"]))
            self.assertNotIn("guard", rule)


def release(home):
    """A release snapshot of this working tree in scratch `home`: tracked files plus its .release-pin.json."""
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    dest = home / ".local" / "share" / "agent-skills" / "releases" / head[:7]
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True,
                            check=True).stdout
    for name in filter(None, listed.split("\0")):
        if (ROOT / name).exists():
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dest / name)
    (dest / ".release-pin.json").write_text(json.dumps({"source": "o/r", "commit": head, "tree": "t"}))
    return dest, head


class InstalledLayoutTests(unittest.TestCase):
    """An installed release, outside any git checkout, finds its pin and contract through agent_skills.layout."""

    def test_installed_release_prints_the_pin_commit_and_an_existing_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            pkg, head = release(home)
            git_dir = subprocess.run(["git", "-C", str(pkg), "rev-parse", "--git-dir"], capture_output=True)
            self.assertNotEqual(git_dir.returncode, 0, "the scratch HOME must be outside any git checkout")
            result = install(pkg, home)
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = (home / ".agents" / "skills" / "workflow-contracts").resolve().parents[1]
            self.assertEqual(installed, pkg)
            done = subprocess.run(
                ["python3", "-c",
                 'from agent_skills import layout; print(layout.release_id(), layout.contract("conveyor.json"))'],
                cwd=installed, capture_output=True, text=True,
                env=dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(done.returncode, 0, done.stderr)
            commit, path = done.stdout.split()
            self.assertEqual(commit, head)
            self.assertEqual(Path(path), installed / "skills" / "workflow-contracts" / "conveyor.json")
            self.assertTrue(Path(path).is_file())


class CodexSessionStartTests(unittest.TestCase):
    """codex/hooks/session-start.py adds `issues-cli resume` for a session named in workers.json `roles`,
    as hooks/session-start.sh does for Claude (conveyor.json `resume.hooks`). The codex binary never runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.home = base / "home"
        self.cli = self.home / ".agents" / "skills" / "workflow-contracts" / "scripts" / "issues-cli"
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text('#!/bin/sh\n[ "$*" = resume ] || exit 3\necho "Board: in-progress 1/8"\n'
                            'echo "Questions: none"\n')
        self.cli.chmod(0o755)
        self.config = base / "workers.json"
        self.config.write_text(json.dumps({"roles": {"coordinator": ROLE}}))
        self.cwd = base / "repo"
        self.cwd.mkdir()
        subprocess.run(["git", "-C", str(self.cwd), "init", "-q"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, session, cwd=None):
        event = {"hook_event_name": "SessionStart", "session_id": session, "cwd": str(cwd or self.cwd)}
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_HOST_SESSION_ID"}
        env.update(HOME=str(self.home), AGENT_SKILLS_CONFIG=str(self.config), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(["python3", str(ROOT / "codex" / "hooks" / "session-start.py")],
                              input=json.dumps(event), capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        output = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        return output["additionalContext"]

    def test_a_role_session_gets_the_resume_picture_before_the_snapshot(self):
        context = self.run_hook(ROLE)
        self.assertTrue(context.startswith("Board: in-progress 1/8\nQuestions: none\n"), context)
        self.assertIn("Local Git snapshot.", context)

    def test_any_other_session_keeps_only_the_snapshot(self):
        context = self.run_hook(OTHER)
        self.assertNotIn("Board:", context)
        self.assertTrue(context.startswith("Local Git snapshot."), context)

    def test_a_role_session_outside_git_still_gets_the_resume_picture(self):
        outside = Path(self.tmp.name).resolve() / "plain"
        outside.mkdir()
        context = self.run_hook(ROLE, outside)
        self.assertEqual(context, "Board: in-progress 1/8\nQuestions: none")

    def test_a_failed_resume_is_said_loudly(self):
        self.cli.write_text("#!/bin/sh\necho 'gh: offline' >&2\nexit 1\n")
        self.assertIn("issues-cli resume failed (exit 1): gh: offline", self.run_hook(ROLE))


class InvocationTests(unittest.TestCase):
    """A belt command in skill text uses the same invocation that authorizations.json allows."""
    FULL = re.compile(r'"?([^\s"`(]*scripts/(issues-cli|safeguard-cli))"? ([a-z-]+)')

    def covered(self, cli):
        prefix = AUTH["invocation"][cli] + " "
        return {e["match"][len(prefix):].split()[0] for e in AUTH["entries"] if e["match"].startswith(prefix)}

    def mismatches(self, cli):
        sub = self.covered(cli)
        found = []
        for md in sorted(ROOT.glob("skills/**/*.md")):
            for path, name, command in self.FULL.findall(md.read_text()):
                if name == cli and command in sub and path != AUTH["invocation"][cli]:
                    found.append(f"{md.relative_to(ROOT)}: {path} {command}")
        return found

    def test_authorized_bash_entries_start_with_the_invocation(self):
        for e in AUTH["entries"]:
            for cli, path in AUTH["invocation"].items():
                if e["tool"] == "bash" and cli in e["match"]:
                    self.assertTrue(e["match"].startswith(path + " "), e["id"])
        self.assertTrue(self.covered("issues-cli") and self.covered("safeguard-cli"))

    def test_issues_cli_invocations_in_skills_match(self):
        self.assertEqual(self.mismatches("issues-cli"), [])

    # T4 owns the skill text; contracts.md still runs `test-slot` through ${CLAUDE_SKILL_DIR}.
    # Remove this marker when T4 lands: an unexpected success fails the suite.
    @unittest.expectedFailure
    def test_safeguard_cli_invocations_in_skills_match(self):
        self.assertEqual(self.mismatches("safeguard-cli"), [])


if __name__ == "__main__":
    unittest.main()
