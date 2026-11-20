"""`issues-cli belt-tick`: sweep, inbox list, pull report, dispatch and one heartbeat, in design order (conveyor.md § Flow).
gh, delegate, the clock and the machine's disk and slots are stubbed; the scheduled-task file is read as text."""
import json
import re
import unittest.mock
from pathlib import Path

from agent_skills import dispatch, issues_cli
from test_issues_cli import REPO
from test_issues_cli_conveyor import CONVEYOR
from test_issues_dispatch import DispatchCase

ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT = re.compile(CONVEYOR['tick']['heartbeat']['pattern'])
SECTIONS = ['== sweep ==', '== inbox ==', '== pull ==', '== dispatch ==']


class TickCase(DispatchCase):
    def tick(self, *extra, ok=True):
        return self.cli('belt-tick', '--repo', REPO, *extra, ok=ok)

    def beat(self, out):
        [line] = [x for x in out.split('\n') if x.startswith('Tick:')]
        self.assertRegex(line, HEARTBEAT)
        return HEARTBEAT.match(line)

    def spool(self, text='Fix the gate'):
        path = Path(self.config['capture_spool'])
        path.write_text(json.dumps({'repo': REPO, 'text': text, 'source': 'chat', 'tag': None, 'at': '2026-11-18 11:00Z'}) + '\n')
        return path


class Order(TickCase):
    def test_steps_run_in_design_order_and_each_sees_the_one_before(self):
        self.spool()
        ready = self.item()
        out = self.tick()
        self.assertEqual([out.index(s) for s in SECTIONS], sorted(out.index(s) for s in SECTIONS))
        self.assertIn('filed spooled capture #2', out)  # the sweep flushed the spool before the inbox list was read
        self.assertIn('- #2 ', out.split('== inbox ==')[1].split('== pull ==')[0])
        self.assertIn(f'started: #{ready} (build)', out)
        self.assertEqual(self.gh.lane(2), 'inbox')  # tick lists the item and never sorts it
        self.assertEqual(self.gh.lane(ready), 'next')

    def test_the_inbox_step_lists_the_allowed_values_for_the_model(self):
        self.gh.add(lane='inbox', body='x\n\nCaptured: 2026-11-18 11:00Z · source chat\n')
        out = self.tick()
        self.assertRegex(out, r'Allowed: domain deploy, policy · kind bug, alert, question, feature, chore · size S, M, L')
        self.assertIn('Inbox to sort: 1', out)

    def test_pull_reports_the_sweeps_pull_next_line_and_moves_nothing(self):
        n = self.at('backlog', labels=('prio:now',))
        out = self.tick()
        self.assertIn(f'Pull next: #{n} (publish moves them)', out.split('== pull ==')[1])
        self.assertEqual(self.gh.lane(n), 'backlog')

    def test_heartbeat_counts(self):
        self.item()
        self.gh.add(lane='inbox', body='x\n\nCaptured: 2026-11-18 11:00Z · source chat\n')
        m = self.beat(self.tick())
        self.assertEqual((m['started'], m['waiting'], m['held'], m['inbox']), ('1', '0', '0', '1'))
        self.assertEqual(self.tick().count('Tick: '), 1)  # dispatch's own line is folded into the one heartbeat


class Failures(TickCase):
    def test_a_failed_sweep_skips_pull_and_the_independent_steps_still_run(self):
        ready = self.item()
        self.gh.add(lane='inbox', body='x\n\nCaptured: 2026-11-18 11:00Z · source chat\n')
        with unittest.mock.patch.object(issues_cli, 'board', side_effect=RuntimeError('github unreachable')):
            out = self.tick(ok=False)
        self.assertIn('step failed: sweep: github unreachable', out)
        self.assertIn('skipped: pull (needs sweep)', out)
        self.assertIn('Inbox to sort: 1', out)
        self.assertIn(f'started: #{ready} (build)', out)
        self.assertEqual(self.beat(out)['started'], '1')

    def test_a_failed_dispatch_is_reported_and_the_heartbeat_still_prints(self):
        with unittest.mock.patch.object(dispatch, 'run', side_effect=issues_cli.Refused('another dispatch is running')):
            out = self.tick(ok=False)
        self.assertIn('step failed: dispatch: another dispatch is running', out)
        self.assertIn('== sweep ==', out)
        m = self.beat(out)
        self.assertEqual((m['started'], m['waiting'], m['held']), ('0', '0', '0'))

    def test_a_failed_inbox_read_does_not_stop_dispatch(self):
        ready = self.item()
        real = issues_cli.open_belt
        calls = []

        def flaky(gh, repo):
            calls.append(1)
            if len(calls) > 1:  # the sweep's read works; the inbox step's does not
                raise RuntimeError('boom')
            return real(gh, repo)
        with unittest.mock.patch.object(issues_cli, 'open_belt', side_effect=flaky):
            out = self.tick(ok=False)
        self.assertIn('step failed: inbox: boom', out)
        self.assertIn('== pull ==', out)


class DryRun(TickCase):
    def test_dry_run_writes_nothing_anywhere(self):
        path = self.spool()
        before = path.read_text()
        self.item()
        self.gh.add(lane='inbox', body='x\n\nCaptured: 2026-11-18 11:00Z · source chat\n')
        self.log.write_text('# log\n')
        self.gh.calls.clear()
        out = self.tick('--dry-run', '--log', str(self.log))
        self.assertEqual(self.gh.writes(), [])
        self.assertEqual(self.delegate_calls, [])
        self.assertEqual(path.read_text(), before)
        self.assertEqual(self.log.read_text(), '# log\n')
        self.assertEqual(list(self.state.glob('*.json')), [])
        self.assertIn('Would start: #1 (build)', out)
        m = self.beat(out)
        self.assertEqual(m['started'], '0')


class TickFile(unittest.TestCase):
    path = ROOT / 'skills/workflow-contracts/references/tick.md'

    def test_the_file_exists_is_within_80_lines_and_its_budget_and_has_a_home(self):
        text = self.path.read_text()
        self.assertLessEqual(len(text.splitlines()), 80)
        budgets = json.loads((ROOT / 'skills/budgets.json').read_text())['files']
        self.assertGreaterEqual(budgets['skills/workflow-contracts/references/tick.md']['bytes'], len(text.encode()))
        homes = json.loads((ROOT / 'skills/homes.json').read_text())['homes']
        [home] = [h for h in homes if h['home'] == 'skills/workflow-contracts/references/tick.md']
        self.assertRegex(text, home['pattern'])

    def test_it_runs_the_command_at_the_configured_cadence_and_says_it_is_not_registered(self):
        text = self.path.read_text()
        self.assertIn('issues-cli belt-tick', text)
        self.assertIn('issues-cli sort', text)
        self.assertIn('--needs-decision', text)
        self.assertIn(f"every {CONVEYOR['tick']['cadence_minutes']} minutes", text)
        self.assertIn('not registered', text)

    def test_every_line_naming_a_gated_action_forbids_it(self):
        for line in self.path.read_text().splitlines():
            if re.search(r'\b(merge|deploy|send|publish|ask the owner)\b', line, re.I):
                self.assertRegex(line, r'(?i)\b(never|not)\b', line)
