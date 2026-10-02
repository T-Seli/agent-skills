import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from agent_skills import Catalog, propose_change, review_change

ROOT = Path(__file__).resolve().parents[1]


class ReviewBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "skills", self.root / "skills")
        (self.root / "agent_skills/evaluations").mkdir(parents=True)
        shutil.copyfile(ROOT / "agent_skills/catalog.json", self.root / "agent_skills/catalog.json")
        shutil.copyfile(ROOT / "agent_skills/evaluations/selection.json",
                        self.root / "agent_skills/evaluations/selection.json")
        (self.root / "evidence.md").write_text("observed miss")
        self.catalog = Catalog(self.root)
        bundle = self.catalog.load("meta.skill-steward", role="dot")
        self.proposal = propose_change(self.catalog, bundle, observation="missed case",
                                       expected="select steward", evidence_refs=["evidence.md"],
                                       fixture="agent_skills/evaluations/selection.json")

    def review(self, proposal=None):
        return review_change(self.catalog, proposal or self.proposal, evaluation_passed=True)

    def test_every_proposal_field_is_pinned(self):
        self.assertEqual(self.review()["decision"], "human-review-needed")
        for key, altered in (("observation", "changed"), ("expected", "changed"),
                             ("evidence_refs", []), ("fixture", "evidence.md"),
                             ("source_hashes", {}), ("package_hashes", {}),
                             ("reference_hashes", {}), ("role", "worker")):
            with self.subTest(key=key):
                changed = {**self.proposal, key: altered}
                self.assertEqual(self.review(changed)["reason"], "proposal changed after pinning")

    def test_changed_evidence_fixture_dependency_and_package_resource_are_blocked(self):
        changes = (("evidence.md", "new evidence", "review reference changed"),
                   ("agent_skills/evaluations/selection.json", '{}', "review reference changed"),
                   ("skills/workflow-contracts/contracts.md", "new dependency", "source bundle changed"),
                   ("skills/skill-steward/SKILL.md", None, "source bundle changed"))
        for path, content, reason in changes:
            with self.subTest(path=path):
                file = self.root / path
                original = file.read_text()
                file.write_text(content if content is not None else original + "\nChanged body.\n")
                try:
                    self.assertEqual(self.review()["reason"], reason)
                finally:
                    file.write_text(original)
        resource = self.root / "skills/skill-steward/references/new.md"
        resource.parent.mkdir(exist_ok=True)
        resource.write_text("new resource")
        self.assertEqual(self.review()["reason"], "source bundle changed")

    def test_cli_reports_stale_fixture_before_parsing_it(self):
        proposal_file = self.root / "proposal.json"
        proposal_file.write_text(json.dumps(self.proposal))
        (self.root / "agent_skills/evaluations/selection.json").write_text("invalid JSON")
        result = subprocess.run([sys.executable, "-m", "agent_skills", "--root", str(self.root),
                                 "review-proposal", str(proposal_file)], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["review"]["reason"], "review reference changed")


if __name__ == "__main__":
    unittest.main()
