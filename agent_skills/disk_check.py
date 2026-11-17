"""Free space on the volume holding a path, against the `Worktree start free` floor."""
import os

GB = 1024 ** 3
EXIT_OK, EXIT_STOP = 0, 20
KEY = 'worktree_start_free_gb'  # machine-config form of workspace-and-train.md `Worktree start free`
DEFAULT_FLOOR_GB = 10


def floor(config):
    value = config.get(KEY, DEFAULT_FLOOR_GB)
    if type(value) not in (int, float) or value < 0:
        raise ValueError(f'{KEY} must be a number >= 0, got {value!r}')
    return value


def check(path, config):
    """(exit code, one-line report) for the volume that holds path; below the floor start nothing."""
    limit = floor(config)
    if not os.path.exists(path):
        raise ValueError(f'no such path: {path}')
    stat = os.statvfs(path)
    free = stat.f_bavail * stat.f_frsize / GB
    state, code = ('stop', EXIT_STOP) if free < limit else ('ok', EXIT_OK)
    return code, f'disk {state}: {free:.1f} GB free on {path} (Worktree start free floor {limit:g} GB)'
