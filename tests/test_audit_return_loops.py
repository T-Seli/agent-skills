"""Adversarial acceptance and return-loop regressions; no native host claims."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from agent_skills.task_contract import assess_completion, packet

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'skills/agent-coordination/scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

tasks, workers = load('tasks'), load('workers')
HEAD, HASH = 'c' * 40, 'd' * 64


def bind(record, revision=1, deliverable='caller-validation', **options):
    fields = dict(user_goal='Validate finite caller', constraints=['synthetic only'],
        priority_source_ref='user:priority', canonical_issue_ref='task:current',
        canonical_owner='same-owner', deliverable_id=deliverable, revision=revision,
        acceptance_ref='checks:caller', environment='isolated',
        changed_criteria='consume successful embedding evidence', next_action='validate caller',
        source_ref='user:original-decision', requested_artifact='caller-report',
        authority_ref='user:approval-caller', artifact_ref='caller:r1',
        gates=['finite caller validation', 'no paid rerun'])
    return tasks.bind_task_contract(record, **{**fields, **options})


def acknowledge(record, source='user:original-decision'):
    active = record['coordination']['active_deliverable']
    return tasks.acknowledge_task_contract(record, deliverable_id=active['id'], revision=active['revision'],
        changed_criteria=active['changed_criteria'], next_action=active['next_action'],
        environment=active['environment'], receipt_ref='worker:readback', decision_source_ref=source)


def base():
    return tasks.new_task('task-current', 'audit-fixture', worker_kind='local', owner='assistant',
        repo='synthetic', worktree='synthetic')


def brief(record):
    return tasks.communication_brief(record, priority_candidates=[], result='Current evidence below',
        remaining=['native use unverified'], next_owner='same-owner')


def event(record, kind, ts, source='worker', **data):
    return {'id': 'receipt-' + str(ts), 'task': record['task_id'], 'ts': ts,
            'source': source, 'kind': kind, 'data': {**tasks.current_task_binding(record), **data}}


def returned():
    record = acknowledge(bind(base()))
    record, _ = tasks.apply(record, event(record, 'dispatched', 1790000100, source='adapter'))
    data = dict(commit=HEAD, final_diff_digest=HASH, tests='caller pass', artifact_kind='caller-report',
        artifact_ref='/unavailable/on/parent/caller.json', result='13 embedding inputs succeeded', remaining=[],
        next_owner='parent', material_facts=[{'fact': '13 embedding inputs succeeded; no paid rerun needed',
            'source_ref': 'worker:embedding-success', 'evidence_level': 'performed'}])
    record, outcome = tasks.apply(record, event(record, 'ready', 1790000101, **data))
    assert outcome == 'applied'
    return record


class ReturnLoops(unittest.TestCase):
    def test_scoped_release_consumes_source_without_weakening_approval_gates(self):
        record = returned()
        record, outcome = tasks.apply(record, event(record, 'verified', 1790000102, source='verifier',
            commit=HEAD, final_diff_digest=HASH, tests_passed=True))
        self.assertEqual(outcome, 'applied')
        args = dict(head=HEAD, final_diff_digest=HASH, scope='caller only', approved_scope='caller only',
            revision=1, approval_action='release', approval_target='caller', lock_owner='same-owner',
            expected_owner='same-owner', pause_required=False)
        _, verdict = tasks.release_gate(record, **args)
        self.assertEqual(verdict, 'blocked')
        record, _ = tasks.apply(record, event(record, 'approval', 1790000103, source='user',
            channel='chat', text='Approve exact caller release', action='release', target='caller', scope='caller only'))
        updated, verdict = tasks.release_gate(record, **args)
        self.assertEqual(verdict, 'admitted')
        self.assertEqual(updated['coordination']['deployment_state']['reasons'], [])

    def test_admission_does_not_consume_original_decision(self):
        record = bind(base())
        record, _ = tasks.apply(record, event(record, 'dispatched', 1790000001, source='adapter'))
        record, _ = tasks.apply(record, event(record, 'accepted', 1790000002))
        self.assertEqual(record['coordination']['execution_state'], 'awaiting-readback')
        with self.assertRaisesRegex(ValueError, 'original decision source'):
            acknowledge(record, source='assistant:summary')
        record = acknowledge(record)
        wrong = {**tasks.current_task_binding(record), 'decision_source_ref': 'old:failure'}
        self.assertEqual(tasks.result_binding(record, **wrong), 'missing-decision-consumption')
        self.assertEqual(tasks.result_binding(record, **tasks.current_task_binding(record)), 'current')

    def test_same_owner_subdeliverables_retain_scope_authority_and_receipts(self):
        record = returned()
        record = bind(record, revision=2, deliverable='three-edit-patch',
            requested_artifact='source-patch', artifact_ref='patch:r2',
            authority_ref='user:approval-three-edits', gates=['three edits only', 'spacing excluded'],
            displaced_reason='Patch acceptance is separate from finite caller validation')
        rows = {row['id']: row for row in brief(record)['subdeliverables']}
        self.assertEqual(rows['caller-validation']['owner'], rows['three-edit-patch']['owner'])
        self.assertEqual(rows['caller-validation']['task_id'], 'task-current')
        self.assertEqual(rows['caller-validation']['authority_ref'], 'user:approval-caller')
        self.assertEqual(rows['three-edit-patch']['gates'], ['three edits only', 'spacing excluded'])
        self.assertEqual(rows['caller-validation']['latest_receipt'], 'receipt-1790000101')
        self.assertIn('13 embedding inputs', rows['caller-validation']['material_facts'][0]['fact'])
        self.assertEqual(rows['caller-validation']['source_ref'], 'user:original-decision')
        self.assertEqual(brief(record)['material_facts'], [])

    def test_historical_inner_deliverable_does_not_close_current_task(self):
        record = acknowledge(bind(base(), deliverable='13c-adoption'))
        record, _ = tasks.apply(record, event(record, 'dispatched', 1790000001, source='adapter'))
        record, outcome = tasks.apply(record, event(record, 'ready', 1790000002,
            deliverable_id='a49-release', commit=HEAD, final_diff_digest=HASH, tests='pass'))
        self.assertEqual(outcome, 'unsupported')
        self.assertEqual(record['status'], 'delivered')
        self.assertIsNone(record['evidence'])
        self.assertEqual(brief(record)['subdeliverables'][0]['id'], '13c-adoption')

    def test_local_link_loss_keeps_inline_fact_but_parent_readback_is_separate(self):
        record = returned()
        value = brief(record)
        self.assertIn('no paid rerun', value['material_facts'][0]['fact'])
        self.assertEqual(value['return_loop']['state'], 'pending-parent-readback')
        args = dict(binding=tasks.current_task_binding(record), result_receipt_ref='receipt-1790000101',
            decision_source_ref='user:original-decision', read_receipt_ref='parent:read', answer_ref='parent:answer')
        for wrong in ({'result_receipt_ref': 'historical:result'}, {'decision_source_ref': 'assistant:summary'},
                      {'binding': {**args['binding'], 'revision': 0}}):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                tasks.reconcile_parent_readback(record, **{**args, **wrong})
        record = tasks.reconcile_parent_readback(record, **args)
        self.assertEqual(brief(record)['return_loop']['state'], 'closed')
        self.assertEqual(record['coordination']['acceptance_state'], 'ready')
        self.assertFalse(tasks.contract_consumption(record)['final']['native_enforcement'])
        record = bind(record, revision=2, displaced_reason='new caller criteria')
        self.assertEqual(brief(record)['return_loop']['state'], 'pending-parent-readback')
        self.assertIsNone(brief(record)['return_loop']['worker_result'])

    def test_inline_fact_required_and_worker_adapter_preserves_it(self):
        record = acknowledge(bind(base()))
        kwargs = dict(deliverable_id='caller-validation', revision=1,
            contract_digest=tasks.current_task_binding(record)['contract_digest'],
            artifact_kind='caller-report', artifact_ref='unavailable:artifact', result='Success',
            remaining=[], next_owner='parent', decision_source_ref='user:original-decision')
        with self.assertRaisesRegex(ValueError, 'inline material facts'):
            tasks.assess_worker_return(record, **kwargs)
        rep = {**tasks.current_task_binding(record), 'status': 'ready',
            'material_facts': [{'fact': 'Embedding succeeded', 'source_ref': 'worker:receipt', 'evidence_level': 'performed'}]}
        parsed = {'session_id': 'synthetic-session', 'error': False, 'report': rep}
        data = workers.events('task-current', 'dispatch-1', parsed, 1790000001, 1790000002)[1]['data']
        self.assertEqual(data['material_facts'], rep['material_facts'])
        self.assertEqual(data['decision_source_ref'], 'user:original-decision')


class OutcomeEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'receipt.json').write_text('synthetic observed results')
        self.sha = hashlib.sha256((self.root / 'receipt.json').read_bytes()).hexdigest()

    def packet(self):
        criteria = []
        for stage, expected in [('component-tests', {'role-suite': 'pass'}),
                ('composed-route', {'ordinary-manager': '200', 'Executive': '403'}),
                ('provisioning', {'create': 'success'}), ('first-login', {'login': 'success'})]:
            criteria.append({'id': stage, 'check': stage, 'evidence_binding': {
                'surface': 'manager workflow', 'fixture': 'ordinary manager', 'environment': 'isolated',
                'candidate': HEAD, 'artifact_kinds': ['receipt'], 'outcome': 'can create and onboard',
                'stage': stage, 'expected_results': expected}})
        return packet(task_id='task-current', revision=1, owner='same-owner', scope='outcome readiness',
            exclusions=['product repair'], baseline=HEAD, deliverables=['outcome answer'], acceptance=criteria,
            context_refs=[], source_hashes={'skill': HASH}, package_hashes={'skill': HASH},
            stop_conditions=['scope changed'], escalation_conditions=['missing evidence'])

    def reports(self, value):
        items = {}
        for c in value['acceptance']:
            b = c['evidence_binding']
            items[c['id']] = {**{k: b[k] for k in ('surface', 'fixture', 'environment', 'outcome', 'stage')},
                'commit': HEAD, 'reference': 'worker:observed', 'check_result': 'pass',
                'artifact_hashes': {'receipt': self.sha}, 'artifacts': {'receipt': 'receipt.json'},
                'observed_results': b['expected_results'].copy()}
        report = dict(task_id=value['task_id'], revision=value['revision'], packet_sha256=value['packet_sha256'],
                      criterion_evidence=items)
        verified = copy.deepcopy(report)
        for item in verified['criterion_evidence'].values():
            item.update(inspector='independent', inspection_result='pass', candidate=HEAD)
        return report, verified

    def test_component_pass_and_manager403_hold_worker_and_parent(self):
        value = self.packet()
        report, verifier = self.reports(value)
        report['criterion_evidence']['composed-route']['observed_results']['ordinary-manager'] = '403'
        verifier['criterion_evidence']['composed-route']['observed_results']['ordinary-manager'] = '403'
        assessment = assess_completion(value, report, verifier, artifact_root=self.root)
        self.assertEqual(assessment['outcome_readiness']['can create and onboard']['verdict'], 'HOLD')
        self.assertEqual(assessment['missing'], ['composed-route'])
        record = tasks.new_task('task-current', 'outcome', worker_kind='local', owner='assistant',
            repo='synthetic', worktree=str(self.root), acceptance_packet=value)
        record, _ = tasks.apply(record, {'id': 'd', 'task': 'task-current', 'ts': 1790000001,
            'source': 'adapter', 'kind': 'dispatched', 'data': {}})
        record, outcome = tasks.apply(record, {'id': 'r', 'task': 'task-current', 'ts': 1790000002,
            'source': 'verifier', 'kind': 'ready', 'data': {'commit': HEAD, 'tests': 'role suite pass',
                'completion_report': report, 'verifier_report': verifier}})
        self.assertEqual(outcome, 'unsupported')
        self.assertEqual(brief(record)['outcome_readiness']['can create and onboard']['verdict'], 'HOLD')
        self.assertEqual(record['status'], 'delivered')

    def test_wrong_outer_candidate_cannot_leak_positive_readiness_to_parent(self):
        value = self.packet()
        report, verifier = self.reports(value)
        record = tasks.new_task('task-current', 'outcome', worker_kind='local', owner='assistant',
            repo='synthetic', worktree=str(self.root), acceptance_packet=value)
        record, _ = tasks.apply(record, {'id': 'd', 'task': 'task-current', 'ts': 1790000001,
            'source': 'adapter', 'kind': 'dispatched', 'data': {}})
        record, outcome = tasks.apply(record, {'id': 'wrong-candidate', 'task': 'task-current', 'ts': 1790000002,
            'source': 'verifier', 'kind': 'ready', 'data': {'commit': 'e' * 40, 'tests': 'pass',
                'completion_report': report, 'verifier_report': verifier}})
        self.assertEqual(outcome, 'unsupported')
        self.assertEqual(brief(record)['outcome_readiness']['can create and onboard']['verdict'], 'HOLD')
        self.assertIsNone(brief(record)['readiness_receipt'])
        self.assertEqual(brief(record)['outcome_readiness']['can create and onboard']['candidate'], HEAD)

    def test_positive_and_denied_composed_paths_pass_without_proving_first_login(self):
        value = self.packet()
        report, verifier = self.reports(value)
        del report['criterion_evidence']['first-login']
        result = assess_completion(value, report, verifier, artifact_root=self.root)
        self.assertEqual(result['missing'], ['first-login'])
        self.assertEqual(result['outcome_readiness']['can create and onboard']['stages']['composed-route'], 'EVIDENCE-COMPLETE')
        report, verifier = self.reports(value)
        self.assertEqual(assess_completion(value, report, verifier, artifact_root=self.root)['status'],
            'evidence-complete-awaiting-acceptance')
        for key, wrong in [('commit', 'e' * 40), ('stage', 'component-tests'),
                ('outcome', 'other outcome'), ('environment', 'other')]:
            changed = copy.deepcopy(report)
            changed['criterion_evidence']['composed-route'][key] = wrong
            self.assertIn('composed-route', assess_completion(value, changed, verifier, artifact_root=self.root)['missing'])

    def test_manual_waiver_is_not_positive_evidence_even_for_legacy_criterion(self):
        # Legacy packets remain usable; a waiver must still not pass their criterion.
        criterion = {'id': 'manual', 'check': 'ordinary manager route succeeds'}
        legacy = packet(task_id='task-current', revision=1, owner='same-owner', scope='route check',
            exclusions=[], baseline=HEAD, deliverables=['route'], acceptance=[criterion], context_refs=[],
            source_hashes={'skill': HASH}, package_hashes={'skill': HASH}, stop_conditions=['changed'], escalation_conditions=['missing'])
        report = dict(task_id=legacy['task_id'], revision=1, packet_sha256=legacy['packet_sha256'],
            criterion_evidence={'manual': {'reference': 'user:waiver', 'check_result': 'pass',
                'commit': HEAD, 'environment': 'isolated', 'evidence_type': 'manual-waiver'}})
        self.assertEqual(assess_completion(legacy, report)['missing'], ['manual'])
        value = self.packet()
        report, verifier = self.reports(value)
        report['criterion_evidence']['composed-route']['evidence_type'] = 'manual-waiver'
        self.assertIn('composed-route', assess_completion(value, report, verifier, artifact_root=self.root)['missing'])
        report, verifier = self.reports(value)
        verifier['criterion_evidence']['composed-route']['evidence_type'] = 'manual-waiver'
        self.assertIn('composed-route', assess_completion(value, report, verifier, artifact_root=self.root)['missing'])


if __name__ == '__main__':
    unittest.main()
