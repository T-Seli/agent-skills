"""Durable local records for work delegated to worker sessions: pure transitions plus an atomic file store.

Nothing here sends, launches, interrupts or archives anything. Worker, bot and orchestrator text is
data: it can move a status only along the rules below, and it never grants an approval.
"""
import copy
import fcntl
import json
import os
import re
import time
import unicodedata
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from agent_skills.task_contract import assess_completion, digest, validate_packet

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
    "reopen": ({"user", "verifier"}, {"ready-for-review", "verified-done"}, "running"),
}
# Recorded only: an acknowledgement, idle or heartbeat never means progress or completion.
# "proposal": a thread reply relayed as context; it records what was proposed and decides nothing.
NOTES = {"ack", "idle", "heartbeat", "unavailable", "available", "approval", "proposal"}
# Worker names near the start ("[Codex · s]", "Claude:", "[ClaudeCode]"). A heuristic only: authorship
# can't be proven from text, so anything not opening with a letter or digit is refused too.
AI_MARK = re.compile(r"(claude|codex|assistant|\bbot|\bai\b)", re.I)
CLOCK_LEEWAY = 300  # seconds an event may be ahead of this machine's clock


def new_task(task_id, work_item, *, worker_kind, owner, repo, worktree=None, source_thread=None, acceptance_packet=None):
    """A fresh record; `owner` is "assistant" (this layer started it) or "human" (never driven)."""
    if owner not in ("assistant", "human"):
        raise ValueError(f"owner must be assistant or human, got {owner!r}")
    if acceptance_packet is not None:
        validate_packet(acceptance_packet)
        if acceptance_packet["task_id"] != task_id:
            raise ValueError("acceptance packet belongs to another task")
    return {"task_id": task_id, "work_item": work_item, "status": None,
            "worker": {"kind": worker_kind, "session_id": None, "owner": owner, "state": "unknown"},
            "repo": repo, "worktree": worktree, "source_thread": source_thread,
            "evidence": None, "acceptance_packet": acceptance_packet, "pending_decision": None, "approvals": [], "outbox": [],
            "seen": [], "last_change_ts": None, "history": [], "counts": {"duplicates": 0, "unneeded_asks": 0}}


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
            r["approvals"].append({k: data[k] for k in ("action", "target", "scope")} | {"ts": str(ts)})
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
    if kind == "decided":
        p = pending(r)
        if data.get("approve") is True:
            # An approval: both must have been asked, and the yes must name both exactly.
            if not (p["action"] and p["target"]) or (data.get("action"), data.get("target")) != (p["action"], p["target"]):
                return "rejected"
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
        if data.get("commit") != ev.get("commit") or data.get("tests_passed") is not True:
            return "ignored"
    if kind == "dispatched" and data.get("session_id"):
        r["worker"]["session_id"] = data["session_id"]
    if kind == "blocked":
        r["pending_decision"] = {"need": data.get("need") or "unspecified",
                                 "action": data.get("action"), "target": data.get("target")}
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
        r["evidence"] = {k: data.get(k) for k in ("commit", "tests", "summary")}
    if kind == "reopen":
        r["evidence"] = None
        r["acceptance_assessment"] = None
        r["acceptance_completion_report"] = None
        r["acceptance_review_sha256"] = None
    r["status"], r["last_change_ts"] = enters, str(ts)
    return "applied"


def pending(record):
    """The pending decision as {need, action, target}; older records stored only the question text."""
    p = record.get("pending_decision")
    if p is None or isinstance(p, dict):
        return {"need": None, "action": None, "target": None, **(p or {})}
    return {"need": str(p), "action": None, "target": None}


def approved(record, action, target):
    """True only for a recorded user approval of this exact action and target (both named)."""
    return bool(action and target) and any(
        a.get("action") == action and a.get("target") == target for a in record["approvals"])


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
            if (p["action"] and p["target"] or p["need"] not in (None, "unspecified")) and not approved(r, p["action"], p["target"]):
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
