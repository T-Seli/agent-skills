"""Fake-clock checkpoint intents; no scheduler, sends or host session access."""
import copy
import tempfile
from pathlib import Path
import unittest

from test_operating_checkpoints import bound, tasks, checkpoint_shape, T0, T1, DUE, LATE
from agent_skills import task_checkpoint as checkpoint

ESCALATE = '2026-10-14T18:20:00Z'
AFTER = '2026-10-14T18:21:00Z'


def staged(now=LATE):
    record = checkpoint.record_checkpoint(bound(), **checkpoint_shape())
    return checkpoint.stage_checkpoint_intents(record, now=now, escalation_after_seconds=600)


def intents(record):
    return record['coordination'].get('checkpoint_intents', [])


class CheckpointIntents(unittest.TestCase):
    def test_changed_checkpoint_retires_pending_notifications_without_deleting_history(self):
        record = staged()
        old_id = intents(record)[0]['id']
        new_cp = {**checkpoint_shape(), 'observed_at_utc':AFTER,
                  'next_check_at_utc':'2026-10-14T18:40:00Z','receipt_ref':'checkpoint:new'}
        record = checkpoint.record_checkpoint(record, **new_cp)
        record = checkpoint.stage_checkpoint_intents(record,now=AFTER)
        old = next(x for x in intents(record) if x['id']==old_id)
        self.assertEqual(old['state'],'superseded')
        self.assertFalse(old['current'])
        self.assertFalse(any(x['state']=='pending' for x in intents(record)))

    def test_before_due_due_and_escalation_are_deterministic(self):
        record = staged(T1)
        self.assertEqual(intents(record), [])
        record = checkpoint.stage_checkpoint_intents(record, now=DUE)
        self.assertEqual([x['kind'] for x in intents(record)], ['checkpoint-due'])
        replay = checkpoint.stage_checkpoint_intents(record, now=LATE)
        self.assertEqual(record, replay)
        record = checkpoint.stage_checkpoint_intents(record, now=ESCALATE)
        self.assertEqual([x['kind'] for x in intents(record)], ['checkpoint-due', 'checkpoint-escalation'])
        self.assertTrue(all(x['progress'] == 'unknown' for x in intents(record)))
        self.assertEqual(record, checkpoint.stage_checkpoint_intents(record, now=AFTER))

    def test_missing_checkpoint_is_unknown_progress_once_and_input_unchanged(self):
        original = bound()
        before = copy.deepcopy(original)
        record = checkpoint.stage_checkpoint_intents(original, now=T0)
        self.assertEqual(original, before)
        self.assertEqual(intents(record)[0]['kind'], 'checkpoint-missing')
        self.assertEqual(intents(record)[0]['progress'], 'unknown')
        self.assertEqual(record, checkpoint.stage_checkpoint_intents(record, now=T1))

    def test_persisted_intent_survives_crash_before_transport(self):
        record = staged()
        intent_id = intents(record)[0]['id']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks.create(root, record)
            tasks.update(root, record['task_id'], checkpoint.begin_checkpoint_intent,
                intent_id=intent_id, observed_at_utc=LATE, attempt_ref='attempt:one')
            # Crash before calling a transport: fresh load retains uncertain state.
            recovered = tasks.load(root, record['task_id'])
        self.assertEqual(intents(recovered)[0]['state'], 'uncertain')
        with self.assertRaises(ValueError):
            checkpoint.begin_checkpoint_intent(recovered, intent_id=intent_id,
                observed_at_utc=AFTER, attempt_ref='attempt:two')

    def test_uncertain_delivery_requires_readback_before_retry(self):
        record = staged()
        intent_id = intents(record)[0]['id']
        record = checkpoint.begin_checkpoint_intent(record, intent_id=intent_id,
            observed_at_utc=LATE, attempt_ref='attempt:one')
        record = checkpoint.settle_checkpoint_intent(record, intent_id=intent_id,
            outcome='uncertain', observed_at_utc=LATE, receipt_ref='transport:timeout')
        with self.assertRaises(ValueError):
            checkpoint.begin_checkpoint_intent(record, intent_id=intent_id,
                observed_at_utc=AFTER, attempt_ref='attempt:two')
        record = checkpoint.reconcile_checkpoint_intent(record, intent_id=intent_id,
            delivered=False, observed_at_utc=AFTER, readback_ref='readback:absent')
        record = checkpoint.begin_checkpoint_intent(record, intent_id=intent_id,
            observed_at_utc=AFTER, attempt_ref='attempt:two')
        self.assertEqual(len(intents(record)[0]['attempts']), 2)

    def test_delivered_is_idempotent_and_not_repeatable(self):
        record = staged()
        intent_id = intents(record)[0]['id']
        record = checkpoint.begin_checkpoint_intent(record, intent_id=intent_id,
            observed_at_utc=LATE, attempt_ref='attempt:one')
        kwargs = dict(intent_id=intent_id, outcome='delivered', observed_at_utc=LATE,
                      receipt_ref='transport:delivered')
        record = checkpoint.settle_checkpoint_intent(record, **kwargs)
        self.assertEqual(record, checkpoint.settle_checkpoint_intent(record, **kwargs))
        with self.assertRaises(ValueError):
            checkpoint.begin_checkpoint_intent(record, intent_id=intent_id,
                observed_at_utc=AFTER, attempt_ref='attempt:two')

    def test_revision_or_checkpoint_change_cannot_reuse_old_intent(self):
        for change in ('revision', 'checkpoint', 'owner'):
            with self.subTest(change=change):
                record = staged()
                old_id = intents(record)[0]['id']
                active = record['coordination']['active_deliverable']
                if change == 'revision':
                    active.update(revision=2, contract_digest='changed')
                elif change == 'checkpoint':
                    active['checkpoint']['receipt_ref'] = 'checkpoint:new'
                else:
                    active['owner'] = 'worker-b'
                record = checkpoint.stage_checkpoint_intents(record, now=AFTER)
                self.assertNotEqual(old_id, intents(record)[-1]['id'])
                with self.assertRaises(ValueError):
                    checkpoint.begin_checkpoint_intent(record, intent_id=old_id,
                        observed_at_utc=AFTER, attempt_ref='attempt:old')

    def test_completed_or_superseded_obligation_creates_no_intent(self):
        record = bound()
        record['status'] = 'verified-done'
        self.assertEqual(intents(checkpoint.stage_checkpoint_intents(record, now=AFTER)), [])
        record['status'] = None
        record['coordination']['active_deliverable']['state'] = 'superseded'
        self.assertEqual(intents(checkpoint.stage_checkpoint_intents(record, now=AFTER)), [])

    def test_receipt_reuse_out_of_order_and_unbound_inputs_rejected(self):
        record = staged()
        intent_id = intents(record)[0]['id']
        with self.assertRaises(ValueError):
            checkpoint.begin_checkpoint_intent(record, intent_id=intent_id,
                observed_at_utc=T0, attempt_ref='attempt:one')
        with self.assertRaises(ValueError):
            checkpoint.settle_checkpoint_intent(record, intent_id=intent_id,
                outcome='delivered', observed_at_utc=LATE, receipt_ref='transport:one')
        with self.assertRaises(ValueError):
            checkpoint.reconcile_checkpoint_intent(record, intent_id=intent_id,
                delivered=False, observed_at_utc=LATE, readback_ref='readback:none')
        record = checkpoint.begin_checkpoint_intent(record, intent_id=intent_id,
            observed_at_utc=LATE, attempt_ref='attempt:one')
        with self.assertRaises(ValueError):
            checkpoint.reconcile_checkpoint_intent(record, intent_id=intent_id,
                delivered=False, observed_at_utc=T0, readback_ref='readback:past')
        self.assertEqual(checkpoint.stage_checkpoint_intents({'task_id': 'legacy'}, now=T0),
                         {'task_id': 'legacy'})
        for value in (-1, True, 0, 86401):
            with self.assertRaises(ValueError):
                checkpoint.stage_checkpoint_intents(bound(), now=T0, escalation_after_seconds=value)


if __name__ == '__main__':
    unittest.main()
