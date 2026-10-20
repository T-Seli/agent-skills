"""Aggregate effectiveness measures from local task records; reads only ids, kinds, outcomes and times.

Usage: python3 metrics.py [task_dir]. Prints JSON: task measures, assistant-thread measures (records in
the parent folder) and proposed corrections.
Corrections are proposals for the user: nothing here edits a skill.
"""
import json
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path

RESPONSES = {"accepted", "running", "blocked", "answered", "ready"}


def _applied(record):
    return [(h["kind"], Decimal(h["ts"]), h["source"]) for h in record["history"] if h["outcome"] == "applied"]


def task_measures(record, now):
    rows = _applied(record)
    sent = next((ts for k, ts, _ in rows if k == "dispatched"), None)
    reply = next((ts for k, ts, _ in rows if k in RESPONSES and sent is not None and ts >= sent), None)
    waiting, since = Decimal(0), None
    for k, ts, _ in rows:
        if k == "blocked" and since is None:
            since = ts
        elif k == "decided" and since is not None:
            waiting, since = waiting + ts - since, None
    if since is not None:
        waiting += Decimal(str(now)) - since
    # One claim per report id: applied (with evidence) or unsupported (without). A repeated or stale
    # copy of a valid report is ignored by tasks.apply and is neither a new claim nor an unsupported one.
    claims = {h["id"]: h["outcome"] for h in record["history"]
              if h["kind"] == "ready" and h["outcome"] in ("applied", "unsupported")}
    out = record["outbox"]
    counts = record.get("counts", {})
    return {"dispatched": sent is not None, "response_s": float(reply - sent) if reply is not None else None,
            "waiting_on_human_s": float(waiting),
            "duplicates": counts.get("duplicates", 0),
            # A retry is a dispatch after one that never settled as sent; a resume after a decision is not.
            "retries": sum(prev["state"] != "sent" for prev in out[:-1]),
            "uncertain": sum(o["state"] == "uncertain" for o in record["outbox"]),
            "unneeded_asks": counts.get("unneeded_asks", 0),
            "claimed": len(claims),
            "claims_without_evidence": sum(o == "unsupported" for o in claims.values()),
            "verified": sum(k == "verified" for k, _, _ in rows)}


def aggregate(records, now=None):
    now = now or time.time()
    per = [task_measures(r, now) for r in records]
    responses = [p["response_s"] for p in per if p["response_s"] is not None]
    total = {k: sum(p[k] for p in per) for k in ("duplicates", "retries", "uncertain", "unneeded_asks",
                                                 "claimed", "claims_without_evidence", "verified")}
    return {"tasks": len(per),
            "median_response_s": statistics.median(responses) if responses else None,
            "no_response": sum(p["dispatched"] and p["response_s"] is None for p in per),
            "waiting_on_human_s": sum(p["waiting_on_human_s"] for p in per), **total}


def corrections(m):
    """Small, testable corrections for each gap; empty when nothing stands out (n is always stated)."""
    out = []
    if m["duplicates"]:
        out.append({"gap": f"{m['duplicates']} duplicate event receipts in {m['tasks']} tasks",
                    "change": "have the caller keep its read cursor so it stops re-feeding old events",
                    "test": "replaying a read page after the fix adds 0 to counts.duplicates (before: >0)"})
    if m["uncertain"] or m["retries"]:
        out.append({"gap": f"{m['uncertain']} unresolved and {m['retries']} repeated dispatches",
                    "change": "settle each launch from its transcript before the next dispatch",
                    "test": "a crash between begin and settle leaves exactly 1 uncertain entry, settled on restart"})
    if m["unneeded_asks"]:
        out.append({"gap": f"{m['unneeded_asks']} approval requests repeated an existing approval",
                    "change": "check tasks.approved(action, target) before asking the user",
                    "test": "a second blocked report for an approved action and target raises no new ask"})
    if m["claims_without_evidence"]:
        out.append({"gap": f"{m['claims_without_evidence']} of {m['claimed']} completion claims had no commit or tests",
                    "change": "make the worker prompt require commit and tests in its report",
                    "test": "a simulated ready report without tests is rejected by the schema, not just ignored"})
    if m["no_response"]:
        out.append({"gap": f"{m['no_response']} of {m['tasks']} dispatched tasks never got a worker report",
                    "change": "flag tasks with no report after the wait window in tasks.attention",
                    "test": "a task delivered past the window appears in attention (before: absent)"})
    return out


def threads(records, now=None):
    """Assistant-thread records (routing.md § Records): reply delay, open needs-human time, send state.
    A reply may be only an acknowledgement, so this is a responsiveness measure, never progress."""
    now = Decimal(str(now or time.time()))
    delays, waiting, unknown_start, by_status = [], Decimal(0), 0, {}
    for r in records:
        sent, reply = r.get("last_sent_ts") or r.get("sent_ts"), r.get("last_reply_ts") or r.get("reply_ts")
        if sent and reply and Decimal(reply) > Decimal(sent):
            delays.append(float(Decimal(reply) - Decimal(sent)))
        if r.get("status") == "needs-human":
            if r.get("status_since"):  # when it became needs-human, not when we last wrote
                waiting += now - Decimal(r["status_since"])
            else:
                unknown_start += 1
        by_status[r.get("status") or "unset"] = by_status.get(r.get("status") or "unset", 0) + 1
    return {"threads": len(records), "median_reply_s": statistics.median(delays) if delays else None,
            "no_reply": len(records) - len(delays), "open_needs_human_s": float(waiting),
            "needs_human_start_unknown": unknown_start,
            "uncertain_sends": sum(r.get("send_state") in ("uncertain", "timed_out") for r in records),
            "by_status": by_status}


def load_records(root):
    return [json.loads(p.read_text()) for p in sorted(Path(root).glob("*.json"))]


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    import tasks
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else tasks.state_dir()
    m = aggregate(load_records(root)) if root.exists() else aggregate([])
    th = threads(load_records(root.parent)) if root.parent.exists() else threads([])
    print(json.dumps({"tasks": m, "threads": th, "corrections": corrections(m)}, indent=1))
