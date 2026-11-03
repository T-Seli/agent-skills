"""Machine-wide cap on concurrent test suites: N flock slot files, held by the exec'd command."""
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BUSY = 75  # exit status: no slot freed in time; not a test failure
DEFAULT_SLOTS = 2


def slot_dir():
    return Path(os.environ.get('AGENT_SKILLS_TEST_SLOTS', '~/.local/state/agent-skills/test-slots')).expanduser()


def configured_slots(config):
    if 'test_slots' not in config:
        return DEFAULT_SLOTS, 'default'
    value = config['test_slots']
    if type(value) is not int or value < 1:
        raise ValueError(f'test_slots must be an integer >= 1, got {value!r}')
    return value, 'config'


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


def run_in_slot(command, *, slots, wait_seconds, poll=0.2):
    """Exec `command` holding a slot (the slot frees when the process dies); BUSY after wait_seconds."""
    directory = slot_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + wait_seconds
    waiting = False
    while True:
        for index in range(slots):
            fd = _try_lock(directory, index)
            if fd is not None:
                owner = {'pid': os.getpid(), 'cwd': os.getcwd(), 'cmd': command,
                         'utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
                os.ftruncate(fd, 0)
                os.write(fd, json.dumps(owner).encode())
                os.set_inheritable(fd, True)
                os.execvp('/bin/sh', ['sh', '-c', command])
        if not waiting:
            print('test-slot: all slots busy, waiting; holders:\n' + '\n'.join(_holders(directory, slots)),
                  file=sys.stderr)
            waiting = True
        if time.monotonic() >= deadline:
            print(f'test-slot: busy after {wait_seconds}s; holders:\n' + '\n'.join(_holders(directory, slots)),
                  file=sys.stderr)
            return BUSY
        time.sleep(poll)
