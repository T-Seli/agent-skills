import importlib.util
import json
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).parents[1] / 'skills/agent-coordination/scripts'
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('coordination_tasks', SCRIPTS / 'tasks.py')
tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tasks)


def base():
    return tasks.new_task('task-123', 'synthetic', worker_kind='local', owner='assistant',
                          repo='example/repo', worktree='worktree')


def history_base():
    return tasks.new_task(
        'task-123', 'synthetic', worker_kind='local', owner='assistant',
        repo='example/repo', worktree='worktree',
        history_capture={'record_owner': 'history-owner',
                         'authorization_ref': 'user:item-1',
                         'history_repo': '/private/tmp/history-fixture'})


def bind(record, revision=1, deliverable='fixture', **changes):
    values = dict(user_goal='Verify one deterministic fixture', constraints=['read-only fixture'],
                  priority_source_ref='task:priority-1', canonical_issue_ref='task:123',
                  canonical_owner='worker-1', deliverable_id=deliverable, revision=revision,
                  acceptance_ref='fixture:expected', environment='local-test',
                  changed_criteria=f'criteria revision {revision}', next_action='run fixture',
                  source_ref=f'task:revision-{revision}')
    return tasks.bind_task_contract(record, **{**values, **changes})


def acknowledge(record, revision=1, deliverable='fixture'):
    return tasks.acknowledge_task_contract(
        record, deliverable_id=deliverable, revision=revision,
        changed_criteria=f'criteria revision {revision}', next_action='run fixture',
        environment='local-test', receipt_ref=f'task:readback-{revision}')


def current_binding(record):
    return tasks.current_task_binding(record)


def approve_release(record, scope='fixture only'):
    active = record['coordination']['active_deliverable']
    event = {'id': 'approval-1', 'task': 'task-123', 'ts': 1790000020,
             'source': 'user', 'kind': 'approval',
             'data': {'channel': 'chat', 'text': 'Approve fixture release',
                      'action': 'release', 'target': 'reviewed fixture', 'scope': scope,
                      'revision': active['revision'],
                      'contract_digest': active['contract_digest']}}
    result, outcome = tasks.apply(record, event)
    assert outcome == 'noted'
    return result


def verify_active(record):
    binding = current_binding(record)
    head, diff = 'a' * 40, 'b' * 64
    events = (
        {'id': 'release-dispatch', 'task': 'task-123', 'ts': 1790000010,
         'source': 'adapter', 'kind': 'dispatched', 'data': {}},
        {'id': 'release-running', 'task': 'task-123', 'ts': 1790000011,
         'source': 'worker', 'kind': 'running', 'data': binding},
        {'id': 'release-ready', 'task': 'task-123', 'ts': 1790000012,
         'source': 'worker', 'kind': 'ready',
         'data': {'commit': head, 'final_diff_digest': diff, 'tests': 'passed', **binding}},
        {'id': 'release-verified', 'task': 'task-123', 'ts': 1790000013,
         'source': 'verifier', 'kind': 'verified',
         'data': {'commit': head, 'final_diff_digest': diff, 'tests_passed': True,
                  **binding}})
    for event in events:
        record, outcome = tasks.apply(record, event)
        assert outcome == 'applied'
    return record


class OrchestrationReplayTests(unittest.TestCase):
    def test_history_lifecycle_separates_append_publish_readback_and_resume_consumption(self):
        record, event_id = tasks.stage_history_checkpoint(
            history_base(), source_id='start-revision-1', transition='start',
            summary='Synthetic task started', evidence_refs=['task:revision-1'])
        digest_value = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'requires its 64-hex digest'):
            tasks.mark_history_checkpoint(
                record, event_id=event_id, stage='locally-appended',
                receipt_ref='history:append-without-digest')
        for stage, receipt in (
                ('locally-appended', 'history:append-1'),
                ('view-rendered', 'history:view-1'),
                ('index-updated', 'history:index-1'),
                ('published', 'history:push-1')):
            record = tasks.mark_history_checkpoint(
                record, event_id=event_id, stage=stage, receipt_ref=receipt,
                **({'digest_value': digest_value} if stage == 'locally-appended' else {}))
        self.assertEqual(record['coordination']['history_publication_state'],
                         'published-unverified')
        record = tasks.consume_history_readback(
            record, task_id='task-123', record_owner='history-owner', revision=1,
            digest_value=digest_value, event_ids=[event_id], readback_ref='fresh-clone:1')
        self.assertEqual(record['coordination']['history_publication_state'], 'readback-verified')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            tasks.consume_history_readback(
                record, task_id='task-123', record_owner='history-owner', revision=2,
                digest_value='e' * 64, event_ids=[event_id], readback_ref='fresh-clone:wrong')
        record = tasks.consume_history_readback(
            record, task_id='task-123', record_owner='history-owner', revision=1,
            digest_value=digest_value, event_ids=[event_id], readback_ref='fresh-clone:1')
        replayed, replayed_id = tasks.stage_history_checkpoint(
            record, source_id='start-revision-1', transition='start',
            summary='Synthetic task started', evidence_refs=['task:revision-1'])
        self.assertEqual(replayed_id, event_id)
        self.assertEqual(replayed['history_outbox'][0]['stage'], 'readback-verified')
        record, next_event_id = tasks.stage_history_checkpoint(
            record, source_id='milestone-revision-1', transition='test',
            summary='Synthetic test passed', evidence_refs=['test:fixture-1'])
        self.assertNotEqual(next_event_id, event_id)
        self.assertEqual(record['coordination']['history_publication_state'], 'not-published')
        record = bind(record, requested_artifact='pdf-report')
        with self.assertRaisesRegex(ValueError, 'latest canonical history'):
            acknowledge(record)
        record = tasks.acknowledge_task_contract(
            record, deliverable_id='fixture', revision=1,
            changed_criteria='criteria revision 1', next_action='run fixture',
            environment='local-test', receipt_ref='task:readback-1',
            history_revision=1, history_digest=digest_value)
        self.assertEqual(tasks.result_binding(record, **current_binding(record)), 'current')

    def test_missing_history_publication_does_not_block_unrelated_authorized_work(self):
        history_record, _ = tasks.stage_history_checkpoint(
            history_base(), source_id='start-revision-1', transition='start',
            summary='Synthetic task started', evidence_refs=['task:revision-1'])
        unrelated_base = tasks.new_task(
            'task-456', 'unrelated-synthetic', worker_kind='local', owner='assistant',
            repo='example/repo', worktree='other-worktree')
        unrelated = acknowledge(bind(unrelated_base, deliverable='unrelated-fixture'),
                                deliverable='unrelated-fixture')
        self.assertEqual(tasks.result_binding(unrelated, **current_binding(unrelated)), 'current')
        self.assertEqual(history_record['coordination']['history_publication_state'], 'not-published')
        self.assertNotEqual(unrelated['task_id'], history_record['task_id'])
        self.assertNotIn('history_capture', unrelated)

    def test_worker_return_must_match_requested_artifact_and_keeps_state_layers_separate(self):
        record = approve_release(acknowledge(bind(base(), requested_artifact='pdf-report')))
        binding = current_binding(record)
        for event in (
                {'id': 'artifact-dispatch', 'task': 'task-123', 'ts': 1790000040,
                 'source': 'adapter', 'kind': 'dispatched', 'data': {}},
                {'id': 'artifact-running', 'task': 'task-123', 'ts': 1790000041,
                 'source': 'worker', 'kind': 'running', 'data': binding}):
            record, outcome = tasks.apply(record, event)
            self.assertEqual(outcome, 'applied')
        adjacent = {'id': 'artifact-adjacent', 'task': 'task-123', 'ts': 1790000042,
                    'source': 'worker', 'kind': 'ready',
                    'data': {'commit': 'a' * 40, 'final_diff_digest': 'b' * 64,
                             'tests': 'passed', 'artifact_kind': 'provisioning-guidance',
                             'artifact_ref': 'handoff.md', 'result': 'Local commit created.',
                             'remaining': ['Push is not published.'], 'next_owner': 'source-owner',
                             **binding}}
        rejected, outcome = tasks.apply(record, adjacent)
        self.assertEqual((outcome, rejected['status']), ('unsupported', 'running'))
        self.assertEqual(len(rejected['approvals']), 1)
        self.assertIsNone(rejected['evidence'])

        correct = {**adjacent, 'id': 'artifact-correct', 'ts': 1790000043,
                   'data': {**adjacent['data'], 'artifact_kind': 'pdf-report',
                            'artifact_ref': 'report.pdf', 'result': 'Requested PDF produced.',
                            'remaining': [], 'next_owner': 'orchestrator'}}
        ready, outcome = tasks.apply(record, correct)
        self.assertEqual((outcome, ready['coordination']['acceptance_state']), ('applied', 'ready'))
        self.assertEqual(ready['coordination']['user_delivery_state'], 'not-delivered')
        self.assertEqual(ready['coordination']['history_publication_state'], 'not-published')
        verified, outcome = tasks.apply(ready, {
            'id': 'artifact-verified', 'task': 'task-123', 'ts': 1790000044,
            'source': 'verifier', 'kind': 'verified',
            'data': {'commit': 'a' * 40, 'final_diff_digest': 'b' * 64,
                     'tests_passed': True, **binding}})
        self.assertEqual(outcome, 'applied')
        delivered = tasks.record_user_delivery(
            verified, artifact_ref='report.pdf', receipt_ref='delivery:parent-1')
        self.assertEqual(delivered['coordination']['user_delivery_state'], 'delivered')
        self.assertEqual(delivered['coordination']['history_publication_state'], 'not-published')
        self.assertNotIn('acceptance', delivered['worker_return'])
        self.assertNotIn('user_delivery', delivered['worker_return'])
        self.assertEqual(delivered['coordination']['acceptance_state'], 'verified')

    def test_implementation_contract_preserves_prior_work_and_separates_local_commit_from_push(self):
        record = approve_release(acknowledge(bind(
            base(), requested_artifact='source-commit-and-push')))
        record = bind(
            record, revision=2, requested_artifact='source-commit-and-push',
            displaced_reason='Expanded implementation and publication criteria')
        record = acknowledge(record, revision=2)
        binding = current_binding(record)
        record = tasks.begin_dispatch(record, 'implementation-dispatch', resume=False)
        record = tasks.settle_dispatch(record, 'implementation-dispatch', 'sent')
        for event in (
                {'id': 'implementation-dispatch', 'task': 'task-123', 'ts': 1790000060,
                 'source': 'adapter', 'kind': 'dispatched', 'data': {}},
                {'id': 'implementation-dispatch:running', 'task': 'task-123', 'ts': 1790000061,
                 'source': 'worker', 'kind': 'running', 'data': binding}):
            record, outcome = tasks.apply(record, event)
            self.assertEqual(outcome, 'applied')
        guidance = {'id': 'implementation-dispatch:guidance', 'task': 'task-123',
                    'ts': 1790000062, 'source': 'worker', 'kind': 'ready',
                    'data': {'commit': 'c' * 40, 'final_diff_digest': 'd' * 64,
                             'tests': 'passed', 'artifact_kind': 'provisioning-guidance',
                             'artifact_ref': 'handoff.md', 'result': 'Guidance only.',
                             'remaining': ['Implementation and push remain.'],
                             'next_owner': 'worker-1', **binding}}
        rejected, outcome = tasks.apply(record, guidance)
        self.assertEqual((outcome, rejected['status']), ('unsupported', 'running'))
        implementation = {**guidance, 'id': 'implementation-dispatch:ready', 'ts': 1790000063,
                          'data': {**guidance['data'],
                                   'artifact_kind': 'source-commit-and-push',
                                   'artifact_ref': 'commit:c',
                                   'result': 'Implementation committed locally.',
                                   'remaining': ['Remote push is unpublished.']}}
        ready, outcome = tasks.apply(record, implementation)
        self.assertEqual(outcome, 'applied')
        ready = tasks.record_source_publication(
            ready, local_commit='c' * 40, local_receipt='git:show:c',
            remote_state='unpublished')
        coordination = ready['coordination']
        self.assertEqual(coordination['source_publication_state']['remote_state'], 'unpublished')
        self.assertEqual(coordination['history_publication_state'], 'not-published')
        self.assertEqual(coordination['user_delivery_state'], 'not-delivered')
        self.assertEqual([(x['id'], x['revision']) for x in coordination['obligations']],
                         [('fixture', 1)])
        self.assertEqual(ready['approvals'][0]['revision'], 1)

    def test_communication_brief_filters_priorities_and_does_not_repeat_valid_approval(self):
        record = bind(base())
        active = record['coordination']['active_deliverable']
        record['status'] = 'blocked'
        record['pending_decision'] = {
            'need': 'Approve exact publish', 'action': 'push', 'target': 'reviewed commit',
            'scope': 'fixture only', 'revision': 1,
            'contract_digest': active['contract_digest']}
        record, outcome = tasks.apply(record, {
            'id': 'brief-approval', 'task': 'task-123', 'ts': 1790000052,
            'source': 'user', 'kind': 'approval',
            'data': {'channel': 'chat', 'text': 'Approve reviewed commit push',
                     'action': 'push', 'target': 'reviewed commit', 'scope': 'fixture only',
                     'revision': 1, 'contract_digest': active['contract_digest']}})
        self.assertEqual(outcome, 'noted')
        brief = tasks.communication_brief(
            record, priority_candidates=[
                {'id': 'ship', 'rank': 1, 'action': 'Push reviewed commit',
                 'immediately_actionable': True, 'waiting_on': [], 'state': 'pending'},
                {'id': 'monitor', 'rank': 2, 'action': 'Observe real traffic',
                 'immediately_actionable': False, 'waiting_on': ['deployment'], 'state': 'pending'},
                {'id': 'old', 'rank': 3, 'action': 'Repeat finished work',
                 'immediately_actionable': True, 'waiting_on': [], 'state': 'completed'}],
            result='Exact approval already exists.', remaining=['Push and verify.'],
            next_owner='source-owner')
        self.assertEqual([x['id'] for x in brief['priorities']], ['ship'])
        self.assertIsNone(brief['approval_need'])
        self.assertEqual((brief['result'], brief['remaining'], brief['next_owner']),
                         ('Exact approval already exists.', ['Push and verify.'], 'source-owner'))
        stale = json.loads(json.dumps(record))
        stale['approvals'][0]['revision'] = 0
        stale_brief = tasks.communication_brief(
            stale, priority_candidates=[], result='Prior approval is stale.',
            remaining=['Current revision approval remains.'], next_owner='user')
        self.assertEqual(stale_brief['approval_need']['revision'], 1)

        multipart = json.loads(json.dumps(record))
        multipart['pending_decision']['parts'] = [
            {'action': 'push', 'target': 'reviewed commit', 'scope': 'fixture only',
             'wording': 'Approve the exact push?'}]
        multipart['approvals'][0]['revision'] = 0
        multipart_brief = tasks.communication_brief(
            multipart, priority_candidates=[], result='Prior multipart approval is stale.',
            remaining=['Current contract approval remains.'], next_owner='user')
        self.assertEqual(multipart_brief['approval_need']['revision'], 1)

    def test_stale_worker_task_drift_preserves_displaced_obligation(self):
        record = acknowledge(bind(base()))
        record = bind(record, revision=2, displaced_state='superseded',
                      displaced_reason='Current user revision replaced it')
        self.assertEqual(tasks.result_binding(record, deliverable_id='fixture', revision=1,
                                              contract_digest='stale'),
                         'stale-revision')
        self.assertEqual(record['coordination']['obligations'][0]['state'], 'superseded')
        self.assertEqual(record['coordination']['execution_state'], 'awaiting-readback')

    def test_result_boundary_rejects_stale_task_next_action_and_uncertain_dispatch(self):
        record = acknowledge(bind(base()))
        binding = current_binding(record)
        record, outcome = tasks.apply(record, {
            'id': 'dispatch-current', 'task': 'task-123', 'ts': 1790000001,
            'source': 'adapter', 'kind': 'dispatched', 'data': {}})
        self.assertEqual(outcome, 'applied')
        for key, value in (('task_id', 'old-task'), ('deliverable_id', 'old-deliverable'),
                           ('next_action', 'publish old result'),
                           ('packet_sha256', 'a' * 64)):
            stale = {**binding, key: value}
            rejected, outcome = tasks.apply(record, {
                'id': f'stale-{key}', 'task': 'task-123', 'ts': 1790000002,
                'source': 'worker', 'kind': 'running', 'data': stale})
            self.assertEqual((outcome, rejected['status']), ('unsupported', 'delivered'))

        uncertain = tasks.begin_dispatch(record, 'dispatch-uncertain', resume=False)
        rejected, outcome = tasks.apply(uncertain, {
            'id': 'uncertain-result', 'task': 'task-123', 'ts': 1790000002,
            'source': 'worker', 'kind': 'running', 'data': binding})
        self.assertEqual((outcome, rejected['status']), ('unsupported', 'delivered'))

    def test_audit_only_contract_rejects_an_out_of_scope_final(self):
        record = bind(base(), next_action='inspect audit evidence only')
        record = tasks.acknowledge_task_contract(
            record, deliverable_id='fixture', revision=1,
            changed_criteria='criteria revision 1',
            next_action='inspect audit evidence only', environment='local-test',
            receipt_ref='task:audit-readback')
        binding = {**current_binding(record), 'next_action': 'publish old result'}
        record, _ = tasks.apply(record, {
            'id': 'audit-dispatch', 'task': 'task-123', 'ts': 1790000001,
            'source': 'adapter', 'kind': 'dispatched', 'data': {}})
        rejected, outcome = tasks.apply(record, {
            'id': 'audit-final', 'task': 'task-123', 'ts': 1790000002,
            'source': 'worker', 'kind': 'ready',
            'data': {'commit': 'a' * 40, 'final_diff_digest': 'b' * 64,
                     'tests': 'passed', **binding}})
        self.assertEqual((outcome, rejected['status']), ('unsupported', 'delivered'))

    def test_contract_consumption_distinguishes_library_calls_from_native_enforcement(self):
        record = bind(base())
        self.assertEqual(tasks.contract_consumption(record)['final']['state'],
                         'helper-only-unconsumed')
        record = acknowledge(record)
        consumed = tasks.contract_consumption(record)
        self.assertEqual(consumed['dispatch']['caller'],
                         'tasks.acknowledge_task_contract')
        self.assertFalse(consumed['dispatch']['native_enforcement'])

        binding = current_binding(record)
        record, _ = tasks.apply(record, {
            'id': 'consume-dispatch', 'task': 'task-123', 'ts': 1790000010,
            'source': 'adapter', 'kind': 'dispatched', 'data': {}})
        record, outcome = tasks.apply(record, {
            'id': 'consume-final', 'task': 'task-123', 'ts': 1790000011,
            'source': 'worker', 'kind': 'ready',
            'data': {'commit': 'a' * 40, 'final_diff_digest': 'b' * 64,
                     'tests': 'passed', **binding}})
        self.assertEqual(outcome, 'applied')
        consumed = tasks.contract_consumption(record)
        self.assertEqual(consumed['final']['receipt_ref'], 'consume-final')
        self.assertFalse(consumed['final']['native_enforcement'])

    def test_completed_obligation_cannot_be_reopened_by_stale_narrative(self):
        record = acknowledge(bind(base()))
        record = bind(record, revision=2, displaced_state='queued',
                      displaced_reason='A new active deliverable took priority')
        record = tasks.complete_obligation(
            record, deliverable_id='fixture', revision=1,
            completion_ref='verification:revision-1')
        reconciled, decision = tasks.reconcile_obligation_claim(
            record, deliverable_id='fixture', revision=1, claimed_state='running',
            source_ref='stale-summary:revision-1')
        self.assertEqual(decision, 'completion-preserved')
        self.assertEqual(reconciled['coordination']['obligations'], [])
        self.assertEqual(reconciled['coordination']['completed_obligations'][0]['state'],
                         'completed')

    def test_dispatch_and_acceptance_do_not_replace_current_revision_readback(self):
        record = bind(base())
        for event in ({'id': 'dispatch-1', 'task': 'task-123', 'ts': 1790000001,
                       'source': 'adapter', 'kind': 'dispatched', 'data': {}},
                      {'id': 'accepted-1', 'task': 'task-123', 'ts': 1790000002,
                       'source': 'worker', 'kind': 'accepted', 'data': {}}):
            record, outcome = tasks.apply(record, event)
            self.assertEqual(outcome, 'applied')
            self.assertEqual(record['coordination']['execution_state'], 'awaiting-readback')

    def test_contract_revision_is_monotonic_and_exact_replay_preserves_readback(self):
        record = acknowledge(bind(base(), revision=2), revision=2)
        replayed = bind(record, revision=2)
        self.assertEqual(replayed['coordination']['active_deliverable']['readback_ref'],
                         'task:readback-2')
        with self.assertRaises(ValueError):
            bind(record, revision=1, displaced_reason='invalid rollback')
        with self.assertRaises(ValueError):
            bind(record, revision=2, environment='other')

    def test_verifier_cannot_bypass_missing_current_readback(self):
        record = bind(base())
        record, _ = tasks.apply(record, {'id': 'dispatch-x', 'task': 'task-123',
                                         'ts': 1790000001, 'source': 'adapter',
                                         'kind': 'dispatched', 'data': {}})
        ready = {'id': 'ready-x', 'task': 'task-123', 'ts': 1790000002,
                 'source': 'verifier', 'kind': 'ready',
                 'data': {'commit': 'abc', 'tests': 'passed', **current_binding(record)}}
        record, outcome = tasks.apply(record, ready)
        self.assertEqual((outcome, record['status']), ('unsupported', 'delivered'))

    def test_hidden_result_requires_pagination_to_last_consumed_receipt(self):
        record = tasks.consume_evidence(base(), source='native-task', receipt='receipt-2',
                                        observed_at='2026-10-08T10:00:00Z')
        self.assertEqual(tasks.evidence_page(record, source='native-task',
                                             receipt_ids=['receipt-4'], has_more=True), 'continue')
        self.assertEqual(tasks.evidence_page(record, source='native-task',
                                             receipt_ids=['receipt-3', 'receipt-2'], has_more=False),
                         'complete')
        self.assertEqual(tasks.evidence_page(record, source='native-task',
                                             receipt_ids=['receipt-1'], has_more=False), 'gap')

    def test_conditional_edge_risk_is_separate_from_observed_impact(self):
        record = tasks.set_decision_frame(
            base(), decision_id='decision-1', rank=1, scope='fixture only', target='local behavior',
            prerequisites=['current revision'], mechanism='bounded retry',
            exposure_frequency='rare', technical_risk='bounded duplicate attempt',
            observed_impact='none in sampled receipts',
            conditional_impact='duplicate action if idempotency is absent',
            business_decision='owner decides whether residual risk is acceptable',
            activation_state='pending', priority_source_ref='task:priority-1')
        decision = record['coordination']['decisions'][0]
        self.assertNotEqual(decision['observed_impact'], decision['conditional_impact'])
        self.assertEqual(decision['activation_state'], 'pending')

    def test_independent_decisions_are_ranked_without_overwrite(self):
        record = tasks.set_decision_frame(
            base(), decision_id='decision-2', rank=2, scope='second', target='local',
            prerequisites=['evidence'], mechanism='manual choice', exposure_frequency='daily',
            technical_risk='low', observed_impact='none', conditional_impact='delay',
            business_decision='owner chooses', activation_state='pending',
            priority_source_ref='task:priority-1')
        record = tasks.set_decision_frame(
            record, decision_id='decision-1', rank=1, scope='first', target='local',
            prerequisites=['evidence'], mechanism='manual choice', exposure_frequency='daily',
            technical_risk='low', observed_impact='none', conditional_impact='delay',
            business_decision='owner chooses', activation_state='pending',
            priority_source_ref='task:priority-1')
        self.assertEqual([x['id'] for x in record['coordination']['decisions']],
                         ['decision-1', 'decision-2'])

    def test_out_of_order_duplicate_receipts_do_not_regress_state(self):
        record = base()
        dispatched = {'id': 'dispatch-1', 'task': 'task-123', 'ts': 1790000001,
                      'source': 'adapter', 'kind': 'dispatched', 'data': {}}
        running = {'id': 'running-1', 'task': 'task-123', 'ts': 1790000003,
                   'source': 'worker', 'kind': 'running', 'data': {}}
        late = {'id': 'accepted-late', 'task': 'task-123', 'ts': 1790000002,
                'source': 'worker', 'kind': 'accepted', 'data': {}}
        for event in (dispatched, running):
            record, outcome = tasks.apply(record, event)
            self.assertEqual(outcome, 'applied')
        record, outcome = tasks.apply(record, late)
        self.assertEqual((outcome, record['status']), ('stale', 'running'))
        record, outcome = tasks.apply(record, running)
        self.assertEqual((outcome, record['status']), ('duplicate', 'running'))

    def test_stale_display_does_not_change_canonical_execution_or_acceptance(self):
        record = acknowledge(bind(base()))
        record['coordination']['acceptance_state'] = 'verified'
        record = tasks.set_display_sync(record, surface_ref='task-card', state='stale')
        self.assertEqual(record['coordination']['execution_state'], 'admitted')
        self.assertEqual(record['coordination']['acceptance_state'], 'verified')
        self.assertEqual(record['coordination']['display_sync']['task-card']['state'], 'stale')

    def test_offline_recovery_retains_contract_and_cursor(self):
        record = acknowledge(bind(base()))
        record = tasks.consume_evidence(record, source='worker', receipt='worker-7',
                                        observed_at='2026-10-08T10:00:00Z')
        restored = json.loads(json.dumps(record))
        self.assertEqual(tasks.result_binding(restored, **current_binding(restored)), 'current')
        self.assertEqual(restored['coordination']['evidence_cursors']['worker']
                         ['last_consumed_receipt'], 'worker-7')

    def test_final_diff_release_requires_owner_lock_revision_scope_and_pause_ack(self):
        record = tasks.request_pause(approve_release(verify_active(
            acknowledge(bind(base())))), source_ref='task:pause-request')
        blocked, gate = tasks.release_gate(
            record, head='a' * 40, final_diff_digest='b' * 64, scope='fixture only',
            approved_scope='fixture only', revision=1, lock_owner='worker-1',
            approval_action='release', approval_target='reviewed fixture',
            expected_owner='worker-1', pause_required=True)
        self.assertEqual((gate, blocked['coordination']['deployment_state']['reasons']),
                         ('blocked', ['pause-unconfirmed']))
        record = tasks.confirm_pause(record, execution_owner='worker-1',
                                     receipt_ref='task:pause-ack')
        released, gate = tasks.release_gate(
            record, head='a' * 40, final_diff_digest='b' * 64, scope='fixture only',
            approved_scope='fixture only', revision=1, lock_owner='worker-1',
            approval_action='release', approval_target='reviewed fixture',
            expected_owner='worker-1', pause_required=True)
        self.assertEqual(gate, 'admitted')
        self.assertEqual(released['coordination']['deployment_state']['pause_ack_ref'],
                         'task:pause-ack')
        consumption = tasks.contract_consumption(released)['release']
        self.assertEqual((consumption['caller'], consumption['outcome'],
                          consumption['native_enforcement']),
                         ('tasks.release_gate', 'admitted', False))

        mismatch, gate = tasks.release_gate(
            record, head='c' * 40, final_diff_digest='d' * 64, scope='fixture only',
            approved_scope='fixture only', revision=1, lock_owner='worker-1',
            approval_action='release', approval_target='reviewed fixture',
            expected_owner='worker-1', pause_required=True)
        self.assertEqual(gate, 'blocked')
        self.assertEqual(mismatch['coordination']['deployment_state']['reasons'],
                         ['accepted-head-mismatch', 'accepted-diff-mismatch'])

    def test_release_gate_rejects_missing_approval_readback_and_pause_bypass(self):
        record = tasks.request_pause(bind(base()), source_ref='task:pause-request')
        blocked, gate = tasks.release_gate(
            record, head='a' * 40, final_diff_digest='b' * 64, scope='fixture only',
            approved_scope='fixture only', revision=1, approval_action='release',
            approval_target='reviewed fixture', lock_owner='worker-1',
            expected_owner='worker-1', pause_required=False)
        self.assertEqual(gate, 'blocked')
        self.assertEqual(blocked['coordination']['deployment_state']['reasons'],
                         ['missing-current-readback', 'approval-missing',
                          'acceptance-not-verified', 'accepted-head-mismatch',
                          'accepted-diff-mismatch', 'pause-unconfirmed'])

    def test_release_approval_cannot_cross_contract_revisions(self):
        record = approve_release(verify_active(acknowledge(bind(base()))))
        record = acknowledge(bind(record, revision=2, displaced_reason='New requirements'),
                             revision=2)
        record['coordination']['acceptance_state'] = 'verified'
        blocked, gate = tasks.release_gate(
            record, head='a' * 40, final_diff_digest='b' * 64, scope='fixture only',
            approved_scope='fixture only', revision=2, approval_action='release',
            approval_target='reviewed fixture', lock_owner='worker-1',
            expected_owner='worker-1', pause_required=False)
        self.assertEqual(gate, 'blocked')
        self.assertIn('approval-missing', blocked['coordination']['deployment_state']['reasons'])

    def test_user_decision_and_acceptance_have_distinct_split_states(self):
        record = base()
        for event in ({'id': 'd', 'task': 'task-123', 'ts': 1790000001,
                       'source': 'adapter', 'kind': 'dispatched', 'data': {}},
                      {'id': 'b', 'task': 'task-123', 'ts': 1790000002,
                       'source': 'worker', 'kind': 'blocked', 'data': {'need': 'choose'}},
                      {'id': 'u', 'task': 'task-123', 'ts': 1790000003,
                       'source': 'user', 'kind': 'decided',
                       'data': {'channel': 'chat', 'text': 'Choose option A'}}):
            record, _ = tasks.apply(record, event)
        self.assertEqual(record['coordination']['execution_state'], 'awaiting-dispatch')

        def ready():
            value = base()
            for event in ({'id': 'rd', 'task': 'task-123', 'ts': 1790000010,
                           'source': 'adapter', 'kind': 'dispatched', 'data': {}},
                          {'id': 'rr', 'task': 'task-123', 'ts': 1790000011,
                           'source': 'worker', 'kind': 'running', 'data': {}},
                          {'id': 'ry', 'task': 'task-123', 'ts': 1790000012,
                           'source': 'worker', 'kind': 'ready',
                           'data': {'commit': 'abc123', 'tests': 'passed'}}):
                value, _ = tasks.apply(value, event)
            return value

        verified, outcome = tasks.apply(ready(), {
            'id': 'verify', 'task': 'task-123', 'ts': 1790000013, 'source': 'verifier',
            'kind': 'verified', 'data': {'commit': 'abc123', 'tests_passed': True}})
        self.assertEqual((outcome, verified['coordination']['acceptance_state']),
                         ('applied', 'verified'))
        accepted, outcome = tasks.apply(ready(), {
            'id': 'accept', 'task': 'task-123', 'ts': 1790000013, 'source': 'user',
            'kind': 'verified', 'data': {'channel': 'chat', 'text': 'Accept this result',
                                         'commit': 'abc123', 'tests_passed': True}})
        self.assertEqual((outcome, accepted['coordination']['acceptance_state']),
                         ('applied', 'accepted'))
        rejected, outcome = tasks.apply(ready(), {
            'id': 'reject', 'task': 'task-123', 'ts': 1790000013, 'source': 'verifier',
            'kind': 'rejected', 'data': {}})
        self.assertEqual((outcome, rejected['coordination']['acceptance_state']),
                         ('applied', 'rejected'))

    def test_watch_baseline_emits_only_on_change(self):
        record = tasks.set_watch_baseline(base(), watch_id='watch-1', scope='task status',
                                          digest_value='same', observed_at='2026-10-08T10:00:00Z',
                                          source_ref='task:status')
        self.assertFalse(tasks.watch_changed(record, watch_id='watch-1', digest_value='same'))
        self.assertTrue(tasks.watch_changed(record, watch_id='watch-1', digest_value='changed'))


if __name__ == '__main__':
    unittest.main()
