"""Offline lifecycle tests. Fake assertions only; never use live pmset/caffeinate."""
import copy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from agent_skills import keep_awake as k

ROOT = Path(__file__).resolve().parents[1]
BASE = k.utc('2026-10-21T22:00:00Z')


class Handle:
    def __init__(self, backend, pid, end, code=0):
        self.backend, self.pid, self.end = backend, pid, end
        self.code, self.returncode = code, None

    def poll(self):
        if self.returncode is None and self.backend.tick >= self.end:
            self.returncode = self.code
        return self.returncode

    def terminate(self):
        self.backend.log.append(('terminate', self.pid, self.backend.tick))
        self.returncode = -15

    def wait(self, timeout=None):
        if self.poll() is None:
            self.backend.tick = max(self.backend.tick, self.end)
            self.returncode = self.code
        return self.returncode


class Fake(k.Native):
    def __init__(self):
        self.tick = 0.; self.handles = {}; self.log = []; self.callback = None
        self.ac = True; self.lost = False; self.reused = False; self.probe_error = False
        self.command_length = .2; self.command_code = 0

    def now(self): return BASE + timedelta(seconds=self.tick)
    def monotonic(self): return self.tick
    def host_id(self): return 'fixture-host-boot'

    def sleep(self, seconds):
        self.tick += seconds
        if self.callback: self.callback(self)

    def pause(self, seconds, child=None):
        if child is not None: seconds=min(seconds,max(0,child.end-self.tick))
        self.sleep(seconds)

    def process(self, pid):
        if pid in self.handles and self.handles[pid].poll() is not None: return None
        return dict(pid=pid, executable='fixture', started='reused' if self.reused else 'original')

    def start_assertion(self, seconds):
        pid = 90000 + len(self.handles)
        self.log.append(('acquire', pid, self.tick, seconds))
        h = Handle(self, pid, self.tick + seconds); self.handles[pid] = h
        return h

    def start_command(self, command):
        self.log.append(('command', list(command), self.tick))
        return Handle(self, 99999, self.tick + self.command_length, self.command_code)

    def observe(self, r):
        self.log.append(('observe', r['pid'], self.tick))
        if self.probe_error:
            return dict(observed_at_utc=k.stamp(self.now()), probe_error='transport-unavailable')
        h = self.handles[r['pid']]
        assertion = None if self.lost or h.poll() is not None else dict(
            id='assertion-'+str(h.pid), pid=h.pid, kind='PreventUserIdleSystemSleep',
            remaining_seconds=max(1, int(h.end - self.tick)))
        return dict(observed_at_utc=k.stamp(self.now()), host_id=self.host_id(),
                    process=self.process(h.pid), supervisor=self.process(os.getpid()),
                    assertion=assertion, power=dict(source='AC Power' if self.ac else 'Battery Power'))

    def assertion_absent(self, pid): return self.handles[pid].poll() is not None


def request(backend, seconds=10, segment=4):
    return dict(task_id='synthetic-critical-task', owner='synthetic-owner', host_id=backend.host_id(),
                approval_ref='synthetic:bounded-test', foreground_ref='owned-test-executor',
                authorized_until_utc=k.stamp(backend.now() + timedelta(seconds=seconds)),
                segment_seconds=segment, check_seconds=1)


class RealFixture(k.Native):
    """Actual test-owned child lifetimes; all host/AC/assertion probes are fake."""
    def __init__(self):
        self.handles = {}; self.identities = {}; self.ends = {}; self.log = []

    def host_id(self): return 'fixture-host-boot'
    def process(self, pid):
        h = self.handles.get(pid)
        if h and h.poll() is not None: return None
        return self.identities.setdefault(pid, dict(pid=pid, executable='fixture', started=str(time.monotonic_ns())))

    def start_assertion(self, seconds):
        h = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep('+str(seconds)+')'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.handles[h.pid] = h; self.ends[h.pid] = self.monotonic()+seconds
        assert h.pid > 0
        return h

    def observe(self, r):
        h = self.handles[r['pid']]
        assertion = None if h.poll() is not None else dict(
            pid=h.pid, id='test-'+str(h.pid), kind='PreventUserIdleSystemSleep',
            remaining_seconds=max(1, int(self.ends[h.pid]-self.monotonic())))
        return dict(host_id=self.host_id(), observed_at_utc=k.stamp(self.now()),
                    process=self.process(h.pid), supervisor=self.process(os.getpid()),
                    assertion=assertion, power=dict(source='AC Power'))

    def assertion_absent(self, pid): return self.handles[pid].poll() is not None


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup); self.path = Path(self.tmp.name)/'owned.json'; self.b = Fake()

    def saved(self): return json.loads(self.path.read_text())
    def run_support(self, **kw):
        r = request(self.b, **kw)
        return k.Supervisor(r, self.path, backend=self.b).run()

    def test_finite_support_window_renewal_and_owner_only_cleanup(self):
        self.assertEqual(self.run_support(seconds=11, segment=4), 0)
        r = self.saved(); self.assertEqual(r['state'], 'expired')
        self.assertTrue(r['cleanup_verified']); self.assertEqual(r['authorized_until_utc'], k.stamp(BASE+timedelta(seconds=11)))
        grants = [x for x in self.b.log if x[0]=='acquire']
        self.assertGreater(len(grants), 1); self.assertLess(len(grants), 7)
        for _, pid, at, duration in grants:
            self.assertLessEqual(at+duration, 11); self.assertLessEqual(duration, 4)
        for event in r['events']:
            observed = next(i for i,x in enumerate(self.b.log) if x[:2] == ('observe',event['new_pid']))
            released = next(i for i,x in enumerate(self.b.log) if x[:2] == ('terminate',event['old_pid']))
            self.assertLess(observed, released)
        self.assertTrue(all(x[1] in self.b.handles for x in self.b.log if x[0]=='terminate'))

    def test_success_failure_and_stdin_child_status(self):
        for code in (0, 7, -2):
            with self.subTest(code=code):
                path=self.path.with_name('child'+str(code)+'.json'); b=Fake(); b.command_code=code
                r=request(b);r['task_id']+='-'+str(code)
                self.assertEqual(k.Supervisor(r, path, backend=b).run(['fake-command']),128-code if code<0 else code)
                r=json.loads(path.read_text()); self.assertEqual(r['child_exit_code'],code); self.assertTrue(r['cleanup_verified'])

    def test_early_loss_is_not_masked_by_future_expiry(self):
        def loss(b): b.lost = b.tick >= 1
        self.b.callback = loss
        self.assertEqual(self.run_support(seconds=60,segment=20),75)
        r=self.saved(); self.assertEqual(r['state'],'coverage-lost'); self.assertLess(self.b.tick,60)
        self.assertEqual(r['assessment']['reason'],'assertion-missing')

    def test_stale_or_unknown_status_never_implies_sleep(self):
        def observe_and_stop(b):
            if b.tick>=1:
                original=self.saved(); b.probe_error=True
                result=k.status(self.path,backend=b)
                self.assertEqual(result['assessment']['state'],'unknown')
                self.assertNotIn('sleep',result['assessment']['reason'])
                self.assertEqual(self.saved(),original)  # status did not mutate source
                b.probe_error=False
                k.control(self.path,owner=original['owner'],generation=original['generation'],operation='release',backend=b)
                b.callback=None
        self.b.callback=observe_and_stop
        self.assertEqual(self.run_support(),0); self.assertEqual(self.saved()['state'],'released')

    def test_PID_reuse_prevents_cleanup_signal(self):
        def replaced(b): b.reused=True
        self.b.callback=replaced
        self.assertEqual(self.run_support(),75)
        self.assertFalse(self.saved()['cleanup_verified'])
        self.assertFalse(any(x[0]=='terminate' for x in self.b.log))

    def test_dedup_foreign_control_and_explicit_reuse(self):
        def second(b):
            original=self.saved()
            with self.assertRaises(ValueError): k.Supervisor(request(b),self.path,backend=b).run()
            with self.assertRaises(ValueError): k.Supervisor(request(b),self.path.with_name('bypass.json'),backend=b).run()
            with self.assertRaises(ValueError):
                k.control(self.path,owner='another-owner',generation=original['generation'],operation='release',backend=b)
            before=len(b.handles)
            reused=k.reuse(self.path,consumer='other-task',task_id='synthetic-critical-task',until_utc=k.stamp(b.now()+timedelta(seconds=1)),backend=b)
            self.assertEqual(reused['request']['owner'],'synthetic-owner'); self.assertFalse(reused['cleanup_authorized'])
            self.assertEqual(reused['state'],'queued-not-executed')
            self.assertEqual(len(b.handles),before)
            with self.assertRaises(ValueError): k.reuse(self.path,consumer='other-task',task_id='synthetic-critical-task',until_utc=k.stamp(BASE+timedelta(hours=1)),backend=b)
            b.callback=None
        self.b.callback=second
        self.assertEqual(self.run_support(seconds=4,segment=4),0); self.assertEqual(len(self.b.handles),1)

    def test_renew_request_is_bounded_and_not_admission_as_execution(self):
        def renew(b):
            r=self.saved()
            result=k.control(self.path,owner=r['owner'],generation=r['generation'],operation='renew',backend=b)
            self.assertEqual(result['state'],'queued-not-executed')
            with self.assertRaises(FileExistsError):
                k.control(self.path,owner=r['owner'],generation=r['generation'],operation='renew',backend=b)
            b.callback=None
        self.b.callback=renew
        self.assertEqual(self.run_support(seconds=6,segment=4),0)
        self.assertTrue(self.saved()['events'])
        self.assertTrue(all(x[2]+x[3]<=6 for x in self.b.log if x[0]=='acquire'))

    def test_unverified_start_prevents_critical_command(self):
        self.b.ac=False
        self.assertEqual(k.Supervisor(request(self.b),self.path,backend=self.b).run(['must-not-run']),75)
        self.assertFalse(any(x[0]=='command' for x in self.b.log))
        self.assertTrue(self.saved()['cleanup_verified'])

    def test_existing_receipt_host_and_duration_bounds(self):
        for field,value in [('segment_seconds',0),('segment_seconds',14401),('check_seconds',61),('host_id','other')]:
            r=request(self.b);r[field]=value
            with self.assertRaises(ValueError): k.Supervisor(r,self.path,backend=self.b)
        self.path.write_text('{}')
        with self.assertRaises(ValueError): k.Supervisor(request(self.b),self.path,backend=self.b).run()
        self.assertEqual(self.path.read_text(),'{}')

    def test_no_recorded_PID_can_be_signaled_by_status_or_control_client(self):
        with mock.patch.object(subprocess.Popen,'terminate',side_effect=AssertionError('no client signal')):
            self.path.write_text(json.dumps({'kind':'owned-keep-awake','pid':88001,'owner':'protected-owner',
                'generation':'foreign','host_id':'unknown','authorized_until_utc':k.stamp(BASE+timedelta(hours=4))}))
            with self.assertRaises((ValueError,KeyError)):
                k.control(self.path,owner='not-owner',generation='foreign',operation='release',backend=self.b)

    def test_clock_rollback_cannot_extend_monotonic_window(self):
        original=self.b.now
        self.b.now=lambda: original()-timedelta(seconds=100 if self.b.tick>=2 else 0)
        self.assertEqual(self.run_support(seconds=7,segment=4),0)
        self.assertLessEqual(self.b.tick,7)


class ParserTests(unittest.TestCase):
    def test_own_assertion_timeout_and_bounded_identity(self):
        text='''pid 88001(caffeinate): [0x111] 00:01:00 PreventUserIdleSystemSleep named: "other"
 Timeout will fire in 999 secs Action=TimeoutActionRelease
pid 90001(caffeinate): [0x222] 00:00:01 PreventUserIdleSystemSleep named: "test"
 Timeout will fire in 5 secs Action=TimeoutActionRelease
'''
        r=k.assertion_readback(text,90001);self.assertEqual((r['id'],r['remaining_seconds']),('0x222',5))
        self.assertIsNone(k.assertion_readback(text,333))
        self.assertIsNone(k.assertion_readback(text.replace('Timeout will fire in 5 secs','unavailable'),90001)['remaining_seconds'])

    def test_power_absent_contradictory_and_battery(self):
        self.assertTrue(k.power_readback("Now drawing from 'AC Power'\n -InternalBattery 89%; charging;")['on_ac'])
        for text in ('',"Now drawing from 'Battery Power'", "Now drawing from 'AC Power'\nNow drawing from 'Battery Power'"):
            self.assertFalse(k.power_readback(text)['on_ac'])


class ForegroundFixtureTests(unittest.TestCase):
    def test_shell_exec_handshake_retains_foreground_supervisor_after_command_launch(self):
        # A real shell execs an owned foreground fixture, not a detached daemon.
        # The handshake returns while the support process and fake assertion live.
        with tempfile.TemporaryDirectory(dir='/private/tmp') as tmp:
            p=Path(tmp)/'r.json';script=Path(tmp)/'fixture.py'
            script.write_text('import sys\nfrom pathlib import Path\nsys.path[:0]='+repr([str(ROOT),str(ROOT/'tests')])+'\nfrom test_keep_awake import RealFixture,request\nfrom agent_skills.keep_awake import Supervisor\nb=RealFixture()\nsys.exit(Supervisor(request(b,seconds=4,segment=4),Path(sys.argv[1]),backend=b).run())\n')
            h=subprocess.Popen(['/bin/sh','-c','exec "$1" "$2" "$3"','fixture',sys.executable,str(script),str(p)],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                for _ in range(150):
                    if p.exists() and json.loads(p.read_text()).get('state')=='running':break
                    time.sleep(.01)
                self.assertIsNone(h.poll());r=json.loads(p.read_text());self.assertEqual(r['state'],'running')
                self.assertEqual(r['supervisor_identity']['pid'],h.pid)
                # Consume a fresh status via a fake readback backend bound to the fixture identities.
                pending={key:r[key] for key in ('task_id','owner','host_id','generation')}
                pending.update(operation='release',requested_at_utc=k.stamp(k.utc()))
                Path(str(p)+'.control').write_text(json.dumps(pending))
                self.assertEqual(h.wait(timeout=5),0)
                final=json.loads(p.read_text());self.assertEqual(final['state'],'released');self.assertTrue(final['cleanup_verified'])
            finally:
                if h.poll() is None:h.terminate();h.wait(timeout=5)
                h.communicate(timeout=2)



class EvidenceAndHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)/'r.json';self.b=Fake()
        r=request(self.b,seconds=1000,segment=1000)
        runner=k.Supervisor(r,self.p,backend=self.b)
        self.receipt={**r,'kind':'owned-keep-awake','generation':'g','state':'running',
                      'supervisor_identity':self.b.process(os.getpid()),'freshness_seconds':120}
        runner._acquire(self.receipt)
        k._save(self.p,self.receipt)
        self.addCleanup(lambda:[runner._stop_grant(*x) for x in runner.grants])

    def test_old_receipt_future_expiry_cannot_make_observation_fresh(self):
        from agent_skills.task_reconciliation import keep_awake_assessment
        r=copy.deepcopy(self.receipt)
        a=keep_awake_assessment(r,now=k.stamp(BASE+timedelta(seconds=121)),owner=r['owner'])
        self.assertEqual((a['state'],a['reason']),('unknown','stale-or-future-observation'))
        self.b.tick=121
        fresh=k.status(self.p,backend=self.b)
        self.assertEqual(fresh['assessment']['state'],'verified-now')
        self.assertEqual(json.loads(self.p.read_text()),self.receipt)

    def test_missing_identities_host_mismatch_timeout_and_AC_fail_closed(self):
        for field,value,reason in [('process_identity',None,'incomplete-process-identity'),
                                 ('supervisor_identity',None,'incomplete-process-identity')]:
            r=copy.deepcopy(self.receipt);r[field]=value
            r['observation']['process']=None;r['observation']['supervisor']=None
            self.assertEqual(k.assess(r,now=k.stamp(BASE),owner=r['owner'])['reason'],reason)
        for key,value,expected in [('host_id','another-boot','host-or-boot-mismatch'),
                                  ('power',{'source':'unknown'},'AC-power-unverified'),
                                  ('assertion',None,'assertion-missing')]:
            r=copy.deepcopy(self.receipt);r['observation'][key]=value
            self.assertEqual(k.assess(r,now=k.stamp(BASE),owner=r['owner'])['reason'],expected)
        r=copy.deepcopy(self.receipt);r['observation']['assertion']['remaining_seconds']=100000
        self.assertEqual(k.assess(r,now=k.stamp(BASE),owner=r['owner'])['state'],'unknown')

    def test_handoff_requires_fresh_acknowledged_consumer_and_does_not_transfer_owner(self):
        other='incoming-coordinator'
        self.assertEqual(k.assess(self.receipt,now=k.stamp(BASE),owner=other)['state'],'unknown')
        result=k.reuse(self.p,consumer=other,task_id='synthetic-critical-task',until_utc=k.stamp(BASE+timedelta(seconds=20)),backend=self.b)
        self.assertEqual(result['state'],'queued-not-executed')
        self.assertFalse(result['ownership_transferred'])
        self.assertEqual(k.assess(self.receipt,now=k.stamp(BASE),owner=other)['state'],'unknown')
        # Owner-side acknowledgment is a separate actual lifecycle step.
        runner=k.Supervisor(request(self.b,seconds=1000,segment=1000),self.p,backend=self.b)
        self.assertEqual(runner._control(self.receipt),'retain-consumer')
        assessment=k.assess(self.receipt,now=k.stamp(BASE),owner=other)
        self.assertEqual(assessment['state'],'verified-now');self.assertTrue(assessment['reuse_existing_owner'])
        self.assertFalse(assessment['cleanup_authorized'])
        self.assertEqual(k.assess(self.receipt,now=k.stamp(BASE+timedelta(seconds=21)),owner=other)['state'],'unknown')
        same=self.receipt['owner']
        self.assertEqual(k.assess(self.receipt,now=k.stamp(BASE),owner=same,task_id='another-task')['state'],'unknown')
        k.reuse(self.p,consumer=same,task_id='another-task',until_utc=k.stamp(BASE+timedelta(seconds=20)),backend=self.b)
        self.assertEqual(runner._control(self.receipt),'retain-consumer')
        self.assertEqual(k.assess(self.receipt,now=k.stamp(BASE),owner=same,task_id='another-task')['state'],'verified-now')

    def test_control_publishes_only_complete_JSON_atomically(self):
        original=os.link
        def publish(source,target):
            value=json.loads(Path(source).read_text())
            self.assertEqual(value['operation'],'release');self.assertFalse(Path(target).exists())
            original(source,target)
        with mock.patch.object(k.os,'link',side_effect=publish):
            result=k.control(self.p,owner=self.receipt['owner'],generation='g',operation='release',backend=self.b)
        self.assertEqual(result['state'],'queued-not-executed')
        pending=Path(str(self.p)+'.control');before=pending.read_bytes()
        with self.assertRaises(FileExistsError):
            k.control(self.p,owner=self.receipt['owner'],generation='g',operation='release',backend=self.b)
        self.assertEqual(before,pending.read_bytes())

    def test_status_CLI_is_read_only_and_task_status_never_acquires(self):
        from agent_skills.safeguard_cli import main
        import contextlib,io
        before=self.p.read_bytes()
        with mock.patch('agent_skills.safeguard_cli.awake_status',return_value=k.status(self.p,backend=self.b)) as probe:
            out=io.StringIO()
            with contextlib.redirect_stdout(out):self.assertEqual(main(['keep-awake','status',str(self.p)]),0)
            self.assertEqual(json.loads(out.getvalue())['assessment']['state'],'verified-now');probe.assert_called_once()
        self.assertEqual(self.p.read_bytes(),before)
        from test_task_reconciliation import RecoveryTests,LATE
        inventory=self.p.with_name('inventory.json');inventory.write_text(json.dumps(RecoveryTests().snapshot()))
        saved=inventory.read_bytes()
        with mock.patch('agent_skills.safeguard_cli.Supervisor',side_effect=AssertionError('no implicit acquire')):
            with mock.patch.object(k.Native,'observe',side_effect=AssertionError('pure assessment must not probe')):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['task-reconcile',str(inventory),'--now',LATE]),0)
        self.assertEqual(inventory.read_bytes(),saved)


class RemainingConsumerTests(unittest.TestCase):
    def test_owner_release_waits_for_acknowledged_bounded_consumer(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
            p=Path(d)/'r.json';b=Fake();stage=[0]
            def actions(backend):
                r=json.loads(p.read_text())
                if stage[0]==0:
                    k.reuse(p,consumer='consumer',task_id='synthetic-critical-task',until_utc=k.stamp(BASE+timedelta(seconds=3)),backend=b);stage[0]=1
                elif stage[0]==1:
                    fresh=k.status(p,backend=b)
                    self.assertEqual(k.assess(fresh,now=k.stamp(b.now()),owner='consumer')['state'],'verified-now')
                    k.control(p,owner=r['owner'],generation=r['generation'],operation='release',backend=b);stage[0]=2
            b.callback=actions
            self.assertEqual(k.Supervisor(request(b,seconds=10,segment=10),p,backend=b).run(),0)
            r=json.loads(p.read_text());self.assertEqual(r['state'],'released');self.assertGreaterEqual(b.tick,3)
            self.assertLess(b.tick,10);self.assertTrue(any(x['kind']=='release-held-for-consumers' for x in r['events']))

    def test_one_second_legacy_window_survives_small_setup_delay(self):
        b=Fake();original=b.start_assertion
        def delayed(seconds):b.tick+=.01;return original(seconds)
        b.start_assertion=delayed
        with mock.patch.object(k,'Native',return_value=b):
            self.assertEqual(k.legacy(['test','1','--','harmless-fixture']),0)
        self.assertTrue(any(x[0]=='command' for x in b.log))
        self.assertTrue(all(1<=x[3]<=14400 for x in b.log if x[0]=='acquire'))

class FinalAdversarialTests(unittest.TestCase):
    def test_native_empty_or_partial_snapshot_is_unknown_not_positive_absence(self):
        b=k.Native()
        for text in ('','permission denied','Assertion status system-wide:\nListed by owning process:\n'):
            with mock.patch.object(b,'read',return_value=text):
                with self.assertRaises(ValueError): b.assertion_absent(90001)
        complete='Assertion status system-wide:\nListed by owning process:\nNo kernel assertions.\n'
        with mock.patch.object(b,'read',return_value=complete):self.assertTrue(b.assertion_absent(90001))
        with mock.patch.object(b,'read',return_value='unknown boot'):
            with mock.patch.object(k.sys,'platform','darwin'):
                with self.assertRaises(RuntimeError):b.host_id()

    def test_pending_consumer_and_recorded_loss_never_become_verified(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
            b=Fake();p=Path(d)/'r';r=request(b,seconds=1000,segment=1000)
            runner=k.Supervisor(r,p,backend=b)
            r.update(kind='owned-keep-awake',generation='g',state='running',supervisor_identity=b.process(os.getpid()))
            runner._acquire(r)
            try:
                r['consumers']=[{'consumer':'other','until_utc':k.stamp(BASE+timedelta(seconds=100))}]
                self.assertNotEqual(k.assess(r,now=k.stamp(BASE),owner='other')['state'],'verified-now')
                r['consumers'][0].update(generation='g',readback_at_utc=k.stamp(BASE+timedelta(seconds=1)))
                self.assertNotEqual(k.assess(r,now=k.stamp(BASE),owner='other')['state'],'verified-now')
                r['state']='coverage-lost'
                self.assertEqual(k.assess(r,now=k.stamp(BASE),owner=r['owner'])['state'],'coverage-lost')
                r['state']='running';r['segment_seconds']=50000
                self.assertEqual(k.assess(r,now=k.stamp(BASE),owner=r['owner'])['reason'],'unbounded-segment')
            finally:
                for grant in runner.grants:runner._stop_grant(*grant)

    def test_cleanup_requires_actual_assertion_removal_and_never_stops_foreign_handle(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
            b=Fake();p=Path(d)/'r';r=request(b)
            foreign=Handle(b,88888,100);b.handles[foreign.pid]=foreign
            b.assertion_absent=lambda pid:False
            self.assertEqual(k.Supervisor(r,p,backend=b).run(['fixture']),75)
            receipt=json.loads(p.read_text());self.assertFalse(receipt['cleanup_verified'])
            self.assertIsNone(foreign.poll());self.assertFalse(any(x[:2]==('terminate',foreign.pid) for x in b.log))

    def test_successor_failure_keeps_initial_known_grant_in_cleanup(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
            b=Fake();orig=b.start_assertion
            def second(seconds):
                result=orig(seconds)
                if len(b.handles)>1:b.lost=True
                return result
            b.start_assertion=second
            self.assertEqual(k.Supervisor(request(b),Path(d)/'r',backend=b).run(),75)
            self.assertTrue(all(h.poll() is not None for h in b.handles.values()))

class SignalAndLossTests(unittest.TestCase):
    def test_signal_only_releases_own_fixture_children(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as tmp:
            p=Path(tmp)/'r.json';script=Path(tmp)/'fixture.py'
            script.write_text('import sys\nfrom pathlib import Path\nsys.path[:0]='+repr([str(ROOT),str(ROOT/'tests')])+'\nfrom test_keep_awake import RealFixture,request\nfrom agent_skills.keep_awake import Supervisor\nb=RealFixture()\nsys.exit(Supervisor(request(b,seconds=5,segment=5),Path(sys.argv[1]),backend=b).run())\n')
            unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(8)'])
            h=subprocess.Popen([sys.executable,str(script),str(p)],stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                for _ in range(150):
                    if p.exists() and json.loads(p.read_text()).get('state')=='running':break
                    time.sleep(.01)
                self.assertEqual(json.loads(p.read_text())['state'],'running')
                h.terminate();self.assertEqual(h.wait(timeout=4),0)
                r=json.loads(p.read_text());self.assertEqual(r['state'],'released');self.assertTrue(r['cleanup_verified'])
                self.assertIsNone(unrelated.poll())
            finally:
                if h.poll() is None:h.terminate();h.wait(timeout=5)
                h.communicate(timeout=2)
                if unrelated.poll() is None:unrelated.terminate()
                unrelated.wait(timeout=3)

    def test_lost_executor_is_distinct_from_unknown_transport(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
            b=Fake();original=b.process
            def lost(pid):return None if pid==os.getpid() and b.tick>=1 else original(pid)
            b.process=lost
            self.assertEqual(k.Supervisor(request(b),Path(d)/'r',backend=b).run(),75)
            r=json.loads((Path(d)/'r').read_text())
            self.assertEqual(r['assessment']['reason'],'process-identity-lost')
            self.assertTrue(r['cleanup_verified'])


if __name__ == "__main__":
    unittest.main()
