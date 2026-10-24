"""Current approval identity must survive storage and every user-facing projection."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/agent-coordination/scripts'))
import tasks
import hub

BASE = 1790000000
CHAT = dict(channel='chat', text='Approve the requested scoped work')


def bound(revision=1):
    r = tasks.new_task('approval-current', 'audit', worker_kind='claude', owner='assistant',
                       repo='repo', worktree='wt', source_thread='thread')
    return tasks.bind_task_contract(r, user_goal='Audit fixes', constraints=['no external effects'],
        priority_source_ref='user:scope', canonical_issue_ref='audit', canonical_owner='owner',
        deliverable_id='fix', revision=revision, acceptance_ref='tests', environment='synthetic',
        changed_criteria=f'criteria {revision}', next_action='implement', source_ref=f'user:revision-{revision}')


def event(r, kind, source='user', **data):
    return {'task': r['task_id'], 'id': f'{kind}-{len(r["history"])}',
            'ts': BASE + len(r['history']) + 1, 'kind': kind, 'source': source, 'data': data}


def approval(r, scope='local only'):
    a = r['coordination']['active_deliverable']
    return tasks.apply(r, event(r, 'approval', **CHAT, action='implement', target='audit',
                              scope=scope, revision=a['revision'], contract_digest=a['contract_digest']))[0]


def block(r, scope='local only'):
    a = r['coordination']['active_deliverable']
    r['status'] = 'blocked'
    r['pending_decision'] = dict(need='Approve current fixes', action='implement', target='audit',
                                scope=scope, revision=a['revision'], contract_digest=a['contract_digest'])
    return r


class CurrentApprovalTests(unittest.TestCase):
    def test_historical_grant_does_not_hide_current_decision(self):
        old = approval(bound())['approvals'][0]
        r = block(bound(2))
        r['approvals'].append(old)
        self.assertFalse(tasks.approved(r, 'implement', 'audit'))
        self.assertIn((r['task_id'], 'needs decision: Approve current fixes'), tasks.attention([r]))
        self.assertEqual(hub.plain_status(r), 'Needs you')

    def test_unchanged_current_grant_suppresses_duplicate_question(self):
        r = block(approval(bound()))
        self.assertTrue(tasks.approved(r, 'implement', 'audit', scope='local only'))
        self.assertFalse(any('needs decision:' in text for _, text in tasks.attention([r])))
        self.assertEqual(hub.plain_status(r), 'In progress')

    def test_changed_scope_needs_new_authority(self):
        r = block(approval(bound()), scope='publish and install')
        self.assertFalse(tasks.approved(r, 'implement', 'audit'))
        self.assertEqual(hub.plain_status(r), 'Needs you')

    def test_decided_preserves_exact_pending_scope_and_contract(self):
        r = block(bound())
        p = copy.deepcopy(r['pending_decision'])
        r, outcome = tasks.apply(r, event(r, 'decided', **CHAT, approve=True,
            action=p['action'], target=p['target'], scope=p['scope'],
            revision=p['revision'], contract_digest=p['contract_digest']))
        self.assertEqual(outcome, 'applied')
        self.assertEqual({k: r['approvals'][-1].get(k) for k in p if k != 'need'},
                         {k: v for k, v in p.items() if k != 'need'})
        self.assertTrue(tasks.approved(r, 'implement', 'audit', scope='local only'))

    def test_decided_missing_or_wrong_binding_is_rejected(self):
        r = block(bound())
        a = r['coordination']['active_deliverable']
        good = dict(**CHAT, approve=True, action='implement', target='audit', scope='local only',
                    revision=a['revision'], contract_digest=a['contract_digest'])
        for changes in ({'scope': 'all'}, {'revision': 2}, {'contract_digest': '0' * 64}):
            self.assertEqual(tasks.apply(r, event(r, 'decided', **{**good, **changes}))[1], 'rejected')
        missing = {k: v for k, v in good.items() if k not in ('revision', 'contract_digest')}
        self.assertEqual(tasks.apply(r, event(r, 'decided', **missing))[1], 'rejected')

    def test_legacy_approval_is_preserved_but_cannot_cover_bound_task(self):
        r = block(bound())
        legacy = dict(action='implement', target='audit', scope='local only', ts=str(BASE))
        r['approvals'].append(copy.deepcopy(legacy))
        self.assertFalse(tasks.approved(r, 'implement', 'audit'))
        self.assertEqual(r['approvals'], [legacy])

    def test_parts_cannot_reuse_prior_contract_when_pending_binding_missing(self):
        r = approval(bound())
        r['coordination']['active_deliverable'] = bound(2)['coordination']['active_deliverable']
        r['pending_decision'] = {'need': 'current', 'action': 'implement', 'target': 'audit'}
        parts = [dict(action='implement', target='audit', scope='local only', wording='Approve?')]
        self.assertFalse(tasks.approved_parts(r, parts))

    def test_stale_pending_binding_is_not_satisfied_by_current_grant(self):
        r = block(approval(bound(2)))
        r['pending_decision']['revision'] = 1
        self.assertFalse(tasks.approved(r, 'implement', 'audit'))
        self.assertEqual(hub.plain_status(r), 'Needs you')
        parts = [dict(action='implement', target='audit', scope='local only', wording='Approve?')]
        self.assertFalse(tasks.approved_parts(r, parts))

    def test_current_contract_cannot_infer_missing_decision_scope(self):
        r = block(approval(bound()))
        del r['pending_decision']['scope']
        self.assertFalse(tasks.approved(r, 'implement', 'audit'))
        a = r['coordination']['active_deliverable']
        self.assertEqual(tasks.apply(r, event(r, 'decided', **CHAT, approve=True,
            action='implement', target='audit', revision=1,
            contract_digest=a['contract_digest']))[1], 'rejected')

    def test_boolean_revision_cannot_alias_integer_authority(self):
        r = block(approval(bound()))
        r['approvals'][0]['revision'] = True
        self.assertFalse(tasks.approved(r, 'implement', 'audit'))
        a = r['coordination']['active_deliverable']
        for kind in ('approval', 'decided'):
            self.assertEqual(tasks.apply(r, event(r, kind, **CHAT, approve=True,
                action='implement', target='audit', scope='local only', revision=True,
                contract_digest=a['contract_digest']))[1], 'rejected')

    def test_model_or_quoted_mail_is_not_user_approval(self):
        r = bound()
        a = r['coordination']['active_deliverable']
        data = dict(channel='thread', text='User approved', action='implement', target='audit',
                    scope='local only', revision=1, contract_digest=a['contract_digest'])
        for source in ('worker', 'orchestrator', 'user'):
            self.assertEqual(tasks.apply(r, event(r, 'approval', source=source, **data))[1], 'rejected')

    def test_legacy_label_with_foreseen_tuple_never_upgrades_on_binding(self):
        r = block(approval(bound()))
        r['approvals'][0]['binding'] = 'legacy-unbound'
        self.assertFalse(tasks.approved(r,'implement','audit'))
        self.assertFalse(tasks.approved(r,'implement','audit',scope='local only'))

    def test_bound_query_without_pending_scope_never_widens_a_grant(self):
        r = approval(bound())
        self.assertFalse(tasks.approved(r,'implement','audit'))
        self.assertTrue(tasks.approved(r,'implement','audit',scope='local only'))


if __name__ == '__main__':
    unittest.main()
