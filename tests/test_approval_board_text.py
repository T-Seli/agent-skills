"""The reply format and approval board must stay in the coordinator guide and output style."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "ENGINEERING-COORDINATOR.md").read_text()
STYLE = (ROOT / "output-styles/orchestrator.md").read_text()


class ApprovalBoardTextTests(unittest.TestCase):
    def test_guide_keeps_reply_format_and_approval_board(self):
        for marker in ("Two asks, never mixed", "SUPERSEDED, do not paste",
                       "plan in progress", "never a second tracker"):
            with self.subTest(marker=marker):
                self.assertIn(marker, GUIDE)

    def test_output_style_keeps_links_and_order(self):
        for marker in ("Need from you first, real links", "a bare id is not a link",
                       "surfaces only when the user must act or asks", "recommended first"):
            with self.subTest(marker=marker):
                self.assertIn(marker, STYLE)


if __name__ == "__main__":
    unittest.main()
