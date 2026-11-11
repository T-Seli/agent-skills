"""Native links and stable material updates without external publication."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from agent_skills.work_trace import validate, preview
from test_issues_cli import work_record, REPO, FakeGh, run


class WorkTrace(unittest.TestCase):
    def test_native_commit_pr_issue_owner_session_decisions_and_next_action(self):
        record=work_record(8); result=preview(record)
        self.assertFalse(result['published'])
        for value in (record['issue_url'],record['source_issue_url'],record['owner'],
                      record['executor']['session_ref'],record['artifacts'][0]['pr_url'],
                      f"https://github.com/{REPO}/commit/{record['artifacts'][0]['commit']}",
                      record['decisions'][0],record['verification'][0],record['next_action']['action']):
            self.assertIn(value,result['body'])
        self.assertIn('deployment: unverified',result['body'])
        self.assertIn('acceptance: open',result['body'])

    def test_observation_clocks_do_not_create_duplicate_material_updates(self):
        before=work_record(8);after=copy.deepcopy(before);after['observed_at']='later-source-observation'
        self.assertEqual(preview(before)['fingerprint'],preview(after)['fingerprint'])
        after['artifacts'][0]['commit']='b'*40
        self.assertNotEqual(preview(before)['fingerprint'],preview(after)['fingerprint'])

    def test_wrong_issue_missing_session_short_commit_or_mismatched_pr_links_refuse(self):
        for change in ('issue','session','commit','pr','owner','proof'):
            r=work_record(8)
            if change=='issue':r['issue_url']=f'https://github.com/{REPO}/issues/9'
            if change=='session':r['executor']['session_ref']=''
            if change=='commit':r['artifacts'][0]['commit']='short'
            if change=='pr':r['artifacts'][0]['pr_url']='https://github.com/other/repo/pull/12'
            if change=='owner':r['owner']=''
            if change=='proof':r['verification']=[]
            with self.subTest(change=change),self.assertRaises(ValueError):validate(r,REPO,8)

    def test_claude_and_codex_share_same_contract_and_unknown_pr_is_explicit(self):
        for host in ('Claude Code','Codex','paired coordinator'):
            r=work_record(8);r['executor']['host']=host
            r['artifacts'][0].update(pr_url=None,pr_state='unverified')
            result=preview(r);self.assertIn('PR unverified',result['body']);self.assertFalse(result['published'])

    def test_preview_same_record_suppresses_repeat_without_any_github_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'record.json';p.write_text(json.dumps(work_record(8)))
            gh=FakeGh()
            code,out,_=run(gh,'status-preview','--work-record',str(p))
            self.assertEqual(code,0);first=json.loads(out);self.assertTrue(first['changed'])
            code,out,_=run(gh,'status-preview','--work-record',str(p),'--previous-fingerprint',first['fingerprint'])
            self.assertEqual(code,0);self.assertFalse(json.loads(out)['changed']);self.assertEqual(gh.calls,[])


if __name__=='__main__':unittest.main()
