import copy
import json
from pathlib import Path
import tempfile
import unittest
from agent_skills.approval_attempts import collect, summarize, append_receipt, classification, validate


def fixture(**changes):
    r = dict(schema_version=1, receipt_id='receipt:1', action_id='action:1', attempt_id='attempt:1',
        retry_of=None, observed_at_utc='2026-10-16T14:00:00Z', owner='owner:1', target='task:2',
        operation=dict(name='send-coordination', scope_ref='packet:exact', scope_sha256='a'*64, revision=1),
        approval=dict(source_ref='user:1', channel='native-task', provenance='direct-user'),
        reviewer=dict(result='accepted', reason_code='none', reason_ref='tool:accepted'),
        delivery='delivered', admission='unknown', execution='not-started', verification='unknown',
        source_refs=['tool:accepted', 'user:1'])
    r.update(changes); return r


class ApprovalAttemptTests(unittest.TestCase):
    def test_duplicate_receipt_is_idempotent_not_duplicate_attempt(self):
        r = fixture(); events, result = collect([], r)
        again, result = collect(events, r)
        self.assertEqual(result, 'duplicate'); self.assertEqual(again, events)
        self.assertEqual(summarize(again)['attempt_count'], 1)
        self.assertEqual(r, fixture())

    def test_retry_separate_from_duplicate_and_no_retry_authority(self):
        first = fixture(reviewer=dict(result='rejected', reason_code='untrusted-relay', reason_ref='review:1'), delivery='not-attempted')
        retry = fixture(receipt_id='receipt:2', attempt_id='attempt:2', retry_of='attempt:1', observed_at_utc='2026-10-16T14:01:00Z')
        events, _ = collect([first], retry); report = summarize(events)
        self.assertEqual(report['attempt_count'], 2); self.assertEqual(report['action_count'], 1)
        self.assertFalse(any(x['retry_authorized'] for x in report['attempts']))
        self.assertEqual(report['attempts'][0]['classification'], 'permission-rejected')

    def test_send_success_is_not_execution_success(self):
        self.assertEqual(classification(fixture()), 'outcome-unverified')
        with self.assertRaises(ValueError): validate(fixture(verification='verified'))

    def test_permission_delivery_transport_scope_and_security_are_distinct(self):
        self.assertEqual(classification(fixture(delivery='failed')), 'permission-accepted-delivery-unresolved')
        for reason, expected in [('transport', 'transport-failure-permission-unknown'), ('stale-scope', 'stale-scope')]:
            r = fixture(reviewer=dict(result='unknown', reason_code=reason, reason_ref='tool:failure'), delivery='cancelled')
            self.assertEqual(classification(r), expected)
        r = fixture(reviewer=dict(result='rejected', reason_code='new-security-gate', reason_ref='tool:gate'), delivery='not-attempted')
        self.assertEqual(classification(r), 'new-security-gate')

    def test_denial_cannot_become_execution(self):
        denied = fixture(reviewer=dict(result='rejected', reason_code='policy-denied', reason_ref='tool:denial'), delivery='not-attempted')
        with self.assertRaises(ValueError): validate(dict(denied, execution='succeeded'))
        with self.assertRaises(ValueError): collect([denied], fixture(receipt_id='receipt:later', observed_at_utc='2026-10-16T14:01:00Z'))

    def test_scope_drift_requires_new_action(self):
        r = fixture(); changed = copy.deepcopy(r); changed.update(receipt_id='receipt:2', attempt_id='attempt:2', retry_of='attempt:1')
        changed['operation']['revision'] = 2
        with self.assertRaises(ValueError): collect([r], changed)

    def test_unknown_retry_and_identity_collision_fail(self):
        with self.assertRaises(ValueError): collect([], fixture(retry_of='attempt:absent'))
        with self.assertRaises(ValueError): collect([fixture()], fixture(delivery='failed'))

    def test_stage_progression_retains_attempt_count_and_history(self):
        first = fixture(); terminal = fixture(receipt_id='receipt:2', observed_at_utc='2026-10-16T14:01:00Z', execution='succeeded', verification='verified')
        rows, _ = collect([first], terminal)
        self.assertEqual(summarize(rows)['attempt_count'], 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(summarize(rows)['attempts'][0]['classification'], 'execution-verified')
        with self.assertRaises(ValueError): collect(rows, fixture(receipt_id='receipt:3', observed_at_utc='2026-10-16T14:02:00Z'))

    def test_raw_payload_fields_and_invalid_clock_rejected(self):
        with self.assertRaises(ValueError): validate(fixture(raw_output='sensitive'))
        with self.assertRaises(ValueError): validate(fixture(observed_at_utc='2026-10-16T14:00:00'))

    def test_explicit_local_append_and_cli_report(self):
        from agent_skills.safeguard_cli import main
        import io, contextlib
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'receipts.jsonl'; receipt=Path(root)/'receipt.json'; receipt.write_text(json.dumps(fixture()))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['approval-record', str(path), str(receipt)]), 0)
                self.assertEqual(main(['approval-record', str(path), str(receipt)]), 0)
                self.assertEqual(main(['approval-report', str(path)]), 0)
            self.assertEqual(len(path.read_text().splitlines()), 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_concurrent_duplicate_append_and_corruption_are_safe(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'attempts.jsonl'
            with ThreadPoolExecutor(max_workers=3) as pool:
                states = list(pool.map(lambda _: append_receipt(path, fixture())['state'], range(6)))
            self.assertEqual(states.count('appended'), 1)
            self.assertEqual(states.count('duplicate'), 5)
            with path.open('a') as stream: stream.write('{incomplete')
            before = path.read_bytes()
            with self.assertRaises(ValueError): append_receipt(path, fixture(receipt_id='receipt:2'))
            self.assertEqual(path.read_bytes(), before)

    def test_existing_runner_metadata_collection_never_reads_streams(self):
        from agent_skills.approval_attempts import execution_observation
        class Result:
            state='done'; returncode=0; finished_at_utc='2026-10-16T14:01:00Z'
            @property
            def stdout(self): raise AssertionError('must not read raw output')
            @property
            def stderr(self): raise AssertionError('must not read raw output')
        result=Result()
        receipt=execution_observation(fixture(), result, receipt_id='receipt:2', source_ref='process:result')
        self.assertEqual(receipt['execution'], 'succeeded')
        self.assertEqual(receipt['verification'], 'pending')
        result.state='uncertain'; result.returncode=-15
        receipt=execution_observation(fixture(), result, receipt_id='receipt:2', source_ref='process:timeout')
        self.assertEqual(receipt['execution'], 'unknown')
        result.state='failed'; result.returncode=2
        self.assertEqual(execution_observation(fixture(), result, receipt_id='receipt:3', source_ref='process:failure')['execution'], 'failed')
