"""Pure release-target reconciliation; never installs, fetches, restarts or publishes."""
import re


CHECKPOINTS = {"task-entry", "resume", "reconnect", "pre-activation", "post-activation"}
ACTIVATIONS = {"native-installer", "manual-republish", "unsupported"}
OBSERVATION_STATES = {"verified", "pending", "unknown", "unavailable"}
_SHA = re.compile(r"[0-9a-f]{40}", re.ASCII)


def _identity(value):
    if not isinstance(value, dict) or set(value) != {"source", "commit", "tree"}:
        raise ValueError("desired release identity requires source, commit and tree")
    if not isinstance(value["source"], str) or not value["source"].strip():
        raise ValueError("desired release source required")
    if (not isinstance(value["commit"], str) or not isinstance(value["tree"], str) or
            not _SHA.fullmatch(value["commit"]) or not _SHA.fullmatch(value["tree"])):
        raise ValueError("desired release requires full immutable commit and tree")
    return dict(value)


def _targets(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "targets"}:
        raise ValueError("invalid release target manifest")
    if manifest["schema_version"] != 1 or not isinstance(manifest["targets"], list) or not manifest["targets"]:
        raise ValueError("release target manifest requires targets")
    targets = {}
    fields = {"id", "adapter", "runtime", "activation", "required", "manual_action", "unsupported_reason"}
    for target in manifest["targets"]:
        if not isinstance(target, dict) or set(target) != fields:
            raise ValueError("invalid declared target")
        target_id = target["id"]
        if not isinstance(target_id, str) or not target_id or target_id in targets:
            raise ValueError("unique target id required")
        if not all(isinstance(target[key], str) and target[key].strip()
                   for key in ("adapter", "runtime")):
            raise ValueError("target adapter and runtime required")
        if target["activation"] not in ACTIVATIONS or type(target["required"]) is not bool:
            raise ValueError("invalid target activation")
        if (target["activation"] == "manual-republish" and
                (not isinstance(target["manual_action"], str) or not target["manual_action"].strip())):
            raise ValueError("manual target requires exact action")
        if (target["activation"] == "unsupported" and
                (not isinstance(target["unsupported_reason"], str) or not target["unsupported_reason"].strip())):
            raise ValueError("unsupported target requires reason")
        if target["activation"] != "manual-republish" and target["manual_action"] is not None:
            raise ValueError("manual action only applies to manual targets")
        if target["activation"] != "unsupported" and target["unsupported_reason"] is not None:
            raise ValueError("unsupported reason only applies to unsupported targets")
        targets[target_id] = dict(target)
    return targets


def _observation(value, desired, *, dimension, checkpoint, current_session_id, expected_body_sha256):
    fields = {"state", "commit", "tree", "receipt_ref", "session_id", "body_sha256", "checkpoint"}
    if not isinstance(value, dict) or set(value) != fields or value.get("state") not in OBSERVATION_STATES:
        raise ValueError("invalid release observation")
    if value["state"] == "verified":
        if (not isinstance(value.get("commit"), str) or not isinstance(value.get("tree"), str) or
                not _SHA.fullmatch(value["commit"]) or not _SHA.fullmatch(value["tree"])):
            raise ValueError("verified observation requires immutable commit and tree")
        if not isinstance(value.get("receipt_ref"), str) or not value["receipt_ref"].strip():
            raise ValueError("verified observation requires receipt")
        state = "match" if (value["commit"], value["tree"]) == (desired["commit"], desired["tree"]) else "drift"
        if value.get("checkpoint") != checkpoint:
            state = "stale-receipt"
        if dimension == "installed":
            if value.get("session_id") is not None or value.get("body_sha256") is not None:
                state = "stale-receipt"
        elif (value.get("session_id") != current_session_id or
              value.get("body_sha256") != expected_body_sha256):
            state = "stale-receipt"
    else:
        if any(value.get(key) is not None for key in ("commit", "tree", "session_id", "body_sha256", "checkpoint")):
            raise ValueError("unverified observation cannot claim release identity")
        if value.get("receipt_ref") is not None and (not isinstance(value["receipt_ref"], str) or not value["receipt_ref"].strip()):
            raise ValueError("invalid observation receipt")
        state = value["state"]
    return {**value, "reconciled_state": state}


def reconcile_release(manifest, state):
    """Reconcile one approved release across an exact target set at a lifecycle checkpoint."""
    declared = _targets(manifest)
    fields = {"schema_version", "checkpoint", "desired", "targets"}
    if not isinstance(state, dict) or set(state) != fields or state.get("schema_version") != 1:
        raise ValueError("invalid release reconciliation state")
    if state["checkpoint"] not in CHECKPOINTS:
        raise ValueError("unsupported reconciliation checkpoint")
    desired = _identity(state["desired"])
    if not isinstance(state["targets"], dict) or set(state["targets"]) != set(declared):
        raise ValueError("observations must match the declared target set exactly")

    results, drift, exceptions, actions = {}, [], [], []
    observation_fields = {"active_task", "rollback_ref", "current_session_id", "expected_body_sha256",
                          "installed", "loaded", "behavior_verified"}
    for target_id, target in declared.items():
        value = state["targets"][target_id]
        if not isinstance(value, dict) or set(value) != observation_fields or type(value["active_task"]) is not bool:
            raise ValueError("invalid target observation")
        if not isinstance(value["current_session_id"], str) or not value["current_session_id"].strip():
            raise ValueError("current target session required")
        body = value["expected_body_sha256"]
        if target["activation"] == "unsupported":
            if body is not None:
                raise ValueError("unsupported target cannot claim expected body")
        elif not isinstance(body, str) or not re.fullmatch(r"[0-9a-f]{64}", body):
            raise ValueError("expected runtime body SHA-256 required")
        rollback_ready = isinstance(value["rollback_ref"], str) and bool(value["rollback_ref"].strip())
        dimensions = {name: _observation(
            value[name], desired, dimension=name, checkpoint=state["checkpoint"],
            current_session_id=value["current_session_id"], expected_body_sha256=body)
                      for name in ("installed", "loaded", "behavior_verified")}
        for name, observation in dimensions.items():
            if observation["reconciled_state"] == "drift":
                drift.append({"target": target_id, "dimension": name,
                              "observed_commit": observation["commit"], "observed_tree": observation["tree"]})

        ready = (target["activation"] != "unsupported" and rollback_ready and
                 all(item["reconciled_state"] == "match" for item in dimensions.values()))
        safe_continuation = bool(value["active_task"] and
                                 dimensions["loaded"]["reconciled_state"] != "match")
        next_action = None
        if target["activation"] == "unsupported":
            exceptions.append({"target": target_id, "kind": "unsupported",
                               "reason": target["unsupported_reason"], "required": target["required"]})
        elif not rollback_ready:
            next_action = "capture-rollback-before-mutation"
        elif dimensions["installed"]["reconciled_state"] != "match":
            next_action = (target["manual_action"] if target["activation"] == "manual-republish"
                           else "install-approved-release-at-safe-checkpoint")
        elif safe_continuation:
            next_action = "continue-active-task-on-loaded-pin; use-approved-pin-for-new-workers"
        elif dimensions["loaded"]["reconciled_state"] != "match":
            next_action = "verify-approved-pin-in-a-fresh-runtime"
        elif dimensions["behavior_verified"]["reconciled_state"] != "match":
            next_action = "run-bounded-behavior-verification"
        if next_action:
            actions.append({"target": target_id, "action": next_action})
        if target["activation"] == "manual-republish" and not ready:
            exceptions.append({"target": target_id, "kind": "manual",
                               "reason": target["manual_action"], "required": target["required"]})
        results[target_id] = {
            "adapter": target["adapter"], "runtime": target["runtime"],
            "activation": target["activation"], "required": target["required"],
            "current_session_id": value["current_session_id"],
            "expected_body_sha256": body,
            "desired": desired, "installed": dimensions["installed"],
            "loaded": dimensions["loaded"], "behavior_verified": dimensions["behavior_verified"],
            "rollback_ready": rollback_ready, "active_task": value["active_task"],
            "safe_continuation": safe_continuation, "ready": ready, "next_action": next_action}

    required = [target_id for target_id, target in declared.items() if target["required"]]
    system_wide = all(results[target_id]["ready"] for target_id in required)
    return {"schema_version": 1, "checkpoint": state["checkpoint"], "desired": desired,
            "declared_targets": list(declared), "required_targets": required, "targets": results,
            "drift": drift, "exceptions": exceptions, "actions": actions,
            "active_task_policy": "never-force-restart-or-silently-switch",
            "watch_policy": "no-scheduler-created; reuse-existing-monitor-identity",
            "system_wide": system_wide,
            "claim": "verified-for-declared-target-set" if system_wide else "not-system-wide"}
