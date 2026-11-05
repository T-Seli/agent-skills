"""Machine-wide cap on concurrent test suites: N flock slot files held by a supervisor that ends its run."""
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BUSY = 75  # exit status: no slot freed in time; not a test failure
DEFAULT_SLOTS = 4
DEFAULT_MAX_SWAP_GB = 8  # swap in use above this holds new runs back
DEFAULT_MIN_FREE_GB = 6  # free memory below this holds new runs back
MEMORY_RECHECK_SECONDS = 5
HELD = 'AGENT_SKILLS_TEST_SLOT_HELD'  # set inside a run, so a nested test-slot does not wait on its own slot


def slot_dir():
    return Path(os.environ.get('AGENT_SKILLS_TEST_SLOTS', '~/.local/state/agent-skills/test-slots')).expanduser()


def configured_slots(config):
    if 'test_slots' not in config:
        return DEFAULT_SLOTS, 'default'
    value = config['test_slots']
    if type(value) is not int or value < 1:
        raise ValueError(f'test_slots must be an integer >= 1, got {value!r}')
    return value, 'config'


def configured_memory_limits(config):
    limits = []
    for key, default in (('test_max_swap_gb', DEFAULT_MAX_SWAP_GB), ('test_min_free_gb', DEFAULT_MIN_FREE_GB)):
        value = config.get(key, default)
        if type(value) not in (int, float) or value < 0:
            raise ValueError(f'{key} must be a number >= 0, got {value!r}')
        limits.append(value)
    return tuple(limits)


def _command(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def read_memory():
    """(swap used GB, free memory GB) from macOS; fails loudly when the output can't be read."""
    swap = re.search(r'used = ([0-9.]+)M', _command('sysctl', '-n', 'vm.swapusage'))
    free = re.search(r'free percentage: ([0-9]+)%', _command('memory_pressure', '-Q'))
    if not swap or not free:
        raise RuntimeError('cannot read swap or free memory (sysctl vm.swapusage, memory_pressure -Q)')
    total = int(_command('sysctl', '-n', 'hw.memsize'))
    return float(swap.group(1)) / 1024, int(free.group(1)) / 100 * total / 2**30


def _memory_problem(reading, max_swap_gb, min_free_gb):
    swap, free = reading
    if swap > max_swap_gb:
        return f'swap {swap:.1f} GB used (limit {max_swap_gb:g} GB)'
    if free < min_free_gb:
        return f'free memory {free:.1f} GB (needs {min_free_gb:g} GB)'
    return None


def _try_lock(directory, index):
    fd = os.open(directory / f'slot-{index}.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _holders(directory, slots):
    return [(directory / f'slot-{i}.lock').read_text().strip() for i in range(slots)
            if (directory / f'slot-{i}.lock').exists()]


class _Stopped(Exception):
    def __init__(self, signum):
        self.status = 128 + signum


def _raise_stopped(signum, _frame):
    raise _Stopped(signum)


def _signal_group(child, sig):
    """False once the run's group is gone; macOS reports EPERM when only zombies remain."""
    child.poll()  # reap the leader
    try:
        os.killpg(child.pid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _end_group(child, grace=2.0):
    """Terminate everything left in the run's process group, then kill what ignores it."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _signal_group(child, sig):
            return
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not _signal_group(child, 0):
                return
            time.sleep(0.05)


def _supervise(command, poll):
    """Run `command` in its own process group; end the group when it finishes, on a signal, or when our caller dies."""
    caller = os.getppid()
    previous = {signum: signal.signal(signum, _raise_stopped) for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    child = subprocess.Popen(['/bin/sh', '-c', command], process_group=0, env={**os.environ, HELD: '1'})
    try:
        while True:
            try:
                status = child.wait(timeout=poll)
                return status if status >= 0 else 128 - status
            except subprocess.TimeoutExpired:
                if os.getppid() != caller:  # the session that started us is gone
                    return 128 + signal.SIGHUP
    except _Stopped as stopped:
        return stopped.status
    finally:
        _end_group(child)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _take(directory, slots, weight):
    """`weight` slot fds, or None with nothing held."""
    fds = []
    for index in range(slots):
        fd = _try_lock(directory, index)
        if fd is not None:
            fds.append(fd)
            if len(fds) == weight:
                return fds
    for fd in fds:
        os.close(fd)
    return None


def run_in_slot(command, *, slots, wait_seconds, max_swap_gb, min_free_gb, weight=1, memory=read_memory, poll=0.2):
    """Run `command` holding `weight` slots until the run and everything it started has ended.
    Waits while slots are busy or memory is short; BUSY after wait_seconds. Inside a run it passes straight through."""
    if os.environ.get(HELD):
        os.execvp('/bin/sh', ['sh', '-c', command])
    if not 1 <= weight <= slots:
        raise ValueError(f'weight must be between 1 and the slot count {slots}, got {weight}')
    directory = slot_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + wait_seconds
    waiting = False
    problem, checked = None, None
    while True:
        if checked is None or time.monotonic() - checked >= MEMORY_RECHECK_SECONDS:
            problem, checked = _memory_problem(memory(), max_swap_gb, min_free_gb), time.monotonic()
            if problem and not waiting:
                print(f'test-slot: waiting for memory: {problem}', file=sys.stderr)
                waiting = True
        if problem:
            if time.monotonic() >= deadline:
                print(f'test-slot: memory still short after {wait_seconds:g}s: {problem}', file=sys.stderr)
                return BUSY
            time.sleep(poll)
            continue
        fds = _take(directory, slots, weight)
        if fds is not None:
            owner = json.dumps({'pid': os.getpid(), 'cwd': os.getcwd(), 'cmd': command, 'weight': weight,
                                'utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}).encode()
            for fd in fds:
                os.ftruncate(fd, 0)
                os.write(fd, owner)
            try:
                return _supervise(command, poll)
            finally:
                for fd in fds:
                    os.close(fd)
        if not waiting:
            print('test-slot: all slots busy, waiting; holders:\n' + '\n'.join(_holders(directory, slots)),
                  file=sys.stderr)
            waiting = True
        if time.monotonic() >= deadline:
            print(f'test-slot: busy after {wait_seconds}s; holders:\n' + '\n'.join(_holders(directory, slots)),
                  file=sys.stderr)
            return BUSY
        time.sleep(poll)
