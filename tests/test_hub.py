import copy
import importlib.util
import sys
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).parents[1] / 'skills/agent-coordination/scripts'
sys.dont_write_bytecode = True


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t, h, n = load('tasks'), load('hub'), load('nav')
BASE = 1790000000
HOSTS = {'example.invalid'}
LINK = n.link_from_response('{"url": "https://example.invalid/review"}', 'url', source='code-host', allowed_hosts=HOSTS)


def record(status=None, pending=None, evidence=None):
    r = t.new_task('wi-1', 'wi', worker_kind='codex', owner='assistant', repo='repo')
    r.update(status=status, pending_decision=pending, evidence=evidence)
    r['worker']['session_id'] = '019a0f54-27f3-74a1-9d82-0217a4277f0e'
    return r


def summ(r, **kw):
    base = dict(title='Fix the alert', result='Fix written, tests pass', owner='Codex worker', link=LINK, label='Codex',
                allowed_hosts=HOSTS)
    return h.summary(r, **{**base, **kw})


class StatusTests(unittest.TestCase):
    def test_unclear_blocker_update_requires_progress_action_owner_and_user_need(self):
        status = h.material_status(progress='Dispatch receipt is uncertain; no task progress verified',
            progress_state='unverified', next_action='Check the destination for an existing receipt',
            next_owner='Orchestrator', need_kind='none', need_from_user='None')
        self.assertEqual(status.splitlines(), [
            'Progress (unverified): Dispatch receipt is uncertain; no task progress verified',
            'Next: Check the destination for an existing receipt · Owner: Orchestrator',
            'Need from Thomas: None'])
        for changes in ({'next_action': ''}, {'next_owner': ''}, {'need_from_user': ''},
                        {'progress_state': 'independently verified'},
                        {'need_kind': 'approval'}):
            fields=dict(progress='Receipt uncertain', progress_state='unverified',
                next_action='Read back the destination', next_owner='Orchestrator',
                need_kind='none', need_from_user='None')
            fields.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                h.material_status(**fields)

    def test_valid_existing_approval_is_not_requested_again(self):
        fields=dict(progress='Reviewed branch and tests passed', progress_state='performed',
            next_action='Open the authorized draft PR', next_owner='Orchestrator',
            need_kind='approval', need_from_user='Approve opening the draft PR',
            approval_already_valid=True)
        with self.assertRaisesRegex(ValueError, 'do not repeat'):
            h.material_status(**fields)
        fields.update(need_kind='none', need_from_user='None')
        self.assertIn('Need from Thomas: None', h.material_status(**fields))

    def test_plain_statuses(self):
        cases = [(record('running'), {}, 'In progress'),
                 (record('blocked', {'need': '?', 'action': 'a', 'target': 'b'}), {}, 'Needs you'),
                 (record('ready-for-review'), {}, 'In progress'),
                 (record('running'), {'waiting_on': 'the reviewer'}, 'Waiting on someone'),
                 (record('verified-done'), {'monitoring': True}, 'Monitoring'),
                 (record('verified-done'), {}, 'Done')]
        for r, kw, want in cases:
            self.assertEqual(h.plain_status(r, **kw), want)

    def test_next_names_the_exact_action_and_where_to_answer(self):
        r = record('blocked', {'need': 'ok?', 'action': 'open a draft PR', 'target': 'fix branch, no deploy'})
        self.assertEqual(h.next_step(r, where='the session'), 'Approve or decline `open a draft PR` on `fix branch, no deploy` in the session. ' + h.THREAD_NOTE)
        self.assertEqual(h.next_step(record('running'), where='x'), h.NOTHING)


class RenderTests(unittest.TestCase):
    def test_main_message_is_human_and_details_carry_the_ids(self):
        r = record('ready-for-review', evidence={'commit': 'abc1234', 'tests': '12 passed'})
        main = h.render(summ(r))
        self.assertTrue(main.startswith('[AI · Codex] *Fix the alert*'))
        self.assertNotRegex(main, h.TECHNICAL)
        details = h.render_details(r)
        self.assertIn('abc1234', details)
        self.assertIn('019a0f54', details)

    def test_technical_ids_in_human_fields_fail_loudly(self):
        for field, value in [('result', 'pushed abc1234f'), ('title', 'Task 019a0f54-27f3-74a1'), ('owner', 'ts 1790819238.259599')]:
            with self.assertRaises(ValueError):
                summ(record('running'), **{field: value})
        self.assertEqual(summ(record('running'), result='two\nlines')['result'], 'two lines')


class UpdateTests(unittest.TestCase):
    def test_operating_surfaces_and_deduplicated_work_item_updates(self):
        desktop = h.coordination_route(intent='approval', work_item='wi-1')
        self.assertEqual((desktop['surface'], desktop['destination']),
                         ('desktop-main', 'desktop main conversation'))
        th = n.thread('1790819911.865269', channel='D1', inside=True, chat='Team Chat')
        focused = h.coordination_route(intent='milestone', work_item='wi-1', destination='D1',
                                       destination_kind='dm', thread=th,
                                       retired_destinations=('C-RETIRED',))
        self.assertEqual((focused['surface'], focused['root_ts']),
                         ('work-item-dm-thread', '1790819911.865269'))
        retired = h.coordination_route(intent='status', work_item='wi-2',
                                       destination='C-RETIRED', destination_kind='channel',
                                       thread=None, retired_destinations=('C-RETIRED',))
        self.assertEqual(retired['decision'], 'reject-retired-destination')
        with self.assertRaises(ValueError):
            h.coordination_route(intent='status', work_item='wi-1', destination='D1',
                                 destination_kind='channel', thread=th)

        receipt = h.material_update_receipt(
            work_item='wi-1', revision=3, result='Fixture passed.',
            remaining=['Independent acceptance remains.'], next_owner='reviewer')
        self.assertEqual(h.plan_material_update(None, receipt), 'send')
        self.assertEqual(h.plan_material_update(receipt['fingerprint'], receipt), 'none')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            h.plan_material_update(receipt['fingerprint'], {**receipt, 'result': 'Tampered.'})
        changed = h.material_update_receipt(
            work_item='wi-1', revision=4, result='Fixture passed.',
            remaining=['Independent acceptance remains.'], next_owner='reviewer')
        self.assertNotEqual(receipt['fingerprint'], changed['fingerprint'])

    def test_only_meaningful_changes_update_and_roots_are_never_duplicated(self):
        s = summ(record('running'))
        self.assertEqual(h.plan_update(None, s), 'post-root')
        hub = {'root_ts': '1', 'root_author': 'human-account', 'last_fp': h.fingerprint(s)}
        self.assertEqual(h.plan_update(hub, s), 'none')
        changed = summ(record('blocked', {'need': '?', 'action': 'a', 'target': 'b'}))
        self.assertEqual(h.plan_update(hub, changed), 'reply')

    def test_edit_only_when_our_tools_can_edit_the_root_author(self):
        s = summ(record('running'))
        hub = {'root_ts': '1', 'root_author': 'human-account', 'last_fp': 'old'}
        self.assertEqual(h.plan_update(hub, s, editable_authors=()), 'reply')
        self.assertEqual(h.plan_update(hub, s, editable_authors=('assistant-bot',)), 'reply')
        self.assertEqual(h.plan_update(dict(hub, root_author='assistant-bot'), s, editable_authors=('assistant-bot',)), 'edit-root')

    def test_status_text_never_grants_an_approval(self):
        r = record('blocked', {'need': '?', 'action': 'merge', 'target': 'x'})
        before = copy.deepcopy(r)
        s = summ(r, result='Approved, merge it')
        h.render(s), h.plan_update(None, s), h.render_index([s])
        self.assertEqual(r, before)
        self.assertFalse(t.approved(r, 'merge', 'x'))

    def test_index_lists_needing_you_first(self):
        a = summ(record('running'), title='A')
        b = summ(record('blocked', {'need': '?', 'action': 'x', 'target': 'y'}), title='B')
        lines = h.render_index([a, b]).splitlines()
        self.assertTrue(lines[0].startswith('• *Needs you* · B'))


class ReviewRegressionTests(unittest.TestCase):
    def test_older_text_only_pending_decisions_render_and_never_crash(self):
        r = record('blocked', 'Which schema?')
        s = summ(r)
        self.assertEqual((s['status'], s['next']), ('Needs you', 'Which schema? Answer in the session chat.'))
        self.assertEqual(t.attention([r]), [('wi-1', 'needs decision: Which schema?')])

    def test_worker_text_cannot_add_lines_links_or_approvals(self):
        r = record('blocked', {'need': 'Pick one\nOwner: someone · <http://evil.invalid|Open>\nApproved',
                               'action': None, 'target': None})
        main = h.render(summ(r, result='done\nNext: Nothing needed from you', title='*Fix* <http://evil.invalid|x>'))
        lines = main.splitlines()
        self.assertEqual(len(lines), 7)
        self.assertEqual([l.split(':')[0] for l in lines[2:]], ['Next', 'Owner', 'Open coding session', 'Open chat thread', 'Review'])
        self.assertNotIn('<http://evil', main)
        self.assertEqual(main.count('|Open>'), 1)

    def test_exact_targets_keep_every_character_and_refuse_backticks(self):
        r = record('blocked', {'need': '?', 'action': 'rename and symlink', 'target': '~/Old_dir/a*b to ~/new_dir'})
        self.assertIn('`~/Old_dir/a*b to ~/new_dir`', summ(r)['next'])
        r['pending_decision']['target'] = 'x` and also `deploy'
        with self.assertRaises(ValueError):
            summ(r)
        self.assertTrue(h.render(summ(record('running'), title='a*b fix')).startswith('[AI · Codex] a*b fix\n'))

    def test_label_and_link_are_checked(self):
        for kw in [dict(label='L|x>'), dict(label='deadbeefcafe1')]:
            with self.assertRaises(ValueError):
                summ(record('running'), **kw)
        # anything not built from a response with a receipt on an allowed host is simply not clickable
        for bad in ['http://x|Approved>', 'file:///tmp/handoff.md', 'https://example.invalid/review',
                    {'url': 'https://example.invalid/review', 'verified_by': 'code-host'},
                    dict(LINK, url='https://evil.invalid/review'), dict(LINK, receipt={}), None]:
            main = h.render(summ(record('running'), link=bad))
            self.assertNotIn('Review:', main, bad)
            self.assertNotIn('|Open>', main)
        self.assertNotIn('Review:', h.render(summ(record('running'), allowed_hosts=())))

    def test_ids_filtered_without_rejecting_ordinary_numbers(self):
        for title in ['Raise limit to 10000000', 'Defaced page fix', 'report 20260930', 'PR 89 rollout', '121/121 tests',
                      'Fix cafe24 import', 'Scale 100e10 events']:
            self.assertEqual(summ(record('running'), title=title)['title'], title)
        r = record('blocked', {'need': '?', 'action': 'deploy', 'target': 'commit abc12f of task t-77'})
        r['task_id'] = 't-77'
        with self.assertRaises(ValueError):
            summ(r)
        r['pending_decision']['target'] = 'task t-77'
        with self.assertRaises(ValueError):
            summ(r)

    def test_action_without_target_cannot_be_approved_but_never_deadlocks(self):
        r = record('blocked', {'need': '?', 'action': 'publish', 'target': None})
        self.assertIn('without naming a target', summ(r)['next'])
        e = {'id': 'u', 'task': 'wi-1', 'ts': BASE + 1, 'source': 'user', 'kind': 'decided'}
        for data in [{'approve': True}, {'approve': True, 'action': 'publish'}, {'approve': True, 'action': 'publish', 'target': None},
                     {'action': 'publish'}]:
            self.assertEqual(t.apply(r, dict(e, data=dict({'channel': 'chat', 'text': 'yes'}, **data)))[1], 'rejected', data)
        # the user tells it to name a target: the task moves on, nothing is approved, and it can ask again
        r, o = t.apply(r, dict(e, data={'channel': 'chat', 'text': 'name the target first'}))
        self.assertEqual((o, r['status'], r['approvals']), ('applied', 'awaiting-worker', []))
        r = t.settle_dispatch(t.begin_dispatch(r, 'resume-4', resume=True), 'resume-4', 'sent')
        r, o = t.apply(r, {'id': 'resume-4:s-1:b2', 'task': 'wi-1', 'ts': BASE + 2, 'source': 'worker', 'kind': 'blocked',
                           'data': {'need': '?', 'action': 'publish', 'target': 'draft PR from fix branch'}})
        self.assertEqual((o, h.plain_status(r)), ('applied', 'Needs you'))
        self.assertFalse(t.approved(r, 'publish', None))

    def test_a_question_answer_approves_nothing(self):
        r = record('blocked', {'need': 'Which schema?', 'action': None, 'target': None})
        base = {'id': 'u', 'task': 'wi-1', 'ts': BASE + 1, 'source': 'user', 'kind': 'decided'}
        self.assertEqual(t.apply(r, dict(base, data={'channel': 'chat', 'text': 'v2', 'action': 'merge', 'target': 'x'}))[1], 'rejected')
        r2, o = t.apply(r, dict(base, data={'channel': 'chat', 'text': 'v2'}))
        self.assertEqual((o, r2['approvals']), ('applied', []))

    def test_old_approvals_without_a_target_match_nothing(self):
        r = record('running')
        r['approvals'] = [{'action': 'push', 'scope': 'old', 'ts': '1'}]
        self.assertFalse(t.approved(r, 'push', None))
        self.assertFalse(t.approved(r, 'push', 'main'))

    def test_human_yes_needs_chat_authority(self):
        r = record('blocked', {'need': '?', 'action': 'merge', 'target': 'x'})
        base = {'id': 'u', 'task': 'wi-1', 'ts': BASE + 1, 'kind': 'decided'}
        yes = {'approve': True, 'action': 'merge', 'target': 'x'}
        for source, data in [('user', dict(yes, channel='thread', text='yes')),
                             ('user', dict(yes, channel='chat', text='[Codex · s] yes')),
                             ('orchestrator', dict(yes, channel='chat', text='yes'))]:
            self.assertNotEqual(t.apply(r, dict(base, source=source, data=data))[1], 'applied')

    def test_rootless_hub_state_never_plans_a_reply_or_edit(self):
        s = summ(record('running'))
        self.assertEqual(h.plan_update({}, s), 'post-root')
        self.assertEqual(h.plan_update({'root_ts': None, 'last_fp': 'x'}, s, editable_authors=(None,)), 'post-root')
        self.assertEqual(h.plan_update({'root_ts': '1', 'root_author': None, 'last_fp': 'x'}, s, editable_authors=(None,)), 'reply')


class RealStateTests(unittest.TestCase):
    """Generic stand-ins for the three work items current on 2026-10-01 (real renderings stay private)."""
    HUMAN_ROOT = {'root_ts': '1', 'root_author': 'human-account', 'last_fp': 'earlier'}

    def alert(self):
        r = record('blocked', {'need': 'Publish as a draft PR?', 'action': 'publish as a draft PR',
                               'target': 'fix/alert-recovery branch, no deployment'},
                   evidence={'commit': 'dcf46f2', 'tests': '121 focused passed'})
        return r, summ(r, title='Alert recovery fixes', result='Both fixes ready on a local branch; nothing pushed or deployed',
                       owner='Codex · alert tuning', label='Codex')

    def rollout(self):
        r = record('verified-done', evidence={'commit': '77352c0', 'tests': '150 passed'})
        return r, summ(r, title='PR 89 rollout', result='Merged and deployed; no live serves yet since deploy',
                       owner='Codex · PR 89 task', label='Codex', monitoring=True)

    def migration(self):
        r = record('blocked', {'need': 'Move the workspace?', 'action': 'rename and symlink',
                               'target': 'old workspace folder to the new home, link left at the old path'})
        return r, summ(r, title='Move workspaces out of the synced folder', result='Plan ready; nothing moved yet',
                       owner='Desktop session · workspace move', label='Claude')

    def test_alert_needs_a_draft_pr_decision_and_no_deployment(self):
        r, s = self.alert()
        self.assertEqual((s['status'], s['next']), ('Needs you', 'Approve or decline `publish as a draft PR` on `fix/alert-recovery branch, '
                                                    'no deployment` in the session chat. ' + h.THREAD_NOTE))
        self.assertEqual(h.plan_update(self.HUMAN_ROOT, s), 'reply')  # its root is on the user's account
        self.assertNotIn('dcf46f2', h.render(s))
        self.assertIn('dcf46f2', h.render_details(r))

    def test_rollout_is_monitoring_with_nothing_needed(self):
        r, s = self.rollout()
        self.assertEqual((s['status'], s['next']), ('Monitoring', h.NOTHING))
        self.assertEqual(h.plan_update(dict(self.HUMAN_ROOT, last_fp=h.fingerprint(s)), s), 'none')

    def test_migration_needs_the_exact_rename_plus_symlink_approval(self):
        r, s = self.migration()
        self.assertEqual(s['status'], 'Needs you')
        self.assertIn('`rename and symlink` on `old workspace folder to the new home, link left at the old path`', s['next'])
        self.assertEqual(h.plan_update(None, s), 'post-root')  # no thread exists for it yet
        chat = {'channel': 'chat', 'text': 'yes', 'approve': True}
        r, o = t.apply(r, {'id': 'u', 'task': 'wi-1', 'ts': BASE + 1, 'source': 'user', 'kind': 'decided',
                           'data': dict(chat, action='rename', target=r['pending_decision']['target'])})
        self.assertEqual(o, 'rejected')  # a yes to the rename alone does not cover the symlink
        r, o = t.apply(r, {'id': 'u2', 'task': 'wi-1', 'ts': BASE + 2, 'source': 'user', 'kind': 'decided',
                           'data': dict(chat, **{k: r['pending_decision'][k] for k in ('action', 'target')})})
        self.assertEqual((o, h.plain_status(r)), ('applied', 'In progress'))

    def test_index_of_the_three(self):
        lines = h.render_index([self.rollout()[1], self.alert()[1], self.migration()[1]]).splitlines()
        self.assertEqual([l.split(' · ')[0] for l in lines], ['• *Needs you*', '• *Needs you*', '• *Monitoring*'])


if __name__ == '__main__':
    unittest.main()

class MaterialTransitionTests(unittest.TestCase):
    def test_assistant_owned_review_and_uncertain_dispatch_do_not_need_user(self):
        ready = record('ready-for-review', evidence={'commit': 'abc1234', 'tests': '12 passed'})
        self.assertEqual(h.plain_status(ready), 'In progress')
        self.assertIn('orchestrator', h.next_step(ready, where='chat').lower())
        uncertain = t.begin_dispatch(record(), 'launch-1', resume=False)
        self.assertEqual(h.plain_status(uncertain), 'In progress')
        self.assertIn('reconcile', h.next_step(uncertain, where='chat').lower())
        self.assertNotIn('approve', h.next_step(uncertain, where='chat').lower())

    def test_existing_approval_and_vague_blocker_are_not_needs_you(self):
        r = record('blocked', {'need': 'Approve?', 'action': 'publish', 'target': 'branch'})
        r['approvals'] = [{'action': 'publish', 'target': 'branch'}]
        self.assertEqual(h.plain_status(r), 'In progress')
        self.assertIn('orchestrator', h.next_step(r, where='chat').lower())
        self.assertEqual(h.plain_status(record('blocked', {'need': 'unspecified'})), 'In progress')

    def test_unknown_owner_stays_with_orchestrator(self):
        r = record('blocked', {'need': 'approve?', 'action': 'publish', 'target': 'branch'})
        r['worker']['owner'] = 'unknown'
        self.assertEqual(h.plain_status(r), 'In progress')
        self.assertIn('reconcile task ownership', h.next_step(r, where='chat'))

    def test_material_reply_overrides_editable_root_and_uncertain_send_reconciles(self):
        s = summ(record('running'))
        hub = {'root_ts': '1', 'root_author': 'assistant-bot', 'last_fp': 'old'}
        self.assertEqual(h.plan_update(hub, s, editable_authors=('assistant-bot',), material=True), 'reply')
        self.assertEqual(h.plan_update(dict(hub, last_fp=h.fingerprint(s)), s,
                                       editable_authors=('assistant-bot',), material=True), 'none')
        self.assertEqual(h.plan_update(dict(hub, send_state='uncertain'), s, material=True), 'reconcile')

class MaterialTraceTests(unittest.TestCase):
    def test_failed_and_uncertain_start_notify_before_other_work_without_heartbeat(self):
        events = []
        r = t.begin_dispatch(record(), 'launch', resume=False)
        text = h.material_from_record(r, progress='Dispatch receipt uncertain; no execution verified',
                                      progress_state='unverified', where='the originating thread')
        events.append(('notify-origin', text))
        events.append(('other-work', None))
        self.assertEqual(events[0][0], 'notify-origin')
        self.assertIn('Need from Thomas: None', text)
        self.assertIn('reconcile', text.lower())
        failed = t.settle_dispatch(r, 'launch', 'not-sent')
        self.assertIn('retry the failed dispatch', h.material_from_record(
            failed, progress='Launch proven absent', progress_state='performed',
            where='the originating thread'))
        self.assertEqual(h.plan_update({'root_ts': '1', 'last_fp': h.fingerprint(summ(record('running')))},
                                       summ(record('running')), material=True), 'none')

    def test_genuine_user_decision_once_then_orchestrator_owns_next_action(self):
        r = record('blocked', {'need': 'Which schema?', 'action': 'use schema', 'target': 'A'})
        before = h.material_from_record(r, progress='Worker asks for schema', progress_state='reported', where='chat')
        self.assertIn('Owner: Thomas', before)
        self.assertIn('Need from Thomas: Approve or decline', before)
        r, outcome = t.apply(r, {'id': 'decision', 'task': 'wi-1', 'ts': BASE + 1,
                                 'source': 'user', 'kind': 'decided',
                                 'data': {'channel': 'chat', 'text': 'Use A', 'approve': True,
                                          'action': 'use schema', 'target': 'A'}})
        self.assertEqual(outcome, 'applied')
        after = h.material_from_record(r, progress='Decision recorded; resume pending',
                                       progress_state='performed', where='chat')
        self.assertIn('Owner: Orchestrator', after)
        self.assertIn('Need from Thomas: None', after)
        self.assertNotIn('running', after.lower())
        self.assertEqual(t.apply(r, {'id': 'decision', 'task': 'wi-1', 'ts': BASE + 1,
                                     'source': 'user', 'kind': 'decided', 'data': {}})[1], 'duplicate')

    def test_ready_review_uses_current_evidence_without_user_ask(self):
        r = record('ready-for-review', evidence={'commit': 'abc1234', 'tests': '12 passed'})
        text = h.material_from_record(r, progress='Worker reports commit and tests; review pending',
                                      progress_state='reported', where='chat')
        self.assertIn('Owner: Orchestrator', text)
        self.assertIn('Need from Thomas: None', text)
        self.assertNotIn('Needs you', h.plain_status(r))

class UncertainOwnershipTests(unittest.TestCase):
    def test_uncertain_dispatch_overrides_pending_user_decision(self):
        r = t.begin_dispatch(record('blocked', {'need': 'Approve?', 'action': 'publish', 'target': 'branch'}),
                             'launch', resume=True)
        text = h.material_from_record(r, progress='Receipt uncertain',
                                      progress_state='unverified', where='chat')
        self.assertIn('Owner: Orchestrator', text)
        self.assertIn('Need from Thomas: None', text)
