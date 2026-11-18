"""Publish a task's plan and tickets as GitHub issues, then claim, tick and close them (workflow-contracts issues.md),
and run the belt's gate commands (workflow-contracts conveyor.md).

The draft folder stays the working copy: `plan.md` records `Issue: <owner/repo>#<n>` and each ticket line in
`action-items.md` records `issue #<n>`, so a second run creates nothing.
"""
import argparse
import functools
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .work_trace import validate as validate_work_trace, preview as trace_preview

ITEM = re.compile(r'^- \[[ x]\] \*\*(\d+)\. (.+?)\*\*(.*)$')
PLAN_ISSUE = re.compile(r'^Issue: (\S+)#(\d+)$', re.M)
BOX = re.compile(r'^(\s*)- \[[ x]\] (.*)$')


class Refused(Exception):
    pass


def is_write(args):
    return args[:2] in (['issue', 'create'], ['issue', 'edit'], ['issue', 'comment'], ['issue', 'close'],
                        ['label', 'create']) or (args[0] == 'api' and '-X' in args)


def real_gh(args, stdin=None):
    return subprocess.run(['gh', *args], input=stdin, capture_output=True, text=True, check=True).stdout


class DryRun:
    """Passes reads to gh; prints writes instead, with placeholder numbers for issues it would create."""
    def __init__(self, gh):
        self.gh, self.next, self.fake = gh, 900001, set()

    def __call__(self, args, stdin=None):
        m = args[0] == 'api' and '-X' not in args and re.fullmatch(r'repos/.+/issues/(\d+)(/.+)?', args[1])
        if m and int(m[1]) in self.fake:
            return '' if m[2] else '0'  # a would-be issue has id 0 and no links yet
        if not is_write(args):
            return self.gh(args, stdin)
        print(shlex.join(['gh', *args]))
        if args[:2] == ['issue', 'create']:
            self.fake.add(self.next); self.next += 1
            return f'https://github.com/{args[args.index("-R") + 1]}/issues/{self.next - 1}'
        return ''


def parse_tickets(text):
    """Ticket items in order: number, after, issue and the item line's index."""
    return [{'n': int(m[1]), 'line': i, 'issue': next((int(x) for x in re.findall(r' · issue #(\d+)', m[3])), None),
             'after': [int(k) for seg in m[3].split(' · ') if seg.startswith('after ') for k in re.findall(r'#(\d+)', seg)]}
            for i, line in enumerate(text.split('\n')) if (m := ITEM.match(line))]


def parse_issue_text(text):
    """The session's plain-language issue text per ticket (`issue-text.md`): {n: (title, what to build, criteria)}."""
    out = {}
    for sec in re.split(r'^(?=## )', text, flags=re.M):  # any heading ends a ticket's section
        m = re.match(r'## (\d+)\. (.+)\n', sec)
        if m:
            lines = sec[m.end():].strip().split('\n')
            criteria = [b[2] for line in lines if (b := BOX.match(line))]
            what = '\n'.join(line for line in lines if not BOX.match(line)).strip()
            out[int(m[1])] = (m[2].strip(), what, criteria)
    return out


def ticket_body(what, criteria, parent, blockers):
    parts = [f'## Parent\n\n#{parent}', f'## What to build\n\n{what}',
             '## Acceptance criteria\n\n' + '\n'.join(f'- [ ] {c}' for c in criteria),
             '## Blocked by\n\n' + ('\n'.join(f'- #{b}' for b in blockers) or 'None: can start now.')]
    return '\n\n'.join(parts) + '\n'


def create(gh, repo, title, body, label=None):
    args = ['issue', 'create', '-R', repo, '--title', title, '--body-file', '-'] + (['--label', label] if label else [])
    return int(gh(args, body).strip().rsplit('/', 1)[1])


def issue_id(gh, repo, n):
    return gh(['api', f'repos/{repo}/issues/{n}', '--jq', '.id']).strip()


def link(gh, repo, n, path, field, targets):
    """POST each target issue to `issues/<n>/<path>` unless GitHub already lists it there."""
    url = f'repos/{repo}/issues/{n}/{path}'
    have = {int(x) for x in gh(['api', url, '--paginate', '--jq', '.[].number']).split()}
    for t in targets:
        if t not in have:
            gh(['api', '-X', 'POST', url, '-F', f'{field}={issue_id(gh, repo, t)}'])


def publish(gh, repo, folder, title, body_file, label, dry_run, owner=None, domain=None, session=None):
    plan_path, items_path, text_path = folder / 'plan.md', folder / 'action-items.md', folder / 'issue-text.md'
    plan = plan_path.read_text()
    items = items_path.read_text() if items_path.exists() else ''
    tickets = parse_tickets(items) if re.search(r'^Tickets: \d+', items, re.M) else []
    text = parse_issue_text(text_path.read_text()) if text_path.exists() else {}
    known = {t['n'] for t in tickets}
    for t in tickets:
        missing = [k for k in t['after'] if k not in known]
        if missing:
            raise Refused(f"ticket {t['n']} is after unknown ticket(s) {missing}")
        if not t['issue'] and not (t['n'] in text and all(text[t['n']])):
            raise Refused(f"ticket {t['n']} needs a '## {t['n']}. <title>' section in issue-text.md "
                          'with a plain what-to-build paragraph and - [ ] criteria')
    m = PLAN_ISSUE.search(plan)
    if m and m[1] != repo:
        raise Refused(f'plan.md is tracked in {m[1]}, not {repo}')
    if not m and not (title and body_file):
        raise Refused('plan.md has no Issue: line; pass --title and --body-file to create it')
    belt = publish_preflight(gh, repo, m and int(m[2]), body_file, owner, domain, session)
    if m:
        parent = int(m[2])
    else:
        ensure_labels(gh, repo, belt['labels'])
        parent = create(gh, repo, title, Path(body_file).read_text(), ','.join(filter(None, [label, *belt['labels']])))
        head, _, rest = plan.partition('\n')
        plan = f'{head}\nIssue: {repo}#{parent}\n{rest}'
        dry_run or plan_path.write_text(plan)
    publish_belt(gh, repo, parent, belt)
    print(f'Issue: {repo}#{parent}')
    numbers, lines = {t['n']: t['issue'] for t in tickets if t['issue']}, items.split('\n')
    for t in tickets:
        blockers = [numbers[k] for k in t['after']]
        n = t['issue']
        if not n:
            # Record the number before linking, so a rerun after a failed link adds the link instead of a duplicate.
            title, what, criteria = text[t['n']]
            n = numbers[t['n']] = create(gh, repo, title, ticket_body(what, criteria, parent, blockers))
            lines[t['line']] += f' · issue #{n}'
            dry_run or items_path.write_text('\n'.join(lines))
        link(gh, repo, n, 'dependencies/blocked_by', 'issue_id', blockers)
        print(f"ticket {t['n']}: #{n}")
    if tickets:
        link(gh, repo, parent, 'sub_issues', 'sub_issue_id', [numbers[t['n']] for t in tickets])


def view(gh, repo, n, fields):
    return json.loads(gh(['issue', 'view', str(n), '-R', repo, '--json', fields]))


def claim_session(body):
    match = re.search(r'· session (\S+)\s*$', body.strip()) if body.startswith('Claimed:') else None
    return match[1] if match else None


def claim_owner(comments):
    """The session holding the issue: the latest claim note whose session did not later get a `Released:` note from the login that wrote the claim."""
    held = []
    for c in comments:
        body, login = c['body'].strip(), (c.get('author') or {}).get('login')
        if claim_session(body):
            held.append((claim_session(body), login))
        elif body.startswith('Released:') and (m := re.search(r'session (\S+)', body)):
            held = [x for x in held if x != (m[1], login)]
    return held[-1][0] if held else None


def session_id(session):
    session = session or os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or os.environ.get('CLAUDE_CODE_SESSION_ID')
    if not session:
        raise Refused('no session id in the environment; pass --session')
    return session


def claim(gh, repo, n, branch, session, approved, takeover=False):
    session = session_id(session)
    me = gh(['api', 'user', '--jq', '.login']).strip()
    data = view(gh, repo, n, 'assignees,author,comments,labels')
    others = [a['login'] for a in data['assignees'] if a['login'] != me]
    if others:
        raise Refused(f'#{n} is assigned to {", ".join(others)}; ask the user before taking it over')
    if data['author']['login'] != me and not approved:
        raise Refused(f"#{n} was filed by {data['author']['login']}; claim it only with the user's OK (--approved)")
    note = f'Claimed: branch `{branch}` · session {session}'
    owner = claim_owner(data['comments'])
    if owner and owner != session and not takeover:
        raise Refused(f'#{n} already carries a claim by session {owner}; ask the user, then pass --takeover')
    if not data['assignees']:
        gh(['issue', 'edit', str(n), '-R', repo, '--add-assignee', '@me'])
    if owner != session:
        gh(['issue', 'comment', str(n), '-R', repo, '--body-file', '-'], note + '\n')
        # Best-effort guard, not atomic: the first claim note of any login after our read wins; a loser retracts its note.
        fresh = view(gh, repo, n, 'assignees,comments')
        winner = next((claim_session(c['body']) for c in fresh['comments'][len(data['comments']):] if claim_session(c['body'])), session)
        rivals = [a['login'] for a in fresh['assignees'] if a['login'] != me]
        if winner != session or rivals:
            who = f'session {winner}' if winner != session else ', '.join(rivals)
            gh(['issue', 'comment', str(n), '-R', repo, '--body-file', '-'], f'Released: session {session} · lost claim to {who}\n')
            raise Refused(f'#{n} was claimed meanwhile by {who}; stop and ask the user')
        cur = lane_of({'number': n, **data})
        record(gh, repo, n, conveyor_line('claim', cur, cur))
    print(f'#{n} claimed by {me}')


def body_digest(body):
    return hashlib.sha256(body.encode()).hexdigest()


def criteria(body):
    """Stable ordinal and exact text within the acceptance section, never unrelated boxes."""
    found, inside = [], False
    for line_index, line in enumerate(body.split('\n')):
        if line.startswith('## '):
            inside = line.strip() == '## Acceptance criteria'
        if inside and (box := BOX.match(line)):
            found.append({'number': len(found) + 1, 'line': line_index, 'text': box[2],
                          'checked': line.lstrip().startswith('- [x] ')})
    return found


def evidence_file(path, repo):
    if not path:
        raise Refused('--evidence-file is required; legacy bulk completion is disabled')
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or data.get('version') != 1 or data.get('repo') != repo or not isinstance(data.get('authority_ref'), str) or not data['authority_ref'].strip() or not isinstance(data.get('issues'), dict):
        raise Refused('evidence needs version 1, matching repo and original scoped authority_ref')
    return data


def checked_evidence(data, n, body, require_all=False):
    entry = data.get('issues', {}).get(str(n), {})
    if not isinstance(entry, dict) or entry.get('body_sha256') != body_digest(body):
        raise Refused(f'#{n} body changed or body_sha256 missing; reconcile before writing')
    validate_work_trace(entry.get('work_record'), data['repo'], n)
    boxes = criteria(body)
    by_number = {c['number']: c for c in boxes}
    proof = entry.get('criteria', [])
    if not isinstance(proof, list):
        raise Refused(f'#{n} criteria evidence must be a list')
    selected = set()
    for item in proof:
        number = item.get('number') if isinstance(item, dict) else None
        if type(number) is not int or number not in by_number or number in selected:
            raise Refused(f'#{n} invalid or duplicate criterion number')
        if item.get('text') != by_number[number]['text'] or item.get('status') != 'verified' or not isinstance(item.get('evidence_ref'), str) or not item['evidence_ref'].strip():
            raise Refused(f'#{n} criterion {number} needs exact text and verified evidence_ref')
        selected.add(number)
    if require_all and (not boxes or selected != set(by_number)):
        raise Refused(f'#{n} closure requires evidence for every acceptance criterion')
    return entry, boxes, selected


def tick(gh, repo, n, evidence_path):
    data = evidence_file(evidence_path, repo)
    body = view(gh, repo, n, 'body')['body']
    _, boxes, selected = checked_evidence(data, n, body)
    lines = body.split('\n')
    for box in boxes:
        if box['number'] in selected and not box['checked']:
            lines[box['line']] = lines[box['line']].replace('- [ ] ', '- [x] ', 1)
    new = '\n'.join(lines)
    if new != body:
        if view(gh, repo, n, 'body')['body'] != body:
            raise Refused(f'#{n} changed during preflight; no write performed')
        gh(['issue', 'edit', str(n), '-R', repo, '--body-file', '-'], new)
    print(f'#{n} proved criteria updated: {sorted(selected)}')


def task_issues(folder):
    """The plan's repo and issue, then each published ticket's issue."""
    m = PLAN_ISSUE.search((folder / 'plan.md').read_text())
    if not m:
        raise Refused('plan.md has no Issue: line')
    items = folder / 'action-items.md'
    tickets = parse_tickets(items.read_text()) if items.exists() else []
    return m[1], int(m[2]), [t['issue'] for t in tickets if t['issue']]


def closes(folder):
    records = re.findall(r'^Issue: (.*)$', (folder / 'plan.md').read_text(), re.M)
    if len(records) != 1 or not re.fullmatch(
            r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9_.-]+#[1-9][0-9]*', records[0]):
        raise Refused('plan.md needs one valid Issue: <owner/repo>#<positive number> record')
    repo, parent, tickets = task_issues(folder)
    if repo.rsplit('/', 1)[1] in ('.', '..') or any(n < 1 for n in tickets):
        raise Refused('closing references need a valid repository and positive issue numbers')
    print('\n'.join(f'Closes {repo}#{n}' for n in [parent] + tickets))


def prepare_evidence(gh, repo, number=None, folder=None):
    """Read-only template: source snapshots never manufacture completion or authority."""
    if folder is not None:
        tracked, parent, tickets = task_issues(folder)
        if tracked != repo:
            raise Refused(f'plan.md is tracked in {tracked}, not {repo}')
        numbers = list(dict.fromkeys(tickets + [parent]))
    else:
        numbers = [number]
    data = {'version': 1, 'repo': repo, 'authority_ref': '', 'issues': {},
            'deployment': {'sha': '', 'status': 'unverified', 'target': '',
                           'receipt_ref': '', 'observed_at': ''}}
    for n in numbers:
        current = view(gh, repo, n, 'state,body')
        if current['state'] != 'OPEN':
            continue
        data['issues'][str(n)] = {
            'body_sha256': body_digest(current['body']),
            'criteria': [{'number': c['number'], 'text': c['text'], 'status': 'unverified',
                          'evidence_ref': ''} for c in criteria(current['body'])],
            'work_record': {'issue_url': f'https://github.com/{repo}/issues/{n}',
                            'source_issue_url': '', 'owner': '',
                            'executor': {'host': '', 'session_ref': ''}, 'artifacts': [],
                            'decisions': [], 'verification': [],
                            'states': {'implementation': 'unverified', 'deployment': 'unverified', 'acceptance': 'unverified'},
                            'next_action': {'owner': '', 'action': ''}},
            'closure': {'status': 'unverified', 'evidence_ref': ''}}
    print(json.dumps(data, indent=2))


def close(gh, repo, folder, sha, evidence_path):
    """Preflight every open issue before closing any; evidence is a supplied receipt, not backend verification."""
    tracked, parent, tickets = task_issues(folder)
    if tracked != repo:
        raise Refused(f'plan.md is tracked in {tracked}, not {repo}')
    data = evidence_file(evidence_path, repo)
    deployment = data.get('deployment', {})
    if not isinstance(deployment, dict) or not re.fullmatch(r'[0-9a-f]{40}', sha) or any(not isinstance(deployment.get(k), str) or not deployment[k].strip() for k in ('target', 'receipt_ref', 'observed_at')) or deployment.get('sha') != sha or deployment.get('status') != 'verified':
        raise Refused('closure needs full deployed SHA and a verified target/receipt_ref/observed_at')
    ready = []
    for n in dict.fromkeys(tickets + [parent]):
        current = view(gh, repo, n, 'state,body')
        if current['state'] != 'OPEN':
            continue
        entry, boxes, _ = checked_evidence(data, n, current['body'], require_all=True)
        closure = entry.get('closure', {})
        if not all(c['checked'] for c in boxes) or not isinstance(closure, dict) or closure.get('status') != 'verified' or not isinstance(closure.get('evidence_ref'), str) or not closure['evidence_ref'].strip():
            raise Refused(f'#{n} closure gate is unproved or acceptance boxes remain open')
        states = entry['work_record']['states']
        if states['implementation'] != 'verified' or states['deployment'] != 'verified' or states['acceptance'] not in ('verified', 'not_applicable'):
            raise Refused(f'#{n} work trace retains an unmet implementation/deployment/acceptance gate')
        ready.append((n, current))
    # Reconcile the whole batch again before the first side effect. GitHub CLI does
    # not offer a compare-and-swap transaction; remote edits after this remain possible.
    for n, current in ready:
        if view(gh, repo, n, 'state,body') != current:
            raise Refused(f'#{n} changed during preflight; no issues closed')
    for n, current in ready:
        if view(gh, repo, n, 'state,body') != current:
            raise Refused(f'#{n} changed during execution; reconcile any earlier successful closures')
        gh(['issue', 'close', str(n), '-R', repo, '--comment',
            f'Deployed in {sha}. Evidence: {deployment["receipt_ref"]}; closure: {data["issues"][str(n)]["closure"]["evidence_ref"]}.'])
        print(f'#{n} closed')


# The belt (conveyor.md): lanes, receipts and limits come from conveyor.json and contracts.md § Defaults.
RELEASE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = RELEASE_ROOT / 'skills' / 'workflow-contracts'
STAMP = '%Y-%m-%d %H:%MZ'
# conveyor.md § Sweep and the build spec § 2a: capture dedupe window, spool and inbox lateness, weekly backlog age.
CAPTURE_WINDOW, SPOOL_LATE = timedelta(minutes=10), timedelta(minutes=15)
INBOX_LATE, BACKLOG_OLD, WEEK = timedelta(hours=24), timedelta(days=30), timedelta(days=7)
UNREACHABLE = re.compile(r'error connecting to|could not resolve host|dial tcp|i/o timeout|connection (refused|reset)'
                         r'|network is unreachable|TLS handshake timeout|HTTP 50[234]', re.I)
FIELDS = 'number,title,body,labels,comments,state,createdAt,url,closedByPullRequestsReferences'
PRIO_RANK = {'prio:now': 0, 'prio:next': 1, 'prio:later': 2}
CARD_LABELS = {'goal': 'Goal', 'from': 'From', 'changes': 'Changes', 'checked': 'Checked', 'if_yes': 'If yes',
               'if_no': 'If no', 'if_wait': 'If wait', 'undo': 'Undo', 'recommended': 'Recommended', 'link': 'Link'}


@functools.lru_cache(maxsize=None)
def belt():
    return json.loads((CONTRACTS / 'conveyor.json').read_text())


def lanes():
    return [lane['name'] for lane in belt()['lanes']]


def receipt(name):
    return belt()['receipts'][name]


def now():
    return datetime.now(timezone.utc)


def stamp(moment):
    return moment.strftime(STAMP)


def parse_stamp(text):
    return datetime.strptime(text, STAMP).replace(tzinfo=timezone.utc)


def parse_iso(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


@functools.lru_cache(maxsize=None)
def skills_sha():
    """The skills release this helper runs from: the timeline's `skills` field."""
    return subprocess.run(['git', '-C', str(RELEASE_ROOT), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True, check=True).stdout.strip()


def machine_config():
    from .safeguard_cli import machine_config as read
    return read()


def project():
    """(root, text) of the project CLAUDE.md governing the working directory."""
    for folder in (Path.cwd(), *Path.cwd().parents):
        if (folder / 'CLAUDE.md').is_file():
            return folder, (folder / 'CLAUDE.md').read_text()
    raise Refused('no project CLAUDE.md at or above the working directory')


def section(text, name):
    m = re.search(rf'^## {re.escape(name)}\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return m[1] if m else ''


def defaults():
    """contracts.md § Defaults, each line overridable by the project's § Defaults."""
    out = {}
    for text in ((CONTRACTS / 'contracts.md').read_text(), project()[1]):
        out.update(re.findall(r'^- ([^:\n]+): (.+)$', section(text, 'Defaults'), re.M))
    return out


def limits():
    line, out = defaults().get('Lane limits', ''), {}
    for key, pattern in (('Build', r'Build (\d+)'), ('Review', r'Review (\d+)'), ('Train', r'train of ≤(\d+)')):
        m = re.search(pattern, line)
        if not m:
            raise Refused(f'§ Defaults `Lane limits` names no {key} number')
        out[key] = int(m[1])
    return out


def review_fallback():
    m = re.match(r'(\d+(?:\.\d+)?) hours?\b', defaults().get('Review fallback', ''))
    if not m:
        raise Refused('§ Defaults has no `Review fallback: <n> hours`')
    return timedelta(hours=float(m[1]))


def knowledge_names():
    """§ Map `Knowledge`: (project root, brain owner/repo, wiki directory), or None for `none`."""
    root, text = project()
    m = re.search(r'^- Knowledge: (.+)$', section(text, 'Map'), re.M)
    if not m:
        raise Refused('project CLAUDE.md § Map has no `Knowledge:` line (conveyor.md § Knowledge)')
    if m[1].strip() == 'none':
        return None
    brain, wiki = (re.search(rf'{key} `?([^`\s·]+)', m[1]) for key in ('brain', 'wiki'))
    return root, brain and brain[1], wiki and wiki[1]


def knowledge():
    """The project's knowledge stores, or None under `Knowledge: none`. Imported on use: T6 ships the module."""
    names = knowledge_names()
    if names is None:
        return None
    root, brain, wiki = names
    from .knowledge import Knowledge
    return Knowledge.open(brain=brain, wiki=wiki and str(root / wiki))


def task_log(path):
    """(path, lines) of the task's log.md; a path outside the working directory is refused (conveyor.md § Permissions)."""
    if path is None:
        return None, []
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise Refused(f'--log {path} is outside the working directory; belt commands take no outside path')
    return resolved, [line.strip() for line in resolved.read_text().split('\n')]


def load(gh, repo, n):
    return view(gh, repo, n, FIELDS)


def label_names(d):
    return [x['name'] for x in d.get('labels', [])]


def lane_of(d):
    found = [x[5:] for x in label_names(d) if x.startswith('lane:')]
    if len(found) > 1:
        raise Refused(f"#{d['number']} carries more than one lane label: {', '.join(found)}")
    return found[0] if found else None


def comment_lines(d):
    return [line.strip() for c in d.get('comments', []) for line in c['body'].replace('\r\n', '\n').split('\n')]


def timeline_of(lines):
    pattern = re.compile(belt()['timeline']['pattern'])
    return [m for line in lines if (m := pattern.match(line))]


def corrected(lines, sources):
    """A wrong receipt is never edited: gates read its `Correction:` in its place (conveyor.md § Receipts)."""
    pattern = re.compile(belt()['timeline']['correction'])
    fixes = [m for line in sources if (m := pattern.match(line))]
    out = []
    for line in lines:
        for f in fixes:
            if not pattern.match(line) and f"{f['field'].rstrip(':')}:" in line and f['wrong'] in line:
                line = line.replace(f['wrong'], f['right'], 1)
        out.append(line)
    return out


def pr_head(gh, repo, number):
    return gh(['pr', 'view', str(number), '-R', repo, '--json', 'headRefOid', '--jq', '.headRefOid']).strip()


class Facts:
    """What the gates read for one issue: labels, body, comments, the task log, the linked PR's head and the claim."""
    def __init__(self, gh, repo, d, log_lines=(), learned=None):
        raw = comment_lines(d)
        self.labels, self.learned = label_names(d), learned
        self.body = [line.strip() for line in d.get('body', '').replace('\r\n', '\n').split('\n')]
        self.comments = corrected(raw, raw + list(log_lines))
        self.log = corrected(list(log_lines), raw + list(log_lines))
        self.timeline = timeline_of(self.comments)
        self.prs = d.get('closedByPullRequestsReferences') or []
        self.head = pr_head(gh, repo, self.prs[0]['number']) if len(self.prs) == 1 else None
        self.claim = claim_owner(d.get('comments', []))


def schedule_ids(f):
    return {m[0].split()[-1] for line in f.log if (m := re.search(receipt('schedule')['pattern'], line))}


def have(name, k, f):
    """True when receipt `name` is present `k` times (conveyor.json receipts)."""
    r = receipt(name)
    source = r['source']
    if source == 'labels':
        return sum(bool(re.fullmatch(r['pattern'], x)) for x in f.labels) == r['count']
    if source == 'linked_pr':
        return len(f.prs) == r['count']
    if source == 'timeline':
        return any(t['command'] == r['command'] for t in f.timeline)
    if source == 'closing_comment':
        return bool(f.learned) and bool(re.fullmatch(r['pattern'], f'Learned: {f.learned}'))
    lines = {'issue_body': f.body, 'issue_comment': f.comments, 'log': f.log}[source]
    found = [m for line in lines if (m := re.search(r['pattern'], line))]
    if r.get('binds') == 'pr_head':
        found = [m for m in found if f.head and f.head.startswith(m['head'])]
    if r.get('not_equal') == 'claim.session':
        found = [m for m in found if m['session'] != f.claim]
    if r.get('binds') == 'schedule.id':
        ids = schedule_ids(f)
        return len(ids) >= k and ids <= {m['id'] for m in found}
    return len({m[0] for m in found}) >= k


def describe(name):
    r = receipt(name)
    token = re.match(r'\^?([A-Za-z][A-Za-z -]*:)', r.get('pattern', ''))
    where = {'labels': 'label', 'linked_pr': 'linked PR', 'timeline': f"Conveyor {r.get('command')} line",
             'closing_comment': 'closing comment'}.get(r['source'], r['source'].replace('_', ' '))
    return f"{name} ({where}{' `' + token[1] + '`' if token and r['source'] != 'labels' else ''})"


def missing_for(f, target):
    need = Counter(next(lane for lane in belt()['lanes'] if lane['name'] == target)['requires'])
    return [describe(name) for name, k in need.items() if not have(name, k, f)]


def lane_count(gh, repo, lane):
    return len(json.loads(gh(['issue', 'list', '-R', repo, '--state', 'open', '--label', f'lane:{lane}',
                              '--limit', '1000', '--json', 'number'])))


def room_missing(gh, repo, target, labels):
    """Lane limits (contracts.md § Defaults): `next` holds at most Build's free slots; Build keeps its last slot for prio:now."""
    lim = limits()
    if target == 'next':
        free, held = lim['Build'] - lane_count(gh, repo, 'in-progress'), lane_count(gh, repo, 'next')
        return [] if held < free else [f'room (next holds {held}; Build has {max(free, 0)} free slots)']
    if target == 'in-progress':
        busy = lane_count(gh, repo, 'in-progress')
        if busy >= lim['Build']:
            return [f"limit (Build {busy} of {lim['Build']})"]
        if busy == lim['Build'] - 1 and 'prio:now' not in labels:
            return ['limit (the last Build slot is kept for prio:now)']
    if target == 'in-review':
        busy = lane_count(gh, repo, 'in-review')
        if busy >= lim['Review']:
            return [f"limit (Review {busy} of {lim['Review']})"]
    return []


def ensure_labels(gh, repo, names):
    """A gate needing a missing belt label creates it: additive only (conveyor.md § Labels)."""
    if not names:
        return
    present = set(gh(['label', 'list', '-R', repo, '--limit', '1000', '--json', 'name', '--jq', '.[].name']).split('\n'))
    for name in names:
        if name not in present:
            gh(['label', 'create', name, '-R', repo])


def relabel(gh, repo, n, add=(), remove=()):
    if not add and not remove:
        return
    ensure_labels(gh, repo, list(add))
    gh(['issue', 'edit', str(n), '-R', repo, *(['--add-label', ','.join(add)] if add else []),
        *(['--remove-label', ','.join(remove)] if remove else [])])


def conveyor_line(command, frm, to, head=None, tests=None, schedules=()):
    line = (f"Conveyor: {stamp(now())} · {command} · {frm or '-'} → {to or '-'} · head {head or '-'} · "
            f"tests {tests or '-'} · skills {skills_sha()} · schedules {','.join(sorted(schedules)) or '-'}")
    if not re.fullmatch(belt()['timeline']['pattern'], line):
        raise Refused(f'malformed timeline line: {line}')
    return line


def record(gh, repo, n, line, log=None, before=(), close_reason=None):
    """One issue comment (or the closing comment) carrying the receipt lines; the timeline line also goes to the task log."""
    body = '\n'.join([*before, line]) + '\n'
    if close_reason:
        gh(['issue', 'close', str(n), '-R', repo, '--reason', close_reason, '--comment', body])
    else:
        gh(['issue', 'comment', str(n), '-R', repo, '--body-file', '-'], body)
    if log and not isinstance(gh, DryRun):
        with log.open('a') as fh:
            fh.write(line + '\n')


def move(gh, repo, n, target, reason=None, log=None, tests=None, learned=None, command='lane'):
    """`lane`: check the entry rule and refuse naming each missing receipt; a move back needs --reason."""
    order = lanes()
    if target not in order:
        raise Refused(f"unknown lane {target!r}; lanes: {', '.join(order)}")
    d = load(gh, repo, n)
    if d['state'] != 'OPEN':
        raise Refused(f'#{n} is closed')
    cur = lane_of(d)
    if cur == target:
        return f'#{n} is already in {target}'
    log_path, log_lines = task_log(log)
    f = Facts(gh, repo, d, log_lines, learned)
    before = []
    if cur is not None and order.index(target) < order.index(cur):
        if not reason:
            raise Refused(f'#{n} {cur} → {target} is a move back; pass --reason (its receipt)')
        before = [f'Moved back: {cur} → {target} · {reason}']
    else:
        if 'hold' in f.labels:
            raise Refused(f'#{n} carries hold; forward moves stop')
        skipped = order[(order.index(cur) + 1 if cur else 0):order.index(target)]
        if skipped and order.index(target) > order.index('next'):
            raise Refused(f"#{n} {cur or '-'} → {target} skips {', '.join(skipped)}; after next no lane is skipped")
        missing = missing_for(f, target) + room_missing(gh, repo, target, f.labels)
        if missing:
            raise Refused(f"#{n} cannot enter {target}; missing: {'; '.join(missing)}")
    relabel(gh, repo, n, [f'lane:{target}'], [f'lane:{cur}'] if cur else [])
    line = conveyor_line(command, cur, target, f.head, tests, schedule_ids(f))
    if target == 'closed':
        record(gh, repo, n, line, log_path, [f'Learned: {learned}'], close_reason='completed')
    else:
        record(gh, repo, n, line, log_path, before)
    return f"#{n} {cur or '-'} → {target}"


def title_of(text):
    first = text.split('\n', 1)[0].strip()
    return first if len(first) <= 80 else first[:79] + '…'


def captured(body):
    """(verbatim text, capture time) of a captured issue body, else None."""
    body = body.replace('\r\n', '\n')
    m = re.search(r'\n\nCaptured: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}Z) · source \S+\n?$', body)
    return (body[:m.start()], parse_stamp(m[1])) if m else None


def recent_capture(gh, repo, text, at):
    for i in json.loads(gh(['issue', 'list', '-R', repo, '--state', 'all', '--limit', '100', '--json', 'number,body'])):
        c = captured(i['body'])
        if c and c[0].strip() == text and abs(c[1] - at) <= CAPTURE_WINDOW:
            return i['number']
    return None


def spool_path():
    value = machine_config().get('capture_spool')
    return Path(value).expanduser() if value else None


def spool_read(path):
    return [json.loads(line) for line in path.read_text().split('\n') if line.strip()] if path and path.exists() else []


def spool_write(path, entries):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(''.join(json.dumps(e) + '\n' for e in entries))
    os.replace(tmp, path)


def spool_add(gh, repo, text, source, tag, at):
    path = spool_path()
    if path is None:
        raise Refused('GitHub is unreachable and workers.json has no capture_spool; nothing was captured')
    entries = spool_read(path)
    if any(e['repo'] == repo and e['text'] == text and abs(parse_stamp(e['at']) - at) <= CAPTURE_WINDOW for e in entries):
        return None, 'spooled already (same text within 10 minutes); the next sweep files it'
    entry = {'repo': repo, 'text': text, 'source': source, 'tag': tag, 'at': stamp(at)}
    if isinstance(gh, DryRun):
        return None, f'would spool: {json.dumps(entry)}'
    path.parent.mkdir(parents=True, exist_ok=True)
    spool_write(path, entries + [entry])
    return None, 'spooled: GitHub is unreachable; the next sweep files it'


def capture(gh, repo, text, source, tag=None, at=None, offline_ok=True):
    """Capture first, think later: the words verbatim as an inbox issue; same text within 10 minutes is one issue."""
    text, at = text.strip(), at or now()
    if not text:
        raise Refused('capture needs the words to capture')
    if not re.fullmatch(r'\S+', source or ''):
        raise Refused('capture needs --source <link or name without spaces>')
    try:
        n = recent_capture(gh, repo, text, at)
        if n:
            return n, f'#{n} (same text captured within 10 minutes)'
        labels = ['lane:inbox'] + ([f'prio:{tag}'] if tag else [])
        ensure_labels(gh, repo, labels)
        n = create(gh, repo, title_of(text), f'{text}\n\nCaptured: {stamp(at)} · source {source}\n', ','.join(labels))
    except subprocess.CalledProcessError as e:
        if not offline_ok or not UNREACHABLE.search(e.stderr or ''):
            raise
        return spool_add(gh, repo, text, source, tag, at)
    record(gh, repo, n, conveyor_line('capture', None, 'inbox'))
    return n, f'#{n}'


def flush_spool(gh, repo):
    """File each spooled capture for this repo; keep what still cannot reach GitHub. (filed numbers, still waiting)."""
    path = spool_path()
    entries, keep, filed = spool_read(path), [], []
    for e in entries:
        if e['repo'] != repo:
            keep.append(e)
            continue
        try:
            filed.append(capture(gh, repo, e['text'], e['source'], e.get('tag'), parse_stamp(e['at']), offline_ok=False)[0])
        except subprocess.CalledProcessError as err:
            if not UNREACHABLE.search(err.stderr or ''):
                raise
            keep.append(e)
    if filed and not isinstance(gh, DryRun):
        spool_write(path, keep)
    return filed, [e for e in keep if e['repo'] == repo]


def prio(gh, repo, n, level, log=None):
    """Bump or drop at the user's word: one prio label, or `drop` closes the issue as not planned."""
    d = load(gh, repo, n)
    cur, (log_path, _) = lane_of(d), task_log(log)
    if level == 'drop':
        record(gh, repo, n, conveyor_line('prio', cur, None), log_path, close_reason='not planned')
        return f'#{n} dropped'
    want, held = f'prio:{level}', [x for x in label_names(d) if x.startswith('prio:')]
    if held == [want]:
        return f'#{n} is already {want}'
    relabel(gh, repo, n, [want], [x for x in held if x != want])
    record(gh, repo, n, conveyor_line('prio', cur, cur), log_path)
    return f'#{n} {want}'


def publish_preflight(gh, repo, parent, body_file, owner, domain, session):
    """Everything publish's belt step needs, checked before any write (conveyor.md § Lanes, `next`)."""
    if not re.fullmatch(r'\S+', owner or ''):
        raise Refused('publish needs --owner <name without spaces>: lane next needs the Owner: line')
    if not domain:
        raise Refused('publish needs --domain: one domain:<name> label from the knowledge store')
    k = knowledge()
    if k is None:
        raise Refused('§ Map says Knowledge: none, so there is no domain vocabulary to publish against')
    valid = k.domains()
    if domain not in valid:
        raise Refused(f"domain {domain!r} is not in the knowledge store's routing table: {', '.join(valid) or 'none'}")
    current = load(gh, repo, parent) if parent else None
    body = current['body'] if current else Path(body_file).read_text()
    if not re.search(receipt('done_when')['pattern'], body, re.M):
        raise Refused('the issue body needs a `Done when: <check>` line')
    held = [x for x in label_names(current) if x.startswith('domain:')] if current else []
    if held and held != [f'domain:{domain}']:
        raise Refused(f"#{parent} already carries {', '.join(held)}; one domain label per issue")
    frm = lane_of(current) if current else None
    if frm != 'next':
        if current and 'hold' in label_names(current):
            raise Refused(f'#{parent} carries hold; forward moves stop')
        if frm and lanes().index(frm) > lanes().index('next'):
            raise Refused(f'#{parent} is in {frm}; publish moves an issue only up to next')
        missing = room_missing(gh, repo, 'next', label_names(current) if current else [])
        if missing:
            raise Refused(f"cannot enter next; missing: {'; '.join(missing)}")
    return {'owner': owner, 'session': session_id(session), 'from': frm, 'current': current,
            'labels': ['lane:next', f'domain:{domain}']}


def publish_belt(gh, repo, n, p):
    """Set lane next and the domain label, write the Owner: line and the timeline line; a rerun writes nothing."""
    cur = p['current']
    if cur:
        held = label_names(cur)
        relabel(gh, repo, n, [x for x in p['labels'] if x not in held],
                [x for x in held if x.startswith('lane:') and x != 'lane:next'])
    lines = comment_lines(cur) if cur else []
    owners = [m['owner'] for line in lines if (m := re.match(receipt('owner')['pattern'], line))]
    if not owners or owners[-1] != p['owner']:
        gh(['issue', 'comment', str(n), '-R', repo, '--body-file', '-'],
           f"Owner: {p['owner']} · session {p['session']} · {stamp(now())}\n")
    if p['from'] != 'next' or not any(t['command'] == 'publish' for t in timeline_of(lines)):
        record(gh, repo, n, conveyor_line('publish', p['from'], 'next'))


def decide(gh, repo, n, text, question, session, log=None):
    """Record the user's answer on the issue with its question link and the calling session, and as a decision row."""
    text = (text or '').strip()
    if not re.fullmatch(r'https?://\S+', question or ''):
        raise Refused('decide needs --question <link to the question>')
    if not text or '\n' in text or '|' in text:
        raise Refused("a decision is one line of the user's words, without |")
    session = session_id(session)
    k = knowledge()
    if k is not None and k.notice:
        raise Refused(f'{k.notice}: decide records its decision row in the brain (conveyor.md § Knowledge)')
    d = load(gh, repo, n)
    cur, (log_path, _), at = lane_of(d), task_log(log), now()
    line = f'Decision: {text} · {stamp(at)} · question {question} · session {session}'
    if not re.fullmatch(receipt('decision')['pattern'], line):
        raise Refused(f'malformed decision line: {line}')
    record(gh, repo, n, conveyor_line('decide', cur, cur), log_path, [line])
    if k is None:
        return f'#{n} decision recorded; Knowledge: none, so no decision row'
    ident = re.sub(r'[^a-z0-9]+', '-', f"{repo.split('/')[1]}-{n}-{at:%Y%m%d%H%M}".lower()).strip('-')
    scope = 'repo:' + re.sub(r'[^a-z0-9]+', '-', repo.split('/')[1].lower()).strip('-')
    out = k.record('decision', ident, at.strftime('%Y-%m-%d'), question, text, scope=scope)
    return f"#{n} decision recorded; decision row {out['path']}"


def origin(d):
    """The From field: the words stored at capture, else the body's first plain line."""
    c = captured(d.get('body', ''))
    text = c[0] if c else d.get('body', '')
    return next((line.strip() for line in text.split('\n') if line.strip() and not line.startswith('#')), '')


def action_record(path):
    """The run-approved action record a go card names (conveyor.json action_record), read from inside the worktree."""
    if not path:
        raise Refused('a go card needs --record <action record JSON>')
    resolved, _ = task_log(path)
    rec = json.loads(resolved.read_text())
    if rec.get('kind') not in belt()['action_record']['kinds'] or not isinstance(rec.get('id'), str) \
            or not re.fullmatch(r'[0-9a-f]{64}', str(rec.get('digest'))):
        raise Refused('the action record needs a known kind, an id and a sha256 digest')
    rollback = rec.get('rollback')
    if not isinstance(rollback, dict) or not rollback:
        raise Refused("the action record carries no rollback data for the go card's Undo")
    return rec, ' · '.join(f'{target}: {ref}' for target, ref in sorted(rollback.items()))


def ask(gh, repo, n, kind, given, record_file=None, log=None, more=None):
    """Build the decision card (conveyor.json card), or record `Asked for more` with --more."""
    d = load(gh, repo, n)
    cur, (log_path, log_lines) = lane_of(d), task_log(log)
    if more is not None:
        if not re.fullmatch(r'https?://\S+', more):
            raise Refused('--more needs the question link')
        record(gh, repo, n, conveyor_line('ask', cur, cur), log_path, [f'Asked for more: {stamp(now())} · question {more}'])
        return f'#{n} Asked for more recorded; not a decision, the question returns'
    card = belt()['card']
    if kind not in card['kinds']:
        raise Refused(f"--kind is one of {', '.join(card['kinds'])}")
    ai = set(card['ai_writes']) | set(card['ai_fills_by_kind'].get(kind, []))
    stray = [k for k, v in given.items() if v and k not in ai]
    if stray:
        raise Refused(f"the script fills {', '.join(stray)} on a {kind} card")
    if cur is None:
        raise Refused(f'#{n} has no lane label')
    f, order = Facts(gh, repo, d, log_lines), lanes()
    present, missing = [], []
    for lane in belt()['lanes'][:order.index(cur) + 1]:
        for name, k in Counter(lane['requires']).items():
            (present if have(name, k, f) else missing).append(name)
    fields = {'goal': f"{d['title']} · step {order.index(cur) + 1} of {len(order)}", 'from': origin(d),
              'checked': f"{', '.join(dict.fromkeys(present)) or 'none'} · Not yet: {', '.join(dict.fromkeys(missing)) or 'none'}",
              'link': d['url'], **{k: (v or '').strip() for k, v in given.items() if k in ai}}
    lines = []
    if kind == 'go':
        rec, fields['undo'] = action_record(record_file)
        lines.append(f"Go: {rec['kind']} {rec['id']} · digest {rec['digest'][:8]}")
    empty = [k for k in card['fields'] if not fields.get(k)]
    if empty:
        raise Refused(f"card refused: empty {', '.join(empty)}")
    opens = re.compile(card['refuse']['opens_with'])
    bad = [k for k in card['fields'] if opens.search(fields[k]) or '\n' in fields[k]]
    if bad:
        raise Refused(f"card refused: {', '.join(bad)} opens with a PR number or sha, or spans lines")
    lines += [f'{CARD_LABELS[k]}: {fields[k]}' for k in card['fields']]
    if len(lines) > card['max_lines']:
        raise Refused(f"card refused: {len(lines)} lines, at most {card['max_lines']}")
    record(gh, repo, n, conveyor_line('ask', cur, cur, f.head, None, schedule_ids(f)), log_path)
    return '\n'.join(lines)


def brief(gh, repo, n, log=None):
    """The station's fixed input: issue body, recorded decisions, and the domain's knowledge pages with verified dates."""
    d = load(gh, repo, n)
    cur, (log_path, _) = lane_of(d), task_log(log)
    lines = comment_lines(d)
    decisions = [x for x in corrected(lines, lines) if re.match(receipt('decision')['pattern'], x)]
    domains = [x.split(':', 1)[1] for x in label_names(d) if x.startswith('domain:')]
    out = [f"# Brief: #{n} {d['title']}", f"Lane: {cur or '-'} · labels: {', '.join(label_names(d)) or 'none'}", '',
           '## Issue', d.get('body', '').strip(), '', '## Decisions', *([f'- {x}' for x in decisions] or ['- none recorded']),
           '', '## Knowledge']
    k = knowledge()
    if k is None:
        out.append('- Knowledge: none in § Map')
    else:
        out += [k.notice] if k.notice else []
        out += [] if domains else ['- no domain label']
        for dom in domains:
            out += [f"- {p['store'] + ':' if p.get('store') else ''}{p['path']} · verified {p.get('verified') or 'unknown'}"
                    f"{' @ ' + p['sha'] if p.get('sha') else ''}{' · pending' if p.get('pending') else ''}"
                    for p in k.pages(dom)] or [f'- no pages for domain:{dom}']
    record(gh, repo, n, conveyor_line('brief', cur, cur), log_path)
    return '\n'.join(out)


def close_belt(gh, repo, n, learned, log=None):
    """Close a belt issue: the `closed` lane's receipts, including the `Learned:` closing line."""
    if not learned:
        raise Refused('close needs --learned: none, lesson: <text>, answered: <q> => <a> or page-fix: <path>: <text>')
    return move(gh, repo, n, 'closed', log=log, learned=learned, command='close')


def open_belt(gh, repo):
    issues = json.loads(gh(['issue', 'list', '-R', repo, '--state', 'open', '--limit', '1000', '--json', FIELDS]))
    by = {lane: [] for lane in lanes()}
    for i in issues:
        if lane_of(i):
            by[lane_of(i)].append(i)
    return [i for group in by.values() for i in group], by


def since(i):
    c = captured(i.get('body', ''))
    return c[1] if c else parse_iso(i['createdAt'])


def pull_order(backlog):
    """prio:now, prio:next, prio:later, then deadline, then age (conveyor.md § Limits and pull)."""
    def key(i):
        rank = min((PRIO_RANK[x] for x in label_names(i) if x in PRIO_RANK), default=len(PRIO_RANK))
        m = re.search(r'^Deadline: (\d{4}-\d{2}-\d{2})', i.get('body', ''), re.M)
        return rank, m[1] if m else '9999-99-99', parse_iso(i['createdAt'])
    return sorted(backlog, key=key)


def start_reviewer(repo, n, head, pr_url):
    """The review fallback: a fresh-context reviewer session through delegate.py runs test-review on that head."""
    prompt = (f'Run /test-review on {pr_url} at head {head} ({repo}#{n}). You are the fresh-context reviewer started '
              f'after Review fallback. Record `Reviewer: session <your session id> · head {head} · fallback` and '
              f'`Reviewed: {head} YES|NO` in the task log.\n')
    subprocess.run([sys.executable, str(RELEASE_ROOT / 'skills' / 'agent-coordination' / 'scripts' / 'delegate.py'),
                    'start', '--prompt-file', '-', '--cwd', str(project()[0]), '--name', f'review-fallback-{n}',
                    '--reason', 'review fallback', '--legacy-unbound'], input=prompt, text=True, capture_output=True, check=True)


def knowledge_digest(t):
    """Weekly: what changed in the brain this week, one undo per change."""
    names = knowledge_names()
    if names is None:
        return ['Knowledge digest: Knowledge: none in § Map']
    path = (machine_config().get('knowledge_stores') or {}).get(names[1]) if names[1] else None
    if not path or not Path(path).expanduser().is_dir():
        return ['Knowledge digest: brain: not configured on this machine']
    changes = [c for c in subprocess.run(['git', '-C', str(Path(path).expanduser()), 'log', f'--since={(t - WEEK).isoformat()}',
                                          '--format=%h %s'], capture_output=True, text=True, check=True).stdout.split('\n') if c]
    return [f'Knowledge digest: {len(changes)} change(s) this week'] + [
        f'- {s} · undo: revert {h} in {names[1]}' for h, _, s in (c.partition(' ') for c in changes)]


def sweep(gh, repo, weekly=False):
    """The board (conveyor.md § Sweep). Writes only the pull, spool flush, fallback start and knowledge log, each with a receipt."""
    t, lim, fallback = now(), limits(), review_fallback()
    asks, violations, wrote, notes = [], [], [], []
    filed, waiting = flush_spool(gh, repo)
    wrote += [f'filed spooled capture #{x}' for x in filed]
    _, by = open_belt(gh, repo)
    room = lim['Build'] - len(by['in-progress']) - len(by['next'])
    for i in pull_order(by['backlog']):
        if room <= 0:
            break
        try:
            move(gh, repo, i['number'], 'next', command='sweep')
        except Refused as e:
            violations.append(f'pull refused: {e}')
            continue
        wrote.append(f"pulled #{i['number']} to next")
        room -= 1
    if any(w.startswith('pulled') for w in wrote):
        _, by = open_belt(gh, repo)
    for i in by['in-review']:
        f = Facts(gh, repo, i)
        req = [m for line in f.comments if (m := re.match(receipt('review_requested')['pattern'], line))]
        if not req or t - parse_stamp(req[-1]['time']) < fallback:
            continue
        head = req[-1]['head']
        violations.append(f"review past fallback: #{i['number']} head {head} requested {req[-1]['time']}")
        if not any(x['command'] == 'sweep' and x['to'] == 'in-review' and x['head'] == head for x in f.timeline):
            if isinstance(gh, DryRun):
                print(f"would start a fallback reviewer for #{i['number']} at {head}")
            else:
                start_reviewer(repo, i['number'], head, f.prs[0]['url'] if f.prs else i['url'])
            record(gh, repo, i['number'], conveyor_line('sweep', 'in-review', 'in-review', head))
            wrote.append(f"fallback reviewer started for #{i['number']} at {head}")
    for i in by['ready-to-release']:
        f = Facts(gh, repo, i)
        moved = [x for x in f.timeline if x['to'] == 'ready-to-release']
        if f.head and moved and not f.head.startswith(moved[-1]['head']):
            violations.append(f"stale head: #{i['number']} reviewed {moved[-1]['head']}, PR head {f.head[:12]}")
    for i in by['monitoring']:
        moved = [x for x in timeline_of(comment_lines(i)) if x['to'] == 'monitoring']
        if not moved or len([s for s in moved[-1]['schedules'].split(',') if s != '-']) < 2:
            violations.append(f"monitoring without two schedules: #{i['number']}")
    free = lim['Build'] - len(by['in-progress'])
    for lane, cap in (('next', free), ('in-progress', lim['Build']), ('in-review', lim['Review']),
                      ('ready-to-release', lim['Train'])):
        if len(by[lane]) > cap:
            violations.append(f'lane over limit: {lane} {len(by[lane])} of {cap}')
    late = [i for i in by['inbox'] if t - since(i) > INBOX_LATE]
    violations += [f"inbox unsorted over 24 h: #{i['number']}" for i in late]
    if waiting and t - min(parse_stamp(e['at']) for e in waiting) > SPOOL_LATE:
        violations.append(f'spool over 15 min: {len(waiting)} capture(s) not yet filed')
    for i in [x for group in by.values() for x in group]:
        lines = comment_lines(i)
        asked = [x['time'] for x in timeline_of(lines) if x['command'] == 'ask']
        decided = [m['time'] for line in lines if (m := re.match(receipt('decision')['pattern'], line))]
        if 'needs-human' in label_names(i):
            asks.append(f"- #{i['number']} {i['title']} (needs-human)")
        elif asked and (not decided or parse_stamp(asked[-1]) > parse_stamp(decided[-1])):
            asks.append(f"- #{i['number']} {i['title']} (asked {asked[-1]})")
    closed = json.loads(gh(['issue', 'list', '-R', repo, '--state', 'closed', '--label', 'lane:closed', '--limit', '100',
                            '--json', 'number,comments']))
    k = False
    for i in closed:
        lines = comment_lines(i)
        if any(x['command'] == 'sweep' and x['to'] == 'closed' for x in timeline_of(lines)):
            continue
        k = knowledge() if k is False else k
        if k is None:
            notes.append('knowledge log: Knowledge: none in § Map')
            break
        keep = [x for x in lines if timeline_of([x]) or re.match(belt()['timeline']['correction'], x)]
        try:
            out = k.log(i['number'], keep)
        except ValueError as e:
            violations.append(f"knowledge log refused for #{i['number']}: {e}")
            continue
        record(gh, repo, i['number'], conveyor_line('sweep', 'closed', 'closed'))
        wrote.append(f"knowledge log #{i['number']}: {out['path']}")
    if weekly:
        old = [i for i in by['backlog'] if t - parse_iso(i['createdAt']) > BACKLOG_OLD]
        if old:
            asks.append(f"- Weekly: keep, drop or bump? {', '.join('#' + str(i['number']) for i in old)} (backlog over 30 days)")
        recent = [x for i in [*[x for g in by.values() for x in g], *closed] for x in comment_lines(i)]
        in_week = lambda when: t - parse_stamp(when) <= WEEK  # noqa: E731
        more = [m for x in recent if (m := re.match(receipt('asked_more')['pattern'], x)) and in_week(m['time'])]
        cards = len([x for x in timeline_of(recent) if x['command'] == 'ask' and in_week(x['time'])]) - len(more)
        decided = [m for x in recent if (m := re.match(receipt('decision')['pattern'], x)) and in_week(m['time'])]
        notes.append(f'Questions (7 days): asked {cards} ({cards / 7:.1f}/day) · decided {len(decided)} · tell me more {len(more)}')
        notes += knowledge_digest(t)
    from .disk_check import check
    notes += [check(str(Path.cwd()), machine_config())[1],
              'Not read: sessions, test slots, denial log (their belt sources are not built yet)']
    backlog = by['backlog']
    count = lambda level: len([i for i in backlog if f'prio:{level}' in label_names(i)])  # noqa: E731
    oldest = f"{int((t - min(since(i) for i in by['inbox'])).total_seconds() // 3600)}h" if by['inbox'] else '-'
    shown = {'next': free, 'in-progress': lim['Build'], 'in-review': lim['Review'], 'ready-to-release': lim['Train']}
    coming = [f"- #{i['number']} {i['title']} ({lane})" for lane in ('in-review', 'ready-to-release') for i in by[lane]]
    return '\n'.join([
        f'Need from you: {len(asks)}', *asks,
        'Lanes: ' + ' · '.join(f"{lane} {len(by[lane])}{'/' + str(shown[lane]) if lane in shown else ''}"
                               for lane in lanes() if lane != 'closed'),
        f"Backlog: {len(backlog)} (now {count('now')} · next {count('next')} · later {count('later')}) · oldest unsorted {oldest}",
        f"Coming to you next: {len(coming)}", *coming,
        f'Violations: {len(violations)}', *[f'- {v}' for v in violations],
        f'Wrote: {len(wrote)}', *[f'- {w}' for w in wrote], *notes])


def main(argv=None, gh=None):
    parser = argparse.ArgumentParser(prog='issues-cli')
    parser.add_argument('--dry-run', action='store_true', help='print every write instead of making it')
    subs = parser.add_subparsers(dest='action', required=True)
    p = subs.add_parser('publish', help="the plan's issue, then one sub-issue per ticket")
    p.add_argument('--repo', required=True); p.add_argument('draft')
    p.add_argument('--title'); p.add_argument('--body-file'); p.add_argument('--label')
    p.add_argument('--owner', help='the accountable owner written on the Owner: line')
    p.add_argument('--domain', help="one domain from the knowledge store's routing table")
    p.add_argument('--session', help='default: the desktop session id, else the CLI session id')
    log = argparse.ArgumentParser(add_help=False)
    log.add_argument('--repo', required=True)
    log.add_argument('--log', help="the task's log.md inside the working directory: log receipts are read and the timeline line appended")
    cap = subs.add_parser('capture', parents=[log], help='capture first: the words verbatim as an inbox issue')
    cap.add_argument('--source', required=True); cap.add_argument('--tag', choices=['now', 'next'])
    cap.add_argument('text', help="the words verbatim; '-' reads stdin")
    pr = subs.add_parser('prio', parents=[log], help='set the priority label, or drop at the user\'s word')
    pr.add_argument('number', type=int); pr.add_argument('level', choices=['now', 'next', 'later', 'drop'])
    ln = subs.add_parser('lane', parents=[log], help='move a card; refuses naming each missing receipt')
    ln.add_argument('number', type=int); ln.add_argument('lane')
    ln.add_argument('--reason', help='required for a move back: its receipt')
    ln.add_argument('--tests', help='the tests reference for the timeline line')
    ln.add_argument('--learned', help='closed only: none | lesson: … | answered: … => … | page-fix: <path>: …')
    dc = subs.add_parser('decide', parents=[log], help="record the user's answer with its question link")
    dc.add_argument('number', type=int); dc.add_argument('text')
    dc.add_argument('--question', required=True); dc.add_argument('--session')
    ak = subs.add_parser('ask', parents=[log], help='print the decision card, or record Asked for more')
    ak.add_argument('number', type=int); ak.add_argument('--kind', choices=['go', 'choice'])
    for field in ('changes', 'if_yes', 'if_no', 'if_wait', 'recommended', 'undo'):
        ak.add_argument('--' + field.replace('_', '-'), dest=field)
    ak.add_argument('--record', help='go: the action record JSON inside the working directory')
    ak.add_argument('--more', metavar='QUESTION_LINK', help='"Tell me more": record Asked for more; not a decision')
    br = subs.add_parser('brief', parents=[log], help="render the station's brief")
    br.add_argument('number', type=int)
    sw = subs.add_parser('sweep', help='the board; pulls, flushes the spool, starts review fallbacks, logs closed issues')
    sw.add_argument('--repo', required=True)
    sw.add_argument('--weekly', action='store_true', help='add the backlog-age question, question counts and knowledge digest')
    c = subs.add_parser('claim')
    c.add_argument('--repo', required=True); c.add_argument('number', type=int)
    c.add_argument('--branch', required=True)
    c.add_argument('--session', help='default: the desktop session id, else the CLI session id')
    c.add_argument('--approved', action='store_true', help="the user OK'd claiming an issue someone else filed")
    c.add_argument('--takeover', action='store_true', help="the user OK'd replacing another session's claim")
    t = subs.add_parser('tick', help="tick a ticket's acceptance criteria after its merge")
    t.add_argument('--repo', required=True); t.add_argument('number', type=int)
    t.add_argument('--evidence-file', help='versioned exact-body, per-criterion evidence JSON; required to write')
    e = subs.add_parser('prepare-evidence', help='read-only exact-body template; never infers proof')
    e.add_argument('--repo', required=True)
    target = e.add_mutually_exclusive_group(required=True)
    target.add_argument('--number', type=int); target.add_argument('--draft')
    s = subs.add_parser('status-preview', help='local native-link status text/fingerprint; never posts')
    s.add_argument('--work-record', required=True)
    s.add_argument('--previous-fingerprint', help='last confirmed update from the owned record; suppress unchanged facts')
    subs.add_parser('closes', help="print the PR body's Closes lines").add_argument('draft')
    x = subs.add_parser('close', parents=[log], help="a belt issue number: the closed lane's receipts; "
                        "a draft folder: trunk flow, close the task's open issues after the deploy record")
    x.add_argument('draft', help='issue number (belt) or draft folder (trunk flow)'); x.add_argument('--sha')
    x.add_argument('--evidence-file', help='versioned deployment and per-issue closure evidence JSON; required to write')
    x.add_argument('--learned', help='belt: none | lesson: … | answered: … => … | page-fix: <path>: …')
    args = parser.parse_args(argv)
    gh = gh or real_gh
    if args.dry_run:
        gh = DryRun(gh)
    try:
        if args.action == 'publish':
            publish(gh, args.repo, Path(args.draft), args.title, args.body_file, args.label, args.dry_run,
                    args.owner, args.domain, args.session)
        elif args.action == 'capture':
            print(capture(gh, args.repo, sys.stdin.read() if args.text == '-' else args.text, args.source, args.tag)[1])
        elif args.action == 'prio':
            print(prio(gh, args.repo, args.number, args.level, args.log))
        elif args.action == 'lane':
            print(move(gh, args.repo, args.number, args.lane, args.reason, args.log, args.tests, args.learned))
        elif args.action == 'decide':
            print(decide(gh, args.repo, args.number, args.text, args.question, args.session, args.log))
        elif args.action == 'ask':
            given = {k: getattr(args, k) for k in ('changes', 'if_yes', 'if_no', 'if_wait', 'recommended', 'undo')}
            print(ask(gh, args.repo, args.number, args.kind, given, args.record, args.log, args.more))
        elif args.action == 'brief':
            print(brief(gh, args.repo, args.number, args.log))
        elif args.action == 'sweep':
            print(sweep(gh, args.repo, args.weekly))
        elif args.action == 'close' and args.draft.isdigit():
            print(close_belt(gh, args.repo, int(args.draft), args.learned, args.log))
        elif args.action == 'close' and not args.sha:
            raise Refused('trunk-flow close needs --sha')
        elif args.action == 'claim':
            claim(gh, args.repo, args.number, args.branch, args.session, args.approved, args.takeover)
        elif args.action == 'tick':
            tick(gh, args.repo, args.number, args.evidence_file)
        elif args.action == 'close':
            close(gh, args.repo, Path(args.draft), args.sha, args.evidence_file)
        elif args.action == 'prepare-evidence':
            prepare_evidence(gh, args.repo, args.number, Path(args.draft) if args.draft else None)
        elif args.action == 'status-preview':
            result = trace_preview(json.loads(Path(args.work_record).read_text()))
            result['changed'] = result['fingerprint'] != args.previous_fingerprint
            print(json.dumps(result, indent=2))
        else:
            closes(Path(args.draft))
    except (Refused, subprocess.CalledProcessError, OSError, ValueError) as e:
        print(f'issues-cli: {getattr(e, "stderr", None) or e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
