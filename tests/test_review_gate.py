import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / 'skills/agent-coordination/scripts'
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('review_gate', SCRIPTS / 'review_gate.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

H, T, B = 'a' * 40, 'b' * 40, 'c' * 40


def packet(**kw):
    base = dict(gate='g1', head=H, tree=T, base=B, diffstat='3 files +10 -2',
                tests='tests/check.sh exit 0, 840 ok, run by author',
                done_when=['suite green'], ledger=[('F-1', 'resolved: fixed in a1b2')])
    base.update(kw)
    return g.build_packet(**base)


class PacketTests(unittest.TestCase):
    def test_same_head_same_fingerprint_and_line_budget(self):
        a, b = packet(), packet()
        self.assertEqual(a['fingerprint'], b['fingerprint'])
        self.assertLessEqual(len(a['text'].splitlines()), 40)
        self.assertIn(H, a['text'])

    def test_other_head_changes_fingerprint(self):
        self.assertNotEqual(packet()['fingerprint'], packet(head='d' * 40)['fingerprint'])

    def test_refuses_secrets_and_private_ids(self):
        for bad in ('token ghp_abcdefghijklmnopqrstuvwx', 'mail a@b.com', 'user U09AWF2ASG2', 'call +1 415 555 0100'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                packet(tests=bad)

    def test_missing_or_unknown_field_fails_loudly(self):
        with self.assertRaises(TypeError):
            packet(extra='x')
        with self.assertRaises(ValueError):
            packet(head='')
        with self.assertRaises(ValueError):
            packet(gate='nope')


class VerdictTests(unittest.TestCase):
    def test_no_blocker_on_exact_head(self):
        v = g.parse_verdict(f'VERDICT g1 {H} {T} NO-BLOCKER', H)
        self.assertEqual(v['state'], 'no-blocker')

    def test_blockers_with_findings(self):
        text = f'VERDICT g1 {H} {T} BLOCKERS 1\nFINDING F-9 P1 a.py:3 wrong head used; rerun check'
        v = g.parse_verdict(text, H)
        self.assertEqual(v['state'], 'blockers')
        self.assertEqual(v['findings'][0]['id'], 'F-9')

    def test_other_head_is_stale_never_no_blocker(self):
        v = g.parse_verdict(f'VERDICT g1 {"d" * 40} {T} NO-BLOCKER', H)
        self.assertEqual(v['state'], 'stale')

    def test_malformed_or_missing_is_unreviewed(self):
        for text in ('', 'looks fine to me', f'VERDICT g1 {H} {T} MAYBE'):
            with self.subTest(text=text):
                self.assertEqual(g.parse_verdict(text, H)['state'], 'unreviewed')

    def test_blockers_count_must_match_findings(self):
        v = g.parse_verdict(f'VERDICT g1 {H} {T} BLOCKERS 2\nFINDING F-9 P1 a.py:3 x; y', H)
        self.assertEqual(v['state'], 'unreviewed')


class DecisionTests(unittest.TestCase):
    def test_disagreement_goes_to_thomas_never_auto_resolved(self):
        self.assertEqual(g.reconcile('blockers', 'yes'), 'needs-human')
        self.assertEqual(g.reconcile('no-blocker', 'no'), 'needs-human')

    def test_agreement_and_unreviewed(self):
        self.assertEqual(g.reconcile('no-blocker', 'yes'), 'reviewed-yes')
        self.assertEqual(g.reconcile('blockers', 'no'), 'reviewed-no')
        self.assertEqual(g.reconcile('unreviewed', 'yes'), 'unreviewed')
        self.assertEqual(g.reconcile('stale', 'yes'), 'unreviewed')

    def test_verdict_state_never_names_approval(self):
        for s in ('no-blocker', 'blockers', 'stale', 'unreviewed'):
            for w in ('yes', 'no'):
                self.assertNotIn('approv', g.reconcile(s, w))


class ConfigTests(unittest.TestCase):
    def test_all_gates_default_on_no_caps(self):
        for gate in g.GATES:
            self.assertTrue(g.gate_settings([], gate)['on'])
        self.assertNotIn('max_per_day', g.gate_settings([], 'g1'))

    def test_layering_narrower_wins_and_off_switch(self):
        cfg = [{'g1': {'on': True, 'deadline_h': 4}}, {'g1': {'on': False}}]
        s = g.gate_settings(cfg, 'g1')
        self.assertFalse(s['on'])
        self.assertEqual(s['deadline_h'], 4)

    def test_unknown_gate_fails(self):
        with self.assertRaises(ValueError):
            g.gate_settings([], 'zz')


class WatchTests(unittest.TestCase):
    def rec(self, **kw):
        r = dict(sent_at=1000, deadline_h=4, retries=0, fingerprint='f')
        r.update(kw)
        return r

    def test_closes_on_verdict(self):
        self.assertEqual(g.watch_step(self.rec(), 1100, 'no-blocker')['action'], 'close')
        self.assertEqual(g.watch_step(self.rec(), 1100, 'blockers')['action'], 'close')

    def test_waits_inside_deadline(self):
        self.assertEqual(g.watch_step(self.rec(), 1000 + 3600, None)['action'], 'wait')

    def test_stale_or_unreviewed_inside_deadline_keeps_waiting(self):
        self.assertEqual(g.watch_step(self.rec(), 1100, 'stale')['action'], 'wait')

    def test_deadline_then_one_retry_then_tell_thomas(self):
        late = 1000 + 4 * 3600 + 1
        self.assertEqual(g.watch_step(self.rec(), late, None)['action'], 'retry')
        step = g.watch_step(self.rec(retries=1, sent_at=late), late + 4 * 3600 + 1, None)
        self.assertEqual(step['action'], 'tell-thomas')
        self.assertEqual(step['state'], 'unreviewed')

    def test_identical_packet_is_deduped(self):
        fp = packet()['fingerprint']
        self.assertFalse(g.should_send(fp, {fp}))
        self.assertTrue(g.should_send(packet(head='d' * 40)['fingerprint'], {fp}))


class ValueTests(unittest.TestCase):
    def test_summary_counts_tests_missed_and_false_positives(self):
        rows = [
            dict(gate='g1', state='blockers', confirmed=True, tests_green=True, latency_s=3600),
            dict(gate='g1', state='blockers', confirmed=False, tests_green=True, latency_s=7200),
            dict(gate='g1', state='no-blocker', latency_s=1800),
            dict(gate='g2', state='unreviewed'),
        ]
        s = g.value_summary(rows)
        self.assertEqual(s['g1']['requests'], 3)
        self.assertEqual(s['g1']['blockers'], 2)
        self.assertEqual(s['g1']['tests_missed'], 1)
        self.assertEqual(s['g1']['false_positives'], 1)
        self.assertEqual(s['g1']['median_latency_s'], 3600)
        self.assertEqual(s['g2']['unreviewed'], 1)


if __name__ == '__main__':
    unittest.main()
