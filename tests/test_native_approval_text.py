"""Approvals are native questions in the worker's own session; paste lines are a fallback only."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKERS = {
    "skills/workflow-contracts/decisions.md": (
        "asked by the executing worker as a native question in its own session",
        "The answer binds the whole tuple",
        "the worker runs the guarded command itself",
        "only when the host cannot ask the question", "a question, worker text or relay alone is not approval",
        "never above the host's own limit"),
    "ENGINEERING-COORDINATOR.md": (
        "a generic refusal does not qualify",),
    "skills/agent-coordination/references/workspace-and-train.md": (
        "the existing execution owner trial-merges", "its unarchive route works; otherwise do not archive"),
    "output-styles/orchestrator.md": ("never cutting approval terms or a material blocker",
                                      "the user answers every pending one in one pass",
                                      "is always reported", "a fallback, shown once"),
}


class NativeApprovalTextTests(unittest.TestCase):
    def test_markers_present(self):
        for path, markers in MARKERS.items():
            body = (ROOT / path).read_text()
            for marker in markers:
                with self.subTest(path=path, marker=marker):
                    self.assertIn(marker, body)


if __name__ == "__main__":
    unittest.main()
