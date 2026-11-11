"""Pure research evidence checks; no retrieval, command execution or authority grants."""
from urllib.parse import urlsplit
from .observation_evidence import utc

TRIGGERS = {'new-api', 'dependency', 'architecture', 'changing-fact', 'unknown-failure', 'tradeoff'}
PERFORMANCE_METRICS = {'correctness', 'repeated-run-reliability', 'regression-safety',
                       'latency', 'cost', 'human-rework'}


def research_decision(*, explicit_request=False, triggers=(), skip_reason=None):
    if type(explicit_request) is not bool or not isinstance(triggers, (list, tuple)) or any(
            x not in TRIGGERS for x in triggers):
        raise ValueError('explicit research intent and known decision triggers required')
    if explicit_request or triggers:
        return {'status': 'required', 'explicit_request': explicit_request,
                'triggers': sorted(set(triggers)), 'reason': 'current decision-relevant retrieval required'}
    if not isinstance(skip_reason, str) or not skip_reason.strip():
        raise ValueError('every blueprint needs a research decision or proportional skip reason')
    return {'status': 'skipped', 'explicit_request': False, 'triggers': [], 'reason': skip_reason}


def assess_research(packet, *, artifact_ref, current_versions, observed_at_utc):
    """Validate caller-supplied provenance, not source truth or real tool execution."""
    if not isinstance(packet, dict):
        raise ValueError('research packet required')
    if not isinstance(artifact_ref, str) or not artifact_ref.strip() or not isinstance(current_versions, dict):
        raise ValueError('current artifact and installed-version context required')
    d = packet['decision']
    expected = research_decision(explicit_request=d['explicit_request'], triggers=d['triggers'],
                                 skip_reason=d['reason'])
    if d != expected:
        raise ValueError('research decision binding differs')
    status = packet['status']
    if status not in ('complete', 'limited', 'blocked', 'skipped'):
        raise ValueError('explicit research status required')
    if packet.get('artifact_ref') != artifact_ref:
        return {'state': 'hold', 'missing': ['current artifact revision mismatch'], 'grants_authority': False}
    sources = packet.get('sources', [])
    if not isinstance(sources, list):
        raise ValueError('inspected source list required')
    if status == 'skipped':
        if d['status'] != 'skipped' or sources:
            raise ValueError('explicit research requests cannot silently skip')
        return {'state': 'skipped', 'reason': d['reason'], 'grants_authority': False}
    for field in ('question', 'limitations', 'local_fit', 'validation'):
        if not isinstance(packet.get(field), str) or not packet[field].strip():
            raise ValueError('research question, fit, limits and falsifiable validation required')
    if d['status'] != 'required':
        raise ValueError('retrieval requires its bound decision')
    now = utc(observed_at_utc)
    missing = []
    for s in sources:
        url = urlsplit(s['url'])
        if url.scheme != 'https' or not url.netloc or url.username or url.password:
            raise ValueError('public HTTPS primary-source URL required')
        if not all(s.get(k) for k in ('receipt_ref', 'finding', 'limits', 'component', 'applicable_version')):
            raise ValueError('source inspection provenance and limits required')
        if s.get('primary') is not True or s.get('retrieval') != 'dynamic-read':
            missing.append('inspected primary dynamic retrieval')
        if 'published_or_revision' not in s or utc(s['accessed_at_utc']) > now:
            raise ValueError('source date/revision or explicit unknown and actual access time required')
        if current_versions.get(s['component']) != s['applicable_version']:
            missing.append('source/local version mismatch')
    if status != 'complete':
        if not packet.get('next_route'):
            raise ValueError('blocked/limited research needs its next supported route')
        missing.append(status)
    if not sources:
        missing.append('no inspected source')
    if not isinstance(packet.get('alternatives'), list) or not packet['alternatives']:
        missing.append('rejected alternative/baseline rationale')
    if packet.get('performance_claim') is True and not PERFORMANCE_METRICS.issubset(
            set(packet.get('validation_metrics', []))):
        missing.append('local baseline/candidate performance and rework checks')
    return {'state': 'hold' if missing else 'ready-for-local-validation',
            'missing': sorted(set(missing)), 'grants_authority': False}
