import unittest
import hashlib
import struct
import zlib
import tempfile
from pathlib import Path

from agent_skills.task_contract import (assess_completion, checkpoint, consume_milestone,
                                        milestone, packet, resume_check, validate_checkpoint,
                                        validate_packet)

H = "a" * 64


def synthetic_png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', 3, 1, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(b'\x00' + b'\x00\x00\x00' * 3)) +
            chunk(b'IEND', b''))


def sample():
    return packet(task_id="work-7", revision=2, owner="worker-1", scope="Review code",
                  exclusions=["deployment"], baseline="commit abc", deliverables=["review"],
                  acceptance=[{"id": "a1", "check": "review has evidence"}], context_refs=[],
                  source_hashes={"core:SKILL.md": H}, package_hashes={"core:SKILL.md": H},
                  stop_conditions=["scope changed"], escalation_conditions=["blocked"])


class TaskContractTests(unittest.TestCase):
    def test_scope_change_cancellation_and_unknown_effect_block_resume(self):
        value = sample()
        saved = checkpoint(value, next_safe_action="continue", uncertain_side_effects=[], sources_fresh=True)
        self.assertEqual(resume_check(value, saved, current_revision=2, sources_fresh=True)["decision"],
                         "eligible-for-owner-review")
        for options in ({"current_revision": 3}, {"sources_fresh": False}, {"canceled": True}):
            self.assertEqual(resume_check(value, saved, **{**{"current_revision": 2,
                                                               "sources_fresh": True}, **options})["decision"],
                             "hold-and-reconcile")
        with self.assertRaises(ValueError):
            checkpoint(value, next_safe_action="retry", uncertain_side_effects=["unknown send"], sources_fresh=True)

    def test_completion_and_milestone_are_evidence_not_acceptance(self):
        value = sample()
        report = {"task_id": "work-7", "revision": 2, "packet_sha256": value["packet_sha256"],
                  "criterion_evidence": {"a1": {"reference": "review.json", "check_result": "pass",
                                                "commit": "abc", "environment": "local"}}}
        self.assertEqual(assess_completion(value, report)["status"], "evidence-complete-awaiting-acceptance")
        event = milestone(value, event_id="e1", kind="completion", reported_status="done",
                          verified_status="unverified", evidence_refs=["review.json"])
        state = {"task_id": "work-7", "revision": 2, "packet_sha256": value["packet_sha256"]}
        state, status = consume_milestone(state, event)
        self.assertEqual(status, "owner-check-needed")
        self.assertEqual(consume_milestone(state, event)[1], "duplicate")
        self.assertEqual(consume_milestone(state, {**event, "revision": 1})[1], "stale-or-foreign")

    def test_packet_tamper_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_packet({**sample(), "scope": "Deploy"})

    def test_malformed_missing_future_and_stale_checkpoints_are_held(self):
        value = sample()
        saved = checkpoint(value, next_safe_action="retry", uncertain_side_effects=[], sources_fresh=True)
        variants = [{**saved, "sources_fresh": False},
                    {key: item for key, item in saved.items() if key != "sources_fresh"},
                    {**saved, "revision": 3}, {**saved, "revision": 1},
                    {**saved, "task_id": "other"}, {**saved, "bundle_sha256": "b" * 64},
                    {**saved, "packet_sha256": "b" * 64},
                    {**saved, "next_safe_action": "deploy"},
                    {**saved, "uncertain_side_effects": ["unknown send"]},
                    {**saved, "checkpoint_sha256": "b" * 64},
                    {**saved, "unexpected": True}]
        for altered in variants:
            with self.subTest(altered=altered):
                self.assertEqual(resume_check(value, altered, current_revision=2,
                                              sources_fresh=True)["decision"], "hold-and-reconcile")
                with self.assertRaises(ValueError):
                    validate_checkpoint(value, altered)
        stale = checkpoint(value, next_safe_action="retry", uncertain_side_effects=[], sources_fresh=False)
        self.assertEqual(resume_check(value, stale, current_revision=2,
                                      sources_fresh=True)["decision"], "hold-and-reconcile")
        uncertain = checkpoint(value, next_safe_action="reconcile",
                               uncertain_side_effects=["unknown send"], sources_fresh=True)
        self.assertEqual(resume_check(value, uncertain, current_revision=2,
                                      sources_fresh=True)["decision"], "hold-and-reconcile")


if __name__ == "__main__":
    unittest.main()

class BoundEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('timeline-screenshot', 'row-inspection', 'header-screenshot', 'baseline.png'):
            (self.root / name).write_bytes(synthetic_png() if 'screenshot' in name or name == 'baseline.png' else name.encode())

    def sha(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def bound(self):
        base = sample()
        return packet(task_id='work-7', revision=2, owner='worker-1', scope='Dropped call timeline',
            exclusions=['deployment'], baseline='production screenshot', deliverables=['timeline', 'header'],
            acceptance=[
                {'id': 'timeline', 'check': 'whole same-call timeline', 'evidence_binding': {
                    'surface': 'lead-alert-drop rows', 'fixture': 'call-42 dropped state',
                    'environment': 'local', 'candidate': 'b' * 40,
                    'artifact_kinds': ['timeline-screenshot', 'row-inspection'],
                    'coverage_ids': ['lead', 'alert', 'drop']}},
                {'id': 'header', 'check': 'production header parity', 'evidence_binding': {
                    'surface': 'timeline header', 'fixture': 'call-42 dropped state',
                    'environment': 'local', 'candidate': 'b' * 40,
                'artifact_kinds': ['header-screenshot'], 'production_reference_sha256': self.sha('baseline.png')}}],
            context_refs=[], source_hashes=base['source_hashes'], package_hashes=base['package_hashes'],
            stop_conditions=['scope changed'], escalation_conditions=['blocked'])

    def evidence(self, value, *, header=True):
        items = {}
        for criterion in value['acceptance']:
            binding = criterion['evidence_binding']
            if criterion['id'] == 'header' and not header:
                continue
            items[criterion['id']] = {'reference': criterion['id'] + '.json', 'check_result': 'pass',
                'commit': binding['candidate'], 'environment': binding['environment'],
                'surface': binding['surface'], 'fixture': binding['fixture'],
                'artifact_hashes': {kind: self.sha(kind) for kind in binding['artifact_kinds']},
                'artifacts': {kind: kind for kind in binding['artifact_kinds']},
                **({'production_reference': 'baseline.png',
                    'production_reference_sha256': self.sha('baseline.png')} if 'production_reference_sha256' in binding else {})}
        return {'task_id': value['task_id'], 'revision': value['revision'],
                'packet_sha256': value['packet_sha256'], 'criterion_evidence': items}

    def verifier(self, report):
        return {'task_id': report['task_id'], 'revision': report['revision'],
                'packet_sha256': report['packet_sha256'],
                'criterion_evidence': {key: {'inspector': 'independent-verifier',
                    'inspection_result': 'pass', 'artifact_hashes': item['artifact_hashes'],
                    'artifacts': item['artifacts'],
                    **({'observed_coverage_ids': ['lead', 'alert', 'drop']} if key == 'timeline' else {}),
                    'surface': item['surface'], 'fixture': item['fixture'],
                    'environment': item['environment'], 'candidate': item['commit'],
                    **({'production_reference_sha256': item['production_reference_sha256']}
                       if 'production_reference_sha256' in item else {})}
                    for key, item in report['criterion_evidence'].items()}}

    def test_one_card_and_http_200_cannot_prove_whole_timeline(self):
        value = self.bound()
        report = self.evidence(value)
        report['criterion_evidence']['timeline']['surface'] = 'one call-card node'
        report['criterion_evidence']['timeline']['artifact_hashes'] = {'http-200': H}
        self.assertIn('timeline', assess_completion(value, report, self.verifier(report), artifact_root=self.root)['missing'])

    def test_each_binding_and_production_baseline_must_match(self):
        value = self.bound()
        for key, wrong in [('surface', 'call card'), ('fixture', 'other call'),
                           ('environment', 'staging'), ('commit', 'c' * 40),
                           ('production_reference_sha256', 'c' * 64)]:
            report = self.evidence(value)
            report['criterion_evidence']['header'][key] = wrong
            with self.subTest(key=key):
                self.assertIn('header', assess_completion(value, report, self.verifier(report), artifact_root=self.root)['missing'])
        report = self.evidence(value)
        del report['criterion_evidence']['header']['production_reference_sha256']
        self.assertIn('header', assess_completion(value, report, self.verifier(report), artifact_root=self.root)['missing'])

    def test_hard_criteria_and_packet_revision_are_independent(self):
        value = self.bound()
        self.assertEqual(assess_completion(value, self.evidence(value, header=False), self.verifier(self.evidence(value, header=False)), artifact_root=self.root)['missing'], ['header'])
        newer = {**value, 'revision': 3}
        self.assertEqual(assess_completion(value, {**self.evidence(value), 'packet_sha256': 'old'})['status'],
                         'stale-or-foreign')

class BoundVerifierTests(BoundEvidenceTests):
    def test_verifier_must_inspect_exact_artifact_and_surface(self):
        value = self.bound()
        report = self.evidence(value)
        verified = self.verifier(report)
        self.assertEqual(assess_completion(value, report, verified, artifact_root=self.root)['status'],
                         'evidence-complete-awaiting-acceptance')
        for key, wrong in [('surface', 'one card'), ('fixture', 'other call'),
                           ('environment', 'staging'), ('candidate', 'c' * 40),
                           ('production_reference_sha256', 'c' * 64)]:
            altered = self.verifier(report)
            altered['criterion_evidence']['header'][key] = wrong
            with self.subTest(key=key):
                self.assertIn('header', assess_completion(value, report, altered, artifact_root=self.root)['missing'])
        altered = self.verifier(report)
        altered['criterion_evidence']['header']['artifact_hashes'] = {'header-screenshot': 'c' * 64}
        self.assertIn('header', assess_completion(value, report, altered, artifact_root=self.root)['missing'])
        altered = self.verifier(report)
        altered['criterion_evidence']['timeline']['observed_coverage_ids'] = ['lead']
        self.assertIn('timeline', assess_completion(value, report, altered, artifact_root=self.root)['missing'])
        altered = self.verifier(report)
        altered['criterion_evidence']['timeline']['artifacts'] = {'timeline-screenshot': 'other.png', 'row-inspection': 'row-inspection'}
        self.assertIn('timeline', assess_completion(value, report, altered, artifact_root=self.root)['missing'])
        (self.root / 'timeline-screenshot').write_bytes(b'HTTP/1.1 200 OK')
        report = self.evidence(value)
        self.assertIn('timeline', assess_completion(value, report, self.verifier(report), artifact_root=self.root)['missing'])
