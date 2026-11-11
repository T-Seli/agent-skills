"""Plan a nonsecret GitHub helper migration offline; never edits the installed config.

Outputs a conditional overlay, not a copy of private config. New publisher defaults
to shadow; it cannot infer approval or fabricate issue/deployment evidence.
"""
import argparse
import copy
import hashlib
import json
import socket
from pathlib import Path

POLICY_FILES = ('skills/test-review/SKILL.md', 'skills/test-review/references/hosted-review.md',
                'skills/test-review/scripts/pr_sweep.py', 'skills/workflow-contracts/contracts.md',
                'skills/workflow-contracts/behavior.md', 'skills/workflow-contracts/decisions.md',
                'skills/workflow-contracts/issues.md',
                'skills/workflow-contracts/references/ci-evidence.md', 'agent_skills/ci_evidence.py',
                'skills/workflow-contracts/references/work-trace.md', 'agent_skills/work_trace.py',
                'skills/workflow-contracts/references/research.md',
                'skills/workflow-contracts/references/review-evidence.md',
                'agent_skills/research_contract.py', 'agent_skills/observation_evidence.py',
                'agent_skills/system_audit.py', 'agent_skills/task_checkpoint.py',
                'skills/ui-design/SKILL.md', 'skills/ui-design/references/design.md',
                'skills/ui-design/references/visualization.md',
                'skills/ui-design/references/iteration.md',
                'skills/workflow-contracts/references/execution-proof.md',
                'agent_skills/evaluation_contract.py', 'agent_skills/catalog.json')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def policy_identity(root):
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in POLICY_FILES}
    return 'skills-sha256:' + digest(files), files


def plan(config, identity, hostname, root):
    if not isinstance(config, dict) or not isinstance(config.get('pr_sweep'), dict):
        raise ValueError('existing pr_sweep object required; do not invent a destination or authorization')
    old = config['pr_sweep']
    if not old.get('repos') or not old.get('authorization'):
        raise ValueError('existing configured repositories and authorization required')
    if not isinstance(identity, dict) or type(identity.get('id')) is not int or identity['id'] < 1 or not identity.get('login') or identity.get('source') != 'gh api user' or not identity.get('observed_at'):
        raise ValueError('verified nonsecret gh api user identity snapshot required')
    if not isinstance(hostname, str) or not hostname.strip():
        raise ValueError('verified publisher hostname required')
    policy, files = policy_identity(root)
    patch = {'schema_version': 2, 'mode': 'shadow', 'reviewer_id': identity['id'],
             'review_policy': policy, 'publisher_host': hostname,
             'publication_authorization': ''}
    return {'migration_version': 1, 'source_config_sha256': digest(config),
            'source_pr_sweep_sha256': digest(old), 'policy_files': files,
            'identity': {'id': identity['id'], 'login': identity['login'],
                         'source': identity['source'], 'observed_at': identity['observed_at']},
            'pr_sweep_overlay': patch,
            'activation': 'not performed; preserve installed release/config/schedules',
            'remaining': ['migrate saved callers explicitly; never infer a reviewed base from current state',
                          'verify issue evidence preparation and genuine receipt population',
                          'agree single publisher handover and scoped publication authority before publish mode',
                          'project CI producer remains separate; hold unavailable hosted proof']}


def apply_to_copy(config, migration, root):
    """Pure conditional merge used for fixtures/staging; returns a copy, no writes."""
    if migration.get('migration_version') != 1 or migration.get('source_config_sha256') != digest(config) or migration.get('source_pr_sweep_sha256') != digest(config.get('pr_sweep')):
        raise ValueError('configuration changed; regenerate and review migration')
    policy, files = policy_identity(root)
    if migration.get('policy_files') != files or migration.get('pr_sweep_overlay', {}).get('review_policy') != policy:
        raise ValueError('review policy source changed; regenerate migration')
    patch = migration.get('pr_sweep_overlay', {})
    expected = {'schema_version', 'mode', 'reviewer_id', 'review_policy', 'publisher_host', 'publication_authorization'}
    if set(patch) != expected or patch['schema_version'] != 2 or patch['mode'] != 'shadow' or patch['publication_authorization'] != '' or patch['reviewer_id'] != migration.get('identity', {}).get('id'):
        raise ValueError('migration can only stage shadow mode with the verified identity')
    staged = copy.deepcopy(config)
    staged['pr_sweep'].update(patch)
    return staged


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True); parser.add_argument('--identity', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    result = plan(json.loads(Path(args.config).read_text()), json.loads(Path(args.identity).read_text()), socket.gethostname(), root)
    # Exclusive create avoids overwriting another task's evidence or the live config.
    with Path(args.output).open('x') as out:
        json.dump(result, out, indent=2); out.write('\n')
    print(json.dumps({'planned': True, 'activated': False, 'output': args.output,
                      'mode': 'shadow', 'review_policy': result['pr_sweep_overlay']['review_policy']}))


if __name__ == '__main__':
    main()
