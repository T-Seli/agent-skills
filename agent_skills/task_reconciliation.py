"""Bounded, caller-supplied evidence assessment. Never dispatches or grants authority."""
from calendar import monthrange
from datetime import datetime, timedelta, timezone
import re
from .task_checkpoint import operating_view, _time
from .keep_awake import assess as assess_keep_awake

# A time without `Z` is rejected rather than read as end of day.
_WHEN = r'(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})Z|(?![T ]?\d))'
_DEADLINES = (re.compile(r'\bdeadline:\s*' + _WHEN, re.I),
              re.compile(r'\b(?:until|deadline)\s+' + _WHEN, re.I))
_PINNED = re.compile(r'\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*')


def keep_awake_assessment(receipt, *, now, owner, task_id=None):
    """Check a structured assertion receipt; no process control or sleep attribution."""
    if not receipt:
        return {'state': 'unverified', 'reason': 'missing-receipt'}
    if receipt.get('kind') == 'owned-keep-awake':
        return assess_keep_awake(receipt, now=now, owner=owner, task_id=task_id)
    required = ('owner', 'pid', 'process_identity_ref', 'assertion_ref',
                'observed_at_utc', 'expires_at_utc', 'cleanup_ref')
    if any(not receipt.get(k) for k in required):
        return {'state': 'unverified', 'reason': 'incomplete-receipt'}
    if type(receipt['pid']) is not int or receipt['pid'] <= 0:
        raise ValueError('positive PID required')
    age = (_time(now) - _time(receipt['observed_at_utc'])).total_seconds()
    if not 0 <= age <= 120 or _time(now) >= _time(receipt['expires_at_utc']):
        return {'state': 'unverified', 'reason': 'stale-or-future-receipt'}
    return {'state': 'receipt-only', 'owner': receipt['owner'],
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
            protection = keep_awake_assessment(obs.get('keep_awake'), now=now, owner=c.get('canonical_owner'), task_id=tid)
            if protection['state'] != 'verified-now':
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


def _deadline(description):
    """Structured `Deadline:` first, then legacy `until`/`deadline`; a bare date ends at 23:59Z."""
    for pattern in _DEADLINES:
        m = pattern.search(description)
        if m:
            return _time(f"{m[1]}T{m[2] or '23:59'}Z")
    return None


def _pinned(field):
    """Values of a cron field made only of numbers, lists and ranges; None for `*` or steps."""
    if not _PINNED.fullmatch(field):
        return None
    values = set()
    for part in field.split(','):
        low, _, high = part.partition('-')
        values.update(range(int(low), int(high or low) + 1))
    return values


def _cron_deadline(cron, year):
    """End of the last calendar day a cron pins by day and month (weekday `*`), else None."""
    _, _, day, month, weekday = cron.split()
    days, months = _pinned(day), _pinned(month)
    if days is None or months is None or weekday != '*':
        return None
    last = max(datetime(year, m, d, 12, tzinfo=timezone.utc)
               for m in months for d in days if d <= monthrange(year, m)[1])
    # Cron fires in the machine's local zone; 12:00Z next day is past that day's end in every US zone.
    return last + timedelta(days=1)


def expired_monitors(tasks, *, now):
    """Enabled recurring schedules past the deadline in their description (else the last day
    their cron pins), and those with neither."""
    expired, unparsed = [], []
    for task in tasks:
        if not task['enabled'] or task.get('fireAt'):
            continue
        cron = task.get('cronExpression')  # ad-hoc tasks have no cron
        deadline = _deadline(task['description']) or (_cron_deadline(cron, now.year) if cron else None)
        if deadline is None:
            unparsed.append(task['taskId'])
        elif deadline < now:
            expired.append({'taskId': task['taskId'], 'deadline': deadline.strftime('%Y-%m-%dT%H:%MZ')})
    return sorted(expired, key=lambda e: e['taskId']), sorted(unparsed)
