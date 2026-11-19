"""T4: stage skills and contract text wired to the belt's gate commands (conveyor.md)."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'skills/agent-coordination/scripts'))
import review_gate as g  # noqa: E402

WC = ROOT / 'skills/workflow-contracts'
ICLI = '~/.agents/skills/workflow-contracts/scripts/issues-cli'


def text(path): return (ROOT / path).read_text(encoding='utf-8')


def section(body, name):
    """The section whose heading starts with name, up to the next heading."""
    return re.split(rf'\n## {re.escape(name)}\b[^\n]*\n', body, maxsplit=1)[1].split('\n## ', 1)[0]


class StageLaneCommands(unittest.TestCase):
    def test_each_stage_names_its_lane_command(self):
        lanes = {
            'skills/implement/SKILL.md': [r'ICLI lane <n> in-progress --log <log\.md>', r'ICLI lane <n> in-review --log <log\.md>'],
            'skills/test-review/SKILL.md': [re.escape(ICLI) + r' lane <n> ready-to-release --log <log\.md>'],
            'skills/deploy/SKILL.md': [re.escape(ICLI) + r' lane <n> monitoring --log <log\.md>'],
            'skills/monitor/SKILL.md': [re.escape(ICLI) + r' close <n> --learned .+ --log <log\.md>'],
        }
        for path, patterns in lanes.items():
            for p in patterns:
                with self.subTest(path=path, pattern=p):
                    self.assertRegex(text(path), p)

    def test_stage_receipts(self):
        self.assertIn('Reviewer: session <id> · head <head sha> · <outside|fallback>', text('skills/test-review/SKILL.md'))
        deploy = text('skills/deploy/SKILL.md')
        self.assertIn('safeguard-cli run-approved release <id> --digest <d>', deploy)
        self.assertIn('`Pushed:`', deploy)
        monitor = text('skills/monitor/SKILL.md')
        for token in ('Monitor verdict: <first-traffic|24h>', 'Scheduler deleted: <runtime> <id>',
                      '`Learned:` (values: conveyor.md § Knowledge)', 'No release:'):
            self.assertIn(token, monitor)


class ContractsText(unittest.TestCase):
    def setUp(self):
        self.body = text(WC / 'contracts.md')

    def test_under_ninety_lines_and_no_scheduler_section(self):
        self.assertLess(self.body.count('\n'), 90)
        self.assertNotIn('## Scheduler', self.body)
        self.assertIn('Scheduler deleted: <runtime> <id>', section(self.body, 'Task log'))

    def test_chain_links_the_belt(self):
        self.assertIn('[conveyor.md](conveyor.md)', section(self.body, 'Chain'))

    def test_consent_has_one_approval_route(self):
        consent = section(self.body, 'Consent')
        approved = json.loads(text(WC / 'conveyor.json'))['receipts']['approved']
        self.assertIn('safeguard-cli run-approved <kind> <id> --digest <d>', consent)
        self.assertIn('conveyor.json `receipts.approved`', consent)
        self.assertIn('pattern', approved)
        self.assertNotIn("exact words>\"", consent)
        self.assertNotIn('travels with its task', consent)
        self.assertNotIn('child session or worker brief', consent)

    def test_test_slot_invocation_matches_authorizations(self):
        inv = json.loads(text('authorizations.json'))['invocation']['safeguard-cli']
        self.assertIn(f'`{inv} test-slot [--weight <suites run at once>]', self.body)


class IssuesAndDecisionsText(unittest.TestCase):
    def test_issues_names_lanes_guarded_moves_and_owner(self):
        body = text(WC / 'issues.md')
        for token in ('`lane:<name>`', 'ICLI lane <n> <lane>', '`Owner:`', '[conveyor.md](conveyor.md)'):
            self.assertIn(token, body)

    def test_decision_card_rules_live_in_one_home(self):
        rounds = section(text(WC / 'decisions.md'), 'Research and question rounds')
        for token in ('authorizations.json', 'issues-cli ask <n> --kind go|choice', '`card.short`', '`card.detail`',
                      '45 words', 'preview', 'Codex', 'one round per goal', 'Tell me more', 'Asked for more',
                      'issues-cli brief <n>', 'issues-cli decide <n>', '[conveyor.md](conveyor.md)'):
            with self.subTest(token=token):
                self.assertIn(token, rounds)
        self.assertNotIn('#\\d+', rounds)  # patterns stay in conveyor.json
        self.assertIn("the question text and the recommended option's description", rounds)
        self.assertNotIn("as the recommended option's `preview`", rounds)

    def test_a_kinds_approval_is_not_asked_by_the_worker(self):
        body = text(WC / 'decisions.md')
        self.assertNotIn('production action, asked by the executing worker', body)
        self.assertIn('one with a kind is prepared by the worker and cleared at the coordinator by its go card and click', body)
        self.assertIn('one with no kind is asked by the executing worker', body)

    def test_deploy_receipt_is_a_record_not_a_go_ahead(self):
        deploy = text('skills/deploy/SKILL.md')
        for s in (s for s in re.split(r'(?<=\.)\s+|\n', deploy) if 'Approved:' in s):
            with self.subTest(sentence=s):
                self.assertIn('never a permission', s)
                self.assertNotIn('proceed', s)
        self.assertIn("every non-branch § Deploy `Targets` entry needs the user's own go-ahead in this session, each time", deploy)
        self.assertEqual(deploy.count("own go-ahead"), 1)

    def test_coordinator_reads_resume_after_compaction(self):
        self.assertRegex(text('skills/agent-coordination/references/coordinator-mode.md'),
                         r'After a compaction, `issues-cli resume` comes first: state no fact about a session, PR, approval or owner before reading it')


class OutsideReviewSwitch(unittest.TestCase):
    """T6d: a repo whose config turns the outside reviewer off is reviewed only by the fresh-context reviewer."""

    def test_default_asks_the_outside_reviewer(self):
        self.assertTrue(g.gate_settings([], 'g1')['outside'])
        self.assertEqual(g.watch_step(dict(sent_at=1000, deadline_h=2, outside=True), 1100, None)['action'], 'wait')

    def test_config_switch_starts_the_local_reviewer_at_once(self):
        s = g.gate_settings([{}, {'g1': {'outside': False}}], 'g1')
        record = dict(sent_at=1000, deadline_h=s['deadline_h'], outside=s['outside'])
        self.assertEqual(g.watch_step(record, 1001, None)['action'], 'fallback')
        record['fallback_at'] = 1001
        self.assertEqual(g.watch_step(record, 1002, None)['action'], 'wait')
        self.assertEqual(g.watch_step(record, 1002, 'no-blocker')['action'], 'close')

    def test_no_repo_name_in_code(self):
        self.assertNotRegex(text('skills/agent-coordination/scripts/review_gate.py'), r'(?i)\bbrain\b')


if __name__ == '__main__':
    unittest.main()
