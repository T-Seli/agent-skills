"""Free space on the volume holding a path, against the `Worktree start free` floor."""
import math
import os

GB = 1024 ** 3
EXIT_OK, EXIT_STOP = 0, 20
KEY = 'worktree_start_free_gb'  # machine-config form of workspace-and-train.md `Worktree start free`
DEFAULT_FLOOR_GB = 10


def floor(config):
    value = config.get(KEY, DEFAULT_FLOOR_GB)
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{KEY} must be a finite number >= 0, got {value!r}')
    return value


def volume_path(path):
    """Resolve symlinks, then walk up to the nearest ancestor that exists: a worktree not yet created lives on its parent's volume."""
    current = os.path.realpath(path)
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            raise ValueError(f'no existing ancestor for {path}')
        current = parent
    return current


def check(path, config):
    """(exit code, one-line report) for the volume holding path (or its nearest existing ancestor); below the floor start nothing."""
    limit = floor(config)
    where = volume_path(path)
    stat = os.statvfs(where)
    free = stat.f_bavail * stat.f_frsize / GB
    state, code = ('stop', EXIT_STOP) if free < limit else ('ok', EXIT_OK)
    return code, f'disk {state}: {free:.1f} GB free on {where} (Worktree start free floor {limit:g} GB)'
