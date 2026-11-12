"""The human task hub: one readable summary per work item in the assistant thread.

Renders text and plans updates; it never sends, edits or approves. The main message is for a person:
title, plain status, latest result, the next decision, owner and a link. Ids, commits and tests go
in a details reply. Status text grants nothing: approvals come only through tasks.apply.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tasks import approved, approved_parts, pending  # noqa: E402
from nav import checked as checked_session, session_details, session_line, thread_line, trusted  # noqa: E402
from agent_skills.approval_handoff import matching_platform_terms, valid_approval_parts

PLAIN = ("Needs you", "In progress", "Monitoring", "Waiting on someone", "Done")
NOTHING = "Nothing needed from you"
PROGRESS_STATES = {"reported", "performed", "independently_verified", "unverified"}
DESKTOP_INTENTS = {"instruction", "decision", "approval"}
THREAD_INTENTS = {"status", "milestone", "blocker", "verified-completion", "focused-discussion"}
# Shas (7+ hex mixing letters and digits, git's shortest default), uuids and message timestamps belong
# in the details reply. Shorter fragments and other tasks' ids can't be told from words here.
# Plain numbers ("Raise limit to 10000000") and hex-looking words ("Defaced") are ordinary text.
TECHNICAL = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"
                       r"|\b[0-9a-f]{8}-[0-9a-f]{4}-|\b\d{10}\.\d{6}\b", re.I)
LABEL = re.compile(r"[A-Za-z][A-Za-z ]{0,19}")
HUMAN_FIELDS = ("title", "status", "result", "next", "owner", "link", "session", "thread")


def clean(text):
    """One line, characters kept: line breaks can't add a line, and escaped '<', '>' can't add a link."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def material_status(*, progress, progress_state, next_action, next_owner, need_kind,
                    need_from_user, approval_already_valid=False):
    """Render a material user-facing update without implying unverified progress or a missing ask.

    The caller checks the evidence, existing approvals and action scope before supplying these fields.
    This pure formatter sends nothing and grants no permission.
    """
    if progress_state not in PROGRESS_STATES:
        raise ValueError("progress state must describe the evidence")
    if need_kind not in {"none", "decision", "approval", "action"}:
        raise ValueError("user need must be classified")
    fields = {k: clean(v) for k, v in dict(progress=progress, next_action=next_action,
                                           next_owner=next_owner, need_from_user=need_from_user).items()}
    if not all(fields.values()):
        raise ValueError("material status needs progress, next action, owner and user need")
    is_none = fields["need_from_user"].lower() in {"none", "nothing needed from you"}
    if (need_kind == "none") != is_none:
        raise ValueError("user need classification and text disagree")
    if need_kind == "approval" and approval_already_valid:
        raise ValueError("do not repeat an existing valid approval request")
    if is_none:
        fields["need_from_user"] = "None"
    return (f"Progress ({progress_state}): {fields['progress']}\n"
            f"Next: {fields['next_action']} · Owner: {fields['next_owner']}\n"
            f"Need from user: {fields['need_from_user']}")


def coordination_route(*, intent, work_item=None, desktop_surface="desktop main conversation",
                       destination=None, destination_kind=None, thread=None,
                       retired_destinations=()):
    """Plan the user surface for one coordination event without sending or mutating anything."""
    if intent in DESKTOP_INTENTS:
        if not clean(desktop_surface):
            raise ValueError("desktop decision surface is required")
        return {"decision": "route", "surface": "desktop-main", "destination": desktop_surface,
                "work_item": work_item}
    if intent not in THREAD_INTENTS:
        raise ValueError("unsupported coordination intent")
    if destination in set(retired_destinations):
        return {"decision": "reject-retired-destination", "surface": None,
                "destination": destination, "work_item": work_item}
    if (not clean(work_item) or destination_kind != "dm" or not isinstance(thread, dict) or
            thread.get("channel") != destination or not thread.get("root_ts")):
        raise ValueError("focused work needs its exact existing DM thread")
    return {"decision": "route", "surface": "work-item-dm-thread", "destination": destination,
            "work_item": work_item, "root_ts": thread["root_ts"]}


def material_update_receipt(*, work_item, revision, result, remaining, next_owner):
    """Fingerprint one complete work-item update so the same revision is routed once."""
    if (not clean(work_item) or type(revision) is not int or revision < 1 or
            not isinstance(remaining, list) or not all(clean(item) for item in remaining) or
            not clean(result) or not clean(next_owner)):
        raise ValueError("complete work-item result, remaining work and next owner required")
    payload = {"work_item": clean(work_item), "revision": revision, "result": clean(result),
               "remaining": [clean(item) for item in remaining], "next_owner": clean(next_owner)}
    return {**payload, "fingerprint": hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def plan_material_update(previous_fingerprint, receipt):
    if not isinstance(receipt, dict) or set(receipt) != {
            "work_item", "revision", "result", "remaining", "next_owner", "fingerprint"}:
        raise ValueError("validated material update receipt required")
    expected = material_update_receipt(**{key: receipt[key] for key in (
        "work_item", "revision", "result", "remaining", "next_owner")})
    if receipt != expected:
        raise ValueError("material update receipt does not match its payload")
    return "none" if previous_fingerprint == receipt["fingerprint"] else "send"


def material_from_record(record, *, progress, progress_state, where):
    """Bind a material update's owner and user need to the current task evidence."""
    need = _user_need(record)
    action = next_step(record, where=where)
    return material_status(progress=progress, progress_state=progress_state,
                           next_action=action, next_owner="User" if need else "Orchestrator",
                           need_kind=("approval" if pending(record)["action"] and pending(record)["target"] else "decision") if need else "none",
                           need_from_user=action if need else "None")


def direct_approval_handoff(*, record, session, allowed_hosts, surface, surface_link_receipt, platform_terms,
                            reason, route, previous_fingerprint):
    """Prepare one direct-confirmation handoff; the caller verifies the link on the user's surface and sends it."""
    if route != "handoff-direct-confirmation":
        return {"decision": "platform-denial" if route == "stop-and-report-platform-denial" else route}
    p = pending(record)
    parts = p.get("parts")
    if (record.get("status") != "blocked" or not valid_approval_parts(parts) or
            (parts[0]["action"], parts[0]["target"]) != (p["action"], p["target"]) or
            not clean(surface) or not clean(reason)):
        raise ValueError("exact blocked task, approval terms and verified user surface required")
    ref = checked_session(session, clean, allowed_hosts)
    url = trusted(session.get("url"), allowed_hosts)
    if (ref["id"] != record.get("worker", {}).get("session_id") or not url or
            ref["url"] != url or session["url"]["receipt"]["source"] != "platform"):
        raise ValueError("a verified link to this task's session is required")
    if not matching_platform_terms(platform_terms, task_id=record["task_id"],
                                   session_id=ref["id"], parts=parts):
        raise ValueError("pending terms must match this task's platform read")
    if (not isinstance(surface_link_receipt, dict) or
            set(surface_link_receipt) != {"surface", "url", "source_ref", "verified"} or
            surface_link_receipt["verified"] is not True or
            surface_link_receipt["surface"] != surface or surface_link_receipt["url"] != url or
            not clean(surface_link_receipt["source_ref"])):
        raise ValueError("verify this exact link on the user's surface before routing")
    identity = {"task": record["task_id"], "session": ref["id"], "url": url,
                "parts": parts, "reason": reason, "surface": surface}
    fp = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if fp == previous_fingerprint:
        return {"decision": "already-routed", "fingerprint": fp}
    asks = "\n".join(f"{i}. {clean(item['wording'])} Action {exact(item['action'])}; "
                     f"target {exact(item['target'])}; scope {exact(item['scope'])}."
                     for i, item in enumerate(parts, 1))
    body = (f"Direct confirmation needed for task {clean(record['task_id'])}.\n"
            f"Open task session in {ref['app']}: <{url}|Open session>\n"
            f"Reason: {clean(reason)}\n{asks}\n"
            "Next owner/action: You answer in that task session; the orchestrator checks the direct reply "
            "and platform admission before resuming. Work remains blocked until then.")
    return {"decision": "send-handoff", "fingerprint": fp, "body": body}


def exact(text):
    """An action or target shown verbatim in inline code, so markup can't change what is approved."""
    text = clean(text)
    if "`" in text:
        raise ValueError("an approval action or target can't contain a backtick")
    return f"`{text}`"


def _user_need(record):
    if any(o["state"] == "uncertain" for o in record.get("outbox", [])):
        return False
    if (record.get("worker") or {}).get("owner") not in {"assistant", "human"}:
        return False
    p = pending(record)
    if p.get("parts"):
        return not approved_parts(record, p["parts"])
    if p["action"] and p["target"]:
        return not approved(record, p["action"], p["target"])
    return bool(p["need"] and p["need"] != "unspecified")


def plain_status(record, *, monitoring=False, waiting_on=None):
    if _user_need(record):
        return "Needs you"
    if waiting_on:
        return "Waiting on someone"
    if record.get("status") == "verified-done":
        return "Monitoring" if monitoring else "Done"
    return "In progress"


THREAD_NOTE = "A thread reply is passed on as context; it doesn't record approval."


def next_step(record, *, where):
    """The exact decision and where to give it, or NOTHING. Approval counts only in the user's chat
    with the session (`where`): workers share the user's messaging account, so a thread reply can't
    prove the user wrote it."""
    p, where = pending(record), clean(where)
    if any(o["state"] == "uncertain" for o in record.get("outbox", [])):
        return "Orchestrator: reconcile the uncertain dispatch receipt before retrying."
    if record.get("status") == "ready-for-review":
        return "Orchestrator: verify the worker evidence and continue the authorized next step."
    if any(o["state"] == "not-sent" for o in record.get("outbox", [])) and record.get("status") is None:
        return "Orchestrator: retry the failed dispatch within the authorized scope."
    if (record.get("worker") or {}).get("owner") not in {"assistant", "human"}:
        return "Orchestrator: reconcile task ownership before routing work."
    if record.get("status") == "awaiting-worker":
        return "Orchestrator: pass the decision to the worker and confirm the dispatch receipt."
    if not _user_need(record) and any(p.values()):
        return "Orchestrator: reconcile the blocker against current evidence and approval."
    if p["action"] and p["target"]:
        prop = record.get("proposal") or {}
        if prop.get("approve") and (prop.get("action"), prop.get("target")) == (p["action"], p["target"]):
            return (f"A thread reply proposes approving {exact(p['action'])} on {exact(p['target'])}. "
                    f"Not recorded: confirm it in {where}.")
        return f"Approve or decline {exact(p['action'])} on {exact(p['target'])} in {where}. {THREAD_NOTE}"
    if p["action"]:
        return f"The worker asked to {exact(p['action'])} without naming a target; tell it to name one, or decline, in {where}."
    if p["need"]:
        return f"{clean(p['need'])} Answer in {where}."
    return NOTHING


def _known_ids(record):
    """This record's own ids. A task id made only of words may still read as a title."""
    w, ev = record.get("worker") or {}, record.get("evidence") or {}
    ids = [w.get("session_id"), ev.get("commit")]
    if re.search(r"\d", record.get("task_id") or ""):
        ids.append(record["task_id"])
    return [str(i).lower() for i in ids if i]


def summary(record, *, title, result, owner, label, link=None, where="the session chat",
            monitoring=False, waiting_on=None, session=None, thread=None, allowed_hosts=()):
    """Two destinations, always shown: `session` (a nav.session() reference) and `thread` (a
    nav.thread() reference to the work item's exact root). `link`: an optional third, the review or
    source, as a nav.link_from_response() result, shown only when nav.trusted() accepts it for
    `allowed_hosts` (the caller's allowlist; empty means nothing is clickable)."""
    if not LABEL.fullmatch(label or ""):
        raise ValueError("label must be a short plain name, such as Claude or Codex")
    s = {"label": label, "title": clean(title), "result": clean(result), "owner": clean(owner),
         "link": trusted(link, allowed_hosts),
         "status": plain_status(record, monitoring=monitoring, waiting_on=waiting_on),
         "next": next_step(record, where=where),
         "session": session_line(checked_session(session, clean, allowed_hosts) if session else None),
         "thread": thread_line(thread, allowed_hosts),
         # the index is read outside any thread and has no details reply
         "thread_elsewhere": thread_line(thread, allowed_hosts, in_index=True)}
    if waiting_on and s["next"] == NOTHING:
        s["next"] = f"{NOTHING}; waiting on {clean(waiting_on)}"
    for k in ("title", "result", "owner"):
        if not s[k]:
            raise ValueError(f"{k} must be non-empty")
    ids = _known_ids(record)
    for k in ("title", "result", "next", "owner", "session"):
        if s[k] is None:
            continue
        if TECHNICAL.search(s[k]) or any(i in s[k].lower() for i in ids):
            raise ValueError(f"{k} carries a technical id; put it in the details reply")
    return s


def _review(s):
    return f"\nReview: <{s['link']}|Open>" if s["link"] else ""


def _title(s):
    return s["title"] if "*" in s["title"] else f"*{s['title']}*"  # a '*' in the title would break the bold


def render(s):
    return (f"[AI · {s['label']}] {_title(s)}\n*{s['status']}* · {s['result']}\n"
            f"Next: {s['next']}\nOwner: {s['owner']}\n{s['session']}\n{s['thread']}" + _review(s))


def render_details(record, session=None, thread=None, **extra):
    """Technical reply: ids, resume command, commit, tests, local paths. Never message bodies or transcripts."""
    ev = record.get("evidence") or {}
    w = record.get("worker") or {}
    who = session_details(session) if session else f"{w.get('kind')} session {w.get('session_id') or 'none'}"
    parts = [f"task {record['task_id']}", who, f"status {record.get('status')}"]
    if thread and thread.get("root_ts"):
        parts.append(f"thread root {thread['root_ts']}")
    parts += [f"{k} {v}" for k, v in (("commit", ev.get("commit")), ("tests", ev.get("tests"))) if v]
    parts += [f"{k} {v}" for k, v in extra.items() if v]
    return "Details: " + clean(" · ".join(parts))


def fingerprint(s):
    return hashlib.sha256("\x1f".join(s[k] or "" for k in HUMAN_FIELDS).encode()).hexdigest()[:16]


def plan_update(hub, s, *, editable_authors=(), material=False):
    """What to do for a new summary: none, post-root, edit-root or reply.

    `hub` is the work item's hub state {root_ts, root_author, last_fp}; with no root_ts there is
    nothing to reply to, so the plan is post-root (the caller has already looked the work item up,
    so a root is never posted twice). An edit is planned only when the root's known author is an
    identity the available tools can edit; otherwise the summary is a reply and the root stays.
    """
    if hub and hub.get("send_state") == "uncertain":
        return "reconcile"
    if not hub or not hub.get("root_ts"):
        return "post-root"
    if hub.get("last_fp") == fingerprint(s):
        return "none"
    if material:
        return "reply"
    author = hub.get("root_author")
    return "edit-root" if author and author in editable_authors else "reply"


def render_index(summaries):
    """One line per work item, needing-you first: shown in chat, or kept on an editable surface the user chose."""
    order = sorted(summaries, key=lambda s: PLAIN.index(s["status"]))
    return "\n".join(f"• *{s['status']}* · {s['title']} · {s['next']} · {s['thread_elsewhere']}" for s in order)
