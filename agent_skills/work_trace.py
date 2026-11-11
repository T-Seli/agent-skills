"""Host-neutral work trace on existing issue/task records; local preview only."""
import hashlib
import json
import re

REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
ISSUE = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*')
PR = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*')


def text(value, field):
    if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
        raise ValueError(f'work trace needs one-line {field}')
    return value


def validate(record, repo, number):
    if not isinstance(record, dict) or record.get('issue_url') != f'https://github.com/{repo}/issues/{number}':
        raise ValueError('work trace needs the exact target issue URL')
    if not isinstance(record.get('source_issue_url'), str) or not ISSUE.fullmatch(record['source_issue_url']):
        raise ValueError('work trace needs a native source issue URL')
    text(record.get('owner'), 'accountable owner')
    executor = record.get('executor')
    if not isinstance(executor, dict): raise ValueError('work trace needs executor host/session')
    text(executor.get('host'), 'executor host'); text(executor.get('session_ref'), 'recoverable session/task reference')
    artifacts = record.get('artifacts')
    if not isinstance(artifacts, list) or not artifacts: raise ValueError('work trace needs source artifacts')
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not isinstance(artifact.get('repo'), str) or not REPO.fullmatch(artifact['repo']):
            raise ValueError('work trace needs artifact repository')
        text(artifact.get('branch'), 'branch')
        if not isinstance(artifact.get('commit'), str) or not re.fullmatch(r'[0-9a-f]{40}', artifact['commit']):
            raise ValueError('work trace needs full source commit')
        state = artifact.get('pr_state')
        if state not in ('none', 'unverified', 'draft', 'open', 'merged', 'closed'):
            raise ValueError('work trace needs explicit native PR state or unverified/none')
        url = artifact.get('pr_url')
        if state in ('none', 'unverified'):
            if url is not None: raise ValueError('use explicit supported PR facts, not an unverified link')
        elif not isinstance(url, str) or not PR.fullmatch(url) or not url.startswith(f"https://github.com/{artifact['repo']}/pull/"):
            raise ValueError('work trace needs native PR URL')
    decisions, verification = record.get('decisions'), record.get('verification')
    if not isinstance(decisions, list): raise ValueError('work trace needs decision references (empty when none)')
    for ref in decisions: text(ref, 'original decision reference')
    if not isinstance(verification, list) or not verification: raise ValueError('work trace needs verification references')
    for ref in verification: text(ref, 'verification reference')
    next_action = record.get('next_action')
    if not isinstance(next_action, dict): raise ValueError('work trace needs next action and owner')
    text(next_action.get('owner'), 'next owner'); text(next_action.get('action'), 'next action')
    states = record.get('states')
    allowed = ('unverified', 'open', 'blocked', 'reported', 'verified', 'not_applicable')
    if not isinstance(states, dict) or any(states.get(k) not in allowed for k in ('implementation', 'deployment', 'acceptance')):
        raise ValueError('work trace needs separate implementation/deployment/acceptance states')
    return record


def preview(record):
    """Material facts only: observation clocks do not create duplicate updates."""
    issue = record.get('issue_url', '') if isinstance(record, dict) else ''
    match = re.fullmatch(r'https://github\.com/([^/]+/[^/]+)/issues/([1-9][0-9]*)', issue)
    if not match: raise ValueError('invalid target issue URL')
    validate(record, match[1], int(match[2]))
    facts = {k: record[k] for k in ('issue_url', 'source_issue_url', 'owner', 'executor', 'artifacts',
                                   'decisions', 'verification', 'next_action', 'states')}
    fingerprint = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    sources = []
    for a in record['artifacts']:
        commit = f"https://github.com/{a['repo']}/commit/{a['commit']}"
        sources.append(f"{a['repo']} branch `{a['branch']}` · [commit {a['commit'][:12]}]({commit}) · " +
                       (f"[PR]({a['pr_url']}) {a['pr_state']}" if a['pr_url'] else f"PR {a['pr_state']}"))
    states = record['states']
    body = '\n'.join([
        f"Work: {record['issue_url']} · source: {record['source_issue_url']}",
        f"Owner: {record['owner']} · executor: {record['executor']['host']} · {record['executor']['session_ref']}",
        *sources,
        'Decisions: ' + ('; '.join(record['decisions']) or 'none recorded'),
        'Verification: ' + '; '.join(record['verification']),
        f"Implementation: {states['implementation']} · deployment: {states['deployment']} · acceptance: {states['acceptance']}",
        f"Next: {record['next_action']['owner']} — {record['next_action']['action']}",
        f"<!-- agent-skills:work-update {fingerprint} -->"])
    return {'fingerprint': fingerprint, 'body': body, 'published': False}
