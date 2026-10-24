#!/usr/bin/env python3
"""The one supported way for an agent to start a Claude worker (worker-execution.md § Delegate).

  start      create the task record, pin its route, launch a detached supervisor; prints one JSON line
  wait       block until the run's receipt exists (bounded); prints the receipt
  status     one JSON line per run: live, done, failed, timeout, lost, unknown (liveness can't be read here)
  reconcile  settle runs whose supervisor died (reboot, kill) as lost; never one of unknown liveness
  report     outcomes, cost and permission denials over recent days, for the skill steward

Ordinary wake launches are unverified. Critical dispatch borrows an acknowledged,
bounded foreground owner, never the legacy detached assertion. The supervisor runs `claude -p` with the
prompt on stdin, saves the stream, then records the execution, the task events and the receipt.
A worker that delegates again inherits AGENT_SKILLS_DEPTH + 1; the ledger refuses past `max_depth`,
past `max_live` running workers, and a second writer in the same directory.
`start --approved-log <log.md> --targets <a,b>` verifies the log's newest `Approved:` record and hands
the worker a release grant (AGENT_SKILLS_GRANT) for those targets of the cwd's repo under `release.repos`.
"""
import argparse
import json
import math
import os
import re
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
from agent_skills import worker_execution, keep_awake, producer_contract, task_checkpoint  # noqa: E402

CONFIG = Path(os.environ.get("AGENT_SKILLS_CONFIG", "~/.config/agent-skills/workers.json")).expanduser()
EXAMPLE = ROOT / "agent_skills" / "delegate_config.example.json"
GUARD = ROOT / "guard"
REFUSED = 3  # exit code: the ledger refused the launch; do the work yourself or wait
UNKNOWN = ("delegate: liveness unknown: signals or `ps` are denied here, so the run is never settled as lost; "
           "wait again, or run `delegate.py reconcile` where they work")
AWS_SECRETS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE")
DB_SECRETS = ("DATABASE_URL", "PGPASSWORD", "PGHOST", "PGUSER", "PGDATABASE", "PGPORT", "PGSERVICE")
APPROVED, APPROVED_AT = "Approved: ", "%Y-%m-%d %H:%MZ"
REMOTE_DENIES = ("Bash(ssh:", "Bash(scp:", "Bash(rsync")  # lifted only for a grant that names hosts


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
    """True for a running process whose command line still names `marker` (pid reuse), False once it
    is gone, None when this environment can't tell: a sandbox may deny signals and `ps`."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # the pid exists; we may not signal it
    try:
        shown = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    except OSError:
        return None
    return marker in shown.stdout if shown.returncode == 0 else None


def runs():
    """Every run directory, oldest first: runs/<task_id>/<dispatch_id>/."""
    return sorted((p.parent for p in runs_root().glob("*/*/supervisor.json")), key=lambda run: run.name)


def run_state(run):
    receipt = run / "receipt.json"
    if receipt.exists():
        return json.loads(receipt.read_text())["outcome"]
    sup = json.loads((run / "supervisor.json").read_text())
    return {True: "live", False: "lost?", None: "unknown"}[alive(sup["supervisor_pid"], "delegate.py")]


def refuse(reason):
    print(json.dumps({"refused": reason}))
    print(f"delegate: refused: {reason}", file=sys.stderr)
    sys.exit(REFUSED)


def guard_settings(run, remote=False):
    """Deny rules plus the fail-closed PreToolUse hook, with this install's absolute paths; `remote`
    lifts the ssh, scp and rsync denies for a grant whose targets name hosts."""
    settings = json.loads((GUARD / "worker-settings.json").read_text())
    if remote:
        settings["permissions"]["deny"] = [d for d in settings["permissions"]["deny"]
                                           if not d.startswith(REMOTE_DENIES)]
    hook = f"{shlex.quote(sys.executable)} {shlex.quote(str(GUARD / 'worker-guard.py'))}"
    settings["hooks"] = {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": hook, "timeout": 10}]}]}
    path = run / "guard.json"
    write_json(path, settings)
    return path


def env_changes(cfg, depth, task_id, grant=None, credentials=()):
    """Only the changes are stored (params.json); the supervisor applies them to its inherited env.
    A grant is never inherited; its targets' credentials restore AWS for this run, never databases."""
    changes = {"set": {"AGENT_SKILLS_DEPTH": str(depth + 1), "AGENT_SKILLS_TASK_ID": task_id},
               "unset": ["AGENT_SKILLS_GRANT"]}
    if grant:
        changes["set"]["AGENT_SKILLS_GRANT"] = json.dumps(grant, separators=(",", ":"))
    if not (cfg.get("aws") or "aws" in credentials):
        changes["unset"] += AWS_SECRETS
        changes["set"].update(AWS_SHARED_CREDENTIALS_FILE="/dev/null", AWS_CONFIG_FILE="/dev/null")
    if not cfg.get("databases"):
        changes["unset"] += DB_SECRETS
        changes["set"]["PGPASSFILE"] = "/dev/null"
    return changes


def approval(log, hours):
    """The newest `Approved:` record of the log (contracts.md § Consent): its targets, time and source."""
    if not Path(log).is_file():
        sys.exit(f"delegate: no such log {log}")
    lines = [line for line in Path(log).read_text().splitlines() if line.startswith(APPROVED)]
    if not lines:
        refuse(f"no {APPROVED.strip()} line in {log}")
    fields = [f.strip() for f in lines[-1][len(APPROVED):].split(" · ")]
    if len(fields) != 5:
        refuse(f"the newest approval has {len(fields)} fields, not 5 (steps · targets · time · source · quote)")
    steps, targets, at, source, quote = fields
    if "deploy" not in {step.strip() for step in steps.split(",")}:
        refuse(f"the newest approval covers {steps!r}, not deploy")
    try:
        moment = datetime.strptime(at, APPROVED_AT).replace(tzinfo=timezone.utc)
    except ValueError:
        moment = None
    if not moment or moment.strftime(APPROVED_AT) != at:
        refuse(f"approval time {at!r} is not YYYY-MM-DD HH:MMZ")
    if moment > now() + timedelta(minutes=5):
        refuse(f"approval time {at} is in the future")
    if moment + timedelta(hours=hours) < now():
        refuse(f"the approval of {at} is older than grant_hours {hours}")
    if not source:
        refuse("the approval names no source")
    if not (len(quote) > 2 and quote[0] == quote[-1] == '"' and quote[1:-1].strip()):
        refuse("the approval quotes no exact words")
    return {t.strip() for t in targets.split(",")} - {""}, moment, source


def origin_repo(cwd):
    """owner/name of the cwd's origin, from an https or ssh URL."""
    url = subprocess.run(["git", "-C", str(cwd), "remote", "get-url", "origin"],
                         capture_output=True, text=True).stdout.strip()
    found = re.fullmatch(r"(?:(?:https|ssh)://[^/]+/|[\w.-]+@[\w.-]+:)([\w.-]+/[\w.-]+?)(?:\.git)?", url)
    if not found:
        refuse(f"origin of {cwd} is not an owner/name URL: {url or 'none'}")
    return found.group(1)


def release_grant(cfg, log, targets, cwd, task_id):
    """The grant a verified approval gives these targets (worker-execution.md § Delegate), and the
    credentials it restores."""
    release = cfg.get("release", {})
    hours = release.get("grant_hours", 12)
    approved, moment, source = approval(log, hours)
    targets = list(dict.fromkeys(t.strip() for t in targets.split(",")))
    if not set(targets) <= approved:
        refuse(f"targets {sorted(set(targets) - approved)} are not in the approval {sorted(approved)}")
    repo = origin_repo(cwd)
    if repo not in release.get("repos", {}):
        refuse(f"no release.repos entry for {repo}")
    entry = release["repos"][repo]
    if not set(targets) <= set(entry["targets"]):
        refuse(f"targets {sorted(set(targets) - set(entry['targets']))} are not configured for {repo}")
    chosen = [entry["targets"][t] for t in targets]
    credentials = {c for t in chosen for c in t.get("credentials", [])}
    if credentials - {"aws"}:
        refuse(f"credentials {sorted(credentials - {'aws'})} of {repo}: a grant restores only aws")
    grant = {"repo": repo, "base": entry["base"], "targets": targets,
             "commands": list(dict.fromkeys(c for t in chosen for c in t.get("commands", []))),
             "hosts": list(dict.fromkeys(h for t in chosen for h in t.get("hosts", []))),
             "expires": (moment + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%MZ"),
             "task_id": task_id, "source": source}
    return grant, credentials


def source_pin():
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return f"{ROOT}@{head or 'snapshot'}"


class ProtectionHold(ValueError):
    pass


def critical_spec(args, task_id, dispatch_id, pin):
    if not args.critical_protection_receipt:
        return None
    try:
        receipt = keep_awake.status(args.critical_protection_receipt)
        end = keep_awake.utc(args.critical_until_utc)
        if (receipt.get('kind') != 'owned-keep-awake' or
                receipt['assessment']['state'] != 'verified-now' or
                receipt['approval_ref'] != args.critical_authority_ref or
                type(receipt.get('check_seconds')) is not int or not 1 <= receipt['check_seconds'] <= 60 or
                not now() < end <= keep_awake.utc(receipt['authorized_until_utc'])):
            raise ValueError('current owned grant, exact authority and bounded UTC end required')
        return {'receipt': str(keep_awake._path(args.critical_protection_receipt)),
                'task_id': task_id, 'dispatch_id': dispatch_id, 'source_pin': pin,
                'consumer': f'delegate:{task_id}:{dispatch_id}',
                'until_utc': keep_awake.stamp(end),
                'binding': {k: receipt[k] for k in ('kind', 'task_id', 'owner', 'generation', 'host_id',
                            'approval_ref', 'foreground_ref', 'supervisor_identity', 'check_seconds', 'authorized_until_utc')}}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        refuse(f'critical protection held: {error}')


class CriticalProtection:
    """A consumer only: no acquisition, owner transfer, PID signal or cleanup."""
    def __init__(self, params, run):
        self.params, self.run, self.spec = params, Path(run), params['critical']
        self.wait_seconds = max(10, self.spec['binding']['check_seconds'] + 5)
        self.ack_end = self.pending_end = self.pending_at = self.failure = None
        self.ack_grant = self.pending_grant = None
        self.ack_read_at = self.pending_requested_at = None
        path = self.run / 'protection.json'
        if path.exists():
            prior = json.loads(path.read_text())
            self.ack_end = prior.get('acknowledged_until_utc')
            self.ack_grant = prior.get('acknowledged_grant')
            self.ack_read_at = prior.get('acknowledged_at_utc')
            self.failure = prior.get('failure')

    def read(self):
        s = self.spec
        if ((s['task_id'], s['dispatch_id'], s['source_pin']) !=
                (self.params['task_id'], self.params['dispatch_id'], source_pin())):
            raise ProtectionHold('delegate-source-or-dispatch-mismatch')
        receipt = keep_awake.status(s['receipt'])
        if any(receipt.get(k) != value for k, value in s['binding'].items()):
            raise ProtectionHold('owner-contract-mismatch')
        return receipt

    def acknowledged(self, receipt, end, *, after=None):
        rows = [c for c in receipt.get('consumers', []) if end and
                c.get('consumer') == self.spec['consumer'] and
                c.get('consumer_task_id') == self.spec['task_id'] and
                c.get('generation') == self.spec['binding']['generation'] and
                c.get('until_utc') == end and c.get('readback_at_utc') and
                0 <= (now() - keep_awake.utc(c['readback_at_utc'])).total_seconds() <= 120 and
                (after is None or keep_awake.utc(c['readback_at_utc']) >= keep_awake.utc(after))]
        return max(rows, key=lambda c: keep_awake.utc(c['readback_at_utc'])) if rows else None

    def view(self, receipt=None):
        s = self.spec
        value = {'state': 'unknown', 'reason': 'probe-unavailable', 'gate': 'HOLD',
                 'task_id': s['task_id'], 'dispatch_id': s['dispatch_id'],
                 'source_pin': s['source_pin'], 'receipt_ref': s['receipt'],
                 'binding': s['binding'], 'consumer': s['consumer'],
                 'requested_until_utc': s['until_utc'],
                 'acknowledged_until_utc': self.ack_end, 'pending_until_utc': self.pending_end,
                 'acknowledged_grant': self.ack_grant, 'acknowledged_at_utc': self.ack_read_at}
        try:
            receipt = receipt if receipt is not None else self.read()
            value['observation'] = receipt.get('observation')
            check = keep_awake.assess(receipt, now=keep_awake.stamp(now()),
                                     owner=s['consumer'], task_id=s['task_id'])
            value.update(state=check['state'], reason=check['reason'])
            if now() >= keep_awake.utc(s['until_utc']):
                value.update(state='expired', reason='critical-window-ended')
            elif not self.ack_read_at or not self.acknowledged(receipt, self.ack_end, after=self.ack_read_at):
                value.update(state='unknown', reason='exact-consumer-acknowledgment-missing')
            elif now() >= keep_awake.utc(self.ack_end):
                value.update(state='expired', reason='consumer-window-ended')
            if value['state'] == 'verified-now' and not self.failure:
                value['gate'] = 'open'
        except ProtectionHold as error:
            value['reason'] = str(error)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            pass
        if self.failure:
            value['failure'] = self.failure
        return value

    def save(self, value):
        write_json(self.run / 'protection.json', value)
        return value

    def request(self, receipt, *, refresh_ack=False):
        obs = receipt['observation']
        grant = {k: receipt[k] for k in ('pid', 'assertion_ref', 'expires_at_utc')}
        end = min(keep_awake.utc(self.spec['until_utc']), keep_awake.utc(receipt['expires_at_utc']),
                  keep_awake.utc(receipt['authorized_until_utc']),
                  keep_awake.utc(obs['observed_at_utc']) + timedelta(seconds=obs['assertion']['remaining_seconds']))
        if end <= now():
            raise ProtectionHold('current-grant-ended')
        if self.ack_end and (grant == self.ack_grant or end <= keep_awake.utc(self.ack_end)):
            if not refresh_ack:
                return  # no observed newer grant, so no extension claim
            end = min(end, keep_awake.utc(self.ack_end))  # freshness never extends this grant
        target = keep_awake.stamp(end)
        admission = keep_awake.reuse(self.spec['receipt'], consumer=self.spec['consumer'],
                                    task_id=self.spec['task_id'], until_utc=target)
        queued = admission['request']
        expected = {k: self.spec['binding'][k] for k in ('owner', 'generation', 'host_id', 'task_id')}
        expected.update(operation='retain-consumer', consumer=self.spec['consumer'],
                        consumer_task_id=self.spec['task_id'], until_utc=target)
        if (admission['state'] != 'queued-not-executed' or admission['receipt'] != self.spec['receipt'] or
                any(queued.get(k) != value for k, value in expected.items()) or
                not 0 <= (now() - keep_awake.utc(queued['requested_at_utc'])).total_seconds() <= 120):
            raise ProtectionHold('consumer-admission-mismatch; reconcile pending request')
        self.pending_end, self.pending_at = target, time.monotonic()
        self.pending_grant = grant
        self.pending_requested_at = queued['requested_at_utc']

    def prepare(self):
        deadline = time.monotonic() + self.wait_seconds
        try:
            receipt = self.read()
            if receipt['assessment']['state'] != 'verified-now':
                raise ProtectionHold('owner-not-verified')
            self.request(receipt)
            while time.monotonic() < deadline:
                receipt = self.read()
                acknowledged = self.acknowledged(receipt, self.pending_end, after=self.pending_requested_at)
                if acknowledged:
                    self.ack_end, self.pending_end = self.pending_end, None
                    self.ack_grant, self.pending_grant = self.pending_grant, None
                    self.ack_read_at = acknowledged['readback_at_utc']
                    value = self.save(self.view(receipt))
                    if value['gate'] == 'open':
                        return value
                    raise ProtectionHold(value['reason'])
                if (receipt['assessment']['state'] != 'verified-now' or
                        now() >= keep_awake.utc(self.spec['until_utc'])):
                    raise ProtectionHold('owner-or-critical-window-ended')
                self.save(self.view(receipt))
                time.sleep(.1)
            raise ProtectionHold('consumer-acknowledgment-timeout; reconcile pending request')
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self.failure = {'reason': str(error), 'observed_at_utc': keep_awake.stamp(now())}
            self.save(self.view())
            raise ProtectionHold(str(error))

    def tick(self, *, refresh=True):
        try:
            receipt = self.read()
            acknowledged = self.acknowledged(receipt, self.pending_end, after=self.pending_requested_at)
            if acknowledged:
                self.ack_end, self.pending_end = self.pending_end, None
                self.ack_grant, self.pending_grant = self.pending_grant, None
                self.ack_read_at = acknowledged['readback_at_utc']
            value = self.view(receipt)
            if value['gate'] == 'open' and refresh and not self.failure:
                if self.pending_end:
                    if time.monotonic() - self.pending_at >= self.wait_seconds:
                        raise ProtectionHold('extension-acknowledgment-timeout; reconcile pending request')
                else:
                    refresh_ack = (now() - keep_awake.utc(self.ack_read_at)).total_seconds() >= 30
                    grant = {k: receipt[k] for k in ('pid', 'assertion_ref', 'expires_at_utc')}
                    if (refresh_ack or grant != self.ack_grant or
                            (keep_awake.utc(self.ack_end) - now()).total_seconds() <= 5):
                        self.request(receipt, refresh_ack=refresh_ack)
            elif value['gate'] != 'open' and not self.failure:
                raise ProtectionHold(value['reason'])
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            if not self.failure:
                self.failure = {'reason': str(error), 'observed_at_utc': keep_awake.stamp(now())}
        value = self.view()
        if value['gate'] != 'open' and not self.failure:
            self.failure = {'reason': value['reason'], 'observed_at_utc': keep_awake.stamp(now())}
            value['failure'] = self.failure
        return self.save(value)


def current_protection(run):
    params = json.loads((Path(run) / 'params.json').read_text())
    return CriticalProtection(params, run).view() if params.get('critical') else None


def start(args):
    cfg = config()
    depth = int(os.environ.get("AGENT_SKILLS_DEPTH", "0"))
    if depth >= cfg["max_depth"]:
        refuse(f"depth {depth} reached max_depth {cfg['max_depth']}: do this yourself or use a subagent")
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        sys.exit(f"delegate: no such directory {cwd}")
    live = [r for r in runs() if run_state(r) in ("live", "unknown")]  # unknown may still be writing
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
    if args.approved_log and depth:
        refuse("a release grant is issued only from a top-level session, never from a worker")
    grant, credentials = (release_grant(cfg, args.approved_log, args.targets, cwd, task_id)
                          if args.approved_log else (None, set()))
    dispatch_id = f"d{time.time_ns() // 1_000_000}"
    pin = source_pin()
    critical = critical_spec(args, task_id, dispatch_id, pin)
    parent = os.environ.get("AGENT_SKILLS_TASK_ID", "top-level")
    decision = args.decision_ref or f"delegated-by:{parent}"
    contract_path = getattr(args, 'contract_file', None)
    legacy = getattr(args, 'legacy_unbound', False)
    contract_value = json.loads(Path(contract_path).read_text()) if contract_path else None
    def require_budget():
        cost = route.get('max_cost_usd')
        if type(cost) not in (int, float) or not math.isfinite(cost) or cost <= 0:
            refuse('contract-bound launch requires an explicit positive cost budget in existing route policy')
    if contract_value is not None:
        require_budget()
    if contract_value is None and not args.resume and not legacy:
        refuse('new work requires --contract-file; --legacy-unbound explicitly preserves old caller semantics')
    if args.resume:
        session_id = tasks.load(root, task_id)["worker"]["session_id"]
        if not session_id:
            sys.exit(f"delegate: task {task_id} has no owned session to resume")
        def resumed(r):
            if contract_value is not None:
                r = producer_contract.bind(tasks, r, contract_value)
            if not r['coordination'].get('active_deliverable') and not legacy:
                raise ValueError('legacy resume requires --legacy-unbound or a current contract')
            if r['coordination'].get('active_deliverable'):
                require_budget()
                producer_contract.require_execution_authority(tasks, r)
            return tasks.begin_dispatch(worker_execution.bind_route(
                r, route, source_pin=pin, decision_ref=decision, change_ref=decision), dispatch_id, resume=True)
        record = tasks.update(root, task_id, resumed)
    else:
        session_id = str(uuid.uuid4())
        record = tasks.new_task(task_id, args.work_item or task_id, worker_kind="claude", owner="assistant",
                                repo=str(cwd), worktree=str(cwd), source_thread=parent)
        if contract_value is not None:
            record = producer_contract.bind(tasks, record, contract_value)
        else:
            record['contract_mode'] = 'legacy-unbound'
        record = worker_execution.bind_route(record, route, source_pin=pin, decision_ref=decision)
        tasks.create(root, tasks.begin_dispatch(record, dispatch_id, resume=False))

    bound = bool(record['coordination'].get('active_deliverable'))
    if bound:
        def checkpoint(r):
            if not r['coordination']['active_deliverable'].get('checkpoint'):
                r = task_checkpoint.record_checkpoint(r, critical=bool(critical), rank=1,
                    blocker=None, next_action=r['coordination']['active_deliverable']['next_action'],
                    next_check_at_utc=stamp(now() + timedelta(minutes=20)),
                    observed_at_utc=stamp(now()), receipt_ref=f'delegate:{task_id}:{dispatch_id}:checkpoint')
            return task_checkpoint.stage_checkpoint_intents(r, now=stamp(now()))
        record = tasks.update(root, task_id, checkpoint)
        prompt = producer_contract.execution_prompt(tasks, record, prompt)

    run = runs_root() / task_id / dispatch_id
    run.mkdir(parents=True, mode=0o700)
    (run / "prompt.md").write_text(prompt)
    os.chmod(run / "prompt.md", 0o600)
    settings = guard_settings(run, remote=bool(grant and grant["hosts"]))
    claude = workers.Claude(route["model"], route["effort"], route.get("max_cost_usd"),
                            settings=settings, max_turns=route.get("max_turns"), name=args.name or task_id)
    write_json(run / "params.json", {
        "task_id": task_id, "dispatch_id": dispatch_id, "cwd": str(cwd), "depth": depth + 1,
        "argv": claude.command(session_id=session_id, resume=args.resume),
        "timeout_seconds": route["timeout_seconds"], "route": {k: route[k] for k in ("tier", "model", "effort")},
        "critical": critical, "session_id": session_id,
        "contract_binding": tasks.current_task_binding(record) if bound else None,
        "env": env_changes(cfg, depth, task_id, grant, credentials),
        "grant": grant and {k: grant[k] for k in ("repo", "base", "targets", "expires", "source")}})
    log = open(run / "supervisor.log", "w")
    sup = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_supervise", str(run)],
                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    write_json(run / "supervisor.json", {"supervisor_pid": sup.pid, "worker_pid": None, "started_at": stamp(now())})
    print(json.dumps({"task_id": task_id, "dispatch_id": dispatch_id, "session_id": session_id,
                      "run_dir": str(run), "depth": depth + 1, "route": route["tier"],
                      "state": "admitted-awaiting-protection" if critical else "admitted"}))


def contract_readback(run, params, env):
    """No-tools phase in the same owned session; missing proof holds execution."""
    record = tasks.load(tasks.state_dir(), params['task_id'])
    producer_contract.require_execution_authority(tasks, record)
    if tasks.current_task_binding(record) != params['contract_binding']:
        raise ValueError('contract changed after admission')
    argv = list(params['argv'])
    argv[argv.index('--json-schema') + 1] = json.dumps(producer_contract.acknowledgment_schema(tasks, record))
    budget_index = argv.index('--max-budget-usd') + 1
    total_budget = float(argv[budget_index])
    ack_budget = min(.50, total_budget / 2)
    argv[budget_index] = str(ack_budget)
    argv += ['--tools', '', '--disable-slash-commands']
    payload = {**producer_contract.envelope(tasks, record),
               'acknowledgment': producer_contract.acknowledgment_binding(tasks, record)}
    prompt = ('Read this task contract. Do no work. Return only the acknowledgment object, '
              'acknowledging its original decision source and acceptance criteria.\n' +
              json.dumps(payload, sort_keys=True))
    started = time.monotonic()
    sup_path = run / 'supervisor.json'
    sup = json.loads(sup_path.read_text())
    write_json(sup_path, {**sup, 'phase':'readback-uncertain', 'worker_pid':None})
    def launched(pid):
        write_json(sup_path, {**sup, 'phase':'readback-running', 'worker_pid':pid})
    # run() bounds this owned process and retains uncertainty on interruption/timeout.
    old_env = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(env)
        result = workers.run(argv, cwd=params['cwd'], timeout=min(120, params['timeout_seconds']),
                             input=prompt, on_started=launched)
    finally:
        os.environ.clear()
        os.environ.update(old_env)
    (run / 'contract-readback.jsonl').write_text(result.stdout)
    parsed = workers.Claude().parse(result.stdout)
    receipt = {'state': result.state, 'exit_code': result.returncode,
               'session_id': parsed['session_id'], 'binding': parsed['report'],
               'execution': parsed.get('execution'), 'requested_tools': [],
               'remaining_seconds': params['timeout_seconds'] - (time.monotonic() - started)}
    receipt['cost_usd'] = (parsed.get('execution') or {}).get('reported_cost_usd')
    tool_calls = [part.get('name') for row in workers._rows(result.stdout)
                  for part in (row.get('message') or {}).get('content', [])
                  if isinstance(part, dict) and part.get('type') == 'tool_use']
    receipt['observed_tool_calls'] = tool_calls
    write_json(run / 'contract-readback-receipt.json', receipt)
    write_json(sup_path, {**sup, 'phase':'readback-complete', 'worker_pid':None})
    if result.state in ('done', 'failed') and parsed['session_id'] == params['session_id']:
        tasks.update(tasks.state_dir(), params['task_id'], producer_contract.retain_seed_session,
            session_id=parsed['session_id'], expected_session_id=params['session_id'],
            receipt_ref=str(run / 'contract-readback-receipt.json'))
    if result.state != 'done' or parsed['error'] or any(name != 'StructuredOutput' for name in tool_calls):
        raise ValueError('contract readback failed or uncertain; execution held')
    tasks.update(tasks.state_dir(), params['task_id'], producer_contract.consume, tasks=tasks,
                 acknowledgment=parsed['report'], session_id=parsed['session_id'],
                 expected_session_id=params['session_id'], receipt_ref=str(run / 'contract-readback-receipt.json'))
    # Resuming the exact seeded session is execution, not a second worker owner.
    execution_argv = list(params['argv'])
    if '--session-id' in execution_argv:
        execution_argv[execution_argv.index('--session-id')] = '--resume'
    execution_argv[execution_argv.index('--max-budget-usd') + 1] = str(total_budget - ack_budget)
    if receipt['remaining_seconds'] <= 0:
        raise ValueError('execution deadline expired during readback')
    return execution_argv, receipt['remaining_seconds']


def supervise(run):
    run = Path(run)
    p = json.loads((run / "params.json").read_text())
    root, task_id, dispatch_id = tasks.state_dir(), p["task_id"], p["dispatch_id"]
    started, t0 = now(), time.time()
    env = {k: v for k, v in os.environ.items() if k not in p["env"]["unset"]}
    env.update(p["env"]["set"])
    protection = CriticalProtection(p, run) if p.get('critical') else None
    if protection:
        try:
            protection.prepare()
        except ProtectionHold:
            tasks.update(root, task_id, tasks.settle_dispatch, dispatch_id, 'not-sent')
            write_json(run / 'receipt.json', {'task_id': task_id, 'dispatch_id': dispatch_id,
                       'outcome': 'protection-held', 'finished_at': stamp(now()),
                       'keep_awake': protection.view(), 'worker_started': False})
            return
    argv, timeout_seconds = p['argv'], p['timeout_seconds']
    if p.get('contract_binding'):
        try:
            argv, timeout_seconds = contract_readback(run, p, env)
        except (ValueError, OSError, KeyError, TypeError) as error:
            tasks.update(root, task_id, tasks.settle_dispatch, dispatch_id, 'not-sent')
            ack_path = run / 'contract-readback-receipt.json'
            ack = json.loads(ack_path.read_text()) if ack_path.exists() else {}
            write_json(run / 'receipt.json', {'task_id': task_id, 'dispatch_id': dispatch_id,
                       'outcome': 'contract-held', 'error': str(error), 'worker_started': False,
                       'readback_phase_started': True, 'readback_session_id': ack.get('session_id'),
                       'contract_readback': str(ack_path), 'cost_usd': ack.get('cost_usd'),
                       'finished_at': stamp(now())})
            return
    try:
        with open(run / "prompt.md") as prompt, open(run / "stream.jsonl", "w") as out, \
                open(run / "stderr.log", "w") as err:
            if p.get('contract_binding'):
                current = tasks.load(root, task_id)
                worker_execution.require_unfrozen(current)
                producer_contract.require_execution_authority(tasks, current)
                if (tasks.current_task_binding(current) != p['contract_binding'] or
                        not current['coordination']['active_deliverable'].get('readback_ref') or
                        json.loads((run / 'contract-readback-receipt.json').read_text())['binding'] !=
                        producer_contract.acknowledgment_binding(tasks, current)):
                    raise ValueError('contract changed before execution')
            if protection and protection.tick(refresh=False)['gate'] != 'open':
                raise ProtectionHold('protection lost before worker launch')
            if p.get('contract_binding'):
                sup_path = run / 'supervisor.json'
                sup = json.loads(sup_path.read_text())
                write_json(sup_path, {**sup, 'phase':'execution-uncertain', 'worker_pid':None})
            worker = subprocess.Popen(argv, cwd=p["cwd"], stdin=prompt, stdout=out, stderr=err,
                                      env=env, start_new_session=True)
    except (FileNotFoundError, ProtectionHold, ValueError) as error:
        tasks.update(root, task_id, tasks.settle_dispatch, dispatch_id, "not-sent")
        feedback(task_id, [{"kind": "worker-unavailable"}])
        write_json(run / "receipt.json", {"task_id": task_id, "dispatch_id": dispatch_id,
                                          "outcome": ("protection-held" if isinstance(error, ProtectionHold) else
                                                      "contract-held" if isinstance(error, ValueError) else "unavailable"),
                                          "keep_awake": protection.view() if protection else 'not-started',
                                          "error": str(error), "finished_at": stamp(now())})
        return
    sup = json.loads((run / "supervisor.json").read_text())
    write_json(run / "supervisor.json", {**sup, "phase":"execution-running", "worker_pid": worker.pid})
    # The session id was fixed before launch, so a started process settles the dispatch.
    tasks.update(root, task_id, tasks.settle_dispatch, dispatch_id, "sent")
    if p.get('contract_binding'):
        tasks.receive(root, {'id': f'{dispatch_id}:dispatched', 'task': task_id,
            'ts': t0, 'source': 'adapter', 'kind': 'dispatched',
            'data': {'session_id': p['session_id']}})
    awake = "not-applicable"
    if protection:
        awake = protection.view()
    elif sys.platform == "darwin":
        subprocess.Popen(["caffeinate", "-i", "-w", str(worker.pid)], start_new_session=True)
        awake = "launched-unverified"
    outcome = "done"
    try:
        deadline = time.monotonic() + timeout_seconds
        while protection and worker.poll() is None:
            protection.tick()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(p['argv'], p['timeout_seconds'])
            try:
                worker.wait(timeout=min(1, remaining))
            except subprocess.TimeoutExpired:
                continue
        if not protection:
            worker.wait(timeout=timeout_seconds)
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
    if protection:
        awake = protection.tick(refresh=False)
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
        if p.get('contract_binding') and not tasks.load(root, task_id)['worker']['last_execution']['result_received']:
            raise ValueError('contract result held: execution/session/route evidence unqualified')
        for event in workers.events(task_id, dispatch_id, parsed, t0, time.time()):
            tasks.receive(root, event)
        if p.get('contract_binding') and (parsed.get('report') or {}).get('status') in ('answered', 'ready'):
            tasks.update(root, task_id, producer_contract.record_reported_result, tasks=tasks,
                dispatch_id=dispatch_id, report=parsed['report'], receipt_ref=f'{dispatch_id}:reported-result')
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
        "permission_denials": len(denials), "grant": p["grant"],
        "report": {k: report.get(k) for k in ("status", "summary", "commit", "tests", "need")},
        "record_status": tasks.load(root, task_id)["status"], "bookkeeping_error": bookkeeping,
        "stream": str(run / "stream.jsonl")})
    if p.get('contract_binding'):
        readback_receipt = json.loads((run / 'contract-readback-receipt.json').read_text())
        receipt_path = run / 'receipt.json'
        value = json.loads(receipt_path.read_text())
        value['contract_readback'] = str(run / 'contract-readback-receipt.json')
        value['cost_usd'] = ((value['cost_usd'] or 0) + (readback_receipt.get('cost_usd') or 0))
        write_json(receipt_path, value)
    if p.get('contract_binding'):
        tasks.update(root, task_id, task_checkpoint.stage_checkpoint_intents, now=stamp(now()))


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
    bound = bool(json.loads((run / 'params.json').read_text()).get('contract_binding'))
    deadline = time.time() + min(args.timeout, 3600)
    unknown = False
    while time.time() < deadline:
        if bound:
            tasks.update(tasks.state_dir(), args.task_id, task_checkpoint.stage_checkpoint_intents, now=stamp(now()))
        if (run / "receipt.json").exists():
            receipt = json.loads((run / "receipt.json").read_text())
            current = current_protection(run)
            print(json.dumps({**receipt, **({'keep_awake_current': current} if current else {})}))
            sys.exit(0 if receipt["outcome"] == "done" and (not current or current['gate'] == 'open') else 1)
        state = run_state(run)
        if state == "lost?":
            state = settle_lost(run)
            if state == "lost":
                continue
        unknown = state in ("unknown", "liveness-unknown")
        time.sleep(2)
    print(json.dumps({"task_id": args.task_id, "dispatch_id": run.name,
                      "state": "unknown" if unknown else "live", 'keep_awake_current': current_protection(run)}))
    if unknown:
        print(UNKNOWN, file=sys.stderr)
    sys.exit(REFUSED)


def settle_lost(run):
    """The supervisor died before writing a receipt: the run is lost unless its worker still runs or
    this environment can't tell."""
    sup = json.loads((run / "supervisor.json").read_text())
    if sup.get('phase') in ('readback-uncertain', 'execution-uncertain') and not sup.get('worker_pid'):
        return 'liveness-unknown'  # launch window unknown; never invent non-execution
    worker = alive(sup["worker_pid"], "claude") if sup.get("worker_pid") else False
    if worker is None:
        return "liveness-unknown"
    if worker:
        return "orphaned-running"
    write_json(run / "receipt.json", {"task_id": run.parent.name, "dispatch_id": run.name, "outcome": "lost",
                                      "keep_awake": current_protection(run),
                                      "finished_at": stamp(now()), "stream": str(run / "stream.jsonl")})
    feedback(run.parent.name, [{"kind": "worker-lost"}])
    return "lost"


def status(args):
    for run in runs():
        if args.task_id and run.parent.name != args.task_id:
            continue
        params = json.loads((run / "params.json").read_text())
        if params.get('contract_binding'):
            tasks.update(tasks.state_dir(), run.parent.name, task_checkpoint.stage_checkpoint_intents, now=stamp(now()))
        receipt = json.loads((run / "receipt.json").read_text()) if (run / "receipt.json").exists() else {}
        print(json.dumps({"task_id": run.parent.name, "dispatch_id": run.name, "state": run_state(run),
                          "started_at": json.loads((run / "supervisor.json").read_text())["started_at"],
                          "cwd": params["cwd"],
                          "depth": params["depth"], "cost_usd": receipt.get("cost_usd"),
                          'keep_awake_current': current_protection(run),
                          "summary": (receipt.get("report") or {}).get("summary")}))


def readback(args):
    """The parent explicitly consumes the matching result; acceptance stays separate."""
    run = latest_run(args.task_id, args.dispatch)
    receipt = json.loads((run / 'receipt.json').read_text())
    binding = json.loads(Path(args.binding_file).read_text())
    record = tasks.load(tasks.state_dir(), args.task_id)
    active = record['coordination'].get('active_deliverable') or {}
    if (receipt.get('outcome') != 'done' or receipt.get('bookkeeping_error') or
            not active.get('result_receipt_ref', '').startswith(run.name + ':') or
            (record.get('worker') or {}).get('session_id') != receipt.get('session_id')):
        raise ValueError('matching completed worker result required')
    def consume(r):
        result = r['coordination']['active_deliverable'].get('reported_result') or {}
        if result.get('dispatch_id') != run.name:
            raise ValueError('current reported artifact required')
        r = worker_execution.consume_result(r, run.name, stdout_sha256=result['stdout_sha256'],
                                            receipt_ref=args.read_receipt)
        return tasks.reconcile_parent_readback(r, binding=binding,
            result_receipt_ref=active['result_receipt_ref'], decision_source_ref=binding.get('decision_source_ref'),
            read_receipt_ref=args.read_receipt, answer_ref=args.answer_ref)
    record = tasks.update(tasks.state_dir(), args.task_id, consume)
    print(json.dumps({'task_id':args.task_id, 'binding':tasks.current_task_binding(record),
        'parent_readback':record['coordination']['active_deliverable']['parent_readback'],
        'acceptance_state':record['coordination']['acceptance_state']}))


def reconcile(_args):
    unknown = 0
    for run in runs():
        state = run_state(run)
        settled = settle_lost(run) if state == "lost?" else "liveness-unknown" if state == "unknown" else None
        if settled:
            unknown += settled == "liveness-unknown"
            print(json.dumps({"task_id": run.parent.name, "dispatch_id": run.name, "settled": settled,
                              'keep_awake_current': current_protection(run)}))
    if unknown:
        print(f"{UNKNOWN} ({unknown} run(s) left unsettled)", file=sys.stderr)
        sys.exit(1)


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
    s = sub.add_parser("start", allow_abbrev=False)  # no "--approved" shorthand slipping past the guard
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
    s.add_argument('--contract-file', help='JSON with contract kwargs and pinned acceptance_packet')
    s.add_argument('--legacy-unbound', action='store_true', help='explicit compatibility mode; no enforced contract claim')
    s.add_argument("--approved-log", help="the task's log.md: its newest Approved: line grants a release")
    s.add_argument("--targets", help="comma-separated release targets, each in the approval and configured")
    s.add_argument('--critical-protection-receipt', help='existing retained foreground owner receipt')
    s.add_argument('--critical-until-utc', help='bounded critical consumer end in explicit UTC')
    s.add_argument('--critical-authority-ref', help='exact original approval_ref of that owned grant')
    w = sub.add_parser("wait")
    w.add_argument("task_id")
    w.add_argument("--dispatch")
    w.add_argument("--timeout", type=int, default=540)
    st = sub.add_parser("status")
    st.add_argument("task_id", nargs="?")
    rd = sub.add_parser('readback')
    rd.add_argument('task_id')
    rd.add_argument('--dispatch')
    rd.add_argument('--binding-file', required=True)
    rd.add_argument('--read-receipt', required=True)
    rd.add_argument('--answer-ref', required=True)
    sub.add_parser("reconcile")
    r = sub.add_parser("report")
    r.add_argument("--days", type=int, default=7)
    sv = sub.add_parser("_supervise")
    sv.add_argument("run")
    args = parser.parse_args(argv)
    if args.cmd == "start" and bool(args.approved_log) != bool(args.targets):
        parser.error("--approved-log and --targets go together")
    if args.cmd == 'start':
        if args.contract_file and args.legacy_unbound:
            parser.error('--contract-file and --legacy-unbound are mutually exclusive')
        critical = [args.critical_protection_receipt, args.critical_until_utc, args.critical_authority_ref]
        if any(x is not None for x in critical) and not all(x and x.strip() for x in critical):
            parser.error('all three --critical-* inputs go together and must be nonempty')
    if args.cmd == "_supervise":
        return supervise(args.run)
    return {"start": start, "wait": wait, "status": status, "readback": readback,
            "reconcile": reconcile, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()
