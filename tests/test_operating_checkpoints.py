"""Offline replays of audited failure mechanisms; no model or native-host claim."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('operating_tasks', ROOT / 'skills/agent-coordination/scripts/tasks.py')
tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tasks)
T0, T1, DUE, LATE = ('2026-10-14T18:00:00Z', '2026-10-14T18:05:00Z',
                     '2026-10-14T18:10:00Z', '2026-10-14T18:11:00Z')
EXP = '2026-10-15T18:00:00Z'


def bound(record=None, revision=1, deliverable='critical-read', **extra):
    record = record or tasks.new_task('fixture-task', 'fixture', worker_kind='local',
                                      owner='assistant', repo='fixture-repo', worktree='fixture-worktree')
    return tasks.bind_task_contract(record, user_goal='Retain agreed outcome', constraints=['offline'],
        priority_source_ref='user:priority', canonical_issue_ref='fixture:issue', canonical_owner='worker-a',
        deliverable_id=deliverable, revision=revision, acceptance_ref='fixture:acceptance',
        environment='offline', changed_criteria='Current requirement', next_action='Read existing evidence',
        source_ref='user:current-decision', **extra)


def brief(record, now=LATE):
    options = dict(priority_candidates=[], result='Current result', remaining=['behavior unknown'], next_owner='worker-a')
    if hasattr(tasks, 'record_checkpoint'):
        options['now'] = now
    return tasks.communication_brief(record, **options)


def checkpoint_shape():
    return dict(critical=True, rank=1, blocker={'kind': 'missing-evidence',
        'source_ref': 'probe:failed', 'action': 'Reconcile the permitted route'},
        next_action='Read existing evidence', next_check_at_utc=DUE,
        observed_at_utc=T0, receipt_ref='checkpoint:first')


def decision(record, source, mechanism):
    return tasks.set_decision_frame(record, decision_id='policy', rank=1, scope='fixture scope',
        target='fixture', prerequisites=[], mechanism=mechanism, exposure_frequency='unknown',
        technical_risk='bounded', observed_impact='unknown', conditional_impact='review needed',
        business_decision='human decides', activation_state='pending', priority_source_ref=source)


class AuditedRegressions(unittest.TestCase):
    """These same existing-interface assertions fail on the exact baseline."""
    def test_buried_approved_critical_blocker_stays_visible(self):
        r = bound()
        r['status'] = 'blocked'
        active = r['coordination']['active_deliverable']
        authority = {'action': 'read', 'target': 'fixture', 'scope': 'read only',
                     'revision': active['revision'], 'contract_digest': active['contract_digest']}
        r['pending_decision'] = {'need': 'Read approved', **authority}
        r['approvals'] = [{**authority, 'binding':'current-contract'}]
        r['coordination']['active_deliverable']['checkpoint'] = checkpoint_shape()
        messages = tasks.attention([r])
        self.assertTrue(any('critical' in m for _, m in messages))
        self.assertFalse(any('needs decision' in m for _, m in messages))

    def test_missed_monitor_detected_without_process_death_claim(self):
        r = bound()
        r['coordination']['watch_baselines']['watch'] = {'digest': 'baseline', 'scope': 'fixture',
            'checkpoint': {'owner': 'worker-a', 'next_check_at_utc': DUE, 'expires_at_utc': EXP,
                           'observed_at_utc': T0, 'receipt_ref': 'schedule:admitted'}}
        messages = tasks.attention([r])
        self.assertTrue(any('monitor check overdue' in m for _, m in messages))
        self.assertFalse(any('dead' in m for _, m in messages))

    def test_corrected_unknown_hides_displaced_material_fact(self):
        r = bound()
        r['worker_return'] = {'material_facts': [{'fact': 'No booking exists',
            'source_ref': 'claim:old', 'evidence_level': 'reported'}]}
        r['coordination']['claim_history'] = [dict(claim_id='booking', state='unknown',
            statement='Provider history unavailable', evidence_level='performed',
            source_ref='claim:correction', supersedes='claim:old', observed_at_utc=T1)]
        self.assertEqual(brief(r)['material_facts'], [])

    def test_superseded_decision_cannot_return_from_old_source(self):
        r = decision(bound(), 'user:first', 'earlier exception')
        r = decision(r, 'user:second', 'exception removed')
        with self.assertRaises(ValueError):
            decision(r, 'user:first', 'earlier exception')
        self.assertEqual(r['coordination']['decisions'][0]['mechanism'], 'exception removed')


@unittest.skipUnless(hasattr(tasks, 'record_checkpoint'), 'new API absent on historical baseline')
class CheckpointTests(unittest.TestCase):
    def critical(self):
        return tasks.record_checkpoint(bound(), **checkpoint_shape())

    def watch(self):
        r = tasks.set_watch_baseline(bound(), watch_id='watch', scope='fixture behavior',
            digest_value='baseline', observed_at=T0, source_ref='release:baseline')
        return tasks.record_watch_checkpoint(r, watch_id='watch', baseline_digest='baseline',
            next_check_at_utc=DUE, expires_at_utc=EXP, observed_at_utc=T0, receipt_ref='schedule:admitted')

    def checked(self, **changes):
        return tasks.record_watch_result(self.watch(), **dict(watch_id='watch', baseline_digest='baseline',
            observed_at_utc=T1, wake_receipt='wake:one', readback_receipt='result:one',
            traffic_count=0, functional_results=[], **changes))

    def test_lower_priority_interruption_retains_owner_checkpoint_and_approvals(self):
        r = self.critical()
        r['approvals'] = [{'action': 'read', 'target': 'fixture', 'scope': 'read only'}]
        updated = bound(r, revision=2, deliverable='small-demo', displaced_reason='New request; retain critical read')
        view = brief(updated)['operating_state']
        self.assertEqual([(x['id'], x['owner'], x['overdue']) for x in view['retained_obligations']],
                         [('critical-read', 'worker-a', True), ('small-demo', 'worker-a', False)])
        self.assertTrue(view['retained_obligations'][1]['checkpoint_missing'])
        self.assertEqual(view['recorded_approvals'], r['approvals'])
        self.assertFalse(view['native_enforcement'])
        self.assertEqual(updated['coordination']['acceptance_state'], 'unreviewed')

    def test_checkpoint_replay_stale_update_and_purity(self):
        original = bound()
        r = tasks.record_checkpoint(original, **checkpoint_shape())
        self.assertNotIn('checkpoint', original['coordination']['active_deliverable'])
        self.assertEqual(tasks.record_checkpoint(r, **checkpoint_shape()), r)
        with self.assertRaises(ValueError):
            tasks.record_checkpoint(r, **{**checkpoint_shape(), 'next_action': 'Old summary'})
        with self.assertRaises(ValueError):
            tasks.record_checkpoint(r, **{**checkpoint_shape(), 'critical': 1})

    def test_critical_tasks_sort_first_without_granting_actions(self):
        critical = self.critical()
        normal = bound()
        normal['task_id'] = 'normal'
        normal['worker']['state'] = 'unavailable'
        self.assertEqual(tasks.attention([normal, critical], now=LATE)[0][0], 'fixture-task')
        self.assertEqual(critical['approvals'], [])

    def test_watch_requires_first_receipts_and_zero_traffic_is_inconclusive(self):
        self.assertEqual(tasks.operating_view(self.watch(), now=T1)['monitors'][0]['watch_state'], 'not-armed')
        view = tasks.operating_view(self.checked(), now=T1)['monitors'][0]
        self.assertEqual(view['watch_state'], 'armed')
        self.assertEqual(view['functional_acceptance'], 'inconclusive-zero-traffic')
        self.assertEqual(self.checked()['coordination']['acceptance_state'], 'unreviewed')

    def test_overdue_expired_and_future_receipts_never_prove_continuity(self):
        r = self.checked()
        self.assertTrue(tasks.operating_view(r, now=LATE)['monitors'][0]['missed_check'])
        self.assertEqual(tasks.operating_view(r, now=LATE)['monitors'][0]['watch_state'], 'not-armed')
        self.assertEqual(tasks.operating_view(r, now=T0)['monitors'][0]['watch_state'], 'not-armed')
        self.assertEqual(tasks.operating_view(r, now='2026-10-16T00:00:00Z')['monitors'][0]['watch_state'], 'not-armed')

    def test_verified_completion_removes_only_active_attention(self):
        r = self.critical()
        r['status'] = 'ready-for-review'
        self.assertTrue(tasks.operating_view(r, now=LATE)['retained_obligations'])
        r['status'] = 'verified-done'
        r['coordination']['contract_consumption']['acceptance'] = {'receipt_ref': 'acceptance:verified'}
        self.assertEqual(tasks.operating_view(r, now=LATE)['retained_obligations'], [])
        r = bound(r, revision=2, deliverable='next', displaced_reason='retain earlier obligation')
        rows = tasks.operating_view(r, now=LATE)['retained_obligations']
        self.assertEqual([x['id'] for x in rows], ['next'])
        self.assertTrue(rows[0]['checkpoint_missing'])
        self.assertEqual(r['coordination']['completed_obligations'][0]['completion_ref'], 'acceptance:verified')

    def test_watch_drift_reschedule_and_historical_evidence_preserved(self):
        r = self.checked()
        r = tasks.record_watch_checkpoint(r, watch_id='watch', baseline_digest='baseline',
            next_check_at_utc='2026-10-14T18:20:00Z', expires_at_utc=EXP,
            observed_at_utc=LATE, receipt_ref='schedule:next')
        self.assertEqual(len(r['coordination']['watch_baselines']['watch']['check_history']), 1)
        self.assertEqual(tasks.operating_view(r, now=LATE)['monitors'][0]['watch_state'], 'not-armed')
        self.assertEqual(tasks.operating_view(r, now=LATE)['monitors'][0]['last_completed_check']['readback_receipt'], 'result:one')
        with self.assertRaises(ValueError):
            tasks.set_watch_baseline(r, watch_id='watch', scope='stale scope',
                digest_value='stale', observed_at=T0, source_ref='release:stale')
        with self.assertRaises(ValueError):
            tasks.set_watch_baseline(r, watch_id=' watch ', scope='stale scope',
                digest_value='stale', observed_at=T0, source_ref='release:padded-id')
        changed = tasks.set_watch_baseline(r, watch_id='watch', scope='fixture behavior',
            digest_value='new-baseline', observed_at=LATE, source_ref='release:next')
        self.assertEqual(tasks.operating_view(changed, now=LATE)['monitors'][0]['reason'], 'missing-checkpoint')
        self.assertEqual(len(changed['coordination']['watch_history']), 1)
        with self.assertRaises(ValueError):
            tasks.record_watch_checkpoint(changed, watch_id='watch', baseline_digest='new-baseline',
                next_check_at_utc='2026-10-14T18:20:00Z', expires_at_utc=EXP,
                observed_at_utc=LATE, receipt_ref='schedule:admitted')
        with self.assertRaises(ValueError):
            tasks.set_watch_baseline(changed, watch_id='watch', scope='fixture behavior',
                digest_value='baseline', observed_at=T0, source_ref='release:baseline')
        with self.assertRaises(ValueError):
            tasks.set_watch_baseline(changed, watch_id='watch', scope='fixture behavior',
                digest_value='stale', observed_at=T0, source_ref='release:stale-reset')
        with self.assertRaises(ValueError):
            tasks.record_watch_result(changed, watch_id='watch', baseline_digest='baseline',
                observed_at_utc=LATE, wake_receipt='old', readback_receipt='old', traffic_count=1, functional_results=[True])

    def test_old_monitor_receipts_cannot_refresh_new_interval(self):
        r = tasks.record_watch_checkpoint(self.checked(), watch_id='watch', baseline_digest='baseline',
            next_check_at_utc='2026-10-14T18:20:00Z', expires_at_utc=EXP,
            observed_at_utc=LATE, receipt_ref='schedule:next')
        for wake, readback in [('wake:one', 'result:new'), ('wake:new', 'result:one'),
                               (' wake:one ', ' result:one ')]:
            with self.assertRaises(ValueError):
                tasks.record_watch_result(r, watch_id='watch', baseline_digest='baseline',
                    observed_at_utc='2026-10-14T18:12:00Z', wake_receipt=wake,
                    readback_receipt=readback, traffic_count=0, functional_results=[])
        with self.assertRaises(ValueError):
            tasks.record_watch_checkpoint(r, watch_id='watch', baseline_digest='baseline',
                next_check_at_utc='2026-10-14T18:21:00Z', expires_at_utc=EXP,
                observed_at_utc='2026-10-14T18:12:00Z', receipt_ref='schedule:admitted')

    def test_legacy_watch_result_replay_keeps_original_record_and_unknown_coverage(self):
        r = self.checked()
        r['coordination']['watch_baselines']['watch']['check'].pop('coverage')
        before = copy.deepcopy(r)
        try:
            updated = tasks.record_watch_result(r, watch_id='watch', baseline_digest='baseline',
                observed_at_utc=T1, wake_receipt='wake:one', readback_receipt='result:one',
                traffic_count=0, functional_results=[])
        except ValueError:
            updated = None
        self.assertEqual(updated, before)
        self.assertEqual(tasks.operating_view(r, now=T1)['monitors'][0]['source_coverage']['state'], 'unknown')

    def test_positive_and_failed_functional_results_are_separate_from_execution(self):
        for outcomes, expected in [([True], 'passed'), ([False], 'failed')]:
            args = dict(watch_id='watch', baseline_digest='baseline', observed_at_utc=T1,
                wake_receipt='wake', readback_receipt='read', traffic_count=1, functional_results=outcomes,
                coverage={'requested': {'start': T0, 'end': T1}, 'observed': {'start': T0, 'end': T1},
                          'source_observed_at_utc': T1, 'source_identity': 'fixture:head',
                          'runtime_identity': 'reader:version', 'state': 'verified', 'cap_seconds': None,
                          'truncated': False, 'max_source_age_seconds': 60, 'receipt_ref': 'source:read'})
            r = tasks.record_watch_result(self.watch(), **args)
            self.assertEqual(tasks.operating_view(r, now=T1)['monitors'][0]['functional_acceptance'], expected)
            self.assertNotEqual(r['status'], 'verified-done')
            self.assertEqual(tasks.operating_view(r, now=LATE)['monitors'][0]['source_coverage']['state'], 'unknown')
            self.assertEqual(r['coordination']['watch_baselines']['watch']['check']['coverage']['source_observed_at_utc'], T1)
        with self.assertRaises(ValueError):
            tasks.record_watch_result(self.watch(), **{**args, 'functional_results': ['pass']})

    def test_claim_corrections_are_append_only_and_old_replay_does_not_restore(self):
        old = dict(claim_id='booking', state='supported', statement='No booking exists',
            evidence_level='reported', source_ref='claim:old', observed_at_utc=T0)
        r = tasks.record_claim(bound(), **old)
        r = tasks.record_claim(r, claim_id='booking', state='unknown', statement='Provider history missing',
            evidence_level='performed', source_ref='claim:correction', observed_at_utc=T1, supersedes='claim:old')
        self.assertEqual(tasks.record_claim(r, **old), r)
        self.assertEqual(len(r['coordination']['claim_history']), 2)
        self.assertEqual(brief(r)['operating_state']['current_claims'][0]['state'], 'unknown')
        with self.assertRaises(ValueError):
            tasks.record_claim(r, **{**old, 'source_ref': 'claim:stale-new-id', 'observed_at_utc': LATE})
        with self.assertRaises(ValueError):
            tasks.record_claim(r, **{**old, 'statement': 'Altered receipt'})
        with self.assertRaises(ValueError):
            tasks.record_claim(r, **{**old, 'claim_id': ' booking ', 'source_ref': 'claim:normalized-stale'})

    def test_decision_history_retains_old_scope_and_fresh_human_source_can_revise(self):
        r = decision(bound(), 'user:first', 'earlier exception')
        r = decision(r, 'user:second', 'exception removed')
        self.assertEqual(r['coordination']['decision_history'][0]['decision']['mechanism'], 'earlier exception')
        self.assertEqual(decision(r, 'user:second', 'exception removed'), r)
        r = decision(r, 'user:third', 'newly reviewed exception')
        self.assertEqual(r['coordination']['decisions'][0]['priority_source_ref'], 'user:third')
        self.assertEqual(r['approvals'], [])
        with self.assertRaises(ValueError):
            decision(r, 'user:third', 'earlier exception')

    def test_authentication_observations_remain_context_scoped(self):
        context = {key: 'fixture:' + key for key in ('host_ref', 'executor_ref', 'shell_ref',
            'executable_ref', 'version', 'user_ref', 'home_ref', 'config_ref', 'cwd_ref', 'mode')}
        context['mode'] = 'restricted'
        r = tasks.record_execution_context(bound(), context=context,
            observations={'authentication': {'state': 'unknown', 'source_ref': 'auth:restricted'}},
            observed_at_utc=T0, receipt_ref='context:first')
        other = {**context, 'mode': 'supported'}
        r = tasks.record_execution_context(r, context=other,
            observations={'authentication': {'state': 'verified', 'source_ref': 'auth:supported'}},
            observed_at_utc=T1, receipt_ref='context:second')
        view = brief(r)['operating_state']
        self.assertEqual(view['execution_context']['context']['mode'], 'supported')
        self.assertEqual(len(r['coordination']['execution_context_history']), 1)
        self.assertNotIn('global_account_state', view)
        with self.assertRaises(ValueError):
            tasks.record_execution_context(r, context={**other, 'token': 'forbidden-field'},
                observations={'authentication': {'state': 'verified', 'source_ref': 'auth'}},
                observed_at_utc=LATE, receipt_ref='context:bad')

    def test_provenance_binds_tests_to_actual_code_state(self):
        from agent_skills.code_state import code_state
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp).resolve()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
            git('init', '-q'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
            (repo / 'source.txt').write_text('before')
            git('add', 'source.txt'); git('commit', '-qm', 'fixture baseline')
            base = git('rev-parse', 'HEAD'); snapshot = code_state(repo)
            r = tasks.capture_provenance(bound(), repo=repo, base=base,
                test_receipt_ref='tests:offline', tested_digest=snapshot['digest'])
            self.assertEqual(brief(r)['operating_state']['provenance']['base'], base)
            git('checkout', '--detach', '-q', base)
            detached = tasks.capture_provenance(bound(), repo=repo, base=base,
                test_receipt_ref='tests:offline', tested_digest=snapshot['digest'])
            self.assertIsNone(detached['coordination']['active_deliverable']['provenance']['branch'])
            (repo / 'source.txt').write_text('after')
            with self.assertRaises(ValueError):
                tasks.capture_provenance(r, repo=repo, base=base, test_receipt_ref='tests:old', tested_digest=snapshot['digest'])

    def test_fresh_and_resumed_cli_consumers_read_persisted_current_state(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp).resolve()
            r = self.critical()
            tasks.create(store, r)
            saved = store / 'fixture-task.json'
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
            def read(now):
                before = saved.read_bytes()
                out = subprocess.check_output([sys.executable, '-m', 'agent_skills.safeguard_cli',
                    'task-status', str(saved), '--now', now], cwd=ROOT, env=env, text=True)
                self.assertEqual(saved.read_bytes(), before)
                return json.loads(out)
            fresh = read(T1)
            tasks.update(store, 'fixture-task', tasks.record_claim, claim_id='booking', state='unknown',
                statement='Provider outcome remains unknown', evidence_level='performed',
                source_ref='claim:current', observed_at_utc=T1)
            resumed = read(LATE)
            self.assertFalse(fresh['retained_obligations'][0]['overdue'])
            self.assertTrue(resumed['retained_obligations'][0]['overdue'])
            self.assertEqual(resumed['current_claims'][0]['state'], 'unknown')
            self.assertEqual(resumed['navigation']['execution_owner'], 'worker-a')
            self.assertFalse(resumed['native_enforcement'])


if __name__ == '__main__':
    unittest.main()
