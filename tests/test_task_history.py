import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'skills/task-history/history.py'
spec = importlib.util.spec_from_file_location('task_history', MODULE)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


def packet(event='event-001', revision=1, kind='start', owner='owner'):
    row = dict(schema_version=1, event_id=event, task_id='task-001', session_id='session-001',
               revision=revision, record_owner=owner, at_utc='2026-10-03T00:00:00Z',
               observed_at_utc='2026-10-03T00:01:00Z', kind=kind, summary='Task started')
    if kind == 'start': row['status'] = 'active'
    return row


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(['git', '-C', str(self.repo), 'init', '-q'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin', 'https://github.com/T-Seli/agent-task-history.git'], check=True)
        self.path = self.repo / 'events/task-001.jsonl'

    def tearDown(self): self.temp.cleanup()

    def add(self, row):
        return history.append(self.repo, row, history.digest(self.path))

    def test_schema_matches_validator_fields(self):
        schema = json.loads((MODULE.parent / 'schema.json').read_text())
        self.assertEqual(set(schema['properties']), history.FIELDS)
        self.assertEqual(set(schema['required']), history.REQUIRED)
        self.assertEqual(set(schema['properties']['kind']['enum']), history.KINDS)

    def test_coordination_milestone_example_matches_the_live_validator(self):
        example = json.loads((MODULE.parent / 'examples/coordination-milestone.json').read_text())
        history.validate(example)
        self.assertEqual(example['kind'], 'decision')
        self.assertEqual(example['evidence'][0]['state'], 'performed')

    def test_retry_collision_stale_and_handoff(self):
        empty = history.digest(self.path)
        first = packet()
        result, digest = self.add(first)
        self.assertEqual(result, 'appended')
        self.assertEqual(history.append(self.repo, first, empty), ('duplicate', digest))
        changed = packet(); changed['summary'] = 'different'
        with self.assertRaisesRegex(ValueError, 'collision'): self.add(changed)
        second = packet('event-002', 2, 'handoff'); second.update(new_record_owner='new-owner', transfer_ack_ref='restricted:ack')
        with self.assertRaisesRegex(ValueError, 'stale history digest'): history.append(self.repo, second, empty)
        self.add(second)
        with self.assertRaisesRegex(ValueError, 'stale record owner'): self.add(packet('event-003', 3, 'decision'))
        third = packet('event-003', 3, 'decision', 'new-owner'); self.add(third)
        self.assertEqual(history.overview(self.repo, 'task-001')['record_owner'], 'new-owner')

    def test_cli_traversal_and_symlink(self):
        self.add(packet())
        for task in ('../task-001', '/tmp/escape'):
            result = subprocess.run([sys.executable, str(MODULE), '--repo', str(self.repo), 'view', task, '--events'], capture_output=True)
            self.assertEqual(result.returncode, 2)
        (self.repo / 'events/evil.jsonl').symlink_to(self.path)
        result = subprocess.run([sys.executable, str(MODULE), '--repo', str(self.repo), 'view', 'evil', '--events'], capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_state_projection_and_checks(self):
        first = packet(); first['open_checks'] = ['deploy confirmation']; self.add(first)
        cancel = packet('event-002', 2, 'cancellation'); cancel['status'] = 'canceled'; cancel['summary'] = 'Canceled by user'; self.add(cancel)
        late = packet('event-003', 3, 'proposal'); late['lesson_proposal'] = 'Review handoff'; self.add(late)
        view = history.overview(self.repo, 'task-001')
        self.assertEqual((view['status'], view['current'], view['open_checks']), ('canceled', 'Canceled by user', ['deploy confirmation']))

    def test_strict_validation(self):
        for change in ({'at_utc': '2026-99-99T99:99:99Z'}, {'summary': ['bad']}, {'files': [{}]},
                       {'kind': 'verification'}, {'schema_version': 2}):
            row = packet(); row.update(change)
            with self.assertRaises(ValueError): history.validate(row)
        row = packet(); row['summary'] = 'No customer payload was copied'; history.validate(row)
        row = packet('event-002', 2, 'verification'); row['head_sha'] = 'a'*40; row['verified_revision'] = 1; row['environment'] = 'local'; row['execution_owner'] = 'worker'
        row['evidence'] = [dict(state='independently_verified', claim='passed', ref='restricted:run',
                                sha='b'*40, environment='local', outcome='pass', verified_by='reviewer')]
        with self.assertRaisesRegex(ValueError, 'match'): history.validate(row)
        row['evidence'][0]['sha'] = 'a'*40; history.validate(row)

    def test_feedback_requires_provenance_correction_and_check_state(self):
        self.add(packet())
        feedback = packet('event-002', 2, 'feedback')
        feedback.update(source_ref='restricted:user-correction', feedback_category='scope_drift',
                        feedback_issue='Worker answered an adjacent task',
                        feedback_impact='One re-dispatch was needed',
                        feedback_correction='Return to the assigned task',
                        feedback_prevention_check='Compare returned answer with dispatch goal',
                        feedback_check_state='unverified',
                        evidence=[dict(state='reported', claim='User corrected the scope', ref='restricted:user-correction')])
        history.validate(feedback)
        self.add(feedback)
        self.assertEqual(history.overview(self.repo, 'task-001')['status'], 'active')
        for missing in ('source_ref', 'feedback_issue', 'feedback_correction', 'evidence'):
            incomplete = dict(feedback)
            incomplete.pop(missing)
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'feedback needs'):
                history.validate(incomplete)
        for changes, error in (({'source_ref': None}, 'feedback needs'),
                               ({'feedback_cause': 'Maybe stale context'}, 'cause needs'),
                               ({'feedback_check_state': 'verified_pass'}, 'needs a reference'),
                               ({'feedback_check_ref': 'restricted:test'}, 'cannot claim'),
                               ({'feedback_category': []}, 'invalid feedback category'),
                               ({'feedback_cause': 'Canceled tool caused the delay', 'feedback_cause_basis': 'observed'},
                                'observed feedback cause needs'),
                               ({'status': 'blocked'}, 'status is not allowed'),
                               ({'resolved_checks': ['review']}, 'checks may be resolved')):
            bad = dict(feedback, **changes)
            if changes.get('source_ref') is None and 'source_ref' in changes: bad.pop('source_ref')
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, error):
                history.validate(bad)
        reported_check = dict(feedback, feedback_check_state='verified_pass',
                              feedback_check_ref='restricted:check',
                              evidence=[dict(state='reported', claim='Worker says check passed',
                                             ref='restricted:check', outcome='pass')])
        with self.assertRaisesRegex(ValueError, 'performed evidence'):
            history.validate(reported_check)
        wrong_ref = dict(reported_check, evidence=[dict(state='performed', claim='Check ran',
            ref='restricted:other-check', outcome='pass')])
        with self.assertRaisesRegex(ValueError, 'performed evidence'):
            history.validate(wrong_ref)
        wrong_outcome = dict(reported_check, evidence=[dict(state='performed', claim='Check failed',
            ref='restricted:check', outcome='fail')])
        with self.assertRaisesRegex(ValueError, 'performed evidence'):
            history.validate(wrong_outcome)
        checked = packet('event-003', 3, 'feedback')
        checked.update({**{k: v for k, v in feedback.items() if k.startswith('feedback_')},
                        'source_ref': 'restricted:check', 'correction_of': 'event-002',
                        'feedback_check_state': 'verified_pass', 'feedback_check_ref': 'restricted:check',
                        'feedback_cause': 'Dispatch omitted target', 'feedback_cause_basis': 'hypothesis',
                        'evidence': [dict(state='performed', claim='Scoped return check passed',
                                          ref='restricted:check', outcome='pass')]})
        self.add(checked)
        self.assertEqual(len(history.events(self.repo, 'task-001')), 3)
        bad = packet('event-004', 4, 'decision'); bad['feedback_issue'] = 'wrong kind'
        with self.assertRaisesRegex(ValueError, 'only allowed'): history.validate(bad)

    def test_feedback_example_packet_is_valid(self):
        path = MODULE.parent / 'examples/feedback-event.json'
        history.validate(json.loads(path.read_text()))

    def test_schema_requires_feedback_fields_and_performed_check_evidence(self):
        schema = json.loads((MODULE.parent / 'schema.json').read_text())
        feedback_rule = next(x['then'] for x in schema['allOf'] if
            x.get('if', {}).get('properties', {}).get('kind', {}).get('const') == 'feedback'
            and 'feedback_check_state' not in x['if']['properties'])
        self.assertTrue({'source_ref', 'feedback_issue', 'feedback_correction', 'evidence'}
                        <= set(feedback_rule['required']))
        self.assertEqual(feedback_rule['properties']['evidence']['minItems'], 1)
        if importlib.util.find_spec('jsonschema') is None:
            return
        import jsonschema
        valid = json.loads((MODULE.parent / 'examples/feedback-event.json').read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(valid, schema)
        for missing in ('source_ref', 'feedback_issue', 'feedback_correction', 'evidence'):
            bad = dict(valid); bad.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)
        reported = dict(valid, feedback_check_state='verified_pass', feedback_check_ref='restricted:check',
                        evidence=[dict(state='reported', claim='Claimed pass', ref='restricted:check', outcome='pass')])
        with self.assertRaises(jsonschema.ValidationError): jsonschema.validate(reported, schema)
        performed = dict(reported, evidence=[dict(state='performed', claim='Check passed',
                                                  ref='restricted:check', outcome='pass')])
        jsonschema.validate(performed, schema)

    def test_corrupt_replay_and_identity(self):
        self.add(packet())
        with self.path.open('a') as out: out.write('{bad')
        with self.assertRaisesRegex(ValueError, 'incomplete history tail'): history.events(self.repo, 'task-001')
        self.assertIn('event-001', self.path.read_text())
        self.path.write_text(json.dumps({**packet(), 'task_id': 'other'}) + '\n')
        with self.assertRaisesRegex(ValueError, 'identity'): history.events(self.repo, 'task-001')

    def test_concurrent_distinct_events_do_not_overwrite(self):
        self.add(packet()); expected = history.digest(self.path)
        barrier = threading.Barrier(2); outcomes = []
        def write(name):
            barrier.wait()
            try: outcomes.append(history.append(self.repo, packet(name, 2, 'decision'), expected)[0])
            except ValueError as exc: outcomes.append(str(exc))
        threads = [threading.Thread(target=write, args=(f'event-00{x}',)) for x in (2, 3)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(outcomes.count('appended'), 1)
        self.assertEqual(len(history.events(self.repo, 'task-001')), 2)

    def test_verification_revision_binding(self):
        first = packet(); first.update(head_sha='a'*40, environment='local', execution_owner='worker')
        self.add(first)
        row = packet('event-002', 2, 'verification'); row['head_sha'] = 'a'*40
        row['verified_revision'] = 1; row['environment'] = 'local'; row['execution_owner'] = 'worker'
        row['evidence'] = [dict(state='independently_verified', claim='passed', ref='restricted:run',
                                sha='a'*40, environment='local', outcome='pass', verified_by='reviewer')]
        self.add(row)
        stale = packet('event-003', 3, 'verification'); stale.update(head_sha='a'*40, environment='local',
            verified_revision=1, evidence=row['evidence'])
        with self.assertRaisesRegex(ValueError, 'stale revision'): self.add(stale)

    def test_transition_replay_rejects_nonstart_and_reopen(self):
        bad = packet(kind='decision')
        with self.assertRaisesRegex(ValueError, 'first event'): self.add(bad)
        self.path.parent.mkdir(mode=0o700, exist_ok=True)
        self.path.write_text(json.dumps(bad) + '\n')
        self.path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'line 1 event'): history.events(self.repo, 'task-001')
        self.path.unlink()
        first = packet(); first['next_step'] = 'deploy'; self.add(first)
        cancel = packet('event-002', 2, 'cancellation'); cancel['status'] = 'canceled'; self.add(cancel)
        proposed = packet('event-003', 3, 'proposal'); proposed['next_step'] = 'retry deploy'; self.add(proposed)
        self.assertIsNone(history.overview(self.repo, 'task-001')['next_step'])
        reopen = packet('event-004', 4, 'decision'); reopen['status'] = 'active'
        with self.assertRaisesRegex(ValueError, 'terminal'): self.add(reopen)
        with self.path.open('a') as handle: handle.write(json.dumps(reopen) + '\n')
        with self.assertRaisesRegex(ValueError, 'line 4 event'): history.events(self.repo, 'task-001')

    def test_verification_binds_prior_code_and_independent_actor(self):
        first = packet(); first.update(head_sha='a'*40, environment='local', execution_owner='worker')
        self.add(first)
        def verify(event, sha='a'*40, verifier='reviewer', outcome='pass'):
            row = packet(event, 2, 'verification')
            row.update(head_sha=sha, environment='local', verified_revision=1,
                evidence=[dict(state='independently_verified', claim='suite', ref='restricted:run',
                    sha=sha, environment='local', outcome=outcome, verified_by=verifier)])
            return row
        with self.assertRaisesRegex(ValueError, 'target code identity'): self.add(verify('event-002', 'b'*40))
        with self.assertRaisesRegex(ValueError, 'not independent'): self.add(verify('event-002', verifier='worker'))
        good = verify('event-002'); self.add(good)
        close = packet('event-003', 3, 'close'); close.update(status='done', head_sha='a'*40,
            environment='local', verified_revision=2, approval_ref='restricted:approval',
            evidence=good['evidence'])
        with self.assertRaisesRegex(ValueError, 'unknown code identity'): self.add(close)
        good['execution_owner'] = 'worker'
        # Preserve append-only history: a new task is used for the successful close path.
        self.path.unlink()
        self.add(first); self.add(good); self.add(close)
        self.assertEqual(history.overview(self.repo, 'task-001')['status'], 'done')

    def test_done_requires_close_and_success(self):
        first = packet(); first.update(head_sha='a'*40, environment='local', execution_owner='worker')
        self.add(first)
        decision = packet('event-002', 2, 'decision'); decision['status'] = 'done'
        with self.assertRaisesRegex(ValueError, 'lifecycle'): self.add(decision)
        close = packet('event-002', 2, 'close'); close.update(status='done', head_sha='a'*40,
            environment='local', verified_revision=1, approval_ref='restricted:approval',
            evidence=[dict(state='independently_verified', claim='failed', ref='restricted:run',
                sha='a'*40, environment='local', outcome='fail', verified_by='reviewer')])
        with self.assertRaisesRegex(ValueError, 'prior passing verification'): self.add(close)

    def test_independent_evidence_requires_binding_for_every_kind(self):
        first = packet(); first.update(head_sha='a'*40, environment='local', execution_owner='worker')
        self.add(first)
        for kind in ('test', 'review', 'deploy', 'decision', 'proposal'):
            with self.subTest(kind=kind):
                row = packet('event-002', 2, kind); row.update(head_sha='b'*40, environment='local',
                    evidence=[dict(state='independently_verified', claim='checked', ref='restricted:run',
                        sha='b'*40, environment='local', outcome='pass', verified_by='reviewer')])
                with self.assertRaisesRegex(ValueError, 'bind a prior revision'): history.validate(row)
                row['verified_revision'] = 1
                with self.assertRaisesRegex(ValueError, 'target code identity'): self.add(row)
                row['head_sha'] = 'a'*40; row['evidence'][0]['sha'] = 'a'*40
                row['evidence'][0]['verified_by'] = 'worker'
                with self.assertRaisesRegex(ValueError, 'not independent'): self.add(row)
        valid = packet('event-002', 2, 'test'); valid.update(head_sha='a'*40,
            environment='local', verified_revision=1, evidence=[dict(state='independently_verified',
                claim='checked', ref='restricted:run', sha='a'*40, environment='local',
                outcome='pass', verified_by='reviewer')])
        self.add(valid)

    def test_failed_verification_is_recordable_but_completion_requires_all_pass(self):
        first = packet(); first.update(head_sha='a'*40, environment='local', execution_owner='worker',
            open_checks=['required regression'])
        self.add(first)
        def proof(outcome):
            return dict(state='independently_verified', claim='check', ref='restricted:run',
                sha='a'*40, environment='local', outcome=outcome, verified_by='reviewer')
        failed = packet('event-002', 2, 'verification'); failed.update(head_sha='a'*40,
            environment='local', execution_owner='worker', verified_revision=1, evidence=[proof('fail')])
        self.add(failed)
        close = packet('event-003', 3, 'close'); close.update(status='done', head_sha='a'*40,
            environment='local', verified_revision=2, approval_ref='restricted:approval',
            evidence=[proof('pass')])
        with self.assertRaisesRegex(ValueError, 'prior passing'): self.add(close)
        self.path.unlink()
        self.add(first)
        for outcome in ('fail', 'unknown'):
            with self.subTest(outcome=outcome):
                verification = packet('event-002', 2, 'verification'); verification.update(
                    head_sha='a'*40, environment='local', execution_owner='worker',
                    verified_revision=1, evidence=[proof('pass'), proof(outcome)])
                self.add(verification)
                with self.assertRaisesRegex(ValueError, 'prior passing'): self.add(close)
                self.path.unlink(); self.add(first)
        passed = packet('event-002', 2, 'verification'); passed.update(head_sha='a'*40,
            environment='local', execution_owner='worker', verified_revision=1, evidence=[proof('pass')])
        self.add(passed)
        with self.assertRaisesRegex(ValueError, 'unresolved checks'): self.add(close)
        close['resolved_checks'] = ['required regression']
        with self.assertRaisesRegex(ValueError, 'cannot resolve'): self.add(close)
        close.pop('resolved_checks')
        self.path.unlink(); self.add(first)
        passed['resolved_checks'] = ['required regression']; self.add(passed); self.add(close)
        self.assertEqual(history.overview(self.repo, 'task-001')['status'], 'done')

    def test_historical_correction_cannot_override_blocked_state(self):
        first = packet(); self.add(first)
        blocked = packet('event-002', 2, 'failure'); blocked.update(status='blocked',
            at_utc='2026-10-03T01:00:00Z'); self.add(blocked)
        correction = packet('event-003', 3, 'decision'); correction.update(status='active',
            correction_of='event-001', at_utc='2026-10-03T00:30:00Z')
        with self.assertRaisesRegex(ValueError, 'historical correction'): self.add(correction)
        correction.pop('status'); self.add(correction)
        self.assertEqual(history.overview(self.repo, 'task-001')['status'], 'blocked')
        current = packet('event-004', 4, 'decision'); current.update(status='active',
            at_utc='2026-10-03T02:00:00Z'); self.add(current)
        self.assertEqual(history.overview(self.repo, 'task-001')['status'], 'active')

    def test_first_event_rejects_prior_event_claims(self):
        for change in ({'verified_revision': 99}, {'correction_of': 'event-000'},
                       {'head_sha': 'a'*40, 'evidence': [dict(state='independently_verified',
                           claim='checked', ref='restricted:run', sha='a'*40, environment='local',
                           outcome='pass', verified_by='owner')], 'verified_revision': 99}):
            with self.subTest(change=change):
                row = packet(); row.update(change)
                with self.assertRaisesRegex(ValueError, 'first event'): self.add(row)
        self.assertFalse(self.path.exists())

    def test_canonical_timestamps_and_current_order(self):
        for value in ('2026-9-30T00:00:00Z', '2026-10-3T00:00:00Z',
                      '2026-10-03T0:00:00Z', '2026-99-99T00:00:00Z'):
            with self.subTest(value=value):
                row = packet(); row['at_utc'] = value
                with self.assertRaisesRegex(ValueError, 'timestamp'): history.validate(row)
        first = packet(); first['at_utc'] = '2026-10-03T02:00:00Z'; self.add(first)
        older = packet('event-002', 2, 'decision'); older.update(status='blocked',
            at_utc='2026-09-30T23:00:00Z')
        with self.assertRaisesRegex(ValueError, 'historical correction'): self.add(older)

    def test_check_mutation_matrix(self):
        self.add(packet())
        for kind in ('proposal', 'test', 'review', 'deploy', 'handoff', 'cancellation', 'close'):
            with self.subTest(kind=kind):
                row = packet('event-002', 2, kind); row['resolved_checks'] = ['required']
                if kind == 'cancellation': row['status'] = 'canceled'
                if kind == 'close': row['status'] = 'done'
                with self.assertRaisesRegex(ValueError, 'checks|close'): history.validate(row)
        decision = packet('event-002', 2, 'decision'); decision['resolved_checks'] = ['required']
        with self.assertRaisesRegex(ValueError, 'scope decision'): history.validate(decision)
        decision.update(approval_ref='restricted:scope', reason='Excluded by approved scope')
        history.validate(decision)
        verification = packet('event-002', 2, 'verification'); verification.update(
            verified_revision=1, head_sha='a'*40, evidence=[dict(state='independently_verified',
                claim='failed', ref='restricted:run', sha='a'*40, environment='local',
                outcome='fail', verified_by='reviewer')], resolved_checks=['required'])
        with self.assertRaisesRegex(ValueError, 'needs evidence'): history.validate(verification)
        verification['evidence'].append({**verification['evidence'][0], 'outcome': 'pass'})
        with self.assertRaisesRegex(ValueError, 'needs evidence'): history.validate(verification)

    def test_close_cannot_add_open_check(self):
        first = packet(); first.update(head_sha='a'*40, environment='local', execution_owner='worker')
        self.add(first)
        proof = dict(state='independently_verified', claim='passed', ref='restricted:run',
            sha='a'*40, environment='local', outcome='pass', verified_by='reviewer')
        verify = packet('event-002', 2, 'verification'); verify.update(head_sha='a'*40,
            environment='local', execution_owner='worker', verified_revision=1, evidence=[proof])
        self.add(verify)
        close = packet('event-003', 3, 'close'); close.update(status='done', head_sha='a'*40,
            environment='local', verified_revision=2, approval_ref='restricted:accept',
            evidence=[proof], open_checks=['required final health'])
        with self.assertRaisesRegex(ValueError, 'unresolved checks'): self.add(close)
        close.pop('open_checks'); self.add(close)
        self.assertEqual(history.overview(self.repo, 'task-001')['open_checks'], [])

    def test_two_processes_conflict_reconcile_and_uncertain_ack(self):
        self.add(packet()); expected = history.digest(self.path)
        packets = []
        for n in (2, 3):
            path = self.repo / f'packet-{n}.json'
            path.write_text(json.dumps(packet(f'event-00{n}', 2, 'decision')))
            packets.append(path)
        gate = "import runpy,sys; sys.stdin.readline(); sys.argv=[sys.argv[1], '--repo', sys.argv[2], 'append', sys.argv[3], '--expected-digest', sys.argv[4]]; runpy.run_path(sys.argv[0], run_name='__main__')"
        procs = [subprocess.Popen([sys.executable, '-c', gate, str(MODULE), str(self.repo), str(path), expected],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for path in packets]
        for proc in procs: proc.stdin.write('go\n'); proc.stdin.flush()
        outcomes = [proc.communicate()[0] for proc in procs]
        self.assertEqual(sum('appended' in outcome for outcome in outcomes), 1)
        rows = history.events(self.repo, 'task-001')
        self.assertEqual(len(rows), 2)
        winner = rows[-1]['event_id']
        loser = 'event-002' if winner == 'event-003' else 'event-003'
        # The first process could have committed before its acknowledgment was lost.
        self.assertEqual(self.add(rows[-1])[0], 'duplicate')
        recovered = packet(loser, 3, 'decision')
        self.add(recovered)
        self.assertEqual({r['event_id'] for r in history.events(self.repo, 'task-001')},
                         {'event-001', 'event-002', 'event-003'})

    def test_replay_is_read_only_even_with_command_evidence(self):
        sentinel = self.repo / 'must-not-exist'
        first = packet(); first.update(head_sha='a'*40, environment='local', execution_owner='worker')
        self.add(first)
        row = packet('event-002', 2, 'test'); row['evidence'] = [dict(state='performed',
            claim='command recorded', ref='restricted:run', sha='a'*40, environment='local',
            command=f'touch {sentinel}', outcome='pass')]
        self.add(row)
        result = subprocess.run([sys.executable, str(MODULE), '--repo', str(self.repo),
            'view', 'task-001', '--events'], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(sentinel.exists())

    def test_remote_identity_and_fresh_clone_permissions(self):
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'set-url', 'origin', 'https://github.com/T-Seli/wrong.git'], check=True)
        with self.assertRaisesRegex(ValueError, 'intended'): history.checkout(self.repo)
        for name in ('agent-knowledge-base', 'agent-task-history'):
            subprocess.run(['git', '-C', str(self.repo), 'remote', 'set-url', 'origin', f'git@github.com:T-Seli/{name}.git'], check=True)
            self.assertEqual(history.checkout(self.repo), self.repo.resolve())
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'set-url', 'origin', 'https://github.com/T-Seli/agent-knowledge-base.git'], check=True)
        self.add(packet()); self.path.chmod(0o644); self.path.parent.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private'): history.events(self.repo, 'task-001')
        history.initialize(self.repo)
        self.assertEqual(len(history.events(self.repo, 'task-001')), 1)

    def test_locks_stay_out_of_the_working_tree(self):
        self.add(packet())
        with history.task_lock(self.repo.resolve() / 'views/task-001.md', True): pass
        git = ['git', '-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false']
        subprocess.run([*git, 'add', 'events/task-001.jsonl'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'journal'], check=True)
        status = subprocess.run([*git, 'status', '--porcelain', '--untracked-files=all'], capture_output=True, text=True, check=True)
        self.assertEqual(status.stdout, '')
        git_dir = Path(subprocess.run([*git, 'rev-parse', '--absolute-git-dir'], capture_output=True, text=True, check=True).stdout.strip())
        self.assertTrue((git_dir / 'task-history-locks/events/task-001.lock').is_file())


class ConfiguredTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'history'
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin', 'https://github.com/T-Seli/agent-task-history.git'], check=True)
        self.config = self.root / 'workers.json'

    def tearDown(self): self.temp.cleanup()

    def configured(self, settings=None):
        if settings is not None: self.config.write_text(json.dumps(settings))
        return subprocess.run([sys.executable, str(MODULE), 'configured'], capture_output=True, text=True,
                              env={**os.environ, 'AGENT_SKILLS_CONFIG': str(self.config), 'HOME': str(self.root)})

    def test_initialized_checkout_prints_its_path(self):
        history.initialize(self.repo)
        for value in (str(self.repo), '~/history'):
            result = self.configured({'task_history_repo': value})
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, f'{self.repo}\n', ''))

    def test_missing_unset_or_uninitialized_is_not_configured(self):
        cases = [(None, 'missing config'), ({}, 'unset'), ({'task_history_repo': None}, 'unset'),
                 ({'task_history_repo': str(self.root / 'absent')}, 'path missing'),
                 ({'task_history_repo': str(self.root)}, 'not initialized'),
                 ({'task_history_repo': str(self.repo)}, 'not initialized')]
        for settings, reason in cases:
            with self.subTest(reason=reason, settings=settings):
                result = self.configured(settings)
                self.assertEqual((result.returncode, result.stdout), (1, 'History: not configured\n'))
                self.assertIn(reason, result.stderr)
                self.assertEqual(result.stderr.count('\n'), 1)
        self.assertFalse((self.repo / 'events').exists())
        (self.repo / 'events').mkdir(); (self.repo / 'events').chmod(0o755)
        result = self.configured()
        self.assertEqual((result.returncode, result.stdout), (1, 'History: not configured\n'))
        self.assertIn('not initialized', result.stderr)


if __name__ == '__main__': unittest.main()
