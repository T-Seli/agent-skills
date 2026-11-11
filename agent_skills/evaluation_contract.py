"""Validation and accounting for reviewed skill trials; never runs an agent."""
import re

SHA = re.compile(r"[0-9a-f]{64}\Z")
SCENARIOS = {"development", "regression", "release"}


def measure_report(text, *, max_words=None, max_lines=None):
    """Measure the full reply; never trim, run a model or certify its content.

    Lexical words are Unicode letter/digit sequences with internal apostrophes
    or hyphens, not language-aware tokenization. Limits are caller-specified.
    """
    if not isinstance(text, str):
        raise ValueError("report text required")
    for limit in (max_words, max_lines):
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("nonnegative integer report limit required")
    words = len(re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", text, re.UNICODE))
    lines = len(text.splitlines())
    return {"words": words, "lines": lines,
            "within_caps": ((max_words is None or words <= max_words) and
                            (max_lines is None or lines <= max_lines))}


def validate_case(case):
    required = {"id", "scenario", "task", "selection_mode", "required_skills",
                "allowed_skills", "forbidden_skills", "outcome_checks", "hard_invariants"}
    if not isinstance(case, dict) or set(case) != required:
        raise ValueError("invalid evaluation case fields")
    if not isinstance(case["id"], str) or not case["id"] or case["scenario"] not in SCENARIOS:
        raise ValueError("case identity or scenario invalid")
    if not isinstance(case["task"], str) or not case["task"].strip():
        raise ValueError("task required")
    if case["selection_mode"] not in ("implicit", "explicit"):
        raise ValueError("selection mode required")
    for key in ("required_skills", "allowed_skills", "forbidden_skills", "outcome_checks", "hard_invariants"):
        values = case[key]
        if not isinstance(values, list) or not all(isinstance(x, str) and x.strip() for x in values):
            raise ValueError(f"invalid {key}")
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {key}")
    if set(case["required_skills"]) - set(case["allowed_skills"]):
        raise ValueError("required skill must be allowed")
    if set(case["forbidden_skills"]) & set(case["allowed_skills"]):
        raise ValueError("forbidden skill is allowed")
    if not case["outcome_checks"] or not case["hard_invariants"]:
        raise ValueError("observable outcomes and safety invariants required")
    return True


def validate_trial(case, trial):
    validate_case(case)
    required = {"case_id", "variant", "runtime", "model", "config_sha256", "bundle_sha256",
                "evaluator_sha256", "selected_skills", "loaded_skills", "artifact_evidence",
                "check_results", "invariant_results", "cost", "environment_failures"}
    if not isinstance(trial, dict) or set(trial) != required or trial["case_id"] != case["id"]:
        raise ValueError("invalid trial fields")
    if trial["variant"] not in ("candidate", "incumbent", "no-target-skill"):
        raise ValueError("unknown variant")
    if not all(isinstance(trial[k], str) and trial[k] for k in ("runtime", "model")):
        raise ValueError("runtime and model required")
    if not all(isinstance(trial[k], str) and SHA.fullmatch(trial[k]) for k in
               ("config_sha256", "bundle_sha256", "evaluator_sha256")):
        raise ValueError("trial hashes required")
    for key in ("selected_skills", "loaded_skills", "artifact_evidence", "environment_failures"):
        if not isinstance(trial[key], list) or not all(isinstance(x, str) for x in trial[key]):
            raise ValueError(f"invalid {key}")
    if not isinstance(trial["cost"], (int, float)) or trial["cost"] < 0:
        raise ValueError("nonnegative cost required")
    for key, expected in (("check_results", case["outcome_checks"]),
                          ("invariant_results", case["hard_invariants"])):
        if not isinstance(trial[key], dict) or set(trial[key]) != set(expected) or not all(
                value in ("pass", "fail", "unknown") for value in trial[key].values()):
            raise ValueError(f"invalid {key}")
    return True


def selection_counts(cases, trials):
    """Only implicit selection is scored; undefined rates remain null."""
    by_id = {case["id"]: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("duplicate case id")
    tp = fp = fn = 0
    for trial in trials:
        case = by_id[trial["case_id"]]
        validate_trial(case, trial)
        if case["selection_mode"] != "implicit":
            continue
        selected = set(trial["selected_skills"])
        tp += len(selected & set(case["required_skills"]))
        fp += len(selected - set(case["allowed_skills"]))
        fn += len(set(case["required_skills"]) - selected)
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


def paired_review(case, candidate, baseline):
    """Require matching conditions and safety before a human reviews improvement."""
    for trial in (candidate, baseline):
        validate_trial(case, trial)
    if candidate["variant"] != "candidate" or baseline["variant"] not in ("incumbent", "no-target-skill"):
        raise ValueError("candidate and comparison trial required")
    for key in ("case_id", "runtime", "model", "config_sha256", "evaluator_sha256"):
        if candidate[key] != baseline[key]:
            return {"decision": "incomparable", "reason": key}
    if any(value != "pass" for value in candidate["invariant_results"].values()):
        return {"decision": "blocked", "reason": "safety invariant not passed"}
    if candidate["environment_failures"] or baseline["environment_failures"]:
        return {"decision": "incomparable", "reason": "environment failure"}
    candidate_passes = sum(value == "pass" for value in candidate["check_results"].values())
    baseline_passes = sum(value == "pass" for value in baseline["check_results"].values())
    return {"decision": "human-review-needed", "candidate_bundle_sha256": candidate["bundle_sha256"],
            "baseline_bundle_sha256": baseline["bundle_sha256"],
            "evaluator_sha256": candidate["evaluator_sha256"],
            "candidate_checks_passed": candidate_passes, "baseline_checks_passed": baseline_passes,
            "candidate_cost": candidate["cost"], "baseline_cost": baseline["cost"]}
