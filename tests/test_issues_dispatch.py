"""`issues-cli dispatch`: preflight caps, ownership marker, safe reserve, dry run and honest status (conveyor.md § Dispatch).
Delegate, gh and the machine's disk and slots are stubbed: nothing is started."""
import json
import re
import subprocess
import unittest.mock
from pathlib import Path

from agent_skills import dispatch, issues_cli
from test_issues_cli import REPO
from test_issues_cli_conveyor import BUILDER, CONVEYOR, COORD, BeltCase

HEARTBEAT = re.compile(CONVEYOR['dispatch']['heartbeat']['pattern'])
MARKER = re.compile(CONVEYOR['dispatch']['marker']['pattern'])
DELEGATE = Path(__file__).resolve().parents[1] / 'skills/agent-coordination/scripts/delegate.py'
WORKER = 'f0000000-0000-4000-8000-000000000001'
ADMITTED = json.dumps({'task_id': 't', 'dispatch_id': 'd1', 'session_id': WORKER, 'state': 'admitted'})


class DispatchCase(BeltCase):
    def setUp(self):
        super().setUp()
        self.state = self.root / 'state'
        self.configure(dispatch={'state_dir': str(self.state)})
        self.delegate_calls, self.result, self.during = [], (0, ADMITTED + '\n', ''), []
        self.disk, self.slots = (0, 'disk ok: plenty'), (4, 4, 0)
        for patcher in (unittest.mock.patch.object(dispatch, 'run_delegate', side_effect=self.fake_delegate),
                        unittest.mock.patch('agent_skills.disk_check.check', side_effect=lambda *a: self.disk),
                        unittest.mock.patch.object(issues_cli, 'test_slots', side_effect=lambda: self.slots)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_delegate(self, argv, stdin, timeout):
        self.delegate_calls.append((argv, stdin))
        self.during.append([json.loads(p.read_text())['status'] for p in sorted(self.state.glob('*.json'))])
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def dispatch(self, *extra, ok=True):
        return self.cli('dispatch', '--repo', REPO, *extra, ok=ok)

    def receipts(self):
        return {p.name: json.loads(p.read_text()) for p in self.state.glob('*.json')}

    def item(self, size='S', **kw):
        n = self.at('next', **kw)
        self.gh.issues[n]['labels'] = [x for x in self.gh.issues[n]['labels'] if not x['name'].startswith('size:')] + [{'name': f'size:{size}'}]
        return n

    def beat(self, out):
        [line] = [x for x in out.split('\n') if x.startswith('Tick:')]
        self.assertRegex(line, HEARTBEAT)
        return HEARTBEAT.match(line)


class Start(DispatchCase):
    def test_a_ready_item_starts_with_the_brief_and_goes_reserved_pending_verified(self):
        n = self.item()
        out = self.dispatch()
        self.assertEqual(self.during, [['submission_pending']])  # reserved is replaced before the prompt goes out
        self.assertEqual(self.receipts()[f'{REPO.replace("/", "-")}-{n}.json']['status'], 'verified')
        self.assertEqual(self.receipts()[f'{REPO.replace("/", "-")}-{n}.json']['session_id'], WORKER)
        [(argv, stdin)] = self.delegate_calls
        self.assertEqual(argv[0], 'start')
        self.assertIn('# Brief: #1 Widget', stdin)
        self.assertIn('--contract-file', argv)
        self.assertIn(f'started: #{n} (build) session {WORKER}', out)
        m = self.beat(out)
        self.assertEqual((m['started'], m['waiting'], m['held']), ('1', '0', '0'))
        self.assertEqual(self.gh.lane(n), 'next')  # dispatch never moves a card

    def test_files_named_in_the_issue_are_passed_to_delegate(self):
        n = self.item()
        self.gh.issues[n]['body'] += 'Files: a.py, b/c.py\n'
        self.dispatch()
        argv = self.delegate_calls[0][0]
        self.assertEqual(argv[argv.index('--files') + 1], 'a.py,b/c.py')

    def test_started_items_wait_for_their_claim_and_a_live_worker_is_not_restarted(self):
        self.item()
        self.dispatch()
        self.live = {WORKER}
        out = self.dispatch()
        self.assertEqual(len(self.delegate_calls), 1)
        self.assertIn('skipped: #1 started: waiting for the worker to claim', out)

    def test_the_batch_follows_priority_and_the_free_room(self):
        self.configure(dispatch={'state_dir': str(self.state), 'build_cap_override': 3})
        later, now_, nxt = self.item(), self.item(), self.item()
        self.gh.issues[later]['labels'].append({'name': 'prio:later'})
        self.gh.issues[now_]['labels'].append({'name': 'prio:now'})
        self.gh.issues[nxt]['labels'].append({'name': 'prio:next'})
        out = self.dispatch()
        self.assertEqual([c[1].split('\n')[0][:9] for c in self.delegate_calls], [f'# Brief: #{now_}'[:9], f'# Brief: #{nxt}'[:9]])
        self.assertIn(f'skipped: #{later} cap: last Build slot kept for prio:now (2 of 3 used)', out)
        self.assertEqual(self.beat(out)['waiting'], '1')

    def test_log_gets_the_tick_lines(self):
        self.item()
        self.dispatch('--log', str(self.log))
        self.assertRegex(self.log.read_text(), r'started: #1 .*\nTick: ')


class Caps(DispatchCase):
    defaults = '- Lane limits: Build 2 (1 kept free for `prio:now`, at most 1 size M) · Review 1 · Investigate 1 · Release 1 train of ≤6 PRs · Sessions 10\n'

    def skipped(self, n, why):
        out = self.dispatch()
        self.assertIn(f'skipped: #{n} {why}', out)
        self.assertEqual(self.delegate_calls, [])
        self.assertEqual(self.beat(out)['started'], '0')

    def test_build_limit(self):
        self.at('in-progress'), self.at('in-progress')
        self.skipped(self.item(), 'cap: Build 2 of 2')

    def test_first_week_cap_override_wins_over_the_contract_limit(self):
        self.configure(dispatch={'state_dir': str(self.state), 'build_cap_override': 1})
        self.at('in-progress')
        self.skipped(self.item(), 'cap: Build 1 of 1')

    def test_started_items_still_in_next_hold_their_build_slot(self):
        first, second = self.item(), self.item()
        self.gh.issues[first]['labels'].append({'name': 'prio:now'})
        self.configure(dispatch={'state_dir': str(self.state), 'build_cap_override': 1})
        self.dispatch()
        self.live, self.delegate_calls = {WORKER}, []
        self.skipped(second, 'cap: Build 1 of 1')

    def test_investigate_limit_counts_investigations_not_builds(self):
        self.at('in-progress', labels=('kind:question',))
        q = self.item(labels=('kind:question',))
        self.skipped(q, 'cap: Investigate 1 of 1')
        b = self.item()
        self.assertIn(f'started: #{b} (build)', self.dispatch())

    def test_the_last_free_build_slot_is_kept_for_prio_now(self):
        self.at('in-progress')
        later = self.item()
        self.skipped(later, 'cap: last Build slot kept for prio:now (1 of 2 used)')
        urgent = self.item()
        self.gh.issues[urgent]['labels'].append({'name': 'prio:now'})
        self.delegate_calls = []
        self.assertIn(f'started: #{urgent} (build)', self.dispatch())

    def test_the_now_slot_still_applies_under_the_first_week_override(self):
        self.configure(dispatch={'state_dir': str(self.state), 'build_cap_override': 3, 'sizes_allowed': ['S']})
        self.at('in-progress'), self.at('in-progress')
        self.skipped(self.item(), 'cap: last Build slot kept for prio:now (2 of 3 used)')

    def test_size_m_quota_in_build(self):
        self.configure(dispatch={'state_dir': str(self.state), 'build_cap_override': 5})
        self.at('in-progress', labels=('size:M',))
        m = self.item('M')
        out = self.dispatch()
        self.assertIn(f'skipped: #{m} cap: size M 1 of 1', out)
        self.assertEqual(self.delegate_calls, [])

    def test_a_contract_line_without_the_two_rules_is_refused_loudly(self):
        self.root.joinpath('CLAUDE.md').write_text(self.root.joinpath('CLAUDE.md').read_text().replace(
            ' (1 kept free for `prio:now`, at most 1 size M)', ''))
        self.item()
        self.assertIn('names no `prio:now` reserve', self.dispatch(ok=False))

    def test_drain_before_fill(self):
        self.at('in-review')
        self.skipped(self.item(), 'drain: Review is full (1 of 1)')

    def test_disk_floor(self):
        self.disk = (20, 'disk stop: 3.0 GB free (Worktree start free floor 10 GB)')
        self.skipped(self.item(), 'disk stop: 3.0 GB free (Worktree start free floor 10 GB)')

    def test_no_free_test_slot(self):
        self.slots = (1, 4, 1)
        self.skipped(self.item(), 'test slot: none free (1 of 4, 1 kept for release runs)')

    def test_size_filter_from_config_defaults_to_the_lane_sizes(self):
        self.configure(dispatch={'state_dir': str(self.state), 'sizes_allowed': ['S'], 'build_cap_override': 5})
        m, s = self.item('M'), self.item('S')
        out = self.dispatch()
        self.assertIn(f'skipped: #{m} size not allowed: M (allowed S)', out)
        self.assertIn(f'started: #{s} (build)', out)
        self.configure(dispatch={'state_dir': str(self.state), 'build_cap_override': 5})
        self.assertIn(f'started: #{m} (build)', self.dispatch())
        large = self.item('L')
        self.assertIn(f'skipped: #{large} size not allowed: L (allowed S, M)', self.dispatch())

    def test_an_item_without_an_owner_is_skipped(self):
        n = self.item()
        self.gh.issues[n]['comments'] = []
        self.skipped(n, 'missing Owner:')

    def test_the_owner_can_set_only_the_documented_keys(self):
        self.configure(dispatch={'state_dir': str(self.state), 'refusal_exit': 0})
        self.assertIn('workers.json dispatch sets refusal_exit', self.dispatch(ok=False))


class OwnershipMarker(DispatchCase):
    def marked(self, state, session=BUILDER):
        n = self.item()
        self.gh.comment(n, f'<!-- conveyor:v1 {state} {session} -->')
        return n

    def test_active_marker_of_a_session_still_in_the_registry_refuses(self):
        n = self.marked('active')
        self.at('in-progress')  # BUILDER holds open, unparked work
        out = self.dispatch()
        self.assertIn(f'skipped: #{n} marker: active session {BUILDER} still in the registry', out)
        self.assertEqual(self.delegate_calls, [])

    def test_a_released_marker_lets_it_start(self):
        n = self.marked('released')
        self.at('in-progress')
        self.assertIn(f'started: #{n}', self.dispatch())

    def test_the_latest_marker_wins(self):
        n = self.marked('active')
        self.gh.comment(n, f'<!-- conveyor:v1 released {BUILDER} -->')
        self.at('in-progress')
        self.assertIn(f'started: #{n}', self.dispatch())

    def test_an_active_marker_of_a_finished_session_does_not_refuse(self):
        n = self.marked('active')
        done = self.gh.add(lane='closed', comments=(f'Claimed: branch `x` · session {BUILDER}',))
        self.gh.close(done)
        self.assertIn(f'started: #{n}', self.dispatch())

    def test_markers_from_another_login_are_ignored(self):
        n = self.marked('active')
        self.gh.issues[n]['comments'][-1]['author'] = {'login': 'stranger'}
        self.at('in-progress')
        self.assertIn(f'started: #{n}', self.dispatch())

    def test_only_a_first_line_marker_counts(self):
        n = self.item()
        self.gh.comment(n, f'note\n<!-- conveyor:v1 active {BUILDER} -->')
        self.at('in-progress')
        self.assertIn(f'started: #{n}', self.dispatch())

    def test_claim_posts_an_active_marker_and_close_a_released_one(self):
        n = self.at('next')
        self.cli('claim', '--repo', REPO, str(n), '--branch', 'feat/w', '--session', BUILDER)
        self.assertEqual(self.gh.issues[n]['comments'][-1]['body'], f'<!-- conveyor:v1 active {BUILDER} -->')
        self.assertRegex(self.gh.issues[n]['comments'][-1]['body'], MARKER)
        self.cli('close', '--repo', REPO, str(n), '--no-release', 'chore', '--why', 'not needed',
                 '--learned', 'none', '--log', str(self.log))
        self.assertEqual(self.gh.issues[n]['comments'][-1]['body'], f'<!-- conveyor:v1 released {BUILDER} -->')
        self.assertIn('Learned: none', self.gh.lines(n))


class SafeReserve(DispatchCase):
    def test_a_refusal_proves_nothing_was_sent_so_the_reservation_is_released_and_the_next_tick_retries(self):
        n = self.item()
        self.result = (3, json.dumps({'refused': '3 workers already running (max_live 3)'}) + '\n', '')
        out = self.dispatch()
        self.assertIn(f'start waits: #{n} 3 workers already running (max_live 3)', out)
        self.assertEqual(self.receipts(), {})
        self.assertEqual(self.gh.lane(n), 'next')
        m = self.beat(out)
        self.assertEqual((m['started'], m['waiting'], m['held']), ('0', '1', '0'))
        self.result = (0, ADMITTED, '')
        self.assertIn(f'started: #{n}', self.dispatch())

    def test_the_refusal_exit_is_the_one_delegate_documents(self):
        declared = int(re.search(r'^REFUSED = (\d+)', DELEGATE.read_text(), re.M)[1])
        self.assertEqual(CONVEYOR['dispatch']['refusal_exit'], declared)

    def test_any_other_failure_is_uncertain_and_held_without_a_retry(self):
        n = self.item()
        self.result = (1, '', 'delegate: boom')
        out = self.dispatch()
        self.assertIn(f'start held: #{n}', out)
        self.assertEqual(self.receipts()[f'{REPO.replace("/", "-")}-{n}.json']['status'], 'submission_pending')
        m = self.beat(out)
        self.assertEqual((m['started'], m['held']), ('0', '1'))
        again = self.dispatch()
        self.assertEqual(len(self.delegate_calls), 1)  # never retried
        self.assertIn(f'start held: #{n} delegate start outcome unknown', again)
        self.assertEqual(self.beat(again)['held'], '1')

    def test_a_timeout_or_unreadable_admission_is_held(self):
        for result in (subprocess.TimeoutExpired('delegate', 1), (0, 'not json\n', ''), (0, '{}\n', '')):
            self.state.exists() and [p.unlink() for p in self.state.glob('*.json')]
            self.result, self.delegate_calls = result, []
            n = self.item()
            self.assertIn(f'start held: #{n}', self.dispatch())
            self.assertEqual(self.receipts()[f'{REPO.replace("/", "-")}-{n}.json']['status'], 'submission_pending')
            self.gh.issues[n]['labels'] = []  # out of the belt for the next round

    def test_a_pre_send_failure_building_the_brief_releases_the_reservation(self):
        n = self.item()
        with unittest.mock.patch.object(issues_cli, 'brief', side_effect=issues_cli.Refused('knowledge store unreadable')):
            out = self.dispatch()
        self.assertIn(f'start waits: #{n} knowledge store unreadable', out)
        self.assertEqual((self.receipts(), self.delegate_calls), ({}, []))

    def test_a_verified_receipt_with_no_running_worker_is_held(self):
        n = self.item()
        self.dispatch()
        out = self.dispatch()
        self.assertIn(f'start held: #{n} started but no running worker shown and still in next', out)
        self.assertEqual(len(self.delegate_calls), 1)

    def test_a_crash_before_submission_leaves_a_reserved_receipt_that_is_released_when_not_startable(self):
        n = self.item()
        self.state.mkdir()
        (self.state / f'{REPO.replace("/", "-")}-{n}.json').write_text(json.dumps({'status': 'reserved'}))
        self.disk = (20, 'disk stop')
        self.dispatch()
        self.assertEqual(self.receipts(), {})
        self.disk = (0, 'ok')
        self.assertIn(f'started: #{n}', self.dispatch())

    def test_two_ticks_never_run_together(self):
        self.item()
        import fcntl
        self.state.mkdir()
        with open(self.state / 'lock', 'w') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            self.assertIn('another dispatch is running', self.dispatch(ok=False))
        self.assertEqual(self.delegate_calls, [])


class UniqueAttempts(DispatchCase):
    """A task id is never reused: delegate refuses an existing one with FileExistsError (exit 1)."""
    def setUp(self):
        super().setUp()
        self.seen = set()
        real = self.fake_delegate

        def once(argv, stdin, timeout):
            task = argv[argv.index('--task-id') + 1]
            if task in self.seen:
                return 1, '', 'FileExistsError: task exists'
            self.seen.add(task)
            return real(argv, stdin, timeout)
        dispatch.run_delegate.side_effect = once

    def ids(self):
        return [c[0][c[0].index('--task-id') + 1] for c in self.delegate_calls]

    def test_a_retry_after_a_released_reservation_starts_a_new_task(self):
        self.item()
        self.result = (3, json.dumps({'refused': 'busy'}) + '\n', '')
        self.dispatch()
        self.result = (0, ADMITTED, '')
        self.assertIn('started: #1', self.dispatch())
        first, second = self.ids()
        self.assertNotEqual(first, second)

    def test_a_new_attempt_after_a_finished_one_starts_a_new_task(self):
        n = self.item()
        self.dispatch()
        self.live = set()
        for p in self.state.glob('*.json'):  # the owner checked the finished worker and cleared its receipt
            p.unlink()
        out = self.dispatch()
        self.assertIn(f'started: #{n}', out)
        self.assertEqual(len(set(self.ids())), 2)

    def test_a_crash_after_reserved_resumes_with_the_recorded_id(self):
        n = self.item()
        self.state.mkdir()
        (self.state / f'{REPO.replace("/", "-")}-{n}.json').write_text(json.dumps({'status': 'reserved', 'task_id': 'conveyor-recorded-1'}))
        self.dispatch()
        self.assertEqual(self.ids(), ['conveyor-recorded-1'])

    def test_reserved_records_the_task_id_before_the_brief_is_built(self):
        n = self.item()
        seen = []
        real = issues_cli.brief
        def spy(*a, **k):
            seen.append(json.loads(next(self.state.glob('*.json')).read_text()))
            return real(*a, **k)
        with unittest.mock.patch.object(issues_cli, 'brief', side_effect=spy):
            self.dispatch()
        self.assertEqual(seen[0]['status'], 'reserved')
        self.assertEqual(seen[0]['task_id'], self.ids()[0])

    def test_the_hold_text_names_the_task_and_a_way_out_that_does_not_loop(self):
        n = self.item()
        self.result = (1, '', 'boom')
        self.dispatch()
        task = self.ids()[0]
        out = self.dispatch()
        self.assertIn(f'delegate.py status {task}', out)
        self.assertIn('no run exists', out)
        for p in self.state.glob('*.json'):
            p.unlink()
        self.result = (0, ADMITTED, '')
        self.assertIn(f'started: #{n}', self.dispatch())


class DryRun(DispatchCase):
    def test_it_writes_nothing_starts_nothing_and_says_why_each_other_item_waits(self):
        self.configure(dispatch={'state_dir': str(self.state), 'sizes_allowed': ['S']})
        go, big, ownerless, marked, held = self.item(), self.item('M'), self.item(), self.item(), self.item()
        self.gh.issues[ownerless]['comments'] = []
        self.gh.comment(marked, f'<!-- conveyor:v1 active {BUILDER} -->')
        self.at('in-progress')
        self.state.mkdir()
        (self.state / f'{REPO.replace("/", "-")}-{held}.json').write_text(json.dumps({'status': 'submission_pending'}))
        before = (self.gh.calls[:], self.receipts())
        out = self.dispatch('--dry-run')
        self.assertEqual([c for c in self.gh.calls[len(before[0]):] if issues_cli.is_write(c[0])], [])
        self.assertEqual((self.delegate_calls, self.receipts()), ([], before[1]))
        self.assertFalse((self.state / 'lock').exists())
        self.assertIn(f'Would start: #{go} (build)', out)
        self.assertIn(f'Skipped: #{big} size not allowed: M', out)
        self.assertIn(f'Skipped: #{ownerless} missing Owner:', out)
        self.assertIn(f'Skipped: #{marked} marker: active session {BUILDER}', out)
        self.assertIn(f'start held: #{held} delegate start outcome unknown', out)
        self.assertNotIn('Tick:', out)

    def test_it_names_the_now_slot_and_the_size_m_quota(self):
        self.configure(dispatch={'state_dir': str(self.state), 'build_cap_override': 3})
        self.at('in-progress', labels=('size:M',)), self.at('in-progress', labels=('size:M',))
        late = self.item()
        out = self.dispatch('--dry-run')
        self.assertIn(f'Skipped: #{late} cap: last Build slot kept for prio:now (2 of 3 used)', out)
        self.gh.issues[late]['labels'].append({'name': 'prio:now'})
        m = self.item('M')
        self.gh.issues[m]['labels'].append({'name': 'prio:now'})
        self.assertIn(f'Skipped: #{m} cap: size M 2 of 2', self.dispatch('--dry-run'))

    def test_the_global_dry_run_flag_means_the_same(self):
        n = self.item()
        out = self.cli('--dry-run', 'dispatch', '--repo', REPO)
        self.assertIn(f'Would start: #{n} (build)', out)
        self.assertFalse(self.state.exists())
        self.assertEqual((self.delegate_calls, self.gh.writes()), ([], []))


class HonestStatus(DispatchCase):
    def lines(self):
        return self.sweep().split('\n')

    def test_an_in_progress_issue_without_a_running_worker_or_pr_is_unverified_and_stays_put(self):
        n = self.at('in-progress')
        before = len(self.gh.writes())
        self.assertIn(f'worker activity unverified: #{n}', self.lines())
        self.assertEqual((self.gh.lane(n), len(self.gh.writes())), ('in-progress', before))

    def test_a_running_worker_is_working_and_not_flagged(self):
        n = self.at('in-progress')
        self.live = {BUILDER}
        out = self.sweep()
        self.assertNotIn('worker activity unverified', out)
        self.assertIn(f'- {BUILDER} · working · claimed #{n} (in-progress)', out)

    def test_without_live_evidence_the_session_is_never_shown_as_working(self):
        self.at('in-progress')
        out = self.sweep()
        self.assertIn('Sessions: 0 working, 2 unverified', out)
        self.assertNotIn('· working ·', out)

    def test_a_pr_or_a_park_removes_the_line(self):
        pr, parked = self.at('in-progress'), self.at('in-progress', labels=('parked',))
        self.gh.link_pr(pr)
        self.assertNotIn('worker activity unverified', self.sweep())

    def test_an_unreadable_job_registry_is_said_not_assumed(self):
        with unittest.mock.patch.object(issues_cli, 'live_sessions', side_effect=RuntimeError('delegate status exited 2: bad row')):
            out = self.at('in-progress') and self.sweep()
        self.assertIn('Live evidence unavailable (delegate status exited 2: bad row): no worker is shown as working', out)

    def test_live_sessions_reads_only_running_rows_of_delegate_status(self):
        rows = [{'task_id': 'a', 'state': 'live', 'session_id': WORKER}, {'task_id': 'b', 'state': 'lost?', 'session_id': 'x'},
                {'task_id': 'c', 'state': 'unknown', 'session_id': 'y'}]
        done = subprocess.CompletedProcess([], 0, ''.join(json.dumps(r) + '\n' for r in rows), '')
        with unittest.mock.patch.object(subprocess, 'run', return_value=done) as call:
            self.assertEqual(self.real_live(), {WORKER})
        self.assertEqual(call.call_args[0][0][-1], 'status')
        with unittest.mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, '', 'coverage')):
            with self.assertRaisesRegex(RuntimeError, 'delegate status exited 2'):
                self.real_live()

    real_live = staticmethod(issues_cli.live_sessions)  # captured before BeltCase patches it
