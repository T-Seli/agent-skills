import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/workflow-contracts/scripts/plain-language-check"
CONFIG = ROOT / "skills/workflow-contracts/plain-language.json"
FIX = ROOT / "tests/fixtures"


def run(*args, stdin=None):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], input=stdin,
                          capture_output=True, text=True)


class PlainLanguageCheck(unittest.TestCase):
    def test_wordy_email_gets_findings_of_every_kind(self):
        r = run(str(FIX / "plain_language_wordy.txt"))
        self.assertEqual(r.returncode, 0)
        for kind in ("long", "passive", "filler"):
            self.assertIn(f": {kind}:", r.stdout)

    def test_plain_rewrite_gets_none(self):
        r = run(str(FIX / "plain_language_plain.txt"))
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_reads_stdin(self):
        r = run(stdin="The file was sent.\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("passive", r.stdout)

    def test_limit_change_in_config_only(self):
        text = "We moved your appointment to a new day because the technician is away.\n"
        self.assertEqual(run(stdin=text).stdout, "")
        cfg = json.loads(CONFIG.read_text())
        cfg["descriptive_max_words"] = 5
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "strict.json"
            p.write_text(json.dumps(cfg))
            r = run("--config", str(p), stdin=text)
        self.assertIn(": long:", r.stdout)
        self.assertEqual(r.returncode, 0)

    def test_filler_list_comes_from_config(self):
        cfg = json.loads(CONFIG.read_text())
        cfg["filler"] = ["soon"]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.json"
            p.write_text(json.dumps(cfg))
            r = run("--config", str(p), stdin="We call you soon.\nWe utilize it.\n")
        self.assertEqual(r.stdout.count("filler"), 1)

    def test_exit_code_always_zero(self):
        junk = "word " * 400 + "\n"
        self.assertEqual(run(stdin=junk).returncode, 0)
        self.assertEqual(run(stdin="").returncode, 0)

    def assert_advisory_failure(self, r):
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_input_file_exits_zero(self):
        self.assert_advisory_failure(run(str(FIX / "no-such-file.txt")))

    def test_missing_config_exits_zero(self):
        self.assert_advisory_failure(run("--config", str(FIX / "no-such.json"), stdin="Hi.\n"))

    def test_malformed_or_incomplete_config_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            bad, partial = Path(d) / "bad.json", Path(d) / "partial.json"
            bad.write_text("{not json")
            partial.write_text("{}")
            self.assert_advisory_failure(run("--config", str(bad), stdin="Hi.\n"))
            self.assert_advisory_failure(run("--config", str(partial), stdin="Hi.\n"))


if __name__ == "__main__":
    unittest.main()
