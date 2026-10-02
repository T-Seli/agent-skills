"""Minimal append-only task history, separate from current project documentation."""
import fcntl
import json
import os
import re
import stat
from pathlib import Path

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
KINDS = {"created", "decision", "handoff", "checkpoint", "blocked", "verified", "closed", "superseded"}


def validate(entry):
    if not isinstance(entry, dict) or set(entry) != {"event_id", "task_id", "revision", "at", "kind", "summary", "refs"}:
        raise ValueError("invalid history fields")
    if any(not isinstance(entry[k], str) or not ID.fullmatch(entry[k]) for k in ("event_id", "task_id")):
        raise ValueError("invalid history identity")
    if type(entry["revision"]) is not int or entry["revision"] < 1 or entry["kind"] not in KINDS:
        raise ValueError("invalid revision or kind")
    if not isinstance(entry["at"], str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", entry["at"]):
        raise ValueError("UTC timestamp required")
    if not isinstance(entry["summary"], str) or not entry["summary"].strip() or "\n" in entry["summary"] or len(entry["summary"]) > 240:
        raise ValueError("short one-line summary required")
    if not isinstance(entry["refs"], list) or len(entry["refs"]) > 16 or not all(
            isinstance(x, str) and x and "\n" not in x and len(x) <= 240 for x in entry["refs"]):
        raise ValueError("invalid evidence references")
    return entry


def read(root, task_id):
    if not isinstance(task_id, str) or not ID.fullmatch(task_id):
        raise ValueError("unsafe task id")
    path = Path(root) / f"{task_id}.jsonl"
    if path.is_symlink():
        raise ValueError("history path must not be a symlink")
    if not path.exists():
        return []
    rows = [validate(json.loads(line)) for line in path.read_text().splitlines()]
    if any(row["task_id"] != task_id for row in rows):
        raise ValueError("foreign task in history")
    if len({row["event_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate history event")
    return rows


def append(root, entry):
    validate(entry)
    root = Path(root)
    if root.is_symlink():
        raise ValueError("history root must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError("history root must be private (0700)")
    path = root / f"{entry['task_id']}.jsonl"
    if path.is_symlink() or (root / f"{entry['task_id']}.lock").is_symlink():
        raise ValueError("history files must not be symlinks")
    lock_path = root / f"{entry['task_id']}.lock"
    with os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prior = [row for row in read(root, entry["task_id"]) if row["event_id"] == entry["event_id"]]
        if prior:
            if prior[0] != entry:
                raise ValueError("history event id reused with different content")
            return "duplicate"
        if path.exists() and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("history file must be private (0600)")
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a", encoding="utf-8") as output:
            output.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
            output.flush()
            os.fsync(output.fileno())
        return "appended"
