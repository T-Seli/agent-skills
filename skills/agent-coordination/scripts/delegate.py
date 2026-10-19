#!/usr/bin/env python3
"""The one supported way for an agent to start a Claude worker (worker-execution.md § Delegate).

  start      create the task record, pin its route, launch a detached supervisor; prints one JSON line
  wait       block until the run's receipt exists (bounded); prints the receipt
  status     one JSON line per run: live, done, failed, timeout, lost
  reconcile  settle runs whose supervisor died (reboot, kill) as lost
  report     outcomes, cost and permission denials over recent days, for the skill steward

The supervisor holds `caffeinate -i -w <worker pid>`, runs `claude -p` in guarded bypass with the
prompt on stdin, saves the stream, then records the execution, the task events and the receipt.
A worker that delegates again inherits AGENT_SKILLS_DEPTH + 1; the ledger refuses past `max_depth`,
past `max_live` running workers, and a second writer in the same directory.
"""
import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT)]
import tasks  # noqa: E402
import workers  # noqa: E402
from agent_skills import worker_execution  # noqa: E402

CONFIG = Path(os.environ.get("AGENT_SKILLS_CONFIG", "~/.config/agent-skills/workers.json")).expanduser()
EXAMPLE = ROOT / "agent_skills" / "delegate_config.example.json"
GUARD = ROOT / "guard"
REFUSED = 3  # exit code: the ledger refused the launch; do the work yourself or wait
AWS_SECRETS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE")
DB_SECRETS = ("DATABASE_URL", "PGPASSWORD", "PGHOST", "PGUSER", "PGDATABASE", "PGPORT", "PGSERVICE")


def now():
    return datetime.now(timezone.utc)


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def config():
    if not CONFIG.exists():
        sys.exit(f"delegate: missing {CONFIG}; copy {EXAMPLE} there and set the routes")
    return json.loads(CONFIG.read_text())


def runs_root():
    return tasks.state_dir() / "runs"


def write_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def alive(pid, marker):
    """True only for a running process whose command line still names `marker` (pid reuse)."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    shown = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    return marker in shown


def runs():
    """Every run directory, oldest first: runs/<task_id>/<dispatch_id>/."""
    return sorted((p.parent for p in runs_root().glob("*/*/supervisor.json")), key=lambda run: run.name)


def run_state(run):
    receipt = run / "receipt.json"
    if receipt.exists():
        return json.loads(receipt.read_text())["outcome"]
    sup = json.loads((run / "supervisor.json").read_text())
    return "live" if alive(sup["supervisor_pid"], "delegate.py") else "lost?"


def refuse(reason):
    print(json.dumps({"refused": reason}))
    print(f"delegate: refused: {reason}", file=sys.stderr)
    sys.exit(REFUSED)


def guard_settings(run):
    """Deny rules plus the fail-closed PreToolUse hook, with this install's absolute paths."""
    settings = json.loads((GUARD / "worker-settings.json").read_text())
    hook = f"{shlex.quote(sys.executable)} {shlex.quote(str(GUARD / 'worker-guard.py'))}"
    settings["hooks"] = {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": hook, "timeout": 10}]}]}
    path = run / "guard.json"
    write_json(path, settings)
    return path


def env_changes(cfg, depth, task_id):
    """Only the changes are stored (params.json); the supervisor applies them to its inherited env."""
    changes = {"set": {"AGENT_SKILLS_DEPTH": str(depth + 1), "AGENT_SKILLS_TASK_ID": task_id}, "unset": []}
    if not cfg.get("aws"):
        changes["unset"] += AWS_SECRETS
        changes["set"].update(AWS_SHARED_CREDENTIALS_FILE="/dev/null", AWS_CONFIG_FILE="/dev/null")
    if not cfg.get("databases"):
        changes["unset"] += DB_SECRETS
        changes["set"]["PGPASSFILE"] = "/dev/null"
    return changes


def source_pin():
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return f"{ROOT}@{head or 'snapshot'}"


def start(args):
    cfg = config()
    depth = int(os.environ.get("AGENT_SKILLS_DEPTH", "0"))
    if depth >= cfg["max_depth"]:
        refuse(f"depth {depth} reached max_depth {cfg['max_depth']}: do this yourself or use a subagent")
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        sys.exit(f"delegate: no such directory {cwd}")
    live = [r for r in runs() if run_state(r) == "live"]
    if len(live) >= cfg["max_live"]:
        refuse(f"{len(live)} workers already running (max_live {cfg['max_live']}): wait for one")
    for r in live:
        if json.loads((r / "params.json").read_text())["cwd"] == str(cwd):
            refuse(f"a worker is already writing in {cwd} ({r.parent.name}): one writer per directory")
    prompt = sys.stdin.read() if args.prompt_file == "-" else Path(args.prompt_file).read_text()
    if not prompt.strip():
        sys.exit("delegate: empty prompt")

    route = worker_execution.select_route(cfg["policy"], cfg["capabilities"], provider="claude",
                                          signals=args.signal, reason=args.reason)
    root = tasks.state_dir()
    task_id = args.task_id or f"w-{now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    dispatch_id = f"d{time.time_ns() // 1_000_000}"
    parent = os.environ.get("AGENT_SKILLS_TASK_ID", "top-level")
    decision = args.decision_ref or f"delegated-by:{parent}"
    if args.resume:
        session_id = tasks.load(root, task_id)["worker"]["session_id"]
        if not session_id:
            sys.exit(f"delegate: task {task_id} has no owned session to resume")
        tasks.update(root, task_id, lambda r: tasks.begin_dispatch(worker_execution.bind_route(
            r, route, source_pin=source_pin(), decision_ref=decision, change_ref=decision), dispatch_id, resume=True))
    else:
        session_id = str(uuid.uuid4())
        record = tasks.new_task(task_id, args.work_item or task_id, worker_kind="claude", owner="assistant",
                                repo=str(cwd), worktree=str(cwd), source_thread=parent)
        record = worker_execution.bind_route(record, route, source_pin=source_pin(), decision_ref=decision)
        tasks.create(root, tasks.begin_dispatch(record, dispatch_id, resume=False))

    run = runs_root() / task_id / dispatch_id
    run.mkdir(parents=True, mode=0o700)
    (run / "prompt.md").write_text(prompt)
    os.chmod(run / "prompt.md", 0o600)
    claude = workers.Claude(route["model"], route["effort"], route.get("max_cost_usd"),
                            settings=guard_settings(run), max_turns=route.get("max_turns"),
                            name=args.name or task_id, mcp_config=cfg.get("mcp_config"))
    write_json(run / "params.json", {
        "task_id": task_id, "dispatch_id": dispatch_id, "cwd": str(cwd), "depth": depth + 1,
        "argv": claude.command(session_id=session_id, resume=args.resume),
        "timeout_seconds": route["timeout_seconds"], "route": {k: route[k] for k in ("tier", "model", "effort")},
        "env": env_changes(cfg, depth, task_id)})
    log = open(run / "supervisor.log", "w")
    sup = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_supervise", str(run)],
                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    write_json(run / "supervisor.json", {"supervisor_pid": sup.pid, "worker_pid": None, "started_at": stamp(now())})
    print(json.dumps({"task_id": task_id, "dispatch_id": dispatch_id, "session_id": session_id,
                      "run_dir": str(run), "depth": depth + 1, "route": route["tier"]}))


def supervise(run):
    run = Path(run)
    p = json.loads((run / "params.json").read_text())
    root, task_id, dispatch_id = tasks.state_dir(), p["task_id"], p["dispatch_id"]
    started, t0 = now(), time.time()
    env = {k: v for k, v in os.environ.items() if k not in p["env"]["unset"]}
    env.update(p["env"]["set"])
    try:
        with open(run / "prompt.md") as prompt, open(run / "stream.jsonl", "w") as out, \
                open(run / "stderr.log", "w") as err:
            worker = subprocess.Popen(p["argv"], cwd=p["cwd"], stdin=prompt, stdout=out, stderr=err,
                                      env=env, start_new_session=True)
    except FileNotFoundError as error:
        tasks.update(root, task_id, tasks.settle_dispatch, dispatch_id, "not-sent")
        feedback(task_id, [{"kind": "worker-unavailable"}])
        write_json(run / "receipt.json", {"task_id": task_id, "dispatch_id": dispatch_id, "outcome": "unavailable",
                                          "error": str(error), "finished_at": stamp(now())})
        return
    sup = json.loads((run / "supervisor.json").read_text())
    write_json(run / "supervisor.json", {**sup, "worker_pid": worker.pid})
    # The session id was fixed before launch, so a started process settles the dispatch.
    tasks.update(root, task_id, tasks.settle_dispatch, dispatch_id, "sent")
    awake = "not-applicable"
    if sys.platform == "darwin":
        subprocess.Popen(["caffeinate", "-i", "-w", str(worker.pid)], start_new_session=True)
        awake = "held"
    outcome = "done"
    try:
        worker.wait(timeout=p["timeout_seconds"])
    except subprocess.TimeoutExpired:
        outcome = "timeout"
        for sig, grace in ((signal.SIGTERM, 10), (signal.SIGKILL, None)):
            try:
                os.killpg(worker.pid, sig)
                worker.wait(timeout=grace)
                break
            except (ProcessLookupError, subprocess.TimeoutExpired):
                continue
        worker.wait()
    finished = now()
    if outcome == "done" and worker.returncode != 0:
        outcome = "failed"
    stdout, stderr = (run / "stream.jsonl").read_text(), (run / "stderr.log").read_text()
    parsed = workers.Claude().parse(stdout)
    execution = workers.RunResult("uncertain" if outcome == "timeout" else outcome, stdout, stderr,
                                  worker.returncode, worker.pid, started.isoformat(), finished.isoformat())
    ref, bookkeeping = f"delegate:{task_id}:{dispatch_id}", None
    try:
        tasks.update(root, task_id, worker_execution.record_execution, dispatch_id, execution, parsed,
                     receipt_ref=ref)
        for event in workers.events(task_id, dispatch_id, parsed, t0, time.time()):
            tasks.receive(root, event)
    except Exception as error:  # the receipt still lands, naming what the task record missed
        bookkeeping = f"{type(error).__name__}: {error}"
        print(f"delegate: task record not updated: {bookkeeping}", file=sys.stderr)
    result = next((r for r in reversed(workers._rows(stdout)) if r.get("type") == "result"), {})
    denials = result.get("permission_denials") or []
    feedback(task_id, [{"kind": "permission-denial", "tool": d.get("tool_name"),
                        "head": head(d.get("tool_input", {}).get("command"))} for d in denials]
             + ([] if outcome == "done" else [{"kind": f"worker-{outcome}"}]))
    report = parsed["report"] or {}
    write_json(run / "receipt.json", {
        "task_id": task_id, "dispatch_id": dispatch_id, "session_id": parsed["session_id"],
        "outcome": outcome, "exit_code": worker.returncode, "started_at": stamp(started),
        "finished_at": stamp(finished), "duration_s": round(time.time() - t0), "cwd": p["cwd"],
        "depth": p["depth"], "route": p["route"], "keep_awake": awake,
        "cost_usd": result.get("total_cost_usd"), "turns": result.get("num_turns"),
        "permission_denials": len(denials),
        "report": {k: report.get(k) for k in ("status", "summary", "commit", "tests", "need")},
        "record_status": tasks.load(root, task_id)["status"], "bookkeeping_error": bookkeeping,
        "stream": str(run / "stream.jsonl")})


def head(command):
    """Only the command's first word goes to the feedback spool, never its arguments."""
    words = (command or "").split()
    words = [w for w in words if "=" not in w.split("/")[0]]
    return os.path.basename(words[0]) if words else None


def feedback(task_id, items):
    if not items:
        return
    with open(tasks.state_dir() / "feedback.jsonl", "a") as fh:
        for item in items:
            fh.write(json.dumps({"at": stamp(now()), "task_id": task_id, **item}) + "\n")


def latest_run(task_id, dispatch_id=None):
    found = sorted((runs_root() / task_id).glob("*/supervisor.json"))
    if dispatch_id:
        found = [f for f in found if f.parent.name == dispatch_id]
    if not found:
        sys.exit(f"delegate: no run for {task_id}")
    return found[-1].parent


def wait(args):
    run = latest_run(args.task_id, args.dispatch)
    deadline = time.time() + min(args.timeout, 3600)
    while time.time() < deadline:
        if (run / "receipt.json").exists():
            receipt = json.loads((run / "receipt.json").read_text())
            print(json.dumps(receipt))
            sys.exit(0 if receipt["outcome"] == "done" else 1)
        if run_state(run) == "lost?":
            settle_lost(run)
            continue
        time.sleep(2)
    print(json.dumps({"task_id": args.task_id, "dispatch_id": run.name, "state": "live"}))
    sys.exit(REFUSED)


def settle_lost(run):
    """The supervisor died before writing a receipt: the run is lost unless its worker still runs."""
    sup = json.loads((run / "supervisor.json").read_text())
    if sup.get("worker_pid") and alive(sup["worker_pid"], "claude"):
        return "orphaned-running"
    write_json(run / "receipt.json", {"task_id": run.parent.name, "dispatch_id": run.name, "outcome": "lost",
                                      "finished_at": stamp(now()), "stream": str(run / "stream.jsonl")})
    feedback(run.parent.name, [{"kind": "worker-lost"}])
    return "lost"


def status(args):
    for run in runs():
        if args.task_id and run.parent.name != args.task_id:
            continue
        params = json.loads((run / "params.json").read_text())
        receipt = json.loads((run / "receipt.json").read_text()) if (run / "receipt.json").exists() else {}
        print(json.dumps({"task_id": run.parent.name, "dispatch_id": run.name, "state": run_state(run),
                          "started_at": json.loads((run / "supervisor.json").read_text())["started_at"],
                          "cwd": params["cwd"],
                          "depth": params["depth"], "cost_usd": receipt.get("cost_usd"),
                          "summary": (receipt.get("report") or {}).get("summary")}))


def reconcile(_args):
    for run in runs():
        if run_state(run) == "lost?":
            print(json.dumps({"task_id": run.parent.name, "dispatch_id": run.name, "settled": settle_lost(run)}))


def report(args):
    since = now() - timedelta(days=args.days)
    receipts = [json.loads(p.read_text()) for p in runs_root().glob("*/*/receipt.json")]
    receipts = [r for r in receipts if datetime.strptime(r["finished_at"], "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=timezone.utc) >= since]
    spool = tasks.state_dir() / "feedback.jsonl"
    items = [json.loads(line) for line in spool.read_text().splitlines()] if spool.exists() else []
    items = [i for i in items if datetime.strptime(i["at"], "%Y-%m-%dT%H:%M:%SZ")
             .replace(tzinfo=timezone.utc) >= since]
    outcomes, denials = {}, {}
    for r in receipts:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    for i in items:
        if i["kind"] == "permission-denial":
            key = f"{i['tool']}:{i['head']}"
            denials[key] = denials.get(key, 0) + 1
    durations = sorted(r["duration_s"] for r in receipts if r.get("duration_s") is not None)
    print(json.dumps({"days": args.days, "runs": len(receipts), "outcomes": outcomes,
                      "median_duration_s": durations[len(durations) // 2] if durations else None,
                      "cost_usd": round(sum(r.get("cost_usd") or 0 for r in receipts), 2),
                      "denials": dict(sorted(denials.items(), key=lambda kv: -kv[1]))}, indent=1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--prompt-file", required=True, help="the brief; '-' reads stdin")
    s.add_argument("--cwd", default=".")
    s.add_argument("--task-id")
    s.add_argument("--work-item")
    s.add_argument("--name")
    s.add_argument("--signal", action="append", default=[], choices=sorted(worker_execution.SIGNALS),
                   help="known complexity: selects the involved route")
    s.add_argument("--reason", default="delegated work")
    s.add_argument("--decision-ref")
    s.add_argument("--resume", action="store_true", help="continue the task's owned session")
    w = sub.add_parser("wait")
    w.add_argument("task_id")
    w.add_argument("--dispatch")
    w.add_argument("--timeout", type=int, default=540)
    st = sub.add_parser("status")
    st.add_argument("task_id", nargs="?")
    sub.add_parser("reconcile")
    r = sub.add_parser("report")
    r.add_argument("--days", type=int, default=7)
    sv = sub.add_parser("_supervise")
    sv.add_argument("run")
    args = parser.parse_args(argv)
    if args.cmd == "_supervise":
        return supervise(args.run)
    return {"start": start, "wait": wait, "status": status, "reconcile": reconcile, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()
