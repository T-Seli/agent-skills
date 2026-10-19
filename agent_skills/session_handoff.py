"""Pure route, checkpoint and takeover contract on the existing task worker record.

Nothing here launches a process, sends a prompt, reads private session storage, discovers
desktop sessions or grants access. Receipts and the recorded writer are cooperative evidence,
not a distributed lock: they cannot exclude a writer that ignores this record.
"""
from copy import deepcopy
import uuid

from .task_checkpoint import _time
from .worker_execution import STATES, _ref

PROCESS_STATES = ("running", "idle", "exited", "unknown")
CAPABILITY_FIELDS = {"provider", "host_ref", "session_ref", "workspace_ref", "action", "state",
                     "source_ref", "observed_at_utc"}
SOURCE_FIELDS = {"session_ref", "id_kind", "workspace_ref", "repo_ref", "branch", "head", "pushed"}
DESTINATION_FIELDS = {"workspace_ref", "repo_ref", "branch", "head", "dirty"}
OBSERVATION_FIELDS = {"session_ref", "process_state", "source_ref", "observed_at_utc"}
CHECKPOINT_FIELDS = {"session_ref", "head", "receipt_ref", "observed_at_utc"}
DESKTOP = "local-desktop"

# Documented routes only; anything absent is unsupported, never discovered or guessed.
# same-session: the destination continues the identical local session after the origin writer exits.
# context-copy: the destination gets a local copy; later local work does not sync to the source.
# diff-apply: only the produced diff moves; no conversation continues.
_SAME = {"continuity": "same-session", "id_kind": "local-uuid", "quiescent": ["exited"],
         "same_workspace": True, "clean": False, "pushed": False}
ROUTES = {
    ("claude", "local-cli", "local-cli"): {**_SAME, "instruction": "claude --resume {session}"},
    ("claude", "local-cli", DESKTOP): {**_SAME, "instruction": "claude --desktop --resume {session}"},
    ("claude", DESKTOP, "local-cli"): {**_SAME, "instruction": "claude --resume {session}"},
    # No CLI command or link exists; only a host that can read and open this exact thread offers it.
    ("codex", "local-cli", DESKTOP): {**_SAME, "capability": "thread-open",
                                      "instruction": "use the supported host thread-open action for the verified session {session}"},
    ("claude", "cloud", "local-cli"): {"continuity": "context-copy", "id_kind": "cloud-id",
                                       "quiescent": ["idle", "exited"], "same_workspace": False,
                                       "clean": True, "pushed": True,
                                       "instruction": "claude --teleport {session}"},
    ("codex", "local-cli", "local-cli"): {**_SAME, "instruction": "codex resume {session}"},
    ("codex", "cloud", "local-cli"): {"continuity": "diff-apply", "id_kind": "cloud-id",
                                      "quiescent": ["idle", "exited"], "same_workspace": False,
                                      "clean": True, "pushed": False,
                                      "instruction": "codex cloud apply {session}"},
}


def plan_handoff(provider, origin, destination):
    route = ROUTES.get((provider, origin, destination))
    if route is None:
        raise ValueError("unsupported route: no documented handoff; do not discover sessions or invent flags")
    return {"provider": provider, "origin": origin, "destination": destination, **deepcopy(route),
            "visual_confirmation": "pending" if destination == DESKTOP else "not-applicable"}


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"exact {label} required")
    return deepcopy(value)


def _session_ref(value, id_kind):
    value = _ref(value)
    is_uuid = False
    try:
        is_uuid = str(uuid.UUID(value)) == value.lower()
    except ValueError:
        pass
    # A cloud ID is not a local resume target and vice versa; neither is inferred from the other.
    if is_uuid != (id_kind == "local-uuid"):
        raise ValueError("session identity does not match the route's id kind")
    return value


def _handoff(record, *states):
    h = record["worker"].get("handoff")
    if not h or h["state"] not in states:
        raise RuntimeError(f"handoff must be {' or '.join(states)}")
    return h


def _capability(route, source, receipt, requested_at_utc, host_ref):
    """Bind a caller-supplied host read/open receipt to this exact host and session; absent or mismatched holds."""
    if receipt is None:
        raise RuntimeError("held: no host capability receipt; route unavailable in this environment")
    receipt = _exact(receipt, CAPABILITY_FIELDS, "host capability receipt")
    for key in ("host_ref", "source_ref"):
        receipt[key] = _ref(receipt[key])
    if receipt["state"] not in STATES:
        raise ValueError("capability state must be verified|blocked|unknown")
    gaps = [k for k, v in (("provider", route["provider"]), ("host_ref", host_ref), ("session_ref", source["session_ref"]),
                           ("workspace_ref", source["workspace_ref"]), ("action", route["capability"]),
                           ("state", "verified")) if receipt[k] != v]
    if _time(receipt["observed_at_utc"]) < _time(requested_at_utc):
        gaps.append("stale")
    if gaps:
        raise RuntimeError(f"held: host capability receipt mismatch {gaps}; route unavailable in this environment")
    return receipt


def request_takeover(record, *, provider, origin, destination, source, requested_ref, requested_at_utc,
                     capability=None, host_ref=None):
    """Record the human's takeover request on the owned assistant session; one writer claim at a time."""
    worker = record["worker"]
    if worker["owner"] != "assistant":
        raise PermissionError("not an assistant-owned session; nothing to take over")
    route = plan_handoff(provider, origin, destination)
    source = _exact(source, SOURCE_FIELDS, "source identity")
    if source["id_kind"] != route["id_kind"]:
        raise ValueError("session identity does not match the route's id kind")
    source["session_ref"] = _session_ref(source["session_ref"], route["id_kind"])
    if provider != worker["kind"] or not worker.get("session_id") or source["session_ref"] != worker["session_id"]:
        raise ValueError("source is not the owned session")
    for key in ("workspace_ref", "repo_ref"):
        source[key] = _ref(source[key])
    _time(requested_at_utc)
    value = {"state": "pending", "route": route, "source": source,
             "requested_ref": _ref(requested_ref), "requested_at_utc": requested_at_utc}
    if route.get("capability"):
        # The caller names the intended host; the same UUID and path elsewhere must not authorize it.
        if host_ref is None:
            raise ValueError("native host route needs the caller's expected host")
        value["expected_host_ref"] = _ref(host_ref)
        value["capability"] = _capability(route, source, capability, requested_at_utc, value["expected_host_ref"])
    elif capability is not None or host_ref is not None:
        raise ValueError("this route takes no host capability receipt or expected host")
    old = worker.get("handoff")
    if old and old["state"] == "pending":
        if old == value:
            return deepcopy(record)
        raise RuntimeError("a takeover is already pending; one writer claim at a time")
    r = deepcopy(record)
    if old:
        r["worker"].setdefault("handoff_history", []).append(old)
    r["worker"]["handoff"] = value
    return r


def _quiescence_gaps(route, *, writer, owned, observation, checkpoint, after):
    observation = _exact(observation, OBSERVATION_FIELDS, "process observation")
    checkpoint = _exact(checkpoint, CHECKPOINT_FIELDS, "saved checkpoint")
    if observation["process_state"] not in PROCESS_STATES:
        raise ValueError("process state must be running|idle|exited|unknown")
    _ref(observation["source_ref"])
    _ref(checkpoint["receipt_ref"])
    seen, saved = _time(observation["observed_at_utc"]), _time(checkpoint["observed_at_utc"])
    gaps = []
    if observation["session_ref"] != writer:
        gaps.append("foreign-observation")
    if seen < _time(after):
        gaps.append("stale-observation")
    if observation["process_state"] not in route["quiescent"]:
        gaps.append("not-quiescent:" + observation["process_state"])
    if checkpoint["session_ref"] != owned:
        gaps.append("foreign-checkpoint")
    if saved < seen:
        gaps.append("checkpoint-precedes-quiescence")
    return gaps, observation, checkpoint


def takeover_gaps(record, *, destination, observation, checkpoint):
    """Recompute every release hold from recorded facts; unknown is a hold, never a pass."""
    h = _handoff(record, "pending")
    route, source = h["route"], h["source"]
    destination = _exact(destination, DESTINATION_FIELDS, "destination identity")
    gaps, _, saved = _quiescence_gaps(route, writer=source["session_ref"], owned=source["session_ref"],
                                      observation=observation, checkpoint=checkpoint, after=h["requested_at_utc"])
    if destination["repo_ref"] != source["repo_ref"]:
        gaps.append("wrong-repo")
    if route["same_workspace"]:
        if destination["workspace_ref"] != source["workspace_ref"]:
            gaps.append("wrong-workspace")
        if destination["branch"] is None or destination["branch"] != source["branch"]:
            gaps.append("wrong-branch")
        if destination["head"] is None or saved["head"] != destination["head"]:
            gaps.append("head-mismatch")
    elif source["head"] is None or saved["head"] != source["head"]:
        gaps.append("head-mismatch")
    if route["clean"]:
        if destination["dirty"] is None:
            gaps.append("unknown-cleanliness")
        elif destination["dirty"]:
            gaps.append("dirty-destination")
    if route["pushed"] and source["pushed"] is not True:
        gaps.append("unverified-push")
    if any(x["state"] == "uncertain" for x in record.get("outbox", [])):
        gaps.append("unreconciled-dispatch")
    return sorted(set(gaps))


def release_to_human(record, *, destination, observation, checkpoint, acceptance_ref):
    """Make the human the recorded writer only after verified quiescence and a saved checkpoint."""
    if not isinstance(acceptance_ref, str) or not acceptance_ref.strip():
        raise ValueError("explicit human acceptance required")
    gaps = takeover_gaps(record, destination=destination, observation=observation, checkpoint=checkpoint)
    if gaps:
        raise RuntimeError(f"takeover held: {gaps}")
    r = deepcopy(record)
    h = r["worker"]["handoff"]
    h.update(state="released", destination=deepcopy(destination), observation=deepcopy(observation),
             checkpoint=deepcopy(checkpoint), acceptance_ref=_ref(acceptance_ref),
             destination_confirmation="pending-visual" if h["route"]["destination"] == DESKTOP else "pending-human")
    r["worker"]["owner"] = "human"
    return r


def confirm_destination(record, *, confirmation_ref, session_ref=None):
    """The human reports what they saw; this layer never opens or inspects the destination."""
    h = _handoff(record, "released")
    continuity, source = h["route"]["continuity"], h["source"]["session_ref"]
    if continuity == "same-session" and session_ref != source:
        raise ValueError("a same-session route must confirm the same session")
    if continuity == "context-copy" and (session_ref is None or session_ref == source):
        raise ValueError("a context copy has its own local session; it is never the source session")
    if continuity == "diff-apply" and session_ref is not None:
        raise ValueError("a diff-apply route continues no session")
    r = deepcopy(record)
    r["worker"]["handoff"].update(destination_confirmation="human-confirmed",
                                  confirmation_ref=_ref(confirmation_ref),
                                  destination_session_ref=None if session_ref is None else _ref(session_ref))
    return r


def hand_back(record, *, observation, checkpoint, handback_ref):
    """Assistant work resumes only on the human's explicit handback after their writer is quiescent."""
    h = _handoff(record, "released")
    if h["destination_confirmation"] != "human-confirmed":
        raise RuntimeError("handback held: ['unconfirmed-destination']")
    # Observe the human's writer; the checkpoint names the assistant's owned session, because a
    # human's context copy is never adopted as the owned session.
    gaps, observation, checkpoint = _quiescence_gaps(
        h["route"], writer=h["destination_session_ref"], owned=h["source"]["session_ref"],
        observation=observation, checkpoint=checkpoint, after=h["checkpoint"]["observed_at_utc"])
    if gaps:
        raise RuntimeError(f"handback held: {sorted(gaps)}")
    r = deepcopy(record)
    r["worker"]["handoff"].update(state="handed-back", handback_ref=_ref(handback_ref),
                                  handback_observation=observation, handback_checkpoint=checkpoint)
    r["worker"]["owner"] = "assistant"
    return r


def cancel_takeover(record, *, cancel_ref):
    _handoff(record, "pending")
    r = deepcopy(record)
    r["worker"]["handoff"].update(state="cancelled", cancel_ref=_ref(cancel_ref))
    return r
