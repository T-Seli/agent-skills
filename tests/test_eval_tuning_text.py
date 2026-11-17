"""behavior.md keeps the eval-tuning rules after Agent prompts."""
import pathlib
import unittest

BODY = (pathlib.Path(__file__).resolve().parent.parent / "skills/workflow-contracts/behavior.md").read_text()


class EvalTuningTextTests(unittest.TestCase):
    def test_section_order_and_markers(self):
        a, b, c = (BODY.index(h) for h in ("## Agent prompts", "## Tune prompts with evals", "## Release train"))
        self.assertLess(a, b)
        self.assertLess(b, c)
        for marker in ("a frozen holdout is read once", "Revert if only train improves",
                       "never paste transcript text", "A user-approved dollar cap",
                       "never reused as a tuning set"):
            with self.subTest(marker=marker):
                self.assertIn(marker, BODY)


if __name__ == "__main__":
    unittest.main()
