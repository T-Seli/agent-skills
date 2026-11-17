import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import budget_lint as b  # noqa: E402


def tree(files, caps=None, homes=(), dup=0):
    d = Path(tempfile.mkdtemp())
    for p, t in files.items():
        (d / p).parent.mkdir(parents=True, exist_ok=True)
        (d / p).write_text(t)
    caps = b.measure(d, list(files)) if caps is None else caps
    (d / "skills").mkdir(exist_ok=True)
    (d / "skills/budgets.json").write_text(json.dumps({"duplicate_runs": dup, "files": caps}))
    (d / "skills/homes.json").write_text(json.dumps({"homes": list(homes)}))
    return d


class BudgetLint(unittest.TestCase):
    def joined(self, d, files):
        return " ".join(b.lint(d, list(files)))

    def test_exact_caps_pass(self):
        f = {"skills/a/SKILL.md": "x " * 50}
        self.assertEqual(b.lint(tree(f), list(f)), [])

    def test_growth_and_headroom_fail(self):
        f = {"skills/a/SKILL.md": "x" * 100}
        self.assertIn("> cap 90", self.joined(tree(f, caps={"skills/a/SKILL.md": {"bytes": 90, "long": 0}}), f))
        self.assertIn("--ratchet", self.joined(tree(f, caps={"skills/a/SKILL.md": {"bytes": 200, "long": 0}}), f))

    def test_new_file_needs_entry(self):
        f = {"skills/a/SKILL.md": "x"}
        self.assertIn("no entry", self.joined(tree(f, caps={}), f))

    def test_packed_line_fails(self):
        f = {"skills/a/SKILL.md": "word " * 200}
        self.assertIn("over 600", self.joined(tree(f, caps={"skills/a/SKILL.md": {"bytes": 1000, "long": 0}}), f))

    def test_single_home(self):
        f = {"skills/a/SKILL.md": "Rule ALPHA here", "skills/b/SKILL.md": "Rule ALPHA again"}
        home = {"id": "alpha", "pattern": "ALPHA", "home": "skills/a/SKILL.md"}
        self.assertIn("belongs only in", self.joined(tree(f, homes=[home]), f))
        ok = dict(home, also=["skills/b/SKILL.md"])
        self.assertEqual(b.lint(tree(f, homes=[ok]), list(f)), [])
        gone = {"skills/a/SKILL.md": "Rule ALPHA", "skills/b/SKILL.md": "clean"}
        self.assertIn("no longer appears", self.joined(tree(gone, homes=[ok]), gone))

    def test_duplicate_runs(self):
        run = " ".join(f"w{i}" for i in range(14))
        f = {"skills/a/SKILL.md": run, "skills/b/SKILL.md": run}
        self.assertIn("duplicate", self.joined(tree(f), f))

    def test_repo_passes(self):
        root = Path(__file__).resolve().parent.parent
        tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
        self.assertEqual(b.lint(root, tracked), [])


if __name__ == "__main__":
    unittest.main()
