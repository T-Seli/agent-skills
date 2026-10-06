"""Fail-closed executable checks for review and release workflows."""
import argparse
import json
import sys
from pathlib import Path

from .code_state import code_state
from .release_guard import capture_rollback, verify_release


def main(argv=None):
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='action', required=True)
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
    args = parser.parse_args(argv)
    try:
        if args.action == 'manifest':
            result = code_state(args.repo, untracked=args.include, excluded=args.exclude_private)
        elif args.action == 'release':
            result = verify_release(args.repo, args.reviewed_sha, args.deployed_sha)
            if not result['ok']:
                print(json.dumps(result, sort_keys=True))
                return 1
        else:
            targets = dict(item.split('=', 1) for item in args.target)
            if len(targets) != len(args.target):
                raise ValueError('duplicate target')
            result = capture_rollback(Path(args.path), targets, task=args.task,
                                      release=args.release, repository=args.repository)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'safeguard failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
