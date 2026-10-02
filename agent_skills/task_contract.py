"""Pure task packets and milestone checks; no dispatch, polling, or external writes."""
import hashlib
import json
import re

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MILESTONES = {"blocker-cleared", "verified-commit", "verified-deploy",
              "scope-changed", "monitor-verdict", "completion"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _words(values, name, *, nonempty=False):
    if not isinstance(values, list) or (nonempty and not values) or not all(
            isinstance(x, str) and x.strip() and "\n" not in x for x in values):
        raise ValueError(f"{name} must be a short string list")


def packet(*, task_id, revision, owner, scope, exclusions, baseline, deliverables,
           acceptance, context_refs, source_hashes, package_hashes,
           stop_conditions, escalation_conditions):
    """One accountable execution owner and exact, reviewable scope."""
    if (not isinstance(task_id, str) or not ID.fullmatch(task_id) or type(revision) is not int
            or revision < 1 or not isinstance(owner, str) or not ID.fullmatch(owner)
            or not isinstance(scope, str) or not scope.strip() or not isinstance(baseline, str)
            or not baseline.strip()):
        raise ValueError("task id, revision, owner, scope and baseline required")
    for name, values, required in (("exclusions", exclusions, False), ("deliverables", deliverables, True),
                                   ("context_refs", context_refs, False), ("stop_conditions", stop_conditions, True),
                                   ("escalation_conditions", escalation_conditions, True)):
        _words(values, name, nonempty=required)
    if (not isinstance(acceptance, list) or not acceptance or
            any(not isinstance(x, dict) or set(x) != {"id", "check"} or
                not isinstance(x["id"], str) or not ID.fullmatch(x["id"]) or
                not isinstance(x["check"], str) or not x["check"].strip() for x in acceptance) or
            len({x["id"] for x in acceptance}) != len(acceptance)):
        raise ValueError("unique acceptance criteria required")
    for hashes in (source_hashes, package_hashes):
        if not isinstance(hashes, dict) or not hashes or not all(
                isinstance(k, str) and k and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
                for k, v in hashes.items()):
            raise ValueError("pinned source hashes required")
    value = {"task_id": task_id, "revision": revision, "execution_owner": owner,
             "scope": scope, "exclusions": exclusions, "target_baseline": baseline,
             "deliverables": deliverables, "acceptance": acceptance,
             "context_refs": context_refs, "source_hashes": source_hashes,
             "package_hashes": package_hashes, "stop_conditions": stop_conditions,
             "escalation_conditions": escalation_conditions, "dispatch": "prepared"}
    return {**value, "packet_sha256": digest(value)}


def validate_packet(value):
    try:
        rebuilt = packet(task_id=value["task_id"], revision=value["revision"],
                         owner=value["execution_owner"], scope=value["scope"],
                         exclusions=value["exclusions"], baseline=value["target_baseline"],
                         deliverables=value["deliverables"], acceptance=value["acceptance"],
                         context_refs=value["context_refs"], source_hashes=value["source_hashes"],
                         package_hashes=value["package_hashes"], stop_conditions=value["stop_conditions"],
                         escalation_conditions=value["escalation_conditions"])
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid task packet") from exc
    if value != rebuilt:
        raise ValueError("packet changed after pinning")
    return True


def checkpoint(value, *, next_safe_action, uncertain_side_effects, sources_fresh):
    validate_packet(value)
    _words(uncertain_side_effects, "uncertain_side_effects")
    if (not isinstance(next_safe_action, str) or not next_safe_action.strip() or
            type(sources_fresh) is not bool):
        raise ValueError("checkpoint action and freshness required")
    if uncertain_side_effects and next_safe_action != "reconcile":
        raise ValueError("uncertain effects require reconciliation before retry")
    saved = {"task_id": value["task_id"], "revision": value["revision"],
             "packet_sha256": value["packet_sha256"],
             "bundle_sha256": digest({"source_hashes": value["source_hashes"],
                                      "package_hashes": value["package_hashes"]}),
             "next_safe_action": next_safe_action,
             "uncertain_side_effects": uncertain_side_effects, "sources_fresh": sources_fresh}
    return {**saved, "checkpoint_sha256": digest(saved)}


def validate_checkpoint(value, saved):
    validate_packet(value)
    keys = {"task_id", "revision", "packet_sha256", "bundle_sha256",
            "next_safe_action", "uncertain_side_effects", "sources_fresh", "checkpoint_sha256"}
    if not isinstance(saved, dict) or set(saved) != keys:
        raise ValueError("invalid checkpoint fields")
    if (saved["task_id"] != value["task_id"] or type(saved["revision"]) is not int or
            saved["revision"] != value["revision"] or
            saved["packet_sha256"] != value["packet_sha256"] or
            saved["bundle_sha256"] != digest({"source_hashes": value["source_hashes"],
                                              "package_hashes": value["package_hashes"]})):
        raise ValueError("checkpoint task, revision or bundle changed")
    if (not isinstance(saved["next_safe_action"], str) or
            not saved["next_safe_action"].strip() or type(saved["sources_fresh"]) is not bool):
        raise ValueError("invalid checkpoint action or freshness")
    _words(saved["uncertain_side_effects"], "uncertain_side_effects")
    if saved["uncertain_side_effects"] and saved["next_safe_action"] != "reconcile":
        raise ValueError("uncertain effects require reconciliation")
    if saved["checkpoint_sha256"] != digest({key: saved[key] for key in keys
                                             if key != "checkpoint_sha256"}):
        raise ValueError("checkpoint changed after pinning")
    return True


def resume_check(value, saved, *, current_revision, sources_fresh, canceled=False):
    validate_packet(value)
    try:
        validate_checkpoint(value, saved)
    except ValueError:
        return {"decision": "hold-and-reconcile"}
    if (type(current_revision) is not int or type(sources_fresh) is not bool or
            type(canceled) is not bool or canceled or current_revision != value["revision"] or
            not sources_fresh or not saved["sources_fresh"] or saved["uncertain_side_effects"]):
        return {"decision": "hold-and-reconcile"}
    return {"decision": "eligible-for-owner-review", "next_safe_action": saved["next_safe_action"]}


def assess_completion(value, report):
    """Evidence complete is not human acceptance, deployment, or verified live behavior."""
    validate_packet(value)
    if (report.get("task_id"), report.get("revision"), report.get("packet_sha256")) != (
            value["task_id"], value["revision"], value["packet_sha256"]):
        return {"status": "stale-or-foreign", "missing": []}
    evidence = report.get("criterion_evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    missing = []
    for criterion in value["acceptance"]:
        item = evidence.get(criterion["id"])
        if not isinstance(item, dict) or not all(item.get(k) for k in (
                "reference", "check_result", "commit", "environment")) or item.get("check_result") != "pass":
            missing.append(criterion["id"])
    return {"status": "evidence-complete-awaiting-acceptance" if not missing else "claimed-unverified",
            "missing": missing, "unverified_limits": report.get("unverified_limits", [])}


def milestone(value, *, event_id, kind, reported_status, verified_status, evidence_refs):
    validate_packet(value)
    if not isinstance(event_id, str) or not ID.fullmatch(event_id) or kind not in MILESTONES:
        raise ValueError("stable event id and known milestone kind required")
    _words(evidence_refs, "evidence_refs")
    if not isinstance(reported_status, str) or not reported_status:
        raise ValueError("reported status required")
    if verified_status not in ("unverified", "verified", "rejected"):
        raise ValueError("separate verification status required")
    return {"event_id": event_id, "task_id": value["task_id"], "revision": value["revision"],
            "packet_sha256": value["packet_sha256"], "kind": kind,
            "reported_status": reported_status, "verified_status": verified_status,
            "evidence_refs": evidence_refs}


def consume_milestone(current, event):
    """Pure orchestrator projection; a current owner must verify real events."""
    if (event.get("task_id") != current.get("task_id") or
            event.get("revision") != current.get("revision") or
            event.get("packet_sha256") != current.get("packet_sha256")):
        return current, "stale-or-foreign"
    if event.get("event_id") in current.get("seen", []):
        return current, "duplicate"
    updated = {**current, "seen": [*current.get("seen", []), event["event_id"]],
               "last_milestone": event}
    return updated, ("owner-check-needed" if event.get("verified_status") != "verified" else "recorded")
