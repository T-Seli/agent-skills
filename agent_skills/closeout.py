"""Read-only handoff/completion and merged worktree cleanup eligibility."""
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


def cleanup_gate(main, worktree, *, base, branch, completion_accepted, no_pending_effects):
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
        if _git(worktree, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("worktree dirty")
        if _git(main, "rev-parse", "--path-format=absolute", "--git-common-dir") != _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"):
            raise ValueError("unrelated repositories")
        base_commit = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
        branch_commit = _git(main, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
        if _git(main, "merge-base", base_commit, branch_commit) != branch_commit:
            raise ValueError("branch not merged into local base")
        return {"eligible": True, "reason": "review-only", "worktree": str(worktree),
                "branch": branch, "base_commit": base_commit, "branch_commit": branch_commit}
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {"eligible": False, "reason": str(exc)}
