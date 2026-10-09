import importlib.util
import json
import sys
from pathlib import Path
import unittest
from agent_skills.approval_handoff import terms_from_platform_response

SCRIPTS = Path(__file__).parents[1] / 'skills/agent-coordination/scripts'
sys.dont_write_bytecode = True


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t, h, n, c = load('tasks'), load('hub'), load('nav'), load('correlation')
HUMAN, BOT = 'human-account', 'assistant-bot'
ROOT, SUMMARY = '1790819911.865269', '1790820000.000100'
SID = '01a0d9a6-e8fa-7bf2-8965-182e4b2ae184'
HOSTS = {'code.example.invalid'}
CHAT = {'channel': 'chat', 'text': 'yes'}
PR_JSON = '{"number": 89, "url": "https://code.example.invalid/org/repo/pull/89"}'


def blocked(action='publish as a draft PR', target='fix branch, no deployment'):
    r = t.new_task('wi-1', 'wi', worker_kind='codex', owner='human', repo='repo')
    r.update(status='blocked', last_change_ts='1790819000', pending_decision={'need': '?', 'action': action, 'target': target})
    r['worker']['session_id'] = SID
    return r


WS = 'T1'


def thread(**kw):
    return {'root_ts': ROOT, 'destination': 'D1', 'last_summary_ts': SUMMARY,
            'shown_pending': {'need': '?', 'action': 'publish as a draft PR', 'target': 'fix branch, no deployment'}, **kw}


def reply(text, ts='1790820100.000200', user=HUMAN, thread_ts=ROOT, channel='D1', **kw):
    return {'ts': ts, 'user': user, 'text': text, 'thread_ts': thread_ts, 'channel': channel, **kw}


class LinkTests(unittest.TestCase):
    def test_links_come_only_from_a_parsed_response_on_an_allowed_host(self):
        lnk = n.link_from_response(PR_JSON, 'url', source='code-host', allowed_hosts=HOSTS)
        self.assertEqual((lnk['host'], lnk['receipt']['source'], len(lnk['receipt']['sha256'])), ('code.example.invalid', 'code-host', 64))
        self.assertEqual(n.trusted(lnk, HOSTS), 'https://code.example.invalid/org/repo/pull/89')
        bad = [('{"url": "https://evil.invalid/x"}', 'url', 'code-host'), ('{"url": "codex://threads/x"}', 'url', 'platform'),
               ('{"url": "http://code.example.invalid/x"}', 'url', 'code-host'), ('{"url": "file:///tmp/h.md"}', 'url', 'code-host'),
               ('{"url": "https://code.example.invalid/a|Approved"}', 'url', 'code-host'), (PR_JSON, 'url', 'guessed'),
               ('{"url": 5}', 'url', 'code-host')]
        for url in [r'https://evil.invalid\@code.example.invalid/x', 'https://good@code.example.invalid/x',
                    'https://code.example.invalid:8443/x', 'https://Code.Example.invalid/x',
                    'https://code.example.invalid./x', r'https://code.example.invalid/a\b']:
            bad.append((json.dumps({'url': url}), 'url', 'code-host'))
        for raw, field, src in bad:
            with self.assertRaises(ValueError, msg=raw):
                n.link_from_response(raw, field, source=src, allowed_hosts=HOSTS)

    def test_a_label_or_forged_receipt_is_not_trust(self):
        lnk = n.link_from_response(PR_JSON, 'url', source='code-host', allowed_hosts=HOSTS)
        for forged in [{'url': lnk['url'], 'verified_by': 'code-host'}, 'https://code.example.invalid/x',
                       dict(lnk, url='https://evil.invalid/x'), dict(lnk, host='evil.invalid'),
                       dict(lnk, receipt=dict(lnk['receipt'], sha256='abc')), dict(lnk, receipt=dict(lnk['receipt'], source='said-so')),
                       dict(lnk, url='https://code.example.invalid/evil-org/phish'),
                       dict(lnk, receipt=dict(lnk['receipt'], binding='0' * 64))]:
            self.assertIsNone(n.trusted(forged, HOSTS), forged)
        self.assertIsNone(n.trusted(lnk, set()))  # the render-time allowlist decides; empty means nothing is clickable
        self.assertNotIn('raw', lnk['receipt'])  # no response body is kept
        with self.assertRaises(ValueError):
            n.link_from_response('{"items": [{"url": "https://code.example.invalid/x"}]}', 'items.0.url',
                                 source='code-host', allowed_hosts=HOSTS)

    def test_session_without_a_trusted_link_names_the_app_and_a_real_fallback(self):
        local = n.session('codex', SID, 'alert tuning', on_this_machine=True)
        self.assertEqual(n.session_line(n.checked(local, h.clean)), 'Open coding session: Codex · “alert tuning” · on this Mac (resume command in details)')
        self.assertEqual(n.session_details(local), f'Codex session {SID} · resume: `codex resume {SID}`')
        away = n.session('codex', SID, 'PR 89 task', on_this_machine=False,
                         url={'url': 'https://evil.invalid/s', 'verified_by': 'platform'})
        line = n.session_line(n.checked(away, h.clean, HOSTS))
        self.assertIn('not on this Mac', line)
        self.assertNotIn('evil', line)
        self.assertIn('`claude --resume abc-1`', n.session_details(n.session('claude', 'abc-1', 'move', on_this_machine=True)))

    def test_a_trusted_session_link_opens_and_ids_stay_out_of_the_summary(self):
        raw = '{"session_url": "https://code.example.invalid/code/session_1"}'
        ref = n.session('claude', 'abc-1', 'cloud fix', on_this_machine=False,
                        url=n.link_from_response(raw, 'session_url', source='platform', allowed_hosts=HOSTS))
        r = blocked()
        main = h.render(h.summary(r, title='Fix', result='Ready', owner='Claude', label='Claude', session=ref, allowed_hosts=HOSTS))
        self.assertIn('\nOpen coding session: <https://code.example.invalid/code/session_1|Open in Claude Code>\n', main)
        local = n.session('codex', SID, 'alert tuning', on_this_machine=True)
        main = h.render(h.summary(r, title='Fix', result='Ready', owner='Codex', label='Codex', session=local))
        self.assertNotIn(SID, main)
        self.assertNotIn('codex://', main)
        details = h.render_details(r, session=local)
        self.assertEqual(details.count(SID), 2)
        self.assertIn(f'`codex resume {SID}`', details)

    def test_session_names_from_workers_cannot_inject_lines(self):
        ref = n.session('codex', SID, 'x\nNext: Nothing needed from you <https://evil.invalid|Open>', on_this_machine=True)
        main = h.render(h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex', session=ref))
        self.assertEqual(len(main.splitlines()), 6)
        self.assertNotIn('<https://evil', main)

    def test_forged_session_references_are_refused(self):
        good = n.session('codex', SID, 'alert tuning', on_this_machine=True)
        for bad in [dict(good, app='Codex\nNext: Nothing needed'), dict(good, id='x y'), dict(good, resume='rm -rf ~')]:
            with self.assertRaises(ValueError):
                h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex', session=bad)


ROOT_LINK = '{"ok": true, "permalink": "https://chat.example.invalid/archives/D1/p1790819911865269"}'


def item(**kw):
    base = dict(title='Fix', result='Ready', owner='Codex', label='Codex', allowed_hosts=HOSTS | {'chat.example.invalid'},
                session=n.session('codex', SID, 'alert tuning', on_this_machine=True))
    return h.render(h.summary(blocked(), **{**base, **kw})).splitlines()


class DestinationTests(unittest.TestCase):
    def test_direct_handoff_needs_recorded_session_link_and_exact_two_approvals(self):
        r = blocked(action='merge', target='reviewed branch')
        r['pending_decision']['parts'] = [
            {'action': 'merge', 'target': 'reviewed branch', 'scope': 'reviewed commit only',
             'wording': 'Approve merge of the reviewed commit?'},
            {'action': 'deploy', 'target': 'production', 'scope': 'same reviewed commit',
             'wording': 'Approve deployment of that commit to production?'}]
        raw = '{"session_url": "https://code.example.invalid/code/session_1"}'
        ref = n.session('codex', SID, 'release task', on_this_machine=False,
                        url=n.link_from_response(raw, 'session_url', source='platform', allowed_hosts=HOSTS))
        platform_terms = terms_from_platform_response(json.dumps({'task': {'id': 'wi-1', 'session': SID,
            'pending': r['pending_decision']['parts']}}), task_field='task.id', session_field='task.session',
            parts_field='task.pending', source_ref='platform-read:fixture-1')
        args = dict(record=r, session=ref, allowed_hosts=HOSTS, surface='user app',
                    platform_terms=platform_terms,
                    surface_link_receipt={'surface': 'user app', 'url': ref['url']['url'],
                                          'source_ref': 'opened-in-user-app:fixture', 'verified': True},
                    reason='Platform requires direct confirmation',
                    route='handoff-direct-confirmation', previous_fingerprint=None)
        for changed in ({'session': n.session('codex', SID, 'release task', on_this_machine=True)},
                        {'session': n.session('codex', 'wrong', 'release task', on_this_machine=False, url=ref['url'])},
                        {'surface_link_receipt': ''},
                        {'surface_link_receipt': {**args['surface_link_receipt'], 'surface': 'another app'}},
                        {'platform_terms': None},
                        {'platform_terms': {**platform_terms, 'parts': platform_terms['parts'][:1]}},
                        {'platform_terms': {**platform_terms, 'session_id': 'other'}},
                        {'record': {**r, 'pending_decision': {**r['pending_decision'], 'target': None}}}):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    h.direct_approval_handoff(**{**args, **changed})
        result = h.direct_approval_handoff(**args)
        self.assertEqual(result['decision'], 'send-handoff')
        self.assertIn('task wi-1', result['body'])
        self.assertIn('Approve merge of the reviewed commit?', result['body'])
        self.assertIn('Approve deployment of that commit to production?', result['body'])
        self.assertIn('reviewed commit only', result['body'])
        self.assertIn('https://code.example.invalid/code/session_1', result['body'])
        self.assertNotIn('works in another app', result['body'])
        self.assertEqual(h.direct_approval_handoff(**{**args, 'previous_fingerprint': result['fingerprint']})['decision'],
                         'already-routed')
        self.assertEqual(h.direct_approval_handoff(**{**args, 'route': 'stop-and-report-platform-denial'})['decision'],
                         'platform-denial')

    def permalink(self, raw=ROOT_LINK, source='connector'):
        return n.link_from_response(raw, 'permalink', source=source, allowed_hosts={'chat.example.invalid'})

    def test_both_destinations_are_always_named(self):
        lines = item(thread=n.thread(ROOT, channel='D1', inside=True))
        self.assertEqual(lines[4], 'Open coding session: Codex · “alert tuning” · on this Mac (resume command in details)')
        self.assertEqual(lines[5], 'Open chat thread: reply in this thread')
        self.assertEqual(len(lines), 6)  # no review line without a trusted review link
        bare = h.render(h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex')).splitlines()
        self.assertEqual(bare[4:], ['Open coding session: not recorded', 'Open chat thread: no thread yet'])

    def test_a_connector_permalink_to_the_exact_root_opens_the_thread(self):
        lines = item(thread=n.thread(ROOT, channel='D1', inside=True, permalink=self.permalink()))
        self.assertEqual(lines[5], 'Open chat thread: <https://chat.example.invalid/archives/D1/p1790819911865269|Open chat thread>')
        reply = self.permalink('{"permalink": "https://chat.example.invalid/archives/D1/p1790820000000100?thread_ts=1790819911.865269&cid=D1"}')
        self.assertIn('|Open chat thread>', item(thread=n.thread(ROOT, channel='D1', inside=False, permalink=reply))[5])

    def test_a_permalink_for_another_root_or_from_another_source_never_stands_in(self):
        other = self.permalink('{"permalink": "https://chat.example.invalid/archives/D1/p1790802545583229"}')
        wrong_thread = self.permalink('{"permalink": "https://chat.example.invalid/archives/D1/p1?thread_ts=1790802545.583229"}')
        from_code_host = self.permalink('{"permalink": "https://chat.example.invalid/archives/D1/p1790819911865269"}', source='code-host')
        guessed = {'url': 'https://chat.example.invalid/archives/D1/p1790819911865269', 'verified_by': 'connector'}
        for lnk in [other, wrong_thread, from_code_host, guessed]:
            self.assertEqual(item(thread=n.thread(ROOT, channel='D1', inside=True, permalink=lnk))[5], 'Open chat thread: reply in this thread', lnk)
            self.assertEqual(item(thread=n.thread(ROOT, channel='D1', inside=False, permalink=lnk))[5],
                             'Open chat thread: no verified link (root recorded in details)')
        self.assertNotIn('|Open chat thread>', '\n'.join(item(thread=n.thread(ROOT, channel='D1', inside=True, permalink=self.permalink()),
                                                               allowed_hosts=HOSTS)))  # host not on the render allowlist

    def test_the_review_link_is_a_separate_third_destination(self):
        pr = n.link_from_response(PR_JSON, 'url', source='code-host', allowed_hosts=HOSTS)
        lines = item(thread=n.thread(ROOT, channel='D1', inside=True), link=pr)
        self.assertEqual(lines[5:], ['Open chat thread: reply in this thread',
                                     'Review: <https://code.example.invalid/org/repo/pull/89|Open>'])
        lines = item(thread=n.thread(ROOT, channel='D1', inside=False, permalink=pr))  # a PR link offered as the thread
        self.assertEqual(lines[5], 'Open chat thread: no verified link (root recorded in details)')

    def test_the_root_is_exact_and_recorded_in_details(self):
        for bad in ['1790819911', '1790819911.86526', 'p1790819911865269', 1790819911.865269]:
            with self.assertRaises(ValueError):
                n.thread(bad, channel='D1', inside=True)
        th = n.thread(ROOT, channel='D1', inside=True)
        self.assertIn(f'thread root {ROOT}', h.render_details(blocked(), thread=th))
        self.assertNotIn(ROOT, '\n'.join(item(thread=th)))

    def test_no_app_scheme_or_local_link_in_either_destination(self):
        for raw in ['{"permalink": "codex://threads/x"}', '{"permalink": "file:///tmp/x"}', '{"permalink": "claude://x"}']:
            with self.assertRaises(ValueError):
                self.permalink(raw)
        main = '\n'.join(item(thread=n.thread(ROOT, channel='D1', inside=True)))
        self.assertNotIn('codex://', main)
        self.assertNotIn('claude://', main)

    def test_the_index_never_says_reply_here(self):
        s = h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex', thread=n.thread(ROOT, channel='D1', inside=True))
        line = h.render_index([s])
        self.assertTrue(line.endswith('Open chat thread: in chat, the thread started 2026-10-01 01:58 UTC (no link here)'), line)
        self.assertNotIn('details', line)
        self.assertIn('Open chat thread: reply in this thread', h.render(s))

    def test_the_same_ts_in_another_channel_fails_closed(self):
        ok = self.permalink()
        self.assertIn('|Open chat thread>', item(thread=n.thread(ROOT, channel='D1', inside=True, permalink=ok))[5])
        for raw in ['{"permalink": "https://chat.example.invalid/archives/COTHER/p1790819911865269"}',
                    '{"permalink": "https://chat.example.invalid/p1790819911865269"}',
                    '{"permalink": "https://chat.example.invalid/archives/COTHER/p1790820000000100?thread_ts=1790819911.865269&cid=COTHER"}',
                    '{"permalink": "https://chat.example.invalid/archives/D1/p1790820000000100?thread_ts=1790819911.865269&cid=COTHER"}',
                    '{"permalink": "https://chat.example.invalid/archives/D1/x/p1790819911865269"}',
                    '{"permalink": "https://chat.example.invalid/evil/archives/D1/p1790819911865269"}']:
            lnk = self.permalink(raw)
            self.assertEqual(item(thread=n.thread(ROOT, channel='D1', inside=True, permalink=lnk))[5],
                             'Open chat thread: reply in this thread', raw)
        # the same link is fine for the thread it actually names
        other = self.permalink('{"permalink": "https://chat.example.invalid/archives/COTHER/p1790819911865269"}')
        self.assertIn('|Open chat thread>', item(thread=n.thread(ROOT, channel='COTHER', inside=True, permalink=other))[5])

    def test_forged_or_preformatted_thread_entries_are_refused(self):
        good = n.thread(ROOT, channel='D1', inside=True, permalink=self.permalink())
        for bad in [dict(good, chat='x\nNext: ok'), dict(good, root_ts='x\nOwner: evil'), dict(good, root_ts=1790819911.865269),
                    dict(good, channel='d1|x>'), dict(good, inside='yes'), dict(good, extra='Open chat thread: <https://evil.invalid|x>'),
                    {'line': 'Open chat thread: <https://evil.invalid|Open chat thread>'}, 'Open chat thread: <https://evil.invalid|x>']:
            with self.assertRaises(ValueError, msg=bad):
                h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex', thread=bad,
                          allowed_hosts={'chat.example.invalid'})
        for bad in [{'root_ts': 1}, 'x']:
            with self.assertRaises(ValueError):
                n.thread_line(bad)
        forged_link = dict(good, permalink={'url': 'https://chat.example.invalid/archives/D1/p1790819911865269', 'host': 'chat.example.invalid',
                                            'receipt': {'source': 'connector', 'field': 'permalink', 'sha256': '0' * 64, 'binding': 'x'}})
        self.assertEqual(n.thread_line(forged_link, {'chat.example.invalid'}), 'Open chat thread: reply in this thread')

    def test_index_fallback_names_the_app_and_thread_without_a_link_or_details(self):
        th = n.thread(ROOT, channel='D1', inside=True, chat='Team Chat')
        s = h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex', thread=th)
        line = h.render_index([s])
        self.assertIn('Open Team Chat thread: in Team Chat, the thread started 2026-10-01 01:58 UTC (no link here)', line)
        self.assertNotIn('<', line.split('Open Team Chat thread')[1])
        linked = h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex', allowed_hosts={'chat.example.invalid'},
                           thread=n.thread(ROOT, channel='D1', inside=True, permalink=self.permalink()))
        self.assertTrue(h.render_index([linked]).endswith('|Open chat thread>'))
        none = h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex')
        self.assertTrue(h.render_index([none]).endswith('Open chat thread: no thread yet'))

    def test_the_chat_app_name_comes_from_the_caller(self):
        self.assertEqual(item(thread=n.thread(ROOT, channel='D1', inside=True, chat='Team Chat'))[5], 'Open Team Chat thread: reply in this thread')
        for bad in ['x|y>', 'chat\nNext: ok', '']:
            with self.assertRaises(ValueError):
                n.thread(ROOT, channel='D1', inside=True, chat=bad)

    def test_a_reply_in_the_thread_still_cannot_approve(self):
        e, why = c.reply_event(reply('yes'), thread(), blocked(), human_user_id=HUMAN, sent_ts={SUMMARY}, workspace=WS)
        r, o = t.apply(blocked(), e)
        self.assertEqual((why, o, r['approvals'], r['status']), ('proposes-approval', 'noted', [], 'blocked'))


class WorkspaceLifecycleTests(unittest.TestCase):
    def test_native_workspace_capabilities_fail_closed_and_never_mutate(self):
        unknown = n.workspace_lifecycle_assessment({
            'visibility': {'state': 'unknown', 'receipt_ref': None},
            'grouping': {'state': 'unavailable', 'receipt_ref': 'native:no-grouping-api'},
            'archive': {'state': 'unknown', 'receipt_ref': None}})
        self.assertEqual((unknown['visibility'], unknown['grouping'], unknown['archive']),
                         ('unverified', 'unverified', 'unverified'))
        self.assertEqual((unknown['actions'], unknown['mutated']), ([], False))
        verified = n.workspace_lifecycle_assessment({
            'visibility': {'state': 'verified', 'receipt_ref': 'native:visible-read-1'},
            'grouping': {'state': 'verified', 'receipt_ref': 'native:group-read-1'},
            'archive': {'state': 'verified', 'receipt_ref': 'native:archive-capability-1'}})
        self.assertEqual((verified['visibility'], verified['grouping'], verified['archive']),
                         ('verified', 'verified', 'available'))
        self.assertEqual((verified['actions'], verified['mutated']), ([], False))
        with self.assertRaises(ValueError):
            n.workspace_lifecycle_assessment({
                'visibility': {'state': 'verified', 'receipt_ref': None},
                'grouping': {'state': 'unknown', 'receipt_ref': None},
                'archive': {'state': 'unknown', 'receipt_ref': None}})


class ChannelBindingTests(unittest.TestCase):
    def event(self, msg, th, task=None):
        return c.reply_event(msg, th, task or blocked(), human_user_id=HUMAN, sent_ts={SUMMARY}, workspace=WS)

    def test_identical_roots_in_two_channels_stay_separate(self):
        a, b = thread(destination='D1'), thread(destination='C2')
        self.assertIs(c.thread_for_reply(reply('yes', channel='D1'), [b, a], workspace=WS), a)
        self.assertIs(c.thread_for_reply(reply('yes', channel='C2'), [a, b], workspace=WS), b)
        self.assertIsNone(c.thread_for_reply(reply('yes', channel='C3'), [a, b], workspace=WS))
        self.assertEqual(self.event(reply('yes', channel='C2'), a), (None, 'other-thread'))
        ea, _ = self.event(reply('yes', channel='D1'), a)
        eb, _ = self.event(reply('yes', channel='C2'), b)
        self.assertNotEqual(ea['id'], eb['id'])
        self.assertEqual(ea['id'], f'thread:{WS}:D1:{ROOT}:1790820100.000200')

    def test_identical_roots_in_two_workspaces_stay_separate(self):
        home, away = thread(), thread(workspace='T2')
        self.assertIs(c.thread_for_reply(reply('yes'), [away, home], workspace=WS), home)
        self.assertIsNone(c.thread_for_reply(reply('yes', team='T2'), [home], workspace=WS))
        self.assertEqual(self.event(reply('yes', team='T2'), home), (None, 'other-thread'))
        self.assertEqual(self.event(reply('yes'), away), (None, 'other-thread'))
        self.assertEqual(self.event(reply('yes', team=WS), home)[1], 'proposes-approval')

    def test_missing_or_legacy_channel_fails_closed(self):
        legacy = {k: v for k, v in thread().items() if k != 'destination'}
        for msg, th in [(reply('yes', channel=None), thread()), (reply('yes', channel=''), thread()),
                        (reply('yes'), legacy), (reply('yes'), thread(destination=None)),
                        (reply('yes', thread_ts=float(ROOT)), thread()), (reply('yes'), thread(root_ts=float(ROOT)))]:
            self.assertEqual(self.event(msg, th), (None, 'other-thread'), (msg, th))
        self.assertIsNone(c.thread_for_reply(reply('yes'), [legacy], workspace=WS))
        self.assertIsNone(c.thread_for_reply(reply('yes', channel=None), [thread()], workspace=WS))

    def test_records_from_before_the_workspace_field_still_read(self):
        old = {'work_item': 'x', 'destination': 'D1', 'root_ts': ROOT, 'last_summary_ts': SUMMARY,
               'shown_pending': thread()['shown_pending'], 'status': 'needs-human'}
        self.assertIs(c.thread_for_reply(reply('yes'), [old], workspace=WS), old)
        self.assertEqual(self.event(reply('yes'), old)[1], 'proposes-approval')

    def test_replays_and_out_of_order_replies_dedupe_per_channel(self):
        a, b = thread(destination='D1'), thread(destination='C2')
        r = blocked()
        early, _ = self.event(reply('more context', ts='1790820100.000200', channel='D1'), a)
        late, _ = self.event(reply('yes', ts='1790820150.000200', channel='D1'), a)
        other, _ = self.event(reply('yes', ts='1790820100.000200', channel='C2'), b)
        outcomes = []
        for e in [late, early, late, other, early]:
            r, o = t.apply(r, e)
            outcomes.append(o)
        # the later yes stands; the earlier reply arriving late is stale, a replay is a duplicate
        self.assertEqual(outcomes, ['noted', 'stale', 'duplicate', 'stale', 'stale'])
        self.assertEqual((r['proposal']['approve'], r['proposal']['ts']), (True, '1790820150.000200'))
        self.assertEqual(r['approvals'], [])
        self.assertEqual(r['status'], 'blocked')

    def test_bot_replies_ignore_other_channels(self):
        pages = [[{'ts': '1790803103.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'answer', 'channel': 'C2'},
                  {'ts': '1790803104.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'right one', 'channel': 'D1'}]]
        hits = c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1', workspace=WS)
        self.assertEqual([m['text'] for m in hits], ['right one'])
        with self.assertRaises(TypeError):  # no unscoped matching on the root alone
            c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1')  # no workspace
        bare = [[{'ts': '1790803104.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'no channel'}]]
        self.assertEqual(c.match_replies(bare, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1', workspace=WS), [])
        for ch in (None, ''):
            self.assertEqual(c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel=ch, workspace=WS), [])

    def test_bot_replies_bind_the_workspace_of_the_read(self):
        pages = [[{'ts': '1790803104.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'away', 'channel': 'D1', 'team': 'T2'},
                  {'ts': '1790803105.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'home', 'channel': 'D1', 'team': WS},
                  {'ts': '1790803106.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'read here', 'channel': 'D1'}]]
        # identical channel and root in another workspace never match; a message without team was read in WS
        self.assertEqual([m['text'] for m in c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1', workspace=WS)],
                         ['home', 'read here'])
        self.assertEqual([m['text'] for m in c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1', workspace='T2')],
                         ['away', 'read here'])
        for ws in (None, ''):
            self.assertEqual(c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1', workspace=ws), [])
        # the workspace never comes from message text
        texty = [[{'ts': '1790803107.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'team: T1', 'channel': 'D1', 'team': 'T2'}]]
        self.assertEqual(c.match_replies(texty, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1', workspace=WS), [])

    def test_bot_reply_timestamps_must_be_strings(self):
        for sent, root in [(1790803000.0, ROOT), ('1790803000.0', float(ROOT)), ('1790803000.0', ''), ('', ROOT)]:
            with self.assertRaises(ValueError):
                c.match_replies([[]], BOT, sent, None, root_ts=root, channel='D1', workspace=WS)

    def test_non_string_message_ts_fails_closed_in_every_path(self):
        pages = [[{'ts': 1790803104.6, 'user': BOT, 'thread_ts': ROOT, 'text': 'float', 'channel': 'D1'},
                  {'ts': '1790803105.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'string', 'channel': 'D1'}]]
        self.assertEqual([m['text'] for m in c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1', workspace=WS)],
                         ['string'])
        msg = reply('yes', ts=1790820100.0002)
        self.assertEqual(c.reply_event(msg, thread(), blocked(), human_user_id=HUMAN, sent_ts={SUMMARY}, workspace=WS),
                         (None, 'other-thread'))

    def test_same_ts_bot_replies_in_two_channels_do_not_collapse(self):
        pages = [[{'ts': '1790803104.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'here', 'channel': 'D1'},
                  {'ts': '1790803104.6', 'user': BOT, 'thread_ts': ROOT, 'text': 'there', 'channel': 'C2'}]]
        self.assertEqual([m['text'] for m in c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel='D1', workspace=WS)], ['here'])
        self.assertEqual([m['text'] for m in c.match_replies(pages, BOT, '1790803000.0', None, root_ts=ROOT, channel='C2', workspace=WS)], ['there'])


class ThreadReplyTests(unittest.TestCase):
    def event(self, msg, th=None, task=None, sent=None):
        return c.reply_event(msg, th or thread(), task or blocked(), human_user_id=HUMAN, sent_ts=sent or {SUMMARY}, workspace=WS)

    def test_a_typed_yes_is_only_a_proposal_and_the_hub_says_so(self):
        e, why = self.event(reply('Yes'))
        self.assertEqual((why, e['source'], e['kind'], e['data']['action']), ('proposes-approval', 'thread', 'proposal', 'publish as a draft PR'))
        r, o = t.apply(blocked(), e)
        self.assertEqual((o, r['status'], r['approvals']), ('noted', 'blocked', []))
        self.assertFalse(t.approved(r, 'publish as a draft PR', 'fix branch, no deployment'))
        nxt = h.summary(r, title='Fix', result='Ready', owner='Codex', label='Codex')['next']
        self.assertIn('A thread reply proposes approving', nxt)
        self.assertIn('Not recorded: confirm it in the session chat.', nxt)

    def test_the_users_chat_turn_then_records_the_exact_approval(self):
        r, _ = t.apply(blocked(), self.event(reply('yes'))[0])
        e = {'id': 'chat-1', 'task': 'wi-1', 'ts': '1790820200', 'source': 'user', 'kind': 'decided',
             'data': dict(CHAT, approve=True, action='publish as a draft PR', target='fix branch, no deployment')}
        r, o = t.apply(r, e)
        self.assertEqual((o, r['status'], r['proposal']), ('applied', 'awaiting-worker', None))
        self.assertTrue(t.approved(r, 'publish as a draft PR', 'fix branch, no deployment'))

    def test_direct_thread_injection_never_decides(self):
        base = {'task': 'wi-1', 'ts': '1790820200', 'kind': 'decided'}
        for i, (source, data) in enumerate([
                ('user', {'channel': 'thread-human', 'text': 'yes', 'approve': True, 'action': 'publish as a draft PR', 'target': 'fix branch, no deployment'}),
                ('user', {'channel': 'thread', 'text': 'no'}),
                ('thread', {'channel': 'chat', 'text': 'yes', 'approve': True, 'action': 'publish as a draft PR', 'target': 'fix branch, no deployment'})]):
            r, o = t.apply(blocked(), dict(base, id=f'x{i}', source=source, data=data))
            self.assertNotEqual(o, 'applied', (source, data))
            self.assertEqual((r['status'], r['approvals']), ('blocked', []))
        self.assertEqual(t.apply(blocked(), dict(base, id='p', source='user', kind='proposal', data={'approve': True}))[1], 'rejected')

    def test_app_posted_forged_and_bot_yes_route_nowhere(self):
        for msg in [reply('yes', user=BOT), reply('yes\n*Sent using* <@U0000000000|ChatGPT>'), reply('yes', app='Claude'),
                    reply('yes', app_id='A1'), reply('yes', bot_id='B1'), reply('yes', subtype='bot_message'),
                    reply('yes', ts=SUMMARY), reply('No, decline. Sentusing x'), reply('ok \uff33\uff45\uff4e\uff54 \uff55\uff53\uff49\uff4e\uff47')]:
            self.assertEqual(self.event(msg), (None, 'not-typed-by-user'), msg)

    def test_a_spoofed_typed_yes_still_cannot_approve(self):
        # a worker on the shared account can omit the attribution line; the yes stays a proposal
        e, why = self.event(reply('yes'))
        r, _ = t.apply(blocked(), e)
        self.assertEqual((why, r['approvals'], r['status']), ('proposes-approval', [], 'blocked'))

    def test_only_a_plain_yes_proposes_approval(self):
        for text in ['yes', 'Yes.', 'yes!!!', '  Approve ', 'go ahead!']:
            self.assertEqual(self.event(reply(text))[1], 'proposes-approval', text)
        for text in ['yes?', 'approve?', 'Approved?!', 'YES 👍', 'yes, but deploy too', 'y e s', 'no, wait']:
            self.assertEqual(self.event(reply(text))[1], 'context', text)

    def test_exact_thread_correlation_and_freshness(self):
        self.assertEqual(self.event(reply('yes', thread_ts='1790800000.000001')), (None, 'other-thread'))
        self.assertEqual(self.event(reply('yes', ts='1790819950.000000')), (None, 'before-summary'))
        self.assertEqual(self.event(reply('yes'), task=blocked(target='fix branch and deploy')), (None, 'summary-out-of-date'))
        q = blocked()
        q['pending_decision'] = {'need': 'Which schema?', 'action': None, 'target': None}
        self.assertEqual(self.event(reply('v2'), th=thread(shown_pending={'need': 'Which branch?', 'action': None, 'target': None}), task=q),
                         (None, 'summary-out-of-date'))
        done = blocked()
        done.update(status='running', pending_decision=None)
        self.assertEqual(self.event(reply('yes'), task=done), (None, 'nothing-pending'))
        a, b = thread(root_ts=ROOT), thread(root_ts='1790802545.583229')
        self.assertIs(c.thread_for_reply(reply('yes'), [b, a], workspace=WS), a)
        self.assertIsNone(c.thread_for_reply(reply('yes', thread_ts=None), [a, b], workspace=WS))
        with self.assertRaises(ValueError):
            c.thread_for_reply(reply('yes'), [a, dict(a)], workspace=WS)

    def test_a_proposal_from_before_the_current_ask_is_stale(self):
        old = self.event(reply('yes', ts='1790820100.000200'))[0]
        r = blocked()
        r['last_change_ts'] = '1790820150'  # declined and re-asked after that reply
        r, o = t.apply(r, old)
        self.assertEqual((o, r.get('proposal')), ('stale', None))
        self.assertNotIn('proposes approving', h.next_step(r, where='the session chat'))

    def test_a_new_decision_clears_an_old_proposal(self):
        r, _ = t.apply(blocked(), self.event(reply('yes'))[0])
        r['status'] = 'running'
        r, o = t.apply(r, {'id': 'b2', 'task': 'wi-1', 'ts': '1790820300', 'source': 'worker', 'kind': 'blocked',
                           'data': {'need': '?', 'action': 'publish as a draft PR', 'target': 'fix branch, no deployment'}})
        self.assertEqual((o, r['proposal']), ('applied', None))

    def test_sent_ts_must_be_strings_and_match_numerically(self):
        with self.assertRaises(ValueError):
            self.event(reply('yes'), sent={1790820100.0002})
        self.assertEqual(self.event(reply('yes', ts='1790820100.0002'), sent={'1790820100.000200'}), (None, 'not-typed-by-user'))

    def test_replays_of_the_same_reply_are_duplicates(self):
        e, _ = self.event(reply('yes'))
        r, _ = t.apply(blocked(), e)
        self.assertEqual(t.apply(r, e)[1], 'duplicate')

    def test_roots_on_the_user_account_are_never_planned_as_edits(self):
        s = h.summary(blocked(), title='Fix', result='Ready', owner='Codex', label='Codex')
        self.assertEqual(h.plan_update({'root_ts': ROOT, 'root_author': HUMAN, 'last_fp': 'x'}, s, editable_authors=(BOT,)), 'reply')


if __name__ == '__main__':
    unittest.main()
