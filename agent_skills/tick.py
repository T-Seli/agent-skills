"""`issues-cli belt-tick`: the belt's one timer command (conveyor.md § Flow, conveyor.json `tick`).

Runs the sweep, lists the inbox for the sort pass, reports `Pull next:`, then dispatches, and ends with one heartbeat.
A failing step is reported and the independent steps still run; `pull` reads the sweep's board, so it is skipped when
the sweep failed. The caller passes the issues_cli module as `cli`, so its Refused is the one main() catches."""
import re


def attempt(cli, name, fn, failed):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - a step's failure, whatever it is, must not end the tick
        failed.append(f'step failed: {name}: {getattr(e, "stderr", None) or e}'.strip())
        return None


def inbox_data(cli, gh, repo):
    labels, k = cli.belt()['labels'], cli.knowledge()
    allowed = {'domain': k.domains() if k else [], 'kind': [x.split(':', 1)[1] for x in labels['kind']],
               'size': [x.split(':', 1)[1] for x in labels['size']]}
    return cli.open_belt(gh, repo)[1]['inbox'], allowed


def dispatch_counts(text, dry):
    """(started, waiting, held) from dispatch's output: its own Tick: line, or the dry run's skip and hold lines."""
    lines = text.split('\n')
    if not dry:
        m = re.search(r'^Tick: .* · started (\d+) · waiting (\d+) · held (\d+)$', text, re.M)
        return int(m[1]), int(m[2]), int(m[3])
    return 0, len([x for x in lines if x.startswith('Skipped:')]), len([x for x in lines if x.startswith('start held:')])


def run(cli, gh, repo, log=None, dry=False):
    """(text, failure count). With `dry` every step is read-only and nothing is written."""
    from . import dispatch
    failed, out = [], []
    board = attempt(cli, 'sweep', lambda: cli.board(gh, repo, write=not dry)[0], failed)
    out += ['== sweep ==', *(board if board is not None else ['(failed)'])]
    inbox = attempt(cli, 'inbox', lambda: inbox_data(cli, gh, repo), failed)
    out.append('== inbox ==')
    if inbox:
        items, allowed = inbox
        out += [f'Inbox to sort: {len(items)}', *[f"- #{i['number']} {i['title']}" for i in items],
                'Allowed: ' + ' · '.join(f"{k} {', '.join(v) or 'none'}" for k, v in allowed.items())]
    out.append('== pull ==')
    if board is None:
        out.append('skipped: pull (needs sweep)')
    else:
        out += [x for x in board if x.startswith('Pull next:')]
    text = attempt(cli, 'dispatch', lambda: dispatch.run(cli, gh, repo, log, dry, beat=False), failed)
    out.append('== dispatch ==')
    started, waiting, held = dispatch_counts(text, dry) if text is not None else (0, 0, 0)
    out += [x for x in (text or '').split('\n') if x and not x.startswith('Tick:')]
    heartbeat = (f"Tick: {cli.stamp(cli.now())} · started {started} · waiting {waiting} · held {held} · "
                 f"inbox {len(inbox[0]) if inbox else 0}")
    if not re.match(cli.belt()['tick']['heartbeat']['pattern'], heartbeat):
        raise cli.Refused(f'malformed heartbeat line: {heartbeat}')
    out += [*failed, heartbeat]
    if log and not dry:
        with cli.task_log(log)[0].open('a') as fh:
            fh.write(heartbeat + '\n')
    return '\n'.join(out), len(failed)
