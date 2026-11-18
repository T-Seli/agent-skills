"""issues-cli belt commands (conveyor.md) against a fake gh that keeps GitHub's state in memory."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_skills import issues_cli
from test_issues_cli import REPO, belt_project, draft, run, spec_body, stub_knowledge

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
CONVEYOR = json.loads((Path(__file__).resolve().parents[1] / 'skills/workflow-contracts/conveyor.json').read_text())
TIMELINE = re.compile(CONVEYOR['timeline']['pattern'])
HEAD, NEW_HEAD = 'a1b2c3d' + '0' * 33, 'e4f5a6b' + '0' * 33
Q = 'https://github.com/o/r/issues/1#issuecomment-9'


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


class Belt:
    """A fake gh holding issues, labels and PRs; writes change its state as GitHub would. `offline` fails every call
    the way gh does when GitHub cannot be reached."""
    def __init__(self, clock):
        self.issues, self.labels, self.prs, self.calls, self.offline, self.clock = {}, set(), {}, [], False, clock

    def add(self, lane=None, labels=(), body='Done when: it works\n', comments=(), age=timedelta(0), title='Widget'):
        n = len(self.issues) + 1
        self.issues[n] = {'number': n, 'title': title, 'body': body, 'state': 'OPEN', 'url': f'https://github.com/{REPO}/issues/{n}',
                          'labels': [{'name': x} for x in ([f'lane:{lane}'] if lane else []) + list(labels)],
                          'comments': [{'author': {'login': 'me'}, 'body': c} for c in comments],
                          'createdAt': iso(self.clock() - age), 'closedByPullRequestsReferences': [],
                          'assignees': [], 'author': {'login': 'me'}}
        return n

    def link_pr(self, n, head=HEAD):
        pr = 500 + n
        self.prs[pr] = head
        self.issues[n]['closedByPullRequestsReferences'] = [{'number': pr, 'url': f'https://github.com/{REPO}/pull/{pr}'}]
        return pr

    def lane(self, n):
        return issues_cli.lane_of(self.issues[n])

    def names(self, n):
        return issues_cli.label_names(self.issues[n])

    def comment(self, n, body):
        self.issues[n]['comments'].append({'author': {'login': 'me'}, 'body': body})

    def lines(self, n):
        return issues_cli.comment_lines(self.issues[n])

    def timeline(self, n):
        return issues_cli.timeline_of(self.lines(n))

    def writes(self):
        return [a for a, _ in self.calls if issues_cli.is_write(a)]

    def opt(self, args, flag):
        return args[args.index(flag) + 1] if flag in args else None

    def __call__(self, args, stdin=None):
        self.calls.append((args, stdin))
        if self.offline:
            raise subprocess.CalledProcessError(1, ['gh', *args], stderr='error connecting to api.github.com')
        if args[:2] == ['issue', 'create']:
            n = self.add(labels=(self.opt(args, '--label') or '').split(',') if '--label' in args else (),
                         body=stdin, title=self.opt(args, '--title'))
            return f'https://github.com/{REPO}/issues/{n}\n'
        if args[:2] == ['issue', 'view']:
            return json.dumps(self.issues[int(args[2])])
        if args[:2] == ['issue', 'list']:
            state, label = self.opt(args, '--state'), self.opt(args, '--label')
            found = [i for i in reversed(self.issues.values())
                     if (state == 'all' or i['state'] == state.upper()) and (not label or label in issues_cli.label_names(i))]
            return json.dumps(found)
        if args[:2] == ['issue', 'edit']:
            i = self.issues[int(args[2])]
            drop = (self.opt(args, '--remove-label') or '').split(',')
            i['labels'] = [x for x in i['labels'] if x['name'] not in drop]
            i['labels'] += [{'name': x} for x in (self.opt(args, '--add-label') or '').split(',') if x]
            if '--add-assignee' in args:
                i['assignees'].append({'login': 'me'})
            return ''
        if args[:2] == ['issue', 'comment']:
            self.comment(int(args[2]), stdin.strip())
            return ''
        if args[:2] == ['issue', 'close']:
            self.issues[int(args[2])]['state'] = 'CLOSED'
            self.comment(int(args[2]), self.opt(args, '--comment').strip())
            return ''
        if args[:2] == ['label', 'list']:
            return '\n'.join(sorted(self.labels))
        if args[:2] == ['label', 'create']:
            self.labels.add(args[2])
            return ''
        if args[:2] == ['pr', 'view']:
            return self.prs[int(args[2])] + '\n'
        if args[:2] == ['api', 'user']:
            return 'me\n'
        raise AssertionError(f'unexpected gh call {args}')


class BeltCase(unittest.TestCase):
    defaults = ''

    def setUp(self):
        self.root = belt_project(self, defaults=self.defaults)
        (self.root / 'workers.json').write_text(json.dumps({'capture_spool': str(self.root / 'spool.jsonl')}))
        self.k = stub_knowledge(self, pages={'deploy': [{'store': 'wiki', 'path': 'pages/release.md', 'verified': '2026-11-02',
                                                         'sha': 'abc1234', 'pending': False}]})
        self.t = T0
        clock = unittest.mock.patch.object(issues_cli, 'now', side_effect=lambda: self.t)
        clock.start()
        self.addCleanup(clock.stop)
        self.started = []
        starter = unittest.mock.patch.object(issues_cli, 'start_reviewer', side_effect=lambda *a: self.started.append(a))
        starter.start()
        self.addCleanup(starter.stop)
        self.gh = Belt(lambda: self.t)
        self.log = self.root / 'log.md'
        self.log.write_text('# log\n')

    def cli(self, *argv, ok=True):
        code, out, err = run(self.gh, *argv)
        if ok is not None:
            self.assertEqual(code, 0 if ok else 1, err or out)
        return out + err

    def lane(self, n, target, *extra, ok=True):
        return self.cli('lane', '--repo', REPO, str(n), target, '--log', str(self.log), *extra, ok=ok)

    def write_log(self, *lines):
        with self.log.open('a') as fh:
            fh.write(''.join(line + '\n' for line in lines))

    def sweep(self, *extra):
        return self.cli('sweep', '--repo', REPO, *extra)

    def board(self, out, prefix):
        return next(line for line in out.split('\n') if line.startswith(prefix))

    # one helper per lane: the receipts its entry rule reads
    def ready_backlog(self, n):
        self.gh.issues[n]['labels'] += [{'name': 'domain:deploy'}, {'name': 'size:S'}]

    def ready_next(self, n):
        self.gh.comment(n, 'Owner: thomas · session coord-1 · 2026-11-18 11:00Z')

    def ready_in_progress(self, n):
        self.gh.comment(n, 'Claimed: branch `feat/w` · session builder-1')
        self.cli('brief', '--repo', REPO, str(n))

    def ready_in_review(self, n, head=HEAD):
        self.write_log('## 2026-11-18 12:00Z — implement: done')
        self.gh.link_pr(n, head)

    def ready_release(self, n, head=HEAD):
        self.write_log(f'Reviewed: {head[:7]} YES', f'Reviewer: session reviewer-1 · head {head[:7]} · outside')

    def ready_monitoring(self):
        self.write_log(f'Approved: release r-1 · digest {"d" * 64} · 2026-11-18 12:00Z · question {Q} · session coord-1',
                       '## 2026-11-18 12:05Z — deploy: a1b2c3d to local', 'Rollback: local: 0123abc',
                       'Scheduler: claude monitor-r-first', 'Scheduler: claude monitor-r-24h')

    def ready_closed(self):
        self.write_log('Monitor verdict: first-traffic All working · 2026-11-18 13:00Z',
                       'Monitor verdict: 24h All working · 2026-11-19 12:00Z',
                       'Scheduler deleted: claude monitor-r-first', 'Scheduler deleted: claude monitor-r-24h')

    def at(self, lane, labels=()):
        """An issue already in `lane` with every earlier receipt present."""
        n = self.gh.add(lane=lane, labels=('domain:deploy', 'size:S', *labels),
                        body='Fix widgets\n\nCaptured: 2026-11-18 11:00Z · source chat\nDone when: it works\n')
        order = issues_cli.lanes()
        if order.index(lane) >= order.index('next'):
            self.ready_next(n)
        if order.index(lane) >= order.index('in-progress'):
            self.gh.comment(n, 'Claimed: branch `feat/w` · session builder-1')
            self.gh.comment(n, f'Conveyor: 2026-11-18 11:30Z · brief · next → next · head - · tests - · skills {"f" * 7} · schedules -')
        return n


class Lanes(BeltCase):
    """T1-a1: each lane move is refused, naming the missing receipt, until the entry rule holds."""
    def test_inbox_needs_captured(self):
        n = self.gh.add(body='loose words\n')
        self.assertIn('capture (issue body `Captured:`)', self.lane(n, 'inbox', ok=False))
        self.gh.issues[n]['body'] = 'loose words\n\nCaptured: 2026-11-18 11:00Z · source chat\n'
        self.lane(n, 'inbox')
        self.assertEqual(self.gh.lane(n), 'inbox')

    def test_backlog_needs_one_domain_and_one_size_label(self):
        n = self.at('inbox')
        self.gh.issues[n]['labels'] = [{'name': 'lane:inbox'}]
        out = self.lane(n, 'backlog', ok=False)
        self.assertIn('domain (label)', out)
        self.assertIn('size (label)', out)
        self.ready_backlog(n)
        self.lane(n, 'backlog')
        self.assertEqual(self.gh.lane(n), 'backlog')

    def test_next_needs_owner_and_done_when_and_room(self):
        n = self.at('backlog')
        self.gh.issues[n]['body'] = 'no spec yet\n'
        out = self.lane(n, 'next', ok=False)
        self.assertIn('owner (issue comment `Owner:`)', out)
        self.assertIn('done_when (issue body `Done when:`)', out)
        self.gh.issues[n]['body'] = 'Done when: widgets show\n'
        self.ready_next(n)
        for _ in range(7):
            self.gh.add(lane='in-progress')
        first = self.at('backlog')
        self.ready_next(first)
        self.lane(first, 'next')  # the one free Build slot
        self.assertIn('room (next holds 1; Build has 1 free slots)', self.lane(n, 'next', ok=False))

    def test_in_progress_needs_claim_brief_and_a_build_slot(self):
        n = self.gh.add(lane='next', labels=('domain:deploy', 'size:S'))
        self.ready_next(n)
        out = self.lane(n, 'in-progress', ok=False)
        self.assertIn('claim (issue comment `Claimed:`)', out)
        self.assertIn('brief (Conveyor brief line)', out)
        self.ready_in_progress(n)
        for _ in range(7):
            self.gh.add(lane='in-progress')
        self.assertIn('the last Build slot is kept for prio:now', self.lane(n, 'in-progress', ok=False))
        self.gh.issues[n]['labels'].append({'name': 'prio:now'})
        self.lane(n, 'in-progress')
        m = self.gh.add(lane='next')
        self.assertIn('limit (Build 8 of 8)', self.lane(m, 'in-progress', ok=False))

    def test_in_review_needs_implement_done_and_a_linked_pr(self):
        n = self.at('in-progress')
        out = self.lane(n, 'in-review', ok=False)
        self.assertIn('implement_done (log)', out)
        self.assertIn('pr (linked PR)', out)
        self.ready_in_review(n)
        self.lane(n, 'in-review')

    def test_ready_to_release_needs_yes_and_a_different_reviewer_on_the_current_head(self):
        n = self.at('in-review')
        self.gh.link_pr(n, NEW_HEAD)
        self.ready_release(n, HEAD)  # reviewed an older head
        out = self.lane(n, 'ready-to-release', ok=False)
        self.assertIn('reviewed_yes (log `Reviewed:`)', out)
        self.assertIn('reviewer (log `Reviewer:`)', out)
        self.write_log(f'Reviewed: {NEW_HEAD[:7]} YES', f'Reviewer: session builder-1 · head {NEW_HEAD[:7]} · fallback')
        out = self.lane(n, 'ready-to-release', ok=False)
        self.assertNotIn('reviewed_yes', out)
        self.assertIn('reviewer (log `Reviewer:`)', out)  # the builder may not review its own work
        self.write_log(f'Reviewer: session reviewer-2 · head {NEW_HEAD[:7]} · fallback')
        self.lane(n, 'ready-to-release')
        self.assertEqual(self.gh.timeline(n)[-1]['head'], NEW_HEAD)

    def test_monitoring_needs_approved_deploy_rollback_and_two_schedules(self):
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        out = self.lane(n, 'monitoring', ok=False)
        for name in ('approved', 'deploy', 'rollback', 'schedule'):
            self.assertIn(name, out)
        self.write_log(f'Approved: release r-1 · digest {"d" * 64} · 2026-11-18 12:00Z · question {Q} · session coord-1',
                       '## 2026-11-18 12:05Z — deploy: a1b2c3d to local', 'Rollback: local: 0123abc',
                       'Scheduler: claude monitor-r-first')
        self.assertIn('schedule (log `Scheduler:`)', self.lane(n, 'monitoring', ok=False))
        self.write_log('Scheduler: claude monitor-r-24h')
        self.lane(n, 'monitoring')
        self.assertEqual(self.gh.timeline(n)[-1]['schedules'], 'monitor-r-24h,monitor-r-first')

    def test_closed_needs_both_verdicts_both_deletions_and_learned(self):
        n = self.at('monitoring')
        self.ready_monitoring()
        self.write_log('Monitor verdict: first-traffic All working · 2026-11-18 13:00Z', 'Scheduler deleted: claude monitor-r-first')
        out = self.cli('close', '--repo', REPO, str(n), '--log', str(self.log), '--learned', 'none', ok=False)
        self.assertIn('monitor_24h', out)
        self.assertIn('monitor_deleted', out)
        self.assertNotIn('learned', out)
        self.write_log('Monitor verdict: 24h All working · 2026-11-19 12:00Z', 'Scheduler deleted: claude monitor-r-24h')
        self.assertIn('close needs --learned', self.cli('close', '--repo', REPO, str(n), ok=False))
        self.assertIn('learned (closing comment `Learned:`)', self.lane(n, 'closed', '--learned', 'maybe', ok=False))
        self.cli('close', '--repo', REPO, str(n), '--log', str(self.log), '--learned', 'lesson: widgets need a cache')
        self.assertEqual(self.gh.issues[n]['state'], 'CLOSED')
        self.assertEqual(self.gh.issues[n]['comments'][-1]['body'].split('\n')[0], 'Learned: lesson: widgets need a cache')

    def test_forward_moves_skip_no_lane_after_next_and_stop_on_hold(self):
        n = self.at('next')
        self.assertIn('skips in-progress', self.lane(n, 'in-review', ok=False))
        self.gh.issues[n]['labels'].append({'name': 'hold'})
        self.ready_in_progress(n)
        self.assertIn('carries hold', self.lane(n, 'in-progress', ok=False))

    def test_a_move_back_needs_reason_as_its_receipt(self):
        n = self.at('in-progress')
        self.assertIn('pass --reason', self.lane(n, 'next', ok=False))
        self.lane(n, 'next', '--reason', 'late NO from the outside reviewer')
        self.assertEqual(self.gh.lane(n), 'next')
        self.assertIn('Moved back: in-progress → next · late NO from the outside reviewer', self.gh.lines(n))

    def test_a_correction_is_read_in_place_of_the_wrong_receipt(self):
        n = self.at('in-review')
        self.gh.link_pr(n, NEW_HEAD)
        self.ready_release(n, HEAD)
        self.write_log(f'Correction: log.md · Reviewed was {HEAD[:7]} · is {NEW_HEAD[:7]}',
                       f'Correction: log.md · Reviewer was {HEAD[:7]} · is {NEW_HEAD[:7]}')
        self.lane(n, 'ready-to-release')

    def test_log_outside_the_working_directory_is_refused(self):
        outside = Path(tempfile.mkdtemp()) / 'log.md'
        outside.write_text('')
        n = self.at('in-progress')
        out = self.cli('lane', '--repo', REPO, str(n), 'in-review', '--log', str(outside), ok=False)
        self.assertIn('outside the working directory', out)
        self.assertEqual(self.gh.writes(), [])

    def test_missing_belt_labels_are_created_additively_and_every_line_matches_the_timeline(self):
        self.gh.labels = {'lane:inbox', 'other'}
        n = self.at('inbox')
        self.lane(n, 'backlog')
        self.assertEqual([a[2] for a in self.gh.writes() if a[:2] == ['label', 'create']], ['lane:backlog'])
        self.assertEqual(self.gh.labels, {'lane:inbox', 'other', 'lane:backlog'})
        line = self.gh.lines(n)[-1]
        self.assertRegex(line, TIMELINE)
        self.assertEqual(self.log.read_text().split('\n')[-2], line)

    def test_dry_run_prints_the_writes_and_changes_nothing(self):
        n = self.at('inbox')
        code, out, _ = run(self.gh, '--dry-run', 'lane', '--repo', REPO, str(n), 'backlog', '--log', str(self.log))
        self.assertEqual(code, 0)
        self.assertEqual(self.gh.writes(), [])
        self.assertIn('gh issue edit', out)
        self.assertEqual(self.log.read_text(), '# log\n')


class Capture(BeltCase):
    def test_capture_files_the_words_verbatim_in_the_inbox(self):
        out = self.cli('capture', '--repo', REPO, '--source', 'slack:C1/p2', '--tag', 'now', 'Widgets vanish\nafter reload')
        self.assertEqual(out.strip(), '#1')
        i = self.gh.issues[1]
        self.assertEqual(i['body'], 'Widgets vanish\nafter reload\n\nCaptured: 2026-11-18 12:00Z · source slack:C1/p2\n')
        self.assertEqual(self.gh.names(1), ['lane:inbox', 'prio:now'])
        self.assertEqual(self.gh.timeline(1)[0]['command'], 'capture')

    def test_same_text_within_ten_minutes_is_one_issue(self):
        self.cli('capture', '--repo', REPO, '--source', 'chat', 'Widgets vanish')
        self.t += timedelta(minutes=9)
        self.assertIn('#1 (same text', self.cli('capture', '--repo', REPO, '--source', 'chat', 'Widgets vanish'))
        self.t += timedelta(minutes=2)
        self.assertEqual(self.cli('capture', '--repo', REPO, '--source', 'chat', 'Widgets vanish').strip(), '#2')

    def test_prio_sets_one_label_and_drop_closes_as_not_planned(self):
        n = self.at('backlog', labels=('prio:later',))
        self.cli('prio', '--repo', REPO, str(n), 'now')
        self.assertEqual([x for x in self.gh.names(n) if x.startswith('prio:')], ['prio:now'])
        self.assertEqual(self.gh.timeline(n)[-1]['command'], 'prio')
        self.cli('prio', '--repo', REPO, str(n), 'drop')
        self.assertEqual(self.gh.issues[n]['state'], 'CLOSED')
        close = next(a for a in self.gh.writes() if a[:2] == ['issue', 'close'])
        self.assertEqual(close[close.index('--reason') + 1], 'not planned')


class Publish(BeltCase):
    def test_publish_sets_next_domain_owner_and_refuses_without_them(self):
        d = draft(items=None)
        for extra, says in ((('--domain', 'deploy'), '--owner'), (('--owner', 'thomas'), '--domain'),
                            (('--owner', 'thomas', '--domain', 'nope'), "not in the knowledge store")):
            out = self.cli('publish', '--repo', REPO, str(d), '--title', 'T', '--body-file', spec_body(), *extra, ok=False)
            self.assertIn(says, out)
        out = self.cli('publish', '--repo', REPO, str(d), '--title', 'T', '--body-file', spec_body('No check\n'),
                       '--owner', 'thomas', '--domain', 'deploy', '--session', 's1', ok=False)
        self.assertIn('Done when:', out)
        self.assertEqual(self.gh.writes(), [])
        self.cli('publish', '--repo', REPO, str(d), '--title', 'T', '--body-file', spec_body(),
                 '--owner', 'thomas', '--domain', 'deploy', '--session', 's1')
        self.assertEqual(sorted(self.gh.names(1)), ['domain:deploy', 'lane:next'])
        self.assertRegex(self.gh.lines(1)[0], CONVEYOR['receipts']['owner']['pattern'])
        self.assertEqual(self.gh.timeline(1)[-1]['command'], 'publish')

    def test_knowledge_none_has_no_domain_vocabulary(self):
        (self.root / 'CLAUDE.md').write_text('# p\n\n## Map\n- Knowledge: none\n')
        out = self.cli('publish', '--repo', REPO, str(draft(items=None)), '--title', 'T', '--body-file', spec_body(),
                       '--owner', 'thomas', '--domain', 'deploy', '--session', 's1', ok=False)
        self.assertIn('Knowledge: none', out)


class Spec5(BeltCase):
    """Build spec § 5 items 1, 2, 3, 7, 9 and the brief and decision parts of 8, as dry runs against the fake gh."""
    def test_1_and_2_one_issue_travels_next_to_closed_by_command_and_the_board_follows_it(self):
        self.cli('capture', '--repo', REPO, '--source', 'chat', 'Widgets vanish after reload')
        n = 1
        self.assertIn('inbox 1', self.board(self.sweep(), 'Lanes:'))
        self.ready_backlog(n)  # the sort pass adds labels; moves are commands only
        self.lane(n, 'backlog')
        self.assertIn('backlog 1', self.board(self.sweep(), 'Lanes:'))
        self.gh.issues[n]['body'] += 'Done when: a saved widget is still there after a reload\n'
        d = draft(plan=f'# Plan: widgets\nIssue: {REPO}#{n}\n', items=None)
        self.cli('publish', '--repo', REPO, str(d), '--owner', 'thomas', '--domain', 'deploy', '--session', 'coord-1')
        self.assertIn('next 1/8', self.board(self.sweep(), 'Lanes:'))
        self.cli('claim', '--repo', REPO, str(n), '--branch', 'feat/w', '--session', 'builder-1')
        self.cli('brief', '--repo', REPO, str(n))
        self.lane(n, 'in-progress')
        self.assertIn('in-progress 1/8', self.board(self.sweep(), 'Lanes:'))
        self.ready_in_review(n)
        self.lane(n, 'in-review')
        self.assertIn('in-review 1/4', self.board(self.sweep(), 'Lanes:'))
        self.ready_release(n)
        self.lane(n, 'ready-to-release')
        self.assertIn('ready-to-release 1/6', self.board(self.sweep(), 'Lanes:'))
        self.ready_monitoring()
        self.lane(n, 'monitoring')
        self.assertIn('monitoring 1', self.board(self.sweep(), 'Lanes:'))
        self.ready_closed()
        self.cli('close', '--repo', REPO, str(n), '--log', str(self.log), '--learned', 'none')
        moves = [(x['command'], x['from'], x['to']) for x in self.gh.timeline(n) if x['from'] != x['to']]
        self.assertEqual(moves, [('capture', '-', 'inbox'), ('lane', 'inbox', 'backlog'), ('publish', 'backlog', 'next'),
                                 ('lane', 'next', 'in-progress'), ('lane', 'in-progress', 'in-review'),
                                 ('lane', 'in-review', 'ready-to-release'), ('lane', 'ready-to-release', 'monitoring'),
                                 ('close', 'monitoring', 'closed')])
        lane_edits = [a for a in self.gh.writes() if a[:2] == ['issue', 'edit'] and 'lane:' in ' '.join(a)]
        self.assertEqual(len(lane_edits), 7)  # every move after capture's labelled create went through a command
        self.assertEqual(self.gh.issues[n]['state'], 'CLOSED')

    def test_2_three_forced_faults_each_show_as_a_board_line(self):
        stale = self.at('ready-to-release')
        self.gh.link_pr(stale, HEAD)
        self.gh.comment(stale, f'Conveyor: 2026-11-18 11:00Z · lane · in-review → ready-to-release · head {HEAD} · tests - · skills {"f" * 7} · schedules -')
        self.gh.prs[500 + stale] = NEW_HEAD  # a push after review
        for _ in range(5):
            self.at('in-review')
        unmonitored = self.at('monitoring')
        self.gh.comment(unmonitored, f'Conveyor: 2026-11-18 11:00Z · lane · ready-to-release → monitoring · head - · tests - · skills {"f" * 7} · schedules -')
        out = self.sweep()
        self.assertIn(f'- stale head: #{stale} reviewed {HEAD}, PR head {NEW_HEAD[:12]}', out)
        self.assertIn('- lane over limit: in-review 5 of 4', out)
        self.assertIn(f'- monitoring without two schedules: #{unmonitored}', out)

    def test_3_rerunning_a_station_from_the_issue_alone_reproduces_its_receipt(self):
        n = self.at('next')
        first = self.cli('brief', '--repo', REPO, str(n))
        second = self.cli('brief', '--repo', REPO, str(n))
        self.assertEqual(first, second)
        a, b = self.gh.timeline(n)[-2:]
        self.assertEqual(a[0], b[0])

    def test_7_offline_capture_is_filed_by_the_next_sweep(self):
        self.gh.offline = True
        self.assertIn('spooled', self.cli('capture', '--repo', REPO, '--source', 'chat', 'Widgets vanish'))
        self.assertIn('spooled already', self.cli('capture', '--repo', REPO, '--source', 'chat', 'Widgets vanish'))
        self.assertEqual(self.gh.issues, {})
        self.gh.offline = False
        self.t += timedelta(minutes=20)
        out = self.sweep()
        self.assertIn('- filed spooled capture #1', out)
        self.assertIn('Captured: 2026-11-18 12:00Z · source chat', self.gh.issues[1]['body'])
        self.assertEqual((self.root / 'spool.jsonl').read_text(), '')

    def test_7_an_unflushed_spool_over_fifteen_minutes_is_a_board_line(self):
        self.gh.offline = True
        self.cli('capture', '--repo', REPO, '--source', 'chat', 'Widgets vanish')
        self.gh.offline = False
        with unittest.mock.patch.object(issues_cli, 'capture', side_effect=subprocess.CalledProcessError(
                1, 'gh', stderr='error connecting to api.github.com')):
            self.t += timedelta(minutes=16)
            self.assertIn('- spool over 15 min: 1 capture(s) not yet filed', self.sweep())

    def test_7_a_now_item_enters_ahead_of_older_later_items(self):
        for _ in range(7):
            self.at('in-progress')
        older = [self.at('backlog', labels=('prio:later',)) for _ in range(2)]
        for n in older:
            self.gh.issues[n]['createdAt'] = iso(T0 - timedelta(days=3))
        urgent = self.at('backlog', labels=('prio:now',))
        for n in older + [urgent]:
            self.ready_next(n)
        out = self.sweep()
        self.assertIn(f'- pulled #{urgent} to next', out)
        self.assertEqual(self.gh.lane(urgent), 'next')
        self.assertEqual([self.gh.lane(n) for n in older], ['backlog', 'backlog'])
        self.assertEqual(self.gh.timeline(urgent)[-1]['command'], 'sweep')

    def test_7_ten_inputs_with_every_slot_full_all_become_issues_and_start_nothing(self):
        for _ in range(8):
            self.at('in-progress')
        numbers = [self.cli('capture', '--repo', REPO, '--source', 'chat', f'idea {k}').strip() for k in range(10)]
        self.assertEqual(numbers, [f'#{k}' for k in range(9, 19)])
        self.sweep()
        self.assertEqual(self.started, [])
        self.assertEqual([self.gh.lane(k) for k in range(9, 19)], ['inbox'] * 10)

    def test_8_brief_lists_the_domain_pages_and_decide_writes_a_decision_row(self):
        n = self.at('next')
        out = self.cli('brief', '--repo', REPO, str(n))
        self.assertIn('- wiki:pages/release.md · verified 2026-11-02 @ abc1234', out)
        self.cli('decide', '--repo', REPO, str(n), 'Keep the grey colour', '--question', Q, '--session', 'coord-1')
        self.assertIn(f'Decision: Keep the grey colour · 2026-11-18 12:00Z · question {Q} · session coord-1', self.gh.lines(n))
        self.assertEqual(self.k['record'], [('decision', f'r-{n}-202611181200', '2026-11-18', Q, 'Keep the grey colour', 'repo:r')])
        self.assertIn('- Decision: Keep the grey colour', self.cli('brief', '--repo', REPO, str(n)))
        self.assertIn('decide needs --question', self.cli('decide', '--repo', REPO, str(n), 'x', '--question', 'nope', ok=False))

    def test_8_closing_without_learned_is_refused_and_the_sweep_logs_each_closed_issue_once(self):
        n = self.at('monitoring')
        self.ready_monitoring()
        self.ready_closed()
        self.assertIn('learned', self.lane(n, 'closed', ok=False))
        self.cli('close', '--repo', REPO, str(n), '--log', str(self.log), '--learned', 'none')
        self.assertIn(f'- knowledge log #{n}: log/2026-11.md', self.sweep())
        self.sweep()
        self.assertEqual([issue for issue, _ in self.k['log']], [n])
        self.assertTrue(all(TIMELINE.match(line) for line in self.k['log'][0][1]))

    def go_card(self, n, *extra, ok=True):
        record = self.root / 'action.json'
        record.write_text(json.dumps({'kind': 'release', 'id': 'r-7', 'digest': 'c' * 64, 'rollback': {'local': '0123abc'}}))
        return self.cli('ask', '--repo', REPO, str(n), '--kind', 'go', '--record', 'action.json', '--log', str(self.log), *extra, ok=ok)

    def test_9_a_go_card_is_refused_until_every_field_is_filled(self):
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        self.ready_in_review(n)
        self.ready_release(n)
        self.assertIn('empty changes, if_yes, if_no, if_wait, recommended', self.go_card(n, ok=False))
        full = ('--changes', 'Saved widgets survive a reload for every user', '--if-yes', 'Release 7 ships tonight',
                '--if-no', 'Widgets keep vanishing', '--if-wait', 'Nothing changes until tomorrow', '--recommended', 'Yes')
        self.assertIn('opens with a PR number', self.go_card(n, *full[:-1], '#12 first', ok=False))
        self.assertIn('the script fills undo', self.go_card(n, *full, '--undo', 'mine', ok=False))
        card = self.go_card(n, *full).strip().split('\n')
        self.assertEqual(card[0], f'Go: release r-7 · digest {"c" * 8}')
        self.assertEqual(card[1], 'Goal: Widget · step 6 of 8')
        self.assertEqual(card[2], 'From: Fix widgets')
        self.assertIn('Undo: local: 0123abc', card)
        self.assertIn('Checked: capture, domain, size, owner, done_when, claim, brief, implement_done, pr, reviewed_yes, reviewer · Not yet: none', card)
        self.assertLessEqual(len(card), 12)

    def test_9_a_removed_receipt_is_listed_under_not_yet(self):
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        self.ready_release(n)  # implement: done was never logged
        card = self.cli('ask', '--repo', REPO, str(n), '--kind', 'choice', '--log', str(self.log), '--changes', 'c',
                        '--if-yes', 'y', '--if-no', 'n', '--if-wait', 'w', '--undo', 'revert', '--recommended', 'Yes')
        self.assertIn('Not yet: implement_done', card)

    def test_9_tell_me_more_is_logged_and_leaves_the_question_waiting(self):
        n = self.at('in-review')
        self.assertIn(f'- #{n} Widget (in-review)', self.sweep())  # Coming to you next before any question
        self.assertIn('Need from you: 0', self.sweep())  # owner and monitor bookkeeping ask nothing
        self.cli('ask', '--repo', REPO, str(n), '--kind', 'choice', '--changes', 'c', '--if-yes', 'y', '--if-no', 'n',
                 '--if-wait', 'w', '--undo', 'revert', '--recommended', 'Yes')
        self.t += timedelta(minutes=1)
        self.cli('ask', '--repo', REPO, str(n), '--more', Q)
        self.assertIn(f'Asked for more: 2026-11-18 12:01Z · question {Q}', self.gh.lines(n))
        self.assertFalse(any(line.startswith('Decision:') for line in self.gh.lines(n)))
        out = self.sweep()
        self.assertIn('Need from you: 1', out)
        self.assertIn(f'- #{n} Widget (asked 2026-11-18 12:01Z)', out)
        self.t += timedelta(minutes=1)
        self.cli('decide', '--repo', REPO, str(n), 'Yes', '--question', Q, '--session', 'coord-1')
        self.assertIn('Need from you: 0', self.sweep())


class Sweep(BeltCase):
    def test_board_lines(self):
        self.at('inbox', labels=('prio:now',))
        self.gh.issues[1]['body'] = 'old\n\nCaptured: 2026-11-17 10:00Z · source chat\n'
        self.at('backlog', labels=('prio:now',))
        self.at('backlog', labels=('prio:later',))
        self.gh.issues[3]['body'] = 'no spec\n'  # cannot be pulled: no Done when
        self.gh.issues[2]['comments'] = []  # cannot be pulled: no Owner
        out = self.sweep()
        self.assertIn('Backlog: 2 (now 1 · next 0 · later 1) · oldest unsorted 26h', out)
        self.assertIn('- inbox unsorted over 24 h: #1', out)
        self.assertIn('- pull refused: #2 cannot enter next; missing: owner', out)
        self.assertIn('- pull refused: #3 cannot enter next; missing: owner (issue comment `Owner:`); done_when', out)  # a refusal does not end the pull
        self.assertIn('Not read: sessions, test slots, denial log', out)

    def test_review_fallback_starts_one_reviewer_after_the_window(self):
        n = self.at('in-review')
        self.gh.link_pr(n)
        self.gh.comment(n, f'Review requested: head {HEAD[:7]} · 2026-11-18 10:30Z · session coord-1')
        self.assertNotIn('review past fallback', self.sweep())
        self.t += timedelta(minutes=31)
        out = self.sweep()
        self.assertIn(f'- review past fallback: #{n} head {HEAD[:7]}', out)
        self.assertIn(f'- fallback reviewer started for #{n} at {HEAD[:7]}', out)
        self.sweep()
        self.assertEqual(self.started, [(REPO, n, HEAD[:7], f'https://github.com/{REPO}/pull/{500 + n}')])

    def test_weekly_adds_the_backlog_age_question_and_counts(self):
        old = self.at('backlog')
        self.gh.issues[old]['createdAt'] = iso(T0 - timedelta(days=31))
        self.gh.issues[old]['comments'] = []  # stays in backlog
        out = self.sweep('--weekly')
        self.assertIn(f'- Weekly: keep, drop or bump? #{old} (backlog over 30 days)', out)
        self.assertIn('Questions (7 days): asked 0 (0.0/day) · decided 0 · tell me more 0', out)
        self.assertIn('Knowledge digest: brain: not configured on this machine', out)


class Knowledge(BeltCase):
    """T1-a3: the module is imported on use and an unmapped brain follows conveyor.md § Knowledge."""
    def test_importing_issues_cli_does_not_import_knowledge(self):
        code = 'import sys, agent_skills.issues_cli; print("agent_skills.knowledge" in sys.modules)'
        out = subprocess.run([sys.executable, '-c', code], cwd=Path(issues_cli.__file__).parents[1],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), 'False')

    def test_unmapped_brain_reads_say_so_and_writes_refuse(self):
        self.k = stub_knowledge(self, notice='brain: not configured on this machine')
        n = self.at('next')
        self.assertIn('brain: not configured on this machine', self.cli('brief', '--repo', REPO, str(n)))
        out = self.cli('decide', '--repo', REPO, str(n), 'Yes', '--question', Q, '--session', 'c', ok=False)
        self.assertIn('brain: not configured on this machine', out)
        self.assertFalse(any(line.startswith('Decision:') for line in self.gh.lines(n)))
        m = self.at('monitoring')
        self.ready_monitoring()
        self.ready_closed()
        self.cli('close', '--repo', REPO, str(m), '--log', str(self.log), '--learned', 'none')
        self.assertIn(f'- knowledge log refused for #{m}: brain: not configured on this machine', self.sweep())

    def test_the_stores_come_from_the_project_map(self):
        self.cli('brief', '--repo', REPO, str(self.at('next')))
        self.assertEqual(self.k['open'], [('acme/brain', str(self.root / 'wiki'))])

    def test_no_knowledge_line_is_refused(self):
        (self.root / 'CLAUDE.md').write_text('# p\n\n## Map\n')
        self.assertIn('no `Knowledge:` line', self.cli('brief', '--repo', REPO, str(self.at('next')), ok=False))


class Limits(BeltCase):
    defaults = '- Lane limits: Build 2 · Review 1 · Release 1 train of ≤6 PRs · Sessions 10\n- Review fallback: 1 hour\n'

    def test_project_defaults_override_the_lane_limits(self):
        n = self.at('in-progress')
        self.gh.link_pr(n)
        self.ready_in_review(n)
        self.at('in-review')
        self.assertIn('limit (Review 1 of 1)', self.lane(n, 'in-review', ok=False))


if __name__ == '__main__':
    unittest.main()
