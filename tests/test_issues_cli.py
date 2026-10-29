"""issues-cli: publish a task's plan and tickets as GitHub issues, claim, tick and close them."""
import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from agent_skills import issues_cli

REPO = 'o/r'
PLAN = '# Plan: add widgets\n\nBase: main\n'
ITEMS = """Revision: r1 · settled D1 · owner orchestration
Tickets: 3

- [ ] **1. Store widgets** · M
  - Why: nothing keeps them today.
  - Where: `server/widgets.js`
  - Done when:
    - [ ] a saved widget reads back
- [ ] **2. Show widgets** · S · after #1
  - Done when:
    - [ ] the list shows a saved widget
    - [ ] an empty list says so
- [ ] **3. Count widgets** · S · after #1, #2
  - Done when: the badge shows the count

**Decisions / blockers**
- [ ] Decide 1: colour (default: grey)
"""
TEXT = """# Issue text

## 1. Keep saved widgets
Widgets people save are kept, so they are still there next time.

- [ ] A saved widget is still there after a reload.

## 2. Show saved widgets
People see the widgets they saved.

- [ ] The list shows a saved widget.
- [ ] An empty list says there are none yet.

## 3. Count saved widgets
A badge shows how many widgets are saved.

- [ ] The badge matches the list.

## Notes for reviewers
Shared context that belongs to no ticket.
- [ ] an open question
"""


class FakeGh:
    """Records every call and the links it was asked to make; issue numbers start at 100 and an issue's id is its
    number × 1000. `fail` names a call (by predicate) that raises once, as gh does on an API error."""
    def __init__(self, issues=None, viewer='me', fail=None):
        self.calls, self.next, self.issues, self.viewer, self.fail = [], 100, issues or {}, viewer, fail
        self.links = {}  # 'repos/o/r/issues/<n>/<sub_issues|dependencies/blocked_by>' -> [linked numbers]

    def __call__(self, args, stdin=None):
        self.calls.append((args, stdin))
        if self.fail and self.fail(args):
            self.fail = None
            raise subprocess.CalledProcessError(1, ['gh', *args], stderr='HTTP 502: Bad Gateway')
        if args[:2] == ['issue', 'create']:
            self.next += 1
            return f'https://github.com/{REPO}/issues/{self.next - 1}\n'
        if args[:2] == ['api', 'user']:
            return self.viewer + '\n'
        if args[0] == 'api' and re.fullmatch(rf'repos/{REPO}/issues/\d+', args[1]):
            return f"{int(args[1].rsplit('/', 1)[1]) * 1000}\n"
        if args[:3] == ['api', '-X', 'POST']:
            self.links.setdefault(args[3], []).append(int(args[-1].split('=')[1]) // 1000)
            return '{}'
        if args[0] == 'api':
            return ''.join(f'{n}\n' for n in self.links.get(args[1], []))
        if args[:2] == ['issue', 'view']:
            return json.dumps(self.issues[int(args[2])])
        return ''

    def writes(self):
        return [(a, s) for a, s in self.calls if issues_cli.is_write(a)]


def draft(plan=PLAN, items=ITEMS, text=TEXT):
    d = Path(tempfile.mkdtemp())
    (d / 'plan.md').write_text(plan)
    if items is not None:
        (d / 'action-items.md').write_text(items)
    if text is not None:
        (d / 'issue-text.md').write_text(text)
    return d


def run(gh, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = issues_cli.main(list(argv), gh=gh)
    return code, out.getvalue(), err.getvalue()


def spec_body():
    f = Path(tempfile.mkdtemp()) / 'spec.md'
    f.write_text('## Problem Statement\n\nNo widgets.\n')
    return str(f)


class Publish(unittest.TestCase):
    def test_spec_then_tickets_as_sub_issues_with_blocked_by(self):
        d, gh = draft(), FakeGh()
        code, out, _ = run(gh, 'publish', '--repo', REPO, str(d), '--title', 'Spec: widgets',
                           '--body-file', spec_body(), '--label', 'ready-for-agent')
        self.assertEqual(code, 0)
        creates = [(a, s) for a, s in gh.writes() if a[:2] == ['issue', 'create']]
        self.assertEqual(len(creates), 4)
        self.assertIn('--label', creates[0][0])
        self.assertEqual([a[a.index('--title') + 1] for a, _ in creates],
                         ['Spec: widgets', 'Keep saved widgets', 'Show saved widgets', 'Count saved widgets'])
        t2 = creates[2][1]
        for part in ('## Parent\n\n#100', '## What to build\n\nPeople see the widgets they saved.',
                     '## Acceptance criteria\n\n- [ ] The list shows a saved widget.\n- [ ] An empty list says there are none yet.',
                     '## Blocked by\n\n- #101'):
            self.assertIn(part, t2)
        for body in [s for _, s in creates[1:]]:  # the session's text only, never the worker ticket (issues.md § Format)
            self.assertNotIn('server/widgets.js', body)
            self.assertNotIn('nothing keeps them today', body)
        self.assertIn('- [ ] The badge matches the list.', creates[3][1])
        self.assertNotIn('Notes for reviewers', creates[3][1])  # another heading ends a ticket's section
        self.assertNotIn('open question', creates[3][1])
        self.assertIn('None: can start now.', creates[1][1])
        posts = [a for a, _ in gh.writes() if a[0] == 'api']
        subs = [a for a in posts if a[3].endswith('/sub_issues')]
        self.assertEqual([a[3] for a in subs], [f'repos/{REPO}/issues/100/sub_issues'] * 3)
        self.assertEqual([a[-1] for a in subs], ['sub_issue_id=101000', 'sub_issue_id=102000', 'sub_issue_id=103000'])
        blocks = [(a[3], a[-1]) for a in posts if a[3].endswith('/blocked_by')]
        self.assertEqual(blocks, [(f'repos/{REPO}/issues/102/dependencies/blocked_by', 'issue_id=101000'),
                                  (f'repos/{REPO}/issues/103/dependencies/blocked_by', 'issue_id=101000'),
                                  (f'repos/{REPO}/issues/103/dependencies/blocked_by', 'issue_id=102000')])
        self.assertIn(f'Issue: {REPO}#100', (d / 'plan.md').read_text())
        items = (d / 'action-items.md').read_text()
        self.assertIn('**2. Show widgets** · S · after #1 · issue #102', items)
        self.assertIn('#100', out)

    def test_republish_creates_nothing(self):
        d, gh = draft(), FakeGh()
        run(gh, 'publish', '--repo', REPO, str(d), '--title', 'T', '--body-file', spec_body())
        before = len(gh.calls)
        code, _, _ = run(gh, 'publish', '--repo', REPO, str(d))
        self.assertEqual(code, 0)
        self.assertEqual([a for a, _ in gh.calls[before:] if issues_cli.is_write(a)], [])

    def test_partly_published_reuses_existing_issue_numbers(self):
        items = ITEMS.replace('**1. Store widgets** · M', '**1. Store widgets** · M · issue #50')
        d, gh = draft(plan=f'# Plan: add widgets\nIssue: {REPO}#40\n', items=items,
                      text=TEXT.replace('## 1.', '## 9.')), FakeGh()  # a published ticket needs no issue text
        code, _, _ = run(gh, 'publish', '--repo', REPO, str(d))
        self.assertEqual(code, 0)
        creates = [s for a, s in gh.writes() if a[:2] == ['issue', 'create']]
        self.assertEqual(len(creates), 2)
        self.assertIn('## Parent\n\n#40', creates[0])
        self.assertIn('## What to build\n\nPeople see the widgets they saved.', creates[0])
        self.assertIn('## Blocked by\n\n- #50', creates[0])
        self.assertIn((f'repos/{REPO}/issues/100/dependencies/blocked_by', 'issue_id=50000'),
                      [(a[3], a[-1]) for a, _ in gh.writes() if a[0] == 'api'])

    def test_rerun_after_a_failed_link_adds_the_link_and_creates_nothing(self):
        d = draft()
        gh = FakeGh(fail=lambda a: a[:3] == ['api', '-X', 'POST'] and a[3].endswith('/issues/102/dependencies/blocked_by'))
        code, _, err = run(gh, 'publish', '--repo', REPO, str(d), '--title', 'T', '--body-file', spec_body())
        self.assertEqual(code, 1)
        self.assertIn('502', err)
        self.assertIn('**2. Show widgets** · S · after #1 · issue #102', (d / 'action-items.md').read_text())
        before = len(gh.calls)
        code, _, _ = run(gh, 'publish', '--repo', REPO, str(d))
        self.assertEqual(code, 0)
        rerun_creates = [a[a.index('--title') + 1] for a, _ in gh.calls[before:] if a[:2] == ['issue', 'create']]
        self.assertEqual(rerun_creates, ['Count saved widgets'])  # only the ticket never reached; #101 and #102 not repeated
        self.assertEqual(sorted(gh.links[f'repos/{REPO}/issues/100/sub_issues']), [101, 102, 103])
        self.assertEqual(gh.links[f'repos/{REPO}/issues/102/dependencies/blocked_by'], [101])
        self.assertEqual(sorted(gh.links[f'repos/{REPO}/issues/103/dependencies/blocked_by']), [101, 102])

    def test_single_task_without_tickets_gets_one_issue(self):
        d, gh = draft(items=None), FakeGh()
        code, _, _ = run(gh, 'publish', '--repo', REPO, str(d), '--title', 'Fix X', '--body-file', spec_body())
        self.assertEqual(code, 0)
        self.assertEqual(len(gh.writes()), 1)

    def test_fails_loudly_before_any_write(self):
        cases = [
            (draft(items=ITEMS.replace('after #1, #2', 'after #9')), ('--title', 'T', '--body-file', spec_body())),
            (draft(), ()),  # no spec issue yet and no title/body to create it
            (draft(plan=f'# Plan\nIssue: other/repo#4\n'), ()),
            (draft(text=None), ('--title', 'T', '--body-file', spec_body())),  # tickets need the session's issue text
            (draft(text=TEXT.split('## 3.')[0]), ('--title', 'T', '--body-file', spec_body())),
            (draft(text=TEXT.replace('- [ ] The badge matches the list.', '')), ('--title', 'T', '--body-file', spec_body())),
        ]
        for d, extra in cases:
            gh = FakeGh()
            code, _, err = run(gh, 'publish', '--repo', REPO, str(d), *extra)
            self.assertNotEqual(code, 0)
            self.assertTrue(err.strip())
            self.assertEqual(gh.writes(), [])

    def test_dry_run_prints_writes_and_changes_nothing(self):
        d, gh = draft(), FakeGh()
        before = (d / 'plan.md').read_text(), (d / 'action-items.md').read_text()
        code, out, _ = run(gh, '--dry-run', 'publish', '--repo', REPO, str(d), '--title', 'T', '--body-file', spec_body())
        self.assertEqual(code, 0)
        self.assertEqual(gh.writes(), [])
        self.assertEqual(out.count('gh issue create'), 4)
        self.assertIn('/dependencies/blocked_by', out)
        self.assertEqual(((d / 'plan.md').read_text(), (d / 'action-items.md').read_text()), before)


def issue(assignees=(), author='me', comments=(), body=''):
    return {'assignees': [{'login': a} for a in assignees], 'author': {'login': author},
            'comments': [{'author': {'login': 'me'}, 'body': c} for c in comments], 'body': body}


class Claim(unittest.TestCase):
    def claim(self, data, *extra):
        gh = FakeGh(issues={7: data})
        code, out, err = run(gh, 'claim', '--repo', REPO, '7', '--branch', 'feat/x', '--session', 's1', *extra)
        return code, gh.writes(), err

    def test_unassigned_own_issue_is_assigned_and_commented(self):
        code, writes, _ = self.claim(issue())
        self.assertEqual(code, 0)
        self.assertEqual(writes[0][0], ['issue', 'edit', '7', '-R', REPO, '--add-assignee', '@me'])
        self.assertEqual(writes[1][0][:2], ['issue', 'comment'])
        self.assertIn('`feat/x`', writes[1][1])
        self.assertIn('s1', writes[1][1])

    def test_someone_elses_assignment_is_refused(self):
        code, writes, err = self.claim(issue(assignees=['hayk']), '--approved')
        self.assertNotEqual(code, 0)
        self.assertEqual(writes, [])
        self.assertIn('hayk', err)

    def test_issue_filed_by_someone_else_needs_approval(self):
        code, writes, err = self.claim(issue(author='hayk'))
        self.assertNotEqual(code, 0)
        self.assertEqual(writes, [])
        code, writes, _ = self.claim(issue(author='hayk'), '--approved')
        self.assertEqual(code, 0)
        self.assertEqual(len(writes), 2)

    def test_repeat_claim_writes_nothing(self):
        code, writes, _ = self.claim(issue(assignees=['me'], comments=['Claimed: branch `feat/x` · session s1']))
        self.assertEqual(code, 0)
        self.assertEqual(writes, [])


    def test_session_defaults_to_the_desktop_session_id(self):
        gh = FakeGh(issues={7: issue()})
        env = {'CLAUDE_CODE_HOST_SESSION_ID': 'local_abc', 'CLAUDE_CODE_SESSION_ID': 'cli-123'}
        with unittest.mock.patch.dict(os.environ, env):
            code, _, _ = run(gh, 'claim', '--repo', REPO, '7', '--branch', 'feat/x')
        self.assertEqual(code, 0)
        self.assertIn('session local_abc', gh.writes()[1][1])

    def test_session_falls_back_to_the_cli_id_and_fails_without_either(self):
        gh = FakeGh(issues={7: issue()})
        with unittest.mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': 'cli-123'}):
            os.environ.pop('CLAUDE_CODE_HOST_SESSION_ID', None)
            self.assertEqual(run(gh, 'claim', '--repo', REPO, '7', '--branch', 'feat/x')[0], 0)
        self.assertIn('session cli-123', gh.writes()[1][1])
        gh = FakeGh(issues={7: issue()})
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            code, _, err = run(gh, 'claim', '--repo', REPO, '7', '--branch', 'feat/x')
        self.assertNotEqual(code, 0)
        self.assertIn('--session', err)
        self.assertEqual(gh.writes(), [])


class Tick(unittest.TestCase):
    BODY = ('## Parent\n\n#1\n\n## What to build\n\n- [ ] not a criterion\n\n'
            '## Acceptance criteria\n\n- [ ] one\n- [x] two\n- [ ] three\n\n## Blocked by\n\n- [ ] other\n')

    def test_ticks_only_acceptance_criteria(self):
        gh = FakeGh(issues={8: issue(body=self.BODY)})
        code, _, _ = run(gh, 'tick', '--repo', REPO, '8')
        self.assertEqual(code, 0)
        (args, body), = gh.writes()
        self.assertEqual(args, ['issue', 'edit', '8', '-R', REPO, '--body-file', '-'])
        self.assertIn('## Acceptance criteria\n\n- [x] one\n- [x] two\n- [x] three', body)
        self.assertIn('- [ ] not a criterion', body)
        self.assertIn('- [ ] other', body)

    def test_nothing_to_tick_writes_nothing(self):
        gh = FakeGh(issues={8: issue(body='## Acceptance criteria\n\n- [x] one\n')})
        self.assertEqual(run(gh, 'tick', '--repo', REPO, '8')[0], 0)
        self.assertEqual(gh.writes(), [])


class Close(unittest.TestCase):
    """Trunk flow has no PR to close issues: after the deploy record, the session closes the task's own issues."""
    def published(self):
        d = draft()
        run(FakeGh(), 'publish', '--repo', REPO, str(d), '--title', 'T', '--body-file', spec_body())
        return d  # spec #100, tickets #101-#103

    def test_closes_every_open_task_issue_with_the_deployed_sha(self):
        states = {100: 'OPEN', 101: 'CLOSED', 102: 'OPEN', 103: 'OPEN'}
        gh = FakeGh(issues={n: {'state': st} for n, st in states.items()})
        code, out, _ = run(gh, 'close', '--repo', REPO, str(self.published()), '--sha', 'abc1234')
        self.assertEqual(code, 0)
        closed = [(a[2], a[a.index('--comment') + 1]) for a, _ in gh.writes()]
        self.assertEqual(closed, [('102', 'Deployed in abc1234.'), ('103', 'Deployed in abc1234.'),
                                  ('100', 'Deployed in abc1234.')])  # tickets first, the spec last
        self.assertTrue(all(a[:2] == ['issue', 'close'] for a, _ in gh.writes()))

    def test_refuses_an_untracked_or_foreign_plan_before_any_write(self):
        for d in (draft(), draft(plan='# Plan\nIssue: other/repo#4\n')):
            gh = FakeGh()
            code, _, err = run(gh, 'close', '--repo', REPO, str(d), '--sha', 'abc1234')
            self.assertNotEqual(code, 0)
            self.assertTrue(err.strip())
            self.assertEqual(gh.writes(), [])

    def test_dry_run_prints_the_closes(self):
        gh = FakeGh(issues={n: {'state': 'OPEN'} for n in (100, 101, 102, 103)})
        code, out, _ = run(gh, '--dry-run', 'close', '--repo', REPO, str(self.published()), '--sha', 'abc1234')
        self.assertEqual(code, 0)
        self.assertEqual(gh.writes(), [])
        self.assertEqual(out.count('gh issue close'), 4)


class Closes(unittest.TestCase):
    def test_lists_the_spec_and_every_ticket(self):
        d = draft()
        run(FakeGh(), 'publish', '--repo', REPO, str(d), '--title', 'T', '--body-file', spec_body())
        code, out, _ = run(FakeGh(), 'closes', str(d))
        self.assertEqual(code, 0)
        self.assertEqual(out.split('\n')[:4], ['Closes #100', 'Closes #101', 'Closes #102', 'Closes #103'])


if __name__ == '__main__':
    unittest.main()
