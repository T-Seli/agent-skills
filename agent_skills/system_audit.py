"""Pure validation and synthesis helpers for bounded read-only system audits."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re


CLAIM_LEVELS = {"observed", "hypothesis", "known-platform-limit", "coverage-gap"}
ANGLES = {"intake-contracts", "execution-context", "decision-friction", "capability-release"}
OUTCOME_SIGNALS = {"repeated-context-request", "duplicate-investigation", "missed-evidence",
                   "decision-block-time", "false-blocker", "successful-handoff"}
CAUSE_BASES = {"observed-root-cause", "hypothesis", "known-platform-limit", "not-established"}
CONFIDENCE = {"high", "medium", "low"}
SOURCE_STATES = {"observed", "unavailable", "not-checked"}
ACCEPTANCE_STATES = {"untested", "passed", "failed", "blocked"}
FAILURE_CLASSES = {
    "legitimate-policy-limit",
    "missing-approval-provenance",
    "incorrect-approval-provenance",
    "unavailable-tool",
    "stale-session-placement",
    "stale-session-id",
    "transport-offline",
    "unsupported-operation",
    "invalid-arguments",
    "implementation-defect",
}
AUTHORIZATION_STATES = {
    "verified-covered", "missing-provenance", "incorrect-provenance",
    "not-required", "policy-denied",
}
FAILURE_OUTCOMES = {"blocked", "failed", "rejected"}
NEXT_ACTION_MODES = {"agent-supported", "human-only"}
REMEDY_BY_CLASS = {
    "legitimate-policy-limit": "respect-policy-limit",
    "missing-approval-provenance": "repair-approval-provenance",
    "incorrect-approval-provenance": "repair-approval-provenance",
    "unavailable-tool": "restore-tool-capability",
    "stale-session-placement": "refresh-session-placement",
    "stale-session-id": "refresh-session-id",
    "transport-offline": "retry-transport-after-reconcile",
    "unsupported-operation": "use-supported-operation",
    "invalid-arguments": "correct-arguments",
    "implementation-defect": "fix-implementation",
}
FAILURE_DOMAINS = {
    "legitimate-policy-limit": "policy",
    "missing-approval-provenance": "approval",
    "incorrect-approval-provenance": "approval",
    "unavailable-tool": "capability",
    "stale-session-placement": "capability",
    "stale-session-id": "capability",
    "transport-offline": "capability",
    "unsupported-operation": "capability",
    "invalid-arguments": "invocation",
    "implementation-defect": "implementation",
}
_APPROVAL_FAILURES = {"missing-approval-provenance", "incorrect-approval-provenance"}
_APPROVAL_REQUEST = re.compile(r"\b(?:ask|request)\b.{0,40}\bapproval\b|\bapprove\s+again\b", re.I)
_GUARD_BYPASS = re.compile(
    r"\b(?:bypass|circumvent|disable|override)\b.{0,40}\b(?:guard|policy|denial|authorization)\b|"
    r"\bforce\b.{0,40}\bdenied\b", re.I)


def _text(value, name, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError(f"invalid {name}")
    return value.strip()


def _text_list(value, name):
    if not isinstance(value, list) or not all(
            isinstance(x, str) and x.strip() and len(x) <= 1000 for x in value):
        raise ValueError(f"invalid {name}")
    return [x.strip() for x in value]


def _utc(value, name):
    value = _text(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"invalid {name}")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def failure_incident(*, incident_id, failure_key, operation, target, failure_class,
                     source_receipt, occurred_at, user_impact, authorization_state,
                     approved_scope, approval_ref, retries_attempted, evidence_attempted,
                     outcome, next_supported_action, owner, next_action_mode,
                     prevention_check, prevention_state="untested", prevention_receipt=None,
                     repeat_of=None, human_action=None, verified=False):
    """Validate one receipt-backed failure occurrence without weakening a guard."""
    if verified is not True:
        raise ValueError("only verified failure incidents may be measured")
    if failure_class not in FAILURE_CLASSES or authorization_state not in AUTHORIZATION_STATES:
        raise ValueError("invalid failure or authorization class")
    expected_authorization = {
        "legitimate-policy-limit": "policy-denied",
        "missing-approval-provenance": "missing-provenance",
        "incorrect-approval-provenance": "incorrect-provenance",
    }.get(failure_class)
    if expected_authorization is not None and authorization_state != expected_authorization:
        raise ValueError("failure class does not match authorization state")
    if outcome not in FAILURE_OUTCOMES or next_action_mode not in NEXT_ACTION_MODES:
        raise ValueError("invalid failure outcome or next-action mode")
    if prevention_state not in ACCEPTANCE_STATES:
        raise ValueError("invalid prevention state")
    if prevention_state in {"passed", "failed"} and not prevention_receipt:
        raise ValueError("prevention result requires a receipt")
    if authorization_state == "verified-covered":
        if not approved_scope or not approval_ref:
            raise ValueError("covered authorization requires scope and receipt")
        if failure_class in _APPROVAL_FAILURES:
            raise ValueError("covered authorization cannot remain an approval blocker")
    elif approved_scope is not None or approval_ref is not None:
        raise ValueError("unverified authorization cannot carry approved scope")
    next_action = _text(next_supported_action, "next supported action")
    if _GUARD_BYPASS.search(next_action):
        raise ValueError("next action may not route around a guard or denial")
    if authorization_state == "verified-covered" and _APPROVAL_REQUEST.search(next_action):
        raise ValueError("covered authorization may not request approval again")
    if next_action_mode == "human-only":
        human_action = _text(human_action, "human-only action")
    elif human_action is not None:
        raise ValueError("human action requires human-only mode")
    return {
        "kind": "audit-failure-incident", "incident_id": _text(incident_id, "incident id"),
        "failure_key": _text(failure_key, "failure key"),
        "operation": _text(operation, "operation"), "target": _text(target, "target"),
        "failure_class": failure_class, "failure_domain": FAILURE_DOMAINS[failure_class],
        "source_receipt": _text(source_receipt, "source receipt"),
        "occurred_at": _utc(occurred_at, "occurred at"),
        "user_impact": _text(user_impact, "user impact"),
        "authorization_state": authorization_state,
        "approved_scope": _text(approved_scope, "approved scope", optional=True),
        "approval_ref": _text(approval_ref, "approval reference", optional=True),
        "retries_attempted": _text_list(retries_attempted, "retries attempted"),
        "evidence_attempted": _text_list(evidence_attempted, "evidence attempted"),
        "outcome": outcome, "remedy_kind": REMEDY_BY_CLASS[failure_class],
        "next_supported_action": next_action, "owner": _text(owner, "owner"),
        "next_action_mode": next_action_mode,
        "human_action": human_action,
        "repeat_of": _text(repeat_of, "repeat occurrence", optional=True),
        "repeat_occurrence": repeat_of is not None,
        "prevention_check": _text(prevention_check, "prevention check"),
        "prevention_state": prevention_state,
        "prevention_receipt": _text(prevention_receipt, "prevention receipt", optional=True),
        "verified": True,
    }


def blocker_update(prior, current):
    """Replace an approval blocker once authenticated scope is clear; never claim delivery."""
    for item in (prior, current):
        if not isinstance(item, dict) or item.get("kind") != "audit-failure-incident":
            raise ValueError("validated failure incidents required")
    if (prior["operation"], prior["target"]) != (current["operation"], current["target"]):
        raise ValueError("blocker transition must retain operation and target")
    if current["occurred_at"] < prior["occurred_at"]:
        raise ValueError("blocker transition cannot move backward in time")
    if (prior["failure_class"] in _APPROVAL_FAILURES and
            current["authorization_state"] == "verified-covered"):
        if current["failure_class"] in _APPROVAL_FAILURES:
            raise ValueError("clear authorization must replace the approval blocker")
        return {"decision": "replace-blocker", "from_failure_class": prior["failure_class"],
                "to_failure_class": current["failure_class"],
                "blocker_domain": current["failure_domain"],
                "ask_user_to_approve_again": False, "claim_operation_succeeded": False,
                "next_supported_action": current["next_supported_action"],
                "owner": current["owner"], "next_action_mode": current["next_action_mode"]}
    return {"decision": "retain-current-blocker", "from_failure_class": prior["failure_class"],
            "to_failure_class": current["failure_class"],
            "blocker_domain": current["failure_domain"],
            "ask_user_to_approve_again": False, "claim_operation_succeeded": False,
            "next_supported_action": current["next_supported_action"],
            "owner": current["owner"], "next_action_mode": current["next_action_mode"]}


def _incident_fingerprint(value):
    return tuple(value.get(k) for k in ("failure_key", "operation", "target", "failure_class"))


def synthesize_failures(incidents, *, prior_incidents=()):
    """Deduplicate identical receipts, count real repeats, and expose failed prevention."""
    if not isinstance(incidents, list) or not isinstance(prior_incidents, (list, tuple)):
        raise ValueError("failure incident lists required")
    by_id = {}
    origin = {}
    for source, values in (("prior", prior_incidents), ("current", incidents)):
        for item in values:
            if not isinstance(item, dict) or item.get("kind") != "audit-failure-incident":
                raise ValueError("validated failure incident required")
            incident_id = item["incident_id"]
            if incident_id in by_id and by_id[incident_id] != item:
                raise ValueError("conflicting failure occurrence id")
            by_id.setdefault(incident_id, deepcopy(item))
            origin.setdefault(incident_id, source)
    for item in by_id.values():
        repeat_of = item.get("repeat_of")
        if repeat_of is None:
            continue
        previous = by_id.get(repeat_of)
        if (previous is None or _incident_fingerprint(previous) != _incident_fingerprint(item) or
                previous["occurred_at"] > item["occurred_at"]):
            raise ValueError("repeat occurrence must reference the same earlier failure")
    groups = {}
    for item in by_id.values():
        groups.setdefault(_incident_fingerprint(item), []).append(item)
    result = []
    for key, values in groups.items():
        values.sort(key=lambda x: (x["occurred_at"], x["incident_id"]))
        for index, item in enumerate(values):
            if index and not item["repeat_occurrence"]:
                raise ValueError("repeated failure occurrence must identify its prior occurrence")
        passed_times = [x["occurred_at"] for x in values if x["prevention_state"] == "passed"]
        recurrence_after_pass = any(x["occurred_at"] > passed for x in values for passed in passed_times)
        states = sorted({x["prevention_state"] for x in values})
        if recurrence_after_pass:
            prevention_status = "recurrence-observed-after-pass"
        elif "failed" in states:
            prevention_status = "prevention-check-failed"
        elif "passed" in states:
            prevention_status = "passed-in-window-no-later-recurrence-observed"
        elif "blocked" in states:
            prevention_status = "prevention-check-blocked"
        else:
            prevention_status = "untested"
        result.append({"kind": "audit-failure-group",
                       "failure_key": key[0], "operation": key[1], "target": key[2],
                       "failure_class": key[3], "failure_domain": values[0]["failure_domain"],
                       "occurrence_count": len(values),
                       "current_occurrence_count": sum(origin[x["incident_id"]] == "current"
                                                       for x in values),
                       "repeat_count": sum(x["repeat_occurrence"] for x in values),
                       "occurrence_ids": [x["incident_id"] for x in values],
                       "source_receipts": [x["source_receipt"] for x in values],
                       "latest_occurred_at": values[-1]["occurred_at"],
                       "next_supported_action": values[-1]["next_supported_action"],
                       "owner": values[-1]["owner"],
                       "next_action_mode": values[-1]["next_action_mode"],
                       "prevention_status": prevention_status,
                       "prevention_receipts": sorted({x["prevention_receipt"] for x in values
                                                       if x["prevention_receipt"]}),
                       "recurrence_after_pass": recurrence_after_pass})
    result.sort(key=lambda x: (x["failure_key"], x["failure_class"]))
    return result


def finding(*, finding_id, finding_key, angle, claim_level, cause_basis, confidence,
            assertion, evidence_window, scope_ref, evidence_refs, impact, counterevidence,
            minimal_remedy, regression_risk, acceptance_test, conclusion,
            acceptance_state="untested", acceptance_receipt=None,
            outcome_signal=None, prior_finding_id=None,
            direct_user_instruction=False, source_authenticated=None, scope_matches=None):
    """Validate one review finding without upgrading absence into evidence."""
    if (angle not in ANGLES or claim_level not in CLAIM_LEVELS or
            cause_basis not in CAUSE_BASES or confidence not in CONFIDENCE):
        raise ValueError("invalid review angle or claim level")
    if not isinstance(evidence_refs, list) or not all(
            isinstance(x, str) and x.strip() and len(x) <= 1000 for x in evidence_refs):
        raise ValueError("invalid evidence references")
    if claim_level == "observed" and not evidence_refs:
        raise ValueError("observed findings require evidence")
    if outcome_signal is not None and outcome_signal not in OUTCOME_SIGNALS:
        raise ValueError("unsupported outcome signal")
    if acceptance_state not in ACCEPTANCE_STATES:
        raise ValueError("invalid acceptance state")
    if acceptance_state in {"passed", "failed"} and not acceptance_receipt:
        raise ValueError("acceptance result requires a receipt")
    if direct_user_instruction is True and (source_authenticated is not True or scope_matches is not True):
        claim_level = "coverage-gap"
        cause_basis = "not-established"
        confidence = "low"
        conclusion = "Direct instruction authority or current scope is not verified."
    return {"finding_id": _text(finding_id, "finding_id"),
            "finding_key": _text(finding_key, "finding_key"), "angle": angle,
            "claim_level": claim_level, "evidence_refs": evidence_refs.copy(),
            "cause_basis": cause_basis, "confidence": confidence,
            "assertion": _text(assertion, "assertion"),
            "evidence_window": _text(evidence_window, "evidence_window"),
            "scope_ref": _text(scope_ref, "scope_ref"),
            "impact": _text(impact, "impact"),
            "counterevidence": _text(counterevidence, "counterevidence", optional=True),
            "minimal_remedy": _text(minimal_remedy, "minimal_remedy"),
            "regression_risk": _text(regression_risk, "regression_risk"),
            "acceptance_test": _text(acceptance_test, "acceptance_test"),
            "conclusion": _text(conclusion, "conclusion"), "outcome_signal": outcome_signal,
            "acceptance_state": _text(acceptance_state, "acceptance_state"),
            "acceptance_receipt": _text(acceptance_receipt, "acceptance_receipt", optional=True),
            "prior_finding_id": _text(prior_finding_id, "prior_finding_id", optional=True),
            "direct_user_instruction": direct_user_instruction is True,
            "source_authenticated": source_authenticated if direct_user_instruction is True else None,
            "scope_matches": scope_matches if direct_user_instruction is True else None}


def _fingerprint(value):
    fields = {k: value.get(k) for k in ("finding_id", "finding_key",
                                        "acceptance_test", "scope_ref")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def _sources(source_manifest):
    if not isinstance(source_manifest, list) or not source_manifest:
        raise ValueError("non-empty source manifest required")
    result = []
    seen = set()
    for item in source_manifest:
        if (not isinstance(item, dict) or set(item) != {"source", "state", "receipt_ref"} or
                item.get("state") not in SOURCE_STATES):
            raise ValueError("invalid source manifest")
        source = _text(item.get("source"), "source")
        if source in seen:
            raise ValueError("duplicate audit source")
        if item["state"] == "observed" and not item.get("receipt_ref"):
            raise ValueError("observed audit source requires a receipt")
        seen.add(source)
        result.append({"source": source, "state": item["state"],
                       "receipt_ref": _text(item.get("receipt_ref"), "receipt_ref", optional=True)})
    return result


def synthesize(findings, *, source_manifest, prior_findings=()):
    """Deduplicate unchanged findings and preserve contradictory conclusions as disputes."""
    if not isinstance(findings, list) or not isinstance(prior_findings, (list, tuple)):
        raise ValueError("findings and prior findings must be lists")
    sources = _sources(source_manifest)
    prior_by_fp = {_fingerprint(x): x for x in prior_findings}
    groups = {}
    for item in findings:
        if not isinstance(item, dict) or item.get("angle") not in ANGLES:
            raise ValueError("validated finding required")
        groups.setdefault(item["finding_id"], []).append(deepcopy(item))
    results = []
    duplicates = []
    for finding_id, items in groups.items():
        assertions = {x["assertion"] for x in items}
        if len(assertions) > 1:
            results.append({"finding_id": finding_id, "finding_key": items[0]["finding_key"],
                            "state": "disputed", "reviewer_count": len(items),
                            "findings": items})
            continue
        previous = prior_by_fp.get(_fingerprint(items[0]))
        if previous:
            duplicates.append({"finding_key": items[0]["finding_key"],
                               "prior_finding_id": previous.get("finding_id"),
                               "evidence_windows": sorted({x["evidence_window"] for x in items}),
                               "current_evidence_refs": sorted({ref for x in items
                                                                for ref in x["evidence_refs"]}),
                               "acceptance_states": sorted({x["acceptance_state"] for x in items}),
                               "acceptance_receipts": sorted({x["acceptance_receipt"] for x in items
                                                              if x["acceptance_receipt"]})})
            continue
        results.append({"finding_id": finding_id, "finding_key": items[0]["finding_key"],
                        "state": "supported", "reviewer_count": len(items),
                        "findings": items})
    results.sort(key=lambda x: x["finding_id"])
    duplicates.sort(key=lambda x: x["finding_key"])
    return {"findings": results, "unchanged": duplicates, "source_manifest": sources,
            "coverage_complete": all(x["state"] == "observed" for x in sources)}


def audit_artifact(*, audit_id, revision, scope_ref, window_start, window_end,
                   prior_artifact_ref, record_owner, history_revision, history_digest,
                   synthesis, failure_ledger=()):
    """Build the minimal sanitized durable envelope; writing remains the caller's job."""
    if type(revision) is not int or revision < 1 or type(history_revision) is not int or history_revision < 0:
        raise ValueError("invalid audit or history revision")
    if not isinstance(synthesis, dict) or not isinstance(synthesis.get("coverage_complete"), bool):
        raise ValueError("validated synthesis required")
    if (not isinstance(failure_ledger, (list, tuple)) or not all(
            isinstance(x, dict) and x.get("kind") == "audit-failure-group"
            for x in failure_ledger)):
        raise ValueError("validated failure ledger required")
    return {"schema_version": 1, "audit_id": _text(audit_id, "audit_id"),
            "revision": revision, "scope_ref": _text(scope_ref, "scope_ref"),
            "window": {"start": _text(window_start, "window_start"),
                       "end": _text(window_end, "window_end")},
            "prior_artifact_ref": _text(prior_artifact_ref, "prior_artifact_ref", optional=True),
            "record_owner": _text(record_owner, "record_owner"),
            "history_base": {"revision": history_revision,
                             "digest": _text(history_digest, "history_digest")},
            "synthesis": deepcopy(synthesis), "failure_ledger": deepcopy(list(failure_ledger)),
            "history_publication": "proposed-not-appended"}
