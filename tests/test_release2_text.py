"""Release 2: collision recipe, Refs until deployed, feedback categories, alert replay, coordinator checkpoints."""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("task_history", ROOT / "skills/task-history/history.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)

MARKERS = {
    "skills/implement/SKILL.md": ("Record `Existing method:`", "gh pr list --state all --search",
                                  "another owner's open PR, branch or claim stops the write"),
    "skills/workflow-contracts/issues.md": ("the PR uses `Refs`, never `Closes`",
                                            "release owner closes the issue after the deploy record"),
    "skills/task-history/SKILL.md": ("cost_min=<n>; user_pastes=<n>; theme=<category>",),
    "skills/monitor/SKILL.md": ("replay the last 7 days of real data", "would-fire count"),
    "ENGINEERING-COORDINATOR.md": ("chat alone is not the queue",
                                   "working, held (reason, owner, next check) or done (archive candidate)"),
}
NEW_CATEGORIES = ("credential_prompt", "approval_relay", "tool_hook", "permission_classifier",
                  "stale_state", "surface_access", "scheduling", "resource")


class Release2Tests(unittest.TestCase):
    def test_markers_present(self):
        for path, markers in MARKERS.items():
            body = (ROOT / path).read_text()
            for marker in markers:
                with self.subTest(path=path, marker=marker):
                    self.assertIn(marker, body)

    def test_new_feedback_categories_are_valid_and_old_ones_stay(self):
        for category in NEW_CATEGORIES + ("scope_drift", "other"):
            with self.subTest(category=category):
                self.assertIn(category, history.FEEDBACK_CATEGORIES)

    def test_unknown_feedback_category_is_still_rejected(self):
        self.assertNotIn("made_up_category", history.FEEDBACK_CATEGORIES)


if __name__ == "__main__":
    unittest.main()
