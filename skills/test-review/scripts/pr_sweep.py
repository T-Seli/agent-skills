#!/usr/bin/env python3
"""The only way the scheduled PR sweep finds work and posts: one YES/NO verdict comment per PR head.

  pending  one JSON line per open, non-draft PR whose head has no verdict yet, oldest update first,
           at most `max_per_run` in total
  post     re-read the PR, then post one verdict comment for the reviewed head; refuses (exit 3) a
           stale head, a second verdict for the same head, a closed or draft PR or an unknown repo

GitHub is reached only through `gh`: reads, plus `gh pr comment`. Nothing here approves, merges or
deploys. Config: `pr_sweep` in AGENT_SKILLS_CONFIG (default ~/.config/agent-skills/workers.json):
{"repos": [{"repo": "owner/name", "checkout": "~/Developer/name"}], "authorization": "...", "max_per_run": 3}
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG = Path(os.environ.get("AGENT_SKILLS_CONFIG", "~/.config/agent-skills/workers.json")).expanduser()
REFUSED = 3  # exit code: this verdict must not be posted
MAX_BODY = 3000
MARKER = "<!-- agent-skills:verdict sha={sha} -->"
FOOTER = "_Automated review by a Claude worker. It never approves, merges or deploys._"


def settings():
    sweep = (json.loads(CONFIG.read_text()) if CONFIG.exists() else {}).get("pr_sweep") or {}
    if not sweep.get("repos") or not sweep.get("authorization"):
        sys.exit(f"PR sweep not configured: set pr_sweep.repos and pr_sweep.authorization in {CONFIG}")
    for entry in sweep["repos"]:
        if "/" not in str(entry.get("repo", "")) or not entry.get("checkout"):
            sys.exit(f"pr_sweep: bad repo entry {json.dumps(entry)}: needs repo owner/name and checkout")
    cap = sweep.get("max_per_run", 3)
    if type(cap) is not int or cap < 1:
        sys.exit(f"pr_sweep: max_per_run must be a positive integer, not {cap!r}")
    return {**sweep, "max_per_run": cap}


def gh(*args):
    done = subprocess.run(["gh", *args], capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"pr_sweep: gh {' '.join(args[:2])} failed ({done.returncode}): {done.stderr.strip()}")
    return done.stdout


def has_verdict(repo, number, sha):
    pages = json.loads(gh("api", "--method", "GET", f"repos/{repo}/issues/{number}/comments",
                          "--paginate", "--slurp"))
    marker = MARKER.format(sha=sha)
    return any(marker in (comment.get("body") or "") for page in pages for comment in page)


def refuse(reason):
    print(json.dumps({"refused": reason}))
    print(f"pr_sweep: refused: {reason}", file=sys.stderr)
    sys.exit(REFUSED)


def pending(_args):
    sweep = settings()
    open_prs = []
    for entry in sweep["repos"]:
        listed = json.loads(gh("pr", "list", "-R", entry["repo"], "--state", "open", "--json",
                               "number,headRefOid,isDraft,title,author,updatedAt,url", "--limit", "100"))
        open_prs += [(pr["updatedAt"], entry, pr) for pr in listed if not pr["isDraft"]]
    found = 0
    for _, entry, pr in sorted(open_prs, key=lambda item: item[0]):
        if found == sweep["max_per_run"]:
            break
        if has_verdict(entry["repo"], pr["number"], pr["headRefOid"]):
            continue
        found += 1
        print(json.dumps({"repo": entry["repo"], "checkout": str(Path(entry["checkout"]).expanduser()),
                          "number": pr["number"], "head_sha": pr["headRefOid"], "title": pr["title"],
                          "author": pr["author"]["login"], "url": pr["url"]}))


def post(args):
    sweep = settings()
    if args.repo not in [entry["repo"] for entry in sweep["repos"]]:
        refuse(f"{args.repo} is not a configured PR sweep repo")
    body = Path(args.body_file).read_text().strip()
    if not body or len(body) > MAX_BODY:
        refuse(f"the body is {len(body)} characters; it must be 1 to {MAX_BODY}")
    pr = json.loads(gh("pr", "view", str(args.pr), "-R", args.repo, "--json", "state,isDraft,headRefOid"))
    if pr["state"] != "OPEN" or pr["isDraft"]:
        refuse(f"PR #{args.pr} is {'a draft' if pr['isDraft'] else pr['state']}, not open for review")
    if pr["headRefOid"] != args.sha:
        refuse(f"the head moved to {pr['headRefOid'][:12]}: the review of {args.sha[:12]} is stale")
    if has_verdict(args.repo, args.pr, args.sha):
        refuse(f"a verdict for {args.sha[:12]} is already posted: one comment per head")
    comment = "\n".join([f"**Ready to merge: {args.verdict}**", f"Reviewed head: `{args.sha[:12]}`", "", body,
                         "", FOOTER, MARKER.format(sha=args.sha)]) + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".md") as tmp:
        tmp.write(comment)
        tmp.flush()
        gh("pr", "comment", str(args.pr), "-R", args.repo, "--body-file", tmp.name)
    print(json.dumps({"repo": args.repo, "number": args.pr, "sha": args.sha, "verdict": args.verdict,
                      "posted": True}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending")
    p = sub.add_parser("post")
    p.add_argument("--repo", required=True, help="owner/name, as configured")
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--sha", required=True, help="the full head sha that was reviewed")
    p.add_argument("--verdict", required=True, choices=["YES", "NO"])
    p.add_argument("--body-file", required=True, help="the review text, 1 to 3000 characters")
    args = parser.parse_args(argv)
    return {"pending": pending, "post": post}[args.cmd](args)


if __name__ == "__main__":
    main()
