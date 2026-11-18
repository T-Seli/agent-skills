"""safeguard-cli run-approved: one click, fixed code paths, refusals and its own record lines (conveyor.md § Approvals)."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest
from unittest import mock

from agent_skills import release_guard, safeguard_cli

ROOT = Path(__file__).resolve().parents[1]
CONVEYOR = json.loads((ROOT / 'skills/workflow-contracts/conveyor.json').read_text(encoding='utf-8'))
AUTH = json.loads((ROOT / 'authorizations.json').read_text(encoding='utf-8'))
CLI = AUTH['invocation']['safeguard-cli']
QUESTION = 'https://x.test/q/9'


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
        self.commit('base.txt', 'base\n')
        git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        git(self.repo, 'push', '-q', 'origin', 'main')
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        self.head = self.commit('feature.txt', 'feature\n')
        self.heads, self.labels = {7: self.head, 8: self.head}, {}
        gh = mock.patch.object(release_guard, '_gh', side_effect=self.fake_gh)
        gh.start()
        self.addCleanup(gh.stop)
        home = mock.patch.dict(os.environ, {'HOME': str(self.tmp / 'home')})
        home.start()
        self.addCleanup(home.stop)
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)

    def commit(self, name, text):
        (self.repo / name).write_text(text)
        git(self.repo, 'add', name)
        git(self.repo, 'commit', '-qm', name)
        return git(self.repo, 'rev-parse', 'HEAD')

    def fake_gh(self, repo, noun, verb, number, flag, fields):
        number = int(number)
        result = {'labels': [{'name': n} for n in self.labels.get((noun, number), ())]}
        if noun == 'pr':
            result['headRefOid'] = self.heads[number]
        return result

    def cli(self, command):
        out = io.StringIO()
        with redirect_stdout(out):
            code = safeguard_cli.main(shlex.split(command)[1:])
        return code, json.loads(out.getvalue()) if out.getvalue().strip() else None

    def prepare(self, kind='release', action_id='r1', train=('11:7',), targets=('main',), minutes=30):
        items = ' '.join(f'--train={t}:{self.head}' for t in train)
        command = (f'{CLI} prepare-action {kind} {action_id} --session local_prep --expires-in-minutes {minutes} '
                   f'{items} ' + ' '.join(f'--target {t}' for t in targets))
        code, record = self.cli(command)
        self.assertEqual(code, 0, record)
        return command, record

    def approve(self, kind, action_id, digest):
        return f'{CLI} run-approved {kind} {action_id} --digest {digest} --question {QUESTION} --session local_coord'

    def folder(self, action_id):
        return next((self.repo / '.claude/drafts').glob(f'*-{action_id}'))

    def log(self, action_id):
        path = self.folder(action_id) / 'log.md'
        return path.read_text() if path.exists() else ''

    def assertRefused(self, reason, command, action_id='r1'):
        code, result = self.cli(command)
        self.assertEqual((code, result['refused']), (1, reason), result)
        self.assertEqual(self.log(action_id), '', 'a refusal writes nothing')
        self.assertFalse((self.folder(action_id) / 'used').exists())

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
            self.assertEqual(self.cli(go)[0], 0)
        self.assertEqual([permission(c) for c in (prepare, go)], ['allow', 'ask'])  # one ask: the go
        self.assertFalse([c for c in calls if permission(c) or not c.startswith(('git ', 'sh '))], calls)
        log = self.log('r1')
        approved = receipt('approved', log)
        self.assertEqual((approved['kind'], approved['id'], approved['digest'], approved['session']),
                         ('release', 'r1', record['digest'], 'local_coord'))
        self.assertEqual(receipt('deploy', log)['sha'], self.head[:9])
        self.assertIn(f'Rollback: main: {self.base}', log)
        self.assertTrue(receipt('rollback', log))
        timeline = [line for line in log.splitlines() if line.startswith('Conveyor: ')]
        self.assertEqual(len(timeline), 1)
        self.assertRegex(timeline[0], CONVEYOR['timeline']['pattern'])
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), self.head)
        self.assertEqual(json.loads((self.folder('r1') / 'rollback.json').read_text())['rollback'], {'main': self.base})
        self.assertTrue(json.loads((self.folder('r1') / 'action.json').read_text())['used_at'])

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

    def test_refuses_moved_head(self):
        _, record = self.prepare()
        self.heads[7] = self.base
        self.assertRefused('moved-head', self.approve('release', 'r1', record['digest']))
        self.heads[7] = self.head
        self.commit('late.txt', 'unreviewed\n')
        self.assertRefused('moved-head', self.approve('release', 'r1', record['digest']))

    def test_refuses_expired(self):
        _, record = self.prepare(minutes=5)
        later = datetime.now(timezone.utc) + timedelta(minutes=6)
        with self.assertRaises(release_guard.Refused) as refused:
            release_guard.run_approved(str(self.repo), 'release', 'r1', record['digest'],
                                       question=QUESTION, session='local_coord', now=later)
        self.assertEqual(refused.exception.reason, 'expired')
        self.assertEqual(self.log('r1'), '')

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
        self.labels[('issue', 11)] = ['hold']
        self.assertRefused('hold', self.approve('release', 'r1', record['digest']))
        self.labels = {('pr', 8): ['hold']}
        self.assertRefused('hold', self.approve('release', 'r1', record['digest']))

    def test_refuses_train_over_limit_from_defaults(self):
        self.assertEqual(release_guard.train_limit(self.repo), 6)
        code, result = self.cli(f'{CLI} prepare-action release r0 --session s --expires-in-minutes 5 --target main '
                                + ' '.join(f'--train=-:{n}:{self.head}' for n in range(1, 8)))
        self.assertEqual(result['refused'], 'train-over-limit')
        _, record = self.prepare(train=('11:7', '12:8'))
        (self.repo / 'CLAUDE.md').write_text('# p\n\n## Defaults\n- Lane limits: Build 8 · Review 4 · Release 1 train of ≤1 PRs\n')
        self.assertRefused('train-over-limit', self.approve('release', 'r1', record['digest']))

    def test_skills_install_writes_the_snippet_and_never_applies_settings(self):
        settings = self.tmp / 'home/.claude/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text('{"mine": true}\n')
        (self.repo / 'install.sh').write_text('printf \'{"permissions": {}}\\n\' > settings.snippet.json\n')
        installed = self.commit('install.sh', (self.repo / 'install.sh').read_text())
        self.heads[7] = installed
        self.head = installed
        _, record = self.prepare('skills-install', 's1', targets=('claude',))
        self.assertEqual(self.cli(self.approve('skills-install', 's1', record['digest']))[0], 0)
        self.assertEqual(settings.read_text(), '{"mine": true}\n')
        self.assertTrue((self.repo / 'settings.snippet.json').exists())
        self.assertRegex(self.log('s1'), r'settings snippet settings\.snippet\.json sha256 [0-9a-f]{64} written, not applied')
        self.assertTrue(receipt('approved', self.log('s1')))

        (self.repo / 'install.sh').write_text('echo x > "$HOME/.claude/settings.json"; echo y > "$HOME/.claude/settings.local.json"\n')
        self.heads[7] = self.head = self.commit('install.sh', (self.repo / 'install.sh').read_text())
        _, record = self.prepare('skills-install', 's2', targets=('claude',))
        code, _ = self.cli(self.approve('skills-install', 's2', record['digest']))
        self.assertEqual(code, 1)
        self.assertEqual(settings.read_text(), '{"mine": true}\n')
        self.assertFalse((self.tmp / 'home/.claude/settings.local.json').exists())

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
        self.assertEqual(self.cli(self.approve('rollback', 'b1', undo['digest']))[0], 0)
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), right)
        self.assertIn(f'Rollback: main: {self.head}', self.log('b1'))
        self.assertTrue(receipt('approved', self.log('b1')))

    def test_rollback_refuses_when_the_target_moved_after_the_deploy(self):
        _, record = self.prepare()
        self.assertEqual(self.cli(self.approve('release', 'r1', record['digest']))[0], 0)
        _, undo = self.prepare('rollback', 'b1', train=())
        newer = self.commit('newer.txt', 'pushed outside the belt\n')
        git(self.repo, 'push', '-q', 'origin', f'{newer}:refs/heads/main')
        self.assertRefused('moved-head', self.approve('rollback', 'b1', undo['digest']), 'b1')


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
