"""issues-cli belt commands (conveyor.md) against a fake gh that keeps GitHub's state in memory."""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_skills import issues_cli, layout
from test_issues_cli import KNOWLEDGE, REPO, belt_project, draft, real_knowledge, run, spec_body, stub_knowledge

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
CONVEYOR = json.loads((Path(__file__).resolve().parents[1] / 'skills/workflow-contracts/conveyor.json').read_text())
TIMELINE = re.compile(CONVEYOR['timeline']['pattern'])
CHECKPOINT = re.compile(CONVEYOR['resume']['checkpoint']['pattern'])
HEAD, NEW_HEAD = 'a1b2c3d' + '0' * 33, 'e4f5a6b' + '0' * 33
Q = 'https://github.com/o/r/issues/1#issuecomment-9'
COORD = 'local_c0000000-0000-4000-8000-000000000001'  # desktop sessions carry local_
OWNER2 = 'local_c0000000-0000-4000-8000-000000000002'
BUILDER = 'b0000000-0000-4000-8000-000000000001'  # headless workers are plain uuids
REVIEWER, REVIEWER2 = 'e0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000002'
RELEASE_OWNER = 'local_d0000000-0000-4000-8000-000000000001'
SHORT = ("Approve the new wording for failed care texts? Staff will see 'Not delivered' instead of 'Failed to send', and "
         "the extra notice only when the number was never reached. Tests passed; nothing goes live until the next "
         "release. Before and after: https://x.test/p/1")
CHANGE = {'store': 'brain', 'sha': 'f' * 40, 'path': 'decisions.md', 'summary': 'record colour decision',
          'at': '2026-11-17T09:00:00Z'}


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
            self.issues[int(args[2])]['reason'] = self.opt(args, '--reason')
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
        if args[:2] == ['repo', 'view']:
            return REPO + '\n'
        raise AssertionError(f'unexpected gh call {args}')


class BeltCase(unittest.TestCase):
    defaults = ''

    def setUp(self):
        self.root = belt_project(self, defaults=self.defaults)
        self.config = {'capture_spool': str(self.root / 'spool.jsonl')}
        self.configure()
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

    def configure(self, **extra):
        self.config.update(extra)
        (self.root / 'workers.json').write_text(json.dumps(self.config))

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
        self.gh.issues[n]['labels'] += [{'name': 'domain:deploy'}, {'name': 'kind:bug'}, {'name': 'size:S'}]

    def ready_next(self, n):
        self.gh.comment(n, f'Owner: thomas · session {COORD} · 2026-11-18 11:00Z')

    def ready_in_progress(self, n):
        self.gh.comment(n, f'Claimed: branch `feat/w` · session {BUILDER}')
        self.cli('brief', '--repo', REPO, str(n))

    def ready_in_review(self, n, head=HEAD):
        self.write_log('## 2026-11-18 12:00Z — implement: done')
        self.gh.link_pr(n, head)

    def ready_release(self, n, head=HEAD):
        self.write_log(f'Reviewed: {head[:7]} YES', f'Reviewer: session {REVIEWER} · head {head[:7]} · outside')

    def ready_monitoring(self, n=None):
        """The monitoring receipts in the log (lane copies them), or already on issue `n` (it entered monitoring)."""
        (self.write_log if n is None else lambda *lines: self.gh.comment(n, '\n'.join(lines)))(f'Approved: release r-1 · digest {"d" * 64} · 2026-11-18 12:00Z · question {Q} · session {COORD}',
                       '## 2026-11-18 12:05Z — deploy: a1b2c3d to local', 'Rollback: local: 0123abc',
                       'Scheduler: claude monitor-r-first', 'Scheduler: claude monitor-r-24h')

    def ready_closed(self):
        self.write_log('Monitor verdict: first-traffic All working · 2026-11-18 13:00Z',
                       'Monitor verdict: 24h All working · 2026-11-19 12:00Z',
                       'Scheduler deleted: claude monitor-r-first', 'Scheduler deleted: claude monitor-r-24h')

    def at(self, lane, labels=()):
        """An issue already in `lane` with every earlier receipt present."""
        n = self.gh.add(lane=lane, labels=('domain:deploy', 'kind:bug', 'size:S', *labels),
                        body='Fix widgets\n\nCaptured: 2026-11-18 11:00Z · source chat\nDone when: it works\n')
        order = issues_cli.lanes()
        if order.index(lane) >= order.index('next'):
            self.ready_next(n)
        if order.index(lane) >= order.index('in-progress'):
            self.gh.comment(n, f'Claimed: branch `feat/w` · session {BUILDER}')
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

    def test_backlog_needs_one_domain_one_kind_and_one_size_label(self):
        n = self.at('inbox')
        self.gh.issues[n]['labels'] = [{'name': 'lane:inbox'}]
        out = self.lane(n, 'backlog', ok=False)
        for name in ('domain (label)', 'kind (label)', 'size (label)'):
            self.assertIn(name, out)
        self.gh.issues[n]['labels'] += [{'name': 'domain:deploy'}, {'name': 'size:S'}]
        out = self.lane(n, 'backlog', ok=False)
        self.assertEqual(out.strip().rsplit('missing: ', 1)[1], 'kind (label)')
        self.gh.issues[n]['labels'].append({'name': 'kind:bug'})
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
        self.assertIn('implement_done (issue comment)', out)
        self.assertIn('pr (linked PR)', out)
        self.ready_in_review(n)
        self.lane(n, 'in-review')

    def test_ready_to_release_needs_yes_and_a_different_reviewer_on_the_current_head(self):
        n = self.at('in-review')
        self.gh.link_pr(n, NEW_HEAD)
        self.ready_release(n, HEAD)  # reviewed an older head
        out = self.lane(n, 'ready-to-release', ok=False)
        self.assertIn('reviewed_yes (issue comment `Reviewed:`)', out)
        self.assertIn('reviewer (issue comment `Reviewer:`)', out)
        self.write_log(f'Reviewed: {NEW_HEAD[:7]} YES', f'Reviewer: session {BUILDER} · head {NEW_HEAD[:7]} · fallback')
        out = self.lane(n, 'ready-to-release', ok=False)
        self.assertNotIn('reviewed_yes', out)
        self.assertIn('reviewer (issue comment `Reviewer:`)', out)  # the builder may not review its own work
        self.write_log(f'Reviewer: session {REVIEWER2} · head {NEW_HEAD[:7]} · fallback')
        self.lane(n, 'ready-to-release')
        self.assertEqual(self.gh.timeline(n)[-1]['head'], NEW_HEAD)

    def test_monitoring_needs_approved_landed_rollback_and_two_schedules(self):
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        out = self.lane(n, 'monitoring', ok=False)
        for name in ('approved', 'landed (deploy (issue comment `deploy:`))', 'rollback', 'schedule'):
            self.assertIn(name, out)
        self.write_log(f'Approved: release r-1 · digest {"d" * 64} · 2026-11-18 12:00Z · question {Q} · session {COORD}',
                       '## 2026-11-18 12:05Z — deploy: a1b2c3d to local', 'Rollback: local: 0123abc',
                       'Scheduler: claude monitor-r-first')
        self.assertIn('schedule (issue comment `Scheduler:`)', self.lane(n, 'monitoring', ok=False))
        self.write_log('Scheduler: claude monitor-r-24h')
        self.lane(n, 'monitoring')
        self.assertEqual(self.gh.timeline(n)[-1]['schedules'], 'monitor-r-24h,monitor-r-first')

    def test_pushed_lands_an_item_only_when_every_deploy_target_is_a_branch(self):
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        self.write_log(f'Approved: release r-1 · digest {"d" * 64} · 2026-11-18 12:00Z · question {Q} · session {COORD}',
                       f'Pushed: {HEAD[:7]} to main', 'Rollback: main: 0123abc',
                       'Scheduler: claude monitor-r-first', 'Scheduler: claude monitor-r-24h')
        claude = (self.root / 'CLAUDE.md').read_text()
        (self.root / 'CLAUDE.md').write_text(claude + '\n## Deploy\n- Targets: box — kind `deploy` — ship — check\n')
        out = self.lane(n, 'monitoring', ok=False)
        self.assertIn('landed (deploy (issue comment `deploy:`))', out)  # Pushed: is not offered here
        (self.root / 'CLAUDE.md').write_text(claude + '\n## Deploy\n- Targets: none (the pipeline ends at the merge)\n')
        self.lane(n, 'monitoring')
        self.assertEqual(self.gh.lane(n), 'monitoring')

    def test_pushed_lands_an_item_when_every_named_target_is_a_branch(self):
        """Fix2 item 3: not only `none`; branch targets alone (one line or one per line) let Pushed: land it."""
        claude = (self.root / 'CLAUDE.md').read_text()
        branch, box = 'main — kind `branch` — git push — ls-remote shows the head', 'box — kind `deploy` — ship — check'
        for targets, lands in ((branch, True), (f'\n  - {branch}\n  - release — kind `branch` — push — check', True),
                               (f'{branch} · {box}', False), (f'\n  - {branch}\n  - {box}', False), ('main', False)):
            (self.root / 'CLAUDE.md').write_text(f'{claude}\n## Deploy\n- Targets: {targets}\n')
            self.assertIs(issues_cli.branch_targets_only(), lands, targets)
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        self.write_log(f'Approved: release r-1 · digest {"d" * 64} · 2026-11-18 12:00Z · question {Q} · session {COORD}',
                       f'Pushed: {HEAD[:7]} to main', 'Rollback: main: 0123abc',
                       'Scheduler: claude monitor-r-first', 'Scheduler: claude monitor-r-24h')
        (self.root / 'CLAUDE.md').write_text(f'{claude}\n## Deploy\n- Targets: {branch}\n')
        self.lane(n, 'monitoring')
        self.assertEqual(self.gh.lane(n), 'monitoring')

    def test_a_later_rolled_back_line_undoes_landed_until_a_newer_push(self):
        """Fix2 item 3, rechecked in fix3 item 4 against main: receipts.landed.undone_by and the rolled_back receipt."""
        self.assertIn('Rolled back:', CONVEYOR['receipts']['landed']['undone_by'])
        self.assertRegex(f'Rolled back: {HEAD[:7]} to main', CONVEYOR['receipts']['rolled_back']['pattern'])
        claude = (self.root / 'CLAUDE.md').read_text()
        (self.root / 'CLAUDE.md').write_text(claude + '\n## Deploy\n- Targets: none (the pipeline ends at the merge)\n')
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        self.gh.comment(n, f'Pushed: {HEAD[:7]} to main')
        self.gh.comment(n, f'Rolled back: {HEAD[:7]} to main')
        self.write_log(f'Approved: release r-1 · digest {"d" * 64} · 2026-11-18 12:00Z · question {Q} · session {COORD}',
                       'Rollback: main: 0123abc', 'Scheduler: claude monitor-r-first', 'Scheduler: claude monitor-r-24h')
        self.assertIn('landed (deploy (issue comment `deploy:`) or pushed (issue comment `Pushed:`))',
                      self.lane(n, 'monitoring', ok=False))
        self.write_log(f'Pushed: {NEW_HEAD[:7]} to main')
        self.lane(n, 'monitoring')
        self.assertEqual(self.gh.lane(n), 'monitoring')

    def test_closed_needs_both_verdicts_both_deletions_and_learned(self):
        n = self.at('monitoring')
        self.ready_monitoring(n)
        self.write_log('Monitor verdict: first-traffic All working · 2026-11-18 13:00Z', 'Scheduler deleted: claude monitor-r-first')
        out = self.cli('close', '--repo', REPO, str(n), '--log', str(self.log), '--learned', 'none', ok=False)
        self.assertIn('monitor_24h', out)
        self.assertIn('monitor_deleted', out)
        self.assertNotIn('learned', out)
        self.write_log('Monitor verdict: 24h All working · 2026-11-19 12:00Z', 'Scheduler deleted: claude monitor-r-24h')
        self.assertIn('close needs --learned', self.cli('close', '--repo', REPO, str(n), ok=False))
        self.assertIn('learned (issue comment `Learned:`)', self.lane(n, 'closed', '--learned', 'maybe', ok=False))
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


class ReleaseId(BeltCase):
    """Fix 1 (C3 A1): the release id comes from agent_skills.layout, and every receipt line is built before the first write."""
    def release(self, pin):
        root = Path(tempfile.mkdtemp())
        if pin:
            (root / '.release-pin.json').write_text(json.dumps({'commit': pin, 'tree': 'b' * 40}))
        return unittest.mock.patch.object(layout, 'release_id', side_effect=lambda: REAL_RELEASE_ID(root))

    def test_an_installed_release_stamps_its_pin_without_git(self):
        n = self.at('inbox')
        with self.release('c' * 40):
            self.lane(n, 'backlog')
        self.assertEqual(self.gh.timeline(n)[-1]['skills'], 'c' * 40)

    def test_no_release_id_moves_nothing_and_writes_nothing(self):
        n = self.at('inbox')
        with self.release(None):  # neither a pin nor a git checkout
            out = self.lane(n, 'backlog', ok=False)
        self.assertIn('no release pin and not a git checkout', out)
        self.assertEqual(self.gh.writes(), [])
        self.assertEqual(self.gh.lane(n), 'inbox')
        with self.release(None):
            for argv in (('prio', '--repo', REPO, str(n), 'now'), ('capture', '--repo', REPO, '--source', 'chat', 'x'),
                         ('close', '--repo', REPO, str(n), '--learned', 'none', '--no-release', 'chore', '--why', 'done')):
                self.cli(*argv, ok=False)
        self.assertEqual(self.gh.writes(), [])

    def test_no_git_and_no_computed_contract_path_in_issues_cli(self):
        source = Path(issues_cli.__file__).read_text()
        for banned in ("'git'", 'rev-parse', '__file__', 'parents[1]'):
            self.assertNotIn(banned, source)


REAL_RELEASE_ID = layout.release_id


class ReceiptHome(BeltCase):
    """Fix 2 (C3 A2): gates read receipts from the issue only; `lane --log` copies the stage's lines there first."""
    def test_a_receipt_only_in_the_log_does_not_count(self):
        n = self.at('in-progress')
        self.gh.link_pr(n)
        self.write_log('## 2026-11-18 12:00Z — implement: done')
        self.assertIn('implement_done', self.cli('lane', '--repo', REPO, str(n), 'in-review', ok=False))
        self.assertEqual(self.gh.writes(), [])

    def test_lane_log_copies_the_stage_lines_as_one_comment_then_checks(self):
        n = self.at('in-review')
        self.gh.link_pr(n)
        self.write_log('## 2026-11-18 12:00Z — implement: done', 'some other note', f'Reviewed: {HEAD[:7]} YES',
                       f'Reviewer: session {REVIEWER} · head {HEAD[:7]} · outside', 'Rollback: local: 0123abc')
        before = len(self.gh.issues[n]['comments'])
        self.lane(n, 'ready-to-release')
        added = [c['body'] for c in self.gh.issues[n]['comments'][before:]]
        self.assertEqual(added[0], f'Reviewed: {HEAD[:7]} YES\nReviewer: session {REVIEWER} · head {HEAD[:7]} · outside')
        self.assertRegex(added[1], TIMELINE)
        self.assertEqual(len(added), 2)

    def test_a_refused_gate_copies_nothing_and_a_rerun_copies_nothing_twice(self):
        n = self.at('in-review')
        self.gh.link_pr(n)
        self.write_log(f'Reviewed: {HEAD[:7]} YES')
        self.lane(n, 'ready-to-release', ok=False)  # no Reviewer: yet
        self.assertEqual(self.gh.writes(), [])
        self.write_log(f'Reviewer: session {REVIEWER} · head {HEAD[:7]} · outside')
        self.lane(n, 'ready-to-release')
        self.lane(n, 'in-review', '--reason', 'pushed again')
        self.lane(n, 'ready-to-release')
        copies = [c['body'] for c in self.gh.issues[n]['comments'] if c['body'].startswith('Reviewed:')]
        self.assertEqual(len(copies), 1)

    def test_ask_reads_the_issue_not_the_log(self):
        n = self.at('in-review')
        self.gh.link_pr(n)
        self.write_log('## 2026-11-18 12:00Z — implement: done')
        self.cli('ask', '--repo', REPO, str(n), '--kind', 'choice', '--log', str(self.log), '--changes', 'c',
                 '--if-yes', 'y', '--if-no', 'n', '--if-wait', 'w', '--undo', 'revert', '--recommended', 'Yes', '--short', SHORT)
        self.assertIn('Not yet: build finished', self.gh.issues[n]['comments'][-1]['body'])


class NoRelease(BeltCase):
    """Fix 3 (C3 A5): an item with nothing to release closes from any lane with `No release:` and `Learned:`."""
    def close(self, n, *extra, ok=True):
        return self.cli('close', '--repo', REPO, str(n), '--learned', 'answered: colour? => grey', *extra, ok=ok)

    def test_an_answered_question_closes_from_backlog(self):
        n = self.at('backlog')
        self.close(n, '--no-release', 'answered', '--why', 'the user chose grey')
        self.assertEqual(self.gh.issues[n]['state'], 'CLOSED')
        self.assertEqual(self.gh.issues[n]['reason'], 'completed')
        body = self.gh.issues[n]['comments'][-1]['body'].split('\n')
        self.assertEqual(body[:2], ['No release: answered · the user chose grey', 'Learned: answered: colour? => grey'])
        self.assertEqual((self.gh.timeline(n)[-1]['command'], self.gh.timeline(n)[-1]['from']), ('close', 'backlog'))
        self.assertEqual(self.gh.lane(n), 'closed')

    def test_a_duplicate_closes_as_not_planned(self):
        n = self.at('inbox')
        self.close(n, '--no-release', 'duplicate', '--why', 'same as the first')
        self.assertEqual(self.gh.issues[n]['reason'], 'not planned')

    def test_refused_once_anything_landed(self):
        for line in (f'Pushed: {HEAD[:7]} to main', '## 2026-11-18 12:05Z — deploy: a1b2c3d to local'):
            n = self.at('ready-to-release')
            self.gh.comment(n, line)
            out = self.close(n, '--no-release', 'chore', '--why', 'nothing to ship', ok=False)
            self.assertIn('only the monitored path closes a landed item', out)
        self.assertEqual(self.gh.writes(), [])

    def test_needs_why_and_a_valid_learned(self):
        n = self.at('backlog')
        self.assertIn('--why', self.close(n, '--no-release', 'chore', ok=False))
        out = self.cli('close', '--repo', REPO, str(n), '--learned', 'maybe', '--no-release', 'chore', '--why', 'x', ok=False)
        self.assertIn('learned (issue comment `Learned:`)', out)
        self.assertEqual(self.gh.writes(), [])


class Spec5(BeltCase):
    """Build spec § 5 items 1, 2, 3, 7, 9 and the brief and decision parts of 8, as dry runs against the fake gh."""
    def test_1_and_2_one_issue_travels_next_to_closed_by_command_and_the_board_follows_it(self):
        self.cli('capture', '--repo', REPO, '--source', 'chat', 'Widgets vanish after reload')
        n = 1
        self.assertIn('inbox 1', self.board(self.sweep(), 'Lanes:'))
        self.ready_backlog(n)  # the sort pass adds labels; moves are commands only
        self.lane(n, 'backlog')
        self.assertIn('backlog 1', self.board(self.sweep(), 'Lanes:'))
        self.assertEqual(self.board(self.sweep(), 'Pull next:'), f'Pull next: #{n} (publish moves them)')
        self.assertEqual(self.gh.lane(n), 'backlog')  # the sweep names it and never moves it
        self.gh.issues[n]['body'] += 'Done when: a saved widget is still there after a reload\n'
        d = draft(plan=f'# Plan: widgets\nIssue: {REPO}#{n}\n', items=None)
        self.cli('publish', '--repo', REPO, str(d), '--owner', 'thomas', '--domain', 'deploy', '--session', COORD)
        self.assertIn('next 1/8', self.board(self.sweep(), 'Lanes:'))
        self.cli('claim', '--repo', REPO, str(n), '--branch', 'feat/w', '--session', BUILDER)
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

    def test_7_a_now_item_is_named_ahead_of_older_later_items_and_nothing_moves(self):
        for _ in range(7):
            self.at('in-progress')
        older = [self.at('backlog', labels=('prio:later',)) for _ in range(2)]
        for n in older:
            self.gh.issues[n]['createdAt'] = iso(T0 - timedelta(days=3))
        urgent = self.at('backlog', labels=('prio:now',))
        out = self.sweep()
        self.assertEqual(self.board(out, 'Pull next:'), f'Pull next: #{urgent} (publish moves them)')  # one free slot
        self.assertEqual([self.gh.lane(n) for n in older + [urgent]], ['backlog'] * 3)
        self.assertEqual([a for a in self.gh.writes() if a[:2] == ['issue', 'edit']], [])

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
        self.cli('decide', '--repo', REPO, str(n), 'Keep the grey colour', '--question', Q, '--session', COORD)
        self.assertIn(f'Decision: Keep the grey colour · 2026-11-18 12:00Z · question {Q} · session {COORD}', self.gh.lines(n))
        self.assertEqual(self.k['record'], [('decision', f'r-{n}-202611181200', '2026-11-18', Q, 'Keep the grey colour', 'repo:r')])
        self.assertIn('- Decision: Keep the grey colour', self.cli('brief', '--repo', REPO, str(n)))
        self.assertIn('decide needs --question', self.cli('decide', '--repo', REPO, str(n), 'x', '--question', 'nope', ok=False))

    def test_8_closing_without_learned_is_refused_and_the_sweep_logs_each_closed_issue_once(self):
        n = self.at('monitoring')
        self.ready_monitoring(n)
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
        self.gh.comment(n, '## 2026-11-18 12:00Z — implement: done')
        self.gh.comment(n, f'Reviewed: {HEAD[:7]} YES\nReviewer: session {REVIEWER} · head {HEAD[:7]} · outside')
        self.assertIn('empty changes, if_yes, if_no, if_wait, recommended', self.go_card(n, '--short', SHORT, ok=False))
        full = ('--short', SHORT, '--changes', 'Saved widgets survive a reload for every user', '--if-yes',
                'Release 7 ships tonight', '--if-no', 'Widgets keep vanishing', '--if-wait', 'Nothing changes until tomorrow',
                '--recommended', 'Yes')
        self.assertIn('opens with a PR number', self.go_card(n, *full[:-1], '#12 first', ok=False))
        self.assertIn('the script fills undo', self.go_card(n, *full, '--undo', 'mine', ok=False))
        self.assertIn("'Changes: We deploy: a1b2c3d to prod' reads as a receipt",
                      self.go_card(n, *full[:3], 'We deploy: a1b2c3d to prod', *full[4:], ok=False))
        self.assertEqual(self.gh.writes(), [])
        self.assertEqual(self.go_card(n, *full).strip(), SHORT)  # the short form is all ask prints
        card = self.gh.issues[n]['comments'][-1]['body'].split('\n')  # the detail is the record, on the issue
        self.assertEqual(card[0], f'Go: release r-7 · digest {"c" * 8}')
        self.assertEqual(card[1], 'Goal: Widget · step 6 of 8')
        self.assertEqual(card[2], 'From: Fix widgets')
        self.assertIn('Undo: local: 0123abc', card)
        self.assertIn('Checked: captured, domain label, kind label, size label, owner set, done-when written, claimed, '
                      'brief rendered, build finished, pull request linked, review passed on this head, '
                      'independent reviewer · Not yet: none', card)
        self.assertEqual([x.split(':')[0] for x in card[1:11]], [issues_cli.CARD_LABELS[k] for k in CONVEYOR['card']['detail']['fields']])
        self.assertTrue(TIMELINE.match(card[11]))
        self.assertLessEqual(len(card) - 1, CONVEYOR['card']['detail']['max_lines'])

    def test_9_a_go_shows_its_kind_id_and_digest_only_in_the_detail(self):
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        full = ('--changes', 'c', '--if-yes', 'y', '--if-no', 'n', '--if-wait', 'w', '--recommended', 'Yes')
        for leak in ('r-7', 'c' * 8):
            short = SHORT.replace('Tests passed', f'Tests passed for {leak}')
            self.assertIn(f'short card refused: {leak}', self.go_card(n, '--short', short, *full, ok=False))
        self.assertEqual(self.gh.writes(), [])
        printed = self.go_card(n, '--short', SHORT, *full)
        self.assertNotIn('Go:', printed)
        self.assertIn(f'Go: release r-7 · digest {"c" * 8}', self.gh.lines(n))

    def short(self, n, text, ok=True):
        return self.cli('ask', '--repo', REPO, str(n), '--kind', 'choice', '--changes', 'c', '--if-yes', 'y', '--if-no', 'n',
                        '--if-wait', 'w', '--undo', 'revert', '--recommended', 'Yes', '--short', text, ok=ok)

    def test_9_the_short_form_is_one_question_three_sentences_45_words_and_one_link(self):
        """Fix2 item 2: card.short limits and every card.short.refuse pattern, read from conveyor.json."""
        n = self.at('in-review')
        link = 'Before and after: https://x.test/p/1'
        body = SHORT[SHORT.index('?') + 2:SHORT.index(link)].strip()
        self.assertEqual(len(body.split()), 30)
        refusals = {
            'issue_number': SHORT.replace('Tests passed', 'Tests for #12 passed'),
            'commit_id': SHORT.replace('Tests passed', 'Tests on a1b2c3d passed'),
            'branch_like': SHORT.replace('Tests passed', 'Tests on feat/care-texts passed'),
            'colon_label': SHORT.replace(' Tests passed', '\nStatus: tests passed'),
            'test_count': SHORT.replace('Tests passed', '12 tests passed'),
        }
        self.assertEqual(set(refusals), set(CONVEYOR['card']['short']['refuse']))
        for name, text in refusals.items():
            self.assertIn(f'short card refused: {name}', self.short(n, text, ok=False), name)
        fourth = SHORT.replace(link, f'Waiting costs nothing. Undo is one click. {link}')  # the labelled link is no sentence
        self.assertIn('short card refused: 4 sentences', self.short(n, fourth, ok=False))
        long = SHORT.replace(link, f"Staff {' '.join(['also'] * 14)} agree. {link}")
        self.assertEqual(len(long[long.index('?') + 2:long.index(link)].split()), 46)
        self.assertIn('short card refused: 3 sentences and 46 words', self.short(n, long, ok=False))
        self.assertIn('one plain question first and one link last', self.short(n, SHORT.replace(' https://x.test/p/1', ''), ok=False))
        self.assertIn('one plain question first and one link last', self.short(n, SHORT.replace('?', '.', 1), ok=False))
        self.assertIn('one plain question first', self.short(n, SHORT + ' https://x.test/p/2', ok=False))
        self.assertEqual(self.gh.writes(), [])
        self.assertEqual(self.short(n, SHORT).strip(), SHORT)

    def test_9_the_card_prints_plain_labels_never_internal_names(self):
        n = self.at('ready-to-release')
        self.gh.link_pr(n)
        self.gh.comment(n, f'Reviewed: {HEAD[:7]} YES\nReviewer: session {REVIEWER} · head {HEAD[:7]} · outside')
        self.short(n, SHORT)
        card = self.gh.issues[n]['comments'][-1]['body']
        self.assertIn('Not yet: build finished', card)  # implement: done was never posted
        checked = self.board(card, 'Checked:')
        for name in CONVEYOR['receipts']:
            if '_' in name:
                self.assertNotIn(name, checked)

    def test_9_tell_me_more_is_logged_and_leaves_the_question_waiting(self):
        n = self.at('in-review')
        self.assertIn(f'- #{n} Widget (in-review)', self.sweep())  # Coming to you next before any question
        self.assertIn('Need from you: 0', self.sweep())  # owner and monitor bookkeeping ask nothing
        self.short(n, SHORT)
        self.t += timedelta(minutes=1)
        self.cli('ask', '--repo', REPO, str(n), '--more', Q)
        self.assertIn(f'Asked for more: 2026-11-18 12:01Z · question {Q}', self.gh.lines(n))
        self.assertFalse(any(line.startswith('Decision:') for line in self.gh.lines(n)))
        out = self.sweep()
        self.assertIn('Need from you: 1', out)
        self.assertIn(f'- #{n} Widget (asked 2026-11-18 12:01Z)', out)
        self.t += timedelta(minutes=1)
        self.cli('decide', '--repo', REPO, str(n), 'Yes', '--question', Q, '--session', COORD)
        self.assertIn('Need from you: 0', self.sweep())


class Sweep(BeltCase):
    def test_board_lines(self):
        self.at('inbox', labels=('prio:now',))
        self.gh.issues[1]['body'] = 'old\n\nCaptured: 2026-11-17 10:00Z · source chat\n'
        self.at('backlog', labels=('prio:now',))
        self.at('backlog', labels=('prio:later',))
        out = self.sweep()
        self.assertIn('Backlog: 2 (now 1 · next 0 · later 1) · oldest unsorted 26h', out)
        self.assertIn('- inbox unsorted over 24 h: #1', out)
        self.assertIn('Pull next: #2, #3 (publish moves them)', out)
        self.assertIn('Test slots: 4 of 4 free', out)
        self.assertNotIn('Not read: sessions', out)

    def stale_review(self):
        n = self.at('in-review')
        self.gh.link_pr(n)
        self.gh.comment(n, f'Review requested: head {HEAD[:7]} · 2026-11-18 10:30Z · session {COORD}')
        return n

    def test_review_fallback_starts_one_reviewer_after_the_window(self):
        n = self.stale_review()
        self.assertNotIn('review past fallback', self.sweep())
        self.t += timedelta(minutes=31)
        out = self.sweep()
        self.assertIn(f'- review past fallback: #{n} head {HEAD[:7]}', out)
        self.assertIn(f'- fallback reviewer started for #{n} at {HEAD[:7]}', out)
        self.sweep()
        self.assertEqual(self.started, [(REPO, n, HEAD[:7], f'https://github.com/{REPO}/pull/{500 + n}')])

    def test_at_most_one_fallback_start_per_sweep(self):
        first, second = self.stale_review(), self.stale_review()
        self.t += timedelta(minutes=31)
        out = self.sweep()
        self.assertEqual(len(self.started), 1)
        self.assertIn('(one start per sweep)', out)
        self.sweep()
        self.assertEqual(sorted(a[1] for a in self.started), [first, second])

    def test_no_fallback_start_without_a_free_test_slot(self):
        self.configure(test_slots=2)
        slots = self.root / 'slots'
        slots.mkdir()
        held = []
        for index in range(2):
            fd = os.open(slots / f'slot-{index}.lock', os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            held.append(fd)
        self.stale_review()
        self.t += timedelta(minutes=31)
        out = self.sweep()
        self.assertEqual(self.started, [])
        self.assertIn('no free test slot: 0 of 2 free', out)
        self.assertIn('Test slots: 0 of 2 free', out)
        os.close(held.pop())
        self.assertIn('fallback reviewer started', self.sweep())
        os.close(held.pop())

    def test_sessions_come_from_owner_and_claim_receipts_on_open_belt_issues(self):
        working = self.at('in-progress')
        parked = self.at('in-progress', labels=('parked',))
        self.gh.issues[parked]['comments'] = [{'author': {'login': 'me'}, 'body': f'Claimed: branch `feat/p` · session {REVIEWER}'}]
        self.at('next')
        self.gh.add(lane='next', comments=('Claimed: branch `x` · session not-a-session-id',))
        out = self.sweep()
        self.assertIn('Sessions: 3 on the belt', out)
        self.assertIn(f'- {BUILDER} · working · claimed #{working} (in-progress)', out)
        self.assertIn(f'- {REVIEWER} · done · claimed #{parked} (in-progress, parked)', out)
        self.assertIn(f'- {COORD} · working · owns #3 (next), owns #{working} (in-progress)', out)
        self.assertNotIn('not-a-session-id', out)

    def test_registry_reads_closed_belt_issues_and_a_closed_issue_never_keeps_a_session_working(self):
        """Fix3 item 2 (contract #24 registry.source and registry.done)."""
        claim = lambda s: f'Claimed: branch `feat/c` · session {s}'  # noqa: E731
        gone = self.gh.add(lane='in-review', comments=(f'Owner: thomas · session {COORD} · 2026-11-18 11:00Z', claim(REVIEWER)))
        mixed_closed = self.gh.add(lane='in-review', comments=(claim(REVIEWER2),))
        mixed_open = self.gh.add(lane='in-progress', comments=(claim(REVIEWER2),))
        parked = self.gh.add(lane='in-progress', labels=('parked',), comments=(claim(BUILDER),))
        self.gh.add(comments=(claim(RELEASE_OWNER),))  # closed but never on the belt
        for n in (gone, mixed_closed, 5):
            self.gh.issues[n]['state'] = 'CLOSED'
        out = self.sweep()
        self.assertIn(['issue', 'list', '-R', REPO, '--state', 'closed', '--limit', '1000', '--json', issues_cli.FIELDS],
                      [a for a, _ in self.gh.calls])
        self.assertIn('Sessions: 4 on the belt', out)
        self.assertIn(f'- {REVIEWER} · done · claimed #{gone} (closed)', out)
        self.assertIn(f'- {COORD} · done · owns #{gone} (closed)', out)
        self.assertIn(f'- {REVIEWER2} · working · claimed #{mixed_open} (in-progress), claimed #{mixed_closed} (closed)', out)
        self.assertIn(f'- {BUILDER} · done · claimed #{parked} (in-progress, parked)', out)
        self.assertNotIn(RELEASE_OWNER, out)

    def test_weekly_adds_the_backlog_age_question_counts_and_the_knowledge_changes(self):
        self.k = stub_knowledge(self, changes=[CHANGE])
        old = self.at('backlog')
        self.gh.issues[old]['createdAt'] = iso(T0 - timedelta(days=31))
        out = self.sweep('--weekly')
        self.assertIn(f'- Weekly: keep, drop or bump? #{old} (backlog over 30 days)', out)
        self.assertIn('Questions (7 days): asked 0 (0.0/day) · decided 0 · tell me more 0', out)
        self.assertIn('Knowledge digest: 1 change(s) this week', out)
        self.assertIn(f'- brain:decisions.md · record colour decision · undo: revert {"f" * 12} in brain', out)
        self.assertEqual(self.k['changes'], ['2026-11-11T12:00:00+00:00'])


class Knowledge(BeltCase):
    """T1-a3 and fixes 6 and 8: the module is imported on use and an unmapped brain follows conveyor.md § Knowledge."""
    def test_importing_issues_cli_does_not_import_knowledge(self):
        code = 'import sys, agent_skills.issues_cli; print("agent_skills.knowledge" in sys.modules)'
        out = subprocess.run([sys.executable, '-c', code], cwd=Path(issues_cli.__file__).parents[1],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), 'False')

    def test_unmapped_brain_reads_say_so_decide_still_records_and_log_refuses(self):
        real_knowledge(self, self.root)  # workers.json maps no knowledge_stores
        n = self.at('next')
        out = self.cli('brief', '--repo', REPO, str(n))
        self.assertIn('brain: not configured on this machine', out)
        self.assertIn('- wiki:pages/release.md · verified 2026-11-02 @ abc1234\n', out)
        out = self.cli('decide', '--repo', REPO, str(n), 'Yes', '--question', Q, '--session', COORD)
        self.assertIn('decision row PENDING: brain: not configured on this machine', out)
        self.assertIn(f'Decision: Yes · 2026-11-18 12:00Z · question {Q} · session {COORD}', self.gh.lines(n))
        m = self.at('monitoring')
        self.ready_monitoring(m)
        self.ready_closed()
        self.cli('close', '--repo', REPO, str(m), '--log', str(self.log), '--learned', 'none')
        self.assertIn(f'- knowledge log refused for #{m}: brain: not configured on this machine', self.sweep())

    def test_decision_scope_is_a_parameter(self):
        n = self.at('next')
        self.cli('decide', '--repo', REPO, str(n), 'Grey everywhere', '--question', Q, '--session', COORD, '--scope', 'global')
        self.cli('decide', '--repo', REPO, str(n), 'Grey for acme', '--question', Q, '--session', COORD, '--scope', 'tenant:acme')
        self.assertEqual([r[-1] for r in self.k['record']], ['global', 'tenant:acme'])
        out = self.cli('decide', '--repo', REPO, str(n), 'x', '--question', Q, '--session', COORD, '--scope', 'team', ok=False)
        self.assertIn('--scope is global, tenant:<id> or repo:<name>', out)

    def test_a_session_outside_the_contract_forms_is_refused(self):
        n = self.at('next')
        out = self.cli('decide', '--repo', REPO, str(n), 'x', '--question', Q, '--session', 'coord-1', ok=False)
        self.assertIn('not local_<uuid> or a uuid', out)
        self.assertEqual(self.gh.writes(), [])

    def test_the_stub_matches_the_real_module(self):
        """Fix2 item 4: the stub keeps the real module's signatures and the contract's return shapes, so the tests
        that need a brain store prove what the real store would return."""
        import inspect
        functions = CONVEYOR['knowledge']['functions']
        stub_knowledge(self, changes=[CHANGE])
        stub = sys.modules['agent_skills.knowledge'].Knowledge
        names = [x for x in ('open', *functions) if hasattr(stub, x)]
        self.assertEqual(set(names), {'open', 'domains', 'pages', 'find', 'record', 'collect', 'log', 'changes'})
        for name in names:
            self.assertEqual(inspect.signature(getattr(stub, name)), inspect.signature(getattr(KNOWLEDGE.Knowledge, name)), name)
        brain = self.root / 'brain'
        brain.mkdir()
        for args in (('init', '-q', '-b', 'main'), ('config', 'user.name', 'T'), ('config', 'user.email', 't@x.invalid')):
            subprocess.run(['git', '-C', str(brain), *args], check=True)
        (brain / 'decisions.md').write_text('# Decisions\n\n| id | status | date | switch | rule | source | scope |\n'
                                            '|---|---|---|---|---|---|---|\n')
        subprocess.run(['git', '-C', str(brain), 'add', '-A'], check=True)
        subprocess.run(['git', '-C', str(brain), 'commit', '-qm', 'seed'], check=True)
        self.configure(knowledge_stores={'acme/brain': str(brain)})
        real, fake = KNOWLEDGE.Knowledge.open(brain='acme/brain'), stub.open()
        for k in (real, fake):  # nothing in the inbox yet: collect folds nothing
            self.assertEqual(k.collect(), {'folded': [], 'branch': None})
        self.assertEqual(functions['collect']['returns'], '{folded, branch}')
        line = 'Conveyor: 2026-11-18 12:00Z · close · monitoring → closed · head - · tests - · skills fffffff · schedules -'
        for call in (lambda k: k.record('decision', 'grey', '2026-11-18', 'https://x.test/q/1', 'Grey everywhere'),
                     lambda k: k.find('grey everywhere')[0], lambda k: k.log(1, [line]), lambda k: k.changes('2026-01-01')[0]):
            self.assertEqual(set(call(real)), set(call(fake)))
        self.assertIn('source', functions['find']['returns'])
        self.assertEqual(real.find('grey everywhere')[0]['source'], 'https://x.test/q/1')

    def test_the_stores_come_from_the_project_map(self):
        self.cli('brief', '--repo', REPO, str(self.at('next')))
        self.assertEqual(self.k['open'], [('acme/brain', str(self.root / 'wiki'))])
        real_knowledge(self, self.root)  # the real module reads the domain vocabulary from the project's wiki
        n = self.at('backlog')
        d = str(draft(plan=f'# Plan: widgets\nIssue: {REPO}#{n}\n', items=None))
        out = self.cli('publish', '--repo', REPO, d, '--owner', 'thomas', '--domain', 'policy', '--session', COORD, ok=False)
        self.assertIn("domain 'policy' is not in the knowledge store's routing table: deploy", out)
        self.cli('publish', '--repo', REPO, d, '--owner', 'thomas', '--domain', 'deploy', '--session', COORD)
        self.assertEqual(self.gh.lane(n), 'next')

    def test_no_knowledge_line_is_refused(self):
        (self.root / 'CLAUDE.md').write_text('# p\n\n## Map\n')
        self.assertIn('no `Knowledge:` line', self.cli('brief', '--repo', REPO, str(self.at('next')), ok=False))


class Resume(BeltCase):
    """Fix 9: resume prints the board plus changes since the role's last checkpoint, within the cap, and writes only
    one Checkpoint: line to that role's log."""
    def setUp(self):
        super().setUp()
        self.role_log = self.root / 'coordinator-log.md'
        self.role_log.write_text('# coordinator\n')
        self.configure(roles={'coordinator': COORD, 'release_owner': RELEASE_OWNER},
                       role_logs={'coordinator': str(self.role_log)})

    def resume(self, *extra, ok=True):
        return self.cli('resume', '--session', COORD, *extra, ok=ok)

    def test_board_changes_and_one_checkpoint(self):
        n = self.at('in-review')
        first = self.resume()
        self.assertIn('Resume for coordinator · o/r', first)
        self.assertIn('Lanes: ', first)
        self.assertIn('Sessions: 2 on the belt', first)
        self.assertIn(f'Since checkpoint: none earlier in {self.role_log}', first)
        self.assertEqual(self.gh.writes(), [])  # read-only toward GitHub
        marks = [line for line in self.role_log.read_text().split('\n') if line.startswith('Checkpoint:')]
        self.assertEqual(marks, ['Checkpoint: 2026-11-18 12:00Z · tokens - · questions 0 · in-progress 0 · in-review 1 · parked 0'])
        self.assertRegex(marks[0], CHECKPOINT)
        self.t += timedelta(minutes=5)
        self.cli('decide', '--repo', REPO, str(n), 'Ship it on Friday', '--question', Q, '--session', COORD)
        self.lane(n, 'in-progress', '--reason', 'late NO')
        before = len(self.gh.writes())
        self.t += timedelta(minutes=5)
        second = self.resume('--repo', REPO)
        self.assertIn('Since checkpoint 2026-11-18 12:00Z: 3 change(s)', second)
        self.assertIn(f'- #{n} lane in-review → in-progress at 2026-11-18 12:05Z', second)
        self.assertIn(f'- #{n} Decision: Ship it on Friday', second)
        self.assertEqual(len(self.gh.writes()), before)
        self.assertEqual(len([x for x in self.role_log.read_text().split('\n') if CHECKPOINT.match(x)]), 2)

    def test_output_stays_within_the_cap(self):
        for k in range(80):
            self.gh.add(lane='in-review', title=f'Widget {k} ' + 'x' * 150)
        out = self.resume()
        cap = CONVEYOR['resume']['cap']
        self.assertLessEqual(len(out.rstrip('\n').split('\n')), cap['lines'])
        self.assertLess(len(out.rstrip('\n')), cap['chars'])
        self.assertIn('cut at the resume cap', out)
        self.assertRegex(out.rstrip('\n').split('\n')[-1], CHECKPOINT)

    def test_only_sessions_named_in_roles(self):
        out = self.cli('resume', '--session', OWNER2, ok=False)
        self.assertIn('not in workers.json roles (coordinator, release_owner)', out)
        out = self.cli('resume', '--session', RELEASE_OWNER, ok=False)
        self.assertIn('role_logs names no existing log.md for release_owner', out)
        self.assertEqual(self.role_log.read_text(), '# coordinator\n')

    def test_the_session_defaults_to_the_desktop_session(self):
        with unittest.mock.patch.dict(os.environ, {'CLAUDE_CODE_HOST_SESSION_ID': COORD}):
            self.assertIn('Resume for coordinator', self.cli('resume'))


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
