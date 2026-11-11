"""Offline routing, delivered context and evidence invalidation; not visual/LLM proof."""
import shutil
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_skills import Catalog
from agent_skills.github_migration import policy_identity

ROOT = Path(__file__).resolve().parents[1]
UI = "company.ui-design"
RESOURCES = {"skills/ui-design/SKILL.md", "skills/ui-design/references/design.md",
             "skills/ui-design/references/visualization.md", "skills/ui-design/references/iteration.md",
             "skills/workflow-contracts/references/research.md"}


class UIDesignPackets(unittest.TestCase):
    def test_shared_chain_routes_ui_as_a_phase_supplement_and_documents_component(self):
        contracts = (ROOT/"skills/workflow-contracts/contracts.md").read_text()
        chain = contracts.split("## Chain", 1)[1].split("## Consent", 1)[0]
        routing = next(line for line in chain.splitlines() if line.startswith("- Routing,"))
        self.assertIn("**ui-design**", routing)
        for boundary in ("UI/frontend/local-prototype", "supplement", "blueprint", "implement", "test-review",
                         "phase authority", "design choice", "consent", "references/execution-proof.md"):
            self.assertIn(boundary, routing)
        components = (ROOT/"README.md").read_text().split("## Components", 1)[1].split("## How stages connect", 1)[0]
        row = next(line for line in components.splitlines() if "`skills/ui-design`" in line)
        self.assertIn("supplement", row)
        self.assertIn("body on invoke", row)

    def test_specific_design_requests_select_ui_without_claiming_general_backend_work(self):
        catalog = Catalog(ROOT)
        for role in ("dot", "worker"):
            for task in ("ui design for a member settings flow", "frontend design options",
                         "visualization design for an uncertain time series", "local ui prototype"):
                with self.subTest(role=role, task=task):
                    self.assertEqual(catalog.select(task, role=role).get("skill_id"), UI)
        self.assertEqual(catalog.select("investigate bug in a database retry", role="worker")["skill_id"], "company.blueprint")
        self.assertEqual(catalog.select("rotate a database index", role="worker")["decision"], "no-match")

    def test_actual_ui_load_contains_declared_references_and_shared_boundaries(self):
        for role in ("dot", "worker"):
            bundle = Catalog(ROOT).load(UI, role=role)
            paths = {s["path"] for s in bundle["sources"]}
            self.assertTrue(RESOURCES <= paths)
            self.assertIn("skills/workflow-contracts/contracts.md", paths)
            self.assertTrue(Catalog(ROOT).fresh(bundle))

    def test_phase_composition_delivers_ui_and_research_once_without_unrelated_ui_context(self):
        catalog = Catalog(ROOT)
        for phase in ("company.blueprint", "company.implement", "company.test-review"):
            with self.subTest(phase=phase):
                ordinary = catalog.load(phase, role="worker")
                self.assertFalse(RESOURCES - {"skills/workflow-contracts/references/research.md"} & {s["path"] for s in ordinary["sources"]})
                self.assertIn("skills/workflow-contracts/references/research.md", {s["path"] for s in ordinary["sources"]})
                packet = catalog.compose([phase, UI], role="worker")
                paths = [s["path"] for s in packet["sources"]]
                self.assertIn("skills/" + phase.split(".", 1)[1] + "/SKILL.md", paths)
                self.assertTrue(RESOURCES <= set(paths))
                self.assertEqual(len(paths), len(set(paths)))

    def test_changed_shared_reference_invalidates_loaded_ui_receipt_and_review_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"source"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            for resource in sorted(RESOURCES):
                with self.subTest(resource=resource):
                    catalog = Catalog(root); bundle = catalog.load(UI, role="worker")
                    before = policy_identity(root)[0]
                    path = root/resource; original = path.read_text()
                    path.write_text(original + "\nChanged synthetic design acceptance.\n")
                    self.assertFalse(catalog.fresh(bundle))
                    self.assertNotEqual(policy_identity(root)[0], before)
                    path.write_text(original)

    def test_real_offline_cli_compose_delivers_iteration_context(self):
        run = subprocess.run([sys.executable, "-B", "-m", "agent_skills", "compose",
                              "--role", "worker", "company.implement", UI], cwd=ROOT,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        packet = json.loads(run.stdout)
        self.assertTrue(RESOURCES <= {s["path"] for s in packet["sources"]})
        self.assertIn("core:skills/ui-design/references/iteration.md", packet["package_hashes"])
        self.assertFalse(any("ui-design" in s["path"] for s in Catalog(ROOT).load("company.handoff", role="worker")["sources"]))

    def test_planning_authorization_regressions_use_real_composed_context(self):
        from agent_skills.evaluation_contract import validate_case
        cases = json.loads((ROOT/"agent_skills/evaluations/ui-planning-authorization.json").read_text())["cases"]
        self.assertEqual({c["id"] for c in cases},
                         {"ui-authorized-read-only-planning", "ui-no-worker-or-browser-planning",
                          "ui-blocked-recovery-short-plan"})
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(validate_case(case))
                bundle = Catalog(ROOT).compose(case["required_skills"], role="worker")
                by_path = {s["path"]: s for s in bundle["sources"]}
                for path in ("skills/blueprint/SKILL.md", "skills/ui-design/references/iteration.md",
                             "skills/workflow-contracts/contracts.md"):
                    self.assertEqual(by_path[path]["content"], (ROOT/path).read_text())
        # This checks valid reusable cases and actual delivered context.
        # Source consistency/authorization decisions need the semantic trial receipts.
