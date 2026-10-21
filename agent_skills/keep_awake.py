"""Task-local foreground idle-sleep protection. No daemon or persistent settings.

Receipts describe observations, not authority. Only the retaining supervisor owns
Popen handles; status/control clients never signal a PID taken from a receipt.
"""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid


def utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() != timedelta(0):
        raise ValueError('explicit UTC time required')
    return parsed


def stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def power_readback(text):
    sources = set(re.findall(r"Now drawing from '([^']+)'", text))
    source = next(iter(sources)) if len(sources) == 1 else 'unknown'
    percent = re.search(r'\b(\d{1,3})%;', text)
    return {'source': source, 'on_ac': source == 'AC Power',
            'battery_percent': int(percent[1]) if percent and int(percent[1]) <= 100 else None}


def assertion_readback(text, pid):
    blocks = re.split(r'(?=^\s*pid \d+\()', text, flags=re.M)
    matches = []
    for block in blocks:
        head = re.match(r'\s*pid (\d+)\([^)]+\):\s*\[([^]]+)\].*?\b(Prevent\w+)', block)
        if head and int(head[1]) == pid and head[3] == 'PreventUserIdleSystemSleep':
            timeout = re.search(r'Timeout will fire in (\d+) secs', block)
            matches.append({'pid': pid, 'id': head[2], 'kind': head[3],
                            'remaining_seconds': int(timeout[1]) if timeout else None})
    if len(matches) > 1:
        raise ValueError('ambiguous owned assertion')
    return matches[0] if matches else None


def _complete_assertions(text):
    if ('Assertion status system-wide:' not in text or 'Listed by owning process:' not in text
            or not re.search(r'(?mi)^(?:Kernel Assertions:|No kernel assertions\b)', text)):
        raise ValueError('incomplete assertion snapshot')
    return text


def assess(receipt, *, now, owner, task_id=None):
    """Pure assessment of supplied fresh evidence; never probes or grants control."""
    result = {'state': 'unknown', 'live_probe_performed': False,
              'cleanup_authorized': False, 'reuse_existing_owner': False}
    required = ('task_id', 'owner', 'host_id', 'generation', 'authorized_until_utc')
    if any(not receipt.get(k) for k in required):
        return dict(result, reason='incomplete-receipt')
    segment = receipt.get('segment_seconds')
    if type(segment) is not int or not 1 <= segment <= 14400:
        return dict(result, reason='unbounded-segment')
    if receipt.get('state') in ('completed', 'released', 'expired'):
        return dict(result, state=receipt['state'], reason='closed-grant')
    if receipt.get('state') == 'coverage-lost' or receipt.get('error'):
        return dict(result, state='coverage-lost', reason='recorded-coverage-loss')
    if utc(now) >= utc(receipt['authorized_until_utc']):
        return dict(result, state='expired', reason='authorized-window-ended')
    obs = receipt.get('observation') or {}
    if not obs or obs.get('probe_error'):
        return dict(result, reason='probe-unavailable')
    age = (utc(now) - utc(obs['observed_at_utc'])).total_seconds()
    if not 0 <= age <= min(120, receipt.get('freshness_seconds', 120)):
        return dict(result, reason='stale-or-future-observation')
    if obs.get('host_id') != receipt['host_id']:
        return dict(result, reason='host-or-boot-mismatch')
    for name in ('process_identity', 'supervisor_identity'):
        identity = receipt.get(name)
        if (not isinstance(identity, dict) or type(identity.get('pid')) is not int or identity['pid'] <= 0
                or not identity.get('started') or not identity.get('executable')):
            return dict(result, reason='incomplete-process-identity')
    if receipt['process_identity']['pid'] != receipt.get('pid'):
        return dict(result, reason='incomplete-process-identity')
    if (obs.get('process') != receipt.get('process_identity') or
            obs.get('supervisor') != receipt.get('supervisor_identity')):
        return dict(result, state='coverage-lost', reason='process-identity-lost')
    assertion = obs.get('assertion')
    if not assertion:
        return dict(result, state='coverage-lost', reason='assertion-missing')
    if (assertion['pid'] != receipt['pid'] or assertion['kind'] != 'PreventUserIdleSystemSleep'
            or assertion['id'] != receipt['assertion_ref']):
        return dict(result, state='coverage-lost', reason='assertion-identity-mismatch')
    remaining = assertion.get('remaining_seconds')
    if type(remaining) is not int or not 1 <= remaining <= segment:
        return dict(result, reason='finite-timeout-unverified')
    observed_end = utc(obs['observed_at_utc']) + timedelta(seconds=remaining)
    if observed_end > utc(receipt['authorized_until_utc']) + timedelta(seconds=1):
        return dict(result, reason='timeout-exceeds-authorization')
    if utc(now) >= min(utc(receipt['expires_at_utc']), observed_end):
        return dict(result, state='expired', reason='grant-ended')
    if (obs.get('power') or {}).get('source') != 'AC Power':
        return dict(result, reason='AC-power-unverified')
    expected_task = task_id if task_id is not None else receipt['task_id']
    if receipt['owner'] != owner or receipt['task_id'] != expected_task:
        consumers = receipt.get('consumers', [])
        if not any(c.get('consumer') == owner and c.get('generation') == receipt['generation']
                   and c.get('consumer_task_id') == expected_task
                   and c.get('readback_at_utc')
                   and 0 <= (utc(now) - utc(c['readback_at_utc'])).total_seconds() <= 120
                   and utc(c['until_utc']) > utc(now) for c in consumers):
            return dict(result, reason='consumer-readback-not-acknowledged')
    return dict(result, state='verified-now', owner=receipt['owner'],
                reuse_existing_owner=receipt['owner'] != owner,
                reason='fresh-bound-process-assertion-and-AC-evidence')


class Native:
    """Only read-only host probes and children explicitly created by this owner."""
    def now(self): return utc()
    def monotonic(self): return time.monotonic()
    def sleep(self, seconds): time.sleep(seconds)

    def pause(self, seconds, child=None):
        if child is None: self.sleep(seconds)
        else:
            try: child.wait(timeout=seconds)
            except subprocess.TimeoutExpired: pass

    def read(self, command):
        return subprocess.check_output(command, text=True, timeout=5,
                                       env={**os.environ, 'LC_ALL': 'C'})

    def host_id(self):
        if sys.platform != 'darwin':
            raise RuntimeError('Mac keep-awake backend unavailable')
        boot = self.read(['/usr/sbin/sysctl', '-n', 'kern.boottime']).strip()
        if not re.search(r'\bsec\s*=\s*\d+', boot):
            raise RuntimeError('boot identity unavailable')
        return hashlib.sha256((os.uname().nodename + boot).encode()).hexdigest()

    def process(self, pid):
        run = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart=', '-o', 'comm='],
                             capture_output=True, text=True, timeout=5,
                             env={**os.environ, 'LC_ALL': 'C'})
        if run.returncode == 1 and not run.stdout.strip() and not run.stderr.strip():
            return None
        if run.returncode or not run.stdout.strip():
            raise RuntimeError('process identity probe unavailable')
        line = run.stdout.strip()
        return {'pid': pid, 'started': line[:24], 'executable': line[24:].strip()}

    def start_assertion(self, seconds):
        executable = shutil.which('caffeinate')
        if not executable:
            raise RuntimeError('caffeinate unavailable')
        # No utility argument: the native manual says -t is ignored with a utility.
        return subprocess.Popen([executable, '-i', '-t', str(seconds), '-w', str(os.getpid())],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

    def start_command(self, command):
        return subprocess.Popen(command)  # preserve stdin/stdout and exact argv

    def observe(self, receipt):
        try:
            return {'observed_at_utc': stamp(self.now()), 'host_id': self.host_id(),
                    'process': self.process(receipt['pid']),
                    'supervisor': self.process(receipt['supervisor_identity']['pid']),
                    'assertion': assertion_readback(_complete_assertions(self.read(['/usr/bin/pmset', '-g', 'assertions'])), receipt['pid']),
                    'power': power_readback(self.read(['/usr/bin/pmset', '-g', 'batt']))}
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
            return {'observed_at_utc': stamp(self.now()), 'probe_error': 'host-probe-unavailable'}

    def assertion_absent(self, pid):
        return assertion_readback(_complete_assertions(self.read(['/usr/bin/pmset', '-g', 'assertions'])), pid) is None


def _path(path):
    path = Path(path).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('task receipt must have canonical non-symlink ancestry')
    if not path.parent.is_dir():
        raise ValueError('existing task artifact directory required')
    return path


def _save(path, value):
    fd, name = tempfile.mkstemp(prefix='.keep-awake-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def status(path, *, backend=None):
    backend = backend or Native()
    path = _path(path)
    receipt = json.loads(path.read_text())
    observation = backend.observe(receipt)
    current = json.loads(path.read_text())
    binding = ('kind', 'task_id', 'owner', 'generation', 'host_id', 'approval_ref', 'foreground_ref',
               'supervisor_identity', 'authorized_until_utc', 'segment_seconds', 'check_seconds', 'freshness_seconds')
    if any(current.get(k) != receipt.get(k) for k in binding):
        observation = {'observed_at_utc': stamp(backend.now()), 'probe_error': 'receipt-contract-changed'}
    else:
        # A reader may have opened the old grant just before verified renewal.
        # Retry once only for this same bound owner; real loss still stays loss.
        if any(current.get(k) != receipt.get(k) for k in
               ('pid', 'process_identity', 'assertion_ref', 'expires_at_utc', 'state')):
            observation = backend.observe(current)
        receipt = current
    receipt['observation'] = observation
    receipt['assessment'] = assess(receipt, now=stamp(backend.now()), owner=receipt['owner'])
    return receipt  # deliberately not persisted by a read-only status call


def control(path, *, owner, generation, operation, backend=None):
    """Queue one exact-owner request; only the foreground supervisor can execute it."""
    if operation not in ('renew', 'release'):
        raise ValueError('unsupported owner control')
    backend = backend or Native(); path = _path(path)
    receipt = status(path, backend=backend)
    if (receipt['owner'], receipt['generation'], receipt['host_id']) != (owner, generation, backend.host_id()):
        raise ValueError('owner/generation/host mismatch')
    if receipt['assessment']['state'] != 'verified-now':
        raise ValueError('fresh ownership evidence required; reconcile unavailable or lost coverage')
    value = {k: receipt[k] for k in ('owner', 'generation', 'host_id', 'task_id')}
    value.update(operation=operation, requested_at_utc=stamp(backend.now()))
    return _enqueue(path, value)


def _enqueue(path, value):
    # One pending request, never overwrite an uncertain request or follow a link.
    pending = path.with_name(path.name + '.control')
    fd, temporary = tempfile.mkstemp(prefix='.keep-awake-control-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, pending)  # publish complete bytes once, no overwrite
    finally:
        os.unlink(temporary)
    return {'state': 'queued-not-executed', 'request': value, 'receipt': str(path)}


@contextmanager
def _reservation(path, scope):
    digest = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[:24]
    lock = path.with_name('.keep-awake-' + digest + '.lock')
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('existing foreground owner; use fresh status/reuse, never duplicate')
        existing = os.read(fd, 4096).decode().strip()
        if existing and existing != str(path):
            raise ValueError('task/owner already bound to another receipt in this artifact directory')
        if not existing:
            os.write(fd, str(path).encode()); os.fsync(fd)
        yield
    finally:
        os.close(fd)  # retain the inode; unlinking a flock permits a second lock


def reuse(path, *, consumer, task_id, until_utc, backend=None):
    """Request a bounded consumer readback; wait for the owner's receipt acknowledgment."""
    backend = backend or Native(); receipt = status(path, backend=backend)
    if not consumer or not task_id or receipt['assessment']['state'] != 'verified-now':
        raise ValueError('fresh coverage required for explicit reuse')
    observed_end = utc(receipt['observation']['observed_at_utc']) + timedelta(
        seconds=receipt['observation']['assertion']['remaining_seconds'])
    if not backend.now() < utc(until_utc) <= min(utc(receipt['expires_at_utc']), observed_end):
        raise ValueError('existing grant does not cover the consumer window')
    value = {k: receipt[k] for k in ('owner', 'generation', 'host_id', 'task_id')}
    value.update(operation='retain-consumer', consumer=consumer, consumer_task_id=task_id, until_utc=until_utc,
                 requested_at_utc=stamp(backend.now()))
    return {**_enqueue(_path(path), value), 'ownership_transferred': False, 'cleanup_authorized': False}


class Supervisor:
    def __init__(self, request, path, *, backend=None):
        self.backend = backend or Native(); self.path = _path(path)
        self.request = dict(request); self.grants = []; self.child = None
        self.stopped = False; self.loss = False; self.release_requested = False
        for key in ('task_id', 'owner', 'host_id', 'approval_ref', 'foreground_ref', 'authorized_until_utc'):
            if not isinstance(request.get(key), str) or not request[key].strip():
                raise ValueError('required request binding: ' + key)
        self.seconds = request.get('segment_seconds', 14400)
        self.interval = request.get('check_seconds', 60)
        self.request.update(segment_seconds=self.seconds, check_seconds=self.interval)
        if type(self.seconds) is not int or not 1 <= self.seconds <= 14400:
            raise ValueError('segment_seconds must be 1..14400')
        if type(self.interval) is not int or not 1 <= self.interval <= 60:
            raise ValueError('check_seconds must be 1..60')
        if request['host_id'] != self.backend.host_id(): raise ValueError('wrong host/boot')
        self.deadline = utc(request['authorized_until_utc'])
        if self.deadline <= self.backend.now(): raise ValueError('authorized window already ended')
        self.monotonic_end = self.backend.monotonic() + (self.deadline - self.backend.now()).total_seconds()

    def _remaining(self):
        return round(min((self.deadline - self.backend.now()).total_seconds(),
                         self.monotonic_end - self.backend.monotonic()), 6)

    def _stop_grant(self, handle, identity):
        try:
            if handle.poll() is None:
                if not identity or self.backend.process(handle.pid) != identity: return False
                handle.terminate()  # exact Popen child, never a receipt PID/group
                handle.wait(timeout=2)
            for _ in range(10):
                if self.backend.assertion_absent(handle.pid): return True
                self.backend.sleep(0.05)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError): pass
        return False  # bounded native timeout remains; removal is unverified

    def _acquire(self, receipt):
        remaining = self._remaining()
        if remaining <= 0: raise ValueError('authorized window exhausted')
        seconds = min(self.seconds, math.ceil(remaining))
        started = self.backend.monotonic()
        handle = self.backend.start_assertion(seconds)
        self.grants.append((handle, None))
        identity = self.backend.process(handle.pid)
        self.grants[-1] = (handle, identity)
        if not identity: raise RuntimeError('assertion process identity unavailable')
        receipt.update(pid=handle.pid, process_identity=identity, assertion_ref='pending',
                       expires_at_utc=stamp(min(self.deadline, self.backend.now() + timedelta(seconds=seconds))),
                       native_timeout_rounding_limit_seconds=1)
        for _ in range(20):
            receipt['observation'] = self.backend.observe(receipt)
            assertion = receipt['observation'].get('assertion')
            if assertion:
                receipt['assertion_ref'] = assertion['id']
                if assess(receipt, now=stamp(self.backend.now()), owner=receipt['owner'])['state'] == 'verified-now':
                    return min(started + seconds, self.monotonic_end), min(300, seconds / 4)
            self.backend.sleep(0.05)
        raise RuntimeError('initial assertion/PID/AC readback not verified')

    def _control(self, receipt):
        path = self.path.with_name(self.path.name + '.control')
        if not path.exists(): return None
        value = json.loads(_path(path).read_text())
        if any(value.get(k) != receipt[k] for k in ('owner', 'generation', 'host_id', 'task_id')):
            raise ValueError('control ownership mismatch; request preserved for reconciliation')
        age = (self.backend.now() - utc(value['requested_at_utc'])).total_seconds()
        if not 0 <= age <= 120: raise ValueError('stale owner control; reconcile before retry')
        if value.get('operation') not in ('renew', 'release', 'retain-consumer'): raise ValueError('unsupported owner control')
        if value['operation'] == 'retain-consumer':
            if (not value.get('consumer') or not value.get('consumer_task_id') or not self.backend.now() < utc(value['until_utc']) <=
                    min(utc(receipt['expires_at_utc']), self.deadline)):
                raise ValueError('consumer request outside current bounded grant')
            receipt.setdefault('consumers', []).append({'consumer': value['consumer'], 'until_utc': value['until_utc'],
                                                       'consumer_task_id': value['consumer_task_id'],
                                                       'generation': receipt['generation'],
                                                       'readback_at_utc': stamp(self.backend.now())})
        path.unlink()  # consumed exact task-owned request; result recorded in receipt
        return value['operation']

    def run(self, command=None):
        with _reservation(self.path, {k: self.request[k] for k in ('task_id', 'owner', 'host_id')}):
            if self.path.exists():
                raise ValueError('existing receipt: reconcile/reuse it; use a new explicit path for a new grant')
            receipt = {**self.request, 'kind': 'owned-keep-awake', 'generation': uuid.uuid4().hex,
                       'supervisor_identity': self.backend.process(os.getpid()),
                       'state': 'admitted', 'freshness_seconds': 120,
                       'cleanup_ref': 'only-retaining-supervisor-Popen-handles', 'events': []}
            _save(self.path, receipt)
            previous = {}
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGINT, signal.SIGTERM):
                    previous[sig] = signal.signal(sig, lambda *_: setattr(self, 'stopped', True))
            try:
                grant_end, margin = self._acquire(receipt)
                receipt['state'] = 'running'; _save(self.path, receipt)
                if command: self.child = self.backend.start_command(command)
                while not self.stopped:
                    receipt['observation'] = self.backend.observe(receipt)
                    check = assess(receipt, now=stamp(self.backend.now()), owner=receipt['owner'])
                    receipt['assessment'] = check; _save(self.path, receipt)
                    receipt['consumers'] = [c for c in receipt.get('consumers', []) if utc(c['until_utc']) > self.backend.now()]
                    if self._remaining() <= 0:
                        receipt['state'] = 'expired'; break
                    if self.release_requested and not receipt['consumers']:
                        receipt['state'] = 'released'; break
                    if self.child and self.child.poll() is not None and not receipt['consumers']:
                        receipt['child_exit_code'] = self.child.returncode
                        self.loss = check['state'] != 'verified-now'
                        receipt['state'] = 'coverage-lost' if self.loss else 'completed'; break
                    if check['state'] in ('coverage-lost', 'expired'):
                        receipt['state'] = 'coverage-lost'; self.loss = True; break
                    operation = self._control(receipt)
                    if operation: _save(self.path, receipt)
                    if operation == 'release':
                        self.release_requested = True
                        if not receipt['consumers']: receipt['state'] = 'released'; break
                        receipt['events'].append({'kind': 'release-held-for-consumers', 'at': stamp(self.backend.now())})
                    can_extend = grant_end < self.monotonic_end - 0.001
                    if operation == 'renew' and not can_extend:
                        receipt['events'].append({'kind': 'renew-not-needed', 'at': stamp(self.backend.now())})
                    if can_extend and (operation == 'renew' or grant_end - self.backend.monotonic() <= margin):
                        if check['state'] != 'verified-now': raise RuntimeError('renewal needs fresh coverage')
                        old = self.grants[-1]
                        grant_end, margin = self._acquire(receipt)  # verify before old release
                        _save(self.path, receipt)  # publish verified successor before old cleanup
                        released = self._stop_grant(*old)
                        receipt['events'].append({'kind': 'bounded-renewal', 'at': stamp(self.backend.now()),
                                                  'old_pid': old[0].pid, 'new_pid': receipt['pid'],
                                                  'old_released': released})
                        if not released: raise RuntimeError('old grant cleanup unverified')
                        _save(self.path, receipt)
                    self.backend.pause(min(self.interval, 1 if self.child else 60,
                                           max(0.05, grant_end - self.backend.monotonic() - margin) if can_extend else self._remaining(),
                                           self._remaining()), self.child)
                if self.stopped:
                    receipt['state'] = 'released'
                    receipt['interrupted_consumers'] = receipt.get('consumers', [])
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                receipt['state'] = 'coverage-lost'; receipt['error'] = 'supervisor-failed; inspect current task evidence'
                self.loss = True
            finally:
                receipt['cleanup_verified'] = all([self._stop_grant(*g) for g in self.grants])
                if not receipt['cleanup_verified']: self.loss = True
                for sig, handler in previous.items(): signal.signal(sig, handler)
                receipt['finished_at_utc'] = stamp(self.backend.now()); _save(self.path, receipt)
            # Existing business work is not killed/replayed when protection expires or is lost.
            if self.child:
                receipt['child_exit_code'] = self.child.wait()
                _save(self.path, receipt)
                code = self.child.returncode
                return (128 - code if code < 0 else code) if code else (75 if self.loss else 0)
            return 75 if self.loss else 0


def legacy(argv):
    """Compatible bounded command wrapper; durable support uses an explicit request."""
    if len(argv) < 4 or argv[2] != '--' or not re.fullmatch(r'[A-Za-z0-9._-]+', argv[0]): return 2
    if not argv[1].isdigit() or not 1 <= int(argv[1]) <= 14400: return 2
    backend = Native(); seconds = int(argv[1])
    with tempfile.TemporaryDirectory(prefix='critical-local-work-') as directory:
        request = {'task_id': argv[0], 'owner': 'command-' + uuid.uuid4().hex,
                   'host_id': backend.host_id(), 'approval_ref': 'explicit-bounded-command-invocation',
                   'foreground_ref': 'current-wrapper-execution', 'segment_seconds': seconds,
                   'authorized_until_utc': stamp(backend.now() + timedelta(seconds=seconds))}
        return Supervisor(request, Path(directory).resolve() / 'receipt.json', backend=backend).run(argv[3:])


if __name__ == '__main__':
    try: sys.exit(legacy(sys.argv[1:]))
    except (OSError, ValueError, RuntimeError): sys.exit(69)
