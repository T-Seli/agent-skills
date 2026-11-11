"""Offline admission of two-sided Node TAP evidence; never trusts a green label.

Consumes captured per-process stdout, exit code and signal plus an exact source/
environment identity. This validates structure/completeness, not artifact origin or
actual deployment. Fetch provenance through the host's trusted GitHub read route.
It deliberately rejects legacy count-only CCM comparison summaries.
"""
import argparse
import json
import re
from pathlib import Path

IDENTITY_FIELDS = ('repo', 'head', 'tested_commit', 'tested_tree', 'base', 'workflow',
                   'runner', 'command', 'lockfiles', 'dependency_setup', 'runtime', 'os', 'services')


def complete_tap(process):
    if not isinstance(process, dict) or not isinstance(process.get('stdout'), str):
        raise ValueError('missing per-process stdout')
    if process.get('signal') is not None or type(process.get('exit_code')) is not int:
        raise ValueError('signal termination or missing exit code')
    text = process['stdout']
    lines = text.splitlines()  # consumes a final line even without a trailing newline
    if sum(line in ('TAP version 13', 'TAP version 14') for line in lines) != 1:
        raise ValueError('requires one TAP stream per process')
    if any(re.match(r'\s*Bail out!', line, re.I) for line in lines):
        raise ValueError('TAP bailout')
    # Suite summaries collapse different failing children into the same suite
    # name. Until hierarchical identities are supported, never treat such a
    # baseline as reusable proof that a nested regression is unchanged.
    if any(re.match(r'^\s+not ok\b', line) or re.search(r"failureType:\s*['\"]?subtestsFailed", line) for line in lines):
        raise ValueError('nested failing TAP needs hierarchical evidence; comparison held')
    plans = [int(m[1]) for line in lines if (m := re.fullmatch(r'1\.\.(\d+)', line))]
    cases = [m for line in lines if (m := re.match(r'^(not ok|ok) (\d+)(?: - (.*))?$', line))]
    if len(plans) != 1 or plans[0] == 0 or [int(m[2]) for m in cases] != list(range(1, plans[0] + 1)):
        raise ValueError('missing, zero, duplicated or incomplete top-level TAP plan')
    counts = {}
    for line in lines:
        match = re.fullmatch(r'# (tests|pass|fail|cancelled|skipped|todo) (\d+)', line)
        if match:
            if match[1] in counts:
                raise ValueError('duplicate TAP summary')
            counts[match[1]] = int(match[2])
    if set(counts) != {'tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'} or counts['tests'] == 0:
        raise ValueError('missing final counts or zero tests')
    if counts['tests'] != sum(counts[k] for k in ('pass', 'fail', 'cancelled', 'skipped', 'todo')) or counts['cancelled']:
        raise ValueError('inconsistent counts or cancelled tests')
    if counts['pass'] + counts['fail'] == 0:
        raise ValueError('no executed assertions: all tests skipped or todo')
    failed = {m[3] or m[2] for m in cases if m[1] == 'not ok' and not re.search(r'\s+#\s*(?:TODO|SKIP)\b', m[3] or '', re.I)}
    names = [m[3] or m[2] for m in cases]
    if failed and len(names) != len(set(names)):
        raise ValueError('duplicate top-level names cannot identify failing assertions')
    if len(failed) != counts['fail']:
        raise ValueError('failure summary contradicts top-level cases')
    # Node exits 1 for complete assertion failures. Other nonzero exits or a
    # successful exit with failing assertions are infrastructure/inconsistent data.
    if process['exit_code'] != (1 if counts['fail'] else 0):
        raise ValueError('infrastructure exit or assertion/exit mismatch')
    return {'tests': counts['tests'], 'failures': sorted(failed)}


def validate_comparison(receipt, expected):
    identity = receipt.get('identity', {})
    if not isinstance(identity, dict) or not isinstance(expected, dict):
        raise ValueError('missing source/environment identity')
    for field in IDENTITY_FIELDS:
        if field not in expected or expected[field] is None or expected[field] == '' or field not in identity or identity[field] != expected[field]:
            raise ValueError(f'missing or mismatched identity: {field}')
    for field in ('head', 'tested_commit', 'tested_tree', 'base'):
        if not isinstance(expected[field], str) or not re.fullmatch(r'[0-9a-f]{40}', expected[field]):
            raise ValueError(f'full source identity required: {field}')
    head, base = complete_tap(receipt.get('candidate')), complete_tap(receipt.get('baseline'))
    added = sorted(set(head['failures']) - set(base['failures']))
    return {'complete': True, 'eligible': not added, 'new_failures': added,
            'candidate': head, 'baseline': base, 'identity': identity}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt'); parser.add_argument('--expected', required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_comparison(json.loads(Path(args.receipt).read_text()), json.loads(Path(args.expected).read_text()))
    except (ValueError, OSError, TypeError, AttributeError) as error:
        print(json.dumps({'complete': False, 'eligible': False, 'reason': str(error)}))
        return 1
    print(json.dumps(result))
    return 0 if result['eligible'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
