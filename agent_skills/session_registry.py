"""Portable, pure session ownership contracts. No host calls or persistence."""
from copy import deepcopy

from .task_contract import ID, validate_checkpoint, validate_packet


def _identifier(value, label):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"invalid {label}")


def register(packet, *, session_id, host, surface, creator, origin_owner,
             operator, resume_ref, workspace_ref):
    """Record observed identity; caller must separately verify its host receipt."""
    validate_packet(packet)
    for label, value in (("session_id", session_id), ("host", host),
                         ("creator", creator), ("origin_owner", origin_owner),
                         ("operator", operator)):
        _identifier(value, label)
    if surface not in ("cloud-terminal", "local-terminal", "desktop"):
        raise ValueError("invalid surface")
    if origin_owner not in ("assistant", "user") or operator not in ("assistant", "human"):
        raise ValueError("invalid ownership")
    if not isinstance(resume_ref, str) or not resume_ref.strip() or not isinstance(workspace_ref, str):
        raise ValueError("resume and workspace references required")
    return {"task_id": packet["task_id"], "revision": packet["revision"],
            "packet_sha256": packet["packet_sha256"], "session_id": session_id,
            "host": host, "surface": surface, "creator": creator,
            "origin_owner": origin_owner, "operator": operator,
            "resume_ref": resume_ref, "workspace_ref": workspace_ref,
            "generation": 1, "state": "observed", "checkpoint": None,
            "pending_effects": [], "completion": "unverified",
            "archive": "ineligible"}


def enroll(registry, entry):
    """One active registered session per work item and host session identity."""
    if not isinstance(registry, dict) or not isinstance(entry, dict):
        raise ValueError("invalid registry entry")
    task_id = entry.get("task_id")
    _identifier(task_id, "task_id")
    if task_id in registry or any(
            other.get("host") == entry.get("host") and
            other.get("session_id") == entry.get("session_id")
            for other in registry.values()):
        raise ValueError("duplicate task or host session")
    return {**registry, task_id: deepcopy(entry)}


def _matches(entry, packet):
    validate_packet(packet)
    return (entry.get("task_id"), entry.get("revision"), entry.get("packet_sha256")) == (
        packet["task_id"], packet["revision"], packet["packet_sha256"])


def status(entry):
    """UI projection; observed identity alone is not a live connection."""
    return {key: deepcopy(entry[key]) for key in (
        "task_id", "revision", "session_id", "host", "surface", "origin_owner",
        "operator", "resume_ref", "workspace_ref", "generation", "state",
        "completion", "archive")}


def checkpoint_takeover(entry, packet, saved, *, expected_generation, stopped,
                        state_verified, pending_effects, human_release=False):
    """Move operator only after the old writer is stopped and state reconciled."""
    if not _matches(entry, packet) or expected_generation != entry["generation"]:
        return entry, "stale"
    validate_checkpoint(packet, saved)
    if not isinstance(pending_effects, list) or not all(isinstance(x, str) and x for x in pending_effects):
        raise ValueError("invalid pending effects")
    if not stopped or not state_verified or not saved["sources_fresh"] or saved[
            "uncertain_side_effects"] or pending_effects:
        return entry, "hold-and-reconcile"
    if entry["operator"] == "human" and not human_release:
        return entry, "human-release-required"
    if entry["state"] not in ("observed", "active", "delegated", "handed-off", "migrated"):
        return entry, "invalid-transition"
    updated = {**entry, "operator": "human" if entry["operator"] == "assistant" else "assistant",
               "generation": entry["generation"] + 1, "state": "handed-off",
               "checkpoint": deepcopy(saved), "pending_effects": []}
    return updated, "handed-off"


def delegate_user_session(entry, *, explicit_request, expected_generation):
    """Delegation changes operator, never original ownership or archive rights."""
    if entry["origin_owner"] != "user" or entry["operator"] != "human" or not explicit_request:
        return entry, "not-authorized"
    if expected_generation != entry["generation"]:
        return entry, "stale"
    return {**entry, "operator": "assistant", "generation": entry["generation"] + 1,
            "state": "delegated"}, "delegated"


def reconcile_migration(entry, packet, saved, *, expected_generation, old_stopped,
                        new_host, new_session_id, new_resume_ref, state_preserved,
                        effects_reconciled, identity_verified, explicit_user_migration=False):
    """Bind a migrated session only after both sides and the checkpoint agree."""
    if not _matches(entry, packet) or expected_generation != entry["generation"]:
        return entry, "stale"
    if entry["origin_owner"] == "user" and not explicit_user_migration:
        return entry, "user-migration-authorization-required"
    validate_checkpoint(packet, saved)
    for label, value in (("new_host", new_host), ("new_session_id", new_session_id)):
        _identifier(value, label)
    if not isinstance(new_resume_ref, str) or not new_resume_ref.strip():
        raise ValueError("resume reference required")
    if not all((old_stopped, state_preserved, effects_reconciled, identity_verified,
                saved["sources_fresh"])) or saved["uncertain_side_effects"]:
        return entry, "hold-and-reconcile"
    return {**entry, "host": new_host, "session_id": new_session_id,
            "resume_ref": new_resume_ref, "generation": entry["generation"] + 1,
            "state": "migrated", "checkpoint": deepcopy(saved)}, "migrated"


def accept_result(entry, packet, *, generation, session_id, completion):
    """Reject late/foreign reports; completion remains an evidence claim."""
    if (not _matches(entry, packet) or generation != entry["generation"] or
            session_id != entry["session_id"]):
        return entry, "stale-or-foreign"
    if completion not in ("claimed", "verified", "accepted"):
        raise ValueError("invalid completion")
    if completion == "accepted" and entry["completion"] != "verified":
        return entry, "verification-required"
    if (entry["completion"] == "accepted" or
            entry["completion"] == "verified" and completion == "claimed"):
        return entry, "already-recorded"
    return {**entry, "completion": completion}, "recorded"


def archive_eligibility(entry, *, host_archive_verified, restore_verified,
                        no_pending_dispatch, no_pending_effects, state_preserved,
                        explicit_user_archive=False):
    """Pure verdict; a host adapter must carry out archive and reconcile it."""
    if entry["origin_owner"] == "user" and not explicit_user_archive:
        return "user-archive-authorization-required"
    if entry["completion"] != "accepted":
        return "acceptance-required"
    if not all((host_archive_verified, restore_verified, no_pending_dispatch,
                no_pending_effects, state_preserved)) or entry["pending_effects"]:
        return "hold-and-reconcile"
    return "eligible-for-reviewed-archive"
