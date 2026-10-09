"""Read-only handoff/completion and merged worktree cleanup eligibility."""
import re
import subprocess
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
        if _git(main, "status", "--porcelain", "--untracked-files=all", "--ignored"):
            raise ValueError("main checkout is not fully clean")
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


def cleanup_gate(main, worktree, *, base, branch, completion_accepted, no_pending_effects,
                 lock_path=None, expected_lock_owner=None, remote_base=None):
    """Never deletes. Exact branch/worktree and merged, clean state must all agree."""
    if not completion_accepted or not no_pending_effects:
        return {"eligible": False, "reason": "completion-or-effects-pending"}
    try:
        main, worktree = Path(main).resolve(strict=True), Path(worktree).resolve(strict=True)
        if main == worktree or Path(_git(main, "rev-parse", "--show-toplevel")) != main:
            raise ValueError("invalid main/worktree")
        if _git(worktree, "rev-parse", "--show-toplevel") != str(worktree):
            raise ValueError("worktree root mismatch")
        if _git(worktree, "symbolic-ref", "--short", "HEAD") != branch:
            raise ValueError("branch mismatch")
        if branch == base or _git(main, "symbolic-ref", "--short", "HEAD") != base:
            raise ValueError("base checkout mismatch")
        if _git(worktree, "status", "--porcelain", "--untracked-files=all", "--ignored"):
            raise ValueError("worktree dirty")
        if _git(main, "rev-parse", "--path-format=absolute", "--git-common-dir") != _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"):
            raise ValueError("unrelated repositories")
        base_commit = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
        branch_commit = _git(main, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
        if _git(main, "merge-base", base_commit, branch_commit) != branch_commit:
            raise ValueError("branch not merged into local base")
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
                "branch": branch, "base_commit": base_commit, "branch_commit": branch_commit}
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {"eligible": False, "reason": str(exc)}
