"""The no-email rule must stay in every place that defines send consent."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKERS = {
    "skills/workflow-contracts/contracts.md": "no session sends, replies to or forwards email",
    "global/CLAUDE.md": "Never send email: write a draft file.",
    "skills/agent-coordination/SKILL.md": "no session sends, replies or forwards email",
    "skills/agent-coordination/references/worker-execution.md": "no email send, reply or forward",
    "ENGINEERING-COORDINATOR.md": "never send, reply or forward",
}


class NoEmailRuleTests(unittest.TestCase):
    def test_rule_is_present_where_send_consent_is_defined(self):
        for path, marker in MARKERS.items():
            with self.subTest(path=path):
                self.assertIn(marker, (ROOT / path).read_text())


if __name__ == "__main__":
    unittest.main()
