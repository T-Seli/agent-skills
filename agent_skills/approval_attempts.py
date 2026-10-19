"""Sanitized, append-only approval observations; evidence is never authorization.

Trusted callers supply structured outcomes and opaque references. No raw tool
output, user payload, credentials or reasoning is collected. There is no global
interception API: collection is explicit at supported caller boundaries.
"""
from copy import deepcopy
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re

FIELDS = {'schema_version', 'receipt_id', 'action_id', 'attempt_id', 'retry_of',
          'observed_at_utc', 'owner', 'target', 'operation', 'approval', 'reviewer',
          'delivery', 'admission', 'execution', 'verification', 'source_refs'}
STATES = {
    'delivery': {'unknown', 'not-attempted', 'delivered', 'failed', 'cancelled'},
    'admission': {'unknown', 'not-attempted', 'admitted', 'denied', 'cancelled'},
    'execution': {'unknown', 'not-started', 'running', 'succeeded', 'failed', 'cancelled'},
    'verification': {'unknown', 'pending', 'verified', 'failed'},
}
REASONS = {'none', 'unknown', 'missing-authorization', 'untrusted-relay', 'stale-scope',
           'new-security-gate', 'policy-denied', 'transport', 'cancelled', 'execution-error'}


def _ref(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or '\n' in value:
        raise ValueError('bounded single-line reference required')


def _clock(value):
    _ref(value)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('UTC observation required')
    return result


def validate(receipt):
    if not isinstance(receipt, dict) or set(receipt) != FIELDS or type(receipt['schema_version']) is not int or receipt['schema_version'] != 1:
        raise ValueError('exact version-1 approval receipt fields required')
    for key in ('receipt_id', 'action_id', 'attempt_id', 'owner', 'target'):
        _ref(receipt[key])
    if receipt['retry_of'] is not None:
        _ref(receipt['retry_of'])
    _clock(receipt['observed_at_utc'])
    op = receipt['operation']
    if not isinstance(op, dict) or set(op) != {'name', 'scope_ref', 'scope_sha256', 'revision'}:
        raise ValueError('exact scoped operation required')
    _ref(op['name']); _ref(op['scope_ref'])
    if not isinstance(op['scope_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', op['scope_sha256']):
        raise ValueError('scope hash required')
    if type(op['revision']) is not int or op['revision'] < 1:
        raise ValueError('positive revision required')
    approval = receipt['approval']
    if not isinstance(approval, dict) or set(approval) != {'source_ref', 'channel', 'provenance'}:
        raise ValueError('approval source/channel/provenance required')
    if approval['source_ref'] is not None:
        _ref(approval['source_ref'])
    _ref(approval['channel'])
    if approval['provenance'] not in {'direct-user', 'relayed-user', 'caller-reported', 'unknown'}:
        raise ValueError('invalid approval provenance')
    review = receipt['reviewer']
    if not isinstance(review, dict) or set(review) != {'result', 'reason_code', 'reason_ref'}:
        raise ValueError('structured reviewer result required')
    if review['result'] not in {'accepted', 'rejected', 'unknown', 'not-required'} or review['reason_code'] not in REASONS:
        raise ValueError('invalid reviewer state')
    if review['reason_ref'] is not None:
        _ref(review['reason_ref'])
    if review['result'] in {'accepted', 'rejected'} and not review['reason_ref']:
        raise ValueError('review result needs source evidence')
    for key, allowed in STATES.items():
        if receipt[key] not in allowed:
            raise ValueError('invalid ' + key)
    if review['result'] == 'rejected' and (receipt['delivery'] == 'delivered' or receipt['admission'] == 'admitted' or receipt['execution'] not in {'unknown', 'not-started'}):
        raise ValueError('rejected attempt cannot claim delivery/admission/execution')
    if receipt['verification'] == 'verified' and receipt['execution'] != 'succeeded':
        raise ValueError('verified execution needs successful execution evidence')
    refs = receipt['source_refs']
    if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
        raise ValueError('bounded evidence references required')
    for ref in refs:
        _ref(ref)
    return deepcopy(receipt)


def binding(receipt):
    return {k: receipt[k] for k in ('action_id', 'owner', 'target', 'operation')}


def collect(existing, receipt):
    """Idempotent receipt replay; retries remain distinct attempts, never extra success."""
    candidate = validate(receipt)
    history = [validate(x) for x in existing]
    for old in history:
        if old['receipt_id'] == candidate['receipt_id']:
            if old != candidate:
                raise ValueError('receipt identity collision')
            return deepcopy(history), 'duplicate'
        if old['action_id'] == candidate['action_id'] and binding(old) != binding(candidate):
            raise ValueError('changed scope/target requires a new action identity')
    same = [x for x in history if x['attempt_id'] == candidate['attempt_id']]
    if same:
        old = same[-1]
        if binding(old) != binding(candidate) or old['retry_of'] != candidate['retry_of'] or old['approval'] != candidate['approval']:
            raise ValueError('attempt binding changed')
        if _clock(candidate['observed_at_utc']) <= _clock(old['observed_at_utc']):
            raise ValueError('observation must advance')
        if old['reviewer']['result'] in {'accepted', 'rejected'} and candidate['reviewer'] != old['reviewer']:
            raise ValueError('new review needs a distinct attempt')
        if old['execution'] in {'succeeded', 'failed', 'cancelled'} and candidate['execution'] != old['execution']:
            raise ValueError('terminal execution cannot be overwritten')
    elif candidate['retry_of']:
        prior = [x for x in history if x['attempt_id'] == candidate['retry_of']]
        if not prior or binding(prior[-1]) != binding(candidate):
            raise ValueError('retry must reference the same scoped action')
        if _clock(candidate['observed_at_utc']) <= _clock(prior[-1]['observed_at_utc']):
            raise ValueError('retry must follow prior attempt')
    return history + [candidate], 'appended'


def classification(receipt):
    if receipt['reviewer']['reason_code'] == 'stale-scope':
        return 'stale-scope'
    if receipt['reviewer']['result'] == 'rejected':
        return 'new-security-gate' if receipt['reviewer']['reason_code'] == 'new-security-gate' else 'permission-rejected'
    if receipt['reviewer']['reason_code'] == 'transport':
        return 'transport-failure-permission-' + ('accepted' if receipt['reviewer']['result'] == 'accepted' else 'unknown')
    if receipt['delivery'] in {'failed', 'cancelled'} or receipt['admission'] == 'cancelled':
        return 'permission-accepted-delivery-unresolved' if receipt['reviewer']['result'] == 'accepted' else 'delivery-unresolved-permission-unknown'
    if receipt['execution'] == 'failed':
        return 'execution-failed'
    if receipt['verification'] == 'verified':
        return 'execution-verified'
    return 'outcome-unverified'


def summarize(receipts):
    history = []
    for receipt in receipts:
        history, _ = collect(history, receipt)
    latest = {r['attempt_id']: r for r in history}
    return {'receipt_count': len(history), 'attempt_count': len(latest),
            'action_count': len({r['action_id'] for r in history}),
            'linked_retry_count': sum(bool(r['retry_of']) for r in latest.values()),
            'collection_coverage': 'explicit caller receipts only',
            'attempts': [{'attempt_id': r['attempt_id'], 'action_id': r['action_id'],
                          'retry_of': r['retry_of'], 'classification': classification(r),
                          'reviewer_result': r['reviewer']['result'],
                          'reason_code': r['reviewer']['reason_code'],
                          'delivery': r['delivery'], 'admission': r['admission'],
                          'execution': r['execution'],
                          'verification': r['verification'], 'retry_authorized': False}
                         for r in latest.values()]}


def append_receipt(path, receipt):
    """Explicit task-local JSONL sink, locked/fsynced; no central publication."""
    validate(receipt)
    path = Path(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a+', encoding='utf-8') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        existing = []
        for line in stream:
            if line.strip():
                existing, _ = collect(existing, json.loads(line))
        _, state = collect(existing, receipt)
        if state == 'appended':
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(receipt, sort_keys=True, separators=(',', ':')) + '\n')
            stream.flush(); os.fsync(stream.fileno())
    return {'state': state, 'receipt_id': receipt['receipt_id'], 'dispatch_authorized': False}


def execution_observation(template, result, *, receipt_id, source_ref):
    """Map existing workers.RunResult metadata only; never inspect stdout/stderr.

    Caller persists this observation after its existing runner returns. Timeout
    remains unknown even if a local child exit is available; remote effects may
    still require readback. Process exit zero is not functional verification.
    """
    receipt = validate(template)
    _ref(receipt_id); _ref(source_ref)
    if result.state not in {'done', 'failed', 'uncertain', 'unavailable'}:
        raise ValueError('unsupported runner state')
    if result.state == 'done' and result.returncode != 0:
        raise ValueError('done requires exit zero')
    if result.state == 'failed' and (type(result.returncode) is not int or result.returncode == 0):
        raise ValueError('failed requires nonzero exit')
    receipt.update(receipt_id=receipt_id, observed_at_utc=result.finished_at_utc,
        execution={'done': 'succeeded', 'failed': 'failed', 'uncertain': 'unknown',
                   'unavailable': 'not-started'}[result.state], verification='pending')
    receipt['source_refs'] = list(dict.fromkeys(receipt['source_refs'] + [source_ref]))
    return validate(receipt)
