"""Offline recovery assessment regressions; no hosts, credentials or dispatch."""
import copy
import json
from pathlib import Path
import unittest
from test_operating_checkpoints import bound, tasks, checkpoint_shape, T0, T1, DUE, LATE, EXP
from agent_skills.task_reconciliation import reconcile_tasks, keep_awake_assessment
from agent_skills.worker_execution import select_route, bind_route


class RecoveryTests(unittest.TestCase):
    def snapshot(self):
        r = bound()
        a = r['coordination']['active_deliverable']
        return dict(expected_task_ids=[r['task_id']], records=[r], observations=[dict(
            task_id=r['task_id'], revision=a['revision'], decision_source_ref=a['source_ref'],
            observed_at_utc=T0, expires_at_utc=EXP)])

    def test_missing_checkpoint_and_inventory_are_visible_without_mutation(self):
        s = self.snapshot(); s['expected_task_ids'].append('missing-owner')
        before = copy.deepcopy(s)
        result = reconcile_tasks(s, now=LATE)
        self.assertFalse(result['coverage_complete'])
        self.assertIn('missing-checkpoint:critical-read', result['tasks'][0]['issues'])
        self.assertFalse(result['tasks'][0]['dispatch_authorized'])
        self.assertEqual(before, s)
        self.assertTrue(any('missing checkpoint' in m for _, m in tasks.attention(s['records'], now=LATE)))

    def test_ordinary_overdue_survives(self):
        r = tasks.record_checkpoint(bound(), **dict(checkpoint_shape(), critical=False))
        self.assertTrue(any('overdue obligation' in m for _, m in tasks.attention([r], now=LATE)))

    def test_stale_and_out_of_order_evidence(self):
        for field, value, issue in [('revision', 0, 'revision-or-decision-mismatch'),
                ('expires_at_utc', T1, 'stale-or-future-observation'),
                ('observed_at_utc', EXP, 'stale-or-future-observation')]:
            with self.subTest(field=field):
                s = self.snapshot(); s['observations'][0][field] = value
                self.assertIn(issue, reconcile_tasks(s, now=LATE)['tasks'][0]['issues'])

    def test_approval_does_not_resolve_delivery_or_scope(self):
        s = self.snapshot(); r = s['records'][0]
        r['approvals'] = [{'source_ref': 'user:approved'}]
        r['coordination']['active_deliverable']['result_receipt_ref'] = 'result:1'
        s['observations'][0].update(required_operations=['provider:get-original'], forbidden_operations=['provider:get-original'])
        row = reconcile_tasks(s, now=LATE)['tasks'][0]
        self.assertIn('unconsumed-result', row['issues'])
        self.assertIn('contradictory-operation-scope', row['issues'])
        self.assertFalse(row['dispatch_authorized'])

    def test_human_paused_uncertain_and_duplicate(self):
        s = self.snapshot(); r = s['records'][0]
        r['worker']['owner'] = 'human'
        r['coordination']['execution_state'] = 'paused'
        r['outbox'] = [{'state': 'uncertain'}]
        issues = reconcile_tasks(s, now=LATE)['tasks'][0]['issues']
        for issue in ('human-owned-or-unknown-owner', 'paused', 'uncertain-dispatch'):
            self.assertIn(issue, issues)
        s['records'].append(copy.deepcopy(r))
        with self.assertRaises(ValueError): reconcile_tasks(s, now=LATE)

    def test_assertion_lifetime_and_other_owner(self):
        receipt = dict(owner='ML', pid=2324, process_identity_ref='process:fixture',
            assertion_ref='pmset:fixture', cleanup_ref='owner-only', observed_at_utc=T0, expires_at_utc=DUE)
        row = keep_awake_assessment(receipt, now=T1, owner='audit')
        self.assertTrue(row['reuse_existing_owner'])
        self.assertFalse(row['cleanup_authorized'])
        self.assertEqual(keep_awake_assessment(receipt, now=LATE, owner='audit')['state'], 'unverified')
        self.assertEqual(keep_awake_assessment(None, now=T1, owner='audit')['state'], 'unverified')

    def test_astra_medium_policy_and_owned_resume(self):
        policy = {'codex': {'involved': dict(model='gpt-6-astra', effort='medium', timeout_seconds=120)}}
        caps = {'codex': {'gpt-6-astra': ['medium', 'high']}}
        route = select_route(policy, caps, provider='codex', signals=['architecture'], reason='approved preference')
        r = bound(); r['worker']['kind'] = 'codex'
        r = bind_route(r, route, source_pin='fixture:pin', decision_ref='user:policy')
        r['worker']['session_id'] = 'owned-session'
        self.assertEqual(bind_route(r, route, source_pin='fixture:pin', decision_ref='user:policy'), r)
        changed = dict(route, effort='high')
        with self.assertRaises(ValueError): bind_route(r, changed, source_pin='fixture:pin', decision_ref='user:policy')
        with self.assertRaises(ValueError): select_route(policy, {'codex': {}}, provider='codex', signals=['architecture'], reason='unavailable')

    def test_old_readback_cannot_consume_new_result(self):
        s = self.snapshot(); a = s['records'][0]['coordination']['active_deliverable']
        a['result_receipt_ref'] = 'result:new'
        a['parent_readback'] = dict(result_receipt_ref='result:old', decision_source_ref=a['source_ref'])
        self.assertIn('unconsumed-result', reconcile_tasks(s, now=LATE)['tasks'][0]['issues'])
        a['parent_readback']['result_receipt_ref'] = 'result:new'
        self.assertNotIn('unconsumed-result', reconcile_tasks(s, now=LATE)['tasks'][0]['issues'])

    def test_critical_execution_requires_current_protection(self):
        s = self.snapshot(); s['observations'][0]['critical_execution'] = True
        row = reconcile_tasks(s, now=LATE)['tasks'][0]
        self.assertIn('critical-keep-awake-unverified', row['issues'])
        self.assertEqual(row['keep_awake']['state'], 'unverified')

    def test_cli_success_and_malformed_snapshot(self):
        from agent_skills.safeguard_cli import main
        import contextlib, io, tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            path.write_text(json.dumps(self.snapshot()))
            before = path.read_bytes(); output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['task-reconcile', str(path), '--now', LATE]), 0)
            self.assertTrue(json.loads(output.getvalue())['assessment_only'])
            self.assertEqual(path.read_bytes(), before)
            path.write_text('{}')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['task-reconcile', str(path), '--now', LATE]), 1)
        s = self.snapshot(); s['observations'][0]['required_operations'] = 'provider:get'
        with self.assertRaises(ValueError): reconcile_tasks(s, now=LATE)
