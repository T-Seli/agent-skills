"""Real launcher boundary with a task-owned fake CLI, never a provider call."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_ROOT = Path(os.environ.get('AUDIT_LAUNCHER_ROOT', ROOT))
sys.path[:0] = [str(ROOT), str(ROOT / 'skills/agent-coordination/scripts')]
import tasks
from agent_skills import producer_contract
from agent_skills.task_contract import packet


def contract_value(task_id='strict-1'):
    contract = dict(user_goal='Return the synthetic outcome', constraints=['no external effects'],
        priority_source_ref='fixture:user', canonical_issue_ref='fixture:issue',
        canonical_owner='fixture-owner', deliverable_id='fixture-outcome', revision=1,
        acceptance_ref='fixture:criteria', environment='synthetic', changed_criteria='echo current tuple',
        next_action='read-only synthetic answer', source_ref='fixture:decision',
        requested_artifact='answer', authority_ref='fixture:user', artifact_ref='fixture:answer',
        gates=['independent parent acceptance'])
    p = packet(task_id=task_id, revision=1, owner='fixture-owner', scope=contract['user_goal'],
        exclusions=['external effects'], baseline='fixture source', deliverables=['synthetic answer'],
        acceptance=[{'id':'outcome', 'check':'exact bound answer'}], context_refs=['fixture:user'],
        source_hashes={'fixture':'a'*64}, package_hashes={'fixture':'b'*64},
        stop_conditions=['scope changed'], escalation_conditions=['missing evidence'])
    return {'contract':contract, 'acceptance_packet':p}


FAKE = r'''#!/usr/bin/env python3
import json, os, sys
a=sys.argv[1:]; prompt=sys.stdin.read()
schema=json.loads(a[a.index('--json-schema')+1]); ack='status' not in schema['properties']
sid=a[a.index('--session-id')+1] if '--session-id' in a else a[a.index('--resume')+1]
with open(os.environ['CALLS'],'a') as f:
 f.write(json.dumps({'ack':ack,'argv':a,'session_id':sid})+'\n')
if ack:
 report=json.loads(prompt.splitlines()[-1])['acknowledgment']
 if os.environ.get('WRONG_ACK'): report['revision']=0
 if os.environ.get('WRONG_SESSION'): sid='wrong-session'
else:
 envelope=json.loads(prompt.splitlines()[1]); binding=envelope['binding']
 report={**binding,'status':'answered','summary':'synthetic result','commit':'','tests':'fixture',
         'artifact_kind':envelope['contract']['requested_artifact'],'artifact_ref':'fixture:answer','result':'synthetic result',
         'remaining':[],'next_owner':'parent',
         'material_facts':[{'fact':'synthetic result','source_ref':'fixture:source','evidence_level':'performed'}],
         'need':'','action':'','target':''}
 if os.environ.get('READY_REPORT'):
  report.update(status='ready',commit='a'*40,final_diff_digest='b'*64)
print(json.dumps({'type':'result','session_id':sid,'is_error':False,'structured_output':report,
                  'total_cost_usd':0.01,'num_turns':1}))
'''


class ProducerContractTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.dir=Path(tmp.name).resolve(); (self.dir/'bin').mkdir()
        for name,body in [('claude',FAKE),('caffeinate','#!/bin/sh\nexit 0\n')]:
            path=self.dir/'bin'/name; path.write_text(body); path.chmod(0o755)
        cfg=json.loads((ROOT/'agent_skills/delegate_config.example.json').read_text())
        cfg['policy']['claude']['ordinary']['model']='fixture-claude'
        cfg['capabilities']['claude']['fixture-claude']=['medium','high']
        (self.dir/'config.json').write_text(json.dumps(cfg))
        (self.dir/'prompt.md').write_text('Return a synthetic answer; no tools needed.')
        (self.dir/'contract.json').write_text(json.dumps(contract_value()))
        self.env={**os.environ,'PATH':str(self.dir/'bin')+':'+os.environ['PATH'],
            'AGENT_SKILLS_CONFIG':str(self.dir/'config.json'),
            'AGENT_COORDINATION_STATE':str(self.dir/'state'),'CALLS':str(self.dir/'calls.jsonl'),
            'PYTHONDONTWRITEBYTECODE':'1'}
        self.env.pop('AGENT_SKILLS_DEPTH',None); self.env.pop('AGENT_SKILLS_TASK_ID',None)

    def cli(self,*args,env=None):
        return subprocess.run([sys.executable,'-B',str(LAUNCHER_ROOT/'skills/agent-coordination/scripts/delegate.py'),
            *args],env={**self.env,**(env or {})},capture_output=True,text=True)

    def start(self,*extra,env=None):
        return self.cli('start','--task-id','strict-1','--cwd',str(self.dir),
            '--prompt-file',str(self.dir/'prompt.md'),*extra,env=env)

    def test_new_unbound_work_is_held_before_launch(self):
        result=self.start()
        self.assertEqual(result.returncode,3,result.stderr)
        self.assertFalse((self.dir/'calls.jsonl').exists())
        self.assertFalse((self.dir/'state/strict-1.json').exists())

    def test_real_launcher_consumes_no_tools_readback_then_same_session_result(self):
        started=self.start('--contract-file',str(self.dir/'contract.json'))
        self.assertEqual(started.returncode,0,started.stderr)
        launch=json.loads(started.stdout)
        result=self.cli('wait','strict-1','--timeout','15')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        receipt=json.loads(result.stdout)
        self.assertEqual(receipt['record_status'],'answered',receipt)
        self.assertIsNone(receipt['bookkeeping_error'])
        calls=[json.loads(x) for x in (self.dir/'calls.jsonl').read_text().splitlines()]
        self.assertEqual([x['ack'] for x in calls],[True,False])
        self.assertEqual({x['session_id'] for x in calls},{launch['session_id']})
        self.assertEqual(calls[0]['argv'][calls[0]['argv'].index('--tools')+1],'')
        self.assertIn('--resume',calls[1]['argv'])
        record=tasks.load(self.dir/'state','strict-1')
        self.assertTrue(record['coordination']['active_deliverable']['readback_ref'])
        self.assertIsNotNone(record['coordination']['active_deliverable']['checkpoint'])
        self.assertNotEqual(record['status'],'verified-done')
        binding_file=self.dir/'binding.json'
        binding_file.write_text(json.dumps(tasks.current_task_binding(record)))
        read=self.cli('readback','strict-1','--dispatch',launch['dispatch_id'],
            '--binding-file',str(binding_file),'--read-receipt','fixture:parent-read',
            '--answer-ref','fixture:parent-answer')
        self.assertEqual(read.returncode,0,read.stderr)
        consumed=json.loads(read.stdout)
        self.assertEqual(consumed['parent_readback']['read_receipt_ref'],'fixture:parent-read')
        self.assertEqual(consumed['acceptance_state'],'unreviewed')
        self.assertTrue(tasks.load(self.dir/'state','strict-1')['worker']['last_execution']['parent_consumed'])
        wrong={**tasks.current_task_binding(record),'revision':2}
        binding_file.write_text(json.dumps(wrong))
        read=self.cli('readback','strict-1','--binding-file',str(binding_file),
            '--read-receipt','fixture:wrong-read','--answer-ref','fixture:wrong-answer')
        self.assertNotEqual(read.returncode,0)

    def test_wrong_readback_or_session_cannot_reach_execution(self):
        for bad in ('WRONG_ACK','WRONG_SESSION'):
            with self.subTest(bad=bad):
                # Each case gets an independent task-owned state; no live processes reused.
                env={bad:'1','AGENT_COORDINATION_STATE':str(self.dir/bad),'CALLS':str(self.dir/(bad+'.jsonl'))}
                started=self.start('--contract-file',str(self.dir/'contract.json'),env=env)
                self.assertEqual(started.returncode,0,started.stderr)
                result=self.cli('wait','strict-1','--timeout','15',env=env)
                self.assertEqual(json.loads(result.stdout)['outcome'],'contract-held',result.stdout)
                self.assertEqual(len((self.dir/(bad+'.jsonl')).read_text().splitlines()),1)

    def test_changed_packet_or_contract_and_foreign_ack_are_rejected(self):
        record=tasks.new_task('strict-1','fixture',worker_kind='claude',owner='assistant',repo='fixture')
        value=contract_value(); bound=producer_contract.bind(tasks,record,value)
        binding=producer_contract.acknowledgment_binding(tasks,bound)
        for key in binding:
            altered={**binding,key:'wrong'}
            with self.subTest(key=key),self.assertRaises(ValueError):
                producer_contract.consume(bound,tasks=tasks,acknowledgment=altered,
                    session_id='s',expected_session_id='s',receipt_ref='fixture:receipt')
        broken=copy.deepcopy(value); broken['acceptance_packet']['scope']='unapproved'
        with self.assertRaises(ValueError): producer_contract.bind(tasks,record,broken)
        for revision in (True,1.0):
            with self.subTest(revision=revision),self.assertRaises(ValueError):
                producer_contract.consume(bound,tasks=tasks,acknowledgment={**binding,'revision':revision},
                    session_id='s',expected_session_id='s',receipt_ref='fixture:receipt')

    def test_bound_legacy_grant_does_not_acquire_current_authority(self):
        record=tasks.new_task('strict-1','fixture',worker_kind='claude',owner='assistant',repo='fixture')
        record['approvals']=[{'action':'release','target':'fixture','scope':'old'}]
        bound=producer_contract.bind(tasks,record,contract_value())
        self.assertFalse(tasks.approved(bound,'release','fixture'))
        self.assertEqual(bound['approvals'],record['approvals'])

    def test_unresolved_current_decision_holds_this_task_only(self):
        record=tasks.new_task('strict-1','fixture',worker_kind='claude',owner='assistant',repo='fixture')
        bound=producer_contract.bind(tasks,record,contract_value())
        active=bound['coordination']['active_deliverable']
        bound['pending_decision']={'need':'current approval','action':'change','target':'fixture',
            'scope':'exact current scope','revision':active['revision'],'contract_digest':active['contract_digest']}
        with self.assertRaises(ValueError): producer_contract.require_execution_authority(tasks,bound)
        bound['approvals']=[{**bound['pending_decision'],'ts':'fixture:approval','binding':'current-contract'}]
        producer_contract.require_execution_authority(tasks,bound)
        bound['approvals'][0]['scope']='other scope'
        with self.assertRaises(ValueError): producer_contract.require_execution_authority(tasks,bound)
        producer_contract.require_execution_authority(tasks,record)  # unrelated independent task

    def test_missing_cost_bound_refuses_before_admission(self):
        cfg=json.loads((self.dir/'config.json').read_text())
        cfg['policy']['claude']['ordinary'].pop('max_cost_usd',None)
        (self.dir/'config.json').write_text(json.dumps(cfg))
        result=self.start('--contract-file',str(self.dir/'contract.json'))
        self.assertEqual(result.returncode,3,result.stderr)
        self.assertIn('positive cost budget',result.stdout)
        self.assertFalse((self.dir/'state/strict-1.json').exists())

    def test_reported_code_ready_is_readable_before_verification_but_never_accepted(self):
        value=contract_value(); value['contract']['requested_artifact']='patch'
        (self.dir/'contract.json').write_text(json.dumps(value))
        started=self.start('--contract-file',str(self.dir/'contract.json'),env={'READY_REPORT':'1'})
        self.assertEqual(started.returncode,0,started.stderr)
        result=self.cli('wait','strict-1','--timeout','15')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        receipt=json.loads(result.stdout)
        self.assertIsNone(receipt['bookkeeping_error'],receipt)
        record=tasks.load(self.dir/'state','strict-1')
        self.assertNotEqual(record['status'],'ready-for-review')
        self.assertEqual(record['coordination']['acceptance_state'],'unreviewed')
        self.assertIsNone(record['evidence'])
        self.assertEqual(record['coordination']['active_deliverable']['reported_result']['artifact_kind'],'patch')
        binding_file=self.dir/'binding.json'; binding_file.write_text(json.dumps(tasks.current_task_binding(record)))
        read=self.cli('readback','strict-1','--binding-file',str(binding_file),
            '--read-receipt','fixture:code-parent-read','--answer-ref','fixture:code-answer')
        self.assertEqual(read.returncode,0,read.stderr)
        after=tasks.load(self.dir/'state','strict-1')
        self.assertTrue(after['worker']['last_execution']['parent_consumed'])
        self.assertEqual(after['coordination']['acceptance_state'],'unreviewed')
