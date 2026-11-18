"""Exact immutable release identity and write-once rollback receipt."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

from . import layout
from .release_maintenance import _verify_release_root
from .release_package import package


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
_CONVEYOR = json.loads(layout.contract('conveyor.json').read_text(encoding='utf-8'))
ACTION = _CONVEYOR['action_record']
_DIGESTED = tuple(field for field in ACTION['fields'] if field not in {'digest_input', 'digest', 'used_at'})
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', re.ASCII)
_SESSION = re.compile(_CONVEYOR['session_id']['pattern'])
_BRANCH = re.compile(r'(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,127}', re.ASCII)
_READY = _CONVEYOR['labels']['lane'].replace('<name>', 'ready-to-release')
_REVIEWED = re.compile(_CONVEYOR['receipts']['reviewed_yes']['pattern'], re.M)
_INSTALL_TARGETS = {'all', 'claude', 'codex'}
_SETTINGS = ('.claude/settings.json', '.claude/settings.local.json', '.codex/config.toml', '.codex/hooks.json')
_REMOTE = 'origin'
_STAMP = '%Y-%m-%dT%H:%M:%SZ'
_ENTRY = re.compile(r'^## (?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}Z) — release: [0-9a-f]{7,40} to .+$', re.M)
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


def _gh(repo, *args, stdin=None):
    """The one external call: GitHub reads (parsed --json) and issue comments (a fake gh in tests)."""
    out = subprocess.run(['gh', *args], cwd=repo, input=stdin, capture_output=True, text=True, check=True).stdout
    return json.loads(out) if '--json' in args else out


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
        or _section_line(layout.contract('contracts.md').read_text(encoding='utf-8'), 'Lane limits')
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
        raise ValueError(f'train item must be <issue>:<pr>:<full head sha>: {text}')
    item = {'issue': None if issue == '-' else int(issue), 'pr': int(pr), 'head': head}
    _named([item])
    return item


def _named(train):
    for item in train:
        if item['issue'] is None:
            raise Refused('no-issue', f'PR {item["pr"]} names no issue; the sweep gives it one')


def _log_entries(log):
    text = log.read_text(encoding='utf-8') if log.exists() else ''
    return text, [chunk for chunk in re.split(r'^(?=## )', text, flags=re.M) if chunk.startswith('## ')]


def _rollback_refs(log):
    """The release entry's Rollback refs, each replaced by its Correction: lines in order."""
    text, entries = _log_entries(log)
    releases = [entry for entry in entries if _ENTRY.match(entry)]
    if not releases:
        return None
    if len(releases) > 1:
        raise ValueError(f'{log} has {len(releases)} release entries')
    line = re.search(r'^Rollback: (.+)$', releases[0], re.M)
    if not line:
        raise ValueError(f'{log} release entry has no Rollback line')
    commit = re.search(r'^Commit: ([0-9a-f]{40})$', releases[0], re.M)
    if not commit:
        raise ValueError(f'{log} release entry has no Commit line')
    refs = dict(pair.split(': ', 1) for pair in line.group(1).split(' · '))
    for fix in _CORRECTION.finditer(text):
        if fix['ref'] != 'Rollback':
            continue
        if refs.get(fix['field']) != fix['wrong']:
            raise ValueError(f'correction for {fix["field"]} does not match its Rollback ref')
        refs[fix['field']] = fix['right']
    return {'time': _ENTRY.match(releases[0])['time'], 'commit': commit.group(1), 'refs': refs}


def _last_deploy(repo, targets):
    """Newest release covering the targets (contracts.md § Task log: the last deploy)."""
    found = []
    for folder in _drafts(repo).glob('????-??-??-release-*'):
        record = json.loads((folder / 'action.json').read_text(encoding='utf-8'))
        deploy = set(targets) <= set(record['targets']) and _rollback_refs(folder / 'log.md')
        if deploy:
            found.append({**deploy, 'record': record})
    if not found:
        raise ValueError(f'no recorded release covers {targets}')
    found.sort(key=lambda item: item['time'])
    if len(found) > 1 and found[-1]['time'] == found[-2]['time']:
        raise ValueError('two releases share the newest minute; correct the logs first')
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
    elif not targets or len(set(targets)) != len(targets):
        raise ValueError('targets must be distinct branch names')
    else:
        for target in targets:
            if not _BRANCH.fullmatch(target):
                raise Refused('non-branch-target', f'{target!r} is not a branch name')
    if _folder(repo, action_id):
        raise Refused('reused', f'action id {action_id} already has a record')
    if kind == 'rollback':
        if train:
            raise ValueError('a rollback takes the train of the release it undoes')
        last, tree = _rollback_tree(repo, targets)
        train = last['record']['train']
    else:
        if not train:
            raise ValueError(f'{kind} needs its train')
        train = [_train_item(item) for item in train]
        tree = _git(repo, 'rev-parse', 'HEAD^{tree}')
    _check_limit(repo, train)
    if kind == 'rollback':  # undoing a rollback re-releases what it removes
        rollback = {target: last['commit'] for target in targets}
    elif kind == 'skills-install':  # the installed version is the main checkout's main
        rollback = {targets[0]: _git(repo, 'rev-parse', 'refs/heads/main')}
    else:
        rollback = {target: _remote_ref(repo, target) for target in targets}
    record = {'kind': kind, 'id': action_id, 'train': train, 'tree': tree, 'targets': list(targets),
              'rollback': rollback,
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
    """The branch's sha on origin; a name origin has no branch for is a non-branch target."""
    found = subprocess.run(['git', '-C', str(repo), 'ls-remote', '--exit-code', _REMOTE, f'refs/heads/{target}'],
                           capture_output=True, text=True)
    if found.returncode == 2:
        raise Refused('non-branch-target', f'{target} is not a branch on {_REMOTE}')
    found.check_returncode()
    return found.stdout.split()[0]


def _train_state(repo, record):
    """Each train item with its PR's head and labels and its issue's labels and comments (the receipt home)."""
    return [(item, _gh(repo, 'pr', 'view', str(item['pr']), '--json', 'headRefOid,labels'),
             _gh(repo, 'issue', 'view', str(item['issue']), '--json', 'labels,comments'))
            for item in record['train']]


def _labels(view):
    return {label['name'] for label in view['labels']}


def _held(state):
    for item, pr, issue in state:
        for noun, number, view in (('pr', item['pr'], pr), ('issue', item['issue'], issue)):
            if 'hold' in _labels(view):
                raise Refused('hold', f'{noun} {number} carries hold')


def _not_ready(state):
    for item, pr, issue in state:
        heads = {found['head'] for comment in issue['comments'] for found in _REVIEWED.finditer(comment['body'])}
        if _READY not in _labels(issue) or not any(pr['headRefOid'].startswith(head) for head in heads):
            raise Refused('not-ready', f'issue {item["issue"]} needs {_READY} and Reviewed: YES on PR {item["pr"]} head')


def _moved(repo, record, state):
    """Refuse when the commit or tree the user approved no longer holds; return the commit to act on."""
    if record['kind'] == 'rollback':
        last, tree = _rollback_tree(repo, record['targets'])
        if tree != record['tree']:
            raise Refused('moved-head', 'the recorded Rollback refs changed since the record was prepared')
        return last['refs'][record['targets'][0]]
    head = _git(repo, 'rev-parse', 'HEAD')
    if _git(repo, 'rev-parse', 'HEAD^{tree}') != record['tree']:
        raise Refused('moved-head', 'HEAD tree differs from the recorded tree')
    for item, pr, _ in state:
        if pr['headRefOid'] != item['head']:
            raise Refused('moved-head', f'PR {item["pr"]} head moved')
        if subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', item['head'], head]).returncode:
            raise Refused('moved-head', f'PR {item["pr"]} head is not in the release')
    return head


def _check(repo, record, kind, digest, now):
    """Every refusal before anything is written; return the commit and each pushed target's current ref."""
    if record['kind'] != kind or record['digest'] != digest or record['digest_input'] != _canonical(record) \
            or hashlib.sha256(record['digest_input'].encode()).hexdigest() != digest:
        raise Refused('digest-mismatch', 'the record does not match the approved digest')
    if record['used_at']:
        raise Refused('reused', f'used at {record["used_at"]}')
    if now >= datetime.strptime(record['expires_at'], _STAMP).replace(tzinfo=timezone.utc):
        raise Refused('expired', f'expired at {record["expires_at"]}')
    _check_limit(repo, record['train'])
    _named(record['train'])
    state = [] if kind == 'rollback' else _train_state(repo, record)
    _held(state)  # hold stops forward moves; it never blocks undoing one
    commit = _moved(repo, record, state)
    _not_ready(state)
    if kind == 'skills-install':
        if _git(repo, 'status', '--porcelain'):
            raise Refused('dirty-tree', 'the working tree differs from the recorded tree')
        return commit, {}
    before = {target: _remote_ref(repo, target) for target in record['targets']}
    if before != record['rollback']:
        raise Refused('moved-head', 'a target moved since the record was prepared; its Undo no longer holds')
    return commit, before


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


def _write(repo, folder, issues, lines):
    """Append the lines to the release log (it keeps every line), then post them on every train issue.

    Return the issues a post missed, so a sweep can re-post them from the log."""
    _append(folder, lines)
    missed = []
    for issue in issues:
        try:
            _gh(repo, 'issue', 'comment', str(issue), '--body-file', '-', stdin='\n'.join(lines) + '\n')
        except (OSError, subprocess.CalledProcessError):
            missed.append(issue)
    return missed


def _push(repo, folder, record, commit, before):
    """Move each target to commit (a rollback leases the refs it replaces), prove each landed."""
    if {target: _remote_ref(repo, target) for target in record['targets']} != before:
        raise RuntimeError('a target moved after the checks')
    capture_rollback(folder / 'rollback.json', before, task=record['id'], release=commit,
                     repository=_drafts(repo).parents[1].name)
    lease = [f'--force-with-lease=refs/heads/{t}:{sha}' for t, sha in before.items()] if record['kind'] == 'rollback' else []
    subprocess.run(['git', '-C', str(repo), 'push', '--atomic', '--quiet', *lease, _REMOTE,
                    *[f'{commit}:refs/heads/{t}' for t in record['targets']]], check=True)
    proofs = {t: verify_release(repo, commit, _remote_ref(repo, t)) for t in record['targets']}
    if not all(proof['ok'] for proof in proofs.values()):
        raise RuntimeError('a target does not run the approved commit')


def _settings(home):
    return {name: (home / name).read_bytes() if (home / name).exists() else None for name in _SETTINGS}


def _release(repo, commit, releases):
    """The commit's snapshot in the releases root: packaged once, re-verified when it already exists."""
    repository = _gh(repo, 'repo', 'view', '--json', 'nameWithOwner')['nameWithOwner']
    destination = Path(releases).expanduser() / commit[:7]
    if destination.exists():
        pin = json.loads((destination / '.release-pin.json').read_text(encoding='utf-8'))
        if pin['source'] != repository or pin['commit'] != commit:
            raise ValueError(f'{destination} holds another release')
        _verify_release_root(destination, Path(repo), pin)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    return Path(package(repo, destination, commit, repository)['destination'])


def _install(repo, record, commit, releases):
    """install.sh from the commit's snapshot in the releases root; settings stay the user's manual step."""
    export = _release(repo, commit, releases)
    home = Path.home()
    before = _settings(home)
    subprocess.run(['sh', 'install.sh', f'--target={record["targets"][0]}'], cwd=export, check=True,
                   stdout=subprocess.DEVNULL)
    changed = [name for name, data in _settings(home).items() if data != before[name]]
    for name in changed:
        if before[name] is None:
            (home / name).unlink()
        else:
            (home / name).write_bytes(before[name])
    if changed:
        raise RuntimeError(f'install changed settings, restored: {", ".join(changed)}')
    snippet = export / 'settings.snippet.json'
    return f'release {export} · settings snippet {snippet.name} sha256 {hashlib.sha256(snippet.read_bytes()).hexdigest()} written, not applied'


def _lines(record, commit, before, digest, question, session, stamp):
    """Every line run-approved writes, built before its first write (conveyor.json receipt_home build_first)."""
    kind, action_id, targets = record['kind'], record['id'], record['targets']
    approved = [f'## {stamp} — run-approved: {kind} {action_id}',
                f'Conveyor: {stamp} · run-approved · - → - · head {commit} · tests - · skills {layout.release_id()} · schedules -',
                f'Approved: {kind} {action_id} · digest {digest} · {stamp} · question {question} · session {session}']
    done = [f'## {stamp} — {kind}: {commit[:9]} to {", ".join(targets)}', f'Commit: {commit}']
    if kind != 'skills-install':
        done += [f'Evidence: {" · ".join(f"{t} at {commit}" for t in targets)}',
                 *[f'{"Rolled back" if kind == "rollback" else "Pushed"}: {commit} to {t}' for t in targets],
                 f'Rollback: {" · ".join(f"{t}: {sha}" for t, sha in before.items())}']
    failed = [f'## {stamp} — failed: {kind} {action_id}', f'Failed: {kind} {action_id} · {stamp} · ']
    return approved, done, failed


def run_approved(repo, kind, action_id, digest, *, question, session, releases, now=None):
    """The one route for a go: refuse per action_record.refusals, else run the kind's fixed path.

    skills-install packages into `releases`, the machine's releases root."""
    now = _now(now)
    if kind not in ACTION['kinds']:
        raise Refused('unknown-kind', kind)
    if not re.fullmatch(r'https?://\S+', question) or not _SESSION.fullmatch(session):
        raise ValueError('question must be a link and session a session id (conveyor.json session_id)')
    folder = _folder(repo, action_id)
    if folder is None:
        raise ValueError(f'no action record for {action_id}; prepare it first')
    record = json.loads((folder / 'action.json').read_text(encoding='utf-8'))
    commit, before = _check(repo, record, kind, digest, now)
    approved, done, failed = _lines(record, commit, before, digest, question, session, _minute(now))
    issues = list(dict.fromkeys(item['issue'] for item in record['train']))
    _claim(folder, record, now)
    try:
        missed = _write(repo, folder, issues, approved)
        if missed:
            raise RuntimeError(f'Approved: not posted on issues {missed}; nothing was run')
        if kind == 'skills-install':
            evidence = _install(repo, record, commit, releases)
            done.append(f'Evidence: {evidence}')
            result = {'kind': kind, 'id': action_id, 'commit': commit, 'evidence': evidence}
        else:
            _push(repo, folder, record, commit, before)
            result = {'kind': kind, 'id': action_id, 'commit': commit, 'rollback': before}
    except Exception as exc:  # after the claim: record the failure everywhere, keep the record used, re-raise
        reason = ' '.join(str(exc).split()) or type(exc).__name__
        _write(repo, folder, issues, failed[:-1] + [failed[-1] + reason])
        raise
    # It landed: the log holds every line; an issue a post missed is re-posted by a sweep, never a failure.
    return {**result, 'unposted': _write(repo, folder, issues, done)}


def correct_rollback(repo, action_id, target, wrong, right, *, now=None):
    """A receipt is never edited: append a Correction: that the rollback kind reads in its place."""
    folder = _folder(repo, action_id)
    if folder is None:
        raise ValueError(f'no action record for {action_id}')
    deploy = _rollback_refs(folder / 'log.md')
    if deploy is None:
        raise ValueError(f'{action_id} has no release entry to correct')
    refs = deploy['refs']
    if refs.get(target) != wrong:
        raise ValueError(f'{target} Rollback ref is {refs.get(target)}, not {wrong}')
    if not re.fullmatch(r'[0-9a-f]{40}', right) or _git(repo, 'rev-parse', '--verify', f'{right}^{{commit}}') != right:
        raise ValueError('the corrected ref must be a full commit sha in this repository')
    stamp = _minute(_now(now))
    _append(folder, [f'## {stamp} — correction: Rollback {target}',
                     f'Correction: Rollback · {target} was {wrong} · is {right}'])
    return {'id': action_id, 'target': target, 'was': wrong, 'is': right}
