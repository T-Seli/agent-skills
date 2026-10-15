"""Fail-closed executable checks for review and release workflows."""
import argparse
import json
import sys
from pathlib import Path

from .closeout import cleanup_gate, main_sync_gate
from .code_state import code_state
from .release_reconciliation import reconcile_release
from .release_guard import capture_rollback, verify_release
from .release_maintenance import maintain_release
from .task_checkpoint import operating_view


def main(argv=None):
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='action', required=True)
    task = subs.add_parser('task-status')
    task.add_argument('record', help='Existing task-local JSON record; read only')
    task.add_argument('--now', help='Explicit UTC time for reproducible overdue checks')
    manifest = subs.add_parser('manifest')
    manifest.add_argument('repo')
    manifest.add_argument('--include', action='append', default=[])
    manifest.add_argument('--exclude-private', action='append', default=[])
    release = subs.add_parser('release')
    release.add_argument('repo')
    release.add_argument('reviewed_sha')
    release.add_argument('deployed_sha')
    rollback = subs.add_parser('rollback-capture')
    rollback.add_argument('path')
    rollback.add_argument('--task', required=True)
    rollback.add_argument('--release', required=True)
    rollback.add_argument('--repository', required=True)
    rollback.add_argument('--target', action='append', required=True)
    reconcile = subs.add_parser('reconcile')
    reconcile.add_argument('manifest')
    reconcile.add_argument('state')
    maintain = subs.add_parser('maintain-release')
    maintain.add_argument('manifest')
    maintain.add_argument('state')
    maintain.add_argument('request')
    cleanup = subs.add_parser('cleanup')
    cleanup.add_argument('main')
    cleanup.add_argument('worktree')
    cleanup.add_argument('--base', required=True)
    cleanup.add_argument('--branch', required=True)
    cleanup.add_argument('--completion-accepted', action='store_true')
    cleanup.add_argument('--no-pending-effects', action='store_true')
    cleanup.add_argument('--lock-path')
    cleanup.add_argument('--expected-lock-owner')
    cleanup.add_argument('--remote-base')
    sync = subs.add_parser('main-sync')
    sync.add_argument('main')
    sync.add_argument('--base', required=True)
    sync.add_argument('--repository', required=True)
    sync.add_argument('--fetched-sha', required=True)
    sync.add_argument('--lock-path', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'task-status':
            result = operating_view(json.loads(Path(args.record).read_text(encoding='utf-8')), now=args.now)
        elif args.action == 'manifest':
            result = code_state(args.repo, untracked=args.include, excluded=args.exclude_private)
        elif args.action == 'release':
            result = verify_release(args.repo, args.reviewed_sha, args.deployed_sha)
            if not result['ok']:
                print(json.dumps(result, sort_keys=True))
                return 1
        elif args.action == 'rollback-capture':
            targets = dict(item.split('=', 1) for item in args.target)
            if len(targets) != len(args.target):
                raise ValueError('duplicate target')
            result = capture_rollback(Path(args.path), targets, task=args.task,
                                      release=args.release, repository=args.repository)
        elif args.action == 'reconcile':
            manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
            state = json.loads(Path(args.state).read_text(encoding='utf-8'))
            result = reconcile_release(manifest, state)
            if not result['system_wide']:
                print(json.dumps(result, sort_keys=True))
                return 1
        elif args.action == 'maintain-release':
            manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
            state = json.loads(Path(args.state).read_text(encoding='utf-8'))
            request = json.loads(Path(args.request).read_text(encoding='utf-8'))
            result = maintain_release(manifest, state, request)
        elif args.action == 'cleanup':
            result = cleanup_gate(args.main, args.worktree, base=args.base, branch=args.branch,
                                  completion_accepted=args.completion_accepted,
                                  no_pending_effects=args.no_pending_effects,
                                  lock_path=args.lock_path,
                                  expected_lock_owner=args.expected_lock_owner,
                                  remote_base=args.remote_base)
            if not result['eligible']:
                print(json.dumps(result, sort_keys=True))
                return 1
        else:
            result = main_sync_gate(args.main, base=args.base, repository=args.repository,
                                    fetched_sha=args.fetched_sha, lock_path=args.lock_path)
            if not result['ready']:
                print(json.dumps(result, sort_keys=True))
                return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'safeguard failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
