"""Strict launcher composition over existing task contracts; no host/tool authority."""
import copy
import json
from .task_contract import digest


def bind(tasks, record, value):
    """Require an explicit outcome contract; never infer authority from prompt text."""
    if not isinstance(value, dict) or set(value) != {'contract', 'acceptance_packet'}:
        raise ValueError('contract and acceptance_packet required')
    contract, packet = value['contract'], value['acceptance_packet']
    if not isinstance(contract, dict) or not isinstance(packet, dict):
        raise ValueError('structured contract and acceptance packet required')
    if packet.get('revision') != contract.get('revision'):
        raise ValueError('packet and contract revisions differ')
    if packet.get('execution_owner') != contract.get('canonical_owner'):
        raise ValueError('packet and contract owners differ')
    required = {'authority_ref', 'artifact_ref', 'gates', 'requested_artifact'}
    if not required <= contract.keys():
        raise ValueError('explicit authority, artifact and gates required')
    record = tasks.bind_packet(record, packet)
    record = tasks.bind_task_contract(record, **contract)
    record['producer_contract_version'] = 1
    return record


def envelope(tasks, record):
    active = copy.deepcopy(record['coordination']['active_deliverable'])
    for key in ('readback_ref', 'acknowledged_source_ref', 'history_readback',
                'parent_readback', 'result_receipt_ref', 'material_facts'):
        active.pop(key, None)
    return {'binding': tasks.current_task_binding(record),
            'contract': active,
            'user_goal': record['coordination']['user_goal'],
            'constraints': record['coordination']['constraints'],
            'acceptance_packet': record['acceptance_packet'],
            'canonical_history': copy.deepcopy(record.get('canonical_history'))}


def acknowledgment_binding(tasks, record):
    return {**tasks.current_task_binding(record), 'context_digest': digest(envelope(tasks, record))}


def require_execution_authority(tasks, record):
    """Hold this task's dependent execution; grants never come from worker prose."""
    if not record.get('pending_decision'):
        return
    pending = tasks.pending(record)
    parts = pending.get('parts')
    if parts:
        allowed = tasks.approved_parts(record, parts)
    else:
        allowed = (pending.get('action') and pending.get('target') and
                   tasks.approved(record, pending['action'], pending['target']))
    if not allowed:
        raise ValueError('current task decision unresolved; hold dependent execution')


def acknowledgment_schema(tasks, record):
    """A separate no-tools turn must echo every bound value, not simply say yes."""
    binding = acknowledgment_binding(tasks, record)
    return {'type': 'object', 'additionalProperties': False,
            'required': list(binding),
            'properties': {key: {'type': ('null' if value is None else 'integer'
                                        if type(value) is int else 'string')}
                           for key, value in binding.items()}}


def record_reported_result(record, *, tasks, dispatch_id, report, receipt_ref):
    """Retain a reported artifact independently from verified acceptance/readiness."""
    execution = next(x for x in record['outbox'] if x['id'] == dispatch_id).get('execution') or {}
    if not execution.get('result_received') or report.get('status') not in ('answered', 'ready'):
        raise ValueError('successful exact worker execution result required')
    binding = tasks.current_task_binding(record)
    if (any(report.get(key) != value or type(report.get(key)) is not type(value)
            for key, value in binding.items()) or tasks.result_binding(record, **binding) != 'current'):
        raise ValueError('reported result does not consume the current binding')
    result = tasks.assess_worker_return(record, deliverable_id=report['deliverable_id'],
        revision=report['revision'], contract_digest=report['contract_digest'],
        artifact_kind=report.get('artifact_kind'), artifact_ref=report.get('artifact_ref'),
        result=report.get('result'), remaining=report.get('remaining'), next_owner=report.get('next_owner'),
        decision_source_ref=report.get('decision_source_ref'), material_facts=report.get('material_facts'))
    if result['status'] != 'current-artifact':
        raise ValueError('reported artifact does not match the current deliverable')
    r = copy.deepcopy(record)
    active = r['coordination']['active_deliverable']
    active['reported_result'] = {**result, 'receipt_ref': receipt_ref,
                                 'stdout_sha256': execution['stdout_sha256'], 'dispatch_id': dispatch_id}
    active['result_receipt_ref'] = receipt_ref
    active['material_facts'] = result.get('material_facts', [])
    active.pop('parent_readback', None)
    r['coordination']['execution_state'] = 'finished'
    tasks._record_contract_consumption(r['coordination'], 'final',
                                       'delegate.record_reported_result', receipt_ref)
    return r


def consume(record, *, tasks, acknowledgment, session_id, expected_session_id, receipt_ref):
    if session_id != expected_session_id or not session_id:
        raise ValueError('worker session mismatch')
    expected = acknowledgment_binding(tasks, record)
    if (not isinstance(acknowledgment, dict) or acknowledgment != expected or
            any(type(acknowledgment[key]) is not type(value) for key, value in expected.items())):
        raise ValueError('worker acknowledgment is missing or stale')
    active = record['coordination']['active_deliverable']
    canonical = record.get('canonical_history') or {}
    record = tasks.acknowledge_task_contract(
        record, deliverable_id=active['id'], revision=active['revision'],
        changed_criteria=active['changed_criteria'], next_action=active['next_action'],
        environment=active['environment'], decision_source_ref=active['source_ref'],
        history_revision=canonical.get('revision'), history_digest=canonical.get('digest'),
        receipt_ref=receipt_ref)
    record['worker']['session_id'] = session_id
    return record


def retain_seed_session(record, *, session_id, expected_session_id, receipt_ref):
    """A completed CLI phase can prove session identity even if its readback is wrong."""
    if (not session_id or session_id != expected_session_id or
            record['worker']['owner'] != 'assistant' or
            record['worker'].get('session_id') not in (None, session_id)):
        raise ValueError('owned seed session identity mismatch')
    r = copy.deepcopy(record)
    r['worker']['session_id'] = session_id
    r['worker']['seed_session_receipt'] = receipt_ref
    return r


def execution_prompt(tasks, record, prompt):
    return ('Current enforced task contract (echo binding in final report):\n' +
            json.dumps(envelope(tasks, record), sort_keys=True) + '\n\n' + prompt)
