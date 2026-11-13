"""Archive needs a recorded grant; release-member PRs stay draft; sweep stays separate from archiving."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKERS = {
    "skills/agent-coordination/references/workspace-and-train.md": (
        "a flag alone is not approval", "Archiving is not task closure",
        "separately from archiving", "the transcript stays recoverable"),
    "skills/workflow-contracts/issues.md": ("except a release-member PR",),
    "skills/test-review/SKILL.md": ("never a release-member PR",),
    "ENGINEERING-COORDINATOR.md": ("a grant the user recorded",),
}


class WorkspaceRulesTextTests(unittest.TestCase):
    def test_markers_present(self):
        for path, markers in MARKERS.items():
            body = (ROOT / path).read_text()
            for marker in markers:
                with self.subTest(path=path, marker=marker):
                    self.assertIn(marker, body)


if __name__ == "__main__":
    unittest.main()
