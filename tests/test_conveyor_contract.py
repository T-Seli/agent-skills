"""Conveyor contract (Wave 0): conveyor.md, conveyor.json, authorizations.json and § Defaults agree."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WC = ROOT / 'skills/workflow-contracts'
def text(p): return p.read_text(encoding='utf-8')
CONVEYOR, SCHEMA = text(WC / 'conveyor.md'), json.loads(text(WC / 'conveyor.json'))
AUTH = json.loads(text(ROOT / 'authorizations.json'))
DEFAULTS = text(WC / 'contracts.md').split('## Defaults', 1)[1]


class Conveyor(unittest.TestCase):
    def test_conveyor_md_fits_its_budget(self):
        self.assertLessEqual(len(CONVEYOR.encode()), 8192)

    def test_every_lane_is_in_the_table_in_order(self):
        names = [l['name'] for l in SCHEMA['lanes']]
        self.assertEqual(names, ['inbox', 'backlog', 'next', 'in-progress', 'in-review', 'ready-to-release', 'monitoring', 'closed'])
        rows = re.findall(r'^\| `([a-z-]+)` \|', CONVEYOR, re.M)
        self.assertEqual(rows, names)

    def test_every_required_receipt_is_defined_and_compiles(self):
        receipts = SCHEMA['receipts']
        for lane in SCHEMA['lanes']:
            for r in lane['requires']:
                self.assertIn(r, receipts, f"{lane['name']} needs undefined receipt {r}")
        for name, r in receipts.items():
            if 'pattern' in r:
                re.compile(r['pattern'])
        re.compile(SCHEMA['timeline']['pattern'])
        re.compile(SCHEMA['timeline']['correction'])
        self.assertEqual(sum(r == 'schedule' for l in SCHEMA['lanes'] for r in l['requires']), 2)

    def test_receipt_patterns_match_the_tokens_skills_write(self):
        r = SCHEMA['receipts']
        samples = {
            'claim': 'Claimed: branch `feat/x` · session local_1',
            'reviewed_yes': 'Reviewed: 863480b5d YES',
            'approved': 'Approved: deploy · box · 2026-11-18 20:40Z · coordinator msg 12 · "go"',
            'deploy': '## 2026-11-18 20:41Z — deploy: 863480b to box',
            'rollback': 'Rollback: box: 3bf92eb',
            'schedule': 'Scheduler: claude monitor-repo-x',
            'monitor_final': '## 2026-11-19 02:30Z — monitor: All working — first traffic',
            'learned': 'Learned: answered: which lane? => next',
            'implement_done': '## 2026-11-18 20:00Z — implement: done',
            'capture': 'Captured: 2026-11-18 20:00Z · source https://example.test/m/1',
            'done_when': 'Done when: the board shows it',
        }
        for name, sample in samples.items():
            self.assertTrue(re.search(r[name]['pattern'], sample, re.M), name)
        line = 'Conveyor: 2026-11-18 20:00Z · lane · in-progress → in-review · head 863480b · tests - · skills 863480b · schedules -'
        self.assertRegex(line, SCHEMA['timeline']['pattern'])

    def test_limits_live_only_in_defaults(self):
        self.assertRegex(DEFAULTS, r'- Lane limits: Build 8 .*Review 4 .*Release 1 train of ≤6 PRs.*Sessions 10')
        self.assertIn('- Review fallback: 2 hours', DEFAULTS)
        self.assertNotIn('Build 8', CONVEYOR)
        self.assertNotIn('limits', {k for l in SCHEMA['lanes'] for k in l} - {'limit'})

    def test_priority_never_collides_with_a_lane(self):
        lanes = {f"lane:{l['name']}" for l in SCHEMA['lanes']}
        self.assertFalse(lanes & set(SCHEMA['labels']['priority']))

    def test_authorizations_are_well_formed(self):
        ids = [e['id'] for e in AUTH['entries']]
        self.assertEqual(len(ids), len(set(ids)))
        for e in AUTH['entries']:
            self.assertEqual({'id', 'command', 'kind', 'mode', 'why'}, set(e))
            self.assertIn((e['kind'], e['mode']), {('bookkeeping', 'allow'), ('go', 'ask'), ('deny', 'deny')}, e['id'])
            self.assertTrue(e['command'].startswith('~/.agents/skills/workflow-contracts/scripts/'), e['id'])
        modes = {e['command'].split()[-1]: e['mode'] for e in AUTH['entries']}
        self.assertEqual(modes['run-approved'], 'ask')
        for gate in ('capture', 'prio', 'lane', 'decide', 'sweep', 'ask', 'brief'):
            self.assertEqual(modes[gate], 'allow', gate)

    def test_knowledge_interface_is_named(self):
        self.assertEqual(set(SCHEMA['knowledge']['commands']), {'pages', 'find', 'record', 'log', 'stale'})
        for k in ('none', 'lesson: x', 'page-fix: wiki/a.md: x'):
            self.assertRegex(f'Learned: {k}', SCHEMA['receipts']['learned']['pattern'])
        self.assertNotRegex('Learned: maybe', SCHEMA['receipts']['learned']['pattern'])
        self.assertIn('- Knowledge:', text(WC / 'project-CLAUDE-template.md'))

    def test_contracts_point_to_the_belt(self):
        self.assertIn('[conveyor.md](conveyor.md)', DEFAULTS)
        for link in ('[conveyor.json](conveyor.json)', '[issues.md](issues.md)', '[decisions.md](decisions.md)', 'authorizations.json'):
            self.assertIn(link, CONVEYOR)


if __name__ == '__main__':
    unittest.main()
