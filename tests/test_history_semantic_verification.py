"""Publication verifies journal derivation, not a self-authored body hash."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'skills/task-history'
sys.path.insert(0, str(MODULE))
import checkpoint_capture
import history
import markdown


class SemanticPublicationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve()
        (self.repo / 'views').mkdir()
        (self.repo / 'INDEX.md').write_text('[view](views/task-001.md) [events](events/task-001.jsonl)\n')
        self.rows = [dict(schema_version=1, event_id='event-001', task_id='task-001',
            session_id='session-001', revision=1, record_owner='owner',
            at_utc='2026-10-24T00:00:00Z', observed_at_utc='2026-10-24T00:00:00Z',
            kind='start', status='active', summary='Synthetic authoritative event')]
        history.validate(self.rows[0])
        self.digest = 'a' * 64
        self.view = self.repo / 'views/task-001.md'
        self.expected = markdown.document(self.rows, history.project(self.rows, self.digest))
        self.view.write_text(self.expected)

    def verify(self, **kwargs):
        with patch.object(history, 'snapshot', return_value=(self.rows, self.digest)):
            return checkpoint_capture.verify_publication(self.repo, task_id='task-001',
                event_id='event-001', expected_digest=self.digest, reader_ref='fixture:reader', **kwargs)

    def test_exact_current_render_passes_without_rewriting_legacy_marker(self):
        result = self.verify()
        self.assertEqual(self.view.read_text(), self.expected)
        self.assertEqual(result['digest'], self.digest)

    def test_self_sealed_false_view_is_rejected_and_preserved(self):
        body = '# An unrelated claim with a genuine journal digest\n'
        forged = ('<!-- task-history:generated sha256=' + hashlib.sha256(body.encode()).hexdigest() +
                  ' source=' + self.digest + ' -->\n' + body)
        self.view.write_text(forged)
        with self.assertRaisesRegex(ValueError, 'journal-derived'):
            self.verify()
        self.assertEqual(self.view.read_text(), forged)

    def test_user_edited_and_different_renderer_views_are_preserved(self):
        for content in ('# User note\n', self.expected + 'manual addition\n'):
            self.view.write_text(content)
            with self.assertRaises(ValueError): self.verify()
            self.assertEqual(self.view.read_text(), content)

    def test_explicit_renderer_pin_mismatch_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, 'renderer'):
            self.verify(expected_renderer_sha256='b' * 64)
        self.assertEqual(self.view.read_text(), self.expected)
