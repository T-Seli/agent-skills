"""Codex's serialized strict wire boundary, distinct from reducer fixtures.

The opt-in live check submits the exact generated file to the supported CLI/service.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('worker_schema', ROOT / 'skills/agent-coordination/scripts/workers.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def strict_contract(schema):
    """Independent check of documented Structured Outputs object/array rules."""
    if schema.get('type') == 'object' or 'object' in schema.get('type', []):
        assert schema.get('additionalProperties') is False, 'open object'
        assert isinstance(schema.get('properties'), dict), 'undefined object'
        assert set(schema.get('required', [])) == set(schema['properties']), 'missing required properties'
        for value in schema['properties'].values():
            strict_contract(value)
    if schema.get('type') == 'array' or 'array' in schema.get('type', []):
        assert 'items' in schema, 'undefined array items'
        strict_contract(schema['items'])


def stdout(report):
    return json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(report)}})


class WireSchema(unittest.TestCase):
    def wire(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'schema.json'
            w.Codex.write_schema(path)
            argv = w.Codex(model="fixture-codex", effort="medium").command('synthetic only', cwd=d, schema_file=path)
            return json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())

    def test_serialized_cli_file_satisfies_strict_contract(self):
        wire = self.wire()
        strict_contract(wire)
        self.assertEqual(len(wire['required']), len(w.REPORT_SCHEMA['properties']))
        self.assertEqual(wire['properties']['status']['enum'], ['running', 'blocked', 'answered', 'ready'])

    def test_old_serialized_schema_reproduces_service_rejection(self):
        legacy = json.loads(json.dumps(w.REPORT_SCHEMA))
        with self.assertRaisesRegex(AssertionError, 'missing required properties'):
            strict_contract(legacy)
        legacy['required'] = list(legacy['properties'])
        with self.assertRaisesRegex(AssertionError, 'open object'):
            strict_contract(legacy)

    def test_binding_fields_remain_required_and_non_nullable(self):
        wire = self.wire()
        for name in ('task_id', 'deliverable_id', 'revision', 'contract_digest', 'next_action', 'decision_source_ref'):
            with self.subTest(field=name):
                self.assertIn(name, wire['required'])
                self.assertEqual(wire['properties'][name]['type'], 'integer' if name == 'revision' else 'string')
        for name in w.REPORT_SCHEMA['required']:
            self.assertNotIsInstance(wire['properties'][name]['type'], list)

    def test_packet_is_required_but_null_only_matches_no_packet_binding(self):
        from test_tasks import t, fresh
        from agent_skills.task_contract import packet
        wire = self.wire()
        self.assertIn('packet_sha256', wire['required'])
        self.assertEqual(wire['properties']['packet_sha256']['type'], ['string', 'null'])
        record = t.bind_task_contract(fresh(), user_goal='communication', constraints=['synthetic'],
            priority_source_ref='decision:r1', canonical_issue_ref='synthetic', canonical_owner='owned',
            deliverable_id='communication', revision=1, acceptance_ref='synthetic', environment='synthetic',
            changed_criteria='return source-bound facts', next_action='return facts', source_ref='decision:r1')
        record = t.acknowledge_task_contract(record, deliverable_id='communication', revision=1,
            changed_criteria='return source-bound facts', next_action='return facts', environment='synthetic', receipt_ref='actual:ack')
        binding = t.current_task_binding(record)
        self.assertIsNone(binding['packet_sha256'])
        parsed = w.Codex(model="fixture-codex", effort="medium").parse(stdout(binding))['report']
        self.assertEqual(t._event_result_binding(record, parsed), 'current')
        p = packet(task_id=record['task_id'], revision=1, owner='owned', scope='synthetic',
            exclusions=['writes'], baseline='a' * 40, deliverables=['communication'],
            acceptance=[{'id':'fact','check':'exact fact'}], context_refs=['synthetic'],
            source_hashes={'synthetic':'b' * 64}, package_hashes={'synthetic':'b' * 64},
            stop_conditions=['stop'], escalation_conditions=['unsupported'])
        record = t.bind_packet(record, p)
        self.assertEqual(t._event_result_binding(record, parsed), 'stale-packet')
        parsed['packet_sha256'] = p['packet_sha256']
        self.assertEqual(t._event_result_binding(record, parsed), 'current')

    def test_wire_generation_does_not_mutate_claude_schema(self):
        before = copy.deepcopy(w.REPORT_SCHEMA)
        self.wire()
        self.assertEqual(w.REPORT_SCHEMA, before)
        argv = w.Claude(model="fixture-claude", effort="medium", settings="guard.json").command(session_id='owned', resume=False)
        self.assertEqual(json.loads(argv[argv.index('--json-schema') + 1]), before)

    def test_evidence_json_transport_restores_arbitrary_task_fields(self):
        evidence = {'task_id': 'current', 'revision': 2, 'packet_sha256': 'p',
                    'criterion_evidence': {'manager-route': {'observed_results': {'ordinary-manager': '403'},
                    'artifact_hashes': {'task-defined-kind': 'h'}}}}
        parsed = w.Codex(model="fixture-codex", effort="medium").parse(stdout({'completion_report': json.dumps(evidence), 'verifier_report': json.dumps(evidence)}))
        self.assertFalse(parsed['error'])
        self.assertEqual(parsed['report'], {'completion_report': evidence, 'verifier_report': evidence})

    def test_invalid_evidence_wire_fails_closed(self):
        for bad in ('{', '[]', 'null', 'true', '42', '"text"'):
            for name in ('completion_report', 'verifier_report'):
                with self.subTest(value=bad, field=name):
                    parsed = w.Codex(model="fixture-codex", effort="medium").parse(stdout({name: bad}))
                    self.assertTrue(parsed['error'])
                    self.assertIsNone(parsed['report'])

    def test_unused_null_and_legacy_object_reports_are_preserved(self):
        report = {'completion_report': None, 'verifier_report': {'task_id': 'legacy'}}
        self.assertEqual(w.Codex(model="fixture-codex", effort="medium").parse(stdout(report))['report'], report)

    @unittest.skipUnless(os.environ.get('AGENT_SKILLS_CODEX_SCHEMA_LIVE') == '1', 'opt-in actual CLI/service boundary')
    def test_live_cli_service_accepts_exact_generated_file(self):
        model = os.environ['AGENT_SKILLS_TEST_CODEX_MODEL']
        effort = os.environ['AGENT_SKILLS_TEST_CODEX_EFFORT']
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'schema.json'
            w.Codex.write_schema(path)
            prompt = ('Synthetic non-sensitive schema smoke test. Do not use tools or read files. Return status=running, '
                      'summary=schema accepted, commit/tests/need/action/target and all binding strings empty, revision=0, '
                      'unused optional fields null. Do not claim readiness or source consumption.')
            argv = w.Codex(model=model, effort=effort).command(prompt, cwd=d, schema_file=path)
            argv[2:2] = ['--skip-git-repo-check', '-c', 'model_reasoning_effort=' + json.dumps(effort)]
            run = subprocess.run(argv, cwd=d, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
            parsed = w.Codex(model="fixture-codex", effort="medium").parse(run.stdout)
            self.assertEqual(run.returncode, 0, run.stdout)
            self.assertFalse(parsed['error'], run.stdout)
            self.assertIsInstance(parsed['report'], dict)
            self.assertEqual(parsed['report']['status'], 'running')
            self.assertEqual(set(parsed['report']), set(w.codex_report_schema()['properties']))


if __name__ == '__main__':
    unittest.main()
