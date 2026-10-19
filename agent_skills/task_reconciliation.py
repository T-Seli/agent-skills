"""Bounded, caller-supplied evidence assessment. Never dispatches or grants authority."""
from .task_checkpoint import operating_view, _time


def keep_awake_assessment(receipt, *, now, owner):
    """Check a structured assertion receipt; no process control or sleep attribution."""
    if not receipt:
        return {'state': 'unverified', 'reason': 'missing-receipt'}
    required = ('owner', 'pid', 'process_identity_ref', 'assertion_ref',
                'observed_at_utc', 'expires_at_utc', 'cleanup_ref')
    if any(not receipt.get(k) for k in required):
        return {'state': 'unverified', 'reason': 'incomplete-receipt'}
    if type(receipt['pid']) is not int or receipt['pid'] <= 0:
        raise ValueError('positive PID required')
    if not _time(receipt['observed_at_utc']) <= _time(now) < _time(receipt['expires_at_utc']):
        return {'state': 'unverified', 'reason': 'stale-or-future-receipt'}
    return {'state': 'receipt-verified', 'owner': receipt['owner'],
            'reuse_existing_owner': receipt['owner'] != owner,
            'live_probe_performed': False, 'cleanup_authorized': False}


def reconcile_tasks(snapshot, *, now):
    """Inventory completeness is explicit; observations bind exact revision and source.

    Snapshot: expected_task_ids, records, observations. Observation fields include
    task_id, revision, decision_source_ref, observed_at_utc, expires_at_utc,
    required_operations/forbidden_operations (exact canonical operation IDs).
    Results advise reconciliation only, even when prior approval is recorded.
    """
    clock = _time(now)
    expected = snapshot['expected_task_ids']
    if not isinstance(expected, list) or any(not isinstance(x, str) or not x for x in expected):
        raise ValueError('expected_task_ids must be nonempty identifiers')
    records = snapshot['records']
    ids = [r['task_id'] for r in records]
    observations = snapshot.get('observations', [])
    obs_ids = [o['task_id'] for o in observations]
    if len(set(ids)) != len(ids) or len(set(expected)) != len(expected) or len(set(obs_ids)) != len(obs_ids):
        raise ValueError('duplicate task identity')
    rows = []
    for record in records:
        tid = record['task_id']
        c = record.get('coordination') or {}
        active = c.get('active_deliverable') or {}
        worker = record.get('worker') or {}
        issues = []
        if not active:
            issues.append('missing-active-contract')
        if not c.get('canonical_owner'):
            issues.append('missing-canonical-owner')
        obs = next((o for o in observations if o['task_id'] == tid), None)
        if not obs:
            issues.append('missing-observation')
        elif (obs.get('revision'), obs.get('decision_source_ref')) != (active.get('revision'), active.get('source_ref')):
            issues.append('revision-or-decision-mismatch')
        else:
            if not _time(obs['observed_at_utc']) <= clock < _time(obs['expires_at_utc']):
                issues.append('stale-or-future-observation')
            required, forbidden = obs.get('required_operations', []), obs.get('forbidden_operations', [])
            if not isinstance(required, list) or not isinstance(forbidden, list):
                raise ValueError('operation lists required')
            if any(not isinstance(x, str) or not x for x in required + forbidden):
                raise ValueError('canonical operation identifiers required')
            if set(required) & set(forbidden):
                issues.append('contradictory-operation-scope')
        if worker.get('owner') != 'assistant':
            issues.append('human-owned-or-unknown-owner')
        if c.get('execution_state') in ('paused', 'pause-requested'):
            issues.append('paused')
        if any(o.get('state') == 'uncertain' for o in record.get('outbox', [])):
            issues.append('uncertain-dispatch')
        readback = active.get('parent_readback') or {}
        if active.get('result_receipt_ref') and (
                readback.get('result_receipt_ref') != active['result_receipt_ref'] or
                readback.get('decision_source_ref') != active.get('source_ref')):
            issues.append('unconsumed-result')
        if record.get('status') != 'verified-done' and not active.get('next_action'):
            issues.append('missing-next-action')
        for item in operating_view(record, now=now)['retained_obligations']:
            if item['checkpoint_missing']:
                issues.append('missing-checkpoint:' + item['id'])
            elif item['overdue']:
                issues.append('overdue:' + item['id'])
        protection = None
        if obs and obs.get('critical_execution'):
            protection = keep_awake_assessment(obs.get('keep_awake'), now=now, owner=c.get('canonical_owner'))
            if protection['state'] != 'receipt-verified':
                issues.append('critical-keep-awake-unverified')
        rows.append({'task_id': tid, 'issues': issues, 'keep_awake': protection,
                     'approval_recorded': bool(record.get('approvals')),
                     'next_action': 'review-current-owner-evidence' if issues else 'retain-current-owner',
                     'dispatch_authorized': False})
    missing = sorted(set(expected) - set(ids))
    unexpected = sorted(set(ids) - set(expected))
    return {'coverage_complete': not missing and not unexpected,
            'missing_task_ids': missing, 'unexpected_task_ids': unexpected,
            'unmatched_observation_ids': sorted(set(obs_ids) - set(ids)),
            'assessment_only': True, 'tasks': rows}
