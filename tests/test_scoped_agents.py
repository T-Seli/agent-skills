import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("local-scout", "skill-reviewer", "skill-implementer")


class ScopedAgentsTests(unittest.TestCase):
    def test_install_materializes_profiles_and_shared_skills_for_both_clients(self):
        # Filesystem materialization is separate from native runtime discovery.
        with tempfile.TemporaryDirectory() as isolated_home:
            result = subprocess.run(
                [str(ROOT / "install.sh"), f"--destination-root={isolated_home}"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = Path(isolated_home)
            for name in PROFILES:
                claude = installed / ".claude/agents" / (name + ".md")
                codex = installed / ".codex/agents" / (name + ".toml")
                self.assertEqual(claude.resolve(), ROOT / "agents" / (name + ".md"))
                self.assertFalse(codex.is_symlink())
                self.assertEqual(codex.read_bytes(), (ROOT / "codex/agents" / (name + ".toml")).read_bytes())
            for skill in ("implement", "tdd", "test-review"):
                claude = installed / ".claude/skills" / skill / "SKILL.md"
                codex = installed / ".agents/skills" / skill / "SKILL.md"
                self.assertEqual(claude.resolve(), codex.resolve())
                self.assertTrue(codex.is_file())

    def test_claude_profiles_retain_skill_docs_and_background_task_tools(self):
        for name in PROFILES:
            frontmatter = (ROOT / "agents" / (name + ".md")).read_text().split("---")[1]
            fields = dict(line.split(":", 1) for line in frontmatter.strip().splitlines())
            tools = set(fields["tools"].strip().split(", "))
            self.assertTrue({"Read", "Bash", "Skill", "WebFetch", "WebSearch", "TaskStop"} <= tools)
            self.assertFalse(any(tool.startswith("mcp__") for tool in tools))
            self.assertNotIn("skills", fields)  # no eager loading of all skill bodies
            if name == "local-scout":
                self.assertFalse({"Write", "Edit", "NotebookEdit"} & tools)
            if name == "skill-implementer":
                self.assertTrue({"Write", "Edit"} <= tools)

    def test_codex_profiles_do_not_claim_per_agent_permissions_or_mcp_overrides(self):
        for name in PROFILES:
            agent = tomllib.loads((ROOT / "codex/agents" / (name + ".toml")).read_text())
            self.assertEqual(agent["name"], name)
            self.assertTrue(agent["developer_instructions"])
            self.assertEqual(agent["features"], {"apps": False, "plugins": False})
            self.assertFalse({"sandbox_mode", "approval_policy", "mcp_servers", "tools", "model"} & agent.keys())
        scout = tomllib.loads((ROOT / "codex/agents/scout.toml").read_text())
        self.assertNotIn("sandbox_mode", scout)


if __name__ == "__main__":
    unittest.main()
