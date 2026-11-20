"""`issues-cli feed`: rows from a feed become inbox issues, deduped by Source-key (conveyor.md § Feeds)."""
import io
import json
import re
import unittest.mock

from agent_skills import feeds, issues_cli
from test_issues_cli import REPO
from test_issues_cli_conveyor import BeltCase, CONVEYOR

HEARTBEAT = re.compile(CONVEYOR['feeds']['heartbeat']['pattern'])
FEED = {'id': 'test-feed', 'kind': 'alert', 'key_fields': ['channel', 'ts'], 'priority': 'prio:now',
        'enabled': True, 'max_new': 2}


def row(ts, summary='Disk almost full', channel='C1', **extra):
    return {'channel': channel, 'ts': ts, 'summary': summary, 'link': f'https://x.test/{channel}/{ts}', **extra}


class FeedCase(BeltCase):
    def setUp(self):
        super().setUp()
        feeds_config = json.loads(json.dumps(issues_cli.belt()['feeds']))
        feeds_config['entries'] = [FEED, {**FEED, 'id': 'off-feed', 'enabled': False}]
        patched = unittest.mock.patch.dict(issues_cli.belt(), {'feeds': feeds_config})
        patched.start()
        self.addCleanup(patched.stop)

    def feed(self, name, rows, *extra, ok=True):
        stdin = io.StringIO(''.join(json.dumps(r) + '\n' for r in rows))
        with unittest.mock.patch('sys.stdin', stdin):
            return self.cli('feed', '--repo', REPO, name, *extra, ok=ok)

    def beat(self, out):
        [line] = [x for x in out.split('\n') if x.startswith('Feed:')]
        self.assertRegex(line, HEARTBEAT)
        return HEARTBEAT.match(line)


class Intake(FeedCase):
    def test_a_new_row_makes_one_inbox_issue_with_summary_link_and_key(self):
        out = self.feed('test-feed', [row('1', free_text='customer name and number')])
        self.assertEqual(len(self.gh.issues), 1)
        body = self.gh.issues[1]['body']
        self.assertEqual(self.gh.lane(1), 'inbox')
        self.assertIn('prio:now', self.gh.names(1))
        self.assertIn('Disk almost full\nhttps://x.test/C1/1\nSource-key: ' + feeds.source_key(FEED, row('1')), body)
        self.assertRegex(body, r'\n\nCaptured: .+ · source https://x.test/C1/1\n$')
        self.assertNotIn('customer', body)
        m = self.beat(out)
        self.assertEqual((m['id'], m['new'], m['updated'], m['skipped']), ('test-feed', '1', '0', '0'))

    def test_an_unchanged_key_does_nothing_even_when_closed(self):
        self.feed('test-feed', [row('1')])
        self.gh.close(1)
        self.gh.calls.clear()
        out = self.feed('test-feed', [row('1')])
        self.assertEqual(self.gh.writes(), [])
        self.assertEqual(len(self.gh.issues), 1)
        self.assertEqual(self.beat(out)['skipped'], '1')

    def test_a_changed_summary_adds_one_comment_and_never_a_new_issue_or_a_close(self):
        self.feed('test-feed', [row('1')])
        self.gh.close(1)
        out = self.feed('test-feed', [row('1', 'Disk full')])
        self.assertEqual(len(self.gh.issues), 1)
        self.assertEqual(self.gh.issues[1]['state'], 'CLOSED')
        updates = [c['body'] for c in self.gh.issues[1]['comments'] if c['body'].startswith('Source updated:')]
        self.assertEqual(len(updates), 1)
        self.assertIn('Disk full', updates[0])
        self.assertEqual(self.beat(out)['updated'], '1')
        self.gh.calls.clear()
        self.feed('test-feed', [row('1', 'Disk full')])  # the update is now the known summary
        self.assertEqual(self.gh.writes(), [])

    def test_the_key_ignores_row_order_and_extra_fields(self):
        a = feeds.source_key(FEED, {'ts': '1', 'channel': 'C1', 'summary': 'a', 'link': 'l'})
        b = feeds.source_key(FEED, {'link': 'other', 'channel': 'C1', 'extra': 1, 'ts': '1', 'summary': 'b'})
        self.assertEqual(a, b)
        self.assertNotEqual(a, feeds.source_key(FEED, row('2')))

    def test_reordered_rows_create_no_second_issue(self):
        self.feed('test-feed', [row('1'), row('2', 'B')])
        out = self.feed('test-feed', [row('2', 'B'), row('1')])
        self.assertEqual(len(self.gh.issues), 2)
        self.assertEqual(self.beat(out)['skipped'], '2')

    def test_the_cap_stops_new_issues_and_reports_the_rest_skipped(self):
        out = self.feed('test-feed', [row(str(k), f'alert {k}') for k in range(5)])
        self.assertEqual(len(self.gh.issues), 2)
        m = self.beat(out)
        self.assertEqual((m['new'], m['skipped']), ('2', '3'))

    def test_a_repeated_key_in_one_run_is_one_issue(self):
        out = self.feed('test-feed', [row('1'), row('1')])
        self.assertEqual(len(self.gh.issues), 1)
        self.assertEqual(self.beat(out)['skipped'], '1')

    def test_row_priority_overrides_the_default(self):
        self.feed('test-feed', [row('1', priority='next')])
        self.assertIn('prio:next', self.gh.names(1))
        self.assertNotIn('prio:now', self.gh.names(1))


class Refusals(FeedCase):
    def test_an_unknown_feed_is_refused(self):
        out = self.feed('nope', [row('1')], ok=False)
        self.assertIn('unknown feed nope', out)
        self.assertEqual(self.gh.calls, [])

    def test_a_disabled_feed_is_refused(self):
        out = self.feed('off-feed', [row('1')], ok=False)
        self.assertIn('off-feed is disabled', out)
        self.assertEqual(self.gh.calls, [])

    def test_a_row_missing_a_key_field_or_with_a_bad_shape_refuses_the_whole_run(self):
        for bad in ({'ts': '1', 'summary': 's', 'link': 'https://x.test/1'},
                    row('2', 'two\nlines'), row('2', ''), {**row('2'), 'link': 'has space'},
                    row('2', priority='urgent'), row('2', 's' * 500)):
            out = self.feed('test-feed', [row('1'), bad], ok=False)
            self.assertIn('row 2', out)
        self.assertEqual(self.gh.calls, [])

    def test_the_shipped_mail_feed_is_off_and_needs_no_mailbox_label(self):
        shipped = {e['id']: e for e in CONVEYOR['feeds']['entries']}
        self.assertTrue(shipped['chat-alerts']['enabled'])
        self.assertFalse(shipped['mail']['enabled'])
        self.assertNotIn('label', json.dumps(shipped['mail']))
        self.assertEqual(shipped['chat-alerts']['priority'], 'prio:now')


class DryRun(FeedCase):
    def test_dry_run_prints_the_writes_and_makes_none(self):
        out = self.feed('test-feed', [row('1')], '--dry-run')
        self.assertEqual(self.gh.writes(), [])
        self.assertIn('gh issue create', out)
        self.assertEqual(self.beat(out)['new'], '1')

    def test_the_heartbeat_goes_to_the_log_only_on_a_real_run(self):
        self.feed('test-feed', [row('1')], '--dry-run', '--log', str(self.log))
        self.assertNotIn('Feed:', self.log.read_text())
        self.feed('test-feed', [row('2')], '--log', str(self.log))
        self.assertEqual(len(re.findall(r'^Feed: ', self.log.read_text(), re.M)), 1)
