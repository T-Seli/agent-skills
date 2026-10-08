#!/usr/bin/env python3
"""Admit one authorized structured checkpoint to local task history.

The host must supply this packet at a task boundary. This module has no session
reader, background hook, network call, or publication side effect.
"""
import argparse
import json
from pathlib import Path
import sys

import history


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
