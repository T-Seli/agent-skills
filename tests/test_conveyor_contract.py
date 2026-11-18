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
R = SCHEMA['receipts']
SHA = '863480b5d'
S1, S2, S0 = (f'local_{i}{"0" * 7}-0000-4000-8000-{"0" * 12}' for i in (1, 2, 3))


def matches(name, sample):
    return re.search(R[name]['pattern'], sample, re.M)


class Lanes(unittest.TestCase):
    def test_conveyor_md_fits_its_budget(self):
        self.assertLessEqual(len(CONVEYOR.encode()), 8192)

    def test_every_lane_is_in_the_table_in_order(self):
        names = [l['name'] for l in SCHEMA['lanes']]
        self.assertEqual(names, ['inbox', 'backlog', 'next', 'in-progress', 'in-review', 'ready-to-release', 'monitoring', 'closed'])
        self.assertEqual(re.findall(r'^\| `([a-z-]+)` \|', CONVEYOR, re.M), names)

    def test_every_required_receipt_is_defined_and_compiles(self):
        for lane in SCHEMA['lanes']:
            for r in lane['requires'] + lane.get('requires_without_release', []):
                self.assertIn(r, R, f"{lane['name']} needs undefined receipt {r}")
        for r in R.values():
            if 'pattern' in r:
                re.compile(r['pattern'])
        for key in ('pattern', 'correction'):
            re.compile(SCHEMA['timeline'][key])

    def test_limits_live_only_in_defaults(self):
        self.assertRegex(DEFAULTS, r'- Lane limits: Build 8 .*Review 4 .*Release 1 train of ≤6 PRs.*Sessions 10')
        self.assertIn('- Review fallback: 2 hours', DEFAULTS)
        self.assertNotIn('Build 8', CONVEYOR)
        limits = {l['limit'] for l in SCHEMA['lanes'] if 'limit' in l}
        self.assertEqual(limits, {'Build', 'Review'})  # each named limit has a number in § Defaults
        self.assertEqual(SCHEMA['lanes'][2]['room'], 'free Build slots')

    def test_priority_never_collides_with_a_lane(self):
        lanes = {f"lane:{l['name']}" for l in SCHEMA['lanes']}
        self.assertFalse(lanes & set(SCHEMA['labels']['priority']))


class Receipts(unittest.TestCase):
    def test_patterns_match_the_tokens_written(self):
        samples = {
            'claim': f'Claimed: branch `feat/x` · session {S1}',
            'owner': f'Owner: T-Seli · session {S1} · 2026-11-18 20:00Z',
            'reviewed_yes': f'Reviewed: {SHA} YES',
            'reviewer': f'Reviewer: session {S2} · head {SHA} · fallback',
            'review_requested': f'Review requested: head {SHA} · 2026-11-18 20:00Z · session {S1}',
            'approved': f'Approved: release r12 · digest {"a" * 64} · 2026-11-18 20:40Z · question https://x.test/q/1 · session {S0}',
            'deploy': f'## 2026-11-18 20:41Z — deploy: {SHA} to box',
            'rollback': 'Rollback: box: 3bf92eb',
            'schedule': 'Scheduler: claude monitor-repo-x',
            'monitor_first': 'Monitor verdict: first-traffic All working · 2026-11-18 21:00Z',
            'monitor_24h': 'Monitor verdict: 24h Working, with issues · 2026-11-19 21:00Z',
            'monitor_deleted': 'Scheduler deleted: claude monitor-repo-x',
            'decision': f'Decision: ship Friday · 2026-11-18 20:00Z · question https://x.test/q/2 · session {S0}',
            'asked_more': 'Asked for more: 2026-11-18 20:00Z · question https://x.test/q/2',
            'learned': 'Learned: answered: which lane? => next',
            'implement_done': '## 2026-11-18 20:00Z — implement: done',
            'capture': 'Captured: 2026-11-18 20:00Z · source https://x.test/m/1',
            'done_when': 'Done when: the board shows it',
            'pushed': f'Pushed: {SHA} to main',
            'failed': 'Failed: release r12 · 2026-11-18 20:41Z · push refused',
            'no_release': 'No release: answered · the board already shows it',
            'parked': 'Parked: waiting on the user · until 2026-11-20 · 2026-11-18 20:00Z · next pick a vendor',
            'source_key': 'Source-key: tracker-sheet:0123456789abcdef',
        }
        for name, sample in samples.items():
            self.assertTrue(matches(name, sample), name)
        for cmd in ('publish', 'claim', 'close', 'lane', 'feed', 'park'):
            line = f'Conveyor: 2026-11-18 20:00Z · {cmd} · next → in-progress · head {SHA} · tests - · skills {SHA} · schedules -'
            self.assertRegex(line, SCHEMA['timeline']['pattern'])

    def test_approved_carries_a_digest_and_no_quoted_words(self):
        self.assertFalse(matches('approved', 'Approved: deploy · box · 2026-11-18 20:40Z · msg 12 · "go"'))
        self.assertFalse(matches('approved', f'Approved: shell r1 · digest {"a" * 64} · 2026-11-18 20:40Z · question https://x.test/q · session s'))

    def test_close_needs_both_verdicts_and_deleted_monitors(self):
        closed = SCHEMA['lanes'][-1]['requires']
        self.assertEqual(sorted(closed), sorted(['monitor_first', 'monitor_24h', 'monitor_deleted', 'monitor_deleted', 'learned']))
        self.assertFalse(matches('monitor_first', '## x — monitor: All working — first traffic'))
        self.assertFalse(matches('monitor_24h', 'Monitor verdict: 24h Regression found · 2026-11-19 21:00Z'))

    def test_gates_read_only_the_issue_and_label_every_receipt(self):
        for name, r in R.items():
            self.assertTrue(r.get('label'), name)
            self.assertNotEqual(r.get('source'), 'log', name)
        self.assertIn('--log', SCHEMA['receipt_home']['log_copies'])
        self.assertIn('Gates read receipts only from the issue', CONVEYOR)

    def test_sessions_use_the_archive_tool_form(self):
        self.assertTrue(matches('reviewer', f'Reviewer: session 1f72e626-fa54-4e3b-8577-2dc51614f5c2 · head {SHA} · fallback'))
        self.assertFalse(matches('claim', 'Claimed: branch `feat/x` · session local_1'))
        self.assertRegex(S1, SCHEMA['session_id']['pattern'])
        self.assertEqual(SCHEMA['registry']['guards'], {'registry_done': 'allow', 'registry_unfinished': 'deny', 'outside_registry': 'ask'})

    def test_items_without_a_release_can_close_and_a_push_is_no_deploy(self):
        closed = SCHEMA['lanes'][-1]
        self.assertEqual(closed['requires_without_release'], ['no_release', 'learned'])
        self.assertEqual(R['landed']['any_of'], ['deploy', 'pushed'])
        self.assertIn('never deploy:', SCHEMA['action_record']['kinds']['release'])
        self.assertNotIn('sweep', SCHEMA['lanes'][2]['called_at'].split('(')[0])
        self.assertEqual(R['no_release']['refused_if'], ['pushed', 'deploy'])
        self.assertIn('names no target other than branches', R['landed']['pushed_only_if'])

    def test_resume_rebuilds_the_picture(self):
        r = SCHEMA['resume']
        self.assertEqual(r['cap'], {'lines': 60, 'chars': 10000})
        self.assertTrue(re.match(r['checkpoint']['pattern'], 'Checkpoint: 2026-11-18 23:00Z · tokens - · questions 2 · in-progress 3 · in-review 1 · parked 0'))
        self.assertEqual(set(r['hooks']), {'SessionStart', 'PreCompact'})
        self.assertEqual(SCHEMA['roles']['config_key'], 'roles')
        self.assertIn('# Compact instructions', text(WC / 'project-CLAUDE-template.md'))

    def test_review_is_independent_of_the_builder(self):
        self.assertEqual(R['reviewer']['not_equal'], 'claim.session')
        self.assertIn('reviewer', SCHEMA['lanes'][5]['requires'])

    def test_decisions_are_never_a_go(self):
        self.assertEqual(set(SCHEMA['never_a_go']), {'decision', 'asked_more'})
        self.assertFalse(matches('decision', 'Decision: ship Friday · 2026-11-18 20:00Z'))
        for lane in SCHEMA['lanes']:
            self.assertFalse(set(lane['requires']) & set(SCHEMA['never_a_go']), lane['name'])


class ActionsAndCards(unittest.TestCase):
    def test_action_record_is_parameters_only(self):
        a = SCHEMA['action_record']
        self.assertEqual(set(a['kinds']), {'release', 'rollback', 'skills-install'})
        for f in ('kind', 'id', 'train', 'tree', 'targets', 'rollback', 'prepared_by', 'prepared_at', 'expires_at', 'digest_input', 'digest', 'used_at'):
            self.assertIn(f, a['fields'])
        self.assertEqual(set(a['refusals']), {'unknown-kind', 'moved-head', 'expired', 'reused', 'digest-mismatch', 'hold', 'train-over-limit', 'not-ready', 'dirty-tree', 'non-branch-target'})
        self.assertIn('digest_input', a['fields']['rollback'])
        self.assertEqual(a['command_lines'], 'forbidden')
        self.assertIn('never applies', a['kinds']['skills-install'])
        self.assertIn('never runs a gated action that has no kind', CONVEYOR)
        kinds = re.search(r'\(\?P<kind>([^)]+)\)', R['approved']['pattern']).group(1).split('|')
        self.assertEqual(set(kinds), set(a['kinds']))

    def test_card_has_ten_fields_and_refuses_ids_first(self):
        c = SCHEMA['card']
        self.assertEqual(len(c['fields']), 10)
        self.assertEqual(c['max_lines'], 12)
        self.assertEqual(set(c['kinds']), {'go', 'choice'})
        self.assertTrue(set(c['ai_writes']) <= set(c['fields']))
        for bad in ('#17 ships the contract', 'PR 17 ships', 'PR #17 ships', f'{SHA} ships'):
            self.assertRegex(bad, c['refuse']['opens_with'])
        for ok in ('The belt contract ships', '2 PRs ship today', 'deadbeef is a word here', 'added to the train'):
            self.assertNotRegex(ok, c['refuse']['opens_with'], ok)
        self.assertIn('recommended', c['ai_writes'])
        self.assertIn('undo', c['script_fills'])
        self.assertIn('digest', c['go_shows'])
        self.assertEqual(set(SCHEMA['questions']), {'bookkeeping', 'go', 'choice'})

    def test_knowledge_interface_is_named(self):
        k = SCHEMA['knowledge']
        self.assertEqual(set(k['functions']), {'pages', 'find', 'domains', 'record', 'collect', 'log', 'stale', 'lint', 'changes'})
        self.assertEqual(k['module'], 'agent_skills.knowledge')
        self.assertEqual(k['functions']['collect']['returns'], '{folded, branch}')
        self.assertTrue(k['functions']['record']['returns'].startswith('{path}'))
        self.assertIn('source', k['functions']['find']['returns'])
        for fn in ('pages', 'find', 'stale'):
            self.assertIn('store', k['functions'][fn]['returns'])
        for s in ('none', 'lesson: x', 'page-fix: wiki/a.md: x'):
            self.assertTrue(matches('learned', f'Learned: {s}'), s)
        self.assertFalse(matches('learned', 'Learned: maybe'))
        self.assertIn('- Knowledge:', text(WC / 'project-CLAUDE-template.md'))
        self.assertNotRegex(CONVEYOR, r'`domain:(?!\*)[a-z]')
        self.assertIn('outside review is off for the brain', CONVEYOR)


class Authorizations(unittest.TestCase):
    def test_entries_are_well_formed(self):
        ids = [e['id'] for e in AUTH['entries']]
        self.assertEqual(len(ids), len(set(ids)))
        for e in AUTH['entries']:
            self.assertTrue({'id', 'tool', 'match', 'kind', 'mode', 'why'} <= set(e) <= {'id', 'tool', 'match', 'kind', 'mode', 'why', 'guard'}, e['id'])
            self.assertIn(e['tool'], {'bash', 'mcp', 'edit'}, e['id'])
            self.assertIn((e['kind'], e['mode']), {('bookkeeping', 'allow'), ('go', 'ask'), ('deny', 'deny')}, e['id'])
            if 'guard' in e:
                self.assertRegex(e['guard'], r'^[a-z-]+-guard$', e['id'])

    def test_gates_are_allowed_and_the_go_is_one_click(self):
        mode = {e['match']: e['mode'] for e in AUTH['entries']}
        icli, scli = AUTH['invocation']['issues-cli'], AUTH['invocation']['safeguard-cli']
        for gate in ('capture', 'prio', 'publish', 'claim', 'lane', 'decide', 'ask', 'brief', 'sweep', 'close', 'feed', 'park', 'resume'):
            self.assertEqual(mode[f'{icli} {gate}'], 'allow', gate)
        self.assertEqual(mode[f'{scli} run-approved'], 'ask')
        self.assertEqual(mode[f'{scli} prepare-action'], 'allow')
        self.assertEqual([e['id'] for e in AUTH['entries'] if e['mode'] == 'ask'], ['run-approved'])
        self.assertTrue(any(e['mode'] == 'deny' and 'email' in e['why'] for e in AUTH['entries']))

    def test_one_invocation_form(self):
        self.assertIn(f"spelled exactly `{AUTH['invocation']['issues-cli']}`", text(WC / 'issues.md'))
        for e in AUTH['entries']:
            if 'scripts/' in e['match']:
                self.assertTrue(e['match'].split()[0] in AUTH['invocation'].values(), e['id'])

    def test_monitor_create_and_delete_are_guarded(self):
        guard = {e['id']: e.get('guard') for e in AUTH['entries']}
        self.assertEqual(guard['monitor-arm'], 'monitor-id-guard')
        self.assertEqual(guard['monitor-delete'], 'monitor-id-guard')
        self.assertEqual(guard['archive-done'], 'archive-guard')

    def test_installed_code_finds_contract_data_one_way(self):
        self.assertEqual(SCHEMA['layout']['module'], 'agent_skills.layout')
        self.assertIn('agent_skills.layout', CONVEYOR)
        self.assertRegex(DEFAULTS, r'- Time boxes: Build S 4 h, M 1 day')

    def test_contracts_point_to_the_belt(self):
        self.assertIn('[conveyor.md](conveyor.md)', DEFAULTS)
        for link in ('[conveyor.json](conveyor.json)', '[issues.md](issues.md)', '[decisions.md](decisions.md)', 'authorizations.json'):
            self.assertIn(link, CONVEYOR)
        self.assertIn('`Owner:` and `Claimed:` receipts', CONVEYOR)


if __name__ == '__main__':
    unittest.main()
