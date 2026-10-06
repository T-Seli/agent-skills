"""Exact immutable release identity and write-once rollback receipt."""
import hashlib
import json
import os
import re
import tempfile
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
