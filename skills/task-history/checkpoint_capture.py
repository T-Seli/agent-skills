#!/usr/bin/env python3
"""Admit one authorized structured checkpoint to local task history.

The host must supply this packet at a task boundary. This module has no session
reader, background hook, network call, or publication side effect.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import history
import markdown


REQUIRED = {"authorization_ref", "expected_digest", "event"}
ALLOWED = REQUIRED


def capture(repo, checkpoint):
    if not isinstance(checkpoint, dict) or set(checkpoint) != ALLOWED:
        raise ValueError("checkpoint needs authorization, expected digest and event")
    authorization = checkpoint["authorization_ref"]
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError("checkpoint authorization is required")
    event = checkpoint["event"]
    if not isinstance(event, dict) or event.get("approval_ref") != authorization:
        raise ValueError("event approval reference must match checkpoint authorization")
    history.validate(event)
    rows, current = history.snapshot(repo, event["task_id"])
    if any(row == event for row in rows):
        result, digest = history.append(repo, event, checkpoint["expected_digest"])
        return {"result": result, "event_id": event["event_id"], "digest": digest}
    if rows and history.owner(rows) != event["record_owner"]:
        raise ValueError("checkpoint record owner does not match current journal")
    if not rows and (event["kind"] != "start" or event["revision"] != 1):
        raise ValueError("new task needs a start event")
    if current != checkpoint["expected_digest"]:
        raise ValueError("stale checkpoint digest; reconcile before retry")
    result, digest = history.append(repo, event, checkpoint["expected_digest"])
    return {"result": result, "event_id": event["event_id"], "digest": digest}


def verify_publication(repo, *, task_id, event_id, expected_digest, reader_ref):
    """Verify journal, generated view, and index from the caller's fresh reader checkout."""
    if not isinstance(reader_ref, str) or not reader_ref.strip():
        raise ValueError("fresh reader reference is required")
    rows, current = history.snapshot(repo, task_id)
    if current != expected_digest:
        raise ValueError("published journal digest does not match expected digest")
    if event_id not in {row["event_id"] for row in rows}:
        raise ValueError("published journal is missing the expected event")
    view = Path(repo).resolve() / "views" / f"{task_id}.md"
    if not view.is_file() or view.is_symlink():
        raise ValueError("published generated view is missing or unsafe")
    content = view.read_text(encoding="utf-8")
    marker = markdown.MARKER.match(content)
    if (not marker or marker.group(2) != current or
            hashlib.sha256(content[marker.end():].encode()).hexdigest() != marker.group(1)):
        raise ValueError("published generated view does not match the journal")
    index = Path(repo).resolve() / "INDEX.md"
    if not index.is_file() or index.is_symlink():
        raise ValueError("published index is missing or unsafe")
    index_text = index.read_text(encoding="utf-8")
    if f"(views/{task_id}.md)" not in index_text or f"(events/{task_id}.jsonl)" not in index_text:
        raise ValueError("published index is missing the task journal or view link")
    return {"task_id": task_id, "event_id": event_id, "revision": len(rows),
            "record_owner": history.owner(rows), "digest": current,
            "reader_ref": reader_ref.strip(), "view": str(view), "index": str(index)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(capture(args.repo, json.loads(args.checkpoint.read_text()))))
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
