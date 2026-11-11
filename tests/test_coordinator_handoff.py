"""Offline coordinator handoff and read-only inventory regressions."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from test_operating_checkpoints import tasks, bound, checkpoint_shape, T0, DUE, LATE, EXP
from agent_skills.task_reconciliation import reconcile_tasks

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('handoff_delegate', ROOT/'skills/agent-coordination/scripts/delegate.py')
delegate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delegate)


def finished():
    r = tasks.record_checkpoint(bound(), **dict(checkpoint_shape(), critical=False))
    r['status'] = 'answered'
    r['coordination']['execution_state'] = 'finished'
    a = r['coordination']['active_deliverable']
    a['result_receipt_ref'] = 'dispatch:result'
    a['parent_readback'] = dict(result_receipt_ref='dispatch:result', decision_source_ref=a['source_ref'])
    return r


def assess(r, now=T0):
    a=r['coordination']['active_deliverable']
    return reconcile_tasks(dict(expected_task_ids=[r['task_id']], records=[r], observations=[dict(
        task_id=r['task_id'],revision=a['revision'],decision_source_ref=a['source_ref'],
        observed_at_utc=T0,expires_at_utc=EXP)]),now=now)['tasks'][0]


class HandoffTests(unittest.TestCase):
    def test_consumed_completed_result_still_needs_next_disposition(self):
        r=finished(); before=copy.deepcopy(r)
        self.assertIn('missing-followup-disposition',assess(r)['issues'])
        self.assertEqual(r,before)


class StatusTests(unittest.TestCase):
    def test_status_does_not_attempt_checkpoint_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)/'fixture-task'/'dispatch'; run.mkdir(parents=True)
            (run/'params.json').write_text(json.dumps(dict(contract_binding={'revision':1},cwd=tmp,depth=0)))
            (run/'supervisor.json').write_text(json.dumps(dict(started_at=T0,supervisor_pid=999999)))
            (run/'receipt.json').write_text(json.dumps(dict(outcome='done')))
            out=io.StringIO()
            with mock.patch.object(delegate,'runs',return_value=[run]), \
                 mock.patch.object(delegate.tasks,'update',side_effect=PermissionError('writes forbidden')), \
                 mock.patch.object(delegate.tasks,'load',return_value=finished()), \
                 contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
                try: result=delegate.main(['status'])
                except PermissionError: result='attempted forbidden write'
            self.assertNotEqual(result,'attempted forbidden write')
            self.assertEqual(len(out.getvalue().splitlines()),1)


class LifecycleTests(unittest.TestCase):
    def projection(self, r, now=T0):
        return tasks.coordinator_attention([r],now=now)[0]

    def followup(self, r, kind='assignment'):
        from agent_skills.task_reconciliation import handoff_binding
        return tasks.record_coordinator_followup(r,binding=handoff_binding(r),kind=kind,
            next_action='Read approved next artifact' if kind=='assignment' else 'Await named acceptance',
            source_ref='user:original-scope',receipt_ref='assignment:1',next_check_at_utc=DUE)

    def test_unconsumed_result_and_empty_action_are_coordinator_not_user_notifications(self):
        r=finished();a=r['coordination']['active_deliverable'];a.pop('parent_readback');a['next_action']=''
        before=copy.deepcopy(r)
        p=self.projection(r)
        self.assertIn('unconsumed-result',p['issues']); self.assertIn('missing-next-action',p['issues'])
        self.assertEqual(tasks.attention([r],now=T0),[])
        self.assertEqual(r,before);self.assertFalse(p['dispatch_authorized'])

    def test_stale_wrong_source_and_revision_readbacks_never_consume(self):
        from agent_skills.task_reconciliation import handoff_binding
        for key,value in [('result_receipt_ref','old'),('decision_source_ref','wrong'),('binding',dict(handoff_binding(finished()),revision=0))]:
            with self.subTest(key=key):
                r=finished();r['coordination']['active_deliverable']['parent_readback'][key]=value
                self.assertIn('unconsumed-result',self.projection(r)['issues'])
                with self.assertRaises(ValueError):self.followup(r)

    def test_followup_assignment_ack_outcome_and_readback_remain_separate(self):
        from agent_skills.task_reconciliation import handoff_binding
        r=self.followup(finished()); p=self.projection(r)
        self.assertEqual(p['followup_state'],'assigned-awaiting-acknowledgment')
        self.assertEqual(p['next_action'],'Read approved next artifact')
        self.assertEqual(p['next_owner'],'worker-a')
        self.assertEqual(p['issues'],[]); self.assertIsNone(p['worker_acknowledgment'])
        r=tasks.acknowledge_coordinator_followup(r,binding=handoff_binding(r),assignment_ref='assignment:1',
            owner='worker-a',receipt_ref='worker:read-assignment')
        self.assertEqual(self.projection(r)['followup_state'],'acknowledged')
        a=r['coordination']['active_deliverable'];a['result_receipt_ref']='result:new'
        p=self.projection(r); self.assertIn('unconsumed-result',p['issues']);self.assertIsNone(p['followup'])

    def test_identical_followup_replay_preserves_acknowledgment(self):
        from agent_skills.task_reconciliation import handoff_binding
        r=self.followup(finished())
        r=tasks.acknowledge_coordinator_followup(r,binding=handoff_binding(r),assignment_ref='assignment:1',
            owner='worker-a',receipt_ref='worker:ack')
        self.assertEqual(self.followup(r),r)

    def test_malformed_current_followup_never_suppresses_attention(self):
        r=self.followup(finished())
        r['coordination']['active_deliverable']['coordinator_followup']['kind']='invented'
        with self.assertRaises(ValueError):self.projection(r)

    def test_assignment_cannot_be_acknowledged_by_wrong_owner_or_revision(self):
        from agent_skills.task_reconciliation import handoff_binding
        r=self.followup(finished())
        for owner,binding in [('other',handoff_binding(r)),('worker-a',dict(handoff_binding(r),revision=2))]:
            with self.assertRaises(ValueError):tasks.acknowledge_coordinator_followup(r,binding=binding,
                assignment_ref='assignment:1',owner=owner,receipt_ref='ack')

    def test_legitimate_holds_are_not_resumption_requests(self):
        for change,expected in [('blocked','blocked'),('paused','paused'),('human','human-owned-or-unknown-owner'),('uncertain','uncertain-dispatch')]:
            r=finished()
            if change=='blocked': r['status']='blocked';r['pending_decision']={'need':'Approve exact action'}
            elif change=='paused':r['coordination']['execution_state']='paused'
            elif change=='human':r['worker']['owner']='human'
            else:r['outbox']=[{'id':'dispatch','state':'uncertain'}]
            p=self.projection(r);self.assertEqual(p['hold'],expected)
            self.assertNotIn('missing-followup-disposition',p['issues']);self.assertFalse(p['dispatch_authorized'])
        r=self.followup(finished(),kind='hold')
        self.assertEqual(self.projection(r)['followup_state'],'held')
        self.assertEqual(self.projection(r,now=DUE)['issues'],[])
        self.assertIn('followup-checkpoint-overdue',self.projection(r,now=LATE)['issues'])

    def test_fresh_active_quiet_missing_stale_and_exact_checkpoint(self):
        r=tasks.record_checkpoint(bound(),**dict(checkpoint_shape(),critical=False))
        r['status']='running';r['coordination']['execution_state']='running'
        self.assertEqual(self.projection(r)['issues'],[])
        self.assertEqual(self.projection(r,now=DUE)['issues'],[])
        self.assertIn('overdue:critical-read',self.projection(r,now=LATE)['issues'])
        r['coordination']['active_deliverable'].pop('checkpoint')
        self.assertIn('missing-checkpoint:critical-read',self.projection(r)['issues'])

    def test_verified_done_keeps_followup_history_without_active_overdue_attention(self):
        for kind in ('assignment','hold'):
            with self.subTest(kind=kind):
                r=tasks.record_checkpoint(bound(),**dict(checkpoint_shape(),critical=False))
                a=r['coordination']['active_deliverable']
                r=tasks.acknowledge_task_contract(r,deliverable_id=a['id'],revision=a['revision'],
                    changed_criteria=a['changed_criteria'],next_action=a['next_action'],
                    environment=a['environment'],receipt_ref='worker:current-contract')
                binding=tasks.current_task_binding(r)
                head,diff='a'*40,'b'*64
                for event_id,source,kind_event,data in [
                    ('dispatch','adapter','dispatched',{}),
                    ('running','worker','running',binding),
                    ('ready','worker','ready',dict(binding,commit=head,final_diff_digest=diff,tests='passed'))]:
                    r,outcome=tasks.apply(r,dict(id=event_id,task=r['task_id'],ts=1790000010+len(r['seen']),
                        source=source,kind=kind_event,data=data))
                    self.assertEqual(outcome,'applied')
                a=r['coordination']['active_deliverable']
                r=tasks.reconcile_parent_readback(r,binding=binding,result_receipt_ref=a['result_receipt_ref'],
                    decision_source_ref=a['source_ref'],read_receipt_ref='parent:read-artifact',answer_ref='parent:disposition')
                r=self.followup(r,kind=kind)
                retained=copy.deepcopy(r['coordination']['active_deliverable'])
                retained.update(id='retained-dependency',state='queued')
                r['coordination']['obligations'].append(retained)
                self.assertIn('followup-checkpoint-overdue',self.projection(r,now=LATE)['issues'])
                r,outcome=tasks.apply(r,dict(id='verified',task=r['task_id'],ts=1790000020,
                    source='verifier',kind='verified',data=dict(binding,commit=head,final_diff_digest=diff,tests_passed=True)))
                self.assertEqual(outcome,'applied');self.assertEqual(r['status'],'verified-done')
                self.assertEqual(r['coordination']['acceptance_state'],'verified')
                before=copy.deepcopy(r);p=self.projection(r,now=LATE)
                self.assertEqual(p['issues'],['overdue:retained-dependency'])
                self.assertEqual(p['followup'],before['coordination']['active_deliverable']['coordinator_followup'])
                self.assertEqual(p['followup_state'],'completed')
                self.assertIsNone(p['next_action']);self.assertIsNone(p['next_owner'])
                self.assertEqual(r,before)

    def test_verified_done_needs_no_followup_duplicate_identity_rejected(self):
        r=finished();r['status']='verified-done'
        self.assertEqual(self.projection(r)['issues'],[])
        with self.assertRaises(ValueError):tasks.coordinator_attention([r,copy.deepcopy(r)],now=T0)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.env=mock.patch.dict(os.environ,{'AGENT_COORDINATION_STATE':str(self.root)});self.env.start();self.addCleanup(self.env.stop)
        tasks.save(self.root,finished())

    def run_fixture(self, name, **params):
        run=self.root/'runs'/'fixture-task'/name;run.mkdir(parents=True)
        (run/'params.json').write_text(json.dumps(dict(contract_binding={'revision':1},cwd=str(self.root),depth=0,**params)))
        (run/'supervisor.json').write_text(json.dumps(dict(started_at=T0,supervisor_pid=999999)))
        (run/'receipt.json').write_text(json.dumps(dict(outcome='done')))
        return run

    def status(self):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=delegate.main(['status'])
        return code,[json.loads(x) for x in out.getvalue().splitlines()],json.loads(err.getvalue())

    def test_status_zero_writes_locks_staging_or_settlement_and_deduplicates_history(self):
        self.run_fixture('one');self.run_fixture('two')
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        real_io_open=io.open;real_os_open=os.open
        def read_only_open(file,mode='r',*args,**kwargs):
            if any(flag in mode for flag in 'wax+'):
                raise AssertionError('write-mode open forbidden')
            return real_io_open(file,mode,*args,**kwargs)
        def read_only_fd(file,flags,*args,**kwargs):
            if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                raise AssertionError('writable descriptor forbidden')
            return real_os_open(file,flags,*args,**kwargs)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch('io.open',side_effect=read_only_open))
            stack.enter_context(mock.patch('builtins.open',side_effect=read_only_open))
            stack.enter_context(mock.patch('os.open',side_effect=read_only_fd))
            for name in ('mkdir','unlink','remove','rename','replace','chmod'):
                stack.enter_context(mock.patch.object(os,name,side_effect=AssertionError('filesystem mutation forbidden')))
            for obj,name in [(tasks,'update'),(tasks,'save'),(tasks,'_locked'),(delegate.tasks,'update'),(delegate.tasks,'save'),(delegate.tasks,'_locked'),
                             (delegate,'write_json'),(delegate,'settle_lost'),(delegate.task_checkpoint,'stage_checkpoint_intents')]:
                stack.enter_context(mock.patch.object(obj,name,side_effect=AssertionError('write/mutation forbidden')))
            stack.enter_context(mock.patch.object(Path,'write_text',side_effect=AssertionError('write forbidden')))
            code,rows,coverage=self.status()
        self.assertEqual(code,0);self.assertTrue(coverage['complete']);self.assertEqual(len(rows),2)
        self.assertEqual(sum('coordinator' in row for row in rows),1)
        self.assertEqual(rows[1]['coordinator_ref'],'fixture-task')
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_malformed_first_middle_last_retains_other_rows_and_partial_exit(self):
        for malformed in ('a','b','c'):
            with self.subTest(malformed=malformed):
                for name in ('a','b','c'):
                    run=self.run_fixture(name) if not (self.root/'runs/fixture-task'/name).exists() else self.root/'runs/fixture-task'/name
                    (run/'params.json').write_text('{bad' if name==malformed else json.dumps(dict(cwd=str(self.root),depth=0)))
                code,rows,coverage=self.status()
                self.assertEqual(code,2);self.assertFalse(coverage['complete']);self.assertEqual(len(rows),3)
                self.assertEqual(sum(row.get('kind')=='coverage-error' for row in rows),1)

    def test_missing_task_supervisor_receipt_and_protection_are_explicit(self):
        run=self.run_fixture('one')
        (self.root/'fixture-task.json').unlink()
        code,rows,c=self.status();self.assertEqual(code,2);self.assertIn('FileNotFoundError',rows[0]['error'])
        tasks.save(self.root,finished());(run/'supervisor.json').unlink()
        self.assertEqual(self.status()[0],2)
        (run/'supervisor.json').write_text(json.dumps(dict(started_at=T0,supervisor_pid=999999)))
        (run/'receipt.json').unlink()
        # No terminal receipt can be a still-running run, never a completion proof.
        with mock.patch.object(delegate,'alive',return_value=None):code,rows,c=self.status()
        self.assertEqual(rows[0]['state'],'unknown');self.assertEqual(rows[0]['receipt_state'],'not-produced')
        (run/'params.json').write_text(json.dumps(dict(cwd=str(self.root),depth=0,critical={})))
        # malformed critical input also reports coverage failure instead of disappearing
        (run/'params.json').write_text(json.dumps(dict(cwd=str(self.root),depth=0,critical={'receipt':'missing'})))
        self.assertEqual(self.status()[0],2)

    def test_cli_exit_cannot_misreport_partial_success(self):
        import subprocess,sys
        run=self.run_fixture('bad');(run/'supervisor.json').unlink()
        proc=subprocess.run([sys.executable,'-B',str(ROOT/'skills/agent-coordination/scripts/delegate.py'),'status'],
            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},text=True,capture_output=True)
        self.assertEqual(proc.returncode,2);self.assertEqual(json.loads(proc.stdout)['kind'],'coverage-error')
        self.assertFalse(json.loads(proc.stderr)['complete'])

    def test_wrong_shape_json_retains_other_rows_instead_of_aborting(self):
        self.run_fixture('good');bad=self.run_fixture('bad')
        (bad/'params.json').write_text('[]')
        try:code,rows,coverage=self.status()
        except AttributeError:code,rows,coverage='aborted',[],{}
        self.assertEqual(code,2);self.assertEqual(len(rows),2)
        self.assertFalse(coverage['complete'])

    def test_checkpoint_staging_is_an_explicit_separate_mutation(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=delegate.main(['stage-checkpoints','fixture-task'])
        self.assertEqual(code,0)
        record=tasks.load(self.root,'fixture-task')
        self.assertIn('checkpoint_intents',record['coordination'])
        self.assertEqual(json.loads(out.getvalue())['checkpoint_intents'],record['coordination']['checkpoint_intents'])
