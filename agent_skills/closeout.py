"""Read-only handoff/completion, merged worktree cleanup and belt archive/monitor eligibility.

The only archive and cleanup check (conveyor.md § Scope): it acts on belt registry sessions and worktrees only."""
import fcntl
import filecmp
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from . import layout
from .task_contract import assess_completion, resume_check


def handoff_gate(packet, saved, *, current_revision, sources_fresh, canceled=False):
    return resume_check(packet, saved, current_revision=current_revision,
                        sources_fresh=sources_fresh, canceled=canceled)


def completion_gate(packet, report, *, verifier_report=None, artifact_root=None,
                    owner_verified=False, human_accepted=False):
    evidence = assess_completion(packet, report, verifier_report, artifact_root=artifact_root)
    if evidence["status"] != "evidence-complete-awaiting-acceptance":
        return {**evidence, "decision": "hold"}
    if not owner_verified or not human_accepted:
        return {**evidence, "decision": "await-owner-or-human-acceptance"}
    return {**evidence, "decision": "accepted"}


def _git(root, *args, limited=True):
    # A worktree in a cloud-synced folder can block git on offloaded files indefinitely.
    # Removals run unlimited: stopping one halfway would leave a partly deleted worktree.
    seconds = float(os.environ.get("AGENT_SKILLS_GIT_TIMEOUT", "30")) if limited else None
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              text=True, check=True, timeout=seconds).stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"git timed out after {seconds:g}s") from exc


def _deploy_lock(root):
    return Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "deploy.lock"


def main_sync_gate(main, *, base, repository, fetched_sha, lock_path):
    """Verify an exact, freshly fetched clean main without pulling or activating it."""
    if (not isinstance(base, str) or not base or not isinstance(repository, str) or not repository or
            not isinstance(fetched_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", fetched_sha)):
        return {"ready": False, "reason": "exact repository, base and fetched SHA required"}
    try:
        main = Path(main).resolve(strict=True)
        if Path(_git(main, "rev-parse", "--show-toplevel")) != main:
            raise ValueError("main checkout root mismatch")
        remote = _git(main, "remote", "get-url", "origin")
        if not re.search(rf"(?:[:/]){re.escape(repository)}(?:\.git)?$", remote):
            raise ValueError("origin repository mismatch")
        if _git(main, "symbolic-ref", "--short", "HEAD") != base:
            raise ValueError("main checkout branch mismatch")
        if _git(main, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("main checkout has tracked or non-ignored untracked changes")
        lock = Path(lock_path)
        if lock.resolve(strict=False) != _deploy_lock(main).resolve(strict=False):
            raise ValueError("lock path does not match repository deploy lock")
        if lock.exists() or lock.is_symlink():
            raise ValueError("active or uncertain owner lock")
        remote_commit = _git(main, "rev-parse", "--verify", f"refs/remotes/origin/{base}^{{commit}}")
        local_commit = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
        if remote_commit != fetched_sha:
            raise ValueError("remote base differs from supplied fresh-fetch receipt")
        if local_commit != remote_commit:
            raise ValueError("main is not exactly synchronized; fast-forward only")
        return {"ready": True, "reason": "exact-clean-synchronized", "repository": repository,
                "base": base, "commit": local_commit, "fetched_sha": fetched_sha,
                "activation": "not-performed"}
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {"ready": False, "reason": str(exc)}


def _worktrees(main):
    """Records from `git worktree list`: `path` plus git's own keys (branch, detached, locked, prunable)."""
    records, current = [], None
    for field in _git(main, "worktree", "list", "--porcelain", "-z").split("\0"):
        if field.startswith("worktree "):
            current = {"path": Path(field[9:]).resolve()}
            records.append(current)
        elif current is not None and field:
            key, _, value = field.partition(" ")
            current[key] = value
    return records


def _worktree_lock(main, worktree):
    """None when unlocked, else git's lock reason ('' when none was given)."""
    return next(record.get("locked") for record in _worktrees(main) if record["path"] == worktree)


def _merge_proof(main, base_commit, commit):
    """'ancestor', or 'no-op' when merging commit into base would change nothing (squash merges)."""
    if _git(main, "merge-base", base_commit, commit) == commit:
        return "ancestor"
    merged = subprocess.run(["git", "-C", str(main), "merge-tree", "--write-tree", base_commit, commit],
                            capture_output=True, text=True)
    if merged.returncode == 0 and merged.stdout.split()[0] == _git(main, "rev-parse", f"{base_commit}^{{tree}}"):
        return "no-op"
    raise ValueError("branch not merged into local base")


def _check_clean(main, worktree, rebuildable):
    """Tracked and untracked entries block; ignored ones only if rebuildable or already in main."""
    declared = [item.strip("/") for item in rebuildable]
    for entry in _git(worktree, "--no-optional-locks", "status", "--porcelain", "-z", "--ignored").split("\0"):
        if not entry:
            continue
        if not entry.startswith("!! "):
            raise ValueError("worktree dirty")
        path = entry[3:]
        name = path.rstrip("/")
        if any(name == item or name.startswith(item + "/") for item in declared):
            continue
        if not _copy_of_main(main, worktree, Path(name)):
            raise ValueError(f"ignored content not rebuildable: {path}")


def _copy_of_main(main, worktree, rel):
    """A symlink into main, or a file or folder whose every file is byte-identical in main."""
    item = worktree / rel
    if item.is_symlink():
        try:
            target = item.resolve(strict=True)
        except (OSError, RuntimeError) as exc:  # missing target, or a loop (RuntimeError before 3.13)
            raise ValueError(f"broken symlink: {rel}") from exc
        if target.is_relative_to(main):
            return True
    elif item.is_dir():  # os.walk descends real folders; symlinked ones are checked as entries
        return all(_copy_of_main(main, worktree, Path(root, entry).relative_to(worktree))
                   for root, dirs, files in os.walk(item)
                   for entry in files + [d for d in dirs if Path(root, d).is_symlink()])
    twin = main / rel
    return twin.is_file() and filecmp.cmp(item, twin, shallow=False)


def cleanup_gate(main, worktree, *, base, completion_accepted, no_pending_effects, branch=None,
                 lock_path=None, expected_lock_owner=None, remote_base=None, rebuildable=(), run_id=None):
    """Never deletes. Exact branch/worktree and merged, clean state must all agree.

    `branch=None` checks a detached worktree (temp base checkouts) at its HEAD commit."""
    if not completion_accepted or not no_pending_effects:
        return {"eligible": False, "reason": "completion-or-effects-pending"}
    try:
        main, worktree = Path(main).resolve(strict=True), Path(worktree).resolve(strict=True)
        if main == worktree or Path(_git(main, "rev-parse", "--show-toplevel")) != main:
            raise ValueError("invalid main/worktree")
        if _git(worktree, "rev-parse", "--show-toplevel") != str(worktree):
            raise ValueError("worktree root mismatch")
        if branch is None:
            if subprocess.run(["git", "-C", str(worktree), "symbolic-ref", "-q", "HEAD"],
                              capture_output=True).returncode == 0:
                raise ValueError("worktree is not detached")
        elif _git(worktree, "symbolic-ref", "--short", "HEAD") != branch:
            raise ValueError("branch mismatch")
        if branch == base or _git(main, "symbolic-ref", "--short", "HEAD") != base:
            raise ValueError("base checkout mismatch")
        _check_clean(main, worktree, rebuildable)
        if _git(main, "rev-parse", "--path-format=absolute", "--git-common-dir") != _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"):
            raise ValueError("unrelated repositories")
        base_commit = _git(main, "rev-parse", "--verify", f"refs/heads/{base}^{{commit}}")
        branch_commit = (_git(worktree, "rev-parse", "HEAD") if branch is None else
                         _git(main, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}"))
        # A temp base checkout sits at merge-base(origin/<base>, head), which a lagging local base may lack.
        fetched = subprocess.run(["git", "-C", str(main), "rev-parse", "-q", "--verify",
                                  f"refs/remotes/origin/{base}^{{commit}}"], capture_output=True, text=True)
        if branch is None and fetched.returncode == 0 and _git(main, "merge-base", fetched.stdout.strip(),
                                                               branch_commit) == branch_commit:
            merge = "ancestor"
        else:
            merge = _merge_proof(main, base_commit, branch_commit)
        reason = _worktree_lock(main, worktree)
        if reason is not None and not set(reason.split()) & {name for name in (branch, run_id) if name}:
            raise ValueError("worktree locked by another owner")
        if remote_base is not None and base_commit != remote_base:
            raise ValueError("local base does not match freshly fetched remote base")
        if (lock_path is None) != (expected_lock_owner is None):
            raise ValueError("lock path and exact expected owner must be paired")
        if lock_path is not None:
            lock = Path(lock_path)
            if lock.resolve(strict=False) != _deploy_lock(main).resolve(strict=False):
                raise ValueError("lock path does not match repository deploy lock")
            owner = lock / "owner"
            if lock.is_symlink() or owner.is_symlink() or not owner.is_file():
                raise ValueError("lock ownership unavailable")
            if owner.read_text(encoding="utf-8").strip() != expected_lock_owner:
                raise ValueError("lock owned by another operation")
        return {"eligible": True, "reason": "review-only", "worktree": str(worktree),
                "branch": branch, "base_commit": base_commit, "branch_commit": branch_commit,
                "merge": merge, "unlock": reason is not None}
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {"eligible": False, "reason": str(exc)}


@contextmanager
def _sweep_lock(main):
    common = Path(_git(main, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    fd = os.open(common / "sweep.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _process_cwds():
    listed = subprocess.run(["lsof", "-d", "cwd", "-Fn"], capture_output=True, text=True)
    if listed.returncode and not listed.stdout:
        raise RuntimeError(f"lsof failed: {listed.stderr.strip()}")
    return {Path(line[1:]).resolve() for line in listed.stdout.splitlines() if line.startswith("n")}


def _inside(path, root):
    return path == root or root in path.parents


def _held(worktree, cwds, leased, *, active_seconds, now):
    """Why a live session may be using this worktree, else None."""
    if any(_inside(cwd, worktree) for cwd in cwds):
        return "a process has its cwd inside"
    if any(_inside(path, worktree) for path in leased):
        return "listed in a lease file"
    gitdir = Path(_git(worktree, "rev-parse", "--absolute-git-dir"))
    for name in ("index", "logs/HEAD"):
        try:
            age = now - (gitdir / name).stat().st_mtime
        except FileNotFoundError:
            continue
        if age < active_seconds:
            return f"git activity {int(age)}s ago"
    return None


def sweep(main, *, base, apply=False, rebuildable=(), lease_files=(), active_seconds=7200, now=None,
          belt_only=False):
    """Run the cleanup gate over every other worktree; with `apply`, remove (never force) the eligible,
    unheld ones and delete a branch only when its merge proof is `ancestor`. `belt_only` keeps every branch
    worktree whose branch no `Claimed:` receipt on an open belt issue names (conveyor.md § Scope)."""
    main = Path(main).resolve(strict=True)
    now = time.time() if now is None else now
    # A lease file is text or JSON (e.g. an app's worktree registry); every absolute path it names is held.
    leased = [Path(found.strip()).expanduser().resolve() for name in lease_files
              for found in re.findall(r'(?:^|")(~?/[^"\n]+)', Path(name).expanduser().read_text(encoding="utf-8"),
                                      re.M)]
    belt = {row["branch"] for row in registry(main) if row["branch"]} if belt_only else None
    report = {"apply": apply, "candidates": [], "held": [], "kept": [], "removed": []}
    with _sweep_lock(main):
        cwds = _process_cwds()
        for record in _worktrees(main):
            worktree = record["path"]
            if worktree == main:
                continue
            branch = record.get("branch", "").removeprefix("refs/heads/") or None
            if not worktree.exists():
                report["kept"].append({"worktree": str(worktree), "reason": "path missing; git worktree prune"})
                continue
            if branch is None and not worktree.name.startswith("_base-"):
                report["kept"].append({"worktree": str(worktree), "reason": "detached and not a temp base"})
                continue
            if belt is not None and branch is not None and branch not in belt:
                report["kept"].append({"worktree": str(worktree), "reason": "outside the belt registry"})
                continue
            try:
                reason = _held(worktree, cwds, leased, active_seconds=active_seconds, now=now)
            except ValueError as exc:
                report["kept"].append({"worktree": str(worktree), "reason": str(exc)})
                continue
            if reason:
                report["held"].append({"worktree": str(worktree), "reason": reason})
                continue
            parts = worktree.name.split("-", 2)
            verdict = cleanup_gate(main, worktree, base=base, branch=branch, completion_accepted=True,
                                   no_pending_effects=True, rebuildable=rebuildable,
                                   run_id=parts[2] if branch is None and len(parts) == 3 else None)
            if not verdict["eligible"]:
                report["kept"].append({"worktree": str(worktree), "reason": verdict["reason"]})
                continue
            report["candidates"].append({"worktree": str(worktree), "branch": branch,
                                         "merge": verdict["merge"], "unlock": verdict["unlock"]})
            if apply:
                if verdict["unlock"]:
                    _git(main, "worktree", "unlock", str(worktree))
                _git(main, "worktree", "remove", str(worktree), limited=False)
                if branch and verdict["merge"] == "ancestor":
                    _git(main, "branch", "-d", branch)
                report["removed"].append(str(worktree))
    return report


# Belt registry and guards (conveyor.json `registry`): receipts on the cwd repo's belt issues are the only source.
# The registry and sweep list open belt issues; each guard instead makes one search for its id over open and closed ones.
SEARCH_LIMIT = 100  # a guard search that fills this cannot prove no open issue was left out, so it fails
VERDICT_FOR = ("monitor_first", "monitor_24h")  # an issue's first `Scheduler:` id is first-traffic, the second 24 h
DEADLINE = re.compile(r"Deadline: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z")  # contracts.md § Scheduler


def _contract():
    return json.loads(layout.contract("conveyor.json").read_text(encoding="utf-8"))


def _state_dir():
    scripts = layout.ROOT / "skills" / "agent-coordination" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import tasks
    return tasks.state_dir()


def belt_issues(cwd, search=None):
    """Issues carrying a `lane:` label in the GitHub repo of `cwd`: every open one, or with `search` the open and
    closed ones holding that exact text, within the guard timeout. Number, open, label names, comment lines."""
    if search is None:
        query, seconds = ["--state", "open", "--limit", "1000"], 30
    else:
        query = ["--state", "all", "--search", f'"{search}"', "--limit", str(SEARCH_LIMIT)]
        seconds = float(os.environ.get("AGENT_SKILLS_GUARD_TIMEOUT", "2"))
    done = subprocess.run(["gh", "issue", "list", *query, "--json", "number,state,labels,comments"],
                          cwd=cwd, capture_output=True, text=True, timeout=seconds)
    if done.returncode:
        raise RuntimeError(f"gh issue list failed: {done.stderr.strip() or done.returncode}")
    listed = json.loads(done.stdout)
    if search is not None and len(listed) >= SEARCH_LIMIT:
        raise RuntimeError(f"search for {search} returned {SEARCH_LIMIT} or more issues; some may be missing")
    issues = []
    for found in listed:
        labels = {label["name"] for label in found["labels"]}
        if any(name.startswith("lane:") for name in labels):
            issues.append({"number": found["number"], "open": found["state"] == "OPEN", "labels": labels,
                           "lines": [line.strip() for comment in found["comments"]
                                     for line in comment["body"].splitlines()]})
    return issues


def _claims(found, receipts):
    """(session, claimed branch or None) for each `Owner:` or `Claimed:` receipt on one issue."""
    for line in found["lines"]:
        for key in ("owner", "claim"):
            if match := re.match(receipts[key]["pattern"], line):
                yield match["session"], line.split("`")[1] if key == "claim" else None


def registry(cwd):
    """One row per `Owner:` or `Claimed:` receipt on an open belt issue: session, issue, parked, claimed branch."""
    receipts = _contract()["receipts"]
    return [{"session": session, "issue": found["number"], "parked": "parked" in found["labels"], "branch": branch}
            for found in belt_issues(cwd) for session, branch in _claims(found, receipts)]


def _session(event):
    """The calling session as receipts name it: the desktop id when the host sets one (as `claim` does)."""
    return os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or event["session_id"]


def archive_check(cwd, session):
    """(decision, reason) per conveyor.json registry guards, from one search for the session over open and closed
    belt issues: on none asks, on an open unparked one denies, else allows."""
    contract = _contract()
    guards = contract["registry"]["guards"]
    if re.fullmatch(contract["session_id"]["pattern"], session) and not session.startswith("local_"):
        return "deny", f"session {session} is a headless worker; it ends by itself and is never archived"
    receipts = contract["receipts"]
    mine = [found for found in belt_issues(cwd, session)
            if any(named == session for named, _ in _claims(found, receipts))]
    if not mine:
        return guards["outside_registry"], f"session {session} is outside the belt registry"
    unfinished = sorted(found["number"] for found in mine if found["open"] and "parked" not in found["labels"])
    if unfinished:
        return guards["registry_unfinished"], \
            f"session {session} has unfinished work on {', '.join(f'#{n}' for n in unfinished)}"
    return guards["registry_done"], "every claimed issue is closed or parked"


def _repo_name(cwd):
    """<repo> (contracts.md): the main worktree's basename; None outside a git checkout."""
    done = subprocess.run(["git", "-C", str(cwd), "worktree", "list", "--porcelain"], capture_output=True, text=True)
    return Path(done.stdout.splitlines()[0][len("worktree "):]).name if done.returncode == 0 else None


def monitor_create_check(cwd, task_id, description):
    """Allow `monitor-<repo>-<slug>` whose description carries a `Deadline:`; anything else asks."""
    repo = _repo_name(cwd)
    if repo is None:
        return "ask", f"monitor {task_id}: {cwd} is not a git checkout, so <repo> is unknown"
    if not re.fullmatch(rf"monitor-{re.escape(repo)}-[a-z0-9]+(?:-[a-z0-9]+)*", task_id or "", re.I):
        return "ask", f"monitor id {task_id} is not monitor-{repo}-<slug>"
    if not DEADLINE.search(description or ""):
        return "ask", f"monitor {task_id} has no `Deadline: YYYY-MM-DDTHH:MMZ` in its description"
    return "allow", "belt monitor id with a deadline"


def monitor_delete_check(cwd, task_id):
    """Allow a `Scheduler:` id on a belt issue once its verdict is recorded; deny before; any other id asks."""
    receipts = _contract()["receipts"]
    for found in belt_issues(cwd, task_id):
        ids = list(dict.fromkeys(line.split()[2] for line in found["lines"]
                                 if re.match(receipts["schedule"]["pattern"], line)))
        if task_id in ids:
            position = ids.index(task_id)
            need = VERDICT_FOR[position] if position < len(VERDICT_FOR) else None
            if need and any(re.match(receipts[need]["pattern"], line) for line in found["lines"]):
                return "allow", "verdict recorded"
            label = receipts[need]["label"] if need else "verdict (only two schedules have one)"
            return "deny", f"#{found['number']}: monitor {task_id} has no {label} receipt yet"
    return "ask", f"{task_id} is not a `Scheduler:` id on a belt issue"


def denial_log():
    """The auto-mode refusal log, in the agent-coordination state dir."""
    return _state_dir() / "denials.jsonl"


def record_denial(event, *, now=None):
    """Append one refusal line; only the command's first word, never its arguments."""
    command = (event.get("tool_input") or {}).get("command") if event.get("tool_name") == "Bash" else None
    words = [word for word in (command or "").split() if "=" not in word.split("/")[0]]
    line = {"time": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_id": _session(event), "cwd": event.get("cwd"), "tool": event["tool_name"],
            "head": os.path.basename(words[0]) if words else None, "tool_use_id": event.get("tool_use_id")}
    path = denial_log()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, "a", encoding="utf-8") as log:
        log.write(json.dumps(line, sort_keys=True) + "\n")
    return line


def belt_denials(cwd):
    """Logged refusals of registry sessions, each with its issue numbers; side-session lines are never counted."""
    issues_by_session = {}
    for row in registry(cwd):
        issues_by_session.setdefault(row["session"], set()).add(row["issue"])
    path = denial_log()
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return [{**line, "issues": sorted(issues_by_session[line["session_id"]])} for line in lines
            if line["session_id"] in issues_by_session]


def session_role(event):
    """The workers.json `roles` name (coordinator, release_owner) of the hook's session, else None."""
    path = Path(os.environ.get("AGENT_SKILLS_CONFIG", "~/.config/agent-skills/workers.json")).expanduser()
    roles = json.loads(path.read_text(encoding="utf-8")).get("roles", {}) if path.is_file() else {}
    names = {event.get("session_id"), os.environ.get("CLAUDE_CODE_HOST_SESSION_ID")} - {None, ""}
    return next((role for role, session in roles.items() if session in names), None)


def resume_picture(event):
    """`issues-cli resume` output for a session named in `roles`, else None; a failed run says so (conveyor.json
    `resume.hooks`). The command is the installed invocation authorizations.json names."""
    if not session_role(event):
        return None
    done = subprocess.run([os.path.expanduser("~/.agents/skills/workflow-contracts/scripts/issues-cli"), "resume"],
                          cwd=event.get("cwd") or ".", capture_output=True, text=True)
    if done.returncode:
        reason = (done.stderr.strip().splitlines() or ["no output"])[-1]
        return f"WARNING: issues-cli resume failed (exit {done.returncode}): {reason}"
    return done.stdout.rstrip("\n")


def archive_decision(event):
    """PreToolUse on the session archive tool; `session_id` "self" means the calling session."""
    target = (event.get("tool_input") or {}).get("session_id")
    return archive_check(event.get("cwd") or ".", _session(event) if target in (None, "self") else target)


def monitor_decision(event):
    """PreToolUse on schedule create and delete; any other tool passes untouched (None)."""
    tool, given, cwd = event.get("tool_name"), event.get("tool_input") or {}, event.get("cwd") or "."
    if tool == "mcp__scheduled-tasks__create_scheduled_task":
        return monitor_create_check(cwd, given.get("taskId"), given.get("description"))
    if tool == "mcp__scheduled-tasks__delete_scheduled_task":
        return monitor_delete_check(cwd, given.get("taskId"))
    return None


def guard_hook(decide):
    """Run a guard on the hook event from stdin; print its ask or deny; any error denies (guard_failure)."""
    try:
        verdict = decide(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 - fail closed and say why
        verdict = ("deny", f"Guard error, refused: {type(exc).__name__}: {exc}")
    if verdict and verdict[0] != "allow":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": verdict[0],
                                                 "permissionDecisionReason": verdict[1]}}))
    return 0
