#!/usr/bin/env python3
"""Rebuildable evidence retrieval over explicitly selected existing task journals.

No second store, embedding call, promotion, authorization or journal write. Claims
are joined by exact recorded scope and evidence identity, never prose similarity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import history

VERSION = 1
# source_ref cites the event's provenance; it is not a configuration version.
CONTEXT_FIELDS = ('source_version', 'runtime_version', 'head_sha')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('explicit bounded ' + label + ' required')
    return value


def _identity(fact):
    return tuple(fact.get(key) for key in ('repo_ref', 'environment', 'scope', 'evidence_ref'))


def rebuild(repo, task_ids):
    """Replay selected journals through their existing validated snapshot reader.

    snapshot uses the journal's existing shared-lock protocol. This does not
    append events or write a projection. Missing/corrupt journals remain gaps.
    """
    if (not isinstance(task_ids, list) or not 1 <= len(task_ids) <= 100 or
            any(not isinstance(task, str) or not history.ID.fullmatch(task) for task in task_ids) or
            len(set(task_ids)) != len(task_ids)):
        raise ValueError('one to one hundred distinct task IDs required')
    facts, snapshots, gaps, contexts = [], [], [], []
    count = 0
    for task_id in sorted(task_ids):
        try:
            rows, digest = history.snapshot(repo, task_id)
        except (ValueError, OSError, UnicodeDecodeError):
            gaps.append({'task_id': task_id, 'state': 'unavailable', 'source_ref': 'journal:' + task_id})
            continue
        if not rows:
            gaps.append({'task_id': task_id, 'state': 'missing', 'source_ref': 'journal:' + task_id})
            continue
        count += len(rows)
        if count > 10000:
            raise ValueError('journal event budget exceeded; select fewer tasks')
        snapshots.append({'task_id': task_id, 'revision': len(rows), 'digest': digest,
                          'record_owner': history.owner(rows)})
        by_event = {}
        for row in rows:
            citation = {'task_id': task_id, 'event_id': row['event_id'], 'revision': row['revision'],
                        'journal_digest': digest, 'record_owner': row['record_owner'],
                        'event_kind': row['kind'], 'at_utc': row['at_utc'],
                        'observed_at_utc': row['observed_at_utc'],
                        **{key: row.get(key) for key in ('repo_ref', 'environment', 'scope',
                            'source_ref', 'source_version', 'runtime_version', 'head_sha')}}
            contexts.append({**citation, 'summary': row['summary'],
                'approval_ref': row.get('approval_ref'), 'authority': False,
                'proposal_only': row['kind'] == 'proposal'})
            created = []
            for index, evidence in enumerate(row.get('evidence', [])):
                fact = {**citation, 'evidence_ref': evidence['ref'], 'claim': evidence['claim'],
                    'evidence_level': evidence['state'], 'outcome': evidence.get('outcome'),
                    'evidence_sha': evidence.get('sha'),
                    'evidence_environment': evidence.get('environment'),
                    'verified_by': evidence.get('verified_by'),
                    'verified_revision': row.get('verified_revision'),
                    'uncertainty': row.get('uncertainty'), 'authority': False,
                    'correction_of': row.get('correction_of'), 'superseded_by': []}
                fact['id'] = _digest([task_id, row['event_id'], index, digest])
                fact['binding'] = 'exact-scope' if all(_identity(fact)) else 'legacy-unbound'
                # Correction links are event-local. Only an exact fact identity
                # in the same journal/scope is displaced; no similarity merge.
                if row.get('correction_of'):
                    targets = by_event.get(row['correction_of'], [])
                    matching = [prior for prior in targets if _identity(prior) == _identity(fact)
                                and all(_identity(fact))]
                    for prior in matching:
                        prior['superseded_by'].append(fact['id'])
                    fact['correction_unresolved'] = not bool(matching)
                created.append(fact)
                facts.append(fact)
            by_event[row['event_id']] = created
    value = {'schema_version': VERSION, 'projection_source_sha256':
             hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'journals': snapshots, 'gaps': gaps, 'facts': facts, 'context_records': contexts,
             'authority': False}
    return {**value, 'projection_digest': _digest(value)}


def _validity(fact, current_context):
    if fact['superseded_by']:
        return 'superseded', ['explicit same-scope correction']
    if not all(_identity(fact)):
        return 'unknown', ['legacy or missing exact evidence scope']
    stale, unknown = [], []
    for field in CONTEXT_FIELDS:
        recorded, expected = fact.get(field), current_context.get(field)
        if recorded is None and expected is None:
            continue  # no invented relevance for an unrecorded dimension
        if recorded is None or expected is None:
            unknown.append(field + ' currentness unavailable')
        elif recorded != expected:
            stale.append(field + ' changed')
    if fact.get('evidence_sha') and current_context.get('head_sha') != fact['evidence_sha']:
        (stale if current_context.get('head_sha') else unknown).append('evidence code binding')
    if fact.get('evidence_environment') and fact['evidence_environment'] != fact['environment']:
        unknown.append('evidence environment differs from event scope')
    if stale:
        return 'stale', stale + unknown
    if not current_context:
        unknown.append('no independently supplied current context')
    if fact['evidence_level'] == 'reported':
        unknown.append('reported claim remains unverified')
    if fact.get('uncertainty') or fact.get('correction_unresolved'):
        unknown.append('recorded uncertainty or unresolved correction')
    if fact['event_kind'] == 'proposal':
        unknown.append('proposal is not an accepted result or policy')
    return ('unknown', unknown) if unknown else ('current', [])


def retrieve(repo, task_ids, *, repo_ref, environment, scope, current_context=None,
             evidence_ref=None, limit=20, cursor=None):
    """Return bounded exact-scope evidence and cursor from a freshly rebuilt projection.

    current_context is independently supplied source/runtime/code identity,
    using only dimensions actually recorded by events. source_ref remains a
    citation, never a configuration pin or a separate conflict group.
    'current' means context-matching recorded evidence, never action authority.
    """
    for key, value in (('repository', repo_ref), ('environment', environment), ('scope', scope)):
        _text(value, key)
    if evidence_ref is not None:
        _text(evidence_ref, 'evidence identity')
    current_context = {} if current_context is None else current_context
    if not isinstance(current_context, dict) or set(current_context) - set(CONTEXT_FIELDS):
        raise ValueError('explicit supported current-context dimensions required')
    for key, value in current_context.items():
        _text(value, key)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('result limit must be one to one hundred')
    projection = rebuild(repo, task_ids)
    query = dict(repo_ref=repo_ref, environment=environment, scope=scope,
                 current_context=current_context, evidence_ref=evidence_ref)
    query_digest = _digest(query)
    offset = 0
    if cursor is not None:
        if (not isinstance(cursor, dict) or set(cursor) != {'projection_digest', 'query_digest', 'offset'} or
                cursor['projection_digest'] != projection['projection_digest'] or
                cursor['query_digest'] != query_digest or type(cursor['offset']) is not int or cursor['offset'] < 0):
            raise ValueError('stale or foreign knowledge cursor; rebuild query')
        offset = cursor['offset']
    selected = [fact for fact in projection['facts'] if fact['repo_ref'] == repo_ref and
                fact['environment'] == environment and fact['scope'] == scope and
                (evidence_ref is None or fact['evidence_ref'] == evidence_ref)]
    groups = {}
    for fact in selected:
        state, reasons = _validity(fact, current_context)
        fact.update(state=state, validity_reasons=reasons)
        if state != 'superseded':
            context_identity = _identity(fact) + tuple(fact.get(key) for key in CONTEXT_FIELDS)
            groups.setdefault(context_identity, []).append(fact)
    for group in groups.values():
        # Different unlinked content is unresolved even when wording might be
        # equivalent. Deterministic retrieval cannot decide semantic agreement.
        if len({(fact['claim'], fact['outcome']) for fact in group}) > 1:
            for fact in group:
                fact['validity_reasons'].append('unlinked claims differ on the same exact evidence identity')
                fact['state'] = 'conflict'
    if offset > len(selected):
        raise ValueError('knowledge cursor offset beyond results')
    page = selected[offset:offset + limit]
    next_offset = offset + len(page)
    cursor = ({'projection_digest': projection['projection_digest'], 'query_digest': query_digest,
               'offset': next_offset} if next_offset < len(selected) else None)
    states = {fact['state'] for fact in selected if fact['state'] != 'superseded'}
    state = ('conflict' if 'conflict' in states else 'unknown' if projection['gaps'] or not states or
             'unknown' in states else 'stale' if 'stale' in states else 'current')
    return {'state': state, 'facts': page, 'total': len(selected), 'next_cursor': cursor,
            'legacy_unbound_count': sum(fact['binding'] == 'legacy-unbound' for fact in projection['facts']),
            'journals': projection['journals'], 'gaps': projection['gaps'],
            'projection_digest': projection['projection_digest'], 'query_digest': query_digest,
            'projection_source_sha256': projection['projection_source_sha256'],
            'authority': False, 'acceptance': 'not-established'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--task', action='append', required=True)
    parser.add_argument('--repo-ref', required=True)
    parser.add_argument('--environment', required=True)
    parser.add_argument('--scope', required=True)
    parser.add_argument('--context-file', type=Path)
    parser.add_argument('--cursor-file', type=Path)
    parser.add_argument('--evidence-ref')
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    try:
        context = json.loads(args.context_file.read_text()) if args.context_file else None
        cursor = json.loads(args.cursor_file.read_text()) if args.cursor_file else None
        print(json.dumps(retrieve(args.repo, args.task, repo_ref=args.repo_ref,
            environment=args.environment, scope=args.scope, current_context=context,
            evidence_ref=args.evidence_ref, limit=args.limit, cursor=cursor), sort_keys=True))
    except (ValueError, OSError, UnicodeDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
