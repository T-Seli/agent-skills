"""Assess supplied source-observation metadata; never samples or refreshes a source."""
from copy import deepcopy
from datetime import datetime


def utc(value):
    if not isinstance(value, str):
        raise ValueError('timezone-aware timestamp required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')
    return result


def assess_coverage(packet, *, observed_at_utc):
    """Caller assertions need adapter evidence; complete metadata is not authentication."""
    now = utc(observed_at_utc)
    if packet is None:
        return {'state': 'unknown', 'reason': 'source observation not supplied', 'evidence': None}
    fields = {'requested', 'observed', 'source_observed_at_utc', 'source_identity',
              'runtime_identity', 'state', 'cap_seconds', 'truncated',
              'max_source_age_seconds', 'receipt_ref'}
    if not isinstance(packet, dict) or set(packet) != fields:
        raise ValueError('exact source observation fields required')
    if packet['state'] not in ('verified', 'failed', 'blocked', 'unknown'):
        raise ValueError('invalid observation state')
    if type(packet['truncated']) is not bool:
        raise ValueError('explicit truncation state required')
    for key in ('cap_seconds', 'max_source_age_seconds'):
        if packet[key] is None and key == 'cap_seconds':
            continue
        if type(packet[key]) is not int or packet[key] < 1:
            raise ValueError('positive cap/age bounds required')
    if not isinstance(packet['receipt_ref'], str) or not packet['receipt_ref'].strip():
        raise ValueError('source observation receipt required')
    def interval(value):
        if not isinstance(value, dict) or set(value) != {'start', 'end'}:
            raise ValueError('explicit observation interval required')
        start, end = utc(value['start']), utc(value['end'])
        if start >= end:
            raise ValueError('observation interval must advance')
        return start, end
    wanted_start, wanted_end = interval(packet['requested'])
    result = {'state': packet['state'], 'reason': 'source state', 'evidence': deepcopy(packet)}
    if packet['state'] != 'verified':
        return result
    if (any(not isinstance(packet[k], str) or not packet[k].strip()
            for k in ('source_identity', 'runtime_identity', 'source_observed_at_utc')) or
            packet['observed'] is None):
        return {**result, 'state': 'unknown', 'reason': 'source identity or observation missing'}
    start, end = interval(packet['observed'])
    source_at = utc(packet['source_observed_at_utc'])
    if end > source_at or source_at > now or wanted_end > now:
        return {**result, 'state': 'unknown', 'reason': 'observation clock not established'}
    if (now - source_at).total_seconds() > packet['max_source_age_seconds']:
        return {**result, 'state': 'unknown', 'reason': 'source observation stale'}
    if packet['cap_seconds'] is not None and (end - start).total_seconds() > packet['cap_seconds']:
        raise ValueError('observed interval exceeds declared capture cap')
    if packet['truncated'] or start > wanted_start or end < wanted_end:
        return {**result, 'state': 'partial', 'reason': 'requested interval not fully observed'}
    return {**result, 'state': 'complete', 'reason': 'requested interval covered by supplied evidence'}
