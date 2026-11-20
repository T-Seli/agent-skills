"""`issues-cli dispatch`: start the Owner-ready items of lane `next` as headless workers (conveyor.md § Dispatch).

Reads preflight limits from config, refuses an issue a live session still holds, keeps a local receipt around
`delegate.py start` so an uncertain start is held and never retried, and prints one heartbeat line.
The caller passes the issues_cli module as `cli`, so its Refused is the one main() catches however it was started."""
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from . import layout


def settings(cli):
    base = cli.belt()['dispatch']
    given = cli.machine_config().get('dispatch') or {}
    fixed = {'marker', 'heartbeat', 'note', 'receipt', 'refusal_exit', 'prompts'}
    unknown = [k for k in given if k not in base or k in fixed]
    if unknown:
        raise cli.Refused(f"workers.json dispatch sets {', '.join(unknown)}; the owner may set "
                          f"{', '.join(k for k in base if k not in fixed)}")
    return {**base, **given}


def state_path(cfg, repo, n):
    return Path(cfg['state_dir']).expanduser() / f"{re.sub(r'[^A-Za-z0-9._-]+', '-', repo)}-{n}.json"


def read_receipt(path):
    return json.loads(path.read_text()) if path.exists() else None


def write_receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, sort_keys=True) + '\n')
    tmp.replace(path)


def sizes_allowed(cli, cfg):
    return cfg['sizes_allowed'] or cli.lane_rule('in-progress')['sizes']


def investigate_limit(cli):
    m = re.search(r'Investigate (\d+)', cli.defaults().get('Lane limits', ''))
    if not m:
        raise cli.Refused('§ Defaults `Lane limits` names no Investigate number')
    return int(m[1])


def build_rules(cli):
    """(slots kept free for prio:now, most size M items in Build) from contracts.md § Defaults `Lane limits`."""
    line = cli.defaults().get('Lane limits', '')
    reserve, m_max = re.search(r'(\d+) kept free for `prio:now`', line), re.search(r'at most (\d+) size M', line)
    if not reserve:
        raise cli.Refused('§ Defaults `Lane limits` names no `prio:now` reserve (`<n> kept free for `prio:now``)')
    if not m_max:
        raise cli.Refused('§ Defaults `Lane limits` names no size M quota (`at most <n> size M`)')
    return int(reserve[1]), int(m_max[1])


def latest_marker(cli, cfg, comments, me):
    """The signed-in login's newest first-line marker (conveyor.json dispatch.marker), or None."""
    pattern = re.compile(cfg['marker']['pattern'])
    found = [m for c in comments if (c.get('author') or {}).get('login') == me
             and (m := pattern.match(c['body'].replace('\r\n', '\n').split('\n', 1)[0].strip()))]
    return found[-1] if found else None


def kind_of(cli, cfg, i):
    return 'investigate' if any(f'kind:{k}' in cli.label_names(i) for k in cfg['investigate_kinds']) else 'build'


def preflight(cli, by, repo, cfg):
    """(stop reason or None, rooms) from the lanes, disk and test slots. A stop holds back every start; rooms are the
    Build and Investigate slots left after the in-progress items and the started items still waiting for their claim."""
    from .disk_check import EXIT_STOP, check
    lim = cli.limits()
    claimed = [i for i in cli.counted(by['next']) if (r := read_receipt(state_path(cfg, repo, i['number']))) and r['status'] == 'verified']
    working = [*cli.counted(by['in-progress']), *claimed]
    inv = len([i for i in working if kind_of(cli, cfg, i) == 'investigate'])
    caps = {'build': cfg['build_cap_override'] or lim['Build'], 'investigate': investigate_limit(cli)}
    used = {'build': len(working) - inv, 'investigate': inv, 'M': len([i for i in working if 'size:M' in cli.label_names(i)])}
    stop = None
    reviewing = len(cli.counted(by['in-review']))
    if reviewing >= lim['Review']:
        stop = f"drain: Review is full ({reviewing} of {lim['Review']})"
    code, line = check(str(cli.project()[0]), cli.machine_config())
    if stop is None and code == EXIT_STOP:
        stop = line
    free, total, reserve = cli.test_slots()
    if stop is None and free - reserve < 1:
        stop = f'test slot: none free ({free} of {total}, {reserve} kept for release runs)'
    return stop, caps, used


def live_or_none(cli):
    try:
        return cli.live_sessions()
    except RuntimeError:
        return None


def hold_text(why, r, path):
    task = r.get('task_id', '?')
    return (f'{why} (task {task}); never retried automatically. Run `delegate.py status {task}`: if no run exists, '
            f'delete {path} and the next tick starts a fresh task; if one exists, let it finish or close it first')


def plan(cli, gh, repo, cfg):
    """(batch [(issue, kind)], skipped [(issue, reason)], held [(issue, reason)]), in priority order, read-only."""
    issues, by = cli.open_belt(gh, repo)
    me, reg, live = gh(['api', 'user', '--jq', '.login']).strip(), cli.registry(issues), live_or_none(cli)
    stop, caps, used = preflight(cli, by, repo, cfg)
    reserve, m_max = build_rules(cli)
    sizes, batch, skipped, held = sizes_allowed(cli, cfg), [], [], []
    for i in cli.pull_order(by['next']):
        n, kind = i['number'], kind_of(cli, cfg, i)
        f = cli.Facts(gh, repo, i)
        owned = any(re.search(cli.receipt('owner')['pattern'], line) for line in f.comments)
        size = next((x[5:] for x in cli.label_names(i) if x.startswith('size:')), None)
        path, r = state_path(cfg, repo, n), read_receipt(state_path(cfg, repo, n))
        mark = latest_marker(cli, cfg, i.get('comments', []), me)
        if cli.frees_slot(i):
            skipped.append((i, next(x for x in cli.belt()['park']['frees_slot'] if x in cli.label_names(i))))
        elif not owned:
            skipped.append((i, 'missing Owner:'))
        elif size not in sizes:
            skipped.append((i, f"size not allowed: {size or 'no size label'} (allowed {', '.join(sizes)})"))
        elif r and r['status'] == 'submission_pending':
            held.append((i, hold_text('delegate start outcome unknown', r, path)))
        elif r and r['status'] == 'verified' and live is not None and r.get('session_id') in live:
            skipped.append((i, 'started: waiting for the worker to claim'))
        elif r and r['status'] == 'verified':
            held.append((i, hold_text('started but no running worker shown and still in next', r, path)))
        elif mark and mark['state'] == 'active' and any(cli.unfinished(x) for x, _ in reg.get(mark['session'], [])):
            skipped.append((i, f"marker: active session {mark['session']} still in the registry"))
        elif stop:
            skipped.append((i, stop))
        elif used[kind] >= caps[kind]:
            skipped.append((i, f'cap: {kind.capitalize()} {used[kind]} of {caps[kind]}'))
        elif kind == 'build' and 'prio:now' not in cli.label_names(i) and used[kind] + reserve >= caps[kind]:
            skipped.append((i, f'cap: last Build slot kept for prio:now ({used[kind]} of {caps[kind]} used)'))
        elif kind == 'build' and size == 'M' and used['M'] >= m_max:
            skipped.append((i, f"cap: size M {used['M']} of {m_max}"))
        else:
            batch.append((i, kind))
            used[kind] += 1
            used['M'] += kind == 'build' and size == 'M'
    return batch, skipped, held


def run_delegate(argv, stdin, timeout):
    """(exit code, stdout, stderr) of one delegate.py call; the seam tests replace."""
    done = subprocess.run([sys.executable, str(layout.ROOT / 'skills' / 'agent-coordination' / 'scripts' / 'delegate.py'), *argv],
                          input=stdin, capture_output=True, text=True, timeout=timeout)
    return done.returncode, done.stdout, done.stderr


def refusal_reason(out, err):
    last = out.strip().splitlines()[-1:]
    try:
        return json.loads(last[0])['refused']
    except (IndexError, ValueError, KeyError, TypeError):
        return err.strip() or 'refused'


def new_task_id(repo, n):
    """One id per attempt: delegate refuses an id it has already used, so a retry never reuses one."""
    return re.sub(r'[^A-Za-z0-9._-]+', '-', f'conveyor-{repo}-{n}')[:70] + f'-{uuid.uuid4().hex[:8]}'


def contract(cli, repo, n, title, prompt, kind, task):
    """(task id, contract file value): a small fixed contract checked by agent_skills.task_contract; the worker's
    only outward actions are its own task branch and draft PR (build) or none (investigate)."""
    owner = 'conveyor-dispatch'
    goal = f'{kind.capitalize()} {repo}#{n}: {title}'
    gate = 'implement: done on the issue' if kind == 'build' else 'an answer, a plan or a card on the issue'
    out = dict(
        user_goal=goal, canonical_issue_ref=f'{repo}#{n}', canonical_owner=owner, deliverable_id=f'{kind}-{n}',
        revision=1, constraints=['no merge, release or deploy', 'work only on this issue and its Done when',
                                 'push only your own task branch and open a draft PR' if kind == 'build' else 'read-only: no edits, commits or pushes'],
        priority_source_ref='conveyor.json dispatch', acceptance_ref=f'{repo}#{n}',
        environment='local checkout', changed_criteria='the issue body or its Done when changes',
        next_action=f'{kind} the issue and record the result on it', source_ref=f'{repo}#{n}',
        requested_artifact='draft-pr' if kind == 'build' else 'answer', authority_ref='conveyor.json dispatch',
        artifact_ref=f'{repo}#{n}', gates=[gate])
    p = cli.packet(task_id=task, revision=1, owner=owner, scope=goal, baseline=f'{repo}#{n}',
                   exclusions=['merges', 'releases', 'deploys'], deliverables=[gate],
                   acceptance=[{'id': 'result', 'check': gate}], context_refs=[f'{repo}#{n}'],
                   source_hashes={'conveyor.json': hashlib.sha256(cli.layout.contract('conveyor.json').read_bytes()).hexdigest()},
                   package_hashes={'prompt': hashlib.sha256(prompt.encode()).hexdigest()},
                   stop_conditions=['the issue is closed or parked', 'a step beyond the plan is needed'],
                   escalation_conditions=['tests cannot run', 'the Done when cannot be met'])
    cli.validate_packet(p)
    return {'contract': out, 'acceptance_packet': p}


def start_one(cli, gh, repo, i, kind, cfg, log):
    """Start one item. Returns (outcome, text): started | waits | held. The receipt is `reserved` while the brief is
    built, `submission_pending` just before delegate is called, `verified` once it returns admission. Only a still
    `reserved` receipt or delegate's documented refusal exit proves the prompt was never sent, so only they release."""
    n, path = i['number'], state_path(cfg, repo, i['number'])
    task = (read_receipt(path) or {}).get('task_id') or new_task_id(repo, n)  # a crash after `reserved` resumes its id
    write_receipt(path, {'status': 'reserved', 'issue': n, 'repo': repo, 'task_id': task})
    try:
        prompt = f"{cli.brief(gh, repo, n, log)}\n\n{cfg['prompts'][kind]}\n"
        value = contract(cli, repo, n, i['title'], prompt, kind, task)
    except (cli.Refused, subprocess.CalledProcessError, OSError, ValueError, RuntimeError) as e:
        path.unlink()
        return 'waits', f'#{n} {getattr(e, "stderr", None) or e}'.strip()
    files = re.search(r'^Files: (.+)$', i.get('body', ''), re.M)
    write_receipt(path, {'status': 'submission_pending', 'issue': n, 'repo': repo, 'task_id': task})
    try:
        with tempfile.TemporaryDirectory() as folder:
            cfile = Path(folder) / 'contract.json'
            cfile.write_text(json.dumps(value))
            code, out, err = run_delegate(['start', '--prompt-file', '-', '--cwd', str(cli.project()[0]), '--name', f'conveyor-{n}',
                                           '--task-id', task, '--reason', f'conveyor {kind}', '--contract-file', str(cfile),
                                           *(['--files', ','.join(x.strip() for x in files[1].split(','))] if files else [])],
                                          prompt, cfg['delegate_timeout_seconds'])
    except (subprocess.SubprocessError, OSError) as e:
        return 'held', f'#{n} delegate start outcome unknown ({type(e).__name__}); receipt submission_pending'
    if code == cfg['refusal_exit']:
        path.unlink()
        return 'waits', f'#{n} {refusal_reason(out, err)}'
    try:
        if code:
            raise ValueError(f'delegate exited {code}')
        session = json.loads(out.strip().splitlines()[-1])['session_id']
    except (ValueError, KeyError, IndexError) as e:
        return 'held', f'#{n} delegate start outcome unknown ({e}); receipt submission_pending'
    write_receipt(path, {'status': 'verified', 'issue': n, 'repo': repo, 'task_id': task, 'session_id': session})
    return 'started', f'#{n} ({kind}) session {session}'


def run(cli, gh, repo, log=None, dry=False):
    cfg = settings(cli)
    if dry:
        batch, skipped, held = plan(cli, gh, repo, cfg)
        return '\n'.join(['Dry run: nothing started, no receipt or GitHub write.',
                          f"Would start: {', '.join('#%d (%s)' % (i['number'], k) for i, k in batch) or 'none'}",
                          *[f"Skipped: #{i['number']} {why}" for i, why in skipped],
                          *[f"start held: #{i['number']} {why}" for i, why in held]])
    folder = state_path(cfg, repo, 0).parent
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / 'lock', 'w') as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise cli.Refused('another dispatch is running (state_dir lock); nothing was started')
        batch, skipped, held = plan(cli, gh, repo, cfg)
        for i, _ in skipped:
            path = state_path(cfg, repo, i['number'])
            if (r := read_receipt(path)) and r['status'] == 'reserved':
                path.unlink()  # a crash before submission_pending: proven pre-send
        started, waits, holds = [], [], [f"start held: #{i['number']} {why}" for i, why in held]
        for i, kind in batch:
            outcome, text = start_one(cli, gh, repo, i, kind, cfg, log)
            {'started': started, 'waits': waits, 'held': holds}[outcome].append(
                text if outcome == 'started' else f'start {outcome}: {text}')
    heartbeat = f"Tick: {cli.stamp(cli.now())} · started {len(started)} · waiting {len(skipped) + len(waits)} · held {len(holds)}"
    if not re.match(cfg['heartbeat']['pattern'], heartbeat):
        raise cli.Refused(f'malformed heartbeat line: {heartbeat}')
    lines = [*[f'started: {x}' for x in started], *waits, *holds,
             *[f"skipped: #{i['number']} {why}" for i, why in skipped], heartbeat]
    if log:
        path, _ = cli.task_log(log)
        with path.open('a') as fh:
            fh.write('\n'.join(lines) + '\n')
    return '\n'.join(lines)
