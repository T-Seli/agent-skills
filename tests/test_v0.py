import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from agent_skills import Catalog, make_handoff, propose_change, review_change
from agent_skills.core import evaluate_selection

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "agent_skills/examples/project.json"
PROFILE = "agent_skills/examples/profile.json"


class V0Tests(unittest.TestCase):
    def test_light_index_select_and_load_only_relevant_sources(self):
        catalog = Catalog(ROOT, profile=PROFILE)
        index = catalog.index("worker")
        self.assertTrue(all(set(x) == {"id", "layer", "summary", "proposed_export_name"} for x in index))
        self.assertEqual(len({x["proposed_export_name"] for x in index}), len(index))
        selected = catalog.select("review change before release", role="worker", complexity="small")
        self.assertEqual((selected["skill_id"], selected["model_tier_hint"]), ("company.test-review", "fast"))
        self.assertEqual(selected["profile_scope"], "team")
        loaded = catalog.load(selected["skill_id"], role="worker")
        self.assertEqual([x["path"] for x in loaded["sources"]],
                         ["skills/test-review/SKILL.md", "skills/workflow-contracts/contracts.md",
                          "skills/workflow-contracts/behavior.md", "skills/workflow-contracts/decisions.md",
                          "skills/workflow-contracts/references/research.md",
                          "skills/workflow-contracts/references/execution-proof.md"])
        self.assertTrue(catalog.fresh(loaded))
        self.assertIn("core:skills/test-review/SKILL.md", loaded["package_hashes"])
        self.assertTrue(all("content" not in x for x in catalog.index()))
        composed = catalog.compose(["company.blueprint", "company.test-review"], role="worker")
        self.assertEqual(len(composed["sources"]), 7)  # two bodies, three contracts, two shared references
        with self.assertRaises(ValueError):
            catalog.compose(["company.handoff"] * 4, role="worker")
        self.assertEqual(catalog.select("preview change", role="worker")["decision"], "no-match")
        with self.assertRaises(ValueError):
            catalog.load("company.test-review", role="dot")

    def test_behavior_contract_travels_with_bundles_and_invalidates_stale_evidence(self):
        path = "skills/workflow-contracts/behavior.md"
        for skill in ("company.agent-coordination", "company.blueprint", "company.test-review", "company.handoff"):
            with self.subTest(skill=skill):
                loaded = Catalog(ROOT).load(skill, role="worker")
                self.assertIn(path, [x["path"] for x in loaded["sources"]])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            catalog = Catalog(root)
            bundle = catalog.load("company.handoff", role="worker")
            self.assertTrue(catalog.fresh(bundle))
            with (root / path).open('a') as f:
                f.write('\nSynthetic changed completion criterion.\n')
            self.assertFalse(catalog.fresh(bundle))
            with self.assertRaisesRegex(ValueError, 'freshness'):
                make_handoff(catalog, bundle, work_item='synthetic-revision', target_role='dot',
                             next_step='Read the current criterion')
            current = catalog.compose(["company.blueprint", "company.test-review", "company.handoff"], role="worker")
            self.assertEqual(sum(x["path"] == path for x in current["sources"]), 1)

    def test_decision_contract_change_invalidates_worker_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            catalog = Catalog(root)
            for role in ('worker', 'dot'):
                self.assertEqual(catalog.select('grill me', role=role)['skill_id'], 'company.grill-me')
            bundle = catalog.load('company.grill-me', role='worker')
            path = root / 'skills/workflow-contracts/decisions.md'
            self.assertIn('skills/workflow-contracts/decisions.md', [x['path'] for x in bundle['sources']])
            path.write_text(path.read_text() + '\nChanged decision prerequisite.\n')
            self.assertFalse(catalog.fresh(bundle))
            with self.assertRaisesRegex(ValueError, 'freshness'):
                make_handoff(catalog, bundle, work_item='synthetic-decision', target_role='dot',
                             next_step='Reconcile changed prerequisite')

    def test_project_binding_and_model_alias(self):
        catalog = Catalog(ROOT, project=PROJECT, profile=PROFILE)
        selected = catalog.select("check project setup", role="worker", complexity="large")
        self.assertEqual(selected["skill_id"], "project.example-check")
        self.assertEqual(selected["model_tier_hint"], "deep")
        self.assertEqual(catalog.load(selected["skill_id"], role="worker")["sources"][1]["path"], "CLAUDE.md")
        personal = Catalog(ROOT, profile="agent_skills/examples/personal-profile.json")
        self.assertEqual(personal.select("handoff task", role="dot")["profile_scope"], "personal")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "profile.json").write_text((ROOT / "agent_skills/examples/personal-profile.json").read_text())
            private = Catalog(ROOT, profile_root=tmp, profile="profile.json")
            self.assertEqual(private.select("handoff task", role="dot")["profile_scope"], "personal")

    def test_handoff_is_metadata_and_no_approval(self):
        catalog = Catalog(ROOT)
        bundle = catalog.load("company.handoff", role="worker")
        handoff = make_handoff(catalog, bundle, work_item="review-1", target_role="dot",
                               next_step="Review evidence", evidence_refs=["tests/test_v0.py"])
        self.assertEqual((handoff["delivery"], handoff["human_decision"]),
                         ("not sent", "not supplied by this handoff"))
        self.assertNotIn("content", json.dumps(handoff))
        self.assertEqual(set(handoff["source_hashes"]),
                         {x["origin"] + ":" + x["path"] for x in bundle["sources"]})
        forged = dict(bundle, sources=bundle["sources"][:1])
        self.assertFalse(catalog.fresh(forged))
        with self.assertRaises(ValueError):
            make_handoff(catalog, forged, work_item="review-1", target_role="dot", next_step="Review")

    def test_task_history_pilot_catalog_loads_complete_package(self):
        catalog = Catalog(ROOT)
        bundle = catalog.load("company.task-history", role="worker")
        paths = {source["path"] for source in bundle["sources"]}
        self.assertIn("skills/task-history/SKILL.md", paths)
        self.assertIn("core:skills/task-history/SKILL.md", bundle["package_hashes"])
        self.assertTrue(catalog.fresh(bundle))

    def test_stale_hash_and_path_escape_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = json.loads((ROOT / "agent_skills/catalog.json").read_text())
            paths = {"agent_skills/catalog.json"}
            for entry in source["skills"]:
                paths.update([entry["body"], *entry["requires"]])
            for path in sorted(paths):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, root / path)
            catalog = Catalog(root)
            bundle = catalog.load("company.handoff", role="worker")
            (root / "skills/handoff/references").mkdir()
            (root / "skills/handoff/references/new.md").write_text("new reference")
            self.assertFalse(catalog.fresh(bundle))  # package changed without changing SKILL.md
            (root / "skills/handoff/references/linked").symlink_to(root / "skills/handoff/references", target_is_directory=True)
            with self.assertRaises(ValueError):
                catalog.load("company.handoff", role="worker")
            (root / "skills/handoff/references/linked").unlink()
            bundle = catalog.load("company.handoff", role="worker")
            (root / "skills/handoff/SKILL.md").write_text("changed")
            self.assertFalse(catalog.fresh(bundle))
            with self.assertRaises(ValueError):
                make_handoff(catalog, bundle, work_item="x", target_role="dot", next_step="y")
            source = json.loads((root / "agent_skills/catalog.json").read_text())
            source["skills"][0]["body"] = "../outside.md"
            (root / "agent_skills/catalog.json").write_text(json.dumps(source))
            with self.assertRaises(ValueError):
                Catalog(root)
            source["skills"][0]["body"] = "skills/skill-steward/SKILL.md"
            (root / "agent_skills/catalog.json").write_text(json.dumps(source).replace('"version": 1', '"version": 1, "version": 1', 1))
            with self.assertRaises(ValueError):
                Catalog(root)

    def test_external_project_binding_stays_inside_its_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".agent-skills").mkdir()
            (project / "skills").mkdir()
            (project / "CLAUDE.md").write_text("# Example local facts\n")
            (project / "README.md").write_text("Local evidence\n")
            (project / "skills/check.md").write_text("# Project-local check\n")
            binding = {"version": 1, "id": "local", "facts": "CLAUDE.md", "skills": [{
                "id": "project.local-check", "layer": "project", "summary": "Check this project",
                "phrases": ["check local project"], "roles": ["worker"],
                "body": "skills/check.md", "requires": ["CLAUDE.md"]}]}
            (project / ".agent-skills/project.json").write_text(json.dumps(binding))
            catalog = Catalog(ROOT, project_root=project, project=".agent-skills/project.json")
            bundle = catalog.load("project.local-check", role="worker")
            self.assertEqual([x["origin"] for x in bundle["sources"]], ["project", "project"])
            handoff = make_handoff(catalog, bundle, work_item="local", target_role="dot",
                                   next_step="Review the result", evidence_refs=["project:README.md"])
            self.assertNotIn(tmp, json.dumps(handoff))
            self.assertEqual(handoff["evidence_refs"], ["project:README.md"])
            (project / "eval.json").write_text(json.dumps({"version": 1, "cases": [{
                "name": "project check", "task": "check local project", "role": "worker",
                "expected": "project.local-check"}]}))
            proposal = propose_change(catalog, bundle, observation="Local check needs clearer output",
                                      expected="Report the project evidence", evidence_refs=["project:README.md"],
                                      fixture="project:eval.json")
            evaluation = evaluate_selection(catalog, proposal["fixture"])
            self.assertEqual((evaluation["passed"], evaluation["total"]), (1, 1))
            self.assertEqual(review_change(catalog, proposal,
                                           evaluation_passed=evaluation["passed"] == evaluation["total"])["decision"],
                             "human-review-needed")
            binding["skills"][0]["body"] = "../outside.md"
            (project / ".agent-skills/project.json").write_text(json.dumps(binding))
            with self.assertRaises(ValueError):
                Catalog(ROOT, project_root=project, project=".agent-skills/project.json")
            (project / ".env").write_text("do-not-load")
            binding["skills"][0]["body"] = ".env"
            (project / ".agent-skills/project.json").write_text(json.dumps(binding))
            with self.assertRaises(ValueError):
                Catalog(ROOT, project_root=project, project=".agent-skills/project.json")
            (project / "skills/link.md").symlink_to(project / "skills/check.md")
            binding["skills"][0]["body"] = "skills/link.md"
            (project / ".agent-skills/project.json").write_text(json.dumps(binding))
            with self.assertRaises(ValueError):
                Catalog(ROOT, project_root=project, project=".agent-skills/project.json")

    def test_proposal_requires_evidence_and_never_promotes(self):
        catalog = Catalog(ROOT)
        bundle = catalog.load("meta.skill-steward", role="dot")
        proposal = propose_change(catalog, bundle, observation="Selector missed a known task",
                                  expected="Select the correct skill", evidence_refs=["tests/test_v0.py"],
                                  fixture="agent_skills/evaluations/selection.json")
        self.assertEqual(proposal["state"], "proposed")
        self.assertEqual(review_change(catalog, proposal, evaluation_passed=False)["decision"], "blocked")
        self.assertEqual(review_change(catalog, proposal, evaluation_passed=True)["decision"],
                         "human-review-needed")
        proposal["observation"] = "different claim"
        self.assertEqual(review_change(catalog, proposal, evaluation_passed=True)["reason"],
                         "proposal changed after pinning")

    def test_cli_evaluation_and_handoff(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(["python3", "-m", "agent_skills", "evaluate"], cwd=ROOT, env=env,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["passed"], 5)
        result = subprocess.run(["python3", "-m", "agent_skills", "handoff", "company.handoff",
                                 "--role", "worker", "--to", "dot", "--work-item", "local-1",
                                 "--next-step", "Review the result", "--evidence", "tests/test_v0.py"],
                                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["delivery"], "not sent")
        proposal = subprocess.run(["python3", "-m", "agent_skills", "propose", "meta.skill-steward",
                                   "--role", "dot", "--observation", "A task was misrouted",
                                   "--expected", "Select the matching skill",
                                   "--fixture", "agent_skills/evaluations/selection.json",
                                   "--evidence", "tests/test_v0.py"], cwd=ROOT, env=env,
                                  capture_output=True, text=True, check=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposal.json"
            path.write_text(proposal.stdout)
            reviewed = subprocess.run(["python3", "-m", "agent_skills", "review-proposal", str(path)],
                                      cwd=ROOT, env=env, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(reviewed.stdout)["review"]["decision"], "human-review-needed")

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "optional schema validator unavailable")
    def test_contract_schema_matches_examples(self):
        import jsonschema
        schema = json.loads((ROOT / "agent_skills/schemas/v0.schema.json").read_text())
        for kind, path in (("catalog", "agent_skills/catalog.json"),
                           ("project", PROJECT), ("profile", PROFILE),
                           ("profile", "agent_skills/examples/personal-profile.json")):
            jsonschema.validate(json.loads((ROOT / path).read_text()),
                                {**schema, "$ref": f"#/$defs/{kind}"})


if __name__ == "__main__":
    unittest.main()
