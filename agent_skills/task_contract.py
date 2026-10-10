"""Pure task packets and milestone checks; no dispatch, polling, or external writes."""
import hashlib
from pathlib import Path
import json
import re
import struct

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MILESTONES = {"blocker-cleared", "verified-commit", "verified-deploy",
              "scope-changed", "monitor-verdict", "completion"}
OUTCOME_STAGES = {"component-tests", "composed-route", "provisioning", "access", "first-login"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _words(values, name, *, nonempty=False):
    if not isinstance(values, list) or (nonempty and not values) or not all(
            isinstance(x, str) and x.strip() and "\n" not in x for x in values):
        raise ValueError(f"{name} must be a short string list")


def _binding(value):
    if not isinstance(value, dict) or not {"surface", "fixture", "environment", "candidate", "artifact_kinds"} <= set(value) or not set(value) <= {
            "surface", "fixture", "environment", "candidate", "artifact_kinds",
            "production_reference_sha256", "coverage_ids", "mounted_entry_points",
            "outcome", "stage", "expected_results"}:
        return False
    outcome_keys = {"outcome", "stage", "expected_results"}
    if outcome_keys & set(value):
        if (not outcome_keys <= set(value) or not isinstance(value["outcome"], str) or
                not value["outcome"].strip() or not isinstance(value["stage"], str) or value["stage"] not in OUTCOME_STAGES or
                not isinstance(value["expected_results"], dict) or not value["expected_results"] or
                not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
                        for k, v in value["expected_results"].items())):
            return False
    if not all(isinstance(value[k], str) and value[k].strip() for k in
               ("surface", "fixture", "environment", "candidate")):
        return False
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value["candidate"]):
        return False
    kinds = value["artifact_kinds"]
    if not isinstance(kinds, list) or not kinds or not all(
            isinstance(k, str) and k.strip() for k in kinds) or len(kinds) != len(set(kinds)):
        return False
    if "coverage_ids" in value:
        ids = value["coverage_ids"]
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x.strip() for x in ids) or len(ids) != len(set(ids)):
            return False
    if "mounted_entry_points" in value:
        points = value["mounted_entry_points"]
        if (not isinstance(points, list) or not points or
                not all(isinstance(x, str) and x.strip() and "\n" not in x for x in points) or
                len(points) != len(set(points))):
            return False
    return "production_reference_sha256" not in value or (
        isinstance(value["production_reference_sha256"], str) and bool(re.fullmatch(
            r"[0-9a-f]{64}", value["production_reference_sha256"])))


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
            any(not isinstance(x, dict) or set(x) not in ({"id", "check"}, {"id", "check", "evidence_binding"}) or
                not isinstance(x["id"], str) or not ID.fullmatch(x["id"]) or
                not isinstance(x["check"], str) or not x["check"].strip() or
                ("evidence_binding" in x and not _binding(x["evidence_binding"])) for x in acceptance) or
            len({x["id"] for x in acceptance}) != len(acceptance)):
        raise ValueError("unique acceptance criteria required")
    outcomes = {}
    for criterion in acceptance:
        binding = criterion.get("evidence_binding") or {}
        if "outcome" in binding:
            identity = (binding["candidate"], binding["environment"])
            if outcomes.setdefault(binding["outcome"], identity) != identity:
                raise ValueError("outcome stages must bind the same candidate and environment")
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


def _artifact_hash(root, reference):
    if not isinstance(reference, str) or not reference or Path(reference).is_absolute() or '..' in Path(reference).parts:
        return None
    path = root / reference
    if path.is_symlink() or not path.resolve(strict=False).is_relative_to(root) or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_image(root, reference):
    if _artifact_hash(root, reference) is None:
        return False
    data = (root / reference).read_bytes()
    return (len(data) >= 33 and data[:8] == b'\x89PNG\r\n\x1a\n' and
            data[12:16] == b'IHDR' and
            all(n > 0 for n in struct.unpack('>II', data[16:24])) and
            data[25] in (0, 2, 3, 4, 6) and data[26] == 0)


def assess_completion(value, report, verifier_report=None, *, artifact_root=None):
    """Evidence complete is not human acceptance, deployment, or verified live behavior."""
    validate_packet(value)
    if not isinstance(report, dict):
        missing = [c["id"] for c in value["acceptance"]]
        return {"status": "claimed-unverified", "missing": missing,
                "outcome_readiness": _outcome_readiness(value, missing)}
    if (report.get("task_id"), report.get("revision"), report.get("packet_sha256")) != (
            value["task_id"], value["revision"], value["packet_sha256"]):
        return {"status": "stale-or-foreign", "missing": []}
    evidence = report.get("criterion_evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    root = Path(artifact_root).resolve() if artifact_root is not None else None
    missing = []
    for criterion in value["acceptance"]:
        item = evidence.get(criterion["id"])
        if not isinstance(item, dict) or not all(item.get(k) for k in (
                "reference", "check_result", "commit", "environment")) or item.get("check_result") != "pass" or item.get("evidence_type") == "manual-waiver":
            missing.append(criterion["id"])
            continue
        binding = criterion.get("evidence_binding")
        reviewed = verifier_report if isinstance(verifier_report, dict) else {}
        verified = reviewed.get("criterion_evidence")
        verified = verified.get(criterion["id"]) if isinstance(verified, dict) else None
        hashes = item.get("artifact_hashes")
        hashes = hashes if isinstance(hashes, dict) else {}
        paths = item.get("artifacts")
        paths = paths if isinstance(paths, dict) else {}
        expected_points = binding.get("mounted_entry_points", []) if binding else []
        point_receipts = item.get("entry_point_receipts")
        verified_point_receipts = (verified or {}).get("entry_point_receipts")
        if binding and (root is None or
                        ("outcome" in binding and (
                            any(item.get(k) != binding[k] for k in ("outcome", "stage")) or
                            item.get("observed_results") != binding["expected_results"] or
                            not isinstance(verified, dict) or
                            any(verified.get(k) != binding[k] for k in ("outcome", "stage")) or
                            verified.get("observed_results") != binding["expected_results"] or
                            verified.get("evidence_type") == "manual-waiver")) or
                        any(_artifact_hash(root, paths.get(kind)) != hashes.get(kind)
                            for kind in binding["artifact_kinds"]) or
                        any("screenshot" in kind and not _png_image(root, paths.get(kind))
                            for kind in binding["artifact_kinds"]) or
                        ("production_reference_sha256" in binding and
                         _artifact_hash(root, item.get("production_reference")) !=
                         binding["production_reference_sha256"]) or
                        not isinstance(verified, dict) or
                        verified.get("inspection_result") != "pass" or
                        not verified.get("inspector") or
                        verified.get("artifact_hashes") != hashes or
                        verified.get("artifacts") != paths or
                        ("coverage_ids" in binding and verified.get("observed_coverage_ids") != binding["coverage_ids"]) or
                        (expected_points and (
                            not isinstance(point_receipts, dict) or
                            set(point_receipts) != set(expected_points) or
                            not all(isinstance(receipt, str) and receipt.strip()
                                    for receipt in point_receipts.values()) or
                            verified.get("observed_entry_points") != expected_points or
                            verified_point_receipts != point_receipts)) or
                        any(verified.get(key) != binding[key] for key in
                            ("surface", "fixture", "environment")) or
                        verified.get("candidate") != binding["candidate"] or
                        ("production_reference_sha256" in binding and
                         verified.get("production_reference_sha256") != binding["production_reference_sha256"]) or
                        (reviewed.get("task_id"), reviewed.get("revision"),
                         reviewed.get("packet_sha256")) !=
                        (value["task_id"], value["revision"], value["packet_sha256"]) or any(item.get(key) != binding[key] for key in
                            ("surface", "fixture", "environment")) or
                        item.get("commit") != binding["candidate"] or
                        any(hashes.get(kind) is None or
                            not isinstance(hashes[kind], str) or
                            not re.fullmatch(r"[0-9a-f]{64}", hashes[kind])
                            for kind in binding["artifact_kinds"]) or
                        ("production_reference_sha256" in binding and
                         item.get("production_reference_sha256") != binding["production_reference_sha256"])):
            missing.append(criterion["id"])
    return {"status": "evidence-complete-awaiting-acceptance" if not missing else "claimed-unverified",
            "missing": missing, "outcome_readiness": _outcome_readiness(value, missing),
            "unverified_limits": report.get("unverified_limits", [])}


def _outcome_readiness(value, missing):
    outcomes = {}
    for criterion in value["acceptance"]:
        binding = criterion.get("evidence_binding") or {}
        if "outcome" not in binding:
            continue
        outcome = outcomes.setdefault(binding["outcome"], {"verdict": "EVIDENCE-COMPLETE", "stages": {},
            "candidate": binding["candidate"], "environment": binding["environment"]})
        stage = binding["stage"]
        verdict = "HOLD" if criterion["id"] in missing else "EVIDENCE-COMPLETE"
        if outcome["stages"].get(stage) != "HOLD":
            outcome["stages"][stage] = verdict
        if verdict == "HOLD":
            outcome["verdict"] = "HOLD"
    return outcomes


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
