"""safeguard-cli disk-check: free space on the volume holding a path, against warn and hard-stop floors."""
import contextlib
import io
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

    def test_ok_above_warn_floor(self):
        code, out, _, stat = run(self.dir.name, 12)
        self.assertEqual((code, out), (0, f'disk ok: 12.0 GB free on {self.dir.name} (warn below 10 GB, stop below 5.4 GB)\n'))
        stat.assert_called_once_with(self.dir.name)

    def test_warn_below_warn_floor_has_distinct_code(self):
        code, out, _, _ = run(self.dir.name, 8)
        self.assertEqual(code, 10)
        self.assertTrue(out.startswith('disk warn: 8.0 GB free'))

    def test_hard_stop_below_hard_floor_has_distinct_code(self):
        code, out, _, _ = run(self.dir.name, 5.0)
        self.assertEqual(code, 20)
        self.assertTrue(out.startswith('disk stop: 5.0 GB free'))

    def test_exactly_at_floor_is_not_below_it(self):
        self.assertEqual(run(self.dir.name, 10)[0], 0)
        self.assertEqual(run(self.dir.name, 9.99)[0], 10)

    def test_missing_path_fails_loudly_without_probing(self):
        code, out, err, stat = run(pathlib.Path(self.dir.name) / 'nope', 50)
        self.assertEqual((code, out), (1, ''))
        self.assertIn('safeguard failed', err)
        stat.assert_not_called()

    def test_other_volume_path_is_measured_not_root(self):
        calls = []

        def fake(path):
            calls.append(path)
            return vfs(3 if path.startswith('/Volumes/other') else 90)
        with mock.patch('os.path.exists', return_value=True), mock.patch('os.statvfs', side_effect=fake):
            self.assertEqual(disk_check.check('/Volumes/other/work', {})[0], 20)
            self.assertEqual(disk_check.check('/home/work', {})[0], 0)
        self.assertEqual(calls, ['/Volumes/other/work', '/home/work'])

    def test_floors_come_from_machine_config(self):
        with mock.patch('os.statvfs', return_value=vfs(15)):
            code, line = disk_check.check(self.dir.name, {'disk_warn_gb': 20, 'disk_hard_stop_gb': 1})
        self.assertEqual(code, 10)
        self.assertIn('warn below 20 GB, stop below 1 GB', line)

    def test_bad_floor_config_fails_loudly(self):
        with self.assertRaises(ValueError):
            disk_check.check(self.dir.name, {'disk_warn_gb': 2, 'disk_hard_stop_gb': 5})


class DiskCheckTextTests(unittest.TestCase):
    MARKERS = {
        'skills/implement/SKILL.md': ('safeguard-cli disk-check',),
        'skills/test-review/SKILL.md': ('safeguard-cli disk-check',),
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
