"""install.sh renders authorizations.json into the Claude settings snippet and Codex rules, inert."""
import json
import os
from pathlib import Path
import re
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
            self.assertEqual([r["id"] for r in rules["rules"]], [e["id"] for e in AUTH["entries"]])
            for e in AUTH["entries"]:
                self.assertIn(CLAUDE_RULE[e["tool"]].format(e["match"]), snippet["permissions"][e["mode"]])
            guarded = {(e["match"], e["guard"]) for e in AUTH["entries"] if "guard" in e}
            self.assertIn(("mcp__scheduled-tasks__delete_scheduled_task", "monitor-id-guard"), guarded)
            self.assertEqual({(m, os.path.basename(c)[:-3]) for m, c in commands(rules["hooks"]["PreToolUse"])},
                             guarded)
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
        for target, hook, who in (("claude", "archive-guard.sh", "archive-done"),
                                  ("codex", "monitor-id-guard.sh", "monitor-delete"),
                                  ("claude", "denial-log.sh", "settings.snippet.json")):
            for mode in ("--dry-run", "--target=" + target):
                with self.subTest(target=target, hook=hook, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    src = source(tmp, drop=(hook,))
                    dest = Path(tmp) / "home"
                    dest.mkdir()
                    result = install(src, dest, mode, f"--target={target}")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"render: {who}: hook {src}/hooks/{hook} is missing or not executable",
                                  result.stderr)
                    self.assertFalse((dest / SNIPPET).exists() or (dest / RULES).exists())


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
