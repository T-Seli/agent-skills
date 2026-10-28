"""Publish a task's plan and tickets as GitHub issues, then claim, tick and close them (workflow-contracts issues.md).

The draft folder stays the working copy: `plan.md` records `Issue: <owner/repo>#<n>` and each ticket line in
`action-items.md` records `issue #<n>`, so a second run creates nothing.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ITEM = re.compile(r'^- \[[ x]\] \*\*(\d+)\. (.+?)\*\*(.*)$')
PLAN_ISSUE = re.compile(r'^Issue: (\S+)#(\d+)$', re.M)
BOX = re.compile(r'^(\s*)- \[[ x]\] (.*)$')


class Refused(Exception):
    pass


def is_write(args):
    return args[:2] in (['issue', 'create'], ['issue', 'edit'], ['issue', 'comment']) or (args[0] == 'api' and '-X' in args)


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
    for sec in re.split(r'^(?=## \d+\. )', text, flags=re.M):
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


def claim(gh, repo, n, branch, session, approved):
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
    if not data['assignees']:
        gh(['issue', 'edit', str(n), '-R', repo, '--add-assignee', '@me'])
    if not any(c['author']['login'] == me and f'branch `{branch}`' in c['body'] for c in data['comments']):
        gh(['issue', 'comment', str(n), '-R', repo, '--body-file', '-'], note + '\n')
    print(f'#{n} claimed by {me}')


def tick(gh, repo, n):
    body, out, inside = view(gh, repo, n, 'body')['body'], [], False
    for line in body.split('\n'):
        if line.startswith('## '):
            inside = line.strip() == '## Acceptance criteria'
        out.append(line.replace('- [ ] ', '- [x] ', 1) if inside and BOX.match(line) else line)
    new = '\n'.join(out)
    if new != body:
        gh(['issue', 'edit', str(n), '-R', repo, '--body-file', '-'], new)
    print(f'#{n} acceptance criteria ticked')


def closes(folder):
    m = PLAN_ISSUE.search((folder / 'plan.md').read_text())
    if not m:
        raise Refused('plan.md has no Issue: line')
    items = folder / 'action-items.md'
    tickets = parse_tickets(items.read_text()) if items.exists() else []
    print('\n'.join(f'Closes #{n}' for n in [int(m[2])] + [t['issue'] for t in tickets if t['issue']]))


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
    t = subs.add_parser('tick', help="tick a ticket's acceptance criteria after its merge")
    t.add_argument('--repo', required=True); t.add_argument('number', type=int)
    subs.add_parser('closes', help="print the PR body's Closes lines").add_argument('draft')
    args = parser.parse_args(argv)
    gh = gh or real_gh
    if args.dry_run:
        gh = DryRun(gh)
    try:
        if args.action == 'publish':
            publish(gh, args.repo, Path(args.draft), args.title, args.body_file, args.label, args.dry_run)
        elif args.action == 'claim':
            claim(gh, args.repo, args.number, args.branch, args.session, args.approved)
        elif args.action == 'tick':
            tick(gh, args.repo, args.number)
        else:
            closes(Path(args.draft))
    except (Refused, subprocess.CalledProcessError) as e:
        print(f'issues-cli: {getattr(e, "stderr", None) or e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
