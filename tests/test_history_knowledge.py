"""Synthetic journals exercise provenance retrieval without a second knowledge store."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'skills/task-history'
sys.path.insert(0, str(MODULE))
import history
import knowledge

SHA = 'a' * 40
CONTEXT = {'source_version': SHA, 'runtime_version': 'fixture-runtime', 'head_sha': SHA}


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin',
                        'https://github.com/T-Seli/agent-task-history.git'], check=True)

    def row(self, revision=1, task='task-001', **updates):
        value = dict(schema_version=1, event_id=f'{task}-event-{revision:03d}', task_id=task,
            session_id='fixture-session', revision=revision, record_owner='fixture-owner',
            at_utc='2026-10-24T00:00:00Z', observed_at_utc='2026-10-24T00:00:00Z',
            kind='start' if revision == 1 else 'implementation', summary='Synthetic evidence',
            repo_ref='fixture:repo', environment='synthetic', scope='fixture outcome',
            source_ref='fixture:observation', **CONTEXT,
            evidence=[dict(state='performed', claim='Fixture check passes', ref='fixture:check',
                           sha=SHA, environment='synthetic', outcome='pass')])
        if revision == 1: value['status'] = 'active'
        value.update(updates)
        return value

    def add(self, row):
        path = self.repo / 'events' / (row['task_id'] + '.jsonl')
        history.append(self.repo, row, history.digest(path))

    def query(self, tasks=None, **changes):
        return knowledge.retrieve(self.repo, tasks or ['task-001'], repo_ref='fixture:repo',
            environment='synthetic', scope='fixture outcome',
            **{'current_context': CONTEXT, **changes})

    def test_current_claim_has_full_rebuildable_provenance_without_authority(self):
        self.add(self.row())
        result = self.query()
        self.assertEqual(result['state'], 'current')
        fact = result['facts'][0]
        for key in ('task_id', 'event_id', 'revision', 'journal_digest', 'record_owner',
                    'evidence_ref', 'evidence_level', 'source_version', 'runtime_version', 'source_ref'):
            self.assertIsNotNone(fact[key])
        self.assertFalse(fact['authority'])
        self.assertEqual(result['acceptance'], 'not-established')
        self.assertEqual(result, self.query())
        self.assertFalse((self.repo / 'knowledge.json').exists())

    def test_explicit_same_scope_correction_keeps_original_and_current_replacement(self):
        first = self.row(); self.add(first)
        second = self.row(2, correction_of=first['event_id'],
            evidence=[dict(state='performed', claim='Fixture check fails', ref='fixture:check',
                           sha=SHA, environment='synthetic', outcome='fail')])
        self.add(second)
        result = self.query()
        self.assertEqual([fact['state'] for fact in result['facts']], ['superseded', 'current'])
        self.assertEqual(result['facts'][0]['superseded_by'], [result['facts'][1]['id']])
        self.assertEqual(history.overview(self.repo, 'task-001')['events'], 2)

    def test_cross_scope_or_different_evidence_correction_does_not_erase_fact(self):
        first = self.row(); self.add(first)
        changed = self.row(2, correction_of=first['event_id'], scope='other outcome')
        self.add(changed)
        self.assertEqual(self.query()['facts'][0]['state'], 'current')
        projection = knowledge.rebuild(self.repo, ['task-001'])
        self.assertTrue(projection['facts'][1]['correction_unresolved'])

    def test_unlinked_different_claims_are_conflict_not_a_voted_conclusion(self):
        self.add(self.row())
        second = self.row(2)
        second['evidence'][0]['claim'] = 'A different unresolved conclusion'
        second['evidence'][0]['outcome'] = 'fail'
        self.add(second)
        result = self.query()
        self.assertEqual(result['state'], 'conflict')
        self.assertEqual({fact['state'] for fact in result['facts']}, {'conflict'})
        self.assertEqual(len(result['facts']), 2)

    def test_differing_event_source_citations_do_not_hide_a_same_context_conflict(self):
        self.add(self.row(source_ref='fixture:original-observation'))
        second = self.row(2, source_ref='fixture:independent-observation')
        second['evidence'][0]['claim'] = 'The same code and runtime produced a failing result'
        second['evidence'][0]['outcome'] = 'fail'
        self.add(second)
        context = {key: value for key, value in CONTEXT.items() if key != 'source_ref'}
        result = self.query(current_context=context)
        self.assertEqual(result['state'], 'conflict')
        self.assertEqual([fact['state'] for fact in result['facts']], ['conflict', 'conflict'])
        self.assertEqual([fact['source_ref'] for fact in result['facts']],
                         ['fixture:original-observation', 'fixture:independent-observation'])
        self.assertTrue(all('source_ref' not in reason for fact in result['facts']
                            for reason in fact['validity_reasons']))

    def test_event_source_citation_is_not_a_missing_freshness_dimension(self):
        self.add(self.row(source_ref='fixture:original-observation'))
        context = {key: value for key, value in CONTEXT.items() if key != 'source_ref'}
        result = self.query(current_context=context)
        self.assertEqual(result['state'], 'current')
        self.assertEqual(result['facts'][0]['source_ref'], 'fixture:original-observation')

    def test_relevant_source_runtime_and_code_changes_are_stale_not_authority(self):
        self.add(self.row())
        for field, new in (('source_version', 'b' * 40), ('runtime_version', 'next-runtime'),
                           ('head_sha', 'c' * 40)):
            with self.subTest(field=field):
                result = self.query(current_context={**CONTEXT, field: new})
                self.assertEqual(result['state'], 'stale')
                self.assertFalse(result['authority'])

    def test_unrelated_repository_event_does_not_stale_selected_fact(self):
        self.add(self.row())
        self.add(self.row(task='task-002', repo_ref='fixture:other-repo', source_version='b' * 40))
        self.assertEqual(self.query(tasks=['task-001', 'task-002'])['state'], 'current')

    def test_different_source_context_is_stale_evidence_not_a_contradiction(self):
        self.add(self.row())
        other = self.row(task='task-002', source_version='b' * 40)
        other['evidence'][0]['claim'] = 'A different source reports a different result'
        other['evidence'][0]['outcome'] = 'fail'
        self.add(other)
        facts = self.query(tasks=['task-001', 'task-002'])['facts']
        self.assertEqual([fact['state'] for fact in facts], ['current', 'stale'])

    def test_missing_freshness_reported_claim_and_proposal_remain_unknown(self):
        first = self.row(approval_ref='fixture:task-only-grant')
        first['evidence'][0]['state'] = 'reported'
        self.add(first)
        self.assertEqual(self.query()['state'], 'unknown')
        self.assertEqual(self.query(current_context={})['state'], 'unknown')
        proposal = self.row(2, kind='proposal', lesson_proposal='Review before any future skill change')
        self.add(proposal)
        result = self.query()
        self.assertEqual(result['state'], 'unknown')
        projection = knowledge.rebuild(self.repo, ['task-001'])
        self.assertFalse(projection['context_records'][0]['authority'])
        self.assertEqual(projection['context_records'][0]['approval_ref'], 'fixture:task-only-grant')
        self.assertTrue(projection['context_records'][1]['proposal_only'])

    def test_missing_or_corrupt_journal_is_an_explicit_gap(self):
        self.add(self.row())
        result = self.query(tasks=['task-001', 'missing-task'])
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['gaps'][0]['state'], 'missing')
        (self.repo / 'events/task-001.jsonl').write_text('broken')
        result = self.query()
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['gaps'][0]['state'], 'unavailable')
        self.assertEqual(result['facts'], [])

    def test_cursor_binds_projection_and_query_and_rejects_changed_source(self):
        self.add(self.row())
        second = self.row(2)
        second['evidence'][0]['ref'] = 'fixture:second-check'
        self.add(second)
        first = self.query(limit=1)
        self.assertEqual(first['total'], 2)
        self.assertEqual(len(first['facts']), 1)
        next_page = self.query(limit=1, cursor=first['next_cursor'])
        self.assertEqual(len(next_page['facts']), 1)
        self.assertNotEqual(first['facts'][0]['id'], next_page['facts'][0]['id'])
        with self.assertRaisesRegex(ValueError, 'stale or foreign'):
            self.query(limit=1, cursor=first['next_cursor'], current_context={})
        self.add(self.row(3))
        with self.assertRaisesRegex(ValueError, 'stale or foreign'):
            self.query(limit=1, cursor=first['next_cursor'])

    def test_invalid_requests_fail_without_traversal_or_unbounded_result(self):
        for tasks in ([], ['../escape'], ['task-001', 'task-001'], [{}]):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                knowledge.rebuild(self.repo, tasks)
        for kwargs in ({'limit': 101}, {'limit': True}, {'current_context': {'unbound': 'value'}},
                       {'current_context': {'source_ref': 'fixture:not-a-version'}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.query(**kwargs)

    def test_legacy_unbound_evidence_does_not_acquire_scope(self):
        row = self.row()
        row.pop('scope')
        self.add(row)
        result = self.query()
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['facts'], [])
        self.assertEqual(result['legacy_unbound_count'], 1)
        self.assertEqual(knowledge.rebuild(self.repo, ['task-001'])['facts'][0]['binding'], 'legacy-unbound')

    def test_cli_reads_real_synthetic_journal_without_changing_it(self):
        self.add(self.row())
        journal = self.repo / 'events/task-001.jsonl'
        original = journal.read_bytes()
        context = self.repo / 'context.json'
        context.write_text(json.dumps(CONTEXT))
        result = subprocess.run([sys.executable, '-B', str(MODULE / 'knowledge.py'),
            '--repo', str(self.repo), '--task', 'task-001', '--repo-ref', 'fixture:repo',
            '--environment', 'synthetic', '--scope', 'fixture outcome',
            '--context-file', str(context), '--limit', '1'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed['state'], 'current')
        self.assertEqual(parsed['facts'][0]['event_id'], 'task-001-event-001')
        self.assertFalse(parsed['authority'])
        self.assertEqual(journal.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
