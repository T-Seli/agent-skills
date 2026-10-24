"""Task-local evidence and status projections; no dispatch, probes or scheduling.

Receipts are caller-supplied evidence, not authenticated authority. Native hosts
must explicitly invoke these interfaces; none of this enforces platform behavior.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import subprocess

from .approval_handoff import BLOCKER_KINDS
from .code_state import code_state
from .system_audit import monitoring_verdict


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("nonempty bounded text required")
    return value.strip()


def _time(value):
    if not isinstance(value, str):
        raise ValueError("UTC timestamp required")
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamp required")
    return parsed


def _active(record):
    active = (record.get('coordination') or {}).get('active_deliverable')
    if not active:
        raise ValueError("current task contract required")
    return active


def record_checkpoint(record, *, critical, rank, blocker, next_action,
                      next_check_at_utc, observed_at_utc, receipt_ref):
    """Retain an owned checkpoint inside the existing deliverable, not a new queue."""
    if type(critical) is not bool or type(rank) is not int or rank < 1:
        raise ValueError("explicit priority required")
    if _time(next_check_at_utc) < _time(observed_at_utc):
        raise ValueError("next checkpoint precedes observation")
    if blocker is not None and (not isinstance(blocker, dict) or set(blocker) != {
            'kind', 'source_ref', 'action'} or blocker['kind'] not in BLOCKER_KINDS):
        raise ValueError("scoped blocker required")
    if blocker is not None:
        blocker = {key: _text(value) for key, value in blocker.items()}
    r = deepcopy(record)
    active = _active(r)
    checkpoint = dict(critical=critical, rank=rank, blocker=blocker,
                      next_action=_text(next_action), next_check_at_utc=next_check_at_utc,
                      observed_at_utc=observed_at_utc, receipt_ref=_text(receipt_ref))
    old = active.get('checkpoint')
    if old == checkpoint:
        return r
    if old and _time(observed_at_utc) <= _time(old['observed_at_utc']):
        raise ValueError("checkpoint must advance; exact replay only")
    if old:
        active.setdefault('checkpoint_history', []).append(old)
    active['checkpoint'] = checkpoint
    return r


def record_claim(record, *, claim_id, state, statement, evidence_level,
                 source_ref, observed_at_utc, supersedes=None):
    """Append an explicit correction; never infer truth from narrative similarity."""
    if state not in ('unknown', 'supported', 'refuted') or evidence_level not in (
            'reported', 'performed', 'independently_verified', 'unverified'):
        raise ValueError("invalid claim state/evidence level")
    if state == 'supported' and evidence_level == 'unverified':
        raise ValueError("supported claim needs labeled evidence")
    _time(observed_at_utc)
    r = deepcopy(record)
    _active(r)
    history = r['coordination'].setdefault('claim_history', [])
    value = dict(claim_id=_text(claim_id), state=state, statement=_text(statement),
                 evidence_level=evidence_level, source_ref=_text(source_ref),
                 observed_at_utc=observed_at_utc, supersedes=supersedes)
    replay = next((x for x in history if x['source_ref'] == value['source_ref']), None)
    if replay:
        if replay != value:
            raise ValueError("claim receipt already names different content")
        return r
    previous = next((x for x in reversed(history) if x['claim_id'] == value['claim_id']), None)
    if previous:
        if supersedes != previous['source_ref'] or _time(observed_at_utc) <= _time(previous['observed_at_utc']):
            raise ValueError("correction must name and advance the current claim")
    elif supersedes is not None:
        raise ValueError("no current claim to supersede")
    history.append(value)
    return r


def current_claims(record):
    values = {}
    for item in (record.get('coordination') or {}).get('claim_history', []):
        values[item['claim_id']] = deepcopy(item)
    return list(values.values())


def current_material_facts(record, facts):
    """Suppress precisely referenced displaced facts; preserve the historical record."""
    history = (record.get('coordination') or {}).get('claim_history', [])
    displaced = {item['supersedes'] for item in history if item.get('supersedes')}
    return [deepcopy(item) for item in facts if item.get('source_ref') not in displaced]


def record_watch_checkpoint(record, *, watch_id, baseline_digest, next_check_at_utc,
                            expires_at_utc, observed_at_utc, receipt_ref):
    """Record the existing watch's due time. This creates no observer or schedule."""
    watch_id = _text(watch_id)
    _active(record)
    if not _time(observed_at_utc) <= _time(next_check_at_utc) <= _time(expires_at_utc):
        raise ValueError("invalid watch checkpoint window")
    r = deepcopy(record)
    baseline = r['coordination'].get('watch_baselines', {}).get(watch_id)
    if not baseline or baseline['digest'] != baseline_digest:
        raise ValueError("watch baseline mismatch")
    if _time(observed_at_utc) < _time(baseline['observed_at']):
        raise ValueError("watch checkpoint precedes baseline")
    value = dict(baseline_digest=baseline_digest, next_check_at_utc=next_check_at_utc,
                 expires_at_utc=expires_at_utc, observed_at_utc=observed_at_utc,
                 receipt_ref=_text(receipt_ref), owner=_active(r)['owner'])
    old = baseline.get('checkpoint')
    if old and old['owner'] != value['owner']:
        raise ValueError("watch execution owner must be reconciled before changing checkpoint")
    if old == value:
        return r
    prior_checkpoints = baseline.get('checkpoint_history', []) + ([old] if old else [])
    for prior in r['coordination'].get('watch_history', []):
        if prior['id'] == watch_id:
            prior_checkpoints += prior.get('checkpoint_history', []) + ([prior['checkpoint']] if prior.get('checkpoint') else [])
    if any(x['receipt_ref'] == value['receipt_ref'] for x in prior_checkpoints):
        raise ValueError("checkpoint receipt cannot name a different interval")
    if old and _time(observed_at_utc) <= _time(old['observed_at_utc']):
        raise ValueError("watch checkpoint must advance")
    if old:
        baseline.setdefault('checkpoint_history', []).append(deepcopy(old))
    if baseline.get('check'):
        baseline.setdefault('check_history', []).append(deepcopy(baseline['check']))
    baseline['checkpoint'] = value
    baseline.pop('check', None)  # a rescheduled obligation needs a new wake/result
    return r


def record_watch_result(record, *, watch_id, baseline_digest, observed_at_utc,
                        wake_receipt, readback_receipt, traffic_count, functional_results):
    watch_id = _text(watch_id)
    r = deepcopy(record)
    baseline = r['coordination'].get('watch_baselines', {}).get(watch_id)
    checkpoint = (baseline or {}).get('checkpoint')
    if not checkpoint or baseline['digest'] != baseline_digest:
        raise ValueError("watch baseline/checkpoint mismatch")
    if _time(observed_at_utc) < _time(checkpoint['observed_at_utc']):
        raise ValueError("watch result precedes checkpoint")
    check = dict(observed_at_utc=observed_at_utc, wake_receipt=wake_receipt,
                 readback_receipt=readback_receipt, traffic_count=traffic_count,
                 functional_results=deepcopy(functional_results))
    normalized = monitoring_verdict(**check, expires_at_utc=checkpoint['expires_at_utc'])
    wake_receipt, readback_receipt = normalized['wake_receipt'], normalized['readback_receipt']
    check.update(wake_receipt=wake_receipt, readback_receipt=readback_receipt)
    old = baseline.get('check')
    if old == check:
        return r
    past = baseline.get('check_history', []) + ([old] if old else [])
    for prior in r['coordination'].get('watch_history', []):
        if prior['id'] == watch_id:
            past += prior.get('check_history', []) + ([prior['check']] if prior.get('check') else [])
    if any((wake_receipt and x.get('wake_receipt') == wake_receipt) or
           (readback_receipt and x.get('readback_receipt') == readback_receipt) for x in past):
        raise ValueError("watch receipt already belongs to an earlier check")
    if old and _time(observed_at_utc) <= _time(old['observed_at_utc']):
        raise ValueError("watch result must advance; exact replay only")
    if old:
        baseline.setdefault('check_history', []).append(deepcopy(old))
    baseline['check'] = check
    return r


CONTEXT_FIELDS = {'host_ref', 'executor_ref', 'shell_ref', 'executable_ref',
                  'version', 'user_ref', 'home_ref', 'config_ref', 'cwd_ref', 'mode'}


def validate_baseline_advance(old, value, history=()):
    """A monitored baseline cannot regress; legacy unmonitored formats remain readable."""
    if any(x.get('source_ref') == value['source_ref'] for x in history):
        raise ValueError("superseded baseline source cannot become current")
    monitored = old and (old.get('checkpoint') or any(x.get('checkpoint') for x in history))
    if monitored and _time(value['observed_at']) <= _time(old['observed_at']):
        raise ValueError("monitored baseline must advance; exact replay only")


def record_execution_context(record, *, context, observations, observed_at_utc, receipt_ref):
    """Keep probe observations scoped to one explicit context; never probe credentials."""
    if not isinstance(context, dict) or set(context) != CONTEXT_FIELDS:
        raise ValueError("exact sanitized execution context required")
    context = {key: _text(value) for key, value in context.items()}
    if not isinstance(observations, dict) or not observations:
        raise ValueError("context observations required")
    for key, value in observations.items():
        if key not in ('host', 'shell', 'network', 'authentication', 'permission') or not isinstance(value, dict) or set(value) != {'state', 'source_ref'}:
            raise ValueError("invalid context observation")
        if value['state'] not in ('verified', 'blocked', 'unknown'):
            raise ValueError("invalid context observation state")
        _text(value['source_ref'])
    _time(observed_at_utc)
    r = deepcopy(record)
    _active(r)
    c = r['coordination']
    value = dict(context=context, observations=deepcopy(observations),
                 observed_at_utc=observed_at_utc, receipt_ref=_text(receipt_ref),
                 context_digest=hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest())
    old = c.get('execution_context')
    if old == value:
        return r
    if old and _time(observed_at_utc) <= _time(old['observed_at_utc']):
        raise ValueError("context observation must advance")
    if old:
        c.setdefault('execution_context_history', []).append(old)
    c['execution_context'] = value
    return r


def capture_provenance(record, *, repo, base, test_receipt_ref, tested_digest,
                       untracked=(), excluded=()):
    """Use the existing code-state manifest; a receipt describes tests, never reruns them."""
    manifest = code_state(repo, untracked=untracked, excluded=excluded)
    if manifest['digest'] != tested_digest:
        raise ValueError("tests do not name the current code-state digest")
    resolved = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '--verify',
                                        base + '^{commit}'], text=True).strip()
    if base != resolved:
        raise ValueError("full base commit required")
    branch_result = subprocess.run(['git', '-C', str(repo), 'symbolic-ref', '--short',
                                   '-q', 'HEAD'], text=True, capture_output=True, check=False)
    if branch_result.returncode not in (0, 1):
        raise ValueError("unable to resolve checkout branch")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    r = deepcopy(record)
    _active(r)['provenance'] = {'base': base, 'branch': branch, 'manifest': manifest,
                               'test_receipt_ref': _text(test_receipt_ref)}
    return r


def operating_view(record, *, now=None):
    """Read-only projection for both local CLI status and the existing communication brief."""
    now = now or datetime.now(timezone.utc).isoformat()
    clock = _time(now)
    c = record.get('coordination') or {}
    active = c.get('active_deliverable')
    retained = []
    for item in ([active] if active else []) + c.get('obligations', []):
        checkpoint = item.get('checkpoint')
        completed = item is active and record.get('status') == 'verified-done'
        if item.get('state') == 'superseded' or completed:
            continue
        retained.append({'id': item['id'], 'revision': item['revision'], 'owner': item.get('owner'),
                         'state': item.get('state', 'active'),
                         'critical': False, 'rank': None,
                         'next_action': item.get('next_action'),
                         **deepcopy(checkpoint or {}),
                         'checkpoint_missing': not bool(checkpoint),
                         'decision_source_ref': item['source_ref'],
                         'overdue': bool(checkpoint) and clock > _time(checkpoint['next_check_at_utc'])})
    watches = []
    for watch_id, baseline in c.get('watch_baselines', {}).items():
        cp = baseline.get('checkpoint')
        if not cp:
            watches.append({'id': watch_id, 'watch_state': 'not-armed', 'reason': 'missing-checkpoint',
                            'functional_acceptance': 'unverified'})
            continue
        check = baseline.get('check') or {}
        missed = clock > _time(cp['next_check_at_utc'])
        future = _time(cp['observed_at_utc']) > clock or (check and _time(check['observed_at_utc']) > clock)
        verdict = monitoring_verdict(wake_receipt=None if missed or future else check.get('wake_receipt'),
            readback_receipt=None if missed or future else check.get('readback_receipt'),
            expires_at_utc=cp['expires_at_utc'], observed_at_utc=now,
            traffic_count=check.get('traffic_count', 0), functional_results=check.get('functional_results', []))
        completed_checks = [x for x in baseline.get('check_history', []) + ([check] if check else [])
                            if x.get('wake_receipt') and x.get('readback_receipt')
                            and _time(x['observed_at_utc']) <= clock]
        watches.append({'id': watch_id, **verdict, 'missed_check': missed,
                        'owner': cp['owner'],
                        'next_check_at_utc': cp['next_check_at_utc'],
                        'last_completed_check': deepcopy(completed_checks[-1]) if completed_checks else None,
                        'last_result': deepcopy(check) or None})
    return {'task_id': record['task_id'], 'native_enforcement': False,
            'current_owner': c.get('canonical_owner'),
            'navigation': {'task_id': record['task_id'], 'execution_owner': c.get('canonical_owner'),
                           'session_id': (record.get('worker') or {}).get('session_id'),
                           'writer': (record.get('worker') or {}).get('owner'),
                           'handoff': deepcopy((record.get('worker') or {}).get('handoff')),
                           'worktree': record.get('worktree'), 'source_thread': record.get('source_thread')},
            'retained_obligations': sorted(retained, key=lambda x: (not x['critical'], x['rank'] if x['rank'] is not None else float('inf'), x['id'])),
            'recorded_approvals': deepcopy(record.get('approvals', [])),
            'current_claims': current_claims(record), 'monitors': watches,
            'execution_context': deepcopy(c.get('execution_context')),
            'provenance': deepcopy((active or {}).get('provenance'))}


def _checkpoint_intent_candidates(record, *, now, escalation_after_seconds):
    """Derive obligations only; absence/age says nothing about worker progress."""
    if type(escalation_after_seconds) is not int or not 1 <= escalation_after_seconds <= 86400:
        raise ValueError("checkpoint escalation interval must be 1..86400 seconds")
    clock = _time(now)
    c = record.get('coordination') or {}
    active = c.get('active_deliverable')
    items = {(x['id'], x['revision']): x for x in
             ([active] if active else []) + c.get('obligations', [])}
    for row in operating_view(record, now=now)['retained_obligations']:
        item = items[(row['id'], row['revision'])]
        cp = item.get('checkpoint')
        if cp and clock < _time(cp['next_check_at_utc']):
            continue
        kinds = ['checkpoint-due'] if cp else ['checkpoint-missing']
        if cp and (clock - _time(cp['next_check_at_utc'])).total_seconds() >= escalation_after_seconds:
            kinds.append('checkpoint-escalation')
        binding = {'task_id': record['task_id'], 'deliverable_id': item['id'],
                   'revision': item['revision'], 'contract_digest': item['contract_digest'],
                   'owner': item['owner'], 'decision_source_ref': item['source_ref'],
                   'checkpoint_ref': cp['receipt_ref'] if cp else None,
                   'due_at_utc': cp['next_check_at_utc'] if cp else None}
        for kind in kinds:
            value = {**binding, 'kind': kind}
            if kind == 'checkpoint-escalation':
                value['escalation_after_seconds'] = escalation_after_seconds
            key = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            yield {'id': key, **value, 'progress': 'unknown', 'next_action': row['next_action']}


def stage_checkpoint_intents(record, *, now, escalation_after_seconds=600):
    """Return state plus due intents for one atomic caller save; never send or schedule.

    The caller persists this entire record in the existing task store. A host may
    then consume pending intents with begin/settle and its separately authorized
    transport. Replays and restarts retain one intent per exact obligation.
    """
    candidates = list(_checkpoint_intent_candidates(record, now=now,
        escalation_after_seconds=escalation_after_seconds))
    r = deepcopy(record)
    if not (r.get('coordination') or {}).get('active_deliverable'):
        return r  # legacy/unbound records remain readable; do not invent a contract
    queue = r['coordination'].setdefault('checkpoint_intents', [])
    known = {x['id'] for x in queue}
    current_ids = {x['id'] for x in candidates}
    for intent in queue:
        intent['current'] = intent['id'] in current_ids
        if not intent['current'] and intent['state'] == 'pending':
            intent['state'] = 'superseded'
            intent['superseded_at_utc'] = now
        # Preserve uncertain delivery for supported readback, even if the
        # obligation changed. Stale pending work is never a notification queue.
    for value in candidates:
        if value['id'] not in known:
            queue.append({**value, 'state': 'pending', 'current':True,
                          'created_at_utc': now, 'attempts': []})
            known.add(value['id'])
    return r


def _intent(record, intent_id):
    intent_id = _text(intent_id)
    matches = [x for x in (record.get('coordination') or {}).get('checkpoint_intents', [])
               if x['id'] == intent_id]
    if len(matches) != 1:
        raise ValueError("one existing checkpoint intent required")
    return matches[0]


def begin_checkpoint_intent(record, *, intent_id, observed_at_utc, attempt_ref):
    """Return uncertain-before-send state. Persist it before any transport call.

    This pure transition cannot prove a caller saved the record or authenticate
    transport permission. The existing store/host driver owns both obligations.
    """
    r = deepcopy(record)
    intent = _intent(r, intent_id)
    if intent['state'] != 'pending':
        raise ValueError("checkpoint intent is not pending; reconcile uncertain delivery")
    clock = _time(observed_at_utc)
    last = intent.get('readback') or intent
    if clock < _time(last.get('observed_at_utc', intent['created_at_utc'])):
        raise ValueError("intent attempt precedes current evidence")
    current = {x['id'] for x in _checkpoint_intent_candidates(r, now=observed_at_utc,
        escalation_after_seconds=intent.get('escalation_after_seconds', 600))}
    if intent_id not in current:
        raise ValueError("checkpoint intent no longer matches a current obligation")
    attempt_ref = _text(attempt_ref)
    for previous in r['coordination']['checkpoint_intents']:
        if any(x['attempt_ref'] == attempt_ref for x in previous['attempts']):
            raise ValueError("attempt reference already consumed")
    intent['attempts'].append({'attempt_ref': attempt_ref, 'observed_at_utc': observed_at_utc})
    intent['state'] = 'uncertain'
    return r


def settle_checkpoint_intent(record, *, intent_id, outcome, observed_at_utc, receipt_ref):
    """Record a transport result; timeout/unknown remains uncertain, never retryable."""
    if outcome not in ('delivered', 'uncertain'):
        raise ValueError("delivered or uncertain transport outcome required")
    r = deepcopy(record)
    intent = _intent(r, intent_id)
    value = {'outcome': outcome, 'observed_at_utc': observed_at_utc,
             'receipt_ref': _text(receipt_ref)}
    if not intent['attempts']:
        raise ValueError("persisted intent attempt required before settlement")
    attempt = intent['attempts'][-1]
    if attempt.get('result') == value:
        return r
    if intent['state'] != 'uncertain' or 'result' in attempt:
        raise ValueError("transport result already settled; use readback reconciliation")
    if _time(observed_at_utc) < _time(attempt['observed_at_utc']):
        raise ValueError("transport result precedes attempt")
    for other in r['coordination']['checkpoint_intents']:
        if any(x.get('result', {}).get('receipt_ref') == value['receipt_ref'] for x in other['attempts']):
            raise ValueError("transport receipt already consumed")
    attempt['result'] = value
    intent['state'] = outcome
    return r


def reconcile_checkpoint_intent(record, *, intent_id, delivered, observed_at_utc, readback_ref):
    """Record supported delivery readback; only confirmed absence permits a new attempt.

    Readback references are caller-supplied evidence, not self-authenticating proof.
    The authorized host must read its destination before supplying this transition.
    """
    if type(delivered) is not bool:
        raise ValueError("explicit delivery readback required")
    r = deepcopy(record)
    intent = _intent(r, intent_id)
    value = {'delivered': delivered, 'observed_at_utc': observed_at_utc,
             'readback_ref': _text(readback_ref)}
    if intent.get('readback') == value:
        return r
    if intent['state'] != 'uncertain' or not intent['attempts']:
        raise ValueError("only an uncertain attempted delivery can be reconciled")
    attempt = intent['attempts'][-1]
    latest = attempt.get('result', attempt)['observed_at_utc']
    if _time(observed_at_utc) < _time(latest):
        raise ValueError("delivery readback precedes attempt/result")
    for other in r['coordination']['checkpoint_intents']:
        if any(x.get('readback', {}).get('readback_ref') == value['readback_ref'] for x in other['attempts']):
            raise ValueError("delivery readback already consumed")
    attempt['readback'] = value
    intent['readback'] = value
    intent['state'] = 'delivered' if delivered else 'pending'
    return r
