"""Synthetic route, checkpoint and takeover regressions; no processes, prompts or session stores."""
import copy
import importlib.util
import os
from pathlib import Path
import unittest

from agent_skills import session_handoff as h
from agent_skills import worker_execution as e
from agent_skills.task_checkpoint import operating_view

ROOT = Path(os.environ.get('WORKER_SOURCE_ROOT', Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('handoff_tasks', ROOT / 'skills/agent-coordination/scripts/tasks.py')
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

LOCAL = '0f0e0d0c-0b0a-4908-8706-050403020100'
COPY = '1f1e1d1c-1b1a-4918-8716-151413121110'
CLOUD = 'cloud_synthetic_01'
T0, T1, T2, T3, T4 = (f'2026-01-01T00:0{i}:00+00:00' for i in range(5))
POLICY = {p: {'ordinary': {'model': p + '-m', 'effort': 'medium', 'timeout_seconds': 30},
              'involved': {'model': p + '-m', 'effort': 'medium', 'timeout_seconds': 30}} for p in ('claude', 'codex')}
CAPS = {p: {p + '-m': ['medium']} for p in POLICY}


def owned(kind='claude', sid=LOCAL, owner='assistant'):
    r = t.new_task('synthetic-handoff', 'synthetic-handoff', worker_kind=kind, owner=owner, repo='synthetic')
    if owner == 'assistant':
        route = e.select_route(POLICY, CAPS, provider=kind, reason='synthetic')
        r = e.bind_route(r, route, source_pin='source:a', decision_ref='decision:a')
    r['worker']['session_id'] = sid
    return r


def source(sid=LOCAL, kind='local-uuid', **kw):
    return {'session_ref': sid, 'id_kind': kind, 'workspace_ref': 'workspace:a', 'repo_ref': 'repo:a',
            'branch': 'task/a', 'head': 'c1', 'pushed': None, **kw}


def dest(**kw):
    return {'workspace_ref': 'workspace:a', 'repo_ref': 'repo:a', 'branch': 'task/a', 'head': 'c1', 'dirty': True, **kw}


def seen(sid=LOCAL, state='exited', at=T2):
    return {'session_ref': sid, 'process_state': state, 'source_ref': 'receipt:exit', 'observed_at_utc': at}


def saved(sid=LOCAL, head='c1', at=T3):
    return {'session_ref': sid, 'head': head, 'receipt_ref': 'receipt:checkpoint', 'observed_at_utc': at}


def requested(record=None, destination='local-desktop', src=None, provider='claude', origin='local-cli'):
    return h.request_takeover(record or owned(provider), provider=provider, origin=origin, destination=destination,
                              source=src or source(), requested_ref='human:request', requested_at_utc=T1)


class Routes(unittest.TestCase):
    def test_documented_routes_label_continuity_and_identity(self):
        same = h.plan_handoff('claude', 'local-cli', 'local-desktop')
        self.assertEqual((same['continuity'], same['id_kind'], same['visual_confirmation']),
                         ('same-session', 'local-uuid', 'pending'))
        self.assertEqual(same['instruction'], 'claude --desktop --resume {session}')
        teleport = h.plan_handoff('claude', 'cloud', 'local-cli')
        self.assertEqual((teleport['continuity'], teleport['id_kind']), ('context-copy', 'cloud-id'))
        self.assertEqual(h.plan_handoff('codex', 'local-cli', 'local-cli')['continuity'], 'same-session')
        self.assertEqual(h.plan_handoff('codex', 'cloud', 'local-cli')['continuity'], 'diff-apply')

    def test_undocumented_routes_fail_closed_without_discovery(self):
        for key in (('codex', 'local-desktop', 'local-cli'), ('claude', 'cloud', 'local-desktop'),
                    ('codex', 'cloud', 'local-desktop'), ('claude', 'local-cli', 'cloud'), ('other', 'local-cli', 'local-cli')):
            with self.assertRaisesRegex(ValueError, 'unsupported route'):
                h.plan_handoff(*key)

    def test_local_uuid_and_cloud_id_are_not_interchangeable(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            requested(owned(sid=CLOUD), src=source(CLOUD, 'cloud-id'))
        with self.assertRaisesRegex(ValueError, 'identity'):
            requested(owned(sid='not-a-uuid'), src=source('not-a-uuid'))
        with self.assertRaisesRegex(ValueError, 'identity'):
            requested(owned(sid=LOCAL), destination='local-cli', origin='cloud', src=source(LOCAL))


class Takeover(unittest.TestCase):
    def test_same_session_release_and_explicit_handback(self):
        r = requested()
        self.assertEqual(r['worker']['handoff']['state'], 'pending')
        r = h.release_to_human(r, destination=dest(), observation=seen(), checkpoint=saved(), acceptance_ref='human:accept')
        self.assertEqual((r['worker']['owner'], r['worker']['handoff']['destination_confirmation']), ('human', 'pending-visual'))
        with self.assertRaises(PermissionError):
            t.begin_dispatch(r, 'd-after-release', resume=True)
        with self.assertRaisesRegex(RuntimeError, 'unconfirmed-destination'):
            h.hand_back(r, observation=seen(at=T4), checkpoint=saved(at=T4), handback_ref='human:back')
        with self.assertRaisesRegex(ValueError, 'same session'):
            h.confirm_destination(r, confirmation_ref='human:seen', session_ref=COPY)
        r = h.confirm_destination(r, confirmation_ref='human:seen', session_ref=LOCAL)
        with self.assertRaisesRegex(RuntimeError, 'not-quiescent:idle'):
            h.hand_back(r, observation=seen(state='idle', at=T4), checkpoint=saved(at=T4), handback_ref='human:back')
        back = h.hand_back(r, observation=seen(at=T4), checkpoint=saved(head='c2', at=T4), handback_ref='human:back')
        self.assertEqual((back['worker']['owner'], back['worker']['handoff']['state']), ('assistant', 'handed-back'))
        self.assertEqual(back['worker']['session_id'], LOCAL)
        resumed = t.begin_dispatch(back, 'd-after-handback', resume=True)  # same-owner resume preserved
        self.assertEqual(resumed['outbox'][-1]['state'], 'uncertain')

    def test_request_freezes_dispatch_and_route_changes_until_cancel(self):
        r = requested()
        with self.assertRaisesRegex(PermissionError, 'frozen'):
            t.begin_dispatch(r, 'd-frozen', resume=True)
        with self.assertRaisesRegex(PermissionError, 'frozen'):
            e.bind_route(r, e.select_route(POLICY, CAPS, provider='claude', signals={'architecture'}, reason='x'),
                         source_pin='source:b', decision_ref='decision:b', change_ref='change:b')
        self.assertEqual(requested(r), r)  # exact replay only
        cancelled = h.cancel_takeover(r, cancel_ref='human:cancel')
        self.assertEqual(t.begin_dispatch(cancelled, 'd-ok', resume=True)['outbox'][-1]['id'], 'd-ok')

    def test_unknown_running_unverified_and_stale_states_hold(self):
        r = requested()
        holds = {'not-quiescent:unknown': dict(observation=seen(state='unknown')),
                 'not-quiescent:running': dict(observation=seen(state='running')),
                 'stale-observation': dict(observation=seen(at=T0)),
                 'foreign-observation': dict(observation=seen(sid=COPY)),
                 'checkpoint-precedes-quiescence': dict(checkpoint=saved(at=T1)),
                 'foreign-checkpoint': dict(checkpoint=saved(sid=COPY)),
                 'head-mismatch': dict(checkpoint=saved(head='c0'))}
        for gap, override in holds.items():
            args = {'destination': dest(), 'observation': seen(), 'checkpoint': saved(), **override}
            with self.subTest(gap), self.assertRaisesRegex(RuntimeError, gap):
                h.release_to_human(r, acceptance_ref='human:accept', **args)
        uncertain = copy.deepcopy(r)
        uncertain['outbox'].append({'id': 'd-timeout', 'state': 'uncertain'})
        with self.assertRaisesRegex(RuntimeError, 'unreconciled-dispatch'):
            h.release_to_human(uncertain, destination=dest(), observation=seen(), checkpoint=saved(), acceptance_ref='human:accept')

    def test_wrong_repo_workspace_branch_and_dirty_copy_targets_hold(self):
        r = requested()
        for gap, value in (('wrong-repo', dest(repo_ref='repo:b')), ('wrong-workspace', dest(workspace_ref='workspace:b')),
                           ('wrong-branch', dest(branch='task/b')), ('head-mismatch', dest(head=None))):
            with self.subTest(gap), self.assertRaisesRegex(RuntimeError, gap):
                h.release_to_human(r, destination=value, observation=seen(), checkpoint=saved(), acceptance_ref='human:accept')
        cloud = requested(owned(sid=CLOUD), destination='local-cli', origin='cloud',
                          src=source(CLOUD, 'cloud-id', pushed=None))
        for gap, value in (('dirty-destination', dest(dirty=True)), ('unknown-cleanliness', dest(dirty=None)),
                           ('unverified-push', dest(dirty=False)), ('wrong-repo', dest(dirty=False, repo_ref='repo:b'))):
            with self.subTest(gap), self.assertRaisesRegex(RuntimeError, gap):
                h.release_to_human(cloud, destination=value, observation=seen(CLOUD, 'idle'),
                                   checkpoint=saved(CLOUD), acceptance_ref='human:accept')

    def test_context_copy_is_never_recorded_as_the_same_session(self):
        cloud = requested(owned(sid=CLOUD), destination='local-cli', origin='cloud', src=source(CLOUD, 'cloud-id', pushed=True))
        r = h.release_to_human(cloud, destination=dest(dirty=False, workspace_ref='workspace:clone', branch='main'),
                               observation=seen(CLOUD, 'idle'), checkpoint=saved(CLOUD), acceptance_ref='human:accept')
        self.assertEqual(r['worker']['handoff']['destination_confirmation'], 'pending-human')
        with self.assertRaisesRegex(ValueError, 'copy'):
            h.confirm_destination(r, confirmation_ref='human:seen', session_ref=CLOUD)
        r = h.confirm_destination(r, confirmation_ref='human:seen', session_ref=COPY)
        back = h.hand_back(r, observation=seen(COPY, 'exited', T4), checkpoint=saved(CLOUD, 'c2', T4), handback_ref='human:back')
        self.assertEqual(back['worker']['session_id'], CLOUD)  # the human's local copy is not adopted

    def test_conflicting_writer_claims_and_permission_denials(self):
        with self.assertRaises(PermissionError):
            requested(owned(owner='human'))
        r = requested()
        with self.assertRaisesRegex(RuntimeError, 'one writer'):
            h.request_takeover(r, provider='claude', origin='local-cli', destination='local-cli', source=source(),
                               requested_ref='human:other', requested_at_utc=T1)
        with self.assertRaisesRegex(ValueError, 'owned session'):
            requested(owned(sid=COPY))
        released = h.release_to_human(r, destination=dest(), observation=seen(), checkpoint=saved(), acceptance_ref='human:accept')
        with self.assertRaises(PermissionError):
            requested(released)
        with self.assertRaisesRegex(RuntimeError, 'pending'):
            h.cancel_takeover(released, cancel_ref='human:cancel')
        with self.assertRaisesRegex(ValueError, 'acceptance'):
            h.release_to_human(r, destination=dest(), observation=seen(), checkpoint=saved(), acceptance_ref=' ')

    def test_claude_desktop_to_cli_is_same_session_after_desktop_writer_exits(self):
        route = h.plan_handoff('claude', 'local-desktop', 'local-cli')
        self.assertEqual((route['continuity'], route['id_kind'], route['instruction'], route['visual_confirmation']),
                         ('same-session', 'local-uuid', 'claude --resume {session}', 'not-applicable'))
        r = requested(destination='local-cli', origin='local-desktop')
        with self.assertRaisesRegex(RuntimeError, 'not-quiescent:idle'):
            h.release_to_human(r, destination=dest(), observation=seen(state='idle'), checkpoint=saved(), acceptance_ref='human:accept')
        released = h.release_to_human(r, destination=dest(), observation=seen(), checkpoint=saved(), acceptance_ref='human:accept')
        self.assertEqual((released['worker']['owner'], released['worker']['handoff']['destination_confirmation']),
                         ('human', 'pending-human'))
        with self.assertRaises(PermissionError):
            requested(owned(owner='human'), destination='local-cli', origin='local-desktop')

    def test_codex_desktop_needs_a_verified_thread_open_receipt_for_the_exact_session(self):
        route = h.plan_handoff('codex', 'local-cli', 'local-desktop')
        self.assertEqual((route['continuity'], route['capability'], route['visual_confirmation']),
                         ('same-session', 'thread-open', 'pending'))

        def ask(capability=None, host_ref='host:a'):
            return h.request_takeover(owned('codex'), provider='codex', origin='local-cli', destination='local-desktop',
                                      source=source(), requested_ref='human:request', requested_at_utc=T1,
                                      capability=capability, host_ref=host_ref)
        receipt = {'provider': 'codex', 'host_ref': 'host:a', 'session_ref': LOCAL, 'workspace_ref': 'workspace:a',
                   'action': 'thread-open', 'state': 'verified', 'source_ref': 'receipt:readback', 'observed_at_utc': T1}
        with self.assertRaisesRegex(RuntimeError, 'capability'):
            ask()
        for override in ({'session_ref': COPY}, {'workspace_ref': 'workspace:b'}, {'provider': 'claude'},
                         {'action': 'thread-read'}, {'state': 'unknown'}, {'state': 'blocked'}, {'observed_at_utc': T0}):
            with self.subTest(override), self.assertRaisesRegex(RuntimeError, 'capability'):
                ask({**receipt, **override})
        with self.assertRaisesRegex(ValueError, 'expected host'):
            ask(receipt, host_ref=None)  # never inferred from the receipt itself
        with self.assertRaisesRegex(RuntimeError, 'host_ref'):
            ask(receipt, host_ref='host:b')  # same UUID and workspace on another host
        with self.assertRaisesRegex(RuntimeError, 'host_ref'):
            ask({**receipt, 'host_ref': 'host:b'})
        with self.assertRaisesRegex(ValueError, 'expected host'):
            h.request_takeover(owned(), provider='claude', origin='local-cli', destination='local-desktop', source=source(),
                               requested_ref='human:request', requested_at_utc=T1, host_ref='host:a')
        with self.assertRaisesRegex(ValueError, 'capability'):
            h.request_takeover(
                owned(), provider='claude', origin='local-cli', destination='local-desktop', source=source(),
                requested_ref='human:request', requested_at_utc=T1, capability=receipt)
        r = ask(receipt)
        self.assertEqual((r['worker']['handoff']['expected_host_ref'], r['worker']['handoff']['capability']['host_ref']),
                         ('host:a', 'host:a'))
        with self.assertRaisesRegex(PermissionError, 'frozen'):
            t.begin_dispatch(r, 'd-frozen', resume=True)
        released = h.release_to_human(r, destination=dest(), observation=seen(), checkpoint=saved(), acceptance_ref='human:accept')
        self.assertEqual(released['worker']['handoff']['destination_confirmation'], 'pending-visual')  # navigation is not sight
        with self.assertRaisesRegex(RuntimeError, 'unconfirmed-destination'):
            h.hand_back(released, observation=seen(at=T4), checkpoint=saved(at=T4), handback_ref='human:back')

    def test_status_projection_shows_writer_and_handoff(self):
        r = requested()
        r['coordination']['active_deliverable'] = None
        nav = operating_view(r, now=T2)['navigation']
        self.assertEqual((nav['writer'], nav['handoff']['state']), ('assistant', 'pending'))


if __name__ == '__main__':
    unittest.main()
