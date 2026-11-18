"""Exact immutable release identity and write-once rollback receipt."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess


_SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}', re.ASCII)


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def verify_release(root, reviewed_sha, deployed_sha):
    """Reject aliases and descendants; return exact reviewed/deployed trees."""
    if not _SHA.fullmatch(reviewed_sha) or not _SHA.fullmatch(deployed_sha):
        raise ValueError('full immutable commit IDs required')
    reviewed_commit = _git(root, 'rev-parse', '--verify', f'{reviewed_sha}^{{commit}}')
    deployed_commit = _git(root, 'rev-parse', '--verify', f'{deployed_sha}^{{commit}}')
    if reviewed_commit != reviewed_sha or deployed_commit != deployed_sha:
        raise ValueError('identity must name a commit directly')
    reviewed_tree = _git(root, 'rev-parse', f'{reviewed_commit}^{{tree}}')
    deployed_tree = _git(root, 'rev-parse', f'{deployed_commit}^{{tree}}')
    return {'ok': reviewed_commit == deployed_commit and reviewed_tree == deployed_tree,
            'reviewed_commit': reviewed_commit, 'deployed_commit': deployed_commit,
            'reviewed_tree': reviewed_tree, 'deployed_tree': deployed_tree}


def _seal(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def capture_rollback(path, rollback, *, task='local-task', release='local-release', repository='local-repository'):
    """Atomically preserve first target refs, bound to release identity and targets."""
    path = Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('symlinked receipt path')
    if not rollback or not all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in rollback.items()):
        raise ValueError('nonempty target refs required')
    identity = {'task': task, 'release': release, 'repository': repository,
                'targets': sorted(rollback)}
    if not all(isinstance(v, str) and v for v in (task, release, repository)):
        raise ValueError('task, release and repository required')
    payload = {'schema_version': 1, 'identity': identity, 'rollback': dict(sorted(rollback.items()))}
    receipt = {**payload, 'sha256': _seal(payload)}
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.rollback-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(receipt, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)
    if path.is_symlink():
        raise ValueError('symlinked receipt path')
    try:
        existing = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('malformed rollback receipt') from exc
    if not isinstance(existing, dict) or set(existing) != {'schema_version', 'identity', 'rollback', 'sha256'}:
        raise ValueError('invalid rollback receipt schema')
    sealed = {key: existing[key] for key in ('schema_version', 'identity', 'rollback')}
    if existing['schema_version'] != 1 or existing['sha256'] != _seal(sealed):
        raise ValueError('rollback receipt integrity failure')
    if not isinstance(existing['rollback'], dict) or not existing['rollback'] or not all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in existing['rollback'].items()):
        raise ValueError('invalid rollback refs')
    if existing['identity'] != identity or set(existing['rollback']) != set(rollback):
        raise ValueError('rollback receipt identity mismatch')
    return existing


# --- Conveyor action records: prepare once, run once under the user's one click (conveyor.md § Approvals).
_ROOT = Path(__file__).resolve().parents[1]
_CONTRACTS = _ROOT / 'skills' / 'workflow-contracts'
_CONVEYOR = json.loads((_CONTRACTS / 'conveyor.json').read_text(encoding='utf-8'))
ACTION = _CONVEYOR['action_record']
_DIGESTED = tuple(field for field in ACTION['fields'] if field not in {'digest_input', 'digest', 'used_at'})
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', re.ASCII)
_BRANCH = re.compile(r'(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,127}', re.ASCII)
_INSTALL_TARGETS = {'all', 'claude', 'codex'}
_SETTINGS = ('.claude/settings.json', '.claude/settings.local.json', '.codex/config.toml', '.codex/hooks.json')
_REMOTE = 'origin'
_STAMP = '%Y-%m-%dT%H:%M:%SZ'
_ENTRY = re.compile(r'^## (?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}Z) — deploy: [0-9a-f]{7,40} to .+$', re.M)
_CORRECTION = re.compile(_CONVEYOR['timeline']['correction'], re.M)


class Refused(ValueError):
    """One of conveyor.json action_record.refusals; nothing was run or written."""
    def __init__(self, reason, detail):
        if reason not in ACTION['refusals']:
            raise ValueError(f'not a contract refusal: {reason}')
        super().__init__(f'{reason}: {detail}')
        self.reason = reason


def _minute(moment):
    return moment.strftime('%Y-%m-%d %H:%MZ')


def _now(now):
    return now or datetime.now(timezone.utc)


def _canonical(record):
    return json.dumps({field: record[field] for field in _DIGESTED}, sort_keys=True, separators=(',', ':'))


def _gh(repo, *args):
    """The one external call: GitHub state for hold labels and PR heads (mocked in tests)."""
    return json.loads(subprocess.check_output(['gh', *args], cwd=repo, text=True))


def _drafts(repo):
    main = _git(repo, 'worktree', 'list', '--porcelain').splitlines()[0].split(' ', 1)[1]
    return Path(main) / '.claude' / 'drafts'


def _folder(repo, action_id):
    hits = [path for kind in ACTION['kinds'] for path in _drafts(repo).glob(f'????-??-??-{kind}-{action_id}')]
    if len(hits) > 1:
        raise ValueError(f'action id {action_id} has {len(hits)} records')
    return hits[0] if hits else None


def _section_line(text, label):
    parts = text.split('\n## Defaults', 1)
    body = parts[1].split('\n## ', 1)[0] if len(parts) == 2 else ''
    found = re.search(rf'^- {label}: (.+)$', body, re.M)
    return found.group(1) if found else None


def train_limit(repo):
    """Release train size from § Defaults `Lane limits`: the project's line wins over contracts.md."""
    project = Path(repo) / 'CLAUDE.md'
    line = (project.exists() and _section_line(project.read_text(encoding='utf-8'), 'Lane limits')) \
        or _section_line((_CONTRACTS / 'contracts.md').read_text(encoding='utf-8'), 'Lane limits')
    found = re.search(r'Release 1 train of ≤(\d+) PRs', line or '')
    if not found:
        raise ValueError('§ Defaults Lane limits names no Release train size')
    return int(found.group(1))


def _check_limit(repo, train):
    limit = train_limit(repo)
    if len(train) > limit:
        raise Refused('train-over-limit', f'{len(train)} PRs, limit {limit}')


def _train_item(text):
    parts = text.split(':')
    issue, pr, head = parts if len(parts) == 3 else ('', '', '')
    if not (issue == '-' or issue.isdigit()) or not pr.isdigit() or not re.fullmatch(r'[0-9a-f]{40}', head):
        raise ValueError(f'train item must be <issue|->:<pr>:<full head sha>: {text}')
    return {'issue': None if issue == '-' else int(issue), 'pr': int(pr), 'head': head}


def _log_entries(log):
    text = log.read_text(encoding='utf-8') if log.exists() else ''
    return text, [chunk for chunk in re.split(r'^(?=## )', text, flags=re.M) if chunk.startswith('## ')]


def _rollback_refs(log):
    """The deploy entry's Rollback refs, each replaced by its Correction: lines in order."""
    text, entries = _log_entries(log)
    deploys = [entry for entry in entries if _ENTRY.match(entry)]
    if not deploys:
        return None
    if len(deploys) > 1:
        raise ValueError(f'{log} has {len(deploys)} deploy entries')
    line = re.search(r'^Rollback: (.+)$', deploys[0], re.M)
    if not line:
        raise ValueError(f'{log} deploy entry has no Rollback line')
    refs = dict(pair.split(': ', 1) for pair in line.group(1).split(' · '))
    for fix in _CORRECTION.finditer(text):
        if fix['ref'] != 'Rollback':
            continue
        if refs.get(fix['field']) != fix['wrong']:
            raise ValueError(f'correction for {fix["field"]} does not match its Rollback ref')
        refs[fix['field']] = fix['right']
    deployed = re.search(r'^Commit: ([0-9a-f]{40})$', deploys[0], re.M).group(1)
    return {'time': _ENTRY.match(deploys[0])['time'], 'commit': deployed, 'refs': refs}


def _last_deploy(repo, targets):
    """Newest release deploy covering the targets (contracts.md § Task log: the last deploy)."""
    found = []
    for folder in _drafts(repo).glob('????-??-??-release-*'):
        record = json.loads((folder / 'action.json').read_text(encoding='utf-8'))
        deploy = set(targets) <= set(record['targets']) and _rollback_refs(folder / 'log.md')
        if deploy:
            found.append({**deploy, 'record': record})
    if not found:
        raise ValueError(f'no recorded deploy covers {targets}')
    found.sort(key=lambda item: item['time'])
    if len(found) > 1 and found[-1]['time'] == found[-2]['time']:
        raise ValueError('two deploys share the newest minute; correct the logs first')
    return found[-1]


def _rollback_tree(repo, targets):
    last = _last_deploy(repo, targets)
    trees = {_git(repo, 'rev-parse', f'{last["refs"][target]}^{{tree}}') for target in targets}
    if len(trees) != 1:
        raise ValueError('targets roll back to different trees; prepare one rollback per tree')
    return last, trees.pop()


def prepare_action(repo, kind, action_id, *, train, targets, session, minutes, now=None):
    """Write the action record: parameters only, digest over every field but digest and used_at."""
    now = _now(now)
    if kind not in ACTION['kinds']:
        raise Refused('unknown-kind', kind)
    if not _NAME.fullmatch(action_id) or not _NAME.fullmatch(session) or minutes <= 0:
        raise ValueError('id and session must be plain names; expiry must be positive')
    if kind == 'skills-install':
        if len(targets) != 1 or targets[0] not in _INSTALL_TARGETS:
            raise ValueError(f'skills-install takes one target of {sorted(_INSTALL_TARGETS)}')
    elif not targets or len(set(targets)) != len(targets) or not all(_BRANCH.fullmatch(t) for t in targets):
        raise ValueError('targets must be distinct plain branch names')
    if _folder(repo, action_id):
        raise Refused('reused', f'action id {action_id} already has a record')
    if kind == 'rollback':
        if train:
            raise ValueError('a rollback takes the train of the deploy it undoes')
        last, tree = _rollback_tree(repo, targets)
        train = last['record']['train']
    else:
        if not train:
            raise ValueError(f'{kind} needs its train')
        train = [_train_item(item) for item in train]
        tree = _git(repo, 'rev-parse', 'HEAD^{tree}')
    _check_limit(repo, train)
    record = {'kind': kind, 'id': action_id, 'train': train, 'tree': tree, 'targets': list(targets),
              'prepared_by': session, 'prepared_at': now.strftime(_STAMP),
              'expires_at': (now + timedelta(minutes=minutes)).strftime(_STAMP)}
    record['digest_input'] = _canonical(record)
    record['digest'] = hashlib.sha256(record['digest_input'].encode()).hexdigest()
    record['used_at'] = None
    folder = _drafts(repo) / f'{now:%Y-%m-%d}-{kind}-{action_id}'
    folder.mkdir(parents=True)
    with (folder / 'action.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, sort_keys=True, indent=1)
        stream.write('\n')
    return record


def _remote_ref(repo, target):
    return _git(repo, 'ls-remote', '--exit-code', _REMOTE, f'refs/heads/{target}').split()[0]


def _moved(repo, record):
    """Refuse when anything the user approved no longer holds; return the commit to act on."""
    if record['kind'] == 'rollback':
        last, tree = _rollback_tree(repo, record['targets'])
        if tree != record['tree']:
            raise Refused('moved-head', 'the recorded Rollback refs changed since the record was prepared')
        for target in record['targets']:
            if _remote_ref(repo, target) != last['commit']:
                raise Refused('moved-head', f'{target} no longer runs the deploy being rolled back')
        return last['refs'][record['targets'][0]]
    head = _git(repo, 'rev-parse', 'HEAD')
    if _git(repo, 'rev-parse', 'HEAD^{tree}') != record['tree']:
        raise Refused('moved-head', 'HEAD tree differs from the recorded tree')
    for item in record['train']:
        if _gh(repo, 'pr', 'view', str(item['pr']), '--json', 'headRefOid')['headRefOid'] != item['head']:
            raise Refused('moved-head', f'PR {item["pr"]} head moved')
        if subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', item['head'], head]).returncode:
            raise Refused('moved-head', f'PR {item["pr"]} head is not in the release')
    return head


def _held(repo, record):
    for item in record['train']:
        refs = [('pr', item['pr'])] + ([('issue', item['issue'])] if item['issue'] is not None else [])
        for noun, number in refs:
            labels = {label['name'] for label in _gh(repo, noun, 'view', str(number), '--json', 'labels')['labels']}
            if 'hold' in labels:
                raise Refused('hold', f'{noun} {number} carries hold')


def _check(repo, record, kind, digest, now):
    if record['kind'] != kind or record['digest'] != digest or record['digest_input'] != _canonical(record) \
            or hashlib.sha256(record['digest_input'].encode()).hexdigest() != digest:
        raise Refused('digest-mismatch', 'the record does not match the approved digest')
    if record['used_at']:
        raise Refused('reused', f'used at {record["used_at"]}')
    if now >= datetime.strptime(record['expires_at'], _STAMP).replace(tzinfo=timezone.utc):
        raise Refused('expired', f'expired at {record["expires_at"]}')
    _check_limit(repo, record['train'])
    if kind != 'rollback':  # hold stops forward moves; it never blocks undoing one
        _held(repo, record)
    return _moved(repo, record)


def _claim(folder, record, now):
    try:
        os.close(os.open(folder / 'used', os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise Refused('reused', 'another run claimed this record') from None
    record['used_at'] = now.strftime(_STAMP)
    temporary = folder / '.action.json.tmp'
    temporary.write_text(json.dumps(record, sort_keys=True, indent=1) + '\n', encoding='utf-8')
    os.replace(temporary, folder / 'action.json')


def _append(folder, lines):
    with (folder / 'log.md').open('a', encoding='utf-8') as stream:
        stream.write('\n' + '\n'.join(lines) + '\n')


def _push(repo, folder, record, commit, leases):
    """Capture current target refs, move each target to commit, prove each landed."""
    before = {target: _remote_ref(repo, target) for target in record['targets']}
    if leases and before != leases:
        raise RuntimeError('a target moved after the checks')
    capture_rollback(folder / 'rollback.json', before, task=record['id'], release=commit,
                     repository=_drafts(repo).parents[1].name)
    lease = [f'--force-with-lease=refs/heads/{t}:{sha}' for t, sha in leases.items()]
    subprocess.run(['git', '-C', str(repo), 'push', '--atomic', '--quiet', *lease, _REMOTE,
                    *[f'{commit}:refs/heads/{t}' for t in record['targets']]], check=True)
    proofs = {t: verify_release(repo, commit, _remote_ref(repo, t)) for t in record['targets']}
    if not all(proof['ok'] for proof in proofs.values()):
        raise RuntimeError('a target does not run the approved commit')
    return before


def _settings(home):
    return {name: (home / name).read_bytes() if (home / name).exists() else None for name in _SETTINGS}


def _install(repo, record):
    """install.sh at the record's tree; settings stay the user's manual step."""
    home = Path.home()
    before = _settings(home)
    subprocess.run(['sh', 'install.sh', f'--target={record["targets"][0]}'], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL)
    changed = [name for name, data in _settings(home).items() if data != before[name]]
    for name in changed:
        if before[name] is None:
            (home / name).unlink()
        else:
            (home / name).write_bytes(before[name])
    if changed:
        raise RuntimeError(f'install changed settings, restored: {", ".join(changed)}')
    snippet = Path(repo) / 'settings.snippet.json'
    return f'settings snippet {snippet.name} sha256 {hashlib.sha256(snippet.read_bytes()).hexdigest()} written, not applied'


def run_approved(repo, kind, action_id, digest, *, question, session, now=None):
    """The one route for a go: refuse per action_record.refusals, else run the kind's fixed path."""
    now = _now(now)
    if kind not in ACTION['kinds']:
        raise Refused('unknown-kind', kind)
    if not re.fullmatch(r'https?://\S+', question) or not _NAME.fullmatch(session):
        raise ValueError('question must be a link and session a plain name')
    folder = _folder(repo, action_id)
    if folder is None:
        raise ValueError(f'no action record for {action_id}; prepare it first')
    record = json.loads((folder / 'action.json').read_text(encoding='utf-8'))
    commit = _check(repo, record, kind, digest, now)
    leases = {t: _remote_ref(repo, t) for t in record['targets']} if kind == 'rollback' else {}
    _claim(folder, record, now)
    stamp, skills = _minute(now), _git(_ROOT, 'rev-parse', 'HEAD')
    _append(folder, [f'## {stamp} — run-approved: {kind} {action_id}',
                     f'Conveyor: {stamp} · run-approved · - → - · head {commit} · tests - · skills {skills} · schedules -',
                     f'Approved: {kind} {action_id} · digest {digest} · {stamp} · question {question} · session {session}'])
    targets = ', '.join(record['targets'])
    if kind == 'skills-install':
        evidence = _install(repo, record)
        _append(folder, [f'## {_minute(_now(None))} — skills-install: {commit[:9]} to {targets}',
                         f'Commit: {commit}', f'Evidence: {evidence}'])
        return {'kind': kind, 'id': action_id, 'commit': commit, 'evidence': evidence}
    before = _push(repo, folder, record, commit, leases)
    rollback = ' · '.join(f'{t}: {sha}' for t, sha in before.items())
    stage = 'deploy' if kind == 'release' else 'rollback'
    _append(folder, [f'## {_minute(_now(None))} — {stage}: {commit[:9]} to {targets}', f'Commit: {commit}',
                     f'Evidence: {" · ".join(f"{t} at {commit}" for t in record["targets"])}',
                     f'Rollback: {rollback}'])
    return {'kind': kind, 'id': action_id, 'commit': commit, 'rollback': before}


def correct_rollback(repo, action_id, target, wrong, right, *, now=None):
    """A receipt is never edited: append a Correction: that the rollback kind reads in its place."""
    folder = _folder(repo, action_id)
    if folder is None:
        raise ValueError(f'no action record for {action_id}')
    deploy = _rollback_refs(folder / 'log.md')
    if deploy is None:
        raise ValueError(f'{action_id} has no deploy entry to correct')
    refs = deploy['refs']
    if refs.get(target) != wrong:
        raise ValueError(f'{target} Rollback ref is {refs.get(target)}, not {wrong}')
    if not re.fullmatch(r'[0-9a-f]{40}', right) or _git(repo, 'rev-parse', '--verify', f'{right}^{{commit}}') != right:
        raise ValueError('the corrected ref must be a full commit sha in this repository')
    stamp = _minute(_now(now))
    _append(folder, [f'## {stamp} — correction: Rollback {target}',
                     f'Correction: Rollback · {target} was {wrong} · is {right}'])
    return {'id': action_id, 'target': target, 'was': wrong, 'is': right}
