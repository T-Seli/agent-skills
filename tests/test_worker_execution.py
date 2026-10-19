"""Synthetic routing, diagnostics and ownership regressions; no model calls."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_skills import worker_execution as e

ROOT = Path(os.environ.get('WORKER_SOURCE_ROOT', Path(__file__).resolve().parents[1]))
def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
w = module('execution_workers', 'skills/agent-coordination/scripts/workers.py')
t = module('execution_tasks', 'skills/agent-coordination/scripts/tasks.py')

POLICY = {p: {'ordinary': {'model': p + '-ordinary', 'effort': 'medium', 'timeout_seconds': 30},
              'involved': {'model': p + '-strong', 'effort': 'high', 'timeout_seconds': 60}}
          for p in ('codex', 'claude')}
CAPS = {p: {p + '-ordinary': ['medium'], p + '-strong': ['high']} for p in POLICY}

def route(provider='codex', signals=()):
    return e.select_route(POLICY, CAPS, provider=provider, signals=signals, reason='synthetic task evidence')

def task():
    r = t.new_task('synthetic-worker', 'synthetic-worker', worker_kind='codex', owner='assistant', repo='synthetic')
    return e.bind_route(r, route(), source_pin='source:a', decision_ref='decision:synthetic')

def process(state='done', stdout='result', stderr='diagnostic'):
    return w.RunResult(state, stdout, stderr, 0 if state == 'done' else None, 123,
                       '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00')

def parsed(model='codex-ordinary', effort=None, sid='owned'):
    return {'session_id': sid, 'error': False, 'report': {'status': 'running'},
            'execution': {'models': [model] if model else [], 'effective_effort': effort}}


class AdapterRegressions(unittest.TestCase):
    def test_explicit_model_and_effort_are_encoded_for_both_providers(self):
        c = w.Claude(model='fixture-claude', effort='high')
        argv = c.command('synthetic', session_id='owned', resume=False)
        self.assertEqual(argv[argv.index('--effort') + 1], 'high')
        argv = w.Codex(model='fixture-codex', effort='medium').command('synthetic', cwd='.', schema_file='schema')
        self.assertIn('model_reasoning_effort="medium"', argv)
        self.assertIn('--ignore-user-config', argv)

    def test_unconfigured_commands_fail_instead_of_using_an_implicit_model(self):
        with self.assertRaises(ValueError):
            w.Claude().command('synthetic', session_id='owned', resume=False)
        with self.assertRaises(ValueError):
            w.Codex().command('synthetic', cwd='.', schema_file='schema')

    def test_timeout_retains_partial_both_streams_and_uncertainty(self):
        def runner(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 1, output=b'partial session receipt', stderr=b'transport failed')
        result = w.run(['synthetic'], cwd='.', timeout=1, runner=runner)
        self.assertEqual(result.state, 'uncertain')
        self.assertEqual(result.stdout, 'partial session receipt')
        self.assertEqual(result.stderr, 'transport failed')
        self.assertEqual(tuple(result), ('uncertain', result.stdout))

    def test_nonzero_keeps_stderr_exit_status_and_identity(self):
        def runner(argv, **kwargs):
            result = subprocess.CompletedProcess(argv, 7, 'partial', 'denied')
            result.pid = 42
            return result
        result = w.run(['synthetic'], cwd='.', timeout=1, runner=runner)
        self.assertEqual((result.state, result.returncode, result.stderr, result.pid), ('failed', 7, 'denied', 42))

    def test_actual_owned_process_timeout_keeps_output_without_touching_other_sessions(self):
        code = "import sys,time;print('partial',flush=True);print('diagnostic',file=sys.stderr,flush=True);time.sleep(5)"
        result = w.run([sys.executable, '-c', code], cwd='.', timeout=.15)
        self.assertEqual(result.state, 'uncertain')
        self.assertIn('partial', result.stdout)
        self.assertIn('diagnostic', result.stderr)
        self.assertIsNotNone(result.pid)

    def test_parser_keeps_actual_metadata_separate_from_worker_claims(self):
        report = {'status': 'running', 'summary': 'I used high effort on another model'}
        stdout = json.dumps({'type': 'result', 'session_id': 'owned', 'structured_output': report,
                             'modelUsage': {'fixture-claude': {'inputTokens': 10}}, 'usage': {'input_tokens': 10}})
        result = w.Claude().parse(stdout)
        self.assertEqual(result['execution']['models'], ['fixture-claude'])
        self.assertIsNone(result['execution']['effective_effort'])
        self.assertEqual(result['report'], report)

    def test_streaming_partial_result_still_retains_session_identity(self):
        stdout = json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'owned', 'model': 'fixture'}) + '\n{"type":'
        result = w.Claude().parse(stdout)
        self.assertEqual(result['session_id'], 'owned')
        self.assertTrue(result['error'])

    def test_conflicting_runtime_efforts_do_not_become_a_single_effective_level(self):
        out = '\n'.join(json.dumps({'type': 'system', 'effort': x}) for x in ['medium', 'high'])
        result = w.Claude().parse(out)['execution']
        self.assertIsNone(result['effective_effort'])
        self.assertEqual(result['conflicting_efforts'], ['high', 'medium'])

    def test_codex_nonterminal_warning_is_retained_without_overriding_success(self):
        rows = [{'type': 'thread.started', 'thread_id': 'owned'},
                {'type': 'item.completed', 'item': {'type': 'error', 'message': 'feature warning'}},
                {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"status":"running"}'}},
                {'type': 'turn.completed', 'usage': {'output_tokens': 1}}]
        result = w.Codex().parse('\n'.join(map(json.dumps, rows)))
        self.assertFalse(result['error'])
        self.assertEqual(result['execution']['diagnostics'], ['feature warning'])
        rows.append({'type': 'turn.failed'})
        self.assertTrue(w.Codex().parse('\n'.join(map(json.dumps, rows)))['error'])
        self.assertTrue(w.Codex().parse(json.dumps(rows[1]))['error'])

    def test_codex_runtime_metadata_must_match_this_output_session(self):
        out = json.dumps({'type': 'thread.started', 'thread_id': 'owned'})
        log = 'event.name="codex.conversation_starts" conversation.id=owned model=fixture-codex reasoning_effort="medium"'
        result = w.Codex().parse(out, log)['execution']
        self.assertEqual((result['models'], result['effective_effort']), (['fixture-codex'], 'medium'))
        self.assertEqual(w.Codex().parse(out, log.replace('id=owned', 'id=other'))['execution']['models'], [])


class RouteAndLifecycle(unittest.TestCase):
    def test_ordinary_default_and_upfront_dynamic_escalation(self):
        self.assertEqual((route()['model'], route()['effort']), ('codex-ordinary', 'medium'))
        for signal in e.SIGNALS:
            with self.subTest(signal=signal):
                self.assertEqual((route(signals=[signal])['model'], route(signals=[signal])['effort']), ('codex-strong', 'high'))

    def test_unavailable_stronger_route_never_silently_falls_back(self):
        with self.assertRaises(ValueError):
            e.select_route(POLICY, {'codex': {'codex-ordinary': ['medium']}}, provider='codex',
                           signals=['architecture'], reason='complex')

    def test_policy_cannot_claim_unsupported_cost_cap(self):
        policy = copy.deepcopy(POLICY)
        policy['codex']['ordinary']['max_cost_usd'] = 1
        with self.assertRaises(ValueError):
            e.select_route(policy, CAPS, provider='codex', reason='test')

    def test_owned_resume_preserves_route_and_requires_explicit_version_change(self):
        r = task(); r['worker']['session_id'] = 'owned'
        dispatch = t.begin_dispatch(r, 'resume', resume=True)
        self.assertEqual(dispatch['outbox'][0]['execution_route'], r['worker']['execution_route'])
        with self.assertRaises(ValueError):
            e.bind_route(r, route(signals=['architecture']), source_pin='source:b', decision_ref='decision:synthetic')
        changed = e.bind_route(r, route(signals=['architecture']), source_pin='source:b',
                               decision_ref='decision:synthetic', change_ref='decision:escalate')
        self.assertEqual(changed['worker']['execution_route']['route']['effort'], 'high')

    def test_owned_session_cannot_be_replaced_or_human_session_dispatched(self):
        r = task(); r['worker']['session_id'] = 'owned'
        with self.assertRaises(ValueError): t.begin_dispatch(r, 'fresh', resume=False)
        r['worker']['owner'] = 'human'
        with self.assertRaises(PermissionError): t.begin_dispatch(r, 'resume', resume=True)

    def test_timeout_stays_unresolved_and_blocks_duplicate(self):
        r = t.begin_dispatch(task(), 'first', resume=False)
        r = e.record_execution(r, 'first', process('uncertain'), parsed(), receipt_ref='receipt:timeout')
        self.assertEqual(r['outbox'][0]['state'], 'uncertain')
        with self.assertRaises(RuntimeError): t.begin_dispatch(r, 'second', resume=True)

    def test_different_resume_identity_rejected(self):
        r = task(); r['worker']['session_id'] = 'owned'
        r = t.begin_dispatch(r, 'resume', resume=True)
        with self.assertRaises(ValueError):
            e.record_execution(r, 'resume', process(), parsed(sid='other'), receipt_ref='receipt:wrong')

    def test_result_parent_consumption_and_acceptance_are_distinct(self):
        r = t.begin_dispatch(task(), 'fresh', resume=False)
        r = e.record_execution(r, 'fresh', process(), parsed(), receipt_ref='receipt:result')
        receipt = r['worker']['last_execution']
        self.assertTrue(receipt['result_received'])
        self.assertIsNone(receipt['effort_match'])
        self.assertFalse(receipt['parent_consumed'])
        with self.assertRaises(ValueError):
            e.consume_result(r, 'fresh', stdout_sha256='wrong', receipt_ref='parent:read')
        consumed = e.consume_result(r, 'fresh', stdout_sha256=receipt['stdout_sha256'], receipt_ref='parent:read')
        self.assertTrue(consumed['worker']['last_execution']['parent_consumed'])
        self.assertEqual(consumed['status'], r['status'])
        self.assertNotEqual(consumed['status'], 'verified-done')

    def test_actual_model_mismatch_cannot_be_consumed_as_requested_success(self):
        r = t.begin_dispatch(task(), 'fresh', resume=False)
        r = e.record_execution(r, 'fresh', process(), parsed(model='cheap-fallback'), receipt_ref='receipt:fallback')
        self.assertFalse(r['worker']['last_execution']['result_received'])
        with self.assertRaises(ValueError):
            e.consume_result(r, 'fresh', stdout_sha256=r['worker']['last_execution']['stdout_sha256'], receipt_ref='parent:read')

    def test_new_receipt_cannot_silently_replace_timeout_or_failure_evidence(self):
        r = t.begin_dispatch(task(), 'fresh', resume=False)
        r = e.record_execution(r, 'fresh', process('uncertain'), parsed(), receipt_ref='receipt:timeout')
        with self.assertRaises(ValueError):
            e.record_execution(r, 'fresh', process(), parsed(), receipt_ref='receipt:later')
        reconciled = e.record_execution(r, 'fresh', process(), parsed(), receipt_ref='receipt:later',
                                       reconciliation_ref='supported:completion')
        self.assertEqual(reconciled['outbox'][0]['execution_history'][0]['state'], 'uncertain')
        self.assertEqual(reconciled['outbox'][0]['state'], 'sent')


OPUS, HAIKU, SONNET = 'claude-opus-5-5', 'claude-haiku-5-5', 'claude-sonnet-5-5'
# Sanitized protocol shape of one saved Opus run whose web fetches ran on Haiku: root init and
# assistant rows (parent_tool_use_id null) name only Opus; Haiku appears only in the result's
# modelUsage; no effort field is exposed. Session ID and structured_output are synthetic.
MIXED_STREAM = (ROOT / 'tests/fixtures/claude_primary_auxiliary_stream.jsonl').read_text()
MIXED_SID = '00000000-0000-4000-8000-0000000000a1'


def claude_task(model=OPUS):
    policy = {'claude': {tier: {'model': model, 'effort': 'medium', 'timeout_seconds': 30}
                         for tier in ('ordinary', 'involved')}}
    chosen = e.select_route(policy, {'claude': {model: ['medium']}}, provider='claude', reason='synthetic')
    r = t.new_task('synthetic-claude', 'synthetic-claude', worker_kind='claude', owner='assistant', repo='synthetic')
    return t.begin_dispatch(e.bind_route(r, chosen, source_pin='source:a', decision_ref='decision:a'), 'fresh', resume=False)


def stream(*rows, result_usage=(OPUS, HAIKU)):
    rows = list(rows) + [{'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': MIXED_SID,
                          'structured_output': {'status': 'running'},
                          'modelUsage': {m: {'inputTokens': 1} for m in result_usage}}]
    return '\n'.join(json.dumps({'session_id': MIXED_SID, **x}) for x in rows)


def root(model, parent=None):
    return {'type': 'assistant', 'message': {'model': model, 'content': []}, 'parent_tool_use_id': parent}


class ModelRoles(unittest.TestCase):
    def recorded(self, stdout, model=OPUS, state='done'):
        parsed = w.Claude().parse(stdout)
        r = e.record_execution(claude_task(model), 'fresh', process(state, stdout), parsed, receipt_ref='receipt:run')
        return r, r['worker']['last_execution']

    def consume(self, r, receipt):
        return e.consume_result(r, 'fresh', stdout_sha256=receipt['stdout_sha256'], receipt_ref='parent:read')

    def test_real_primary_opus_with_auxiliary_haiku_is_a_consumable_match(self):
        parsed = w.Claude().parse(MIXED_STREAM)['execution']
        self.assertEqual((parsed['primary_models'], parsed['auxiliary_models'], parsed['model_attribution']),
                         ([OPUS], [HAIKU], 'root-rows'))
        self.assertEqual(parsed['models'], [OPUS, HAIKU])  # aggregate diagnostics preserved
        self.assertEqual(set(parsed['model_usage']), {OPUS, HAIKU})
        self.assertIsNone(parsed['effective_effort'])  # unexposed, never invented
        r, receipt = self.recorded(MIXED_STREAM)
        self.assertEqual((receipt['model_match'], receipt['result_received'], receipt['session_id']), (True, True, MIXED_SID))
        self.assertNotIn('route_mismatch', receipt)
        self.assertTrue(self.consume(r, receipt)['worker']['last_execution']['parent_consumed'])

    def test_result_record_alone_leaves_mixed_primary_unknown_not_wrong(self):
        result_only = MIXED_STREAM.strip().splitlines()[-1]
        parsed = w.Claude().parse(result_only)['execution']
        self.assertEqual((parsed['primary_models'], parsed['auxiliary_models'], parsed['model_attribution']),
                         ([], [], 'usage-only'))
        r, receipt = self.recorded(result_only)
        self.assertIsNone(receipt['model_match'])
        self.assertTrue(receipt['result_received'])
        self.assertNotIn('route_mismatch', receipt)

    def test_genuine_primary_mismatch_fails_closed_even_when_requested_is_auxiliary(self):
        for rows in ([{'type': 'system', 'subtype': 'init', 'model': SONNET}, root(SONNET)],
                     [root(SONNET), root(OPUS, parent='toolu_synthetic')]):
            with self.subTest(rows=rows):
                r, receipt = self.recorded(stream(*rows, result_usage=(SONNET, OPUS)))
                self.assertEqual((receipt['model_match'], receipt['result_received'], receipt['route_mismatch']),
                                 (False, False, True))
                with self.assertRaises(ValueError):
                    self.consume(r, receipt)
        side = w.Claude().parse(stream(root(SONNET), root(OPUS, parent='toolu_synthetic')))['execution']
        self.assertEqual((side['primary_models'], side['auxiliary_models']), ([SONNET], [OPUS, HAIKU]))

    def test_conflicting_or_absent_primary_evidence_never_becomes_a_match(self):
        r, receipt = self.recorded(stream({'type': 'system', 'subtype': 'init', 'model': OPUS}, root(SONNET)))
        self.assertEqual((receipt['model_match'], receipt['result_received']), (False, False))
        self.assertEqual(receipt['observed']['primary_models'], [OPUS, SONNET])
        r, receipt = self.recorded(stream(result_usage=(SONNET, HAIKU)))  # requested absent from all usage
        self.assertEqual((receipt['model_match'], receipt['result_received']), (False, False))

    def test_conflicting_primary_efforts_withhold_a_matching_model(self):
        r, receipt = self.recorded(stream({'type': 'system', 'subtype': 'init', 'model': OPUS, 'effort': 'high'},
                                          {'type': 'system', 'effort': 'medium'}, root(OPUS)))
        self.assertEqual(receipt['model_match'], True)
        self.assertEqual(receipt['observed']['conflicting_efforts'], ['high', 'medium'])
        self.assertEqual((receipt['result_received'], receipt['route_mismatch']), (False, True))

    def test_helper_usage_is_diagnostic_never_quota_and_timeouts_stay_unresolved(self):
        r, receipt = self.recorded(MIXED_STREAM, state='uncertain')
        self.assertEqual(receipt['observed']['model_usage'][HAIKU]['outputTokens'], 3456)
        self.assertNotIn('quota', json.dumps(receipt))
        self.assertFalse(receipt['result_received'])
        self.assertEqual(r['outbox'][0]['state'], 'uncertain')


CEILING = {**copy.deepcopy(POLICY), 'claude': {**POLICY['claude'], 'effort_ceiling': 'high'}}
WIDE_CAPS = {'claude': {'claude-ordinary': ['medium'], 'claude-strong': ['high', 'xhigh', 'max']}}


class EffortCeiling(unittest.TestCase):
    def select(self, policy, signals=()):
        return e.select_route(policy, WIDE_CAPS, provider='claude', signals=signals, reason='synthetic')

    def test_ordinary_medium_and_justified_high_record_the_applied_ceiling(self):
        ordinary, involved = self.select(CEILING), self.select(CEILING, ['architecture'])
        self.assertEqual((ordinary['effort'], ordinary['effort_ceiling']), ('medium', 'high'))
        self.assertEqual((involved['effort'], involved['tier'], involved['effort_ceiling']), ('high', 'involved', 'high'))

    def test_heavier_than_ceiling_fails_without_fallback_even_when_supported(self):
        for effort in ('xhigh', 'max'):
            policy = copy.deepcopy(CEILING)
            policy['claude']['involved']['effort'] = effort
            with self.subTest(effort=effort), self.assertRaisesRegex(ValueError, 'ceiling'):
                self.select(policy, ['high-risk'])

    def test_unranked_effort_under_a_ceiling_fails_explicitly(self):
        policy = copy.deepcopy(CEILING)
        policy['claude']['involved']['effort'] = 'ultra'
        with self.assertRaises(ValueError):
            e.select_route(policy, {'claude': {'claude-strong': ['ultra']}}, provider='claude',
                           signals=['architecture'], reason='synthetic')

    def test_policy_without_ceiling_is_an_explicit_compatibility_path(self):
        policy = copy.deepcopy(POLICY)
        policy['claude']['involved']['effort'] = 'xhigh'
        chosen = self.select(policy, ['architecture'])
        self.assertEqual(chosen['effort'], 'xhigh')
        self.assertNotIn('effort_ceiling', chosen)
        self.assertNotIn('effort_ceiling', route())

    def test_requested_and_unexposed_effective_effort_stay_distinct(self):
        r = t.begin_dispatch(task(), 'fresh', resume=False)
        result = parsed()
        result['execution']['usage'] = [{'input_tokens': 10, 'output_tokens': 2}]
        receipt = e.record_execution(r, 'fresh', process(), result, receipt_ref='receipt:usage')['worker']['last_execution']
        self.assertEqual(receipt['requested']['route']['effort'], 'medium')
        self.assertIsNone(receipt['observed']['effective_effort'])
        self.assertIsNone(receipt['effort_match'])
        self.assertEqual(receipt['observed']['usage'][0]['input_tokens'], 10)
        self.assertNotIn('quota', json.dumps(receipt))


NOW = '2026-10-16T20:00:00+00:00'
CODEX_ROUTE = route()


def receipt(env='normal-mac', auth='mac-user', auth_state='verified', observed_at='2026-10-16T19:50:00+00:00', **caps):
    capabilities = {'auth': {'state': auth_state, 'source_ref': f'auth-status:{env}'}}
    capabilities.update({k.replace('_', ':'): {'state': v, 'source_ref': 'fixture:' + k} for k, v in caps.items()})
    return {'environment_id': env, 'auth_context': auth, 'observed_at_utc': observed_at,
            'source_ref': f'readiness:{env}', 'capabilities': capabilities,
            'models': {'codex': {'codex-ordinary': ['medium']}}}


def check(value, required=('auth',), env='normal-mac', auth='mac-user', chosen=CODEX_ROUTE, now=NOW):
    return e.check_environment(required, value, environment_id=env, auth_context=auth,
                               route=chosen, now=now, max_age_seconds=3600)


class EnvironmentReadiness(unittest.TestCase):
    def test_sandbox_auth_false_and_normal_mac_auth_true_stay_context_scoped(self):
        sandbox = check(receipt('sandbox', 'sandbox-user', 'blocked'), env='sandbox', auth='sandbox-user')
        self.assertFalse(sandbox['ready'])
        self.assertEqual(sandbox['gaps'], {'blocked': ['auth']})
        self.assertEqual((sandbox['environment_id'], sandbox['auth_context']), ('sandbox', 'sandbox-user'))
        normal = check(receipt())
        self.assertTrue(normal['ready'])
        self.assertEqual(normal['gaps'], {})

    def test_receipt_from_one_context_cannot_satisfy_another(self):
        borrowed = check(receipt('sandbox', 'sandbox-user'))
        self.assertFalse(borrowed['ready'])
        self.assertEqual(borrowed['gaps'], {'mismatch': ['auth_context', 'environment_id']})
        self.assertEqual(check(receipt(auth='other-user'))['gaps'], {'mismatch': ['auth_context']})

    def test_supported_route_does_not_imply_database_messaging_or_quota(self):
        value = receipt(repo_skills='verified')
        result = check(value, required=['auth', 'repo:skills', 'db:fixture', 'messaging:team', 'quota'])
        self.assertFalse(result['ready'])
        self.assertEqual(result['gaps'], {'unknown': ['db:fixture', 'messaging:team', 'quota']})
        value['capabilities']['quota'] = {'state': 'unknown', 'source_ref': 'usage:tokens-only'}
        self.assertIn('quota', check(value, required=['quota'])['gaps']['unknown'])
        self.assertTrue(check(value, required=['auth', 'repo:skills'])['ready'])

    def test_stale_future_and_unsupported_route_block(self):
        self.assertEqual(check(receipt(observed_at='2026-10-16T18:00:00+00:00'))['gaps'], {'stale': True})
        self.assertEqual(check(receipt(observed_at='2026-10-16T21:00:00+00:00'))['gaps'], {'stale': True})
        heavy = dict(CODEX_ROUTE, effort='high')
        self.assertEqual(check(receipt(), chosen=heavy)['gaps'], {'unsupported_route': True})

    def test_malformed_receipts_fail_without_leaking_credentials(self):
        secret = 'sk-fixture-secret-value'
        bad = [dict(receipt(), token=secret),
               dict(receipt(), observed_at_utc='2026-10-16T19:50:00'),
               dict(receipt(), environment_id=7),
               dict(receipt(), source_ref=f'https://user:{secret}@example.invalid/x'),
               dict(receipt(), capabilities={'auth': {'state': 'verified', 'source_ref': 'x', 'token': secret}}),
               dict(receipt(), capabilities={'auth': {'state': 'loggedIn', 'source_ref': 'x'}}),
               dict(receipt(), models={'codex': ['medium']})]
        for value in bad:
            with self.subTest(value=sorted(value)), self.assertRaises(ValueError) as caught:
                check(value)
            self.assertNotIn(secret, str(caught.exception))
        with self.assertRaises(ValueError):
            check(receipt(), required='auth')
        with self.assertRaises(ValueError):
            check(receipt(), now='2026-10-16T20:00:00')

    def test_record_keeps_refs_and_hash_only(self):
        value = receipt(messaging_team='verified')
        result = check(value, required=['auth'])
        self.assertEqual(result['capabilities'], {'auth': {'state': 'verified', 'source_ref': 'auth-status:normal-mac'}})
        self.assertEqual(len(result['receipt_sha256']), 64)
        self.assertNotIn('messaging', json.dumps(result))

    def test_pure_check_makes_no_network_or_subprocess_call(self):
        from unittest import mock
        with mock.patch('socket.socket', side_effect=AssertionError('network')), \
                mock.patch('subprocess.Popen', side_effect=AssertionError('subprocess')):
            self.assertTrue(check(receipt())['ready'])


class ReadinessBinding(unittest.TestCase):
    def bind(self, readiness, required=('auth',), env='normal-mac', auth='mac-user', now=NOW):
        r = t.new_task('synthetic-ready', 'synthetic-ready', worker_kind='codex', owner='assistant', repo='synthetic')
        return e.bind_route(r, CODEX_ROUTE, source_pin='source:a', decision_ref='decision:synthetic',
                            readiness=readiness, required=required, environment_id=env, auth_context=auth, now=now)

    def test_ready_receipt_binds_and_travels_with_the_dispatch(self):
        r = self.bind(check(receipt()))
        bound = r['worker']['execution_route']['readiness']
        self.assertEqual((bound['environment_id'], bound['auth_context']), ('normal-mac', 'mac-user'))
        self.assertNotIn('ready', bound)
        dispatch = t.begin_dispatch(r, 'fresh', resume=False)
        self.assertEqual(dispatch['outbox'][0]['execution_route']['readiness'], bound)

    def test_forged_ready_flag_and_dropped_requirements_are_rechecked(self):
        forged = check(receipt('sandbox', 'sandbox-user', 'blocked'), env='sandbox', auth='sandbox-user')
        forged.update(ready=True, gaps={})
        with self.assertRaisesRegex(RuntimeError, 'blocked'):
            self.bind(forged, env='sandbox', auth='sandbox-user')
        narrow = check(receipt(), required=['auth'])
        with self.assertRaisesRegex(RuntimeError, 'messaging:team'):
            self.bind(narrow, required=['auth', 'messaging:team'])

    def test_binding_rechecks_context_and_freshness_before_dispatch(self):
        ready = check(receipt())
        with self.assertRaisesRegex(RuntimeError, 'mismatch'):
            self.bind(ready, env='sandbox')
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            self.bind(ready, now='2026-10-16T22:00:00+00:00')
        with self.assertRaises(ValueError):
            self.bind(ready, env=None)
        with self.assertRaises(ValueError):
            self.bind({'ready': True})

    def test_compatibility_path_records_no_environment_check(self):
        self.assertNotIn('readiness', task()['worker']['execution_route'])

    def test_only_declared_capabilities_gate_binding(self):
        ready = check(receipt(), required=['auth'])
        self.assertNotIn('db:fixture', json.dumps(ready))
        self.assertIn('readiness', self.bind(ready, required=['auth'])['worker']['execution_route'])
        with self.assertRaisesRegex(RuntimeError, 'db:fixture'):
            self.bind(ready, required=['auth', 'db:fixture'])

    def test_declared_preflight_without_readiness_fails_closed(self):
        for declared in ({'required': ['db:fixture']}, {'environment_id': 'normal-mac'},
                         {'auth_context': 'mac-user'}, {'now': NOW}):
            r = t.new_task('synthetic-ready', 'synthetic-ready', worker_kind='codex', owner='assistant', repo='synthetic')
            with self.subTest(declared=sorted(declared)), self.assertRaisesRegex(ValueError, 'readiness'):
                e.bind_route(r, CODEX_ROUTE, source_pin='source:a', decision_ref='decision:synthetic', **declared)


if __name__ == '__main__':
    unittest.main()
