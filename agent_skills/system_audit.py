"""Pure validation and synthesis helpers for bounded read-only system audits."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from .observation_evidence import assess_coverage


CLAIM_LEVELS = {"observed", "hypothesis", "known-platform-limit", "coverage-gap"}
ANGLES = {"intake-contracts", "execution-context", "decision-friction", "capability-release"}
OUTCOME_SIGNALS = {"repeated-context-request", "duplicate-investigation", "missed-evidence",
                   "decision-block-time", "false-blocker", "successful-handoff",
                   "workspace-navigation-gap"}
CAUSE_BASES = {"observed-root-cause", "hypothesis", "known-platform-limit", "not-established"}
CONFIDENCE = {"high", "medium", "low"}
SOURCE_STATES = {"observed", "unavailable", "not-checked", "not-applicable"}
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
HUMAN_EFFORT = {"quick", "short", "extended"}
RISK_LEVELS = {"low", "medium", "high", "critical"}
READINESS_STATES = {"ready", "conditional", "not-ready"}
DOWNSTREAM_IMPACT = {"high", "medium", "low"}
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
    r"\b(?:route|work)\s+around\b|"
    r"\b(?:bypass|circumvent|disable|override|evade)\b.{0,40}\b(?:guard|policy|denial|authorization)\b|"
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
                     operation_scope, approved_scope, approval_ref,
                     retries_attempted, evidence_attempted,
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
    authorization_failure = {
        "policy-denied": "legitimate-policy-limit",
        "missing-provenance": "missing-approval-provenance",
        "incorrect-provenance": "incorrect-approval-provenance",
    }.get(authorization_state)
    if authorization_failure is not None and failure_class != authorization_failure:
        raise ValueError("authorization state does not match current failure class")
    if outcome not in FAILURE_OUTCOMES or next_action_mode not in NEXT_ACTION_MODES:
        raise ValueError("invalid failure outcome or next-action mode")
    if prevention_state not in ACCEPTANCE_STATES:
        raise ValueError("invalid prevention state")
    if prevention_state in {"passed", "failed"} and not prevention_receipt:
        raise ValueError("prevention result requires a receipt")
    operation_scope_value = _text(operation_scope, "operation scope")
    if authorization_state == "verified-covered":
        if not approved_scope or not approval_ref:
            raise ValueError("covered authorization requires scope and receipt")
        approved_scope_value = _text(approved_scope, "approved scope")
        approval_ref_value = _text(approval_ref, "approval reference")
        if approved_scope_value != operation_scope_value:
            raise ValueError("approved scope must exactly match the operation scope")
        if failure_class in _APPROVAL_FAILURES:
            raise ValueError("covered authorization cannot remain an approval blocker")
    elif approved_scope is not None or approval_ref is not None:
        raise ValueError("unverified authorization cannot carry approved scope")
    else:
        approved_scope_value = None
        approval_ref_value = None
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
        "operation_scope": operation_scope_value,
        "approved_scope": approved_scope_value,
        "approval_ref": approval_ref_value,
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
    if ((prior["operation"], prior["target"], prior["operation_scope"]) !=
            (current["operation"], current["target"], current["operation_scope"])):
        raise ValueError("blocker transition must retain operation, target and scope")
    if current["occurred_at"] < prior["occurred_at"]:
        raise ValueError("blocker transition cannot move backward in time")
    if (prior["failure_class"] in _APPROVAL_FAILURES and
            current["authorization_state"] == "verified-covered"):
        if current.get("approved_scope") != current.get("operation_scope"):
            raise ValueError("clear authorization must match the current operation scope")
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
        if (repeat_of == item["incident_id"] or previous is None or
                _incident_fingerprint(previous) != _incident_fingerprint(item) or
                previous["occurred_at"] >= item["occurred_at"]):
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
                       "recurrence_after_pass": recurrence_after_pass,
                       "occurrences": deepcopy(values)})
    result.sort(key=lambda x: (x["failure_key"], x["failure_class"]))
    return result


def _owned_work(value, name, *, authorization_required=False):
    if not isinstance(value, list):
        raise ValueError(f"invalid {name}")
    result = []
    by_task = {}
    for item in value:
        required = {"task_id", "owner", "work"}
        if authorization_required:
            required.add("authorization_ref")
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"invalid {name}")
        row = {key: _text(item[key], f"{name} {key}") for key in required}
        task_id = row["task_id"]
        if task_id in by_task and by_task[task_id] != row:
            raise ValueError(f"conflicting duplicate {name}")
        if task_id not in by_task:
            by_task[task_id] = row
            result.append(row)
    return result


def human_unlock(*, unlock_id, task_id, owner, daily_priority_ref, daily_priority_rank,
                 human_effort, readiness, readiness_receipts, safety_ready,
                 risk_level, risk_summary, downstream_impact, impact_basis,
                 downstream_work_unlocked, deadline,
                 dependencies, shared_resources, exact_decision,
                 parallel_authorized_work=()):
    """Record one human-owned decision opportunity without deciding or dispatching it."""
    if (type(daily_priority_rank) is not int or daily_priority_rank < 1 or
            human_effort not in HUMAN_EFFORT or readiness not in READINESS_STATES or
            risk_level not in RISK_LEVELS or downstream_impact not in DOWNSTREAM_IMPACT or
            safety_ready not in {True, False}):
        raise ValueError("invalid human unlock priority, effort, readiness or risk")
    receipts = _text_list(readiness_receipts, "readiness receipts")
    if readiness == "ready" and (safety_ready is not True or not receipts):
        raise ValueError("ready human unlock requires passing safety and readiness receipts")
    deadline_value = None if deadline is None else _utc(deadline, "human unlock deadline")
    downstream = _owned_work(downstream_work_unlocked, "downstream work")
    if readiness == "ready" and not downstream:
        raise ValueError("ready human unlock must identify downstream work")
    parallel = _owned_work(list(parallel_authorized_work), "parallel authorized work",
                           authorization_required=True)
    return {
        "kind": "human-unlock", "unlock_id": _text(unlock_id, "unlock id"),
        "task_id": _text(task_id, "task id"), "owner": _text(owner, "owner"),
        "daily_priority_ref": _text(daily_priority_ref, "daily priority reference"),
        "daily_priority_rank": daily_priority_rank, "human_effort": human_effort,
        "readiness": readiness, "readiness_receipts": receipts,
        "safety_ready": safety_ready, "risk_level": risk_level,
        "risk_summary": _text(risk_summary, "risk summary"),
        "downstream_impact": downstream_impact,
        "impact_basis": _text(impact_basis, "downstream impact basis"),
        "downstream_work_unlocked": downstream, "deadline": deadline_value,
        "dependencies": _text_list(dependencies, "dependencies"),
        "shared_resources": _text_list(shared_resources, "shared resources"),
        "exact_decision": _text(exact_decision, "exact decision"),
        "parallel_authorized_work": parallel,
        "human_decision_required": True, "auto_decide": False,
    }


def prioritize_human_unlocks(unlocks, *, limit=3):
    """Recommend a small ready set and list already-authorized concurrent work."""
    if not isinstance(unlocks, list) or type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError("human unlock list and limit of one to three required")
    by_id = {}
    task_owners = {}
    unlock_by_task = {}
    priority_refs = set()
    gated_tasks = set()
    for item in unlocks:
        if not isinstance(item, dict) or item.get("kind") != "human-unlock":
            raise ValueError("validated human unlock required")
        unlock_id = item["unlock_id"]
        if unlock_id in by_id and by_id[unlock_id] != item:
            raise ValueError("conflicting human unlock id")
        by_id.setdefault(unlock_id, deepcopy(item))
        priority_refs.add(item["daily_priority_ref"])
        task_id, owner = item["task_id"], item["owner"]
        if task_id in unlock_by_task and unlock_by_task[task_id]["unlock_id"] != unlock_id:
            raise ValueError("one canonical human unlock decision is allowed per task")
        unlock_by_task[task_id] = item
        if task_id in task_owners and task_owners[task_id] != owner:
            raise ValueError("task owner conflict")
        task_owners[task_id] = owner
        for work in item["downstream_work_unlocked"]:
            downstream_id, downstream_owner = work["task_id"], work["owner"]
            if downstream_id in task_owners and task_owners[downstream_id] != downstream_owner:
                raise ValueError("downstream work owner conflicts with canonical task owner")
            task_owners[downstream_id] = downstream_owner
            gated_tasks.add(downstream_id)
    if len(priority_refs) > 1:
        raise ValueError("human unlocks must use one canonical daily priority receipt")

    effort_order = {"quick": 0, "short": 1, "extended": 2}
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    impact_order = {"high": 0, "medium": 1, "low": 2}
    eligible = [x for x in by_id.values() if x["readiness"] == "ready" and x["safety_ready"]]
    eligible.sort(key=lambda x: (
        x["daily_priority_rank"], x["deadline"] is None, x["deadline"] or "",
        risk_order[x["risk_level"]], impact_order[x["downstream_impact"]],
        effort_order[x["human_effort"]], x["unlock_id"],
    ))

    parallel_by_task = {}
    for item in by_id.values():
        for work in item["parallel_authorized_work"]:
            task_id = work["task_id"]
            if task_id in gated_tasks:
                raise ValueError("work cannot be both decision-gated and already authorized")
            if task_id in task_owners and task_owners[task_id] != work["owner"]:
                raise ValueError("parallel work owner conflicts with canonical task owner")
            existing = parallel_by_task.get(task_id)
            if existing is not None and existing != work:
                raise ValueError("conflicting duplicate parallel work")
            parallel_by_task.setdefault(task_id, deepcopy(work))

    all_unlocks = sorted(by_id.values(), key=lambda x: x["unlock_id"])
    deferred = sorted((x for x in by_id.values() if x not in eligible),
                      key=lambda x: x["unlock_id"])
    return {
        "kind": "human-unlock-plan",
        "recommended_decisions": deepcopy(eligible[:limit]),
        "ready_not_selected": deepcopy(eligible[limit:]),
        "parallel_authorized_work": [parallel_by_task[key] for key in sorted(parallel_by_task)],
        "deferred_not_ready": deepcopy(deferred),
        "all_unlocks": deepcopy(all_unlocks),
        "auto_decisions": [],
        "selection_basis": "daily priority, deadline, readiness/risk, receipt-backed downstream impact, human effort",
    }


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
    """Stable mechanism identity; reviewer-local finding IDs are retained only as aliases."""
    fields = {k: value.get(k) for k in ("finding_key", "acceptance_test", "scope_ref")}
    if not all(fields.values()) and re.fullmatch(r"[0-9a-f]{64}", str(value.get("mechanism_fingerprint") or "")):
        return value["mechanism_fingerprint"]
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
        if item["state"] in {"observed", "unavailable", "not-applicable"} and not item.get("receipt_ref"):
            raise ValueError("observed, unavailable and not-applicable audit sources require receipts")
        seen.add(source)
        result.append({"source": source, "state": item["state"],
                       "receipt_ref": _text(item.get("receipt_ref"), "receipt_ref", optional=True)})
    return result


def synthesize(findings, *, source_manifest, prior_findings=(), required_sources=None):
    """Deduplicate unchanged findings and preserve contradictory conclusions as disputes."""
    if not isinstance(findings, list) or not isinstance(prior_findings, (list, tuple)):
        raise ValueError("findings and prior findings must be lists")
    sources = _sources(source_manifest)
    if required_sources is not None and (not isinstance(required_sources, list) or
            not required_sources or not all(isinstance(x, str) and x.strip() for x in required_sources) or
            len(required_sources) != len(set(required_sources))):
        raise ValueError("required audit sources must be a non-empty unique list")
    prior_by_fp = {_fingerprint(x): x for x in prior_findings}
    groups = {}
    for item in findings:
        if not isinstance(item, dict) or item.get("angle") not in ANGLES:
            raise ValueError("validated finding required")
        groups.setdefault(_fingerprint(item), []).append(deepcopy(item))
    results = []
    duplicates = []
    for fingerprint, items in groups.items():
        aliases = sorted({x["finding_id"] for x in items})
        assertions = {x["assertion"] for x in items}
        if len(assertions) > 1:
            results.append({"finding_id": aliases[0], "finding_aliases": aliases,
                            "mechanism_fingerprint": fingerprint,
                            "finding_key": items[0]["finding_key"],
                            "acceptance_test": items[0]["acceptance_test"],
                            "scope_ref": items[0]["scope_ref"],
                            "state": "disputed", "reviewer_count": len(items),
                            "findings": items})
            continue
        previous = prior_by_fp.get(_fingerprint(items[0]))
        if previous:
            duplicates.append({"finding_key": items[0]["finding_key"],
                               "prior_finding_id": previous.get("finding_id"),
                               "current_finding_aliases": aliases,
                               "evidence_windows": sorted({x["evidence_window"] for x in items}),
                               "current_evidence_refs": sorted({ref for x in items
                                                                for ref in x["evidence_refs"]}),
                               "acceptance_states": sorted({x["acceptance_state"] for x in items}),
                               "acceptance_receipts": sorted({x["acceptance_receipt"] for x in items
                                                              if x["acceptance_receipt"]})})
            continue
        results.append({"finding_id": aliases[0], "finding_aliases": aliases,
                        "mechanism_fingerprint": fingerprint,
                        "finding_key": items[0]["finding_key"],
                        "acceptance_test": items[0]["acceptance_test"],
                        "scope_ref": items[0]["scope_ref"],
                        "state": "supported", "reviewer_count": len(items),
                        "findings": items})
    results.sort(key=lambda x: x["finding_id"])
    duplicates.sort(key=lambda x: x["finding_key"])
    by_source = {item["source"]: item for item in sources}
    if required_sources is None:
        missing = ["required-sources-not-declared"]
    else:
        missing = [source for source in required_sources if source not in by_source]
        missing.extend(source for source in required_sources if source in by_source and
                       by_source[source]["state"] not in {"observed", "not-applicable"})
    return {"findings": results, "unchanged": duplicates, "source_manifest": sources,
            "required_sources": list(required_sources or []),
            "coverage_missing": sorted(set(missing)), "coverage_complete": not missing}


def monitoring_verdict(*, wake_receipt, readback_receipt, expires_at_utc,
                       observed_at_utc, traffic_count, functional_results, coverage=None):
    """A configured watch is not armed without current wake and readback receipts."""
    if (type(traffic_count) is not int or traffic_count < 0 or not isinstance(functional_results, list) or
            any(type(value) is not bool for value in functional_results)):
        raise ValueError("invalid monitoring evidence")
    observed = _utc(observed_at_utc, "observed_at_utc")
    expires = _utc(expires_at_utc, "expires_at_utc") if expires_at_utc else None
    receipts_current = bool(wake_receipt and readback_receipt and expires and observed <= expires)
    armed = "armed" if receipts_current else "not-armed"
    source = assess_coverage(coverage, observed_at_utc=observed_at_utc)
    if not receipts_current:
        acceptance = "unverified"
    elif traffic_count == 0:
        acceptance = "inconclusive-zero-traffic"
    elif not functional_results:
        acceptance = "unverified"
    elif source['state'] not in ('complete', 'partial'):
        acceptance = "unverified"
    elif not all(functional_results):
        acceptance = "failed"
    elif source['state'] != 'complete':
        acceptance = "unverified"
    else:
        acceptance = "passed"
    return {"watch_state": armed, "functional_acceptance": acceptance,
            "traffic_count": traffic_count,
            "wake_receipt": _text(wake_receipt, "wake_receipt", optional=True),
            "readback_receipt": _text(readback_receipt, "readback_receipt", optional=True),
            "expires_at_utc": expires_at_utc, "observed_at_utc": observed_at_utc,
            "source_coverage": source}


def audit_artifact(*, audit_id, revision, scope_ref, window_start, window_end,
                   prior_artifact_ref, record_owner, history_revision, history_digest,
                   synthesis, failure_ledger=(), human_unlock_plan=None):
    """Build the minimal sanitized durable envelope; writing remains the caller's job."""
    if type(revision) is not int or revision < 1 or type(history_revision) is not int or history_revision < 0:
        raise ValueError("invalid audit or history revision")
    if not isinstance(synthesis, dict) or not isinstance(synthesis.get("coverage_complete"), bool):
        raise ValueError("validated synthesis required")
    if (not isinstance(failure_ledger, (list, tuple)) or not all(
            isinstance(x, dict) and x.get("kind") == "audit-failure-group"
            for x in failure_ledger)):
        raise ValueError("validated failure ledger required")
    if human_unlock_plan is not None and (
            not isinstance(human_unlock_plan, dict) or
            human_unlock_plan.get("kind") != "human-unlock-plan"):
        raise ValueError("validated human unlock plan required")
    return {"schema_version": 1, "audit_id": _text(audit_id, "audit_id"),
            "revision": revision, "scope_ref": _text(scope_ref, "scope_ref"),
            "window": {"start": _text(window_start, "window_start"),
                       "end": _text(window_end, "window_end")},
            "prior_artifact_ref": _text(prior_artifact_ref, "prior_artifact_ref", optional=True),
            "record_owner": _text(record_owner, "record_owner"),
            "history_base": {"revision": history_revision,
                             "digest": _text(history_digest, "history_digest")},
            "synthesis": deepcopy(synthesis), "failure_ledger": deepcopy(list(failure_ledger)),
            "human_unlock_plan": deepcopy(human_unlock_plan),
            "history_publication": "proposed-not-appended"}
