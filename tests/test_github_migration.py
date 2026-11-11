"""Offline compatibility migration and caller integration: no real GitHub writes."""
import copy
import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_skills.github_migration import plan, apply_to_copy, policy_identity
from test_issues_cli import FakeGh, draft, run, REPO, evidence, SHA, work_record

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publisher_fixture_support', ROOT/'tests/test_pr_sweep.py')
SUPPORT = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(SUPPORT)


def legacy():
    return {'unrelated': {'sentinel': 'keep', 'other_policy': 3}, 'pr_sweep': {
        'repos':[{'repo':'o/a','checkout':'/src/a'}], 'authorization':'original legacy scope',
        'max_per_run':2, 'custom_sentinel':'retain'}}


def identity():
    return {'id':SUPPORT.ACTOR, 'login':'fixture-reviewer', 'source':'gh api user', 'observed_at':'2026-11-06T00:00:00Z'}


class Migration(unittest.TestCase):
    def test_conditional_overlay_preserves_all_existing_settings_and_never_enables_publish(self):
        original=legacy(); before=copy.deepcopy(original)
        migration=plan(original,identity(),socket.gethostname(),ROOT)
        staged=apply_to_copy(original,migration,ROOT)
        self.assertEqual(original,before); self.assertEqual(staged['unrelated'],before['unrelated'])
        for field in ('repos','authorization','max_per_run','custom_sentinel'):
            self.assertEqual(staged['pr_sweep'][field],before['pr_sweep'][field])
        self.assertEqual(staged['pr_sweep']['mode'],'shadow')
        self.assertEqual(staged['pr_sweep']['publication_authorization'],'')
        self.assertNotIn('original legacy scope',json.dumps(migration))
        self.assertNotIn('sentinel',json.dumps(migration))
        self.assertEqual(migration['pr_sweep_overlay']['review_policy'],policy_identity(ROOT)[0])

    def test_changed_config_policy_and_publish_tampering_refuse(self):
        source=legacy(); migration=plan(source,identity(),socket.gethostname(),ROOT)
        changed=copy.deepcopy(source);changed['unrelated']['other_policy']=4
        with self.assertRaisesRegex(ValueError,'configuration changed'):apply_to_copy(changed,migration,ROOT)
        for key,value in (('mode','publish'),('reviewer_id',999),('review_policy','stale')):
            bad=copy.deepcopy(migration);bad['pr_sweep_overlay'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):apply_to_copy(source,bad,ROOT)
        bad=copy.deepcopy(migration);bad['policy_files']['skills/test-review/SKILL.md']='stale'
        with self.assertRaisesRegex(ValueError,'policy source changed'):apply_to_copy(source,bad,ROOT)

    def test_changed_loaded_research_reference_invalidates_policy_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            files=set(policy_identity(ROOT)[1]) | {'skills/workflow-contracts/references/research.md'}
            for name in files:
                target=root/name; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/name).read_bytes())
            before=policy_identity(root)[0]
            (root/'skills/workflow-contracts/references/research.md').write_text('changed research policy\n')
            self.assertNotEqual(policy_identity(root)[0],before)

    def test_missing_original_scope_or_unverified_identity_never_invented(self):
        for config in ({},{'pr_sweep':{'repos':[],'authorization':'x'}},{'pr_sweep':{'repos':[{}]}}):
            with self.assertRaises(ValueError):plan(config,identity(),socket.gethostname(),ROOT)
        for changed in ({'source':'guessed'},{'id':None},{'observed_at':''}):
            with self.assertRaises(ValueError):plan(legacy(),{**identity(),**changed},socket.gethostname(),ROOT)

    def test_issue_caller_template_tick_refresh_close_dry_run_end_to_end(self):
        body='## Acceptance criteria\n- [ ] implementation tested\n- [ ] observed behavior\n'
        gh=FakeGh(issues={8:{'body':body,'state':'OPEN'}})
        d=draft(plan=f'# Plan\nIssue: {REPO}#8\n',items=None)
        code,out,_=run(gh,'prepare-evidence','--repo',REPO,'--draft',str(d))
        self.assertEqual(code,0); self.assertEqual(gh.writes(),[])
        template=json.loads(out); self.assertEqual(template['authority_ref'],'')
        self.assertTrue(all(c['status']=='unverified' for c in template['issues']['8']['criteria']))
        p=d/'evidence.json';p.write_text(json.dumps(template))
        self.assertEqual(run(gh,'tick','--repo',REPO,'8','--evidence-file',str(p))[0],1)
        self.assertEqual(gh.writes(),[])
        # Proof comes from the fixture's independent acceptance source, not from
        # the preparer. Only the first criterion is proved at this checkpoint.
        template['authority_ref']='original-fixture-user-turn'
        template['issues']['8']['work_record']=work_record(8)
        template['issues']['8']['criteria']=template['issues']['8']['criteria'][:1]
        template['issues']['8']['criteria'][0].update(status='verified',evidence_ref='fixture-test:pass')
        p.write_text(json.dumps(template))
        self.assertEqual(run(gh,'tick','--repo',REPO,'8','--evidence-file',str(p))[0],0)
        new_body=gh.writes()[-1][1];self.assertIn('- [ ] observed behavior',new_body)
        gh.issues[8]['body']=new_body
        # Old receipt now has a stale body hash and cannot authorize more work.
        self.assertEqual(run(gh,'tick','--repo',REPO,'8','--evidence-file',str(p))[0],1)
        # Separate behavioral evidence arrives; refresh the exact source first.
        code,out,_=run(gh,'prepare-evidence','--repo',REPO,'--number','8')
        refreshed=json.loads(out);refreshed['authority_ref']='original-fixture-user-turn'
        refreshed['issues']['8']['work_record']=work_record(8)
        for c in refreshed['issues']['8']['criteria']:c.update(status='verified',evidence_ref='fixture:observed')
        p.write_text(json.dumps(refreshed))
        self.assertEqual(run(gh,'tick','--repo',REPO,'8','--evidence-file',str(p))[0],0)
        gh.issues[8]['body']=gh.writes()[-1][1]
        closure=evidence(gh.issues,deployment=True)
        before=len(gh.writes())
        code,out,_=run(gh,'--dry-run','close','--repo',REPO,str(d),'--sha',SHA,'--evidence-file',closure)
        self.assertEqual(code,0);self.assertEqual(len(gh.writes()),before);self.assertIn('gh issue close',out)
        self.assertTrue(all(a[:2]!=['issue','close'] for a,_ in gh.writes()))


    @unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'optional JSON Schema validator unavailable')
    def test_schema_accepts_staged_copy_and_rejects_missing_publication_scope(self):
        import jsonschema
        schema=json.loads((ROOT/'agent_skills/pr_sweep.schema.json').read_text())
        staged=apply_to_copy(legacy(),plan(legacy(),identity(),socket.gethostname(),ROOT),ROOT)
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(staged['pr_sweep'],schema)
        for changed in ({'mode':'publish'}, {'reviewer_id':None}, {'schema_version':1}):
            with self.subTest(changed=changed), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate({**staged['pr_sweep'],**changed},schema)



class StagedPublisher(SUPPORT.PrSweepTests):
    # Reuse fixture support, but run only the migration test (inherited tests are
    # deliberately excluded below, avoiding a duplicate full publisher suite).
    def test_migrated_config_to_pending_to_shadow_post_has_no_external_writes(self):
        source={'pr_sweep':{'repos':[{'repo':'o/a','checkout':'/src/a'}],
                            'authorization':'legacy fixture scope','max_per_run':2},'unrelated':7}
        migration=plan(source,identity(),socket.gethostname(),ROOT)
        staged=apply_to_copy(source,migration,ROOT);self.config.write_text(json.dumps(staged))
        self.gh_data(list={'o/a':[[SUPPORT.pr(7)]],'o/b':[[]]})
        found=self.sweep('pending');self.assertEqual(found.returncode,0,found.stderr)
        row=json.loads(found.stdout);self.assertEqual(row['base_sha'],SUPPORT.BASE)
        args=self.post_args(policy=row['policy'])
        posted=self.sweep(*args);self.assertEqual(posted.returncode,0,posted.stderr)
        self.assertFalse(json.loads(posted.stdout)['posted'])
        self.assertFalse([c for c in self.calls() if c['argv'][:2]==['pr','comment']])
        self.assertFalse((self.dir/'pr-sweep-state').exists())
        # Legacy input cannot guess the reviewed base/policy even in shadow mode.
        missing=args[:];i=missing.index('--base');del missing[i:i+2]
        self.assertNotEqual(self.sweep(*missing).returncode,0)

# Inherit setup/helpers, not duplicate tests. unittest discovery respects None.
for _name in dir(SUPPORT.PrSweepTests):
    if _name.startswith('test_') and _name not in StagedPublisher.__dict__:
        setattr(StagedPublisher,_name,None)


if __name__=='__main__':unittest.main()
