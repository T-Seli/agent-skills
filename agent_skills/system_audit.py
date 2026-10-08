"""Pure validation and synthesis helpers for bounded read-only system audits."""
from copy import deepcopy
import hashlib
import json


CLAIM_LEVELS = {"observed", "hypothesis", "known-platform-limit", "coverage-gap"}
ANGLES = {"intake-contracts", "execution-context", "decision-friction", "capability-release"}
OUTCOME_SIGNALS = {"repeated-context-request", "duplicate-investigation", "missed-evidence",
                   "decision-block-time", "false-blocker", "successful-handoff"}
CAUSE_BASES = {"observed-root-cause", "hypothesis", "known-platform-limit", "not-established"}
CONFIDENCE = {"high", "medium", "low"}
SOURCE_STATES = {"observed", "unavailable", "not-checked"}
ACCEPTANCE_STATES = {"untested", "passed", "failed", "blocked"}


def _text(value, name, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError(f"invalid {name}")
    return value.strip()


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
                   synthesis):
    """Build the minimal sanitized durable envelope; writing remains the caller's job."""
    if type(revision) is not int or revision < 1 or type(history_revision) is not int or history_revision < 0:
        raise ValueError("invalid audit or history revision")
    if not isinstance(synthesis, dict) or not isinstance(synthesis.get("coverage_complete"), bool):
        raise ValueError("validated synthesis required")
    return {"schema_version": 1, "audit_id": _text(audit_id, "audit_id"),
            "revision": revision, "scope_ref": _text(scope_ref, "scope_ref"),
            "window": {"start": _text(window_start, "window_start"),
                       "end": _text(window_end, "window_end")},
            "prior_artifact_ref": _text(prior_artifact_ref, "prior_artifact_ref", optional=True),
            "record_owner": _text(record_owner, "record_owner"),
            "history_base": {"revision": history_revision,
                             "digest": _text(history_digest, "history_digest")},
            "synthesis": deepcopy(synthesis), "history_publication": "proposed-not-appended"}
