"""agent_skills.layout: contract data and release id in a release and in a checkout."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from agent_skills import layout


class Layout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'skills/workflow-contracts').mkdir(parents=True)
        (self.root / 'skills/workflow-contracts/conveyor.json').write_text('{}')

    def tearDown(self):
        self.tmp.cleanup()

    def test_installed_release_reads_the_pin_without_git(self):
        (self.root / '.release-pin.json').write_text(json.dumps({'commit': 'a' * 40, 'tree': 'b' * 40}))
        self.assertEqual(layout.release_id(self.root), 'a' * 40)
        self.assertEqual(layout.contract('conveyor.json', self.root), self.root / 'skills/workflow-contracts/conveyor.json')

    def test_checkout_without_pin_uses_head(self):
        git = ['git', '-C', str(self.root)]
        subprocess.run(git + ['init', '-q'], check=True)
        subprocess.run(git + ['-c', 'user.name=t', '-c', 'user.email=t@x', 'commit', '-q', '--allow-empty', '-m', 'x'], check=True)
        head = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(layout.release_id(self.root), head)

    def test_neither_pin_nor_checkout_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            layout.release_id(self.root)
        with self.assertRaises(FileNotFoundError):
            layout.contract('missing.json', self.root)

    def test_this_checkout_finds_the_real_contract(self):
        self.assertTrue(layout.contract('conveyor.json').is_file())


if __name__ == '__main__':
    unittest.main()
