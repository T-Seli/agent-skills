"""The handoff paste check: blocks that a command would reject are caught before the user pastes them."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / "skills" / "handoff" / "scripts" / "check_block.py"


def run(text):
    p = subprocess.run([sys.executable, str(CHECK)], input=text, capture_output=True, text=True)
    return p.returncode, p.stdout


class HandoffPasteCheckTests(unittest.TestCase):
    def test_words_a_command_rejects_are_reported(self):
        for text, expect in [
                ("First: read .claude/drafts/x/log.md now.", "log.md"),
                ('Next: "python3 ~/.claude/skills/a/scripts/delegate.py report"', "delegate.py"),
                ("Config lives in release.repos of the workers file.", "release.repos"),
                ("Start with --approved-log <log> --targets <t>.", "angle bracket"),
                ("See https://example.com/x", "link"), ("Run /deploy next.", "slash command"),
                ("Ask @buffington first.", "not a file @-mention"), ("Use `code` here.", "backtick"),
                ("This is **bold**.", "bold"), ("# Heading", "heading"), ("an _emphasis_ word", "emphasis")]:
            with self.subTest(text=text):
                code, out = run(text)
                self.assertEqual(code, 1)
                self.assertIn(expect, out)

    def test_plain_text_and_existing_file_mentions_pass(self):
        with tempfile.NamedTemporaryFile(suffix=".md") as f:
            text = (f"Continue the work. First: read @{f.name} and the guard folder.\n"
                    "- Done + verified: 494 tests, 6 known errors; ccm_backend and Signal7-Voice targets saved (user)\n"
                    'Next: run "git status" in ~/Developer/agent-skills-canonical; e.g. at 10-24 05:00Z, 16/16 links.')
            self.assertEqual(run(text), (0, "ok\n"))

    def test_missing_file_mentions_and_the_cap_are_reported(self):
        self.assertIn("names no existing file", run("Read @/no/such/file.md first.")[1])
        self.assertIn("lines; the cap", run("x\n" * 41)[1])
        self.assertIn("words; the cap", run("word " * 451)[1])


if __name__ == "__main__":
    unittest.main()
