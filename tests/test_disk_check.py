"""safeguard-cli disk-check: free space on the volume holding a path, against warn and hard-stop floors."""
import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from agent_skills import disk_check
from agent_skills.safeguard_cli import main

ROOT = pathlib.Path(__file__).resolve().parent.parent
GB = 1024 ** 3


def vfs(free_gb):
    return mock.Mock(f_bavail=int(free_gb * GB) // 4096, f_frsize=4096)


def run(path, free_gb):
    out, err = io.StringIO(), io.StringIO()
    env = {'AGENT_SKILLS_CONFIG': '/nonexistent/workers.json'}
    with mock.patch.dict(os.environ, env), mock.patch('os.statvfs', return_value=vfs(free_gb)) as stat, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(['disk-check', str(path)])
    return code, out.getvalue(), err.getvalue(), stat


class DiskCheckTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.real = os.path.realpath(self.dir.name)

    def test_ok_above_warn_floor(self):
        code, out, _, stat = run(self.dir.name, 12)
        self.assertEqual((code, out), (0, f'disk ok: 12.0 GB free on {self.real} (Worktree start free floor 10 GB)\n'))
        stat.assert_called_once_with(self.real)

    def test_below_floor_stops_with_distinct_code(self):
        code, out, _, _ = run(self.dir.name, 8)
        self.assertEqual(code, 20)
        self.assertTrue(out.startswith('disk stop: 8.0 GB free'))

    def test_floor_itself_is_ok_and_just_below_stops(self):
        self.assertEqual(run(self.dir.name, 10)[0], 0)
        self.assertEqual(run(self.dir.name, 9.99)[0], 20)

    def test_not_yet_created_path_is_measured_at_its_nearest_existing_ancestor(self):
        code, out, _, stat = run(pathlib.Path(self.dir.name) / 'new' / 'deeper', 50)
        self.assertEqual(code, 0)
        self.assertIn(f'on {self.real} ', out)
        stat.assert_called_once_with(self.real)

    def test_totally_missing_root_fails_loudly_without_probing(self):
        with mock.patch('os.path.exists', return_value=False), mock.patch('os.statvfs') as stat:
            with self.assertRaises(ValueError):
                disk_check.check('/gone/work', {})
        stat.assert_not_called()

    def test_symlinked_destination_is_measured_on_its_target_volume(self):
        main, low = pathlib.Path(self.real) / 'main', pathlib.Path(self.real) / 'low'
        (main / '.claude').mkdir(parents=True)
        low.mkdir()
        (main / '.claude' / 'worktrees').symlink_to(low)
        seen = []

        def fake(path):
            seen.append(path)
            return vfs(3 if path == str(low) else 90)
        with mock.patch('os.statvfs', side_effect=fake):
            self.assertEqual(disk_check.check(str(main), {})[0], 0)
            code, line = disk_check.check(str(main / '.claude' / 'worktrees' / 'new-slug'), {})
        self.assertEqual((code, seen), (20, [str(main), str(low)]))
        self.assertIn(str(low), line)

    def test_cli_checks_every_path_and_exits_with_the_worst(self):
        out = io.StringIO()
        with mock.patch('os.statvfs', side_effect=lambda p: vfs(3 if p.endswith('low') else 90)), \
                contextlib.redirect_stdout(out):
            os.makedirs(os.path.join(self.real, 'low'))
            code = main(['disk-check', self.real, os.path.join(self.real, 'low')])
        self.assertEqual(code, 20)
        self.assertEqual([l.split(':')[0] for l in out.getvalue().splitlines()], ['disk ok', 'disk stop'])

    def test_other_volume_path_is_measured_not_root(self):
        calls = []

        def fake(path):
            calls.append(path)
            return vfs(3 if path.startswith('/Volumes/other') else 90)
        with mock.patch('os.path.exists', return_value=True), mock.patch('os.path.realpath', side_effect=lambda p: p), \
                mock.patch('os.statvfs', side_effect=fake):
            self.assertEqual(disk_check.check('/Volumes/other/work', {})[0], 20)
            self.assertEqual(disk_check.check('/home/work', {})[0], 0)
        self.assertEqual(calls, ['/Volumes/other/work', '/home/work'])

    def test_floor_comes_from_machine_config(self):
        with mock.patch('os.statvfs', return_value=vfs(15)):
            self.assertEqual(disk_check.check(self.dir.name, {'worktree_start_free_gb': 20})[0], 20)
            self.assertEqual(disk_check.check(self.dir.name, {'worktree_start_free_gb': 1})[0], 0)

    def test_json_nan_and_infinity_floors_are_rejected_not_obeyed(self):
        for text in ('NaN', 'Infinity'):
            floor = json.loads(f'{{"worktree_start_free_gb": {text}}}')
            with self.subTest(text=text), mock.patch('os.statvfs', return_value=vfs(0.1)), self.assertRaises(ValueError):
                disk_check.check(self.dir.name, floor)

    def test_nonsensical_floor_config_fails_loudly(self):
        for bad in (-1, 'ten', True, None, float('nan'), float('inf'), float('-inf')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                disk_check.check(self.dir.name, {'worktree_start_free_gb': bad})


class DiskCheckTextTests(unittest.TestCase):
    MARKERS = {
        'skills/implement/SKILL.md': ('safeguard-cli disk-check "$MAIN" "$MAIN/.claude/worktrees/<slug>"', 'proceed only on exit 0', 'no helper: start nothing'),
        'skills/test-review/SKILL.md': ('safeguard-cli disk-check "$MAIN" <the worktree path below>', 'proceed only on exit 0', 'no helper: start nothing'),
        'skills/agent-coordination/scripts/delegate.py': ('disk_check', 'EXIT_STOP'),
        'skills/agent-coordination/references/workspace-and-train.md': ('disk-check',),
    }

    def test_callers_name_the_check(self):
        for path, markers in self.MARKERS.items():
            body = (ROOT / path).read_text()
            for marker in markers:
                with self.subTest(path=path, marker=marker):
                    self.assertIn(marker, body)


if __name__ == '__main__':
    unittest.main()
