#!/usr/bin/env python3
"""Private, append-only central task events. Never commits, pushes or executes replayed commands."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,100}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
REMOTE = re.compile(r"^(?:https://github\.com/|git@github\.com:)T-Seli/agent-task-history(?:\.git)?$")
SECRET = re.compile(r"(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:password|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*\S+|\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,})\b)")
PRIVATE_PATH = re.compile(r"(?:^|[ /])(?:\.codex/sessions|\.claude/projects)(?:[/ ]|$)")
KINDS = {"start", "decision", "implementation", "test", "review", "deploy", "failure", "handoff", "verification", "proposal", "feedback", "cancellation", "close"}
FEEDBACK_CATEGORIES = {"user_correction", "confusion", "clarification", "scope_drift", "runbook_gap", "dispatch_failure", "repeated_blocker", "other"}
FEEDBACK_CHECK_STATES = {"unverified", "verified_pass", "verified_fail"}
FEEDBACK_CAUSE_BASES = {"observed", "hypothesis"}
STATES = {"performed", "reported", "independently_verified"}
STATUS = {"active", "blocked", "canceled", "done"}
FIELDS = {"schema_version", "event_id", "task_id", "session_id", "revision", "record_owner", "execution_owner", "at_utc", "observed_at_utc", "kind", "summary", "status", "scope", "approval_ref", "decision", "reason", "failed_approach", "files", "evidence", "uncertainty", "next_step", "open_checks", "resolved_checks", "lesson_proposal", "source_ref", "correction_of", "base_sha", "head_sha", "dirty_diff_digest", "environment", "new_record_owner", "transfer_ack_ref", "verified_revision", "source_version", "runtime_version", "context", "implementation", "validation", "outcomes", "monitoring", "excluded_scope", "module_changes", "repo_ref", "branch_ref", "clear_next_step", "feedback_category", "feedback_issue", "feedback_impact", "feedback_correction", "feedback_prevention_check", "feedback_check_state", "feedback_check_ref", "feedback_cause", "feedback_cause_basis"}
REQUIRED = {"schema_version", "event_id", "task_id", "session_id", "revision", "record_owner", "at_utc", "observed_at_utc", "kind", "summary"}
EVIDENCE_FIELDS = {"state", "claim", "ref", "sha", "environment", "command", "outcome", "verified_by"}
CONFIG = Path(os.environ.get("AGENT_SKILLS_CONFIG", "~/.config/agent-skills/workers.json")).expanduser()


def fail(message):
    raise ValueError(message)


def string(value, name, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        fail("invalid " + name)
    return value


def timestamp(value, name):
    string(value, name, 20)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
            fail("noncanonical UTC timestamp: " + name)
    except ValueError:
        fail("invalid UTC timestamp: " + name)


def validate(data):
    if not isinstance(data, dict) or not REQUIRED <= data.keys() or set(data) - FIELDS:
        fail("invalid event fields")
    if data["schema_version"] != 1 or type(data["revision"]) is not int or data["revision"] < 1:
        fail("invalid schema version or revision")
    for key in ("event_id", "task_id", "session_id"):
        if not isinstance(data[key], str) or not ID.fullmatch(data[key]):
            fail("invalid " + key)
    if "clear_next_step" in data and (data["clear_next_step"] is not True or "next_step" in data):
        fail("clear_next_step must be true and cannot accompany next_step")
    for key in ("record_owner", "summary"):
        string(data[key], key, 240)
    for key in ("at_utc", "observed_at_utc"):
        timestamp(data[key], key)
    if data["kind"] not in KINDS or ("status" in data and data["status"] not in STATUS):
        fail("invalid kind or status")
    feedback_fields = {"feedback_category", "feedback_issue", "feedback_impact", "feedback_correction", "feedback_prevention_check", "feedback_check_state", "feedback_check_ref", "feedback_cause", "feedback_cause_basis"}
    if data["kind"] == "feedback":
        required_feedback = {"source_ref", "feedback_category", "feedback_issue", "feedback_impact", "feedback_correction", "feedback_prevention_check", "feedback_check_state"}
        if not required_feedback <= data.keys() or not data.get("evidence"):
            fail("feedback needs source, issue, impact, correction, prevention check and evidence")
        if (not isinstance(data["feedback_category"], str) or data["feedback_category"] not in FEEDBACK_CATEGORIES
                or not isinstance(data["feedback_check_state"], str) or data["feedback_check_state"] not in FEEDBACK_CHECK_STATES):
            fail("invalid feedback category or check state")
        if ("feedback_cause" in data) != ("feedback_cause_basis" in data):
            fail("feedback cause needs an observed or hypothesis basis")
        if "feedback_cause_basis" in data and (not isinstance(data["feedback_cause_basis"], str)
                                               or data["feedback_cause_basis"] not in FEEDBACK_CAUSE_BASES):
            fail("invalid feedback cause basis")
        if data.get("feedback_cause_basis") == "observed" and not any(
                isinstance(item, dict) and item.get("state") in {"performed", "independently_verified"}
                for item in data["evidence"]):
            fail("observed feedback cause needs performed or independently verified evidence")
        if data["feedback_check_state"] != "unverified" and not data.get("feedback_check_ref"):
            fail("verified prevention check needs a reference")
        if data["feedback_check_state"] == "unverified" and data.get("feedback_check_ref"):
            fail("unverified prevention check cannot claim a verification reference")
        if data["feedback_check_state"] != "unverified":
            expected_outcome = "pass" if data["feedback_check_state"] == "verified_pass" else "fail"
            if not any(isinstance(item, dict) and item.get("state") in {"performed", "independently_verified"}
                       and item.get("ref") == data["feedback_check_ref"] and item.get("outcome") == expected_outcome
                       for item in data["evidence"]):
                fail("verified prevention check needs performed evidence at its check reference and outcome")
    elif feedback_fields & data.keys():
        fail("feedback fields only allowed on feedback events")
    allowed_status = {"start": {"active"}, "decision": {"active", "blocked"},
                      "failure": {"blocked"}, "cancellation": {"canceled"}, "close": {"done"}}
    if "status" in data and data["status"] not in allowed_status.get(data["kind"], set()):
        fail("status is not allowed for this lifecycle kind")
    if data["kind"] == "start" and data.get("status") != "active":
        fail("start requires active status")
    if data["kind"] == "cancellation" and data.get("status") != "canceled":
        fail("cancellation requires canceled status")
    if data["kind"] == "close" and data.get("status") != "done":
        fail("close requires done status")
    if data["kind"] == "close" and data.get("resolved_checks"):
        fail("close cannot resolve its own required checks")
    if data.get("resolved_checks") and data["kind"] not in {"verification", "decision"}:
        fail("checks may be resolved only by verification or scoped decision")
    if data.get("resolved_checks") and data["kind"] == "decision" and not (data.get("approval_ref") and data.get("reason")):
        fail("scope decision resolving checks needs approval reference and reason")
    if data.get("resolved_checks") and data["kind"] == "verification" and (not data.get("evidence") or any(not isinstance(e, dict) or e.get("state") != "independently_verified" or e.get("outcome") != "pass" for e in data["evidence"])):
        fail("verification resolving checks needs evidence")
    if data["kind"] == "handoff" and not (data.get("new_record_owner") and data.get("transfer_ack_ref")):
        fail("handoff needs new owner and acknowledgment reference")
    if data["kind"] != "handoff" and ("new_record_owner" in data or "transfer_ack_ref" in data):
        fail("owner transfer fields only allowed at handoff")
    for key in FIELDS - REQUIRED - {"files", "module_changes", "evidence", "open_checks", "resolved_checks", "revision", "schema_version", "status", "verified_revision", "clear_next_step"}:
        if key in data:
            string(data[key], key)
    for key in ("base_sha", "head_sha", "dirty_diff_digest"):
        if key in data and not SHA.fullmatch(data[key]):
            fail("invalid " + key)
    changes = data.get("module_changes", [])
    if not isinstance(changes, list) or len(changes) > 30:
        fail("invalid module changes")
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "what", "why"}:
            fail("module changes need path, what and why")
        for key, value in change.items():
            string(value, key)
    for key in ("files", "open_checks", "resolved_checks"):
        if key in data and (not isinstance(data[key], list) or len(data[key]) > 100 or any(not isinstance(x, str) or not x.strip() or len(x) > 240 for x in data[key])):
            fail("invalid " + key)
    if data.get("source_version") and not SHA.fullmatch(data["source_version"]):
        fail("source_version must be full SHA")
    if data.get("lesson_proposal") and data["kind"] != "proposal":
        fail("lessons must be proposals")
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > 30:
        fail("invalid evidence list")
    if "verified_revision" in data and (type(data["verified_revision"]) is not int or data["verified_revision"] < 1):
        fail("invalid verified revision")
    if (data["kind"] in {"verification", "close"} or any(isinstance(x, dict) and x.get("state") == "independently_verified" for x in evidence)) and not data.get("verified_revision"):
        fail("verification must bind a prior revision")
    if data["kind"] in {"verification", "close"} and not evidence:
        fail("verification or close requires evidence")
    for item in evidence:
        if not isinstance(item, dict) or set(item) - EVIDENCE_FIELDS or not {"state", "claim", "ref"} <= item.keys():
            fail("invalid evidence item")
        if item["state"] not in STATES:
            fail("invalid evidence state")
        for key, value in item.items():
            if key != "state":
                string(value, key)
        if "sha" in item and not SHA.fullmatch(item["sha"]):
            fail("invalid evidence SHA")
        if item["state"] == "independently_verified":
            if not all(item.get(x) for x in ("verified_by", "sha", "environment", "outcome")):
                fail("independent verification needs verifier, SHA, environment and outcome")
            if item["outcome"] not in {"pass", "fail", "unknown"}:
                fail("invalid independent outcome")
            if item["sha"] != data.get("head_sha"):
                fail("independent verification SHA must match event head SHA")
        if "command" in item and not all(item.get(x) for x in ("sha", "environment", "outcome")):
            fail("command evidence needs SHA, environment and outcome")
    if data["kind"] in {"verification", "close"} and not any(x["state"] == "independently_verified" for x in evidence):
        fail("verification requires independent evidence")
    serialized = json.dumps(data, ensure_ascii=False)
    if SECRET.search(serialized) or PRIVATE_PATH.search(serialized):
        fail("possible secret or private session path; sanitize before writing")
    if len(serialized) > 20000:
        fail("event too large")
    return data


def checkout(repo):
    repo = Path(repo).resolve()
    result = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    remote = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True)
    if result.returncode or Path(result.stdout.strip()).resolve() != repo or remote.returncode or not REMOTE.fullmatch(remote.stdout.strip()):
        fail("expected a root checkout of the intended private history repository")
    return repo


def path_for(repo, task_id, create=False):
    if not isinstance(task_id, str) or not ID.fullmatch(task_id):
        fail("invalid task ID")
    repo = checkout(repo)
    directory = repo / "events"
    if create:
        directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or (directory.exists() and (not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077)):
        fail("event directory must be private and not a symlink; run init")
    path = directory / (task_id + ".jsonl")
    if path.is_symlink() or (path.exists() and (not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077)):
        fail("event file must be private regular file; run init")
    return path


@contextmanager
def task_lock(path, exclusive):
    # Locks live in the checkout's git dir, keeping the working tree clean for every writer of it.
    git_dir = subprocess.run(["git", "-C", str(path.parent.parent), "rev-parse", "--absolute-git-dir"],
                             capture_output=True, text=True, check=True).stdout.strip()
    lock = Path(git_dir) / "task-history-locks" / path.parent.name / path.with_suffix(".lock").name
    if lock.is_symlink():
        fail("unsafe lock path")
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600), "r+") as handle:
        if stat.S_IMODE(os.fstat(handle.fileno()).st_mode) & 0o077:
            fail("unsafe lock permissions; run init")
        fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def validate_transition(rows, row):
    """Validate a new event against the same prior state during append and replay."""
    if row["revision"] != len(rows) + 1:
        fail("stale revision")
    if not rows and (row.get("verified_revision") or row.get("correction_of") or any(e["state"] == "independently_verified" for e in row.get("evidence", []))):
        fail("first event cannot refer to prior verification or correction")
    if not rows:
        if row["kind"] != "start":
            fail("first event must start task")
        return
    if row["task_id"] != rows[0]["task_id"]:
        fail("foreign task")
    if row["record_owner"] != owner(rows):
        fail("stale record owner")
    if row.get("correction_of") and row["correction_of"] not in {r["event_id"] for r in rows}:
        fail("correction target not found")
    prior_state = next(r for r in reversed(rows) if "status" in r)
    prior_status = prior_state["status"]
    if "status" in row and (row.get("correction_of") or datetime.strptime(row["at_utc"], "%Y-%m-%dT%H:%M:%SZ") < datetime.strptime(prior_state["at_utc"], "%Y-%m-%dT%H:%M:%SZ")):
        fail("historical correction cannot change current status")
    if prior_status in {"canceled", "done"} and "status" in row:
        fail("terminal task cannot transition")
    if row.get("verified_revision"):
        if row["verified_revision"] != len(rows):
            fail("verification targets stale revision")
        target = rows[-1]
        if not all(target.get(k) for k in ("head_sha", "environment", "execution_owner")):
            fail("target revision has unknown code identity or executor")
        if row.get("head_sha") != target["head_sha"] or row.get("environment") != target["environment"]:
            fail("verification differs from target code identity")
        independent = [e for e in row.get("evidence", []) if e["state"] == "independently_verified"]
        if any(e.get("sha") != target["head_sha"] or e.get("environment") != target["environment"] or e.get("verified_by") == target["execution_owner"] for e in independent):
            fail("verification is stale or not independent")
        if row["kind"] == "close":
            prior_evidence = target.get("evidence", [])
            if target["kind"] != "verification" or not prior_evidence or any(e.get("outcome") != "pass" for e in prior_evidence):
                fail("close requires prior passing verification")
    if row["kind"] == "close":
        if not row.get("approval_ref"):
            fail("close requires exact approval reference")
        if any(e.get("outcome") != "pass" for e in row["evidence"]):
            fail("close requires all evidence to pass")
        if row.get("open_checks") or unresolved(rows):
            fail("close blocked by unresolved checks")


def unresolved(rows, candidate=None):
    checks = {}
    for row in [*rows, *([candidate] if candidate else [])]:
        for check in row.get("open_checks", []):
            checks[check] = True
        for check in row.get("resolved_checks", []):
            checks.pop(check, None)
    return list(checks)


def replay(path):
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        fail("incomplete history tail; valid prefix preserved; reconcile before repair")
    rows, seen = [], set()
    for number, line in enumerate(raw.splitlines(), 1):
        try:
            row = validate(json.loads(line))
        except (ValueError, UnicodeDecodeError) as exc:
            fail(f"corrupt history line {number}; valid prefix preserved: {exc}")
        if row["task_id"] != path.stem or row["event_id"] in seen or row["revision"] != number:
            fail(f"invalid history identity or revision at line {number}")
        try:
            validate_transition(rows, row)
        except ValueError as exc:
            fail(f"invalid transition at line {number} event {row['event_id']}: {exc}")
        seen.add(row["event_id"])
        rows.append(row)
    return rows


def owner(rows):
    current = rows[0]["record_owner"]
    for row in rows:
        if row["kind"] == "handoff":
            current = row["new_record_owner"]
    return current


def snapshot(repo, task_id):
    path = path_for(repo, task_id)
    if not path.parent.exists():
        return [], digest(path)
    with task_lock(path, False):
        return replay(path), digest(path)


def events(repo, task_id):
    return snapshot(repo, task_id)[0]


def digest(path):
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def append(repo, data, expected):
    validate(data)
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail("invalid expected digest")
    path = path_for(repo, data["task_id"], create=True)
    with task_lock(path, True):
        rows = replay(path)
        current = digest(path)
        duplicate = next((row for row in rows if row["event_id"] == data["event_id"]), None)
        if duplicate is not None:
            if duplicate == data:
                return "duplicate", current
            fail("event ID collision with different content")
        if current != expected:
            fail("stale history digest; re-read and reconcile")
        validate_transition(rows, data)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return "appended", digest(path)


def current_next_step(rows):
    step = None
    terminal = False
    for row in rows:
        if terminal:
            continue
        if row.get("clear_next_step"):
            step = None
        elif "next_step" in row:
            step = row["next_step"]
        if row.get("status") in {"canceled", "done"}:
            step = None
            terminal = True
    return step


def project(rows, observed_digest):
    if not rows:
        fail("task not found")
    state = next((r for r in reversed(rows) if "status" in r), rows[0])
    open_checks = unresolved(rows)
    return {"task_id": rows[0]["task_id"], "record_owner": owner(rows), "current": state["summary"], "latest_activity": rows[-1]["summary"], "status": state["status"], "state_revision": state["revision"], "last_event": rows[-1]["event_id"], "last_at_utc": rows[-1]["at_utc"], "next_step": current_next_step(rows), "open_checks": open_checks, "events": len(rows), "digest": observed_digest}


def overview(repo, task):
    rows, observed_digest = snapshot(repo, task)
    return project(rows, observed_digest)


def initialize(repo):
    repo = checkout(repo)
    directory = repo / "events"
    if directory.is_symlink():
        fail("unsafe event directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix not in {".jsonl", ".lock"}:
            fail("unexpected event path; inspect manually")
        os.chmod(path, 0o600)
    return str(directory)


def configured():
    """Return (checkout, None) when central history is on, else (None, reason). Reads only."""
    if not CONFIG.exists():
        return None, f"missing config {CONFIG}"
    value = json.loads(CONFIG.read_text()).get("task_history_repo")
    if not value:
        return None, f"task_history_repo unset in {CONFIG}"
    repo = Path(value).expanduser()
    if not repo.exists():
        return None, f"task_history_repo path missing: {repo}"
    try:
        repo = checkout(repo)
    except ValueError as exc:
        return None, f"not initialized: {repo}: {exc}"
    events = repo / "events"
    if events.is_symlink() or not events.is_dir() or stat.S_IMODE(events.stat().st_mode) & 0o077:
        return None, f"not initialized: {repo} has no private events/; run init"
    return repo, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("append")
    add.add_argument("packet", type=Path)
    add.add_argument("--expected-digest", required=True)
    view = sub.add_parser("view")
    view.add_argument("task_id")
    view.add_argument("--events", action="store_true")
    sub.add_parser("init")
    sub.add_parser("configured", help="print the configured history checkout, or `History: not configured` and exit 1")
    args = parser.parse_args()
    if args.action != "configured" and args.repo is None:
        parser.error("--repo is required")
    try:
        if args.action == "configured":
            repo, reason = configured()
            if reason:
                print("History: not configured")
                print(reason, file=sys.stderr)
                return 1
            print(repo)
        elif args.action == "append":
            result, value = append(args.repo, json.loads(args.packet.read_text()), args.expected_digest)
            print(json.dumps({"result": result, "digest": value}))
        elif args.action == "init":
            print(initialize(args.repo))
        else:
            print(json.dumps(events(args.repo, args.task_id) if args.events else overview(args.repo, args.task_id), indent=2))
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
