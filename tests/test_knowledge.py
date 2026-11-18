"""agent_skills.knowledge: brain and wiki stores, routing, inbox, collect, log, stale, lint."""
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from agent_skills.knowledge import Knowledge, KnowledgeError

SHA = 'abc1234'
HEAD = f'verified: 2026-11-01 @ {SHA}\n'
TIMELINE = ('Conveyor: 2026-11-18 10:05Z · brief · queued → ready · head abc1234 · tests pass · '
            'skills abc1234 · schedules ok')
TIMELINE2 = TIMELINE.replace('brief', 'close').replace('10:05', '11:00')
CORRECTION = 'Correction: #42 · head was abc1234 · is def5678'
DECISIONS = ('# Decisions\n' + HEAD + '\n| id | status | date | switch | rule | source | scope |\n|---|---|---|---|---|---|---|\n'
             '| consent-first | decided | 2026-10-01 | - | Ask consent before any send. | chat | global |\n')
LESSONS = ('# Lessons\n' + HEAD + '\n| id | date | what happened | rule now | source |\n|---|---|---|---|---|\n'
           '| old-lesson | 2026-09 | A send went out twice. | Dedupe before send. | pr-1 |\n')
ANSWERED = ('# Answered\n' + HEAD + '\n| question | answer | date | source |\n|---|---|---|---|\n'
            '| Where do checkouts live? | Under the developer folder. | 2026-10-26 | chat |\n')
BRAIN_INDEX = ('# Index\n' + HEAD + '\n| Task words | Read | Domain |\n|---|---|---|\n'
               '| consent, opt out | [decisions](decisions.md) | policy |\n'
               '| mistakes | [lessons](lessons.md) | policy |\n'
               '| answers | [answered](answered.md) | process |\n')
WIKI_INDEX = ('# Wiki\n' + HEAD + '\n| Task words | Read | Domain |\n|---|---|---|\n'
              '| deploy, ship | [release](pages/release.md) | deploy |\n'
              '| rollback | [release](pages/release.md) | deploy |\n'
              '| consent | [consent](pages/consent.md) | policy |\n')


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git(path, 'init', '-q', '-b', 'main')
    git(path, 'config', 'user.name', 'Test')
    git(path, 'config', 'user.email', 'test@example.invalid')


def commit_all(path, msg='c'):
    git(path, 'add', '-A')
    git(path, 'commit', '-q', '-m', msg)
    return git(path, 'rev-parse', 'HEAD')


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def inbox_text(kind, ident, date='2026-11-10', source='chat', scope='global', text=None):
    text = text or {'decision': 'Always log it.', 'lesson': 'It broke => Test it first.',
                    'answered': 'Which day? => Monday.'}[kind]
    return f'kind: {kind}\nid: {ident}\ndate: {date}\nsource: {source}\nscope: {scope}\ntext: {text}\n'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        self.brain = self.root / 'brain'
        self.wiki = self.root / 'repo' / 'wiki'
        init_repo(self.brain)
        write(self.brain / 'decisions.md', DECISIONS)
        write(self.brain / 'lessons.md', LESSONS)
        write(self.brain / 'answered.md', ANSWERED)
        write(self.brain / 'index.md', BRAIN_INDEX)
        write(self.brain / 'inbox' / 'folded' / '.keep.md', '')
        commit_all(self.brain, 'seed')
        init_repo(self.root / 'repo')
        write(self.wiki / 'index.md', WIKI_INDEX)
        write(self.wiki / 'pages' / 'release.md', '# Release\n' + HEAD + 'Ship by fast-forward.\n')
        write(self.wiki / 'pages' / 'consent.md', '# Consent\n' + HEAD + 'Consent text.\n')
        commit_all(self.root / 'repo', 'seed')
        self.config = self.root / 'workers.json'
        self.config.write_text(json.dumps({'knowledge_stores': {'acme/brain': str(self.brain)}}))

    def open(self, brain='acme/brain', wiki=True):
        return Knowledge.open(brain=brain, wiki=str(self.wiki) if wiki else None, config_path=str(self.config))

    def inbox(self, kind, ident, stamp='20261110T100000Z', **kw):
        p = self.brain / 'inbox' / f'{stamp}-{kind}-{ident}.md'
        write(p, inbox_text(kind, ident, **kw))
        return p


class TestOpen(Base):
    def test_mapped_brain_has_no_notice(self):
        self.assertIsNone(self.open().notice)

    def test_unmapped_brain_notice_and_wiki_reads(self):
        k = self.open(brain='other/none')
        self.assertEqual(k.notice, 'brain: not configured on this machine')
        self.assertEqual([p['store'] for p in k.pages('deploy')], ['wiki'])

    def test_mapped_but_missing_folder_raises(self):
        self.config.write_text(json.dumps({'knowledge_stores': {'acme/brain': str(self.root / 'gone')}}))
        with self.assertRaises(KnowledgeError):
            self.open()

    def test_no_config_file_is_unmapped(self):
        k = Knowledge.open(brain='acme/brain', wiki=str(self.wiki), config_path=str(self.root / 'nope.json'))
        self.assertIn('not configured', k.notice)

    def test_env_config_is_default(self):
        with mock.patch.dict(os.environ, {'AGENT_SKILLS_CONFIG': str(self.config)}):
            self.assertIsNone(Knowledge.open(brain='acme/brain').notice)

    def test_bad_config_raises(self):
        self.config.write_text('{not json')
        with self.assertRaises(KnowledgeError):
            self.open()

    def test_missing_wiki_dir_raises(self):
        with self.assertRaises(KnowledgeError):
            Knowledge.open(wiki=str(self.root / 'absent'), config_path=str(self.config))

    def test_writes_refuse_without_brain(self):
        k = self.open(brain='other/none')
        with self.assertRaises(KnowledgeError):
            k.record('decision', 'x-y', '2026-11-10', 'chat', 'Text.')
        with self.assertRaises(KnowledgeError):
            k.collect()
        with self.assertRaises(KnowledgeError):
            k.log(7, [TIMELINE])

    def test_error_is_value_error(self):
        self.assertTrue(issubclass(KnowledgeError, ValueError))


class TestReads(Base):
    def test_domains_sorted_distinct_across_stores(self):
        self.assertEqual(self.open().domains(), ['deploy', 'policy', 'process'])

    def test_domains_wiki_only(self):
        self.assertEqual(self.open(brain='x/y').domains(), ['deploy', 'policy'])

    def test_pages_brain_first_distinct_with_header(self):
        pages = self.open().pages('policy')
        self.assertEqual([(p['store'], p['path']) for p in pages],
                         [('brain', 'decisions.md'), ('brain', 'lessons.md'), ('wiki', 'pages/consent.md')])
        self.assertEqual(pages[0]['verified'], '2026-11-01')
        self.assertEqual(pages[0]['sha'], SHA)
        self.assertEqual(len(self.open().pages('deploy')), 1)

    def test_pages_without_header_has_none(self):
        write(self.wiki / 'pages' / 'release.md', '# Release\nno header\n')
        page = self.open().pages('deploy')[0]
        self.assertIsNone(page['verified'])
        self.assertIsNone(page['sha'])

    def test_pages_unknown_or_empty_domain(self):
        self.assertEqual(self.open().pages('nothing'), [])

    def test_pages_pending_flag_by_kind(self):
        self.inbox('lesson', 'new-lesson')
        pages = {p['path']: p['pending'] for p in self.open().pages('policy')}
        self.assertEqual(pages, {'decisions.md': False, 'lessons.md': True, 'pages/consent.md': False})
        self.inbox('answered', 'new-answer')
        self.assertTrue(self.open().pages('process')[0]['pending'])

    def test_folded_inbox_is_not_pending(self):
        write(self.brain / 'inbox' / 'folded' / '20261110T100000Z-lesson-done.md', inbox_text('lesson', 'done'))
        self.assertFalse(any(p['pending'] for p in self.open().pages('policy')))

    def test_find_decision_answer_and_ranking(self):
        found = self.open().find(['consent', 'send'])
        self.assertEqual(found[0]['id'], 'consent-first')
        self.assertEqual(found[0]['text'], 'Ask consent before any send.')
        self.assertEqual(found[0]['file'], 'decisions.md')
        self.assertEqual(found[0]['store'], 'brain')
        self.assertEqual(found[0]['source'], 'chat')
        self.assertEqual(found[0]['score'], 2)
        self.assertFalse(found[0]['pending'])

    def test_find_answered_text_and_id_none(self):
        hit = self.open().find(['checkouts', 'live'])[0]
        self.assertEqual(hit['text'], 'Where do checkouts live? => Under the developer folder.')
        self.assertIsNone(hit['id'])

    def test_find_answered_with_id_column(self):
        write(self.brain / 'answered.md', '# A\n' + HEAD + '\n| id | question | answer | date | source |\n|---|---|---|---|---|\n'
              '| q-one | Which zone? | UTC. | 2026-10-26 | chat |\n')
        self.assertEqual(self.open().find(['zone'])[0]['id'], 'q-one')

    def test_find_needs_half_the_words(self):
        k = self.open()
        self.assertEqual(len(k.find(['consent', 'zzzzz'])), 1)
        self.assertEqual(k.find(['consent', 'zzzzz', 'yyyyy']), [])

    def test_find_stop_words_and_empty(self):
        k = self.open()
        with self.assertRaises(KnowledgeError):
            k.find(['the', 'and', 'ab'])
        with self.assertRaises(KnowledgeError):
            k.find([])
        self.assertEqual(k.find(['the', 'consent'])[0]['id'], 'consent-first')

    def test_find_includes_pending_inbox_and_caps_at_five(self):
        self.inbox('decision', 'consent-extra', text='Consent applies to chat.')
        found = self.open().find(['consent'])
        pending = [f for f in found if f['pending']]
        self.assertEqual(pending[0]['id'], 'consent-extra')
        self.assertEqual(pending[0]['file'], 'inbox/20261110T100000Z-decision-consent-extra.md')
        for i in range(8):
            self.inbox('decision', f'consent-{i}', stamp=f'2026111{i}T100000Z', text='Consent again.')
        self.assertEqual(len(self.open().find(['consent'])), 5)

    def test_find_reads_wiki_tables(self):
        write(self.wiki / 'decisions.md', '# D\n' + HEAD + '\n| id | status | date | switch | rule | source |\n|---|---|---|---|---|---|\n'
              '| wiki-rule | decided | 2026-10-01 | - | Wiki rule about rollback. | chat |\n')
        hit = self.open().find(['rollback'])[0]
        self.assertEqual((hit['id'], hit['store'], hit['source']), ('wiki-rule', 'wiki', 'chat'))


class TestRecord(Base):
    def rec(self, **over):
        args = dict(kind='decision', id='new-rule', date='2026-11-10', source='chat', text='Do the thing.')
        args.update(over)
        k = self.open()
        return k.record(args.pop('kind'), args.pop('id'), args.pop('date'), args.pop('source'), args.pop('text'), **args)

    def test_writes_one_inbox_file(self):
        out = self.rec()
        path = self.brain / out['path']
        self.assertRegex(out['path'], r'^inbox/\d{8}T\d{6}Z-decision-new-rule\.md$')
        body = path.read_text()
        for line in ('kind: decision', 'id: new-rule', 'date: 2026-11-10', 'source: chat', 'scope: global',
                     'text: Do the thing.'):
            self.assertIn(line, body.splitlines())

    def test_scope_forms(self):
        self.rec(scope='tenant:acme', id='a-b')
        self.rec(scope='repo:tool', id='c-d')
        with self.assertRaises(KnowledgeError):
            self.rec(scope='world', id='e-f')

    def test_validation_refusals(self):
        bad = [dict(kind='note'), dict(id='Bad_Id'), dict(id='-x'), dict(date='2026-13-01'), dict(date='2026-11'),
               dict(source=''), dict(source='a|b'), dict(text=''), dict(text='two\nlines'), dict(text='pipe | here'),
               dict(kind='lesson', text='no arrow'), dict(kind='answered', text='no arrow'),
               dict(kind='lesson', date='11-2026', text='a => b')]
        for over in bad:
            with self.subTest(over=over), self.assertRaises(KnowledgeError):
                self.rec(**over)

    def test_lesson_month_date_and_answered_ok(self):
        self.rec(kind='lesson', id='l-one', date='2026-11', text='It broke => Fix it.')
        self.rec(kind='answered', id='a-one', text='Why? => Because.')

    def test_duplicate_across_table_inbox_and_folded(self):
        self.rec(id='fresh-id')
        with self.assertRaises(KnowledgeError):
            self.rec(id='fresh-id')
        with self.assertRaises(KnowledgeError):
            self.rec(id='consent-first')
        with self.assertRaises(KnowledgeError):
            self.rec(kind='lesson', id='old-lesson', text='a => b')
        write(self.brain / 'inbox' / 'folded' / '20260101T000000Z-decision-was-folded.md', inbox_text('decision', 'was-folded'))
        with self.assertRaises(KnowledgeError):
            self.rec(id='was-folded')
        self.rec(kind='lesson', id='consent-first', text='a => b')  # same id, other kind


class TestCollect(Base):
    def test_nothing_pending(self):
        self.assertEqual(self.open().collect(), {'folded': [], 'branch': None})

    def test_decision_folds_on_current_branch(self):
        self.inbox('decision', 'log-it', scope='tenant:acme')
        commit_all(self.brain, 'inbox')
        before = git(self.brain, 'rev-list', '--count', 'HEAD')
        out = self.open().collect()
        self.assertEqual(out, {'folded': ['log-it'], 'branch': None})
        row = [l for l in (self.brain / 'decisions.md').read_text().splitlines() if l.startswith('| log-it')]
        self.assertEqual(row, ['| log-it | decided | 2026-11-10 | - | Always log it. | chat | tenant:acme |'])
        self.assertTrue((self.brain / 'inbox' / 'folded' / '20261110T100000Z-decision-log-it.md').exists())
        self.assertFalse((self.brain / 'inbox' / '20261110T100000Z-decision-log-it.md').exists())
        self.assertEqual(int(git(self.brain, 'rev-list', '--count', 'HEAD')), int(before) + 1)
        self.assertEqual(git(self.brain, 'status', '--porcelain'), '')
        self.assertEqual(self.open().find(['always', 'log'])[0]['pending'], False)

    def test_lesson_and_answered_fold_on_new_branch(self):
        self.inbox('lesson', 'new-lesson', stamp='20261110T100000Z')
        self.inbox('answered', 'new-answer', stamp='20261110T100001Z')
        commit_all(self.brain, 'inbox')
        head = git(self.brain, 'rev-parse', 'HEAD')
        out = self.open().collect()
        self.assertEqual(sorted(out['folded']), ['new-answer', 'new-lesson'])
        self.assertRegex(out['branch'], r'^collect/\d{8}T\d{6}Z$')
        self.assertEqual(git(self.brain, 'rev-parse', 'HEAD'), head)
        self.assertEqual(git(self.brain, 'status', '--porcelain'), '')
        self.assertNotIn('new-lesson', (self.brain / 'lessons.md').read_text())
        self.assertEqual(git(self.brain, 'worktree', 'list').count('\n'), 0)
        lessons = git(self.brain, 'show', f"{out['branch']}:lessons.md")
        self.assertIn('| new-lesson | 2026-11-10 | It broke | Test it first. | chat |', lessons)
        answered = git(self.brain, 'show', f"{out['branch']}:answered.md")
        self.assertIn('| Which day? | Monday. | 2026-11-10 | chat |', answered)
        files = git(self.brain, 'ls-tree', '-r', '--name-only', out['branch'])
        self.assertIn('inbox/folded/20261110T100000Z-lesson-new-lesson.md', files)
        self.assertNotIn('inbox/20261110T100000Z-lesson-new-lesson.md', files)

    def test_refuses_uncommitted_tables(self):
        self.inbox('decision', 'log-it')
        commit_all(self.brain, 'inbox')
        write(self.brain / 'decisions.md', DECISIONS + '\n')
        with self.assertRaises(KnowledgeError):
            self.open().collect()

    def test_unknown_column_refuses_and_leaves_everything(self):
        write(self.brain / 'decisions.md', DECISIONS.replace('| scope |', '| mystery |').replace('| global |', '| x |'))
        self.inbox('decision', 'log-it')
        commit_all(self.brain, 'inbox')
        with self.assertRaises(KnowledgeError):
            self.open().collect()
        self.assertTrue((self.brain / 'inbox' / '20261110T100000Z-decision-log-it.md').exists())
        self.assertEqual(git(self.brain, 'status', '--porcelain'), '')

    def test_lint_failure_aborts_and_restores(self):
        self.inbox('decision', 'log-it', text='password: hunter2hunter2')
        self.inbox('lesson', 'new-lesson', stamp='20261110T100001Z')
        commit_all(self.brain, 'inbox')
        head = git(self.brain, 'rev-parse', 'HEAD')
        with self.assertRaises(KnowledgeError) as ctx:
            self.open().collect()
        self.assertIn('credential', str(ctx.exception))
        self.assertEqual(git(self.brain, 'rev-parse', 'HEAD'), head)
        self.assertEqual(git(self.brain, 'status', '--porcelain'), '')
        self.assertEqual(git(self.brain, 'branch', '--list', 'collect/*'), '')
        self.assertEqual(git(self.brain, 'worktree', 'list').count('\n'), 0)


class TestReview(Base):
    def test_find_accepts_a_string(self):
        self.assertEqual(self.open().find('consent send')[0]['id'], 'consent-first')

    def test_result_keys_carry_store(self):
        k = self.open()
        self.assertTrue(all('store' in p for p in k.pages('policy')))
        self.assertTrue(all('store' in h for h in k.find(['consent'])))

    def test_domain_may_contain_digits(self):
        write(self.wiki / 'index.md', WIKI_INDEX + '| texting registration | [release](pages/release.md) | a2p |\n')
        k = self.open()
        self.assertIn('a2p', k.domains())
        self.assertEqual(k.pages('a2p')[0]['path'], 'pages/release.md')
        self.assertEqual(k.lint(), [])

    def test_non_global_scope_never_dropped(self):
        self.inbox('lesson', 'scoped', scope='tenant:acme')
        commit_all(self.brain, 'inbox')
        head = git(self.brain, 'rev-parse', 'HEAD')
        with self.assertRaises(KnowledgeError) as ctx:
            self.open().collect()
        self.assertIn('scope', str(ctx.exception))
        self.assertEqual(git(self.brain, 'rev-parse', 'HEAD'), head)
        self.assertEqual(git(self.brain, 'branch', '--list', 'collect/*'), '')
        self.assertTrue((self.brain / 'inbox' / '20261110T100000Z-lesson-scoped.md').exists())
        with self.assertRaises(KnowledgeError):
            self.open().record('lesson', 'other-one', '2026-11-10', 'chat', 'a => b', scope='repo:tool')
        self.open().record('lesson', 'other-two', '2026-11-10', 'chat', 'a => b')

    def test_record_refuses_secrets_before_writing(self):
        k = self.open()
        for text in ('mail me@example.com', 'api_key = abcd1234', 'call 555-123-4567'):
            with self.subTest(text=text), self.assertRaises(KnowledgeError):
                k.record('decision', 'leaky', '2026-11-10', 'chat', text)
        with self.assertRaises(KnowledgeError):
            k.record('decision', 'leaky', '2026-11-10', 'me@example.com', 'Fine text.')
        self.assertEqual(list((self.brain / 'inbox').glob('*.md')), [])

    def test_preexisting_lint_failure_does_not_block_collect(self):
        write(self.brain / 'tenants' / 'note.md', '# N\n' + HEAD + 'call 555-123-4567\n')
        commit_all(self.brain, 'old page')
        self.inbox('decision', 'log-it')
        self.assertEqual(self.open().collect()['folded'], ['log-it'])
        self.assertTrue(any('tenants/note.md' in f and 'phone' in f for f in self.open().lint()))

    def test_collect_commits_uncommitted_inbox_itself(self):
        k = self.open()
        k.record('decision', 'rec-one', '2026-11-10', 'chat', 'Recorded then collected.')
        k.record('lesson', 'rec-two', '2026-11-10', 'chat', 'It broke => Fix it.')
        out = k.collect()
        self.assertEqual(sorted(out['folded']), ['rec-one', 'rec-two'])
        self.assertEqual(git(self.brain, 'status', '--porcelain'), '')

    def test_failed_collect_restores_uncommitted_inbox(self):
        head = git(self.brain, 'rev-parse', 'HEAD')
        path = self.inbox('decision', 'bad-one', text='password: hunter2hunter2')
        with self.assertRaises(KnowledgeError):
            self.open().collect()
        self.assertEqual(git(self.brain, 'rev-parse', 'HEAD'), head)
        self.assertTrue(path.exists())
        self.assertEqual(git(self.brain, 'status', '--porcelain'), '?? inbox/' + path.name)

    def test_branch_cut_after_decision_commit(self):
        self.inbox('decision', 'log-it')
        self.inbox('lesson', 'new-lesson', stamp='20261110T100001Z')
        out = self.open().collect()
        self.assertIn('| log-it |', git(self.brain, 'show', f"{out['branch']}:decisions.md"))
        self.assertNotIn('pr', out)

    def test_second_collect_skips_entries_on_unmerged_branch(self):
        self.inbox('lesson', 'one-lesson')
        first = self.open().collect()
        self.assertEqual(self.open().collect(), {'folded': [], 'branch': None})
        self.inbox('lesson', 'two-lesson', stamp='20261110T100001Z')
        with mock.patch('agent_skills.knowledge._stamp', return_value='20261201T000001Z'):
            second = self.open().collect()
        self.assertEqual(second['folded'], ['two-lesson'])
        self.assertNotEqual(second['branch'], first['branch'])
        self.assertEqual(len(git(self.brain, 'branch', '--list', 'collect/*').splitlines()), 2)

    def test_stale_skips_brain_pages_and_lint_refuses_their_code_line(self):
        write(self.brain / 'tenants' / 'note.md', '# N\nverified: 2026-11-02 @ deadbeef\ncode: src/a.py\n')
        commit_all(self.brain, 'page')
        k = self.open()
        self.assertEqual(k.stale(), [])
        self.assertTrue(any('tenants/note.md' in f and 'code:' in f for f in k.lint()))


class TestLog(Base):
    def test_writes_month_file(self):
        out = self.open().log(42, [TIMELINE, TIMELINE2])
        self.assertEqual(out['path'], 'log/2026-11.md')
        self.assertEqual((self.brain / 'log' / '2026-11.md').read_text(),
                         f'# Log 2026-11\n\n## #42\n{TIMELINE}\n{TIMELINE2}\n')

    def test_commits_the_month_file_once(self):
        k = self.open()
        before = int(git(self.brain, 'rev-list', '--count', 'HEAD'))
        k.log(42, [TIMELINE])
        self.assertEqual(git(self.brain, 'status', '--porcelain'), '')
        k.log(42, [TIMELINE])
        self.assertEqual(int(git(self.brain, 'rev-list', '--count', 'HEAD')), before + 1)

    def test_idempotent_and_replaces_in_place(self):
        k = self.open()
        k.log(42, [TIMELINE])
        k.log(43, [TIMELINE2])
        first = (self.brain / 'log' / '2026-11.md').read_bytes()
        k.log(43, [TIMELINE2])
        self.assertEqual((self.brain / 'log' / '2026-11.md').read_bytes(), first)
        k.log(42, [TIMELINE, CORRECTION])
        text = (self.brain / 'log' / '2026-11.md').read_text()
        self.assertEqual(text.count('## #42'), 1)
        self.assertLess(text.index('## #42'), text.index('## #43'))
        self.assertIn(CORRECTION, text)
        self.assertEqual(text.count(TIMELINE2), 1)

    def test_replaces_section_in_other_month_file(self):
        k = self.open()
        write(self.brain / 'log' / '2026-10.md', f'# Log 2026-10\n\n## #9\n{TIMELINE}\n')
        out = k.log(9, [TIMELINE2])
        self.assertEqual(out['path'], 'log/2026-10.md')
        self.assertFalse((self.brain / 'log' / '2026-11.md').exists())

    def test_refuses_bad_lines(self):
        k = self.open()
        for lines in ([], ['free text'], [TIMELINE, 'Conveyor: nope'], [TIMELINE + '\nx'], [CORRECTION]):
            with self.subTest(lines=lines), self.assertRaises(KnowledgeError):
                k.log(5, lines)
        with self.assertRaises(KnowledgeError):
            k.log('abc', [TIMELINE])
        self.assertFalse((self.brain / 'log').exists())


class TestStale(Base):
    def make(self):
        repo = self.root / 'repo'
        write(repo / 'src' / 'a.py', 'one\n')
        write(repo / 'src' / 'b.py', 'one\n')
        sha = commit_all(repo, 'code')
        write(self.wiki / 'pages' / 'release.md',
              f'# Release\nverified: 2026-11-02 @ {sha}\ncode: src/a.py#main, src/b.py\n')
        write(self.wiki / 'pages' / 'consent.md', f'# Consent\nverified: 2026-11-02 @ {sha}\ncode: src/b.py\n')
        commit_all(repo, 'pages')
        return repo

    def test_unchanged_is_not_stale(self):
        self.make()
        self.assertEqual(self.open().stale(), [])

    def test_changed_path_reported(self):
        repo = self.make()
        write(repo / 'src' / 'a.py', 'two\n')
        commit_all(repo, 'change')
        out = self.open().stale()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['path'], 'pages/release.md')
        self.assertEqual(out[0]['verified'], '2026-11-02')
        self.assertEqual(out[0]['changed'], ['src/a.py'])

    def test_unknown_sha_raises_naming_page(self):
        repo = self.make()
        write(self.wiki / 'pages' / 'consent.md', '# C\nverified: 2026-11-02 @ deadbeef\ncode: src/b.py\n')
        commit_all(repo, 'bad')
        with self.assertRaises(KnowledgeError) as ctx:
            self.open().stale()
        self.assertIn('pages/consent.md', str(ctx.exception))

    def test_pages_without_code_line_skipped(self):
        self.assertEqual(self.open().stale(), [])


class TestLint(Base):
    def lint(self, **kw):
        return self.open(**kw).lint()

    def test_clean(self):
        self.assertEqual(self.lint(), [])

    def test_budgets(self):
        write(self.wiki / 'index.md', WIKI_INDEX + 'x\n' * 60)
        write(self.wiki / 'pages' / 'release.md', '# R\n' + HEAD + 'x\n' * 80)
        out = self.lint()
        self.assertTrue(any('index.md' in f and 'lines' in f for f in out))
        self.assertTrue(any('pages/release.md' in f and 'lines' in f for f in out))
        write(self.brain / 'decisions.md', DECISIONS + '| a-b | decided | 2026-10-01 | - | r | s | global |\n' * 90)
        self.assertFalse(any('decisions.md' in f for f in self.lint()))

    def test_secrets_and_pii(self):
        samples = {'AKIA' + 'A' * 16: 'AWS', '-----BEGIN RSA PRIVATE KEY-----': 'private key',
                   'sk-' + 'a' * 24: 'API key', 'xoxb-1234567890-abc': 'chat token', 'Bearer ' + 'a' * 24: 'bearer',
                   'api_key = abcd1234': 'credential', 'mail me@example.com': 'email', 'call 555-123-4567': 'phone'}
        for text, name in samples.items():
            write(self.wiki / 'pages' / 'release.md', '# R\n' + HEAD + text + '\n')
            with self.subTest(name=name):
                self.assertTrue(any('pages/release.md' in f and name.lower() in f.lower() for f in self.lint()), text)

    def test_missing_verified(self):
        write(self.wiki / 'pages' / 'release.md', '# R\nbody\n')
        self.assertTrue(any('verified' in f and 'release.md' in f for f in self.lint()))

    def test_routing_rows(self):
        write(self.wiki / 'index.md', WIKI_INDEX.replace('| deploy |', '| Deploy |', 1))
        self.assertTrue(any('domain' in f.lower() for f in self.lint()))
        write(self.wiki / 'index.md', WIKI_INDEX.replace('pages/consent.md', 'pages/missing.md'))
        out = self.lint()
        self.assertTrue(any('missing.md' in f for f in out))
        self.assertTrue(any('consent.md' in f and 'not linked' in f for f in out))

    def test_table_rules(self):
        write(self.brain / 'decisions.md', DECISIONS +
              '| bad-status | maybe | 2026-10-01 | - | r | s | global |\n'
              '| bad-date | decided | 10/01 | - | r | s | global |\n'
              '| no-source | decided | 2026-10-01 | - | r |  | global |\n')
        write(self.brain / 'lessons.md', LESSONS + '| l-bad | yesterday | a | b | s |\n| l-nosrc | 2026-10 | a | b |  |\n')
        write(self.brain / 'answered.md', ANSWERED + '| q | a | 2026-1 | s |\n| q2 | a | 2026-10-26 |  |\n')
        out = '\n'.join(self.lint())
        for needle in ('bad-status', 'bad-date', 'no-source', 'l-bad', 'l-nosrc', "'q'", 'q2'):
            self.assertIn(needle, out)

    def test_inbox_needs_six_keys(self):
        write(self.brain / 'inbox' / '20261110T100000Z-decision-x-y.md', 'kind: decision\nid: x-y\n')
        self.assertTrue(any('inbox' in f and 'scope' in f for f in self.lint()))

    def test_lint_runs_on_wiki_only(self):
        write(self.wiki / 'pages' / 'release.md', '# R\nbody\n')
        self.assertTrue(self.lint(brain='x/y'))


if __name__ == '__main__':
    unittest.main()
