"""Durable local records for work delegated to worker sessions: pure transitions plus an atomic file store.

Nothing here sends, launches, interrupts or archives anything. Worker, bot and orchestrator text is
data: it can move a status only along the rules below, and it never grants an approval.
"""
import copy
import fcntl
import hashlib
import json
import os
import re
import time
import unicodedata
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from agent_skills.task_contract import assess_completion, digest, validate_packet
from agent_skills.approval_handoff import valid_approval_parts

STATUSES = ("delivered", "accepted", "running", "blocked", "awaiting-worker", "ready-for-review", "verified-done")
# kind: (allowed sources, statuses it may leave, status it enters)
MOVES = {
    "dispatched": ({"adapter"}, {None}, "delivered"),
    "accepted": ({"adapter", "worker"}, {"delivered"}, "accepted"),
    "running": ({"adapter", "worker"}, {"delivered", "accepted", "awaiting-worker"}, "running"),
    "blocked": ({"adapter", "worker"}, {"delivered", "accepted", "running", "awaiting-worker"}, "blocked"),
    "decided": ({"user"}, {"blocked"}, "awaiting-worker"),
    "ready": ({"worker", "verifier"}, {"delivered", "accepted", "running", "awaiting-worker"}, "ready-for-review"),
    "verified": ({"user", "verifier"}, {"ready-for-review"}, "verified-done"),
    "rejected": ({"user", "verifier"}, {"ready-for-review"}, "running"),
    "reopen": ({"user", "verifier"}, {"ready-for-review", "verified-done"}, "running"),
}
# Recorded only: an acknowledgement, idle or heartbeat never means progress or completion.
# "proposal": a thread reply relayed as context; it records what was proposed and decides nothing.
NOTES = {"ack", "idle", "heartbeat", "unavailable", "available", "approval", "proposal"}
# Worker names near the start ("[Codex · s]", "Claude:", "[ClaudeCode]"). A heuristic only: authorship
# can't be proven from text, so anything not opening with a letter or digit is refused too.
AI_MARK = re.compile(r"(claude|codex|assistant|\bbot|\bai\b)", re.I)
CLOCK_LEEWAY = 300  # seconds an event may be ahead of this machine's clock
EXECUTION_STATES = ("not-started", "awaiting-dispatch", "awaiting-readback", "admitted", "running",
                    "pause-requested", "paused", "blocked", "awaiting-reconciliation", "finished")
ACCEPTANCE_STATES = ("unreviewed", "rejected", "ready", "verified", "accepted")
DISPLAY_STATES = ("current", "stale", "unknown")
HISTORY_STAGES = ("pending", "locally-appended", "view-rendered", "index-updated",
                  "published", "readback-verified")
_UNSET = object()


def _coordination(work_item):
    return {"user_goal": None, "constraints": [], "priority_source_ref": None,
            "canonical_issue_ref": work_item, "canonical_owner": None,
            "active_deliverable": None, "obligations": [], "completed_obligations": [],
            "obligation_reconciliations": [], "evidence_cursors": {},
            "decisions": [], "execution_state": "not-started",
            "acceptance_state": "unreviewed", "deployment_state": None,
            "source_publication_state": None,
            "user_delivery_state": "not-delivered",
            "history_publication_state": "not-published",
            "display_sync": {}, "watch_baselines": {}, "contract_consumption": {}}


def _coord(record):
    return record.setdefault("coordination", _coordination(record["work_item"]))


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError(f"invalid {name}")
    return value.strip()


def _hex(value, name, lengths):
    value = _text(value, name)
    if len(value) not in lengths or not re.fullmatch(r"[0-9a-f]+", value):
        raise ValueError(f"invalid {name}")
    return value


def _contract_digest(value):
    fields = {key: value[key] for key in ("id", "revision", "acceptance_ref", "environment",
                                           "changed_criteria", "next_action", "source_ref",
                                           "requested_artifact")}
    return digest(fields)


def bind_task_contract(record, *, user_goal, constraints, priority_source_ref,
                       canonical_issue_ref, canonical_owner, deliverable_id, revision,
                       acceptance_ref, environment, changed_criteria, next_action,
                       source_ref, requested_artifact=None, displaced_state="queued",
                       displaced_reason=None):
    """Bind one active deliverable and preserve any displaced acknowledged obligation."""
    if not isinstance(constraints, list) or not all(isinstance(x, str) and x.strip() for x in constraints):
        raise ValueError("invalid constraints")
    if type(revision) is not int or revision < 1 or displaced_state not in ("queued", "superseded"):
        raise ValueError("invalid task contract revision or displaced state")
    values = {name: _text(value, name) for name, value in (
        ("user_goal", user_goal), ("priority_source_ref", priority_source_ref),
        ("canonical_issue_ref", canonical_issue_ref), ("canonical_owner", canonical_owner),
        ("deliverable_id", deliverable_id), ("acceptance_ref", acceptance_ref),
        ("environment", environment), ("changed_criteria", changed_criteria),
        ("next_action", next_action), ("source_ref", source_ref))}
    values["requested_artifact"] = (_text(requested_artifact, "requested_artifact")
                                      if requested_artifact is not None else None)
    r = copy.deepcopy(record)
    coordination = _coord(r)
    previous = coordination.get("active_deliverable")
    if previous and (previous["id"], previous["revision"]) != (values["deliverable_id"], revision):
        if revision <= previous["revision"]:
            raise ValueError("task contract revision must increase monotonically")
        if displaced_reason is None:
            raise ValueError("displaced deliverable needs a reason")
        obligation = {**copy.deepcopy(previous), "state": displaced_state,
                      "reason": _text(displaced_reason, "displaced_reason"),
                      "source_ref": values["source_ref"]}
        if not any((x["id"], x["revision"]) == (obligation["id"], obligation["revision"])
                   for x in coordination["obligations"]):
            coordination["obligations"].append(obligation)
    elif previous:
        expected = {"id": values["deliverable_id"], "revision": revision,
                    "acceptance_ref": values["acceptance_ref"], "environment": values["environment"],
                    "changed_criteria": values["changed_criteria"], "next_action": values["next_action"],
                    "source_ref": values["source_ref"],
                    "requested_artifact": values["requested_artifact"]}
        if any(previous.get(key) != value for key, value in expected.items()):
            raise ValueError("changed task contract fields require a new revision")
        outer = {"user_goal": values["user_goal"], "constraints": constraints,
                 "priority_source_ref": values["priority_source_ref"],
                 "canonical_issue_ref": values["canonical_issue_ref"],
                 "canonical_owner": values["canonical_owner"]}
        if any(coordination.get(key) != value for key, value in outer.items()):
            raise ValueError("changed task ownership or scope requires a new revision")
        return r  # exact contract replay preserves readback, evidence and split state
    active = {"id": values["deliverable_id"], "revision": revision,
              "acceptance_ref": values["acceptance_ref"], "environment": values["environment"],
              "changed_criteria": values["changed_criteria"], "next_action": values["next_action"],
              "source_ref": values["source_ref"],
              "requested_artifact": values["requested_artifact"]}
    active["contract_digest"] = _contract_digest(active)
    active["readback_ref"] = None
    coordination.update({"user_goal": values["user_goal"], "constraints": constraints.copy(),
                         "priority_source_ref": values["priority_source_ref"],
                         "canonical_issue_ref": values["canonical_issue_ref"],
                         "canonical_owner": values["canonical_owner"],
                         "active_deliverable": active,
                         "execution_state": "awaiting-readback", "acceptance_state": "unreviewed"})
    r["evidence"] = None
    if r.get("status") in ("ready-for-review", "verified-done"):
        r["status"] = "awaiting-worker"
    return r


def acknowledge_task_contract(record, *, deliverable_id, revision, changed_criteria,
                              next_action, environment, receipt_ref,
                              history_revision=None, history_digest=None):
    """Record a worker's exact current-revision readback before accepting new work."""
    r = copy.deepcopy(record)
    coordination = _coord(r)
    active = coordination.get("active_deliverable")
    actual = (deliverable_id, revision, changed_criteria, next_action, environment)
    expected = ((active or {}).get("id"), (active or {}).get("revision"),
                (active or {}).get("changed_criteria"), (active or {}).get("next_action"),
                (active or {}).get("environment"))
    if actual != expected:
        raise ValueError("worker readback does not match the active deliverable revision")
    canonical = r.get("canonical_history")
    if r.get("history_capture") and canonical:
        if ((history_revision, history_digest) !=
                (canonical.get("revision"), canonical.get("digest"))):
            raise ValueError("worker readback must consume the latest canonical history state")
        active["history_readback"] = {
            "revision": history_revision, "digest": history_digest,
            "readback_ref": canonical["readback_ref"]}
    active["readback_ref"] = _text(receipt_ref, "receipt_ref")
    coordination["execution_state"] = "admitted"
    _record_contract_consumption(
        coordination, "dispatch", "tasks.acknowledge_task_contract", active["readback_ref"])
    return r


def current_task_binding(record):
    """Return the tuple a current worker result must echo; this does not dispatch it."""
    active = (record.get("coordination") or {}).get("active_deliverable")
    if not active:
        raise ValueError("no active deliverable")
    packet = record.get("acceptance_packet") or {}
    return {"task_id": record["task_id"], "deliverable_id": active["id"],
            "revision": active["revision"], "contract_digest": active["contract_digest"],
            "next_action": active["next_action"],
            "packet_sha256": packet.get("packet_sha256")}


def result_binding(record, *, deliverable_id, revision, contract_digest=None,
                   task_id=_UNSET, next_action=_UNSET, packet_sha256=_UNSET):
    active = (record.get("coordination") or {}).get("active_deliverable")
    if not active:
        return "unbound"
    if task_id is not _UNSET and task_id != record.get("task_id"):
        return "stale-task"
    if deliverable_id != active["id"]:
        return "stale-deliverable"
    if revision != active["revision"]:
        return "stale-revision"
    if contract_digest != active.get("contract_digest"):
        return "stale-contract"
    if next_action is not _UNSET and next_action != active.get("next_action"):
        return "stale-next-action"
    expected_packet = (record.get("acceptance_packet") or {}).get("packet_sha256")
    if packet_sha256 is not _UNSET and packet_sha256 != expected_packet:
        return "stale-packet"
    if not active.get("readback_ref"):
        return "missing-current-readback"
    canonical = record.get("canonical_history")
    if record.get("history_capture") and canonical and (
            active.get("history_readback", {}).get("revision") != canonical.get("revision") or
            active.get("history_readback", {}).get("digest") != canonical.get("digest")):
        return "stale-history-readback"
    return "current"


def contract_consumption(record):
    """Expose local library calls without claiming that a native host invoked them."""
    empty = {"state": "helper-only-unconsumed", "caller": None,
             "receipt_ref": None, "native_enforcement": False}
    consumed = (record.get("coordination") or {}).get("contract_consumption") or {}
    return {stage: {**empty, **copy.deepcopy(consumed.get(stage, {}))}
            for stage in ("dispatch", "final", "acceptance", "release")}


def _record_contract_consumption(coordination, stage, caller, receipt_ref, outcome="applied"):
    coordination.setdefault("contract_consumption", {})[stage] = {
        "state": "consumed-by-library-caller", "caller": caller,
        "receipt_ref": receipt_ref, "outcome": outcome, "native_enforcement": False}


def _event_result_binding(record, data):
    return result_binding(
        record, task_id=data.get("task_id"), deliverable_id=data.get("deliverable_id"),
        revision=data.get("revision"), contract_digest=data.get("contract_digest"),
        next_action=data.get("next_action"), packet_sha256=data.get("packet_sha256"))


def evidence_page(record, *, source, receipt_ids, has_more):
    """Say whether pagination reached the last consumed receipt before asking for progress."""
    cursor = (record.get("coordination") or {}).get("evidence_cursors", {}).get(source)
    expected = (cursor or {}).get("last_consumed_receipt")
    if expected is None or expected in receipt_ids:
        return "complete"
    return "continue" if has_more is True else "gap"


def complete_obligation(record, *, deliverable_id, revision, completion_ref):
    """Move one displaced obligation to completed without losing its contract identity."""
    r = copy.deepcopy(record)
    coordination = _coord(r)
    matches = [item for item in coordination["obligations"]
               if (item["id"], item["revision"]) == (deliverable_id, revision)]
    if len(matches) != 1:
        raise KeyError("active displaced obligation not found")
    obligation = matches[0]
    coordination["obligations"].remove(obligation)
    completed = {**obligation, "state": "completed",
                 "completion_ref": _text(completion_ref, "completion_ref")}
    coordination["completed_obligations"].append(completed)
    return r


def reconcile_obligation_claim(record, *, deliverable_id, revision, claimed_state, source_ref):
    """A stale narrative cannot reopen a receipt-backed completed obligation."""
    if claimed_state not in ("queued", "running", "blocked", "completed"):
        raise ValueError("invalid obligation claim state")
    r = copy.deepcopy(record)
    coordination = _coord(r)
    completed = next((item for item in coordination["completed_obligations"]
                      if (item["id"], item["revision"]) == (deliverable_id, revision)), None)
    decision = "completion-preserved" if completed and claimed_state != "completed" else "claim-recorded"
    coordination["obligation_reconciliations"].append({
        "id": _text(deliverable_id, "deliverable_id"), "revision": revision,
        "claimed_state": claimed_state, "source_ref": _text(source_ref, "source_ref"),
        "decision": decision})
    return r, decision


def consume_evidence(record, *, source, receipt, observed_at):
    r = copy.deepcopy(record)
    _coord(r)["evidence_cursors"][_text(source, "source")] = {
        "last_consumed_receipt": _text(receipt, "receipt"),
        "observed_at": _text(observed_at, "observed_at")}
    return r


def set_decision_frame(record, *, decision_id, rank, scope, target, prerequisites,
                       mechanism, exposure_frequency, technical_risk,
                       observed_impact, conditional_impact, business_decision,
                       activation_state, priority_source_ref):
    if (not isinstance(prerequisites, list) or
            not all(isinstance(x, str) and x.strip() for x in prerequisites) or
            type(rank) is not int or rank < 1):
        raise ValueError("invalid decision prerequisites")
    allowed = ("not-requested", "pending", "blocked", "applied", "rolled-back")
    if activation_state not in allowed:
        raise ValueError("invalid activation state")
    r = copy.deepcopy(record)
    decision = {name: _text(value, name) for name, value in (
        ("id", decision_id), ("scope", scope), ("target", target), ("mechanism", mechanism),
        ("exposure_frequency", exposure_frequency), ("technical_risk", technical_risk),
        ("observed_impact", observed_impact), ("conditional_impact", conditional_impact),
        ("business_decision", business_decision), ("priority_source_ref", priority_source_ref))}
    decision.update({"rank": rank, "prerequisites": prerequisites.copy(),
                     "activation_state": activation_state})
    decisions = _coord(r).setdefault("decisions", [])
    if any(x["rank"] == rank and x["id"] != decision["id"] for x in decisions):
        raise ValueError("independent decisions need distinct ranks")
    decisions[:] = [x for x in decisions if x["id"] != decision["id"]]
    decisions.append(decision)
    decisions.sort(key=lambda x: (x["rank"], x["id"]))
    return r


def request_pause(record, *, source_ref):
    r = copy.deepcopy(record)
    coordination = _coord(r)
    coordination["execution_state"] = "pause-requested"
    deployment = coordination.get("deployment_state") or {}
    deployment["pause_request_ref"] = _text(source_ref, "source_ref")
    coordination["deployment_state"] = deployment
    return r


def confirm_pause(record, *, execution_owner, receipt_ref):
    r = copy.deepcopy(record)
    coordination = _coord(r)
    if coordination.get("execution_state") != "pause-requested" or execution_owner != coordination.get("canonical_owner"):
        raise ValueError("pause is effective only after the execution owner confirms it")
    coordination["execution_state"] = "paused"
    deployment = coordination.get("deployment_state") or {}
    deployment.update({"pause_state": "confirmed", "pause_ack_ref": _text(receipt_ref, "receipt_ref")})
    coordination["deployment_state"] = deployment
    return r


def release_gate(record, *, head, final_diff_digest, scope, approved_scope, revision,
                 approval_action, approval_target, lock_owner, expected_owner, pause_required):
    """Bind release admission to the final revision, diff, owner lock and confirmed pause."""
    r = copy.deepcopy(record)
    coordination = _coord(r)
    active = coordination.get("active_deliverable") or {}
    reasons = []
    if revision != active.get("revision"):
        reasons.append("stale-revision")
    if result_binding(r, deliverable_id=active.get("id"), revision=revision,
                      contract_digest=active.get("contract_digest")) != "current":
        reasons.append("missing-current-readback")
    if scope != approved_scope:
        reasons.append("scope-mismatch")
    approval = next((x for x in reversed(r.get("approvals", []))
                     if x.get("action") == approval_action and x.get("target") == approval_target and
                     x.get("scope") == approved_scope and x.get("revision") == revision and
                     x.get("contract_digest") == active.get("contract_digest")), None)
    if approval is None:
        reasons.append("approval-missing")
    if coordination.get("acceptance_state") not in ("verified", "accepted"):
        reasons.append("acceptance-not-verified")
    accepted = r.get("evidence") or {}
    if accepted.get("commit") != head:
        reasons.append("accepted-head-mismatch")
    if accepted.get("final_diff_digest") != final_diff_digest:
        reasons.append("accepted-diff-mismatch")
    if lock_owner != expected_owner or expected_owner != coordination.get("canonical_owner"):
        reasons.append("lock-owner-mismatch")
    deployment = coordination.get("deployment_state") or {}
    pause_expected = pause_required is True or bool(deployment.get("pause_request_ref"))
    if pause_expected and (coordination.get("execution_state") != "paused" or
                           not deployment.get("pause_ack_ref")):
        reasons.append("pause-unconfirmed")
    state = {"head": _hex(head, "head", {40, 64}),
             "final_diff_digest": _hex(final_diff_digest, "final_diff_digest", {64}),
             "scope": _text(scope, "scope"), "revision": revision,
             "approval_action": _text(approval_action, "approval_action"),
             "approval_target": _text(approval_target, "approval_target"),
             "approval_ref": (approval or {}).get("ts"),
             "lock_owner": _text(lock_owner, "lock_owner"),
             "pause_state": deployment.get("pause_state", "not-required" if not pause_expected else "unknown"),
             "pause_ack_ref": deployment.get("pause_ack_ref"),
             "gate": "admitted" if not reasons else "blocked", "reasons": reasons}
    coordination["deployment_state"] = state
    _record_contract_consumption(
        coordination, "release", "tasks.release_gate",
        f"release-gate:{state['head']}:{state['final_diff_digest']}", outcome=state["gate"])
    return r, state["gate"]


def set_display_sync(record, *, surface_ref, state, receipt_ref=None):
    if state not in DISPLAY_STATES or (state == "current" and not receipt_ref):
        raise ValueError("invalid display sync state")
    r = copy.deepcopy(record)
    _coord(r)["display_sync"][_text(surface_ref, "surface_ref")] = {
        "state": state, "last_sync_receipt": (_text(receipt_ref, "receipt_ref")
                                                if receipt_ref is not None else None)}
    return r


def set_watch_baseline(record, *, watch_id, scope, digest_value, observed_at, source_ref):
    r = copy.deepcopy(record)
    _coord(r)["watch_baselines"][_text(watch_id, "watch_id")] = {
        "scope": _text(scope, "scope"), "digest": _text(digest_value, "digest"),
        "observed_at": _text(observed_at, "observed_at"),
        "source_ref": _text(source_ref, "source_ref")}
    return r


def watch_changed(record, *, watch_id, digest_value):
    baseline = (record.get("coordination") or {}).get("watch_baselines", {}).get(watch_id)
    return baseline is None or baseline.get("digest") != digest_value


def actionable_priorities(candidates, *, priority_source_ref):
    """Return only explicitly actionable work in the user's stated priority order."""
    if not isinstance(candidates, list):
        raise ValueError("priority candidates must be a list")
    source = _text(priority_source_ref, "priority_source_ref")
    result = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {
                "id", "rank", "action", "immediately_actionable", "waiting_on", "state"}:
            raise ValueError("invalid priority candidate")
        if type(candidate["rank"]) is not int or candidate["rank"] < 1:
            raise ValueError("invalid priority rank")
        if candidate["state"] not in ("pending", "completed", "deferred"):
            raise ValueError("invalid priority state")
        if not isinstance(candidate["waiting_on"], list) or not all(
                isinstance(x, str) and x.strip() for x in candidate["waiting_on"]):
            raise ValueError("invalid priority prerequisites")
        if candidate["immediately_actionable"] is True and not candidate["waiting_on"] and candidate["state"] == "pending":
            result.append({"id": _text(candidate["id"], "id"),
                           "rank": candidate["rank"],
                           "action": _text(candidate["action"], "action"),
                           "priority_source_ref": source})
    return sorted(result, key=lambda item: (item["rank"], item["id"]))


def communication_brief(record, *, priority_candidates, result, remaining, next_owner):
    """Build one concise checkpoint without repeating an already valid approval."""
    if not isinstance(remaining, list) or not all(isinstance(x, str) and x.strip() for x in remaining):
        raise ValueError("remaining work must be a string list")
    coordination = _coord(record)
    decision = pending(record)
    def matches(item):
        required = {key: decision.get(key) for key in (
            "action", "target", "scope", "revision", "contract_digest")
                    if decision.get(key) is not None}
        return all(item.get(key) == value for key, value in required.items())
    satisfied = (approved_parts(record, decision["parts"]) if decision.get("parts") else
                 any(matches(item) for item in record["approvals"]))
    approval_need = None if satisfied or not (decision.get("action") and decision.get("target")) else {
        "need": decision.get("need"), "action": decision["action"], "target": decision["target"],
        "scope": decision.get("scope"), "revision": decision.get("revision")}
    return {"priorities": actionable_priorities(
                priority_candidates, priority_source_ref=coordination.get("priority_source_ref") or "unspecified"),
            "approval_need": approval_need, "result": _text(result, "result"),
            "remaining": remaining.copy(), "next_owner": _text(next_owner, "next_owner")}


def assess_worker_return(record, *, deliverable_id, revision, contract_digest,
                         artifact_kind, artifact_ref, result, remaining, next_owner):
    """Validate the returned artifact without inferring acceptance or delivery."""
    binding = result_binding(record, deliverable_id=deliverable_id, revision=revision,
                             contract_digest=contract_digest)
    active = (record.get("coordination") or {}).get("active_deliverable") or {}
    requested = active.get("requested_artifact")
    if binding != "current":
        return {"status": binding}
    if not isinstance(remaining, list) or not all(isinstance(x, str) and x.strip() for x in remaining):
        raise ValueError("remaining work must be a string list")
    details = {"artifact_kind": _text(artifact_kind, "artifact_kind"),
               "artifact_ref": _text(artifact_ref, "artifact_ref"),
               "result": _text(result, "result"), "remaining": remaining.copy(),
               "next_owner": _text(next_owner, "next_owner")}
    status = "current-artifact" if requested is None or requested == details["artifact_kind"] else "adjacent-output"
    return {"status": status, **details}


def record_user_delivery(record, *, artifact_ref, receipt_ref):
    """Record one verified user delivery; execution or history publication cannot imply it."""
    r = copy.deepcopy(record)
    coordination = _coord(r)
    if coordination.get("acceptance_state") not in ("verified", "accepted"):
        raise ValueError("user delivery requires verified acceptance")
    value = {"artifact_ref": _text(artifact_ref, "artifact_ref"),
             "receipt_ref": _text(receipt_ref, "receipt_ref")}
    prior = coordination.get("user_delivery")
    if prior and prior != value:
        raise ValueError("a different user delivery already exists")
    coordination["user_delivery"] = value
    coordination["user_delivery_state"] = "delivered"
    return r


def record_source_publication(record, *, local_commit, local_receipt,
                              remote_state, remote_receipt=None):
    """Keep a local commit distinct from remote source publication."""
    if remote_state not in {"unpublished", "published"}:
        raise ValueError("remote source state must be unpublished or published")
    if remote_state == "published" and remote_receipt is None:
        raise ValueError("published source requires a remote receipt")
    r = copy.deepcopy(record)
    state = {"local_commit": _hex(local_commit, "local_commit", {40, 64}),
             "local_receipt": _text(local_receipt, "local_receipt"),
             "remote_state": remote_state,
             "remote_receipt": (_text(remote_receipt, "remote_receipt")
                                if remote_receipt is not None else None)}
    prior = _coord(r).get("source_publication_state")
    if prior and (prior["local_commit"] != state["local_commit"] or
                  (prior["remote_state"] == "published" and remote_state != "published")):
        raise ValueError("source publication state cannot replace or regress")
    _coord(r)["source_publication_state"] = state
    return r


def stage_history_checkpoint(record, *, source_id, transition, summary, evidence_refs):
    """Stage sanitized metadata only; this never appends or publishes task history."""
    if not record.get("history_capture"):
        raise ValueError("task has no authorized history capture configuration")
    if transition not in {"start", "decision", "failure", "implementation", "test",
                          "review", "deploy", "handoff", "verification"}:
        raise ValueError("unsupported history checkpoint transition")
    if not isinstance(evidence_refs, list) or not all(isinstance(x, str) and x.strip() for x in evidence_refs):
        raise ValueError("history evidence references must be a string list")
    source = _text(source_id, "source_id")
    event_id = "coord-" + hashlib.sha256((record["task_id"] + "\0" + source).encode()).hexdigest()[:32]
    r = copy.deepcopy(record)
    existing = next((x for x in r["history_outbox"] if x["event_id"] == event_id), None)
    item = {"event_id": event_id, "transition": transition, "summary": _text(summary, "summary"),
            "evidence_refs": evidence_refs.copy(), "stage": "pending", "receipts": {}}
    if existing:
        if any(existing.get(key) != item[key] for key in (
                "event_id", "transition", "summary", "evidence_refs")):
            raise ValueError("history checkpoint id already names different content")
        return r, event_id
    r["history_outbox"].append(item)
    _coord(r)["history_publication_state"] = "not-published"
    return r, event_id


def history_checkpoint_packet(record, *, event_id, expected_digest, event):
    """Bind an owner append packet to the exact staged checkpoint and task authorization."""
    config = record.get("history_capture") or {}
    item = next((x for x in record.get("history_outbox", []) if x["event_id"] == event_id), None)
    if not item or not isinstance(event, dict):
        raise ValueError("staged history checkpoint and event are required")
    expected = {"event_id": item["event_id"], "task_id": record["task_id"],
                "record_owner": config.get("record_owner"), "kind": item["transition"],
                "summary": item["summary"], "approval_ref": config.get("authorization_ref")}
    if any(event.get(key) != value for key, value in expected.items()):
        raise ValueError("history event does not match the staged checkpoint")
    if event.get("source_ref") not in item["evidence_refs"]:
        raise ValueError("history event source is not staged evidence")
    binding = {**expected, "evidence_refs": item["evidence_refs"].copy()}
    return {"authorization_ref": config["authorization_ref"],
            "expected_digest": _hex(expected_digest, "expected_digest", {64}),
            "binding": binding, "event": copy.deepcopy(event)}


def mark_history_checkpoint(record, *, event_id, stage, receipt_ref, digest_value=None):
    """Advance one checkpoint through append, render, index, publish and readback stages."""
    if stage not in HISTORY_STAGES[1:]:
        raise ValueError("invalid history stage")
    r = copy.deepcopy(record)
    item = next((x for x in r.get("history_outbox", []) if x["event_id"] == event_id), None)
    if not item:
        raise KeyError("unknown history checkpoint")
    current = HISTORY_STAGES.index(item["stage"])
    target = HISTORY_STAGES.index(stage)
    if target < current:
        raise ValueError("history checkpoint cannot move backward")
    if target > current + 1:
        raise ValueError("history checkpoint stages cannot be skipped")
    receipt = _text(receipt_ref, "receipt_ref")
    supplied_digest = _hex(digest_value, "digest", {64}) if digest_value is not None else None
    if stage == "locally-appended" and supplied_digest is None:
        raise ValueError("local history append requires its 64-hex digest")
    if current >= HISTORY_STAGES.index("locally-appended") and not item.get("digest"):
        raise ValueError("history checkpoint is missing its append digest")
    if item.get("digest") and supplied_digest is not None and item["digest"] != supplied_digest:
        raise ValueError("history digest does not match the local append")
    if target == current:
        if (item["receipts"].get(stage) != receipt or
                (supplied_digest is not None and item.get("digest") != supplied_digest)):
            raise ValueError("history stage replay has a different receipt")
        return r
    item["stage"] = stage
    item["receipts"][stage] = receipt
    if stage == "locally-appended":
        item["digest"] = supplied_digest
    coordination = _coord(r)
    if stage == "published":
        coordination["history_publication_state"] = "published-unverified"
    elif stage == "readback-verified":
        coordination["history_publication_state"] = "readback-verified"
    return r


def consume_history_readback(record, *, task_id, record_owner, revision, digest_value,
                             event_ids, readback_ref):
    """Bind a fresh canonical read to resume; retrieval is not independent acceptance."""
    config = record.get("history_capture") or {}
    if task_id != record.get("task_id") or record_owner != config.get("record_owner"):
        raise ValueError("history readback task or owner mismatch")
    if type(revision) is not int or revision < 1 or not isinstance(event_ids, list) or not event_ids:
        raise ValueError("invalid history readback")
    digest_value = _hex(digest_value, "digest", {64})
    latest = record.get("history_outbox", [])[-1] if record.get("history_outbox") else None
    if latest and (latest["event_id"] not in event_ids or
                   latest["stage"] not in {"published", "readback-verified"}):
        raise ValueError("fresh readback must contain the latest published checkpoint")
    if latest and latest.get("digest") != digest_value:
        raise ValueError("fresh readback digest does not match the local append")
    r = copy.deepcopy(record)
    if latest:
        r = mark_history_checkpoint(r, event_id=latest["event_id"], stage="readback-verified",
                                    receipt_ref=readback_ref, digest_value=digest_value)
    r["canonical_history"] = {"task_id": task_id, "record_owner": record_owner,
                              "revision": revision, "digest": digest_value,
                              "event_ids": event_ids.copy(),
                              "readback_ref": _text(readback_ref, "readback_ref")}
    return r


def new_task(task_id, work_item, *, worker_kind, owner, repo, worktree=None, source_thread=None,
             acceptance_packet=None, history_capture=None):
    """A fresh record; `owner` is "assistant" (this layer started it) or "human" (never driven)."""
    if owner not in ("assistant", "human"):
        raise ValueError(f"owner must be assistant or human, got {owner!r}")
    if acceptance_packet is not None:
        validate_packet(acceptance_packet)
        if acceptance_packet["task_id"] != task_id:
            raise ValueError("acceptance packet belongs to another task")
    if history_capture is not None:
        if owner != "assistant" or not isinstance(history_capture, dict) or set(history_capture) != {
                "record_owner", "authorization_ref", "history_repo"}:
            raise ValueError("history capture requires explicit owner, authorization and repository")
        for key in ("record_owner", "authorization_ref", "history_repo"):
            _text(history_capture[key], key)
        if not Path(history_capture["history_repo"]).is_absolute():
            raise ValueError("history repository must be an absolute path")
    return {"task_id": task_id, "work_item": work_item, "status": None,
            "worker": {"kind": worker_kind, "session_id": None, "owner": owner, "state": "unknown"},
            "repo": repo, "worktree": worktree, "source_thread": source_thread,
            "evidence": None, "acceptance_packet": acceptance_packet, "pending_decision": None, "approvals": [], "outbox": [],
            "seen": [], "last_change_ts": None, "history": [], "counts": {"duplicates": 0, "unneeded_asks": 0},
            "coordination": _coordination(work_item),
            **({"history_capture": copy.deepcopy(history_capture), "history_outbox": [],
                "canonical_history": None} if history_capture else {})}


def bind_packet(record, value):
    """Attach a pinned acceptance envelope; a new revision invalidates old readiness."""
    validate_packet(value)
    if value["task_id"] != record["task_id"]:
        raise ValueError("acceptance packet belongs to another task")
    r = copy.deepcopy(record)
    previous = r.get("acceptance_packet")
    if previous and previous["packet_sha256"] != value["packet_sha256"]:
        r["evidence"] = None
        r["acceptance_assessment"] = None
        r["acceptance_completion_report"] = None
        r["acceptance_review_sha256"] = None
        if r["status"] in ("ready-for-review", "verified-done"):
            r["status"] = "awaiting-worker"
            r["resume_after"] = len(r["outbox"])
    r["acceptance_packet"] = value
    return r


def _from_user(data):
    """A user event counts only from the user's own chat turn. A thread message, even one that looks
    typed on the user's account, may have been posted by a worker sharing that account, so it arrives
    as a `proposal` and never as the user's word; so may anything carrying an AI prefix."""
    text = unicodedata.normalize("NFKC", data.get("text") or "").strip()
    return (data.get("channel") == "chat" and bool(text) and text[0].isalnum() and text[0].isascii()
            and not AI_MARK.search(text[:40]))


def direct_reply_observation(record, *, task_id, session_id):
    """Identify a reply's task; observation never authenticates the author or admits approval."""
    return ("reply-in-task-needs-verification" if task_id == record["task_id"] and session_id and
            session_id == record["worker"].get("session_id") else "other-task")


def apply(record, event):
    """Return (new record, outcome): applied, noted, duplicate, stale, ignored, unsupported or rejected.

    Events: {id (stable), task, ts, source, kind, data?}. Sources: adapter (local launch receipts),
    worker (its own report), orchestrator (the coordinating assistant's reply), verifier (this layer's
    own check of the evidence), user (the user's chat turn, the only source of decisions and approvals).
    A repeated id is a no-op once it applied or was noted; an ignored, stale or rejected event is
    not remembered, so replaying it after the events it waited for can still apply it. A status move older than the last change is stale, so a late or
    replayed report cannot undo a newer one. Moves outside MOVES are ignored, never forced.
    """
    if event.get("task") != record["task_id"]:
        return record, "rejected"
    if event["id"] in record["seen"]:
        return record, "duplicate"
    ts = _ts(event["ts"])
    r = copy.deepcopy(record)
    kind, source, data = event["kind"], event["source"], event.get("data") or {}
    outcome = _apply(r, kind, source, data, ts, event["id"])
    if outcome in ("applied", "noted"):
        r["seen"].append(event["id"])
    elif any(h["id"] == event["id"] and h["outcome"] == outcome for h in r["history"]):
        return record, outcome  # the same unapplied replay again: nothing new to keep
    r["history"].append({"id": event["id"], "kind": kind, "source": source, "ts": str(ts), "outcome": outcome})
    return r, outcome


def _ts(value):
    """Epoch seconds, not ahead of this clock; anything else would freeze or poison the stale check."""
    ts = Decimal(str(value))
    if not ts.is_finite() or not Decimal("1e9") <= ts <= Decimal(time.time() + CLOCK_LEEWAY):
        raise ValueError(f"event ts must be epoch seconds, got {value!r}")
    return ts


def _apply(r, kind, source, data, ts, event_id):
    if source == "user" and not _from_user(data):
        return "rejected"
    if kind in NOTES:
        if kind in ("unavailable", "available") and source == "adapter":
            r["worker"]["state"] = kind
        if kind == "approval":
            if source != "user" or not (data.get("action") and data.get("target") and data.get("scope")):
                return "rejected"
            active = (r.get("coordination") or {}).get("active_deliverable") or {}
            if active and (data.get("revision"), data.get("contract_digest")) != (
                    active.get("revision"), active.get("contract_digest")):
                return "rejected"
            r["approvals"].append({k: data[k] for k in ("action", "target", "scope")} | {
                "ts": str(ts), "revision": data.get("revision"),
                "contract_digest": data.get("contract_digest")})
        if kind == "proposal":
            if source != "thread":
                return "rejected"
            if r["last_change_ts"] is not None and ts <= Decimal(r["last_change_ts"]):
                return "stale"  # made before the current decision was asked
            if r.get("proposal") and ts <= Decimal(r["proposal"]["ts"]):
                return "stale"  # an older reply arriving late never replaces a newer one
            r["proposal"] = {"approve": data.get("approve") is True, "action": data.get("action"),
                             "target": data.get("target"), "ts": str(ts)}
        return "noted"
    if kind not in MOVES:
        return "ignored"
    sources, leaves, enters = MOVES[kind]
    if r["last_change_ts"] is not None and ts <= Decimal(r["last_change_ts"]):
        return "stale"
    if source not in sources or r["status"] not in leaves:
        return "ignored"
    active = (r.get("coordination") or {}).get("active_deliverable")
    if (source in ("worker", "verifier") and kind in ("running", "blocked", "ready", "verified") and
            any(item.get("state") == "uncertain" for item in r.get("outbox", []))):
        return "unsupported"
    if active and kind in ("running", "blocked", "ready", "verified"):
        if _event_result_binding(r, data) != "current":
            return "unsupported"
    if kind in ("running", "blocked", "ready") and r["status"] == "awaiting-worker" and not any(
        o["state"] == "sent" and event_id.startswith(o["id"] + ":")
        for o in r["outbox"][r.get("resume_after", len(r["outbox"])):]
    ):
        return "unsupported"  # require this report's current resume receipt
    packet = r.get("acceptance_packet")
    if kind == "ready" and packet:
        if source != "verifier" or not isinstance(data.get("completion_report"), dict) or not isinstance(data.get("verifier_report"), dict):
            return "unsupported"
        assessment = assess_completion(packet, data["completion_report"], data["verifier_report"],
                                       artifact_root=r.get("worktree"))
        if (assessment["status"] != "evidence-complete-awaiting-acceptance" or
                any(c.get("evidence_binding") and c["evidence_binding"]["candidate"] != data.get("commit")
                    for c in packet["acceptance"])):
            return "unsupported"
    if kind == "ready" and not (data.get("commit") and data.get("tests")):
        return "unsupported"  # a completion claim without a commit and tests is not ready for review
    if active and kind == "ready":
        try:
            _hex(data.get("commit"), "commit", {40, 64})
            _hex(data.get("final_diff_digest"), "final_diff_digest", {64})
        except ValueError:
            return "unsupported"
        if active.get("requested_artifact"):
            try:
                worker_return = assess_worker_return(
                    r, deliverable_id=data.get("deliverable_id"), revision=data.get("revision"),
                    contract_digest=data.get("contract_digest"),
                    artifact_kind=data.get("artifact_kind"), artifact_ref=data.get("artifact_ref"),
                    result=data.get("result"), remaining=data.get("remaining"),
                    next_owner=data.get("next_owner"))
            except ValueError:
                return "unsupported"
            if worker_return["status"] != "current-artifact":
                return "unsupported"
    if kind == "decided":
        p = pending(r)
        if data.get("approve") is True:
            # An approval: both must have been asked, and the yes must name both exactly.
            if not (p["action"] and p["target"]) or (data.get("action"), data.get("target")) != (p["action"], p["target"]):
                return "rejected"
            if p.get("parts") and not approved_parts(r, p["parts"]):
                return "rejected"  # no positive decision until every distinct scope is authenticated
        elif data.get("action") or data.get("target"):
            return "rejected"  # an answer (a no, a redirect, "name the target first") names nothing to approve
    if kind == "verified" and packet:
        if (source != "verifier" or not isinstance(data.get("verifier_report"), dict) or
                digest(data["verifier_report"]) != r.get("acceptance_review_sha256") or
                (r.get("acceptance_assessment") or {}).get("status") != "evidence-complete-awaiting-acceptance" or
                assess_completion(packet, r.get("acceptance_completion_report"), data["verifier_report"],
                                  artifact_root=r.get("worktree"))["status"] != "evidence-complete-awaiting-acceptance"):
            return "unsupported"
    if kind == "verified":
        ev = r["evidence"] or {}
        if (data.get("commit") != ev.get("commit") or data.get("tests_passed") is not True or
                (active and data.get("final_diff_digest") != ev.get("final_diff_digest"))):
            return "ignored"
    if kind == "dispatched" and data.get("session_id"):
        r["worker"]["session_id"] = data["session_id"]
    if kind == "blocked":
        parts = data.get("parts")
        if parts is not None and (not valid_approval_parts(parts) or
                                  (parts[0]["action"], parts[0]["target"]) !=
                                  (data.get("action"), data.get("target"))):
            return "rejected"
        r["pending_decision"] = {"need": data.get("need") or "unspecified",
                                 "action": data.get("action"), "target": data.get("target"),
                                 **({"scope": data.get("scope")} if data.get("scope") else {}),
                                 **({"revision": data.get("revision"),
                                     "contract_digest": data.get("contract_digest")}
                                    if data.get("revision") is not None else {}),
                                 **({"parts": copy.deepcopy(parts)} if parts is not None else {})}
        if data.get("action") and approved(r, data["action"], data.get("target")):
            r.setdefault("counts", {}).setdefault("unneeded_asks", 0)
            r["counts"]["unneeded_asks"] += 1  # asked again for something the user already approved
    if kind in ("blocked", "decided"):
        r["proposal"] = None  # a proposal answers the decision it was made on, not a later one
    if kind == "decided":
        if data.get("approve") is True:
            r["approvals"].append({"action": data["action"], "target": data.get("target"),
                                   "scope": "the pending decision", "ts": str(ts)})
        r["pending_decision"] = None
        r["resume_after"] = len(r["outbox"])  # only a later resume receipt can prove new execution
    if kind == "ready" and packet:
        r["acceptance_assessment"] = assessment
        r["acceptance_completion_report"] = data["completion_report"]
        r["acceptance_review_sha256"] = digest(data["verifier_report"])
    if kind == "ready":
        r["evidence"] = {k: data.get(k) for k in (
            "commit", "final_diff_digest", "tests", "summary")}
        if active and active.get("requested_artifact"):
            r["worker_return"] = worker_return
    if kind == "reopen":
        r["evidence"] = None
        r["acceptance_assessment"] = None
        r["acceptance_completion_report"] = None
        r["acceptance_review_sha256"] = None
    coordination = _coord(r)
    if active and kind == "ready":
        _record_contract_consumption(
            coordination, "final", "tasks.apply:ready", event_id)
    elif active and kind == "verified":
        _record_contract_consumption(
            coordination, "acceptance", "tasks.apply:verified", event_id)
    if kind in ("dispatched", "accepted"):
        coordination["execution_state"] = ("awaiting-readback" if active and
                                             not active.get("readback_ref") else "admitted")
    elif kind == "running":
        coordination["execution_state"] = "running"
    elif kind == "blocked":
        coordination["execution_state"] = "blocked"
    elif kind == "decided":
        coordination["execution_state"] = "awaiting-dispatch"
    elif kind == "ready":
        coordination["execution_state"] = "finished"
        coordination["acceptance_state"] = "ready"
    elif kind == "verified":
        coordination["execution_state"] = "finished"
        coordination["acceptance_state"] = "accepted" if source == "user" else "verified"
    elif kind == "rejected":
        coordination["execution_state"] = "running"
        coordination["acceptance_state"] = "rejected"
    elif kind == "reopen":
        coordination["execution_state"] = "running"
        coordination["acceptance_state"] = "unreviewed"
    r["status"], r["last_change_ts"] = enters, str(ts)
    return "applied"


def pending(record):
    """The pending decision as {need, action, target}; older records stored only the question text."""
    p = record.get("pending_decision")
    if p is None or isinstance(p, dict):
        return {"need": None, "action": None, "target": None, "scope": None,
                "revision": None, "contract_digest": None, **(p or {})}
    return {"need": str(p), "action": None, "target": None, "scope": None,
            "revision": None, "contract_digest": None}


def approved(record, action, target):
    """True only for a recorded user approval of this exact action and target (both named)."""
    return bool(action and target) and any(
        a.get("action") == action and a.get("target") == target for a in record["approvals"])


def approved_parts(record, parts):
    """Every distinct pending part was admitted for the current contract binding."""
    decision = pending(record)
    binding = {key: decision.get(key) for key in ("revision", "contract_digest")
               if decision.get(key) is not None}
    return valid_approval_parts(parts) and all(any(
        (a.get("action"), a.get("target"), a.get("scope")) ==
        (p["action"], p["target"], p["scope"]) and
        all(a.get(key) == value for key, value in binding.items())
        for a in record["approvals"])
        for p in parts)


def begin_dispatch(record, dispatch_id, *, resume):
    """Mark a launch uncertain before it happens; refuses while another is unresolved or the session is human-owned."""
    if record["worker"]["owner"] != "assistant":
        raise PermissionError("human-owned session: report to the user, never dispatch to, resume or interrupt it")
    if any(o["id"] == dispatch_id for o in record["outbox"]):
        raise ValueError(f"dispatch id {dispatch_id} already used: pick a new one")
    if any(o["state"] == "uncertain" for o in record["outbox"]):
        raise RuntimeError("an earlier dispatch is unresolved: reconcile it before any new one")
    r = copy.deepcopy(record)
    r["outbox"].append({"id": dispatch_id, "state": "uncertain"})
    return r


def settle_dispatch(record, dispatch_id, state):
    """state: sent (receipt or transcript found), not-sent (proven absent) or unknown (stays uncertain)."""
    if state not in ("sent", "not-sent", "unknown"):
        raise ValueError(state)
    r = copy.deepcopy(record)
    hit = [o for o in r["outbox"] if o["id"] == dispatch_id]
    if not hit:
        raise KeyError(f"no dispatch {dispatch_id} on task {record['task_id']}")
    if state != "unknown":
        hit[0]["state"] = state
    return r


def attention(records):
    """What the user should hear about: decisions, reviews, unavailable workers, unresolved launches."""
    out = []
    for r in records:
        uncertain = any(o["state"] == "uncertain" for o in r["outbox"])
        if r["status"] == "blocked" and not uncertain:
            p = pending(r)
            satisfied = approved_parts(r, p["parts"]) if p.get("parts") else approved(r, p["action"], p["target"])
            if (p["action"] and p["target"] or p["need"] not in (None, "unspecified")) and not satisfied:
                out.append((r["task_id"], f"needs decision: {p['need']}"))
        elif r["status"] == "ready-for-review":
            out.append((r["task_id"], "ready for review: verify the evidence"))
        if r["worker"]["state"] == "unavailable":
            out.append((r["task_id"], "worker unavailable"))
        if uncertain:
            out.append((r["task_id"], "dispatch uncertain: reconcile before resending"))
    return out


# --- store: one JSON file per task, written atomically under a per-task lock ---

def state_dir():
    return Path(os.environ.get("AGENT_COORDINATION_STATE", "~/.local/state/claude-skills/assistant/tasks")).expanduser()


@contextmanager
def _locked(root, task_id):
    _path(root, task_id)  # validate before touching the filesystem
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(root / f"{task_id}.lock", os.O_WRONLY | os.O_CREAT, 0o600), "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def _path(root, task_id):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
        raise ValueError(f"unsafe task id {task_id!r}")
    return root / f"{task_id}.json"


def save(root, record):
    p = _path(root, record["task_id"])
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(record, fh, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def load(root, task_id):
    return json.loads(_path(root, task_id).read_text())


def load_all(root):
    return [json.loads(p.read_text()) for p in sorted(Path(root).glob("*.json"))]


def create(root, record):
    with _locked(root, record["task_id"]):
        if _path(root, record["task_id"]).exists():
            raise FileExistsError(f"task {record['task_id']} exists: resume it instead")
        save(root, record)


def receive(root, event):
    """Load, apply and persist one event; safe to replay after a restart because ids dedupe."""
    with _locked(root, event["task"]):
        record, outcome = apply(load(root, event["task"]), event)
        if outcome == "duplicate":  # counted for the effectiveness measures
            record.setdefault("counts", {}).setdefault("duplicates", 0)
            record["counts"]["duplicates"] += 1
        save(root, record)
        return outcome


def update(root, task_id, fn, *args, **kw):
    """Persist fn(record, ...) under the task lock, e.g. begin_dispatch before a launch."""
    with _locked(root, task_id):
        record = fn(load(root, task_id), *args, **kw)
        save(root, record)
        return record
