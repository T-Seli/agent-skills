#!/usr/bin/env python3
"""Bounded PR review queue and publisher. No approve, merge, issue-close or deploy.

Config pr_sweep requires repos, authorization, reviewer_id (GitHub numeric account
id), review_policy (explicit version), publisher_host (the single publishing host),
and optional max_per_run. Existing configurations must be explicitly migrated.
The same host serializes each PR and journals an attempt before publication;
ambiguous attempts require reconciliation, never blind retries. No distributed lock
or GitHub compare-and-swap is claimed. Configure one publisher host only.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG = Path(os.environ.get("AGENT_SKILLS_CONFIG", "~/.config/agent-skills/workers.json")).expanduser()
REFUSED = 3
MAX_BODY = 3000
FOOTER = "_Automated advisory review by agent-skills. It never approves, merges or deploys._"


def settings():
    sweep = (json.loads(CONFIG.read_text()) if CONFIG.exists() else {}).get("pr_sweep") or {}
    if not sweep.get("repos") or not sweep.get("authorization"):
        sys.exit(f"PR sweep not configured: set pr_sweep.repos and pr_sweep.authorization in {CONFIG}")
    for entry in sweep["repos"]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(entry.get("repo", ""))) or not entry.get("checkout"):
            sys.exit("pr_sweep: repo entry needs owner/name and checkout")
    cap = sweep.get("max_per_run", 3)
    if type(cap) is not int or cap < 1:
        sys.exit("pr_sweep: max_per_run must be a positive integer")
    if sweep.get("schema_version") != 2 or sweep.get("mode") not in ("shadow", "publish") or type(sweep.get("reviewer_id")) is not int or sweep["reviewer_id"] < 1 or not isinstance(sweep.get("review_policy"), str) or not sweep["review_policy"].strip() or not sweep.get("publisher_host"):
        sys.exit("pr_sweep: explicit v2 migration required: mode, reviewer_id, review_policy and publisher_host")
    if sweep["mode"] == "publish" and (not isinstance(sweep.get("publication_authorization"), str) or not sweep["publication_authorization"].strip()):
        sys.exit("pr_sweep: publish requires its own scoped publication_authorization; legacy approval is retained, not expanded")
    if sweep["publisher_host"] != socket.gethostname():
        sys.exit("pr_sweep: this is not the configured single publisher host")
    return {**sweep, "max_per_run": cap}


def gh(*args):
    done = subprocess.run(["gh", *args], capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"pr_sweep: gh {' '.join(args[:2])} failed ({done.returncode}): {done.stderr.strip()}")
    return done.stdout


def identity(sweep):
    me = json.loads(gh("api", "user"))
    if me.get("id") != sweep["reviewer_id"]:
        refuse("connected GitHub identity differs from configured reviewer_id")


def key(repo, number, sha, base, sweep):
    if not all(re.fullmatch(r"[0-9a-f]{40}", value or "") for value in (sha, base)):
        refuse("full head and resolved base SHAs are required")
    return {"repo": repo, "pr": number, "head": sha, "base": base,
            "policy": sweep["review_policy"], "reviewer_id": sweep["reviewer_id"]}


def marker(binding):
    return "<!-- agent-skills:verdict-v2 " + json.dumps(binding, sort_keys=True, separators=(",", ":")) + " -->"


def review_state(binding):
    pages = json.loads(gh("api", "--method", "GET", f"repos/{binding['repo']}/issues/{binding['pr']}/comments",
                          "--paginate", "--slurp"))
    expected = marker(binding)
    authored = [c for page in pages for c in page if c.get("user", {}).get("id") == binding["reviewer_id"]]
    if any(expected in (c.get("body") or "") for c in authored):
        return {"state": "current"}
    legacy = re.compile(r"<!-- agent-skills:verdict sha=" + re.escape(binding["head"]) + r" -->")
    old = [c for c in authored if legacy.search(c.get("body") or "")]
    if old:
        return {"state": "legacy_hold", "existing_review_refs": [
            c.get("html_url") or c.get("url") or f"comment id {c.get('id', 'unavailable')}" for c in old]}
    return {"state": "pending"}


def has_verdict(binding):
    # A legacy hold is deliberately not current head/base/policy proof.
    return review_state(binding)["state"] == "current"


def admit_review(binding):
    status = review_state(binding)
    if status["state"] == "current":
        refuse("an authenticated verdict for this head/base/policy is already posted")
    if status["state"] == "legacy_hold":
        refuse("legacy same-head review requires reconciliation; no duplicate review/publication: " +
               ", ".join(status["existing_review_refs"]))


def refuse(reason):
    print(json.dumps({"refused": reason}))
    print(f"pr_sweep: refused: {reason}", file=sys.stderr)
    sys.exit(REFUSED)


def state_paths(binding, create=False):
    root = CONFIG.parent / "pr-sweep-state"
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    pr_id = hashlib.sha256(f"{binding['repo']}#{binding['pr']}".encode()).hexdigest()
    attempt_id = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    return root / (pr_id + ".lock"), root / (attempt_id + ".json")


@contextlib.contextmanager
def owned_lock(path):
    with path.open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            refuse("another publisher owns this PR; reconcile rather than duplicate")
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def journal(path, binding):
    # Exclusive create + fsync before the network call: a failed/uncertain call is
    # never retried automatically. Keep this record for manual supported readback.
    with path.open("x") as out:
        json.dump({"binding": binding, "state": "attempted; outcome requires readback"}, out)
        out.flush()
        os.fsync(out.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def pending(_args):
    sweep = settings()
    identity(sweep)
    open_prs = []
    for entry in sweep["repos"]:
        pages = json.loads(gh("api", "--method", "GET", f"repos/{entry['repo']}/pulls?state=open&per_page=100",
                              "--paginate", "--slurp"))
        open_prs += [(pr["updated_at"], entry, pr) for page in pages for pr in page if not pr["draft"]]
    found = 0
    for _, entry, pr in sorted(open_prs, key=lambda item: item[0]):
        if found == sweep["max_per_run"]:
            break
        binding = key(entry["repo"], pr["number"], pr["head"]["sha"], pr["base"]["sha"], sweep)
        status = review_state(binding)
        if status["state"] == "current":
            continue
        if status["state"] == "legacy_hold":
            print(json.dumps({"held": "legacy_same_head_review", "repo": binding["repo"],
                              "number": binding["pr"], "head_sha": binding["head"],
                              "current_v2_proof": False, "existing_review_refs": status["existing_review_refs"]}), file=sys.stderr)
            continue
        _, attempt = state_paths(binding)
        if attempt.exists():
            print(f"pr_sweep: held uncertain attempt for {entry['repo']}#{pr['number']}; reconcile {attempt}", file=sys.stderr)
            continue
        found += 1
        print(json.dumps({"repo": entry["repo"], "checkout": str(Path(entry["checkout"]).expanduser()),
                          "number": pr["number"], "head_sha": binding["head"], "base_sha": binding["base"],
                          "policy": binding["policy"], "title": pr["title"],
                          "author": pr["user"]["login"], "url": pr["html_url"]}))


def current_pr(repo, number):
    return json.loads(gh("pr", "view", str(number), "-R", repo, "--json", "state,isDraft,headRefOid,baseRefOid"))


def validate_pr(pr, binding):
    if pr["state"] != "OPEN" or pr["isDraft"]:
        refuse(f"PR #{binding['pr']} is {'a draft' if pr['isDraft'] else pr['state']}, not open for review")
    if pr["headRefOid"] != binding["head"] or pr["baseRefOid"] != binding["base"]:
        refuse("head or base moved: this review is stale")


def post(args):
    sweep = settings()
    if args.repo not in [entry["repo"] for entry in sweep["repos"]]:
        refuse(f"{args.repo} is not a configured PR sweep repo")
    if args.policy != sweep["review_policy"]:
        refuse("review policy changed: this review is stale")
    binding = key(args.repo, args.pr, args.sha, args.base, sweep)
    body = Path(args.body_file).read_text().strip()
    if not body or len(body) > MAX_BODY:
        refuse(f"the body is {len(body)} characters; it must be 1 to {MAX_BODY}")
    identity(sweep)
    if sweep["mode"] == "shadow":
        validate_pr(current_pr(args.repo, args.pr), binding)
        admit_review(binding)
        print(json.dumps({"repo": args.repo, "number": args.pr, "sha": args.sha, "base": args.base,
                          "policy": args.policy, "posted": False, "mode": "shadow",
                          "next": "retain local review; publication is not enabled"}))
        return
    lock, attempt = state_paths(binding, create=True)
    with owned_lock(lock):
        validate_pr(current_pr(args.repo, args.pr), binding)
        admit_review(binding)
        if attempt.exists():
            refuse(f"prior publication outcome requires reconciliation: {attempt}")
        comment = "\n".join([f"**Advisory readiness: {args.verdict}**", f"Reviewed head: `{args.sha}`; base: `{args.base}`",
                             "", body, "", FOOTER, marker(binding)]) + "\n"
        with tempfile.NamedTemporaryFile("w", suffix=".md") as tmp:
            tmp.write(comment)
            tmp.flush()
            # A final read narrows the remote race; GitHub comment creation has no
            # atomic head/base precondition. Recheck after posting and report staleness.
            validate_pr(current_pr(args.repo, args.pr), binding)
            admit_review(binding)
            journal(attempt, binding)
            result = gh("pr", "comment", str(args.pr), "-R", args.repo, "--body-file", tmp.name).strip()
        after = current_pr(args.repo, args.pr)
        still_current = after["state"] == "OPEN" and not after["isDraft"] and after["headRefOid"] == args.sha and after["baseRefOid"] == args.base
        print(json.dumps({"repo": args.repo, "number": args.pr, "sha": args.sha, "base": args.base,
                          "policy": args.policy, "verdict": args.verdict, "posted": True,
                          "current_after_post": still_current, "comment": result}))
        if not still_current:
            print("pr_sweep: published exact-source advisory became stale; reconcile with owner, no automatic repost", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending")
    p = sub.add_parser("post")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--sha", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--policy", required=True)
    p.add_argument("--verdict", required=True, choices=["YES", "NO"])
    p.add_argument("--body-file", required=True)
    args = parser.parse_args(argv)
    try:
        return {"pending": pending, "post": post}[args.cmd](args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        refuse(f"invalid data or local state: {error}")


if __name__ == "__main__":
    main()
