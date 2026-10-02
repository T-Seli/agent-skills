import importlib.util
import sys
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).parents[1] / 'skills/agent-coordination/scripts'
sys.dont_write_bytecode = True


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t, m = load('tasks'), load('metrics')
BASE = 1790000000
CHAT = {'channel': 'chat', 'text': 'yes'}


def ev(task, i, ts, source, kind, **data):
    return {'id': i, 'task': task, 'ts': BASE + ts, 'source': source, 'kind': kind, 'data': data}


def run(task, *events, dispatches=1):
    r = t.new_task(task, task, worker_kind='claude', owner='assistant', repo='repo')
    for n in range(dispatches):
        r = t.settle_dispatch(t.begin_dispatch(r, f'd{n}', resume=False), f'd{n}', 'sent')
    for e in events:
        r, _ = t.apply(r, ev(task, *e[:4], **(e[4] if len(e) > 4 else {})))
    return r


READY = dict(commit='abc1234', tests='5 passed')


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.good = run('good', ('d', 0, 'adapter', 'dispatched'), ('r', 30, 'worker', 'running'),
                        ('y', 100, 'worker', 'ready', READY), ('v', 120, 'verifier', 'verified', dict(commit='abc1234', tests_passed=True)))
        self.blocked = run('blk', ('d', 0, 'adapter', 'dispatched'), ('b', 10, 'worker', 'blocked', dict(need='?', action='merge', target='x')),
                           ('u', 610, 'user', 'decided', dict(CHAT, approve=True, action='merge', target='x')),
                           ('b2', 620, 'worker', 'blocked', dict(need='again', action='merge', target='x')),
                           ('y0', 700, 'worker', 'ready'), dispatches=2)
        self.silent = run('quiet', ('d', 0, 'adapter', 'dispatched'))

    def test_delays_waiting_and_completion_counts(self):
        a = m.aggregate([self.good, self.blocked, self.silent], now=BASE + 1000)
        self.assertEqual((a['tasks'], a['median_response_s'], a['no_response']), (3, 20.0, 1))
        # 600 s for the first decision, then 380 s still open on the second ask
        self.assertEqual(a['waiting_on_human_s'], 980.0)
        # the evidence-less ready arrived while blocked, where no ready can apply: not a claim
        self.assertEqual((a['claimed'], a['claims_without_evidence'], a['verified']), (1, 0, 1))
        self.assertEqual((a['unneeded_asks'], a['retries']), (1, 0))  # a resume after a decision is not a retry

    def test_ack_is_not_a_response(self):
        r = run('ack', ('d', 0, 'adapter', 'dispatched'), ('k', 5, 'orchestrator', 'ack'), ('i', 9, 'adapter', 'idle'))
        self.assertEqual(m.aggregate([r])['no_response'], 1)

    def test_gaps_become_small_corrections_with_a_test_each(self):
        a = m.aggregate([self.good, self.blocked, self.silent], now=BASE + 1000)
        fixes = m.corrections(a)
        self.assertTrue(fixes and all(f['change'] and f['test'] for f in fixes))
        self.assertEqual({f['gap'].split(' ', 1)[1].split(' ')[0] for f in fixes} >= {'approval', 'of'}, True)
        self.assertEqual(m.corrections(m.aggregate([self.good])), [])

    def test_measures_read_no_bodies(self):
        self.assertEqual(set(m.task_measures(self.good, BASE)), {
            'dispatched', 'response_s', 'waiting_on_human_s', 'duplicates', 'retries', 'uncertain',
            'unneeded_asks', 'claimed', 'claims_without_evidence', 'verified'})


class ReviewRegressionTests(unittest.TestCase):
    def test_only_a_dispatch_after_an_unsettled_one_is_a_retry(self):
        r = t.new_task('rt', 'rt', worker_kind='claude', owner='assistant', repo='repo')
        r = t.settle_dispatch(t.begin_dispatch(r, 'd0', resume=False), 'd0', 'not-sent')
        r = t.settle_dispatch(t.begin_dispatch(r, 'd1', resume=False), 'd1', 'sent')
        r = t.settle_dispatch(t.begin_dispatch(r, 'd2', resume=True), 'd2', 'sent')
        self.assertEqual(m.task_measures(r, BASE)['retries'], 1)
        self.assertIn('repeated dispatches', m.corrections(m.aggregate([r]))[0]['gap'])

    def test_a_repeated_or_stale_valid_ready_is_not_an_unsupported_claim(self):
        r = run('rr', ('d', 0, 'adapter', 'dispatched'), ('y', 10, 'worker', 'ready', READY),
                ('y2', 20, 'worker', 'ready', READY), ('y', 30, 'worker', 'ready', READY), ('y3', 5, 'worker', 'ready', READY),
                ('n', 40, 'worker', 'ready', {}))
        tm = m.task_measures(r, BASE)
        self.assertEqual((tm['claimed'], tm['claims_without_evidence']), (1, 0))  # 'n' came after ready-for-review
        done = run('vd', ('d', 0, 'adapter', 'dispatched'), ('y', 10, 'worker', 'ready', READY),
                   ('v', 20, 'verifier', 'verified', dict(commit='abc1234', tests_passed=True)), ('late', 30, 'worker', 'ready', {}))
        self.assertEqual(m.task_measures(done, BASE)['claims_without_evidence'], 0)  # nothing to claim after verified-done
        r = run('ur', ('d', 0, 'adapter', 'dispatched'), ('r', 5, 'worker', 'running'), ('n', 10, 'worker', 'ready', {}))
        tm = m.task_measures(r, BASE)
        self.assertEqual((tm['claimed'], tm['claims_without_evidence']), (1, 1))


class ThreadTests(unittest.TestCase):
    def test_both_record_shapes_and_open_decisions(self):
        recs = [{'sent_ts': '1790000000.1', 'reply_ts': '1790000004.1', 'send_state': 'sent'},
                # became needs-human at 300, though our last write was at 100: waiting starts at 300
                {'last_sent_ts': '1790000100.0', 'last_reply_ts': '1790000118.0', 'status': 'needs-human',
                 'status_since': '1790000300.0', 'send_state': 'sent'},
                {'last_sent_ts': '1790000200.0', 'status': 'running', 'send_state': 'uncertain'},
                {'last_sent_ts': '1790000250.0', 'status': 'needs-human', 'send_state': 'sent'}]
        th = m.threads(recs, now=1790000700)
        self.assertEqual((th['threads'], th['median_reply_s'], th['no_reply'], th['open_needs_human_s'],
                          th['needs_human_start_unknown'], th['uncertain_sends']), (4, 11.0, 2, 400.0, 1, 1))
        self.assertEqual(th['by_status'], {'unset': 1, 'needs-human': 2, 'running': 1})


if __name__ == '__main__':
    unittest.main()
