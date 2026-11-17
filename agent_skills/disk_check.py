"""Free space on the volume holding a path, against the warn and hard-stop floors."""
import os

GB = 1024 ** 3
EXIT_OK, EXIT_WARN, EXIT_STOP = 0, 10, 20
DEFAULT_WARN_GB = 10  # workspace-and-train.md `Worktree start free`
DEFAULT_STOP_GB = 5.4


def floors(config):
    warn, stop = config.get('disk_warn_gb', DEFAULT_WARN_GB), config.get('disk_hard_stop_gb', DEFAULT_STOP_GB)
    for key, value in (('disk_warn_gb', warn), ('disk_hard_stop_gb', stop)):
        if type(value) not in (int, float) or value < 0:
            raise ValueError(f'{key} must be a number >= 0, got {value!r}')
    if stop > warn:
        raise ValueError(f'disk_hard_stop_gb {stop:g} exceeds disk_warn_gb {warn:g}')
    return warn, stop


def check(path, config):
    """(exit code, one-line report) for the volume that holds path."""
    warn, stop = floors(config)
    if not os.path.exists(path):
        raise ValueError(f'no such path: {path}')
    stat = os.statvfs(path)
    free = stat.f_bavail * stat.f_frsize / GB
    state, code = ('stop', EXIT_STOP) if free < stop else ('warn', EXIT_WARN) if free < warn else ('ok', EXIT_OK)
    return code, f'disk {state}: {free:.1f} GB free on {path} (warn below {warn:g} GB, stop below {stop:g} GB)'
