"""Where installed code finds contract data and the release id (conveyor.json `layout`).

The root is the directory holding this package: an installed release (it carries
.release-pin.json and is not a git repository) or a checkout. No other code computes
contract paths or runs git for the release id.
"""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def contract(name, root=ROOT):
    """Path of a contract file such as conveyor.json; fails loudly when it is missing."""
    path = Path(root) / 'skills' / 'workflow-contracts' / name
    if not path.is_file():
        raise FileNotFoundError(f'contract file missing: {path}')
    return path


def release_id(root=ROOT):
    """The pin's commit in a release; git HEAD only in a checkout with no pin."""
    pin = Path(root) / '.release-pin.json'
    if pin.is_file():
        return json.loads(pin.read_text(encoding='utf-8'))['commit']
    done = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f'no release pin and not a git checkout: {root}')
    return done.stdout.strip()
