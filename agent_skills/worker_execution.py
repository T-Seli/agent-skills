"""Explicit routing and execution receipts on the existing task; no launch or authority.

Catalogs, policy and source receipts are supplied by the authenticated caller.
Model-reported prose is never execution metadata. Nothing here expands access.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math

SIGNALS = {"architecture", "ambiguous-failure", "high-risk", "multi-system", "repeated-failure"}
EFFORT_RANK = ("low", "medium", "high", "xhigh", "max")
STATES = ("verified", "blocked", "unknown")  # task_checkpoint.record_execution_context vocabulary
RECEIPT_FIELDS = {"environment_id", "auth_context", "observed_at_utc", "source_ref", "capabilities", "models"}
READINESS_FIELDS = {"environment_id", "auth_context", "source_ref", "receipt_sha256", "observed_at_utc",
                    "checked_at_utc", "max_age_seconds", "required", "capabilities", "route"}


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty receipt or selection required")
    return value.strip()


def select_route(policy, capabilities, *, provider, signals=(), reason):
    """Choose involved work up front; never fall back when that route is unavailable."""
    signals = set(signals)
    if signals - SIGNALS:
        raise ValueError("unrecognized complexity signal")
    tier = "involved" if signals else "ordinary"
    route = deepcopy(policy[provider][tier])
    model, effort = _text(route["model"]), _text(route["effort"])
    if effort not in capabilities.get(provider, {}).get(model, []):
        raise ValueError("requested model/effort not in the supplied capability receipt")
    # A policy without a ceiling stays caller-compatible; its route then carries no `effort_ceiling`.
    ceiling = policy[provider].get("effort_ceiling")
    if ceiling is not None:
        if ceiling not in EFFORT_RANK or effort not in EFFORT_RANK:
            raise ValueError("effort ceiling needs ranked effort levels")
        if EFFORT_RANK.index(effort) > EFFORT_RANK.index(ceiling):
            raise ValueError("route effort exceeds the policy ceiling; no fallback")
    timeout = route.get("timeout_seconds")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("bounded timeout required")
    if route.get("max_cost_usd") is not None and (
            type(route["max_cost_usd"]) not in (int, float) or not math.isfinite(route["max_cost_usd"]) or route["max_cost_usd"] <= 0):
        raise ValueError("positive cost bound required")
    if provider == "codex" and route.get("max_cost_usd") is not None:
        raise ValueError("Codex adapter cannot enforce a dollar cap; use a time bound")
    limits = {"effort_ceiling": ceiling} if ceiling is not None else {}
    return {**route, "provider": provider, "model": model, "effort": effort, **limits,
            "tier": tier, "signals": sorted(signals), "reason": _text(reason)}


def _ref(value):
    value = _text(value)
    if any(c.isspace() for c in value) or "@" in value.partition("://")[2].partition("/")[0]:
        raise ValueError("references must be single tokens without embedded credentials")
    return value


def _utc(value):
    moment = datetime.fromisoformat(_text(value))
    if moment.tzinfo is None:
        raise ValueError("timezone-aware time required")
    return moment


def check_environment(required, receipt, *, environment_id, auth_context, route, now, max_age_seconds):
    """Pure readiness check of caller-supplied metadata for one execution context; never probes.

    A receipt describes only its own environment and auth context: a blocked sandbox login is not
    an account-wide logout, and it cannot satisfy a dispatch planned for another context.
    """
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise ValueError("exact sanitized readiness receipt required")  # never echo field names or values
    caps, models = receipt["capabilities"], receipt["models"]
    if not isinstance(caps, dict) or not all(
            isinstance(v, dict) and set(v) == {"state", "source_ref"} and v["state"] in STATES
            for v in caps.values()):
        raise ValueError("capabilities need {state: verified|blocked|unknown, source_ref}")
    if not isinstance(models, dict) or not all(
            isinstance(m, dict) and all(isinstance(e, list) and all(isinstance(x, str) for x in e)
                                        for e in m.values()) for m in models.values()):
        raise ValueError("models need {provider: {model: [effort, ...]}}")
    if type(max_age_seconds) not in (int, float) or not 0 < max_age_seconds < math.inf:
        raise ValueError("bounded freshness required")
    if isinstance(required, (str, dict)):
        raise ValueError("required capabilities must be a list of names")
    required = sorted({_text(x) for x in required})
    _utc(receipt["observed_at_utc"])
    _utc(now)
    readiness = {"environment_id": _ref(receipt["environment_id"]), "auth_context": _ref(receipt["auth_context"]),
                 "source_ref": _ref(receipt["source_ref"]),
                 "receipt_sha256": hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest(),
                 "observed_at_utc": receipt["observed_at_utc"], "checked_at_utc": now,
                 "max_age_seconds": max_age_seconds, "required": required,
                 "capabilities": {x: {"state": caps[x]["state"], "source_ref": _ref(caps[x]["source_ref"])}
                                  for x in required if x in caps},
                 "route": {"provider": route["provider"], "model": route["model"], "effort": route["effort"],
                           "supported_efforts": sorted(models.get(route["provider"], {}).get(route["model"], []))}}
    gaps = readiness_gaps(readiness, required=required, environment_id=environment_id,
                          auth_context=auth_context, route=route, now=now)
    return {**readiness, "ready": not gaps, "gaps": gaps}


def readiness_gaps(readiness, *, required, environment_id, auth_context, route, now):
    """Recompute gaps from recorded facts against the dispatch's own needs; never trust a `ready` flag."""
    if not isinstance(readiness, dict) or not READINESS_FIELDS <= set(readiness):
        raise ValueError("readiness record required")
    caps, limit = readiness["capabilities"], readiness["max_age_seconds"]
    if (isinstance(required, (str, dict)) or
            not isinstance(caps, dict) or not all(isinstance(v, dict) for v in caps.values()) or
            type(limit) not in (int, float) or not 0 < limit < math.inf or
            not isinstance(readiness["route"], dict) or not isinstance(readiness["route"].get("supported_efforts"), list)):
        raise ValueError("malformed readiness record")
    age = (_utc(now) - _utc(readiness["observed_at_utc"])).total_seconds()
    states = {x: caps.get(x, {}).get("state", "unknown") for x in {_text(x) for x in required}}
    gaps = {"mismatch": sorted(k for k, v in (("environment_id", environment_id), ("auth_context", auth_context))
                               if readiness[k] != _text(v)),
            "stale": not 0 <= age <= limit,
            "unknown": sorted(x for x, s in states.items() if s not in STATES[:2]),
            "blocked": sorted(x for x, s in states.items() if s == "blocked"),
            "unsupported_route": any(readiness["route"].get(k) != route[k] for k in ("provider", "model", "effort"))
                                 or route["effort"] not in readiness["route"]["supported_efforts"]}
    return {k: v for k, v in gaps.items() if v}


def require_unfrozen(record):
    """A requested takeover (session_handoff) freezes new dispatch and route changes; in-flight results still record."""
    if (record["worker"].get("handoff") or {}).get("state") == "pending":
        raise PermissionError("takeover requested: dispatch and route changes are frozen until release or cancel")


def bind_route(record, route, *, source_pin, decision_ref, change_ref=None, readiness=None,
               required=(), environment_id=None, auth_context=None, now=None):
    """Pin a route on the owned task; a resumed model/source change needs its own receipt.

    Without `readiness` or any declared need/context this is the compatibility path: the route
    carries no environment check. Declaring a need or context without readiness fails closed.
    """
    if readiness is None and (required or environment_id is not None or auth_context is not None or now is not None):
        raise ValueError("declared preflight needs a readiness record; dependent dispatch blocked")
    if record["worker"]["owner"] != "assistant":
        raise PermissionError("human-owned worker")
    require_unfrozen(record)
    if route["provider"] != record["worker"]["kind"]:
        raise ValueError("provider does not match task owner")
    value = {"route": deepcopy(route), "source_pin": _text(source_pin),
             "decision_ref": _text(decision_ref)}
    if readiness is not None:
        gaps = readiness_gaps(readiness, required=required, environment_id=environment_id,
                              auth_context=auth_context, route=route, now=now)
        if gaps:
            raise RuntimeError(f"environment not ready; dependent dispatch blocked: {gaps}")
        value["readiness"] = {k: deepcopy(readiness[k]) for k in sorted(READINESS_FIELDS)}
    old = record["worker"].get("execution_route")
    if old == value:
        return deepcopy(record)
    if any(x["state"] == "uncertain" for x in record.get("outbox", [])):
        raise RuntimeError("reconcile uncertain dispatch before route changes")
    if old and record["worker"].get("session_id") and not change_ref:
        raise ValueError("resumed route/source change requires an explicit change receipt")
    r = deepcopy(record)
    if old:
        r["worker"].setdefault("route_history", []).append({**old, "change_ref": _text(change_ref or decision_ref)})
    r["worker"]["execution_route"] = value
    return r


def _model_match(primary, models, requested):
    """Root primary evidence decides; aggregate usage only proves absence or a sole model.

    Membership of the requested model in mixed usage is never proof: True/False/None = match,
    definite mismatch (including conflicting primaries), unknown.
    """
    if primary:
        return primary == [requested]
    if not models:
        return None
    if requested not in models:
        return False
    return True if models == [requested] else None


def record_execution(record, dispatch_id, execution, parsed, *, receipt_ref, reconciliation_ref=None):
    """Retain diagnostics by hash/ref, not raw content; terminal result is not acceptance."""
    r = deepcopy(record)
    hit = next(x for x in r["outbox"] if x["id"] == dispatch_id)
    requested = hit.get("execution_route")
    if not requested:
        raise ValueError("dispatch has no pinned route")
    sid = parsed.get("session_id")
    previous = r["worker"].get("session_id")
    if hit.get("resume") and (not previous or sid != previous):
        raise ValueError("resume did not return the owned session identity")
    if previous and sid and previous != sid:
        raise ValueError("unexpected replacement session")
    observed = deepcopy(parsed.get("execution", {}))
    models = observed.get("models", [])
    effort = observed.get("effective_effort")
    route = requested["route"]
    model_match = _model_match(observed.get("primary_models") or [], models, route["model"])
    effort_match = (effort == route["effort"]) if effort is not None else None
    receipt = {"receipt_ref": _text(receipt_ref), "session_id": sid,
               "state": execution.state, "exit_code": execution.returncode,
               "pid": execution.pid, "started_at_utc": execution.started_at_utc,
               "finished_at_utc": execution.finished_at_utc,
               "stdout_sha256": hashlib.sha256(execution.stdout.encode()).hexdigest(),
               "stderr_sha256": hashlib.sha256(execution.stderr.encode()).hexdigest(),
               "requested": requested, "observed": observed,
               "model_match": model_match, "effort_match": effort_match,
               "result_received": bool(execution.state == "done" and sid and
                                       not parsed.get("error") and parsed.get("report")),
               "parent_consumed": False}
    if model_match is False or effort_match is False or observed.get("conflicting_efforts"):
        receipt["result_received"] = False
        receipt["route_mismatch"] = True
    old = hit.get("execution")
    if old:
        if old == receipt:
            return r
        if not reconciliation_ref:
            raise ValueError("different execution evidence requires explicit reconciliation")
        hit.setdefault("execution_history", []).append(old)
        receipt["reconciliation_ref"] = _text(reconciliation_ref)
    hit["execution"] = receipt
    r["worker"]["last_execution"] = receipt
    if sid:
        r["worker"]["session_id"] = sid
    # Process completion alone cannot settle a launch without a supported session receipt.
    if sid and execution.state != "uncertain":
        hit["state"] = "sent"
    return r


def consume_result(record, dispatch_id, *, stdout_sha256, receipt_ref):
    r = deepcopy(record)
    hit = next(x for x in r["outbox"] if x["id"] == dispatch_id)
    receipt = hit.get("execution") or {}
    if not receipt.get("result_received") or stdout_sha256 != receipt.get("stdout_sha256"):
        raise ValueError("parent must consume this exact successful result")
    receipt["parent_consumed"] = True
    receipt["parent_readback_ref"] = _text(receipt_ref)
    if r["worker"].get("last_execution", {}).get("receipt_ref") == receipt["receipt_ref"]:
        r["worker"]["last_execution"] = deepcopy(receipt)
    return r
