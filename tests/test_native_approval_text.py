"""Approvals are native questions in the worker's own session; paste lines are a fallback only."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKERS = {
    "skills/workflow-contracts/decisions.md": (
        "asked by the executing worker as a native question in its own session",
        "The answer authorizes only that hash; any change voids it",
        "the worker runs the guarded command itself",
        "only when the host cannot ask the question"),
    "ENGINEERING-COORDINATOR.md": (
        "the user answers every pending question in one pass",
        "A paste-ready line is a fallback only"),
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
