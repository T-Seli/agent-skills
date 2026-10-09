"""Approval-bound release maintenance actions with explicit lifecycle receipts."""

import json
import re
import subprocess
from pathlib import Path

from .release_reconciliation import reconcile_release


_SHA = re.compile(r"[0-9a-f]{40}", re.ASCII)
_ACTIONS = {"fast-forward-main", "activate-local-release"}
_TARGET_ADAPTERS = {
    "codex": {"codex"},
    "claude": {"claude-code"},
    "all": {"codex", "claude-code"},
}


def _git(root, *args, check=True):
    run = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                         text=True, check=check)
    return run.stdout.strip()


def _exact_dict(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"invalid {label}")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} required")
    return value.strip()


def _approval(request, desired):
    approval = _exact_dict(request["approval"],
                           {"ref", "action", "source", "commit", "tree"},
                           "approval binding")
    _text(approval["ref"], "approval reference")
    if approval["action"] not in _ACTIONS:
        raise ValueError("unsupported approved maintenance action")
    if {key: approval[key] for key in ("source", "commit", "tree")} != desired:
        raise ValueError("approval does not bind the desired immutable release")
    return approval


def _admission(request):
    admission = _exact_dict(request["admission"],
                            {"expected_reviewer_mode", "observed_reviewer_mode", "receipt_ref"},
                            "reviewer admission receipt")
    expected = _text(admission["expected_reviewer_mode"], "expected reviewer mode")
    observed = admission["observed_reviewer_mode"]
    receipt = admission["receipt_ref"]
    if observed is None or receipt is None:
        raise ValueError("reviewer mode evidence unavailable")
    if _text(observed, "observed reviewer mode") != expected:
        raise ValueError("observed reviewer mode differs from approved expectation")
    _text(receipt, "reviewer mode receipt")
    return {**admission, "verified": True}


def _repository_matches(remote, repository):
    return bool(re.search(rf"(?:[:/]){re.escape(repository)}(?:\.git)?$", remote))


def _lock_owner(lock, expected):
    owner = lock / "owner"
    if lock.is_symlink() or not lock.is_dir() or owner.is_symlink() or not owner.is_file():
        raise ValueError("deploy lock ownership unavailable")
    if owner.read_text(encoding="utf-8").strip() != expected:
        raise ValueError("deploy lock owned by another operation")


def _clean_without_ignored(root):
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("main checkout has tracked or non-ignored untracked changes")


def _fast_forward(parameters, desired):
    value = _exact_dict(parameters,
                        {"main", "base", "repository", "fetched_sha", "lock_path", "lock_owner"},
                        "main fast-forward parameters")
    base = _text(value["base"], "base branch")
    repository = _text(value["repository"], "repository")
    owner = _text(value["lock_owner"], "deploy lock owner")
    fetched = value["fetched_sha"]
    if not isinstance(fetched, str) or not _SHA.fullmatch(fetched) or fetched != desired["commit"]:
        raise ValueError("fresh fetch receipt must equal the approved release commit")
    main = Path(value["main"]).resolve(strict=True)
    if Path(_git(main, "rev-parse", "--show-toplevel")) != main:
        raise ValueError("main checkout root mismatch")
    if _git(main, "symbolic-ref", "--short", "HEAD") != base:
        raise ValueError("main checkout branch mismatch")
    if not _repository_matches(_git(main, "remote", "get-url", "origin"), repository):
        raise ValueError("origin repository mismatch")
    common = Path(_git(main, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    lock = Path(value["lock_path"])
    if lock.resolve(strict=False) != (common / "deploy.lock").resolve(strict=False):
        raise ValueError("lock path does not match repository deploy lock")
    _lock_owner(lock, owner)
    _clean_without_ignored(main)
    remote_ref = f"refs/remotes/origin/{base}"
    remote = _git(main, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    local = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
    if remote != fetched:
        raise ValueError("remote base differs from supplied fresh-fetch receipt")
    ancestor = subprocess.run(["git", "-C", str(main), "merge-base", "--is-ancestor",
                               local, fetched], capture_output=True, text=True)
    if ancestor.returncode != 0:
        raise ValueError("main is not safely fast-forwardable to the approved release")

    # Final pre-mutation race check. Ignored content is neither enumerated nor read.
    _lock_owner(lock, owner)
    _clean_without_ignored(main)
    if _git(main, "rev-parse", "--verify", f"{remote_ref}^{{commit}}") != fetched:
        raise ValueError("remote base changed after preflight")
    if local != fetched:
        merged = subprocess.run(["git", "-C", str(main), "merge", "--ff-only",
                                 "--no-overwrite-ignore", remote_ref],
                                capture_output=True, text=True)
        if merged.returncode != 0:
            raise ValueError("fast-forward refused to preserve working content")

    _lock_owner(lock, owner)
    _clean_without_ignored(main)
    after = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
    if after != fetched or _git(main, "rev-parse", "--verify", f"{remote_ref}^{{commit}}") != fetched:
        raise RuntimeError("post-fast-forward identity mismatch")
    return {
        "action": "fast-forward-main",
        "result": "already-current" if local == fetched else "fast-forwarded",
        "repository": repository,
        "base": base,
        "before": local,
        "after": after,
        "fetched_sha": fetched,
        "lock_owner": owner,
        "ignored_content": "preserved-not-enumerated",
        "activation": "not-performed",
    }


def _installer_targets(manifest, reconciliation, target):
    adapters = _TARGET_ADAPTERS[target]
    selected = [item["id"] for item in manifest["targets"]
                if item["activation"] == "native-installer" and item["adapter"] in adapters]
    if not selected:
        raise ValueError("installer target has no declared native runtime")
    actions = {(item["target"], item["action"]) for item in reconciliation["actions"]}
    for target_id in selected:
        if (target_id, "install-approved-release-at-safe-checkpoint") not in actions:
            raise ValueError("activation was not recommended for every selected runtime")
    return selected


def _activate(manifest, state, reconciliation, parameters, desired, runner):
    value = _exact_dict(parameters, {"release_root", "target", "safe_checkpoint_ref"},
                        "local activation parameters")
    target = value["target"]
    if target not in _TARGET_ADAPTERS:
        raise ValueError("invalid installer target")
    checkpoint_ref = _text(value["safe_checkpoint_ref"], "safe checkpoint receipt")
    selected = _installer_targets(manifest, reconciliation, target)
    if any(item["target"] not in selected or item["dimension"] != "installed"
           for item in reconciliation["drift"]):
        raise ValueError("unrelated or runtime-loaded drift blocks automatic activation")
    release_input = Path(value["release_root"])
    if release_input.is_symlink():
        raise ValueError("release root must not be a symlink")
    release = release_input.resolve(strict=True)
    if release.name != desired["commit"][:7]:
        raise ValueError("release directory does not match approved commit")
    pin = release / ".release-pin.json"
    installer = release / "install.sh"
    if pin.is_symlink() or installer.is_symlink() or not pin.is_file() or not installer.is_file():
        raise ValueError("immutable release pin or installer unavailable")
    if json.loads(pin.read_text(encoding="utf-8")) != desired:
        raise ValueError("immutable release pin differs from approval")
    rollback_refs = {target_id: state["targets"][target_id]["rollback_ref"]
                     for target_id in selected}
    if any(not isinstance(ref, str) or not ref.strip() for ref in rollback_refs.values()):
        raise ValueError("every selected runtime needs rollback provenance")
    run = runner([str(installer), f"--target={target}"], cwd=str(release),
                 capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError("transactional installer failed; inspect its retained failure receipt")
    rollback_receipt = None
    for line in run.stdout.splitlines():
        if line.startswith("rollback receipt: "):
            rollback_receipt = line.split(": ", 1)[1]
    return {
        "action": "activate-local-release",
        "result": "activation-performed-awaiting-post-activation-reconciliation",
        "release_root": str(release),
        "target": target,
        "selected_targets": selected,
        "safe_checkpoint_ref": checkpoint_ref,
        "rollback_refs": rollback_refs,
        "installer_rollback_receipt": rollback_receipt,
        "settings_or_trust_changed": False,
        "restart_performed": False,
    }


def maintain_release(manifest, state, request, *, runner=subprocess.run):
    """Execute exactly one approved maintenance action and return its bounded receipt."""
    _exact_dict(request, {"schema_version", "checkpoint", "approval", "admission", "parameters"},
                "maintenance request")
    if request["schema_version"] != 1 or request["checkpoint"] != state.get("checkpoint"):
        raise ValueError("maintenance request must bind the current lifecycle checkpoint")
    reconciliation = reconcile_release(manifest, state)
    approval = _approval(request, reconciliation["desired"])
    admission = _admission(request)
    if approval["action"] == "fast-forward-main":
        if reconciliation["drift"]:
            raise ValueError("release drift blocks automatic main synchronization")
        action = _fast_forward(request["parameters"], reconciliation["desired"])
    else:
        action = _activate(manifest, state, reconciliation, request["parameters"],
                           reconciliation["desired"], runner)
    return {
        "schema_version": 1,
        "checkpoint": request["checkpoint"],
        "authorization_ref": approval["ref"],
        "desired": reconciliation["desired"],
        "reviewer_admission": admission,
        "action_receipt": action,
        "post_action_reconciliation_required": approval["action"] == "activate-local-release",
        "system_wide_claim": False,
        "scheduler_created": False,
    }
