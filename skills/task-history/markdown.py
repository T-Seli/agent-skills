#!/usr/bin/env python3
"""Deterministic human-readable view of private task events; JSONL remains authoritative."""
import argparse
import hashlib
import html
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

import history

MARKER = re.compile(r"^<!-- task-history:generated sha256=([0-9a-f]{64}) source=([0-9a-f]{64}) -->\n")
SPECIAL = re.compile(r"([\\`*_{}\[\]()|])")


def safe(value):
    # Escape inline syntax and any line that could become a heading, quote or list.
    lines = []
    for line in str(value).splitlines():
        escaped = SPECIAL.sub(r"\\\1", html.escape(line, quote=True))
        if re.match(r"^\s*(?:[#>]|[-+*]\s|\d+\.\s)", line):
            offset = len(line) - len(line.lstrip())
            escaped = escaped[:offset] + "\\" + escaped[offset:]
        lines.append(escaped)
    return "\n".join(lines)


def field(label, value):
    return f"**{label}:** {safe(value)}\n\n" if value else ""


def section(title, body):
    return f"### {title}\n\n{body}" if body else ""


def render(rows, state):
    task = rows[0]["task_id"]
    out = [f"# Task {safe(task)}\n\n", "## Current overview\n\n",
           field("Status", state["status"]), field("Current state", state["current"]), field("Latest activity", state["latest_activity"]),
           field("Record owner", state["record_owner"]),
           field("Latest event", state["last_event"]),
           field("Events", state["events"]), field("Source digest", state["digest"])]
    if state.get("next_step"):
        out.append(field("Next step", state["next_step"]))
    if state["open_checks"]:
        out.append("**Unresolved checks:**\n\n" + "".join(f"- {safe(x)}\n" for x in state["open_checks"]) + "\n")
    out.append("The event journal is the audit source. Statements below retain their recorded provenance; commands are displayed, never run.\n\n")
    out.append("## Chronological implementation log\n\n")
    for row in rows:
        anchor = f"event-{row['event_id']}"
        out.append(f'<a id="{anchor}"></a>\n')
        out.append(f"## {safe(row['at_utc'])} — {safe(row['kind'])}: {safe(row['summary'])}\n\n")
        out.append(field("Event", row["event_id"]) + field("Revision", row["revision"]) + field("Session", row["session_id"]))
        out.append(field("Record owner at event", row["record_owner"]) + field("Execution owner", row.get("execution_owner")))
        out.append(field("Observed", row["observed_at_utc"]) + field("Status change", row.get("status")))
        out.append(field("Approval reference", row.get("approval_ref")) + field("Source reference", row.get("source_ref")))
        out.append(field("Repository", row.get("repo_ref")) + field("Branch", row.get("branch_ref")) + field("Base SHA", row.get("base_sha")) + field("Head SHA", row.get("head_sha")) + field("Dirty diff digest", row.get("dirty_diff_digest")) + field("Environment", row.get("environment")) + field("Source version", row.get("source_version")) + field("Runtime version", row.get("runtime_version")))
        audit = field("Verified revision", row.get("verified_revision"))
        if row.get("open_checks"):
            audit += "**Checks opened:**\n\n" + "".join(f"- {safe(x)}\n" for x in row["open_checks"]) + "\n"
        if row.get("resolved_checks"):
            audit += "**Checks resolved:**\n\n" + "".join(f"- {safe(x)}\n" for x in row["resolved_checks"]) + "\n"
        out.append(section("Audit state changes", audit))
        context = field("Scope", row.get("scope")) + field("Excluded scope", row.get("excluded_scope")) + (safe(row["context"]) + "\n\n" if row.get("context") else "")
        out.append(section("Context", context))
        implementation = (safe(row["implementation"]) + "\n\n" if row.get("implementation") else "")
        for change in row.get("module_changes", []):
            implementation += f"- **{safe(change['path'])}:** {safe(change['what'])} **Why:** {safe(change['why'])}\n"
        if row.get("module_changes"):
            implementation += "\n"
        if row.get("files"):
            implementation += "**Files:** " + ", ".join(safe(x) for x in row["files"]) + "\n\n"
        out.append(section("Implementation", implementation))
        decisions = field("Decision", row.get("decision")) + field("Why", row.get("reason")) + field("Failed approach", row.get("failed_approach"))
        out.append(section("Decisions and alternatives", decisions))
        if row["kind"] == "feedback":
            feedback = (field("Category", row["feedback_category"]) + field("Observed issue", row["feedback_issue"])
                        + field("Impact or rework", row["feedback_impact"]) + field("Correction", row["feedback_correction"])
                        + field("Prevention check", row["feedback_prevention_check"])
                        + field("Check state", row["feedback_check_state"]) + field("Check reference", row.get("feedback_check_ref"))
                        + field("Cause basis", row.get("feedback_cause_basis")) + field("Cause", row.get("feedback_cause")))
            out.append(section("Feedback and prevention", feedback))
        validation = ("**Event-authored validation narrative (not independent verification):** " + safe(row["validation"]) + "\n\n" if row.get("validation") else "")
        evidence = row.get("evidence", [])
        if evidence:
            validation += "**Evidence as recorded:**\n\n"
            for item in evidence:
                label = {"performed": "Performed", "reported": "Reported", "independently_verified": "Independently verified"}[item["state"]]
                validation += f"- **{label}:** {safe(item['claim'])} (ref: {safe(item['ref'])})"
                for key, label in (("outcome", "outcome"), ("sha", "SHA"), ("environment", "environment"), ("command", "command"), ("verified_by", "verifier")):
                    if item.get(key):
                        validation += f"; {label}: {safe(item[key])}"
                validation += "\n"
            validation += "\n"
        else:
            validation += "**Evidence:** none recorded for this event.\n\n"
        out.append(section("Validation and evidence", validation))
        outcomes = ("**Event-authored outcome:** " + safe(row["outcomes"]) + "\n\n" if row.get("outcomes") else "") + field("Monitoring", row.get("monitoring")) + field("Uncertainty", row.get("uncertainty"))
        out.append(section("Outcomes and monitoring", outcomes))
        handoff = field("Next step", row.get("next_step")) + ("**Next-step update:** Cleared\n\n" if row.get("clear_next_step") else "") + field("New record owner", row.get("new_record_owner")) + field("Transfer acknowledgment", row.get("transfer_ack_ref"))
        out.append(section("Handoff and resumption", handoff))
        if row.get("correction_of"):
            out.append(field("Correction of", row["correction_of"]))
        if row.get("lesson_proposal"):
            out.append(section("Improvement proposal (requires review)", safe(row["lesson_proposal"]) + "\n\n"))
    return "".join(out)


def document(rows, state):
    body = render(rows, state)
    marker = f"<!-- task-history:generated sha256={hashlib.sha256(body.encode()).hexdigest()} source={state['digest']} -->\n"
    return marker + body


def write(repo, task):
    path = history.path_for(repo, task)
    with history.task_lock(path, True):
        rows = history.replay(path)
        state = history.project(rows, history.digest(path))
        content = document(rows, state)
        directory = Path(repo).resolve() / "views"
        if directory.is_symlink():
            history.fail("unsafe view directory")
        directory.mkdir(mode=0o700, exist_ok=True)
        if stat.S_IMODE(directory.stat().st_mode) & 0o077:
            history.fail("view directory must be private")
        output = directory / f"{task}.md"
        with history.task_lock(output, True):
            if output.is_symlink() or (output.exists() and (not output.is_file() or stat.S_IMODE(output.stat().st_mode) & 0o077)):
                history.fail("unsafe view file")
            if output.exists():
                previous = output.read_text(encoding="utf-8")
                if previous == content:
                    return "unchanged", output
                match = MARKER.match(previous)
                if not match or hashlib.sha256(previous[match.end():].encode()).hexdigest() != match.group(1):
                    history.fail("view contains user edits; preserve it and resolve manually")
            fd, temp = tempfile.mkstemp(prefix=f".{task}.", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, output)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return "written", output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("task_id")
    parser.add_argument("--write", action="store_true", help="create or update only the managed views/<task>.md file")
    args = parser.parse_args()
    try:
        if args.write:
            result, path = write(args.repo, args.task_id)
            print(f"{result}: {path}")
        else:
            rows, source_digest = history.snapshot(args.repo, args.task_id)
            print(document(rows, history.project(rows, source_digest)), end="")
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
