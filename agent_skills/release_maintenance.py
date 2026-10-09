"""Approval-bound release maintenance actions with explicit lifecycle receipts."""

import hashlib
import json
import os
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
                                 "--no-overwrite-ignore", fetched],
                                capture_output=True, text=True)
        if merged.returncode != 0:
            raise ValueError("fast-forward refused to preserve working content")

    _lock_owner(lock, owner)
    _clean_without_ignored(main)
    after = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
    if after != fetched:
        raise RuntimeError("post-fast-forward local identity mismatch")
    remote_after = _git(main, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    synchronized = remote_after == fetched
    return {
        "action": "fast-forward-main",
        "result": (("already-current" if local == fetched else "fast-forwarded")
                   if synchronized else "approved-commit-landed-remote-advanced"),
        "repository": repository,
        "base": base,
        "before": local,
        "after": after,
        "fetched_sha": fetched,
        "remote_after": remote_after,
        "synchronized": synchronized,
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


def _release_entries(root):
    entries = set()
    for current, directories, files in os.walk(root, followlinks=False):
        current = Path(current)
        for name in [*directories, *files]:
            entries.add((current / name).relative_to(root).as_posix())
    return entries


def _verify_release_root(release, source, desired):
    if source.is_symlink():
        raise ValueError("source checkout must not be a symlink")
    source = source.resolve(strict=True)
    if Path(_git(source, "rev-parse", "--show-toplevel")) != source:
        raise ValueError("source checkout root mismatch")
    if not _repository_matches(_git(source, "remote", "get-url", "origin"), desired["source"]):
        raise ValueError("source checkout repository mismatch")
    if (_git(source, "rev-parse", "HEAD^{commit}") != desired["commit"] or
            _git(source, "rev-parse", "HEAD^{tree}") != desired["tree"]):
        raise ValueError("source checkout differs from approved commit and tree")
    _clean_without_ignored(source)

    raw = subprocess.run(["git", "-C", str(source), "ls-files", "-s", "-z"],
                         check=True, capture_output=True, text=True).stdout
    tracked = {}
    for record in raw.split("\0"):
        if not record:
            continue
        metadata, name = record.split("\t", 1)
        mode = metadata.split(" ", 1)[0]
        if mode not in {"100644", "100755", "120000"}:
            raise ValueError("unsupported tracked entry in approved release")
        tracked[name] = mode
    expected_entries = {".release-pin.json"}
    for name in tracked:
        path = Path(name)
        expected_entries.add(path.as_posix())
        expected_entries.update(parent.as_posix() for parent in path.parents
                                if parent.as_posix() != ".")
    if _release_entries(release) != expected_entries:
        raise ValueError("release contents differ from the approved tracked tree")
    for name, mode in tracked.items():
        source_path, release_path = source / name, release / name
        if mode == "120000":
            if (not source_path.is_symlink() or not release_path.is_symlink() or
                    os.readlink(source_path) != os.readlink(release_path)):
                raise ValueError("release symlink differs from the approved tracked tree")
        else:
            if (source_path.is_symlink() or release_path.is_symlink() or
                    not source_path.is_file() or not release_path.is_file() or
                    hashlib.sha256(source_path.read_bytes()).digest() !=
                    hashlib.sha256(release_path.read_bytes()).digest() or
                    bool(source_path.stat().st_mode & 0o111) != bool(release_path.stat().st_mode & 0o111)):
                raise ValueError("release file differs from the approved tracked tree")
    return source


def _activate(manifest, state, reconciliation, parameters, desired, runner):
    value = _exact_dict(parameters,
                        {"release_root", "source_checkout", "target", "safe_checkpoint_ref"},
                        "local activation parameters")
    target = value["target"]
    if target not in _TARGET_ADAPTERS:
        raise ValueError("invalid installer target")
    checkpoint_ref = _text(value["safe_checkpoint_ref"], "safe checkpoint receipt")
    selected = _installer_targets(manifest, reconciliation, target)
    for item in reconciliation["drift"]:
        active_loaded_pin = (item["target"] in selected and
                             state["targets"][item["target"]]["active_task"] and
                             item["dimension"] in {"loaded", "behavior_verified"})
        if not (item["target"] in selected and item["dimension"] == "installed") and not active_loaded_pin:
            raise ValueError("unrelated or inactive runtime-loaded drift blocks automatic activation")
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
    source = _verify_release_root(release, Path(value["source_checkout"]), desired)
    rollback_refs = {target_id: state["targets"][target_id]["rollback_ref"]
                     for target_id in selected}
    if any(not isinstance(ref, str) or not ref.strip() for ref in rollback_refs.values()):
        raise ValueError("every selected runtime needs rollback provenance")
    run = runner([str(installer), f"--target={target}"], cwd=str(release),
                 capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError("transactional installer failed; inspect its retained failure receipt")
    rollback_receipt = None
    no_changes = False
    for line in run.stdout.splitlines():
        if line.startswith("rollback receipt: "):
            rollback_receipt = line.split(": ", 1)[1]
        if line == "install transaction: no changes":
            no_changes = True
    if rollback_receipt is None and not no_changes:
        raise RuntimeError("installer completion provenance unavailable; reconcile before retry")
    return {
        "action": "activate-local-release",
        "result": "activation-performed-awaiting-post-activation-reconciliation",
        "release_root": str(release),
        "verified_source_checkout": str(source),
        "target": target,
        "selected_targets": selected,
        "safe_checkpoint_ref": checkpoint_ref,
        "rollback_refs": rollback_refs,
        "installer_rollback_receipt": rollback_receipt,
        "installer_no_changes": no_changes,
        "active_sessions_preserved": [target_id for target_id in selected
                                      if state["targets"][target_id]["active_task"]],
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
        "post_action_reconciliation_required": (
            approval["action"] == "activate-local-release" or
            not action.get("synchronized", True)),
        "system_wide_claim": False,
        "scheduler_created": False,
    }
