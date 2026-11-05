"""Fail-closed executable checks for review and release workflows."""
import argparse
import json
import os
import sys
from pathlib import Path

from .closeout import cleanup_gate, main_sync_gate, sweep
from .code_state import code_state
from .release_reconciliation import reconcile_release
from .release_guard import capture_rollback, verify_release
from .release_maintenance import maintain_release
from .task_checkpoint import operating_view
from .task_reconciliation import reconcile_tasks
from .approval_attempts import append_receipt, summarize
from .test_slot import configured_memory_limits, configured_slots, run_in_slot
from .keep_awake import Native, Supervisor, status as awake_status, control as awake_control, reuse as awake_reuse


def machine_config():
    """Optional machine keys in the delegate config; absent file means defaults."""
    path = Path(os.environ.get('AGENT_SKILLS_CONFIG', '~/.config/agent-skills/workers.json')).expanduser()
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def main(argv=None):
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='action', required=True)
    awake = subs.add_parser('keep-awake', help='Explicit owned foreground protection; no implicit task-status launch')
    operations = awake.add_subparsers(dest='operation', required=True)
    operations.add_parser('host', help='Read-only current host/boot binding')
    acquire = operations.add_parser('acquire', help='Remain foreground until bounded completion; retain execution handle')
    acquire.add_argument('request', help='Explicit task/owner/host/deadline/approval/foreground JSON binding')
    acquire.add_argument('receipt', help='New receipt in the existing task artifact directory')
    acquire.add_argument('command', nargs=argparse.REMAINDER)
    probe = operations.add_parser('status', help='Fresh process/assertion/AC observation; no receipt write')
    probe.add_argument('receipt')
    for operation in ('renew', 'release'):
        item = operations.add_parser(operation, help='Queue exact-owner request, never signal a receipt PID')
        item.add_argument('receipt'); item.add_argument('--owner', required=True)
        item.add_argument('--generation', required=True)
    reuse = operations.add_parser('reuse', help='Fresh consumer reference without transfer/control')
    reuse.add_argument('receipt'); reuse.add_argument('--consumer', required=True)
    reuse.add_argument('--task-id', required=True, help='Exact consuming task, separate from its owner')
    reuse.add_argument('--until-utc', required=True)
    task = subs.add_parser('task-status')
    task.add_argument('record', help='Existing task-local JSON record; read only')
    task.add_argument('--now', help='Explicit UTC time for reproducible overdue checks')
    recovery = subs.add_parser('task-reconcile')
    recovery.add_argument('snapshot', help='Explicit bounded JSON inventory; read only')
    recovery.add_argument('--now', required=True)
    approval = subs.add_parser('approval-record')
    approval.add_argument('journal', help='Explicit task-local JSONL receipt sink')
    approval.add_argument('receipt', help='Sanitized structured receipt JSON')
    approval_report = subs.add_parser('approval-report')
    approval_report.add_argument('journal')
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
    cleanup.add_argument('--branch', help='Omit for a detached temp checkout')
    cleanup.add_argument('--run-id', help='Lock reasons naming this id count as this run\'s own')
    cleanup.add_argument('--rebuildable', action='append', default=[], help='Ignored dir the project can recreate')
    cleanup.add_argument('--completion-accepted', action='store_true')
    cleanup.add_argument('--no-pending-effects', action='store_true')
    cleanup.add_argument('--lock-path')
    cleanup.add_argument('--expected-lock-owner')
    cleanup.add_argument('--remote-base')
    sweeper = subs.add_parser('sweep', help='Dry run by default: remove every eligible, unheld worktree with --apply')
    sweeper.add_argument('main')
    sweeper.add_argument('--base', required=True)
    sweeper.add_argument('--apply', action='store_true')
    sweeper.add_argument('--rebuildable', action='append', default=[], help='Ignored dir the project can recreate')
    sweeper.add_argument('--active-hours', type=float, default=2, help='Git activity this recent holds a worktree')
    slot = subs.add_parser('test-slot', help='Run a shell command holding one of the machine-wide test slots; exit 75 when busy')
    slot.add_argument('--wait-seconds', type=float, default=540, help='Under the 10-minute agent tool limit')
    slot.add_argument('command', help='Shell command, e.g. the project test command')
    sync = subs.add_parser('main-sync')
    sync.add_argument('main')
    sync.add_argument('--base', required=True)
    sync.add_argument('--repository', required=True)
    sync.add_argument('--fetched-sha', required=True)
    sync.add_argument('--lock-path', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'keep-awake':
            if args.operation == 'host': result = {'host_id': Native().host_id()}
            elif args.operation == 'status': result = awake_status(args.receipt)
            elif args.operation == 'reuse':
                result = awake_reuse(args.receipt, consumer=args.consumer, task_id=args.task_id, until_utc=args.until_utc)
            elif args.operation == 'acquire':
                command = args.command[1:] if args.command[:1] == ['--'] else args.command
                return Supervisor(json.loads(Path(args.request).read_text()), args.receipt).run(command or None)
            else:
                result = awake_control(args.receipt, owner=args.owner, generation=args.generation, operation=args.operation)
        elif args.action == 'task-status':
            result = operating_view(json.loads(Path(args.record).read_text(encoding='utf-8')), now=args.now)
        elif args.action == 'task-reconcile':
            result = reconcile_tasks(json.loads(Path(args.snapshot).read_text()), now=args.now)
        elif args.action == 'approval-record':
            result = append_receipt(args.journal, json.loads(Path(args.receipt).read_text()))
        elif args.action == 'approval-report':
            result = summarize([json.loads(line) for line in Path(args.journal).read_text().splitlines() if line.strip()])
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
                                  remote_base=args.remote_base, rebuildable=args.rebuildable,
                                  run_id=args.run_id)
            if not result['eligible']:
                print(json.dumps(result, sort_keys=True))
                return 1
        elif args.action == 'test-slot':
            config = machine_config()
            slots, source = configured_slots(config)
            max_swap_gb, min_free_gb = configured_memory_limits(config)
            print(f'test-slot: {slots} slots ({source})', file=sys.stderr)
            return run_in_slot(args.command, slots=slots, wait_seconds=args.wait_seconds,
                               max_swap_gb=max_swap_gb, min_free_gb=min_free_gb)
        elif args.action == 'sweep':
            result = sweep(args.main, base=args.base, apply=args.apply, rebuildable=args.rebuildable,
                           lease_files=machine_config().get('worktree_lease_files', []),
                           active_seconds=args.active_hours * 3600)
        else:
            result = main_sync_gate(args.main, base=args.base, repository=args.repository,
                                    fetched_sha=args.fetched_sha, lock_path=args.lock_path)
            if not result['ready']:
                print(json.dumps(result, sort_keys=True))
                return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f'safeguard failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
