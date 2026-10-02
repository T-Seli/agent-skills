"""Offline helpers for the work-item channel; connector I/O and approval stay with the caller."""

import hashlib
import re
import sys
import unicodedata
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tasks import pending  # noqa: E402

POLL_SECONDS = (5, 15, 30, 60, 120)
TIMEOUT_SECONDS = 600
# Reports only. "needs-human" reports a decision the user must make; it never approves that decision.
ROUTINE_CATEGORIES = {"status", "context", "blocker", "needs-human", "verified-completion"}
STATUSES = ("pending", "running", "needs-human", "verified-done")
# The connector marks a message posted through an app on the user's account with a "Sent using" line;
# any form of it, anywhere, rules the message out. So does any app or bot field a reader exposes.
ATTRIBUTION = re.compile(r"sent\W*using", re.I)
APP_FIELDS = ("app", "app_id", "bot_id", "bot_profile", "subtype")
# The whole reply, ignoring case, surrounding space and trailing '.' or '!'; a '?' never approves.
YES = {"yes", "y", "approve", "approved", "yes approve", "go ahead", "yes go ahead"}


def text_hash(text):
    """Fingerprint of a sent body, so records can block duplicates without storing the text."""
    return hashlib.sha256(text.encode()).hexdigest()


def _send_open(text, record):
    return bool(text and record.get("send_state") not in ("uncertain", "timed_out")
                and record.get("last_sent_hash") != text_hash(text))


def may_send(exact_text, approved_text, record):
    """Exact approval, no unresolved attempt, and not a repeat of the last sent body."""
    return exact_text == approved_text and _send_open(exact_text, record)


def may_send_routine(policy, text, category, destination, now, *, sensitive, requests_action, record):
    """True only inside the user's standing policy; anything else needs exact-text approval.

    `sensitive` and `requests_action` are the caller's judgement about the drafted text
    (secrets, customer personal data, credentials; asking anyone to take a consequential
    action). A report may describe an action the user must decide on; it may not request
    that anyone carry it out. The policy has no end date unless the user set `expires`.
    """
    if not policy or not _send_open(text, record):
        return False
    if policy.get("expires") and now >= datetime.fromisoformat(policy["expires"]):
        return False
    return bool(category in ROUTINE_CATEGORIES and category in policy.get("categories", ())
                and destination == policy.get("recipient")
                and not sensitive and not requests_action)


def next_delay(attempt, sent_at, now):
    remaining = TIMEOUT_SECONDS - (now - sent_at)
    return max(0, min(POLL_SECONDS[attempt] if attempt < len(POLL_SECONDS) else 60, remaining))


def match_replies(pages, bot_user, sent_ts, request_id, root_ts=None, *, channel, workspace):
    """Return every qualifying bot reply, oldest first, from complete thread/history pages.

    The caller decides which is the substantive answer: an early "on it" is only an acknowledgement.
    Each message has ts, user, text, and optionally thread_ts. Thread replies match the work
    item's root (`root_ts`, default `sent_ts`) and must be newer than `sent_ts`, the last send,
    so stale replies drop out; top-level replies need an explicit request ID. The worker's own
    messages never match because they are not from `bot_user`. A ts is unique only within a channel,
    so the caller stamps each message with the `channel` it read; a message from another channel, or
    with no channel, never matches. `workspace` is the authoritative workspace of that read (from the
    config, never from message text); a `team` on a message must equal it. Results are keyed by
    (workspace, channel, ts). Timestamps must be the recorded strings.
    """
    if not all(isinstance(v, str) and v for v in (channel, workspace)):
        return []
    if not (isinstance(sent_ts, str) and sent_ts) or (root_ts is not None and not (isinstance(root_ts, str) and root_ts)):
        raise ValueError("pass sent and root ts as the recorded non-empty strings; floats lose digits")
    found = {}
    root = Decimal(str(sent_ts))
    thread = sent_ts if root_ts is None else root_ts
    for page in pages:
        for msg in page:
            if not isinstance(msg.get("ts"), str):
                continue  # a message ts that isn't the connector's string can't be matched exactly
            try:
                ts = Decimal(msg["ts"])
            except ArithmeticError:
                continue
            if ts <= root or msg.get("user") != bot_user:
                continue
            if msg.get("channel") != channel or msg.get("team") not in (None, workspace):
                continue
            in_thread = msg.get("thread_ts") == thread
            top_level = bool(request_id and not msg.get("thread_ts")
                             and request_id in msg.get("text", ""))
            if in_thread or top_level:
                found[(workspace, channel, str(ts))] = msg
    return [found[k] for k in sorted(found, key=lambda k: Decimal(k[2]))]


def select_work_item(records, work_item):
    """The one record for a work item, None when new, or raise when several need reconciling."""
    hits = [r for r in records if r.get("work_item") == work_item]
    if len(hits) > 1:
        raise ValueError(f"{len(hits)} records for work item {work_item}: reconcile before sending")
    return hits[0] if hits else None


def set_status(record, status, now):
    """Change the thread record's status, stamping `status_since` only when it actually changes."""
    if record.get("status") != status:
        record["status"], record["status_since"] = status, str(now)
    return record


def _msg_key(msg, workspace):
    """(workspace, channel, root) a reply belongs to, as exact strings, or None. The caller sets
    `channel` from the conversation it read; a `team` on the message must be the configured workspace."""
    ch, root, team = msg.get("channel"), msg.get("thread_ts"), msg.get("team")
    if not (isinstance(ch, str) and ch and isinstance(root, str) and root) or team not in (None, workspace):
        return None
    return workspace, ch, root


def _thread_key(thread, workspace):
    """(workspace, channel, root) of a work item's record: channel from its `destination`; workspace
    from the record, else the configured one (records predating the field were all made under it).
    A record without a destination or root has no key, so nothing can attach to it."""
    ch, root, ws = thread.get("destination"), thread.get("root_ts"), thread.get("workspace", workspace)
    if not (isinstance(ch, str) and ch and isinstance(root, str) and root and isinstance(ws, str) and ws):
        return None
    return ws, ch, root


def thread_for_reply(msg, threads, *, workspace):
    """The one thread record with this reply's exact workspace, channel and root, or None; several raise."""
    key = _msg_key(msg, workspace)
    hits = [t for t in threads if key and _thread_key(t, workspace) == key]
    if len(hits) > 1:
        raise ValueError(f"{len(hits)} records share {key}: reconcile first")
    return hits[0] if hits else None


def typed_by_user(msg, *, human_user_id, sent_ts):
    """The strongest signal this connector gives that the user typed it: their account, no app
    attribution line, and not one of the messages our records sent. An AI label is checked later."""
    if any(not isinstance(ts, str) for ts in sent_ts):
        raise ValueError("record sent message ts values as strings; floats lose digits")
    return (msg.get("user") == human_user_id and not any(msg.get(f) for f in APP_FIELDS)
            and not ATTRIBUTION.search(_plain(msg.get("text")))
            and Decimal(str(msg.get("ts"))) not in {Decimal(ts) for ts in sent_ts})


def _plain(text):
    """Compatibility forms folded (fullwidth letters) and format characters (zero-width) dropped."""
    text = unicodedata.normalize("NFKC", text or "")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _is_yes(text):
    t = re.sub(r"\s+", " ", text.lower()).strip()
    return "?" not in t and t.rstrip(".!").strip() in YES


def reply_event(msg, thread, task, *, human_user_id, sent_ts, workspace):
    """Turn a thread reply into a `proposal` task event, or (None, reason).

    `thread` is the work item's record: destination (channel), root_ts, optional workspace, and what
    the last summary showed (last_summary_ts, shown_pending {need, action, target}). The reply must
    match its workspace, channel and root exactly. Workers share the user's messaging account and the attribution check is
    only observed behaviour, so a reply never decides: a yes proposes exactly the action and target
    shown, anything else is context. The caller relays the text to the worker as data; approval
    still needs the user's chat turn (tasks.apply `decided`).
    """
    key = _msg_key(msg, workspace)
    if thread is None or key is None or key != _thread_key(thread, workspace) or not isinstance(msg.get("ts"), str):
        return None, "other-thread"
    if not typed_by_user(msg, human_user_id=human_user_id, sent_ts=sent_ts):
        return None, "not-typed-by-user"
    if not thread.get("last_summary_ts") or Decimal(str(msg["ts"])) <= Decimal(str(thread["last_summary_ts"])):
        return None, "before-summary"
    p = pending(task)
    if not (p["need"] or p["action"] or p["target"]):
        return None, "nothing-pending"
    shown = thread.get("shown_pending") or {}
    if (p["need"], p["action"], p["target"]) != (shown.get("need"), shown.get("action"), shown.get("target")):
        return None, "summary-out-of-date"
    approve = _is_yes(msg.get("text") or "") and bool(p["action"] and p["target"])
    data = {"approve": True, "action": p["action"], "target": p["target"]} if approve else {}
    # ts are unique only within a channel, so the id carries the whole thread key
    event = {"id": "thread:" + ":".join(key) + f":{msg['ts']}", "task": task["task_id"], "ts": msg["ts"],
             "source": "thread", "kind": "proposal", "data": data}
    return event, "proposes-approval" if approve else "context"


def reduce_status(status, events):
    """Apply status events in time order, ignoring duplicates; never grants authorization.

    Events: {ts, by: worker|orchestrator|user, kind, evidence?}. Kinds: sent, ack, accept,
    claim-done, close, needs-human, decided, reopen. Orchestrator text can move a status but
    a worker completion needs evidence, and closure needs that evidence first.
    """
    seen, evidenced = set(), False
    for e in sorted(events, key=lambda e: Decimal(str(e["ts"]))):
        if e["ts"] in seen:
            continue
        seen.add(e["ts"])
        kind, by = e["kind"], e["by"]
        if kind == "sent" and status is None:
            status = "pending"
        elif kind == "accept" and by == "orchestrator" and status == "pending":
            status = "running"
        elif kind == "claim-done" and by == "worker":
            evidenced = bool(e.get("evidence"))
            status = "pending" if not evidenced else status
        elif kind == "close" and by == "orchestrator" and evidenced:
            status = "verified-done"
        elif kind == "needs-human":
            status = "needs-human"
        elif kind == "decided" and by == "user" and status == "needs-human":
            status = "running"
        elif kind == "reopen":
            status, evidenced = "running", False
        # "ack" and anything unknown change nothing: an acknowledgement is not acceptance.
    return status
