import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from sys import executable

from agent_skills.release_reconciliation import reconcile_release


COMMIT = 'a' * 40
TREE = 'b' * 40
OLD_COMMIT = 'c' * 40
OLD_TREE = 'd' * 40
BODY = 'e' * 64


def observation(state='verified', commit=COMMIT, tree=TREE, receipt='receipt:1', *,
                dimension='loaded', session='session-1', body=BODY, checkpoint='resume'):
    if state != 'verified':
        commit = tree = session = body = checkpoint = None
    elif dimension == 'installed':
        session = body = None
    return {'state': state, 'commit': commit, 'tree': tree, 'receipt_ref': receipt,
            'session_id': session, 'body_sha256': body, 'checkpoint': checkpoint}


def manifest():
    return {'schema_version': 1, 'targets': [
        {'id': 'local', 'adapter': 'codex', 'runtime': 'codex-cli',
         'activation': 'native-installer', 'required': True,
         'manual_action': None, 'unsupported_reason': None},
        {'id': 'cloud', 'adapter': 'codex', 'runtime': 'saved-cloud-task',
         'activation': 'manual-republish', 'required': True,
         'manual_action': 'Republish, then verify a fresh task.', 'unsupported_reason': None},
        {'id': 'dot', 'adapter': 'dot', 'runtime': 'host-built-in',
         'activation': 'unsupported', 'required': False,
         'manual_action': None, 'unsupported_reason': 'No supported interface.'}]}


def state():
    target = {'active_task': False, 'rollback_ref': 'release:old',
              'current_session_id': 'session-1', 'expected_body_sha256': BODY,
              'installed': observation(dimension='installed'), 'loaded': observation(),
              'behavior_verified': observation()}
    return {'schema_version': 1, 'checkpoint': 'resume',
            'desired': {'source': 'owner/repo', 'commit': COMMIT, 'tree': TREE},
            'targets': {'local': dict(target), 'cloud': dict(target),
                        'dot': {'active_task': False, 'rollback_ref': None,
                                'current_session_id': 'not-applicable', 'expected_body_sha256': None,
                                'installed': observation('unavailable'),
                                'loaded': observation('unavailable'),
                                'behavior_verified': observation('unavailable')}}}


class ReleaseReconciliationTests(unittest.TestCase):
    def test_exact_declared_target_set_can_verify(self):
        result = reconcile_release(manifest(), state())
        self.assertTrue(result['system_wide'])
        self.assertEqual(result['claim'], 'verified-for-declared-target-set')
        self.assertFalse(result['targets']['dot']['ready'])
        self.assertEqual(result['exceptions'][0]['kind'], 'unsupported')

    def test_manual_cloud_pending_blocks_system_wide_claim(self):
        value = state()
        value['targets']['cloud']['installed'] = observation('pending', receipt='ui:pending')
        value['targets']['cloud']['loaded'] = observation('unknown', receipt=None)
        value['targets']['cloud']['behavior_verified'] = observation('unknown', receipt=None)
        result = reconcile_release(manifest(), value)
        self.assertFalse(result['system_wide'])
        self.assertEqual(result['targets']['cloud']['next_action'], 'Republish, then verify a fresh task.')
        self.assertIn('manual', {item['kind'] for item in result['exceptions']})

    def test_active_task_keeps_loaded_pin_and_reports_drift(self):
        value = state()
        value['targets']['local']['active_task'] = True
        value['targets']['local']['loaded'] = observation(commit=OLD_COMMIT, tree=OLD_TREE)
        value['targets']['local']['behavior_verified'] = observation('unknown', receipt=None)
        result = reconcile_release(manifest(), value)
        local = result['targets']['local']
        self.assertTrue(local['safe_continuation'])
        self.assertIn('continue-active-task', local['next_action'])
        self.assertEqual(result['drift'][0]['dimension'], 'loaded')
        self.assertFalse(result['system_wide'])

    def test_stale_session_or_body_receipt_remains_unverified(self):
        value = state()
        value['targets']['local']['loaded'] = observation(session='old-session')
        result = reconcile_release(manifest(), value)
        self.assertEqual(result['targets']['local']['loaded']['reconciled_state'], 'stale-receipt')
        self.assertFalse(result['system_wide'])
        value = state()
        value['targets']['local']['behavior_verified'] = observation(body='f' * 64)
        result = reconcile_release(manifest(), value)
        self.assertEqual(result['targets']['local']['behavior_verified']['reconciled_state'], 'stale-receipt')

    def test_repeated_checkpoint_is_deterministic_and_creates_no_watch(self):
        first = reconcile_release(manifest(), state())
        second = reconcile_release(manifest(), state())
        self.assertEqual(first, second)
        self.assertEqual(first['watch_policy'], 'no-scheduler-created; reuse-existing-monitor-identity')

    def test_missing_or_extra_target_fails_closed(self):
        value = state()
        value['targets'].pop('cloud')
        with self.assertRaisesRegex(ValueError, 'declared target set exactly'):
            reconcile_release(manifest(), value)
        value = state()
        value['targets']['other'] = value['targets']['local']
        with self.assertRaisesRegex(ValueError, 'declared target set exactly'):
            reconcile_release(manifest(), value)

    def test_cli_returns_nonzero_until_every_required_target_verified(self):
        value = state()
        value['targets']['cloud']['installed'] = observation('pending')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = root / 'manifest.json', root / 'state.json'
            manifest_path.write_text(json.dumps(manifest()))
            state_path.write_text(json.dumps(value))
            run = subprocess.run([executable, '-m', 'agent_skills.safeguard_cli', 'reconcile',
                                  str(manifest_path), str(state_path)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertFalse(json.loads(run.stdout)['system_wide'])


if __name__ == '__main__':
    unittest.main()
