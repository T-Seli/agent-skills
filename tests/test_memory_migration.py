import builtins
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_skills import memory_migration as mm

FIXTURE = Path(__file__).parent / 'fixtures' / 'memory_migration' / 'mem'


def tree_hash(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}


class MemoryMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.drafts = self.tmp / 'drafts'
        self.mem = FIXTURE.resolve()
        self.config = self.tmp / 'workers.json'
        self.write_config({'memory_dirs': [str(self.mem)], 'memory_migration_drafts': str(self.drafts)})

    def write_config(self, cfg):
        self.config.write_text(json.dumps(cfg))

    def classify(self, table):
        self.drafts.mkdir(parents=True, exist_ok=True)
        (self.drafts / mm.CLASSIFICATION).write_text(json.dumps({str(self.mem / k): v for k, v in table.items()}))

    def full_table(self):
        return {
            'review-rule.md': {'destination': 'skill', 'target': 'skills/implement/SKILL.md', 'reason': 'process rule'},
            'acme-billing.md': {'destination': 'knowledge', 'kind': 'lesson', 'scope': 'tenant:example', 'reason': 'domain fact'},
            'editor-pref.md': {'destination': 'memory', 'reason': 'personal preference'},
            'loose-note.md': {'destination': 'memory', 'reason': 'no frontmatter, pointer'},
        }

    def run_plan(self):
        with mock.patch.dict(os.environ, {'AGENT_SKILLS_CONFIG': str(self.config)}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return mm.main(['plan'])

    def test_each_destination_counted_and_rendered(self):
        self.classify(self.full_table())
        self.assertEqual(self.run_plan(), 0)
        plan = json.loads((self.drafts / mm.PLAN).read_text())
        self.assertEqual(plan['counts'], {'skill': 1, 'knowledge': 1, 'memory': 2, 'unclassified': 0})
        diff = (self.drafts / mm.DIFF).read_text()
        self.assertIn('\n-- [Review rule](review-rule.md)', diff)  # index line removed
        self.assertIn('\n-- [Acme billing fact]', diff)
        self.assertNotIn('\n-- [Editor preference]', diff)  # stays in memory
        self.assertIn('+++ b/skill/skills/implement/SKILL.md', diff)
        self.assertIn('Always run the linter', diff)
        self.assertIn('+++ b/knowledge/tenant:example', diff)
        self.assertIn('record(kind=lesson, id=acme-billing', diff)

    def test_unclassified_files_listed_and_exit_nonzero(self):
        self.assertEqual(self.run_plan(), 1)
        plan = json.loads((self.drafts / mm.PLAN).read_text())
        self.assertEqual(plan['counts']['unclassified'], 4)

    def test_file_without_frontmatter_is_inventoried(self):
        files = {f['name']: f for f in mm.inventory([self.mem])}
        self.assertFalse(files['loose-note.md']['frontmatter'])
        self.assertIsNone(files['loose-note.md']['type'])
        self.assertEqual(files['review-rule.md']['type'], 'feedback')
        self.assertNotIn('MEMORY.md', files)

    def test_missing_config_keys_name_both(self):
        for cfg in ({}, {'memory_dirs': [str(self.mem)]}):
            self.write_config(cfg)
            with self.assertRaises(SystemExit) as cm:
                self.run_plan()
            self.assertIn('memory_dirs', str(cm.exception))
            self.assertIn('memory_migration_drafts', str(cm.exception))

    def test_bad_classification_fails_loudly(self):
        for entry in ({'destination': 'skill', 'reason': 'x'},  # no target
                      {'destination': 'knowledge', 'reason': 'x', 'kind': 'lesson'},  # no scope
                      {'destination': 'memory', 'reason': 'a\nb'},
                      {'destination': 'elsewhere', 'reason': 'x'}):
            self.classify({**self.full_table(), 'editor-pref.md': entry})
            with self.assertRaises(SystemExit):
                self.run_plan()

    def test_classification_of_unknown_file_fails(self):
        self.classify({**self.full_table(), 'ghost.md': {'destination': 'memory', 'reason': 'x'}})
        with self.assertRaises(SystemExit):
            self.run_plan()

    def test_drafts_inside_memory_or_repo_refused(self):
        for bad in (self.mem / 'drafts', mm.REPO / 'drafts'):
            self.write_config({'memory_dirs': [str(self.mem)], 'memory_migration_drafts': str(bad)})
            with self.assertRaises(SystemExit):
                self.run_plan()

    def test_memory_is_read_only_and_writes_stay_in_drafts(self):
        self.classify(self.full_table())
        before = tree_hash(self.mem)
        opened = []
        real_open = io.open

        def spy(file, mode='r', *a, **kw):
            opened.append((None if isinstance(file, int) else Path(str(file)).resolve(), mode))
            return real_open(file, mode, *a, **kw)

        with mock.patch.object(io, 'open', spy), mock.patch.object(builtins, 'open', spy):
            self.assertEqual(self.run_plan(), 0)
        self.assertEqual(tree_hash(self.mem), before)
        memory_opens = [(p, m) for p, m in opened if p and self.mem in (p, *p.parents)]
        self.assertTrue(memory_opens)
        self.assertTrue(all(set(m) <= set('rbt') for _, m in memory_opens), memory_opens)
        writes = [p for p, m in opened if p and set(m) & set('wax+')]
        self.assertTrue(writes)
        self.assertTrue(all(self.drafts in p.parents for p in writes), writes)


if __name__ == '__main__':
    unittest.main()
