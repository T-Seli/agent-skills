import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1] / 'skills/task-history'
sys.path.insert(0, str(SKILL))
import history
import markdown


def event(event_id, revision, kind, **fields):
    row = dict(schema_version=1, event_id=event_id, task_id='synthetic-readable-task',
        session_id='session-001', revision=revision, record_owner='writer',
        execution_owner='writer', at_utc=f'2026-10-03T00:00:0{revision}Z',
        observed_at_utc=f'2026-10-03T00:01:0{revision}Z', kind=kind,
        summary='Synthetic task', repo_ref='example/private-repo', branch_ref='feature/example',
        head_sha='a'*40, environment='local-test')
    row.update(fields)
    return row


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(['git', '-C', str(self.repo), 'init', '-q'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin',
            'https://github.com/T-Seli/agent-task-history.git'], check=True)
        self.path = self.repo / 'events/synthetic-readable-task.jsonl'

    def tearDown(self): self.temp.cleanup()

    def add(self, row):
        history.append(self.repo, row, history.digest(self.path))

    def sample(self):
        self.add(event('sample-start', 1, 'start', status='active',
            summary='Investigate a small synthetic change',
            context='The earlier allocator produced duplicate windows.',
            scope='One module only', excluded_scope='No deployment',
            open_checks=['focused-test-review', 'live rollout proof'], next_step='Run focused tests'))
        self.add(event('sample-implementation', 2, 'implementation',
            summary='Added deterministic interval allocator',
            dirty_diff_digest='b'*40, source_version='a'*40, runtime_version='synthetic-cli-1',
            implementation='Split overlapping windows and retain remaining gaps.',
            module_changes=[dict(path='availability.py', what='Add split helper',
                why='Keep allocation deterministic')],
            decision='Use Python allocation', reason='Existing SQL boundary remains stable',
            failed_approach='Recursive SQL expanded rows too far',
            evidence=[dict(state='reported', claim='Worker says focused test passed',
                ref='restricted:worker-report', sha='a'*40, environment='local-test',
                outcome='reported-pass')],
            uncertainty='Reported test has not been independently checked',
            next_step='Review test output'))
        self.add(event('sample-test', 3, 'test', summary='Focused test command completed',
            validation='15 unit tests were run locally; production behavior is untested.',
            evidence=[dict(state='performed', claim='15 unit tests passed',
                ref='restricted:test-run', sha='a'*40, environment='local-test',
                command='python3 -m unittest test_alloc', outcome='pass')],
            outcomes='No deployment occurred.', monitoring='Watch split counts after pilot rollout.'))
        self.add(event('sample-verification', 4, 'verification',
            summary='Reviewer checked the focused test result', verified_revision=3,
            resolved_checks=['focused-test-review'], next_step='Plan live rollout proof',
            evidence=[dict(state='independently_verified', claim='Focused test result checked',
                ref='restricted:review-run', sha='a'*40, environment='local-test',
                outcome='pass', verified_by='reviewer')]))

    def test_deterministic_readable_log_and_provenance(self):
        self.sample()
        rows, digest = history.snapshot(self.repo, 'synthetic-readable-task')
        state = history.project(rows, digest)
        first = markdown.document(rows, state)
        self.assertEqual(first, markdown.document(rows, state))
        for text in ('## Current overview', 'Latest activity', '## Chronological implementation log',
                     '### Context', '### Implementation', '### Decisions and alternatives',
                     '### Validation and evidence', '### Outcomes and monitoring',
                     'Reported', 'Performed', 'Recursive SQL expanded rows too far',
                     '15 unit tests', 'No deployment occurred', 'event-sample-implementation',
                     'Checks opened', 'Checks resolved', 'Verified revision', 'Dirty diff digest',
                     'Source version', 'Runtime version'):
            self.assertIn(text, first)
        self.assertIn('Independently verified', first)
        self.assertIn('**Reported:** Worker says focused test passed', first)
        self.assertIn('**Unresolved checks:**', first)
        self.assertIn('restricted:worker-report', first)
        self.assertIn('**Verified revision:** 3', first)
        self.assertIn('**Checks resolved:**\n\n- focused-test-review', first)
        self.assertIn('**Checks opened:**\n\n- focused-test-review\n- live rollout proof', first)
        self.assertIn('**Dirty diff digest:** ' + 'b'*40, first)
        self.assertIn('**Source version:** ' + 'a'*40, first)
        self.assertIn('**Runtime version:** synthetic-cli-1', first)

    def test_missing_evidence_and_markdown_escape(self):
        self.add(event('sample-start', 1, 'start', status='active',
            summary='<script>bad</script> [link](https://example.com)',
            context='## forged heading\n<script>again</script>'))
        text = markdown.document(*self.snapshot())
        self.assertIn('&lt;script&gt;', text)
        self.assertNotIn('<script>', text)
        self.assertIn('\\## forged heading', text)
        self.assertIn('none recorded for this event', text)

    def test_feedback_renders_issue_impact_and_unverified_prevention(self):
        self.add(event('sample-start', 1, 'start', status='active'))
        self.add(event('sample-feedback', 2, 'feedback', source_ref='restricted:correction',
            feedback_category='runbook_gap', feedback_issue='Stale preflight repeated',
            feedback_impact='One extra dispatch', feedback_correction='Follow current route',
            feedback_prevention_check='Compare dispatch with runbook', feedback_check_state='unverified',
            feedback_cause='Old context may have been reused', feedback_cause_basis='hypothesis',
            evidence=[dict(state='reported', claim='User reported repeated preflight', ref='restricted:correction')]))
        text = markdown.document(*self.snapshot())
        for phrase in ('### Feedback and prevention', 'Stale preflight repeated', 'One extra dispatch',
                       'Follow current route', 'Compare dispatch with runbook', 'unverified',
                       'hypothesis', '**Reported:** User reported repeated preflight'):
            self.assertIn(phrase, text)

    def snapshot(self):
        rows, digest = history.snapshot(self.repo, 'synthetic-readable-task')
        return rows, history.project(rows, digest)

    def test_write_idempotency_and_user_edit_preservation(self):
        self.sample()
        legacy = self.repo / 'tasks/legacy.md'
        legacy.parent.mkdir(); legacy.write_text('# My existing notes\n')
        result, view = markdown.write(self.repo, 'synthetic-readable-task')
        self.assertEqual(result, 'written')
        self.assertEqual(markdown.write(self.repo, 'synthetic-readable-task')[0], 'unchanged')
        self.assertEqual(stat.S_IMODE(view.stat().st_mode), 0o600)
        before = view.read_text()
        self.add(event('sample-proposal', 5, 'proposal',
            summary='Future improvement proposed', lesson_proposal='Compare against baseline before accepting.'))
        self.assertEqual(markdown.write(self.repo, 'synthetic-readable-task')[0], 'written')
        self.assertNotEqual(view.read_text(), before)
        view.write_text(view.read_text() + '\nUser note: keep this.\n')
        self.add(event('sample-handoff', 6, 'handoff', summary='Pass to next writer',
            new_record_owner='next-writer', transfer_ack_ref='restricted:ack'))
        with self.assertRaisesRegex(ValueError, 'user edits'):
            markdown.write(self.repo, 'synthetic-readable-task')
        self.assertIn('User note: keep this.', view.read_text())
        self.assertEqual(legacy.read_text(), '# My existing notes\n')
        self.assertEqual(len(history.events(self.repo, 'synthetic-readable-task')), 6)

    def test_example_matches_renderer_and_narrative_schema(self):
        self.sample()
        rows, state = self.snapshot()
        example = (SKILL / 'examples/synthetic-readable-task.md').read_text()
        self.assertEqual(example, markdown.document(rows, state))
        invalid = event('bad-event', 4, 'implementation', module_changes=[dict(path='x.py', what='changed')])
        with self.assertRaisesRegex(ValueError, 'path, what and why'):
            history.validate(invalid)
        secret = event('bad-event', 4, 'implementation', context='api_key=SECRET_VALUE')
        with self.assertRaisesRegex(ValueError, 'secret'):
            history.validate(secret)

    def test_next_step_inheritance_clear_supersede_and_terminal(self):
        self.add(event('step-start', 1, 'start', status='active', next_step='Run tests'))
        self.add(event('step-observe', 2, 'test', summary='Tests observed'))
        self.assertEqual(history.overview(self.repo, 'synthetic-readable-task')['next_step'], 'Run tests')
        self.add(event('step-clear', 3, 'decision', summary='Review complete', clear_next_step=True))
        self.assertIsNone(history.overview(self.repo, 'synthetic-readable-task')['next_step'])
        view, output = markdown.write(self.repo, 'synthetic-readable-task')
        self.assertEqual(view, 'written')
        self.assertIn('**Next-step update:** Cleared', output.read_text())
        self.assertIn('**Next step:** Run tests', output.read_text())
        self.add(event('step-new', 4, 'decision', summary='More work', next_step='Run integration'))
        self.assertEqual(history.overview(self.repo, 'synthetic-readable-task')['next_step'], 'Run integration')
        self.add(event('step-cancel', 5, 'cancellation', status='canceled', next_step='Ignore old plan'))
        self.add(event('step-late', 6, 'proposal', next_step='Stale retry'))
        self.assertIsNone(history.overview(self.repo, 'synthetic-readable-task')['next_step'])
        bad = event('bad-clear', 7, 'proposal', clear_next_step=True, next_step='Conflicting')
        with self.assertRaisesRegex(ValueError, 'clear_next_step'):
            history.validate(bad)

    def test_cli_stdout_is_read_only_and_rejects_unsafe_id(self):
        self.sample()
        command = [sys.executable, str(SKILL / 'markdown.py'), '--repo', str(self.repo),
                   'synthetic-readable-task']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('### Validation and evidence', result.stdout)
        self.assertFalse((self.repo / 'views').exists())
        result = subprocess.run(command[:-1] + ['../legacy'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__': unittest.main()
