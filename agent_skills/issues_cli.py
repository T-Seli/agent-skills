"""Publish a task's plan and tickets as GitHub issues, then claim, tick and close them (workflow-contracts issues.md).

The draft folder stays the working copy: `plan.md` records `Issue: <owner/repo>#<n>` and each ticket line in
`action-items.md` records `issue #<n>`, so a second run creates nothing.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from .work_trace import validate as validate_work_trace, preview as trace_preview

ITEM = re.compile(r'^- \[[ x]\] \*\*(\d+)\. (.+?)\*\*(.*)$')
PLAN_ISSUE = re.compile(r'^Issue: (\S+)#(\d+)$', re.M)
BOX = re.compile(r'^(\s*)- \[[ x]\] (.*)$')


class Refused(Exception):
    pass


def is_write(args):
    return args[:2] in (['issue', 'create'], ['issue', 'edit'], ['issue', 'comment'], ['issue', 'close']) or (args[0] == 'api' and '-X' in args)


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


def publish(gh, repo, folder, title, body_file, label, dry_run):
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
    if m:
        parent = int(m[2])
    else:
        parent = create(gh, repo, title, Path(body_file).read_text(), label)
        head, _, rest = plan.partition('\n')
        plan = f'{head}\nIssue: {repo}#{parent}\n{rest}'
        dry_run or plan_path.write_text(plan)
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
    """The session holding the issue: the latest claim note whose session did not later post a `Released:` note."""
    held = []
    for c in comments:
        body = c['body'].strip()
        if claim_session(body):
            held.append(claim_session(body))
        elif body.startswith('Released:') and (m := re.search(r'session (\S+)', body)):
            held = [x for x in held if x != m[1]]
    return held[-1] if held else None


def claim(gh, repo, n, branch, session, approved, takeover=False):
    session = session or os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or os.environ.get('CLAUDE_CODE_SESSION_ID')
    if not session:
        raise Refused('no session id in the environment; pass --session')
    me = gh(['api', 'user', '--jq', '.login']).strip()
    data = view(gh, repo, n, 'assignees,author,comments')
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


def main(argv=None, gh=None):
    parser = argparse.ArgumentParser(prog='issues-cli')
    parser.add_argument('--dry-run', action='store_true', help='print every write instead of making it')
    subs = parser.add_subparsers(dest='action', required=True)
    p = subs.add_parser('publish', help="the plan's issue, then one sub-issue per ticket")
    p.add_argument('--repo', required=True); p.add_argument('draft')
    p.add_argument('--title'); p.add_argument('--body-file'); p.add_argument('--label')
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
    x = subs.add_parser('close', help="trunk flow: close the task's open issues after the deploy record")
    x.add_argument('--repo', required=True); x.add_argument('draft'); x.add_argument('--sha', required=True)
    x.add_argument('--evidence-file', help='versioned deployment and per-issue closure evidence JSON; required to write')
    args = parser.parse_args(argv)
    gh = gh or real_gh
    if args.dry_run:
        gh = DryRun(gh)
    try:
        if args.action == 'publish':
            publish(gh, args.repo, Path(args.draft), args.title, args.body_file, args.label, args.dry_run)
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
