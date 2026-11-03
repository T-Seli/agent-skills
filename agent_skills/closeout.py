"""Read-only handoff/completion and merged worktree cleanup eligibility."""
import fcntl
import filecmp
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from .task_contract import assess_completion, resume_check


def handoff_gate(packet, saved, *, current_revision, sources_fresh, canceled=False):
    return resume_check(packet, saved, current_revision=current_revision,
                        sources_fresh=sources_fresh, canceled=canceled)


def completion_gate(packet, report, *, verifier_report=None, artifact_root=None,
                    owner_verified=False, human_accepted=False):
    evidence = assess_completion(packet, report, verifier_report, artifact_root=artifact_root)
    if evidence["status"] != "evidence-complete-awaiting-acceptance":
        return {**evidence, "decision": "hold"}
    if not owner_verified or not human_accepted:
        return {**evidence, "decision": "await-owner-or-human-acceptance"}
    return {**evidence, "decision": "accepted"}


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _deploy_lock(root):
    return Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "deploy.lock"


def main_sync_gate(main, *, base, repository, fetched_sha, lock_path):
    """Verify an exact, freshly fetched clean main without pulling or activating it."""
    if (not isinstance(base, str) or not base or not isinstance(repository, str) or not repository or
            not isinstance(fetched_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", fetched_sha)):
        return {"ready": False, "reason": "exact repository, base and fetched SHA required"}
    try:
        main = Path(main).resolve(strict=True)
        if Path(_git(main, "rev-parse", "--show-toplevel")) != main:
            raise ValueError("main checkout root mismatch")
        remote = _git(main, "remote", "get-url", "origin")
        if not re.search(rf"(?:[:/]){re.escape(repository)}(?:\.git)?$", remote):
            raise ValueError("origin repository mismatch")
        if _git(main, "symbolic-ref", "--short", "HEAD") != base:
            raise ValueError("main checkout branch mismatch")
        if _git(main, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("main checkout has tracked or non-ignored untracked changes")
        lock = Path(lock_path)
        if lock.resolve(strict=False) != _deploy_lock(main).resolve(strict=False):
            raise ValueError("lock path does not match repository deploy lock")
        if lock.exists() or lock.is_symlink():
            raise ValueError("active or uncertain owner lock")
        remote_commit = _git(main, "rev-parse", "--verify", f"refs/remotes/origin/{base}^{{commit}}")
        local_commit = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
        if remote_commit != fetched_sha:
            raise ValueError("remote base differs from supplied fresh-fetch receipt")
        if local_commit != remote_commit:
            raise ValueError("main is not exactly synchronized; fast-forward only")
        return {"ready": True, "reason": "exact-clean-synchronized", "repository": repository,
                "base": base, "commit": local_commit, "fetched_sha": fetched_sha,
                "activation": "not-performed"}
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {"ready": False, "reason": str(exc)}


def _worktrees(main):
    """Records from `git worktree list`: `path` plus git's own keys (branch, detached, locked, prunable)."""
    records, current = [], None
    for field in _git(main, "worktree", "list", "--porcelain", "-z").split("\0"):
        if field.startswith("worktree "):
            current = {"path": Path(field[9:]).resolve()}
            records.append(current)
        elif current is not None and field:
            key, _, value = field.partition(" ")
            current[key] = value
    return records


def _worktree_lock(main, worktree):
    """None when unlocked, else git's lock reason ('' when none was given)."""
    return next(record.get("locked") for record in _worktrees(main) if record["path"] == worktree)


def _merge_proof(main, base_commit, commit):
    """'ancestor', or 'no-op' when merging commit into base would change nothing (squash merges)."""
    if _git(main, "merge-base", base_commit, commit) == commit:
        return "ancestor"
    merged = subprocess.run(["git", "-C", str(main), "merge-tree", "--write-tree", base_commit, commit],
                            capture_output=True, text=True)
    if merged.returncode == 0 and merged.stdout.split()[0] == _git(main, "rev-parse", f"{base_commit}^{{tree}}"):
        return "no-op"
    raise ValueError("branch not merged into local base")


def _check_clean(main, worktree, rebuildable):
    """Tracked and untracked entries block; ignored ones only if rebuildable or already in main."""
    declared = [item.strip("/") for item in rebuildable]
    for entry in _git(worktree, "--no-optional-locks", "status", "--porcelain", "-z", "--ignored").split("\0"):
        if not entry:
            continue
        if not entry.startswith("!! "):
            raise ValueError("worktree dirty")
        path = entry[3:]
        name = path.rstrip("/")
        if any(name == item or name.startswith(item + "/") for item in declared):
            continue
        item = worktree / name
        if item.is_symlink() and item.resolve().is_relative_to(main):
            continue
        twin = main / name
        if not path.endswith("/") and twin.is_file() and filecmp.cmp(item, twin, shallow=False):
            continue
        raise ValueError(f"ignored content not rebuildable: {path}")


def cleanup_gate(main, worktree, *, base, completion_accepted, no_pending_effects, branch=None,
                 lock_path=None, expected_lock_owner=None, remote_base=None, rebuildable=(), run_id=None):
    """Never deletes. Exact branch/worktree and merged, clean state must all agree.

    `branch=None` checks a detached worktree (temp base checkouts) at its HEAD commit."""
    if not completion_accepted or not no_pending_effects:
        return {"eligible": False, "reason": "completion-or-effects-pending"}
    try:
        main, worktree = Path(main).resolve(strict=True), Path(worktree).resolve(strict=True)
        if main == worktree or Path(_git(main, "rev-parse", "--show-toplevel")) != main:
            raise ValueError("invalid main/worktree")
        if _git(worktree, "rev-parse", "--show-toplevel") != str(worktree):
            raise ValueError("worktree root mismatch")
        if branch is None:
            if subprocess.run(["git", "-C", str(worktree), "symbolic-ref", "-q", "HEAD"],
                              capture_output=True).returncode == 0:
                raise ValueError("worktree is not detached")
        elif _git(worktree, "symbolic-ref", "--short", "HEAD") != branch:
            raise ValueError("branch mismatch")
        if branch == base or _git(main, "symbolic-ref", "--short", "HEAD") != base:
            raise ValueError("base checkout mismatch")
        _check_clean(main, worktree, rebuildable)
        if _git(main, "rev-parse", "--path-format=absolute", "--git-common-dir") != _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"):
            raise ValueError("unrelated repositories")
        base_commit = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
        branch_commit = (_git(worktree, "rev-parse", "HEAD") if branch is None else
                         _git(main, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}"))
        merge = _merge_proof(main, base_commit, branch_commit)
        reason = _worktree_lock(main, worktree)
        if reason is not None and not set(reason.split()) & {name for name in (branch, run_id) if name}:
            raise ValueError("worktree locked by another owner")
        if remote_base is not None and base_commit != remote_base:
            raise ValueError("local base does not match freshly fetched remote base")
        if (lock_path is None) != (expected_lock_owner is None):
            raise ValueError("lock path and exact expected owner must be paired")
        if lock_path is not None:
            lock = Path(lock_path)
            if lock.resolve(strict=False) != _deploy_lock(main).resolve(strict=False):
                raise ValueError("lock path does not match repository deploy lock")
            owner = lock / "owner"
            if lock.is_symlink() or owner.is_symlink() or not owner.is_file():
                raise ValueError("lock ownership unavailable")
            if owner.read_text(encoding="utf-8").strip() != expected_lock_owner:
                raise ValueError("lock owned by another operation")
        return {"eligible": True, "reason": "review-only", "worktree": str(worktree),
                "branch": branch, "base_commit": base_commit, "branch_commit": branch_commit,
                "merge": merge, "unlock": reason is not None}
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {"eligible": False, "reason": str(exc)}


@contextmanager
def _sweep_lock(main):
    common = Path(_git(main, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    fd = os.open(common / "sweep.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _process_cwds():
    listed = subprocess.run(["lsof", "-d", "cwd", "-Fn"], capture_output=True, text=True)
    if listed.returncode and not listed.stdout:
        raise RuntimeError(f"lsof failed: {listed.stderr.strip()}")
    return {Path(line[1:]).resolve() for line in listed.stdout.splitlines() if line.startswith("n")}


def _inside(path, root):
    return path == root or root in path.parents


def _held(worktree, cwds, leased, *, active_seconds, now):
    """Why a live session may be using this worktree, else None."""
    if any(_inside(cwd, worktree) for cwd in cwds):
        return "a process has its cwd inside"
    if any(_inside(path, worktree) for path in leased):
        return "listed in a lease file"
    gitdir = Path(_git(worktree, "rev-parse", "--absolute-git-dir"))
    for name in ("index", "logs/HEAD"):
        try:
            age = now - (gitdir / name).stat().st_mtime
        except FileNotFoundError:
            continue
        if age < active_seconds:
            return f"git activity {int(age)}s ago"
    return None


def sweep(main, *, base, apply=False, rebuildable=(), lease_files=(), active_seconds=7200, now=None):
    """Run the cleanup gate over every other worktree; with `apply`, remove (never force) the eligible,
    unheld ones and delete a branch only when its merge proof is `ancestor`."""
    main = Path(main).resolve(strict=True)
    now = time.time() if now is None else now
    leased = [Path(line.strip()).expanduser().resolve() for name in lease_files
              for line in Path(name).expanduser().read_text(encoding="utf-8").splitlines() if line.strip()]
    report = {"apply": apply, "candidates": [], "held": [], "kept": [], "removed": []}
    with _sweep_lock(main):
        cwds = _process_cwds()
        for record in _worktrees(main):
            worktree = record["path"]
            if worktree == main:
                continue
            branch = record.get("branch", "").removeprefix("refs/heads/") or None
            if not worktree.exists():
                report["kept"].append({"worktree": str(worktree), "reason": "path missing; git worktree prune"})
                continue
            if branch is None and not worktree.name.startswith("_base-"):
                report["kept"].append({"worktree": str(worktree), "reason": "detached and not a temp base"})
                continue
            reason = _held(worktree, cwds, leased, active_seconds=active_seconds, now=now)
            if reason:
                report["held"].append({"worktree": str(worktree), "reason": reason})
                continue
            parts = worktree.name.split("-", 2)
            verdict = cleanup_gate(main, worktree, base=base, branch=branch, completion_accepted=True,
                                   no_pending_effects=True, rebuildable=rebuildable,
                                   run_id=parts[2] if branch is None and len(parts) == 3 else None)
            if not verdict["eligible"]:
                report["kept"].append({"worktree": str(worktree), "reason": verdict["reason"]})
                continue
            report["candidates"].append({"worktree": str(worktree), "branch": branch,
                                         "merge": verdict["merge"], "unlock": verdict["unlock"]})
            if apply:
                if verdict["unlock"]:
                    _git(main, "worktree", "unlock", str(worktree))
                _git(main, "worktree", "remove", str(worktree))
                if branch and verdict["merge"] == "ancestor":
                    _git(main, "branch", "-d", branch)
                report["removed"].append(str(worktree))
    return report
