"""Conditional, in-memory migration of owned legacy roles. Never edits live config."""
import hashlib
import json
import re
import tomllib
from pathlib import Path

OWNED = ('local-scout', 'skill-reviewer', 'skill-implementer')


def remove_owned_registrations(text, expected_roles):
    before = tomllib.loads(text)
    roles = before.get('agents', {})
    for name in OWNED:
        entry = roles.get(name)
        if (not isinstance(entry, dict) or set(entry) != {'description', 'config_file'} or
                entry != expected_roles.get(name)):
            raise ValueError(f'owned role {name} differs; preserve user changes')
    lines = text.splitlines(keepends=True)
    out = []; removing = None; found = set()
    for line in lines:
        if line.lstrip().startswith('['):
            match = re.fullmatch(r'\[agents\.([a-z-]+)\]\s*', line.strip())
            removing = match[1] if match and match[1] in OWNED else None
            if removing:
                found.add(removing)
                continue
        if removing and line.strip() and not line.lstrip().startswith('#'):
            # Only our simple two-field blocks are editable. Preserve comments,
            # and refuse multiline/inline-comment forms instead of guessing.
            if not re.match(r'^\s*(description|config_file)\s*=', line) or '#' in line or '"""' in line or "'''" in line:
                raise ValueError('non-simple owned role block; preserve and migrate manually')
            continue
        out.append(line)
    if found != set(OWNED): raise ValueError('owned role headers differ; preserve config')
    result = ''.join(out); after = tomllib.loads(result)
    expected = dict(before); expected_roles = dict(roles)
    for name in OWNED: expected_roles.pop(name)
    expected['agents'] = expected_roles
    if not expected_roles and 'agents' not in after: expected.pop('agents')
    if after != expected: raise ValueError('unexpected config change')
    return result


def plan(text, expected_roles):
    result = remove_owned_registrations(text, expected_roles)
    return {'source_config_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'staged_config_sha256': hashlib.sha256(result.encode()).hexdigest(),
            'remove_only_owned_legacy_roles': list(OWNED),
            'expected_entry_sha256': {name: hashlib.sha256(json.dumps(expected_roles[name],sort_keys=True).encode()).hexdigest() for name in OWNED},
            'standalone_files': 'regular TOML files; no additional [agents.name] registration',
            'live_config_written': False}


def apply_to_copy(text, migration, expected_roles):
    if hashlib.sha256(text.encode()).hexdigest() != migration.get('source_config_sha256'):
        raise ValueError('configuration changed after review; preserve newer edits')
    expected_hashes={name: hashlib.sha256(json.dumps(expected_roles[name],sort_keys=True).encode()).hexdigest() for name in OWNED}
    if migration.get('expected_entry_sha256') != expected_hashes:
        raise ValueError('verified expected role entries changed')
    result=remove_owned_registrations(text,expected_roles)
    if hashlib.sha256(result.encode()).hexdigest() != migration.get('staged_config_sha256'):
        raise ValueError('staged configuration differs from reviewed migration')
    return result
