"""safeguard-cli run-approved: one click, fixed code paths, refusals and its own record lines (conveyor.md § Approvals)."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import functools
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from agent_skills import layout, release_guard, safeguard_cli

ROOT = Path(__file__).resolve().parents[1]
CONVEYOR = json.loads((ROOT / 'skills/workflow-contracts/conveyor.json').read_text(encoding='utf-8'))
AUTH = json.loads((ROOT / 'authorizations.json').read_text(encoding='utf-8'))
CLI = AUTH['invocation']['safeguard-cli']
QUESTION = 'https://x.test/q/9'
UUID = '0f6c2d4e-1a2b-4c3d-8e9f-0a1b2c3d4e5f'
DESKTOP, HEADLESS = f'local_{UUID}', UUID
PIN = 'c' * 40
READY = 'lane:ready-to-release'

# A stand-in for the gh CLI: reads and writes one JSON state file; posts append issue comments.
FAKE_GH = f'''#!{sys.executable}
import json, os, sys
path = os.environ['FAKE_GH_STATE']
with open(path) as stream:
    state = json.load(stream)
noun, verb, number = sys.argv[1:4]
item = state[noun][number]
if verb == 'view':
    print(json.dumps({{f: item[f] for f in sys.argv[sys.argv.index('--json') + 1].split(',')}}))
elif noun == 'issue' and verb == 'comment' and sys.argv[4:] == ['--body-file', '-']:
    if state.get('fail_comments'):
        sys.exit('gh: comment refused')
    item['comments'].append({{'body': sys.stdin.read()}})
    with open(path, 'w') as stream:
        json.dump(state, stream)
    print('https://x.test/issues/' + number)
else:
    sys.exit('fake gh: unsupported ' + ' '.join(sys.argv[1:]))
'''


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def permission(command):
    """The authorizations.json mode a bash command meets: longest matching prefix, else None."""
    hits = [e for e in AUTH['entries'] if e['tool'] == 'bash'
            and (command == e['match'] or command.startswith(e['match'] + ' '))]
    return max(hits, key=lambda e: len(e['match']))['mode'] if hits else None


def receipt(name, text):
    return re.search(CONVEYOR['receipts'][name]['pattern'], text, re.M)


class RunApproved(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.remote, self.repo = self.tmp / 'remote.git', self.tmp / 'work'
        git(self.tmp, 'init', '-q', '--bare', '-b', 'main', str(self.remote))
        git(self.tmp, 'init', '-q', '-b', 'main', str(self.repo))
        for key, value in (('user.email', 'test@example.invalid'), ('user.name', 'Test'), ('commit.gpgsign', 'false')):
            git(self.repo, 'config', key, value)
        (self.repo / '.git/info/exclude').write_text('.claude/drafts/\n')
        self.commit('base.txt', 'base\n')
        git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        git(self.repo, 'push', '-q', 'origin', 'main')
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        self.head = self.commit('feature.txt', 'feature\n')
        # A pinned scratch release root: the release id never comes from a git checkout of the skills.
        self.release_root = self.tmp / 'release'
        self.release_root.mkdir()
        (self.release_root / '.release-pin.json').write_text(json.dumps({'commit': PIN, 'tree': 'd' * 40}))
        pinned = mock.patch.object(layout, 'release_id', functools.partial(layout.release_id, self.release_root))
        pinned.start()
        self.addCleanup(pinned.stop)
        bin_dir = self.tmp / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'gh').write_text(FAKE_GH)
        (bin_dir / 'gh').chmod(0o755)
        self.gh_state = self.tmp / 'gh.json'
        self.gh = {'pr': {}, 'issue': {}}
        for pr in (7, 8):
            self.pr(pr, self.head)
        for issue in (11, 12):
            self.ready(issue, self.head)
        env = mock.patch.dict(os.environ, {'HOME': str(self.tmp / 'home'), 'FAKE_GH_STATE': str(self.gh_state),
                                           'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}'})
        env.start()
        self.addCleanup(env.stop)
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)

    def commit(self, name, text):
        (self.repo / name).write_text(text)
        git(self.repo, 'add', name)
        git(self.repo, 'commit', '-qm', name)
        return git(self.repo, 'rev-parse', 'HEAD')

    def save(self):
        self.gh_state.write_text(json.dumps(self.gh))

    def pr(self, number, head, labels=()):
        self.gh['pr'][str(number)] = {'headRefOid': head, 'labels': [{'name': n} for n in labels]}
        self.save()

    def issue(self, number, labels=(), comments=()):
        self.gh['issue'][str(number)] = {'labels': [{'name': n} for n in labels],
                                         'comments': [{'body': body} for body in comments]}
        self.save()

    def ready(self, number, head, labels=(READY,)):
        self.issue(number, labels, [f'Reviewed: {head[:9]} YES'])

    def comments(self, number):
        return [c['body'] for c in json.loads(self.gh_state.read_text())['issue'][str(number)]['comments'][1:]]

    def cli(self, command):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = safeguard_cli.main(shlex.split(command)[1:])
        self.stderr = err.getvalue()
        return code, json.loads(out.getvalue()) if out.getvalue().strip() else None

    def prepare(self, kind='release', action_id='r1', train=('11:7',), targets=('main',), minutes=30):
        items = ' '.join(f'--train={t}:{self.head}' for t in train)
        command = (f'{CLI} prepare-action {kind} {action_id} --session local_prep --expires-in-minutes {minutes} '
                   f'{items} ' + ' '.join(f'--target {t}' for t in targets))
        code, record = self.cli(command)
        self.assertEqual(code, 0, record)
        return command, record

    def approve(self, kind, action_id, digest, session=DESKTOP):
        return f'{CLI} run-approved {kind} {action_id} --digest {digest} --question {QUESTION} --session {session}'

    def folder(self, action_id):
        return next((self.repo / '.claude/drafts').glob(f'*-{action_id}'))

    def log(self, action_id):
        path = self.folder(action_id) / 'log.md'
        return path.read_text() if path.exists() else ''

    def assertUnused(self, action_id):
        self.assertEqual(self.log(action_id), '', 'nothing is written before the claim')
        self.assertFalse((self.folder(action_id) / 'used').exists())
        self.assertIsNone(json.loads((self.folder(action_id) / 'action.json').read_text())['used_at'])
        self.assertEqual([self.comments(n) for n in (11, 12)], [[], []], 'no issue post before the claim')

    def assertRefused(self, reason, command, action_id='r1'):
        code, result = self.cli(command)
        self.assertEqual((code, result and result['refused']), (1, reason), (result, self.stderr))
        self.assertUnused(action_id)

    def test_release_dry_run_needs_one_permission_point_and_writes_its_own_records(self):
        calls, real_run, real_output = [], subprocess.run, subprocess.check_output

        def spy(real):
            def call(argv, *a, **k):
                calls.append(' '.join(argv))
                return real(argv, *a, **k)
            return call
        with mock.patch('subprocess.run', side_effect=spy(real_run)), \
                mock.patch('subprocess.check_output', side_effect=spy(real_output)):
            prepare, record = self.prepare()
            go = self.approve('release', 'r1', record['digest'])
            self.assertEqual(self.cli(go)[0], 0, self.stderr)
        self.assertEqual([permission(c) for c in (prepare, go)], ['allow', 'ask'])  # one ask: the go
        self.assertFalse([c for c in calls if permission(c) in ('ask', 'deny') or not c.startswith(('git ', 'gh '))], calls)
        self.assertEqual({permission(c) for c in calls if c.startswith('gh issue comment ')}, {'allow'})
        self.assertFalse([c for c in calls if str(ROOT) in c], 'no git or gh call on the skills checkout')
        log = self.log('r1')
        approved = receipt('approved', log)
        self.assertEqual((approved['kind'], approved['id'], approved['digest'], approved['session']),
                         ('release', 'r1', record['digest'], DESKTOP))
        self.assertEqual((receipt('pushed', log)['sha'], receipt('pushed', log)['branch']), (self.head, 'main'))
        self.assertIsNone(receipt('deploy', log), 'release writes Pushed:, never deploy:')
        self.assertIn(f'Rollback: main: {self.base}', log)
        self.assertTrue(receipt('rollback', log))
        timeline = [line for line in log.splitlines() if line.startswith('Conveyor: ')]
        self.assertEqual(len(timeline), 1)
        self.assertEqual(re.match(CONVEYOR['timeline']['pattern'], timeline[0])['skills'], PIN)
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), self.head)
        self.assertEqual(json.loads((self.folder('r1') / 'rollback.json').read_text())['rollback'], {'main': self.base})
        self.assertTrue(json.loads((self.folder('r1') / 'action.json').read_text())['used_at'])

    def test_every_train_issue_and_the_release_log_carry_the_same_lines(self):
        _, record = self.prepare(train=('11:7', '12:8', '-:8'))
        self.assertEqual(self.cli(self.approve('release', 'r1', record['digest']))[0], 0, self.stderr)
        log = self.log('r1')
        for issue in (11, 12):
            posted = ''.join(self.comments(issue))
            for name in ('approved', 'pushed', 'rollback'):
                self.assertTrue(receipt(name, posted), (issue, name))
                self.assertEqual(receipt(name, posted)[0], receipt(name, log)[0])
            self.assertIn(posted.strip(), log.replace('\n\n', '\n'))
            self.assertIsNone(receipt('deploy', posted))

    def test_a_failure_before_the_claim_leaves_the_record_unused(self):
        _, record = self.prepare()
        with mock.patch.object(layout, 'release_id', side_effect=RuntimeError('no release pin and not a git checkout')):
            code, _ = self.cli(self.approve('release', 'r1', record['digest']))
        self.assertEqual(code, 1)
        self.assertIn('no release pin', self.stderr)
        self.assertUnused('r1')
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), self.base)
        self.assertEqual(self.cli(self.approve('release', 'r1', record['digest']))[0], 0, 'the record is still usable')

    def test_a_failure_after_the_claim_appends_failed_everywhere_and_keeps_the_record_used(self):
        _, record = self.prepare(train=('11:7', '12:8'))
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\necho rejected by the remote >&2\nexit 1\n')
        hook.chmod(0o755)
        go = self.approve('release', 'r1', record['digest'])
        self.assertEqual(self.cli(go)[0], 1)
        log = self.log('r1')
        failed = receipt('failed', log)
        self.assertEqual((failed['kind'], failed['id']), ('release', 'r1'))
        self.assertTrue(receipt('approved', log))
        self.assertIsNone(receipt('pushed', log))
        for issue in (11, 12):
            self.assertEqual(receipt('failed', ''.join(self.comments(issue)))[0], failed[0])
        self.assertTrue((self.folder('r1') / 'used').exists())
        self.assertEqual(self.cli(go)[1]['refused'], 'reused')

    def test_record_holds_parameters_only_never_a_command_line(self):
        _, record = self.prepare()
        self.assertEqual(set(record), set(CONVEYOR['action_record']['fields']))
        self.assertEqual(record['digest_input'], json.dumps(
            {k: record[k] for k in record if k not in {'digest_input', 'digest', 'used_at'}},
            sort_keys=True, separators=(',', ':')))
        self.assertEqual(record['train'], [{'issue': 11, 'pr': 7, 'head': self.head}])
        self.assertEqual(record['rollback'], {'main': self.base}, 'the go card Undo reads this')
        self.assertIn('"rollback":', record['digest_input'])
        for target in ('main; rm -rf /', '--upload-pack=touch x', 'a..b', 'main main'):
            with self.assertRaises(ValueError):
                release_guard.prepare_action(str(self.repo), 'release', 'r2', train=[f'11:7:{self.head}'],
                                             targets=[target], session='local_prep', minutes=30)
        with self.assertRaises(ValueError):
            release_guard.prepare_action(str(self.repo), 'release', 'r3', train=['11:7:HEAD && make deploy'],
                                         targets=['main'], session='local_prep', minutes=30)

    def test_refuses_unknown_kind(self):
        _, record = self.prepare()
        self.assertRefused('unknown-kind', self.approve('settings-install', 'r1', record['digest']))
        code, result = self.cli(f'{CLI} prepare-action deploy r9 --session s --expires-in-minutes 5 --target main')
        self.assertEqual(result['refused'], 'unknown-kind')

    def test_refuses_a_target_that_is_not_a_branch(self):
        for target in ("'production server'", 'no-such-branch'):
            code, result = self.cli(f'{CLI} prepare-action release r0 --session s --expires-in-minutes 5 '
                                    f'--train=11:7:{self.head} --target {target}')
            self.assertEqual((code, result['refused']), (1, 'non-branch-target'), target)
        git(self.repo, 'push', '-q', 'origin', f'{self.base}:refs/heads/release-x')
        _, record = self.prepare(targets=('release-x',))
        git(self.repo, 'push', '-q', 'origin', '--delete', 'release-x')
        self.assertRefused('non-branch-target', self.approve('release', 'r1', record['digest']))

    def test_refuses_not_ready(self):
        _, record = self.prepare(train=('11:7', '12:8'))
        go = self.approve('release', 'r1', record['digest'])
        self.ready(12, self.head, labels=('lane:in-review',))
        self.assertRefused('not-ready', go)
        self.ready(12, self.base)
        self.assertRefused('not-ready', go)
        self.issue(12, (READY,), [f'Decision: ship it · 2026-11-18 10:00Z · question {QUESTION} · session {DESKTOP}'])
        self.assertRefused('not-ready', go)
        self.ready(12, self.head)
        self.assertEqual(self.cli(go)[0], 0, self.stderr)

    def test_refuses_moved_head(self):
        _, record = self.prepare()
        self.pr(7, self.base)
        self.assertRefused('moved-head', self.approve('release', 'r1', record['digest']))
        self.pr(7, self.head)
        git(self.repo, 'push', '-q', 'origin', f'{self.head}:refs/heads/main')
        self.assertRefused('moved-head', self.approve('release', 'r1', record['digest']))
        git(self.repo, 'push', '-q', '-f', 'origin', f'{self.base}:refs/heads/main')
        self.commit('late.txt', 'unreviewed\n')
        self.assertRefused('moved-head', self.approve('release', 'r1', record['digest']))

    def test_refuses_expired(self):
        _, record = self.prepare(minutes=5)
        later = datetime.now(timezone.utc) + timedelta(minutes=6)
        with self.assertRaises(release_guard.Refused) as refused:
            release_guard.run_approved(str(self.repo), 'release', 'r1', record['digest'],
                                       question=QUESTION, session=DESKTOP, now=later)
        self.assertEqual(refused.exception.reason, 'expired')
        self.assertUnused('r1')

    def test_refuses_reused(self):
        _, record = self.prepare()
        go = self.approve('release', 'r1', record['digest'])
        self.assertEqual(self.cli(go)[0], 0)
        first = self.log('r1')
        code, result = self.cli(go)
        self.assertEqual(result['refused'], 'reused')
        self.assertEqual(self.log('r1'), first)
        code, result = self.cli(f'{CLI} prepare-action rollback r1 --session s --expires-in-minutes 5 --target main')
        self.assertEqual(result['refused'], 'reused')

    def test_refuses_digest_mismatch(self):
        _, record = self.prepare()
        self.assertRefused('digest-mismatch', self.approve('release', 'r1', 'f' * 64))
        path = self.folder('r1') / 'action.json'
        tampered = {**record, 'targets': ['release-elsewhere']}
        path.write_text(json.dumps(tampered))
        self.assertRefused('digest-mismatch', self.approve('release', 'r1', record['digest']))

    def test_refuses_hold_on_issue_or_pr(self):
        _, record = self.prepare(train=('11:7', '-:8'))
        self.ready(11, self.head, labels=(READY, 'hold'))
        self.assertRefused('hold', self.approve('release', 'r1', record['digest']))
        self.ready(11, self.head)
        self.pr(8, self.head, labels=('hold',))
        self.assertRefused('hold', self.approve('release', 'r1', record['digest']))

    def test_refuses_train_over_limit_from_defaults(self):
        self.assertEqual(release_guard.train_limit(self.repo), 6)
        code, result = self.cli(f'{CLI} prepare-action release r0 --session s --expires-in-minutes 5 --target main '
                                + ' '.join(f'--train=-:{n}:{self.head}' for n in range(1, 8)))
        self.assertEqual(result['refused'], 'train-over-limit')
        _, record = self.prepare(train=('11:7', '12:8'))
        (self.repo / '.git/info/exclude').write_text('.claude/drafts/\nCLAUDE.md\n')
        (self.repo / 'CLAUDE.md').write_text('# p\n\n## Defaults\n- Lane limits: Build 8 · Review 4 · Release 1 train of ≤1 PRs\n')
        self.assertRefused('train-over-limit', self.approve('release', 'r1', record['digest']))

    def install_script(self, text):
        self.head = self.commit('install.sh', text)
        self.pr(7, self.head)
        self.ready(11, self.head)

    def test_skills_install_runs_from_an_export_and_never_applies_settings(self):
        settings = self.tmp / 'home/.claude/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text('{"mine": true}\n')
        self.install_script('pwd -P > "$HOME/ran-in"\nprintf \'{"permissions": {}}\\n\' > settings.snippet.json\n')
        _, record = self.prepare('skills-install', 's1', targets=('claude',))
        self.assertEqual(self.cli(self.approve('skills-install', 's1', record['digest'], HEADLESS))[0], 0, self.stderr)
        export = self.folder('s1') / 'release'
        self.assertEqual((self.tmp / 'home/ran-in').read_text().strip(), str(export.resolve()))
        self.assertEqual(json.loads((export / '.release-pin.json').read_text()),
                         {'commit': self.head, 'tree': record['tree']})
        self.assertEqual(sorted(p.name for p in export.iterdir()),
                         ['.release-pin.json', 'base.txt', 'feature.txt', 'install.sh', 'settings.snippet.json'])
        self.assertFalse((self.repo / 'settings.snippet.json').exists(), 'install never runs in the working tree')
        self.assertEqual(settings.read_text(), '{"mine": true}\n')
        self.assertRegex(self.log('s1'), r'settings snippet settings\.snippet\.json sha256 [0-9a-f]{64} written, not applied')
        self.assertEqual(receipt('approved', self.log('s1'))['session'], HEADLESS)
        self.assertTrue(receipt('approved', ''.join(self.comments(11))))

        self.install_script('echo x > "$HOME/.claude/settings.json"; echo y > "$HOME/.claude/settings.local.json"\n')
        _, record = self.prepare('skills-install', 's2', targets=('claude',))
        self.assertEqual(self.cli(self.approve('skills-install', 's2', record['digest']))[0], 1)
        self.assertEqual(settings.read_text(), '{"mine": true}\n')
        self.assertFalse((self.tmp / 'home/.claude/settings.local.json').exists())
        self.assertIn('install changed settings', receipt('failed', self.log('s2'))['reason'])

    def test_skills_install_refuses_a_dirty_tree(self):
        self.install_script('printf \'{}\\n\' > settings.snippet.json\n')
        _, record = self.prepare('skills-install', 's1', targets=('claude',))
        go = self.approve('skills-install', 's1', record['digest'])
        (self.repo / 'feature.txt').write_text('edited after review\n')
        self.assertRefused('dirty-tree', go, 's1')
        git(self.repo, 'checkout', '--', 'feature.txt')
        (self.repo / 'stray.txt').write_text('untracked\n')
        self.assertRefused('dirty-tree', go, 's1')
        (self.repo / 'stray.txt').unlink()
        self.assertEqual(self.cli(go)[0], 0, self.stderr)

    def test_session_ids_take_both_forms_and_nothing_else(self):
        for action_id, session in (('r1', DESKTOP), ('r2', HEADLESS)):
            git(self.repo, 'push', '-q', '-f', 'origin', f'{self.base}:refs/heads/main')
            _, record = self.prepare(action_id=action_id)
            self.assertEqual(self.cli(self.approve('release', action_id, record['digest'], session))[0], 0, self.stderr)
            self.assertEqual(receipt('approved', self.log(action_id))['session'], session)
        git(self.repo, 'push', '-q', '-f', 'origin', f'{self.base}:refs/heads/main')
        self.ready(11, self.head)
        _, record = self.prepare(action_id='r3')
        for session in ('local_coord', f'remote_{UUID}', UUID.upper()):
            self.assertEqual(self.cli(self.approve('release', 'r3', record['digest'], session))[0], 1, session)
            self.assertIn('session id', self.stderr)
            self.assertUnused('r3')

    def test_rollback_reads_the_correction_in_place_of_a_wrong_receipt(self):
        _, record = self.prepare()
        self.assertEqual(self.cli(self.approve('release', 'r1', record['digest']))[0], 0)
        wrong = self.log('r1')
        git(self.repo, 'checkout', '-q', '-b', 'side', self.base)
        right = self.commit('side.txt', 'the ref that really ran\n')
        code, result = self.cli(f'{CLI} correct-rollback r1 main {self.head} {right}')
        self.assertEqual(code, 1, 'a correction must name the receipt value it replaces')
        self.assertEqual(self.cli(f'{CLI} correct-rollback r1 main {self.base} {right}')[0], 0)
        log = self.log('r1')
        self.assertTrue(log.startswith(wrong), 'the receipt itself is never edited')
        self.assertRegex(log.splitlines()[-1], CONVEYOR['timeline']['correction'])
        _, undo = self.prepare('rollback', 'b1', train=())
        self.assertEqual(undo['train'], record['train'])
        self.assertEqual(self.cli(self.approve('rollback', 'b1', undo['digest']))[0], 0, self.stderr)
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), right)
        self.assertIn(f'Rollback: main: {self.head}', self.log('b1'))
        self.assertEqual(receipt('pushed', self.log('b1'))['sha'], right)
        self.assertTrue(receipt('approved', ''.join(self.comments(11)[-2:])))

    def test_rollback_refuses_when_the_target_moved_after_the_release(self):
        _, record = self.prepare()
        self.assertEqual(self.cli(self.approve('release', 'r1', record['digest']))[0], 0)
        _, undo = self.prepare('rollback', 'b1', train=())
        posted = self.comments(11)
        newer = self.commit('newer.txt', 'pushed outside the belt\n')
        git(self.repo, 'push', '-q', 'origin', f'{newer}:refs/heads/main')
        code, result = self.cli(self.approve('rollback', 'b1', undo['digest']))
        self.assertEqual((code, result['refused']), (1, 'moved-head'))
        self.assertEqual(self.log('b1'), '')
        self.assertEqual(self.comments(11), posted)

    def test_a_release_entry_without_a_commit_line_fails_loudly_by_name(self):
        _, record = self.prepare()
        self.assertEqual(self.cli(self.approve('release', 'r1', record['digest']))[0], 0)
        log = self.folder('r1') / 'log.md'
        log.write_text(re.sub(r'^Commit: .*\n', '', log.read_text(), flags=re.M))
        with self.assertRaisesRegex(ValueError, 'release entry has no Commit line'):
            release_guard._rollback_refs(log)
        self.assertEqual(self.cli(f'{CLI} correct-rollback r1 main {self.base} {self.head}')[0], 1)
        self.assertIn('release entry has no Commit line', self.stderr)
        code, _ = self.cli(f'{CLI} prepare-action rollback b1 --session s --expires-in-minutes 5 --target main')
        self.assertEqual(code, 1)
        self.assertIn('release entry has no Commit line', self.stderr)


class SweepStaysOnTheBelt(unittest.TestCase):
    def run_sweep(self, fake):
        with mock.patch.object(safeguard_cli, 'sweep', fake), \
                mock.patch.object(safeguard_cli, 'machine_config', return_value={}), \
                mock.patch('sys.stdout'):
            safeguard_cli.main(['sweep', '/tmp/main', '--base', 'main'])

    def test_live_sweep_asks_closeout_for_belt_worktrees_only(self):
        seen = {}
        def belt_aware(main, *, base, apply=False, rebuildable=(), lease_files=(), active_seconds=7200, belt_only=False):
            seen['belt_only'] = belt_only
            return {'ok': True}
        self.run_sweep(belt_aware)
        self.assertIs(seen['belt_only'], True)

    def test_older_closeout_without_the_option_still_runs(self):
        seen = {}
        def older(main, *, base, apply=False, rebuildable=(), lease_files=(), active_seconds=7200):
            seen['called'] = True
            return {'ok': True}
        self.run_sweep(older)
        self.assertTrue(seen['called'])


if __name__ == '__main__':
    unittest.main()
