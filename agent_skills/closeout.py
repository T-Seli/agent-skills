"""Read-only handoff/completion, merged worktree cleanup and belt archive/monitor eligibility.

The only archive and cleanup check (conveyor.md § Scope): it acts on belt registry sessions and worktrees only."""
import fcntl
import filecmp
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

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
    worktree outside the belt registry (conveyor.md § Scope)."""
    main = Path(main).resolve(strict=True)
    now = time.time() if now is None else now
    # A lease file is text or JSON (e.g. an app's worktree registry); every absolute path it names is held.
    leased = [Path(found.strip()).expanduser().resolve() for name in lease_files
              for found in re.findall(r'(?:^|")(~?/[^"\n]+)', Path(name).expanduser().read_text(encoding="utf-8"),
                                      re.M)]
    belt = {Path(record["worktree"]).resolve() for record in registry() if record.get("worktree")} \
        if belt_only else None
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
            if belt is not None and branch is not None and worktree not in belt:
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


# Belt registry (conveyor.md § Scope): the agent-coordination task store is its one home.
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "agent-coordination" / "scripts"
CONVEYOR = Path(__file__).resolve().parents[1] / "skills" / "workflow-contracts" / "conveyor.json"
VERDICT_FOR = ("monitor_first", "monitor_24h")  # deploy arms the first-traffic schedule, then the 24 h one


def _state_dir():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import tasks
    return tasks.state_dir()


def registry():
    """Task records the belt started (`worker.owner` assistant); a human-owned record is the user's own session."""
    root = _state_dir()
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*.json"))] \
        if root.is_dir() else []
    return [record for record in records if (record.get("worker") or {}).get("owner") == "assistant"]


def archive_check(session_id):
    """Allowed only for a belt session whose every task record is verified-done."""
    found = [record for record in registry() if record["worker"].get("session_id") == session_id]
    if not found:
        return {"allowed": False, "reason": f"session {session_id} is outside the belt registry; "
                                            "the belt never archives a user side session"}
    unfinished = [record["task_id"] for record in found if record.get("status") != "verified-done"]
    if unfinished:
        return {"allowed": False, "reason": f"task {', '.join(unfinished)} is not verified-done"}
    return {"allowed": True, "reason": "verified-done", "tasks": [record["task_id"] for record in found]}


def denial_log():
    """The auto-mode refusal log, next to the registry it is read with."""
    return _state_dir() / "denials.jsonl"


def record_denial(event, *, now=None):
    """Append one refusal line; only the command's first word, never its arguments."""
    command = (event.get("tool_input") or {}).get("command") if event.get("tool_name") == "Bash" else None
    words = [word for word in (command or "").split() if "=" not in word.split("/")[0]]
    line = {"time": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_id": event["session_id"], "cwd": event.get("cwd"), "tool": event["tool_name"],
            "head": os.path.basename(words[0]) if words else None, "tool_use_id": event.get("tool_use_id")}
    path = denial_log()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, "a", encoding="utf-8") as log:
        log.write(json.dumps(line, sort_keys=True) + "\n")
    return line


def belt_denials():
    """Logged refusals of belt sessions, each with its task ids; side-session lines are never counted."""
    path = denial_log()
    tasks_by_session = {}
    for record in registry():
        tasks_by_session.setdefault(record["worker"].get("session_id"), []).append(record["task_id"])
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return [{**line, "tasks": tasks_by_session[line["session_id"]]} for line in lines
            if line["session_id"] in tasks_by_session]


def _task_folders(cwd):
    """Task folders by name, TASK copies (main checkout, then this one) before DRAFT (contracts.md § Folders)."""
    top = Path(_git(cwd, "rev-parse", "--show-toplevel")).resolve()
    main = _worktrees(top)[0]["path"]
    claude = top / "CLAUDE.md"
    named = re.search(r"^- Task records: *`?([^`\s]+)", claude.read_text(encoding="utf-8"), re.M) \
        if claude.is_file() else None
    records = named.group(1) if named else "tasks"
    roots = ([] if records == "none" else [main / records, top / records]) + [main / ".claude" / "drafts"]
    folders = {}
    for root in dict.fromkeys(roots):
        for folder in sorted(root.glob("*/")) if root.is_dir() else ():
            folders.setdefault(folder.name, []).append(folder)
    return folders


def _read(folders, name):
    return "\n".join((folder / name).read_text(encoding="utf-8") for folder in folders if (folder / name).is_file())


def _deploy_blocks(text):
    """Per deploy entry, in order: its schedule ids and the monitor verdict receipts recorded after it."""
    receipts = json.loads(CONVEYOR.read_text(encoding="utf-8"))["receipts"]
    blocks = []
    for line in map(str.strip, text.splitlines()):
        if re.search(receipts["deploy"]["pattern"], line):
            blocks.append({"schedules": [], "verdicts": set()})
        elif blocks and re.match(receipts["schedule"]["pattern"], line):
            if line.split()[2] not in blocks[-1]["schedules"]:
                blocks[-1]["schedules"].append(line.split()[2])
        elif blocks:
            blocks[-1]["verdicts"].update(key for key in VERDICT_FOR if re.match(receipts[key]["pattern"], line))
    return blocks


def monitor_delete_check(cwd, schedule_id):
    """A schedule may go once the deploy that recorded it has that schedule's verdict (first, then 24 h)."""
    found = []
    for name, folders in _task_folders(cwd).items():
        blocks = [block for block in _deploy_blocks(_read(folders, "log.md")) if schedule_id in block["schedules"]]
        if blocks:
            position = blocks[-1]["schedules"].index(schedule_id)
            found.append((name, VERDICT_FOR[position] if position < len(VERDICT_FOR) else None, blocks[-1]))
    if not found:
        return {"allowed": False, "reason": f"no task log records `Scheduler: <runtime> {schedule_id}`"}
    missing = [f"{name} ({need or 'a third schedule has no verdict'})" for name, need, block in found
               if need not in block["verdicts"]]
    if missing:
        return {"allowed": False, "reason": f"monitor {schedule_id} has no recorded verdict in {', '.join(missing)}"}
    return {"allowed": True, "reason": "verdict recorded", "tasks": [name for name, _, _ in found]}


def monitoring_entry_check(cwd, issue):
    """The move into lane monitoring needs two schedule ids on the newest deploy of the issue's task."""
    plan = re.compile(rf"^Issue: \S+#{issue}$", re.M)
    tasks = {name: folders for name, folders in _task_folders(cwd).items() if plan.search(_read(folders, "plan.md"))}
    if not tasks:
        return {"allowed": False, "reason": f"no task plan records `Issue: <owner/repo>#{issue}`"}
    for name, folders in tasks.items():
        blocks = _deploy_blocks(_read(folders, "log.md"))
        count = len(blocks[-1]["schedules"]) if blocks else 0
        if count < 2:
            return {"allowed": False, "reason": f"{name}: {count} `Scheduler:` id(s) on the newest deploy, 2 needed"}
    return {"allowed": True, "reason": "two schedule ids", "tasks": list(tasks)}


def _lane_monitoring_issue(command):
    """The issue number of an `issues-cli lane <n> monitoring` call in the command, else None."""
    for segment in re.split(r"&&|\|\||[;|\n]", command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        for at, token in enumerate(tokens[:-1]):
            if Path(token).name == "issues-cli" and tokens[at + 1] == "lane":
                words = [word for word in tokens[at + 2:] if not word.startswith("-")]
                if words[1:2] == ["monitoring"] and words[0].lstrip("#").isdigit():
                    return words[0].lstrip("#")
    return None


def archive_decision(event):
    """PreToolUse on the session archive tool: a deny reason, else None."""
    session = (event.get("tool_input") or {}).get("session_id")
    verdict = archive_check(event["session_id"] if session in (None, "self") else session)
    return None if verdict["allowed"] else f"Archive refused: {verdict['reason']}."


def monitor_decision(event):
    """PreToolUse on schedule delete and Bash: a deny reason, else None."""
    tool, given, cwd = event.get("tool_name"), event.get("tool_input") or {}, event.get("cwd") or "."
    if tool == "mcp__scheduled-tasks__delete_scheduled_task":
        verdict = monitor_delete_check(cwd, given.get("taskId"))
    elif tool == "Bash" and (issue := _lane_monitoring_issue(given.get("command", ""))):
        verdict = monitoring_entry_check(cwd, issue)
    else:
        return None
    return None if verdict["allowed"] else f"Refused: {verdict['reason']}."


def guard_hook(decide):
    """Run a guard on the hook event from stdin; any error denies, so a broken guard never lets an action by."""
    try:
        reason = decide(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 - fail closed and say why
        reason = f"Guard error, refused: {type(exc).__name__}: {exc}"
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0
