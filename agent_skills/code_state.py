"""Deterministic, bounded Git candidate state with explicit untracked coverage."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def _private(path):
    parts = Path(path).parts
    return any(part in {'.claude', '.git', 'logs', 'private', 'customer', 'customers', 'credentials', '__pycache__'} for part in parts) or Path(path).suffix.lower() in {'.env', '.log', '.key', '.pem', '.p12', '.db', '.sqlite'}


def _path(root, name):
    p = Path(name)
    if p.is_absolute() or '..' in p.parts or not p.parts or p.as_posix() != name:
        raise ValueError('invalid repository-relative path')
    target = root / p
    if not target.resolve(strict=False).is_relative_to(root) or any((root / Path(*p.parts[:i])).is_symlink() for i in range(1, len(p.parts) + 1)):
        raise ValueError('symlink or path escape')
    return target


def code_state(root, *, untracked=(), excluded=()):
    """Hash tracked contents/modes and explicitly admitted untracked source.

    Unknown untracked names fail closed. Exclusions are limited to visibly
    private paths; their names are not placed in the returned manifest.
    """
    root = Path(root).resolve()
    tracked = set(filter(None, _git(root, 'ls-files', '-z').decode().split('\0')))
    unknown = set(filter(None, _git(root, 'ls-files', '--others', '-z').decode().split('\0')))
    # Include ignored names in the inventory. We inspect names only until
    # the caller explicitly admits a source file or excludes a private path.
    included, hidden = set(untracked), set(excluded)
    if included & hidden or included - unknown or hidden - unknown:
        raise ValueError('untracked dispositions do not match Git inventory')
    if any(not _private(name) for name in hidden):
        raise ValueError('source file cannot be excluded')
    if unknown != included | hidden:
        raise ValueError('unresolved untracked paths: explicit include or private exclusion required')
    if any(_private(name) for name in tracked):
        raise ValueError('tracked sensitive path prevents a complete review receipt')
    entries = []
    for name in sorted(tracked | included):
        if _private(name):
            raise ValueError('private source path cannot be included')
        file = _path(root, name)
        if name in included and not file.is_file():
            raise ValueError('explicit source file is missing')
        if file.exists() and not file.is_file():
            raise ValueError('source path is not a regular file')
        state = 'tracked' if name in tracked else 'explicit-untracked'
        mode = '100755' if file.exists() and os.access(file, os.X_OK) else '100644'
        entries.append({'path': name, 'state': state if file.exists() else 'deleted', 'mode': mode if file.exists() else None,
                        'sha256': hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None})
    payload = {'head': _git(root, 'rev-parse', 'HEAD').decode().strip(), 'files': entries,
               'excluded_untracked_count': len(hidden)}
    payload['digest'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return payload
