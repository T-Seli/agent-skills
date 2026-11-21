"""Fixes from the real-worker dry run (F7 to F10): the installed wrapper, a new --log file, the worker's issues-cli tree and
the parent posting the worker's result. gh and delegate are stubbed; the wrapper test runs the real wrapper script."""
import json
import os
import re
import stat
import subprocess
import unittest.mock
from pathlib import Path

from agent_skills import dispatch, issues_cli, layout
from test_issues_cli import REPO, belt_project
from test_issues_cli_conveyor import CONVEYOR, BeltCase
from test_issues_dispatch import ADMITTED, WORKER, DispatchCase

WRAPPER = Path(__file__).resolve().parents[1] / 'skills/workflow-contracts/scripts/issues-cli'
WORKER_RESULT = re.compile(CONVEYOR['receipts']['worker_result']['pattern'])
FAKE_GH = """#!/bin/sh
case "$*" in
  *"api user"*) echo me ;;
  *"issue list"*) echo '[]' ;;
  *) echo "unexpected gh call: $*" >&2; exit 9 ;;
esac
"""


class InstalledWrapper(unittest.TestCase):
    """F7: the installed `issues-cli` runs the module with runpy, so `sys.modules[__name__]` is not the module."""
    def setUp(self):
        self.root = belt_project(self, knowledge='none')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.bin / 'gh').write_text(FAKE_GH)
        (self.bin / 'gh').chmod((self.bin / 'gh').stat().st_mode | stat.S_IXUSR)
        patched = unittest.mock.patch.dict(os.environ, {'PATH': f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                                                        'AGENT_COORDINATION_STATE': str(self.root / 'coord')})
        patched.start()
        self.addCleanup(patched.stop)

    def wrapper(self, *argv):
        done = subprocess.run([str(WRAPPER), *argv], capture_output=True, text=True, cwd=self.root, stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout + done.stderr

    def test_dispatch_dry_run_runs_under_the_wrapper(self):
        code, out = self.wrapper('dispatch', '--repo', REPO, '--dry-run')
        self.assertEqual(code, 0, out)
        self.assertIn('Dry run: nothing started', out)

    def test_feed_runs_under_the_wrapper_and_refuses_a_disabled_feed_by_name(self):
        code, out = self.wrapper('feed', '--repo', REPO, 'mail')
        self.assertEqual(code, 1, out)
        self.assertIn('feed mail is disabled', out)
        self.assertNotIn('Traceback', out)

    def test_belt_tick_dry_run_runs_under_the_wrapper(self):
        code, out = self.wrapper('belt-tick', '--repo', REPO, '--dry-run')
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r'(?m)^Tick: .* · inbox 0$')


class NewLogFile(BeltCase):
    """F8: `--log` names a file that does not exist yet."""
    def test_belt_tick_creates_the_log_inside_the_working_directory(self):
        new = self.root / 'fresh.md'
        out = self.cli('belt-tick', '--repo', REPO, '--log', str(new))
        self.assertEqual([x for x in new.read_text().split('\n') if x.startswith('Tick:')], [x for x in out.split('\n') if x.startswith('Tick:')])

    def test_a_log_outside_the_working_directory_is_still_refused(self):
        self.assertIn('outside the working directory', self.cli('belt-tick', '--repo', REPO, '--log', '/tmp/not-here-log.md', ok=False))

    def test_dry_run_does_not_create_the_log(self):
        new = self.root / 'fresh.md'
        self.cli('belt-tick', '--repo', REPO, '--dry-run', '--log', str(new))
        self.assertFalse(new.exists())


class WorkerTree(DispatchCase):
    """F9: the worker uses the issues-cli of the tree that dispatches it."""
    def scripts(self):
        return str(layout.contract('scripts/issues-cli').parent)

    def test_the_worker_env_puts_this_trees_scripts_first(self):
        env = dispatch.worker_env(issues_cli, dispatch.settings(issues_cli))
        self.assertEqual(env['PATH'].split(os.pathsep)[0], self.scripts())

    def test_dispatch_passes_that_env_to_delegate(self):
        self.item()
        self.dispatch()
        self.assertEqual(self.delegate_envs[0]['PATH'].split(os.pathsep)[0], self.scripts())

    def test_the_brief_names_the_exact_command(self):
        self.item()
        self.dispatch()
        self.assertIn(str(layout.contract('scripts/issues-cli')), self.delegate_calls[0][1])


class ParentPostsResult(DispatchCase):
    """F10: the worker cannot comment, so the parent posts its finished result on the issue, once."""
    def setUp(self):
        super().setUp()
        self.coord = self.root / 'coord'
        patched = unittest.mock.patch.dict(os.environ, {'AGENT_COORDINATION_STATE': str(self.coord)})
        patched.start()
        self.addCleanup(patched.stop)

    def start_item(self):
        n = self.item()
        self.dispatch()
        [(task, receipt)] = [(r['task_id'], p) for p, r in ((p, json.loads(p.read_text())) for p in self.state.glob('*.json'))]
        return n, task

    def finish(self, task, **report):
        run = self.coord / 'runs' / task / 'd1'
        run.mkdir(parents=True)
        (run / 'receipt.json').write_text(json.dumps({
            'task_id': task, 'dispatch_id': 'd1', 'outcome': 'done', 'exit_code': 0, 'finished_at': '2026-11-18 12:30Z',
            'cost_usd': 0.87, 'report': {'status': 'blocked', 'summary': 'Built it.\nDraft PR is open.', 'commit': 'f9fcf12',
                                         'tests': 'content check', 'need': 'parent posts the result', **report}}))

    def result_lines(self, n):
        return [m for x in self.gh.lines(n) if (m := WORKER_RESULT.match(x))]

    def test_a_finished_worker_gets_its_result_posted_once(self):
        n, task = self.start_item()
        out = self.dispatch()
        self.assertEqual(self.result_lines(n), [])  # no receipt yet: still running
        self.finish(task)
        out = self.dispatch()
        [m] = self.result_lines(n)
        self.assertEqual((m['task'], m['outcome'], m['status'], m['commit']), (task, 'done', 'blocked', 'f9fcf12'))
        self.assertIn('Summary: Built it. Draft PR is open.', self.gh.lines(n))
        self.assertIn('Need: parent posts the result', self.gh.lines(n))
        self.assertIn(f'posted: #{n} worker result', out)
        self.dispatch()
        self.assertEqual(len(self.result_lines(n)), 1)

    def test_dry_run_posts_nothing(self):
        n, task = self.start_item()
        self.finish(task)
        self.gh.calls.clear()
        out = self.dispatch('--dry-run')
        self.assertEqual(self.gh.writes(), [])
        self.assertIn(f'Would post: #{n} worker result', out)
