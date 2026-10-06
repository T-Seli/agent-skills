"""Synthetic Git fixtures for source manifests and release binding."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from agent_skills.code_state import code_state
from agent_skills.release_guard import capture_rollback, verify_release


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


class SafeguardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.email', 'test@example.invalid')
        git(self.root, 'config', 'user.name', 'Test')
        (self.root / 'source.py').write_text('one\n')
        (self.root / 'removed.py').write_text('old\n')
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'initial')
        self.reviewed = git(self.root, 'rev-parse', 'HEAD')

    def test_manifest_tracks_edits_deletes_renames_and_explicit_new_source(self):
        (self.root / 'source.py').write_text('two\n')
        (self.root / 'removed.py').rename(self.root / 'moved.py')
        (self.root / 'new.py').write_text('new\n')
        (self.root / 'secret.env').write_text('private')
        first = code_state(self.root, untracked=['new.py', 'moved.py'], excluded=['secret.env'])
        self.assertEqual(first, code_state(self.root, untracked=['moved.py', 'new.py'], excluded=['secret.env']))
        self.assertEqual([x['path'] for x in first['files']], ['moved.py', 'new.py', 'removed.py', 'source.py'])
        self.assertNotIn('secret.env', json.dumps(first))
        (self.root / 'new.py').write_text('changed\n')
        self.assertNotEqual(first['digest'], code_state(self.root, untracked=['new.py', 'moved.py'], excluded=['secret.env'])['digest'])
        with self.assertRaises(ValueError):
            code_state(self.root, untracked=['secret.env'])

    def test_release_requires_exact_reviewed_tree(self):
        git(self.root, 'commit', '--allow-empty', '-qm', 'record only')
        record = git(self.root, 'rev-parse', 'HEAD')
        self.assertFalse(verify_release(self.root, self.reviewed, record)['ok'])
        self.assertEqual(verify_release(self.root, self.reviewed, record)['reviewed_tree'],
                         verify_release(self.root, self.reviewed, record)['deployed_tree'])
        self.assertTrue(verify_release(self.root, self.reviewed, self.reviewed)['ok'])
        (self.root / 'source.py').write_text('other\n')
        git(self.root, 'add', 'source.py')
        git(self.root, 'commit', '-qm', 'unreviewed change')
        descendant = git(self.root, 'rev-parse', 'HEAD')
        result = verify_release(self.root, self.reviewed, descendant)
        self.assertFalse(result['ok'])
        self.assertNotEqual(result['reviewed_tree'], result['deployed_tree'])

    def test_first_rollback_capture_survives_retry(self):
        receipt = self.root / 'rollback.json'
        first = capture_rollback(receipt, {'target-a': 'old-a'})
        self.assertEqual(first, capture_rollback(receipt, {'target-a': 'new-a'}))
        self.assertEqual(first['rollback'], {'target-a': 'old-a'})


if __name__ == '__main__':
    unittest.main()

class HardenedSafeguardTests(SafeguardTests):
    def test_unresolved_untracked_requires_disposition(self):
        (self.root / 'new.py').write_text('x')
        with self.assertRaises(ValueError):
            code_state(self.root)
        self.assertTrue(code_state(self.root, untracked=['new.py'])['digest'])
        with self.assertRaises(ValueError):
            code_state(self.root, excluded=['new.py'])

    def test_external_parent_and_final_symlinks_rejected(self):
        outside = Path(self.tmp.name).parent / 'outside-source-safeguard'
        outside.mkdir(exist_ok=True)
        (outside / 'x.py').write_text('x')
        (self.root / 'linked').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            code_state(self.root, untracked=['linked/x.py'])
        (self.root / 'alias.py').symlink_to(outside / 'x.py')
        with self.assertRaises(ValueError):
            code_state(self.root, untracked=['alias.py'])
        (self.root / 'linked').unlink()
        (self.root / 'alias.py').unlink()
        (outside / 'x.py').unlink()
        outside.rmdir()

    def test_hidden_config_and_executable_mode_affect_digest(self):
        (self.root / '.build.yml').write_text('a')
        git(self.root, 'add', '.build.yml')
        before = code_state(self.root)['digest']
        (self.root / '.build.yml').write_text('b')
        self.assertNotEqual(before, code_state(self.root)['digest'])
        before = code_state(self.root)['digest']
        (self.root / 'source.py').chmod(0o755)
        self.assertNotEqual(before, code_state(self.root)['digest'])

    def test_release_rejects_ref_alias(self):
        with self.assertRaises(ValueError):
            verify_release(self.root, 'HEAD', self.reviewed)
        with self.assertRaises(ValueError):
            verify_release(self.root, self.reviewed, 'HEAD')

    def test_receipt_identity_integrity_and_symlink(self):
        receipt = self.root / 'receipt.json'
        capture_rollback(receipt, {'a': 'old'}, task='task-1', release=self.reviewed, repository='repo-1')
        with self.assertRaises(ValueError):
            capture_rollback(receipt, {'b': 'old'}, task='task-1', release=self.reviewed, repository='repo-1')
        with self.assertRaises(ValueError):
            capture_rollback(receipt, {'a': 'new'}, task='task-2', release=self.reviewed, repository='repo-1')
        receipt.write_text('{')
        with self.assertRaises(ValueError):
            capture_rollback(receipt, {'a': 'old'}, task='task-1', release=self.reviewed, repository='repo-1')
        receipt.unlink()
        target = self.root / 'other.json'
        target.write_text('{}')
        receipt.symlink_to(target)
        with self.assertRaises(ValueError):
            capture_rollback(receipt, {'a': 'old'}, task='task-1', release=self.reviewed, repository='repo-1')

class CommandGateTests(SafeguardTests):
    def test_failed_release_command_prevents_following_action(self):
        from sys import executable
        marker = self.root / 'deployed'
        command = [executable, '-m', 'agent_skills.safeguard_cli', 'release',
                   str(self.root), self.reviewed, 'HEAD']
        checked = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True)
        if checked.returncode == 0:
            marker.write_text('ran')
        self.assertNotEqual(checked.returncode, 0)
        self.assertFalse(marker.exists())

    def test_concurrent_first_capture_is_complete(self):
        from concurrent.futures import ThreadPoolExecutor
        receipt = self.root / 'concurrent.json'
        def capture(ref):
            return capture_rollback(receipt, {'a': ref}, task='t', release='r', repository='repo')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(capture, ['old-1', 'old-2']))
        self.assertEqual(results[0], results[1])
        self.assertIn(results[0]['rollback']['a'], {'old-1', 'old-2'})

class IndependentMissTests(SafeguardTests):
    def test_ignored_source_cannot_keep_review_digest(self):
        (self.root / '.gitignore').write_text('generated.py\n')
        git(self.root, 'add', '.gitignore')
        (self.root / 'generated.py').write_text('first\n')
        with self.assertRaises(ValueError):
            code_state(self.root)
        first = code_state(self.root, untracked=['generated.py'])['digest']
        (self.root / 'generated.py').write_text('second\n')
        self.assertNotEqual(first, code_state(self.root, untracked=['generated.py'])['digest'])
        with self.assertRaises(ValueError):
            code_state(self.root, excluded=['generated.py'])

    def test_tracked_sensitive_source_fails_complete_review_without_reading(self):
        folder = self.root / 'credentials'
        folder.mkdir()
        (folder / 'config.py').write_text('first\n')
        git(self.root, 'add', 'credentials/config.py')
        with self.assertRaises(ValueError):
            code_state(self.root)
        (folder / 'config.py').write_text('second\n')
        with self.assertRaises(ValueError):
            code_state(self.root)
