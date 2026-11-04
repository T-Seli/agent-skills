import json
import hashlib
import struct
import zlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_skills.closeout import cleanup_gate, completion_gate, handoff_gate, main_sync_gate
from agent_skills.history import append, read
from agent_skills.source_readiness import (compare_receipt, installed_links,
                                           runtime_capability_receipt, source_receipt)
from agent_skills.task_contract import checkpoint, packet

H = "a" * 64


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def sample():
    return packet(task_id="task-1", revision=1, owner="worker-1", scope="review",
                  exclusions=["deploy"], baseline="abc", deliverables=["report"],
                  acceptance=[{"id": "a1", "check": "tests pass"}], context_refs=[],
                  source_hashes={"core:SKILL.md": H}, package_hashes={"core:SKILL.md": H},
                  stop_conditions=["scope change"], escalation_conditions=["blocked"])


class SourceHistoryCloseoutTests(unittest.TestCase):
    def test_main_sync_gate_requires_exact_clean_fetched_main_and_no_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin, main = Path(tmp) / "origin.git", Path(tmp) / "main"
            run("git", "init", "-q", "--bare", str(origin))
            run("git", "clone", "-q", str(origin), str(main))
            run("git", "-C", str(main), "checkout", "-qb", "main")
            (main / "x").write_text("base")
            run("git", "-C", str(main), "add", "x")
            run("git", "-C", str(main), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "-qm", "base")
            run("git", "-C", str(main), "push", "-q", "-u", "origin", "main")
            sha = run("git", "-C", str(main), "rev-parse", "origin/main")
            lock = main / ".git/deploy.lock"
            self.assertTrue(main_sync_gate(main, base="main", repository="origin",
                                           fetched_sha=sha, lock_path=lock)["ready"])
            lock.mkdir()
            self.assertFalse(main_sync_gate(main, base="main", repository="origin",
                                            fetched_sha=sha, lock_path=lock)["ready"])
            lock.rmdir()
            (main / ".git/info/exclude").write_text("ignored.bin\n")
            (main / "ignored.bin").write_text("keep")
            self.assertTrue(main_sync_gate(main, base="main", repository="origin",
                                           fetched_sha=sha, lock_path=lock)["ready"])
            self.assertEqual((main / "ignored.bin").read_text(), "keep")
            (main / "untracked.bin").write_text("user work")
            result = main_sync_gate(main, base="main", repository="origin",
                                    fetched_sha=sha, lock_path=lock)
            self.assertFalse(result["ready"])
            self.assertIn("tracked or non-ignored untracked", result["reason"])
            self.assertEqual((main / "untracked.bin").read_text(), "user work")

    def test_runtime_receipt_separates_installed_loaded_and_exercised_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'release'
            route_root = Path(tmp) / 'runtime'
            (root / 'skills').mkdir(parents=True)
            route_root.mkdir()
            body = root / 'skills' / 'fixture.md'
            body.write_text('fixture\n')
            commit, tree = 'a' * 40, 'b' * 40
            (root / '.release-pin.json').write_text(json.dumps({
                'source': 'T-Seli/agent-skills', 'commit': commit, 'tree': tree}))
            route = route_root / 'fixture'
            route.symlink_to(body)
            digest = hashlib.sha256(body.read_bytes()).hexdigest()
            bundle = {'sources': [{'path': 'skills/fixture.md', 'sha256': digest}],
                      'load_receipt': {'runtime': 'codex', 'session_id': 'session-1',
                                       'reader': 'native-skill-reader', 'read_ref': 'read:fixture-1',
                                       'selected_path': 'skills/fixture.md', 'sha256': digest}}
            ready = runtime_capability_receipt(
                root, runtime='codex', expected_commit=commit, expected_tree=tree,
                installed_routes={'fixture': {'route': route, 'source': 'skills/fixture.md'}},
                loaded_bundle=bundle,
                behavior_checks=[{'id': 'selected-body-used', 'outcome': 'pass',
                                  'receipt_ref': 'fixture:behavior-1'}])
            self.assertTrue(ready['ready'])
            claude_bundle = {**bundle, 'load_receipt': {**bundle['load_receipt'],
                                                        'runtime': 'claude',
                                                        'session_id': 'session-2'}}
            blocked = runtime_capability_receipt(
                root, runtime='claude', expected_commit=commit, expected_tree=tree,
                installed_routes={'fixture': {'route': route, 'source': 'skills/fixture.md'}},
                loaded_bundle=claude_bundle,
                behavior_checks=[{'id': 'fresh-session-readback', 'outcome': 'blocked',
                                  'receipt_ref': 'fixture:no-native-reader'}])
            self.assertTrue(blocked['installed_ready'])
            self.assertTrue(blocked['loaded_ready'])
            self.assertFalse(blocked['behavior_ready'])
            self.assertFalse(blocked['ready'])
            for invalid in ({'sources': bundle['sources']},
                            {**bundle, 'load_receipt': {**bundle['load_receipt'], 'runtime': 'claude'}},
                            {**bundle, 'load_receipt': {**bundle['load_receipt'], 'sha256': '0' * 64}}):
                with self.subTest(invalid=invalid):
                    result = runtime_capability_receipt(
                        root, runtime='codex', expected_commit=commit, expected_tree=tree,
                        installed_routes={'fixture': {'route': route, 'source': 'skills/fixture.md'}},
                        loaded_bundle=invalid,
                        behavior_checks=[{'id': 'selected-body-used', 'outcome': 'pass',
                                          'receipt_ref': 'fixture:behavior-1'}])
                    self.assertFalse(result['loaded_ready'])
                    self.assertFalse(result['ready'])
            wrong = root / 'skills' / 'other.md'
            wrong.write_text('other\n')
            route.unlink()
            route.symlink_to(wrong)
            mismatch = runtime_capability_receipt(
                root, runtime='codex', expected_commit=commit, expected_tree=tree,
                installed_routes={'fixture': {'route': route, 'source': 'skills/fixture.md'}},
                loaded_bundle=bundle,
                behavior_checks=[{'id': 'selected-body-used', 'outcome': 'pass',
                                  'receipt_ref': 'fixture:behavior-1'}])
            self.assertFalse(mismatch['installed_ready'])
            self.assertFalse(mismatch['ready'])
            route.unlink()
            route.symlink_to(body)
            duplicate = {**bundle, 'sources': [
                {'path': 'skills/fixture.md', 'sha256': '0' * 64},
                {'path': 'skills/fixture.md', 'sha256': digest}],
                'load_receipt': {**bundle['load_receipt'], 'sha256': '0' * 64}}
            with self.assertRaisesRegex(ValueError, 'duplicate loaded source path'):
                runtime_capability_receipt(
                    root, runtime='codex', expected_commit=commit, expected_tree=tree,
                    installed_routes={'fixture': {'route': route, 'source': 'skills/fixture.md'}},
                    loaded_bundle=duplicate,
                    behavior_checks=[{'id': 'selected-body-used', 'outcome': 'pass',
                                      'receipt_ref': 'fixture:behavior-1'}])

    def test_runtime_receipt_accepts_loaded_file_under_linked_skill_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'release'
            skill = root / 'skills' / 'fixture'
            route_root = Path(tmp) / 'runtime'
            skill.mkdir(parents=True)
            route_root.mkdir()
            body = skill / 'SKILL.md'
            body.write_text('fixture\n')
            commit, tree = 'a' * 40, 'b' * 40
            (root / '.release-pin.json').write_text(json.dumps({
                'source': 'T-Seli/agent-skills', 'commit': commit, 'tree': tree}))
            route = route_root / 'fixture'
            route.symlink_to(skill, target_is_directory=True)
            digest = hashlib.sha256(body.read_bytes()).hexdigest()
            result = runtime_capability_receipt(
                root, runtime='codex', expected_commit=commit, expected_tree=tree,
                installed_routes={'fixture': {'route': route, 'source': 'skills/fixture'}},
                loaded_bundle={'sources': [{'path': 'skills/fixture/SKILL.md', 'sha256': digest}],
                               'load_receipt': {'runtime': 'codex', 'session_id': 'session-1',
                                                'reader': 'native-skill-reader', 'read_ref': 'read:fixture-1',
                                                'selected_path': 'skills/fixture/SKILL.md', 'sha256': digest}},
                behavior_checks=[{'id': 'selected-body-used', 'outcome': 'pass',
                                  'receipt_ref': 'fixture:behavior-1'}])
            self.assertTrue(result['ready'])
            sibling = root / 'skills' / 'other.md'
            sibling.write_text('not the routed skill\n')
            sibling_digest = hashlib.sha256(sibling.read_bytes()).hexdigest()
            escaped = runtime_capability_receipt(
                root, runtime='codex', expected_commit=commit, expected_tree=tree,
                installed_routes={'fixture': {'route': route, 'source': 'skills/fixture'}},
                loaded_bundle={'sources': [{'path': 'skills/fixture/../other.md',
                                            'sha256': sibling_digest}],
                               'load_receipt': {'runtime': 'codex', 'session_id': 'session-1',
                                                'reader': 'native-skill-reader', 'read_ref': 'read:escape',
                                                'selected_path': 'skills/fixture/../other.md',
                                                'sha256': sibling_digest}},
                behavior_checks=[{'id': 'selected-body-used', 'outcome': 'pass',
                                  'receipt_ref': 'fixture:behavior-escape'}])
            self.assertFalse(escaped['loaded_ready'])
            self.assertFalse(escaped['ready'])

    def test_bound_closeout_requires_current_independent_artifact_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def chunk(kind, data):
                return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
            image = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 3, 1, 8, 2, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress(b'\x00' + b'\x00\x00\x00' * 3)) + chunk(b'IEND', b''))
            (root / 'timeline.png').write_bytes(image)
            sha = hashlib.sha256((root / 'timeline.png').read_bytes()).hexdigest()
            value = packet(task_id='task-1', revision=1, owner='worker-1', scope='timeline',
                           exclusions=['deploy'], baseline='abc', deliverables=['timeline'],
                           acceptance=[{'id': 'a1', 'check': 'whole timeline', 'evidence_binding': {
                               'surface': 'whole timeline', 'fixture': 'synthetic call',
                               'environment': 'local', 'candidate': 'b' * 40,
                               'artifact_kinds': ['screenshot'], 'coverage_ids': ['lead', 'alert', 'drop']}}], context_refs=[],
                           source_hashes={'core:SKILL.md': H}, package_hashes={'core:SKILL.md': H},
                           stop_conditions=['scope change'], escalation_conditions=['blocked'])
            envelope = {'task_id': 'task-1', 'revision': 1, 'packet_sha256': value['packet_sha256']}
            report = {**envelope, 'criterion_evidence': {'a1': {
                'reference': 'timeline.png', 'check_result': 'pass', 'commit': 'b' * 40,
                'environment': 'local', 'surface': 'whole timeline', 'fixture': 'synthetic call',
                'artifacts': {'screenshot': 'timeline.png'}, 'artifact_hashes': {'screenshot': sha}}}}
            inspection = {**envelope, 'criterion_evidence': {'a1': {
                'inspector': 'verifier-1', 'inspection_result': 'pass',
                'surface': 'whole timeline', 'fixture': 'synthetic call', 'environment': 'local',
                'candidate': 'b' * 40, 'artifact_hashes': {'screenshot': sha},
                'artifacts': {'screenshot': 'timeline.png'},
                'observed_coverage_ids': ['lead', 'alert', 'drop']}}}
            self.assertEqual(completion_gate(value, report, owner_verified=True,
                                             human_accepted=True, artifact_root=root)['decision'], 'hold')
            self.assertEqual(completion_gate(value, report, verifier_report=inspection,
                                             artifact_root=root, owner_verified=True,
                                             human_accepted=True)['decision'], 'accepted')
            (root / 'timeline.png').write_bytes(b'changed')
            self.assertEqual(completion_gate(value, report, verifier_report=inspection,
                                             artifact_root=root, owner_verified=True,
                                             human_accepted=True)['decision'], 'hold')

    def test_source_receipt_and_links_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            run("git", "-C", str(root), "init", "-q")
            for name in ("agent_skills/catalog.json", "skills/workflow-contracts/contracts.md",
                         "global/CLAUDE.md", "install.sh"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            run("git", "-C", str(root), "add", ".")
            run("git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
            receipt = source_receipt(root)
            self.assertTrue(compare_receipt(root, receipt)["ready"])
            self.assertFalse(compare_receipt(root / "missing", receipt)["ready"])
            with self.assertRaises(ValueError):
                source_receipt(root, expected_commit=receipt["commit"][:7])
            self.assertFalse(installed_links(root, Path(tmp) / "empty-home")["ready"])
            (root / "install.sh").write_text("changed")
            self.assertFalse(compare_receipt(root, receipt)["ready"])

    def test_history_is_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {"event_id": "e1", "task_id": "task-1", "revision": 1,
                   "at": "2026-10-02T00:00:00Z", "kind": "decision",
                   "summary": "Approved local implementation", "refs": ["chat:123"]}
            self.assertEqual(append(tmp, row), "appended")
            self.assertEqual(stat.S_IMODE((Path(tmp) / "task-1.jsonl").stat().st_mode), 0o600)
            self.assertEqual(append(tmp, row), "duplicate")
            self.assertEqual(read(tmp, "task-1"), [row])
            with self.assertRaises(ValueError):
                append(tmp, {**row, "event_id": "e2", "summary": "secret\nsecond line"})
            with self.assertRaises(ValueError):
                read(tmp, "../escape")
            with self.assertRaises(ValueError):
                append(tmp, {**row, "summary": "different"})
            os.chmod(tmp, 0o755)
            with self.assertRaises(ValueError):
                append(tmp, {**row, "event_id": "e3"})

    def test_handoff_completion_and_cleanup_gate(self):
        value = sample()
        saved = checkpoint(value, next_safe_action="continue", uncertain_side_effects=[], sources_fresh=True)
        self.assertEqual(handoff_gate(value, saved, current_revision=1, sources_fresh=True)["decision"],
                         "eligible-for-owner-review")
        self.assertEqual(handoff_gate(value, saved, current_revision=2, sources_fresh=True)["decision"],
                         "hold-and-reconcile")
        report = {"task_id": "task-1", "revision": 1, "packet_sha256": value["packet_sha256"],
                  "criterion_evidence": {"a1": {"reference": "report", "check_result": "pass",
                                                "commit": "abc", "environment": "local"}}}
        self.assertEqual(completion_gate(value, report)["decision"], "await-owner-or-human-acceptance")
        self.assertEqual(completion_gate(value, report, owner_verified=True, human_accepted=True)["decision"], "accepted")
        with tempfile.TemporaryDirectory() as tmp:
            main, worktree = Path(tmp) / "main", Path(tmp) / "task"
            main.mkdir()
            run("git", "-C", str(main), "init", "-q", "-b", "main")
            (main / "x").write_text("base")
            run("git", "-C", str(main), "add", ".")
            run("git", "-C", str(main), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
            run("git", "-C", str(main), "worktree", "add", "-qb", "feat/test", str(worktree))
            self.assertTrue(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                         completion_accepted=True, no_pending_effects=True)["eligible"])
            (worktree / "x").write_text("changed")
            self.assertFalse(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                          completion_accepted=True, no_pending_effects=True)["eligible"])
            run("git", "-C", str(worktree), "add", ".")
            run("git", "-C", str(worktree), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "change")
            self.assertFalse(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                          completion_accepted=True, no_pending_effects=True)["eligible"])
            run("git", "-C", str(main), "merge", "--ff-only", "feat/test")
            self.assertTrue(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                         completion_accepted=True, no_pending_effects=True)["eligible"])
            exclude = Path(run("git", "-C", str(worktree), "rev-parse", "--git-path", "info/exclude"))
            exclude.write_text("deps\n")
            (worktree / "deps").mkdir()
            (worktree / "deps/a.js").write_text("keep")
            self.assertFalse(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                          completion_accepted=True, no_pending_effects=True)["eligible"])
            shutil.rmtree(worktree / "deps")
            lock = main / ".git/deploy.lock"
            lock.mkdir()
            (lock / "owner").write_text("agent feat/test 2026-10-09T00:00:00Z\n")
            self.assertFalse(cleanup_gate(
                main, worktree, base="main", branch="feat/test", completion_accepted=True,
                no_pending_effects=True, lock_path=lock, expected_lock_owner="another owner")["eligible"])
            self.assertTrue(cleanup_gate(
                main, worktree, base="main", branch="feat/test", completion_accepted=True,
                no_pending_effects=True, lock_path=lock,
                expected_lock_owner="agent feat/test 2026-10-09T00:00:00Z",
                remote_base=run("git", "-C", str(main), "rev-parse", "main"))["eligible"])
            self.assertFalse(cleanup_gate(
                main, worktree, base="main", branch="feat/test", completion_accepted=True,
                no_pending_effects=True, remote_base="0" * 40)["eligible"])
            self.assertFalse(cleanup_gate(main, worktree, base="main", branch="feat/test",
                                          completion_accepted=False, no_pending_effects=True)["eligible"])


COMMIT = ("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm")


class CleanupGateRefinementTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.main, self.worktree = Path(self._tmp.name).resolve() / "main", Path(self._tmp.name).resolve() / "task"
        self.main.mkdir()
        run("git", "-C", str(self.main), "init", "-q", "-b", "main")
        (self.main / "x").write_text("base")
        (self.main / ".gitignore").write_text("node_modules\n")
        run("git", "-C", str(self.main), "add", ".")
        run("git", "-C", str(self.main), *COMMIT, "base")
        (self.main / "node_modules").mkdir()
        (self.main / "node_modules/dep.js").write_text("dep")

    def gate(self, **extra):
        args = dict(base="main", branch="feat/test", completion_accepted=True, no_pending_effects=True)
        return cleanup_gate(self.main, self.worktree, **{**args, **extra})

    def add_worktree(self, *flags, branch="feat/test"):
        run("git", "-C", str(self.main), "worktree", "add", "-q", *flags, *(["-b", branch] if branch else []),
            str(self.worktree), *([] if branch else ["--detach"]))

    def commit_in(self, root, name, text):
        (root / name).write_text(text)
        run("git", "-C", str(root), "add", name)
        run("git", "-C", str(root), *COMMIT, name)

    def test_ignored_symlink_into_main_is_eligible(self):
        self.add_worktree()
        (self.worktree / "node_modules").symlink_to(self.main / "node_modules")
        self.assertTrue(self.gate()["eligible"])

    def test_ignored_identical_copy_is_eligible_and_edited_copy_is_not(self):
        (self.main / "local.cfg").write_text("A=1")
        (self.main / ".git/info/exclude").write_text("local.cfg\n")
        self.add_worktree()
        (self.worktree / "local.cfg").write_text("A=1")
        self.assertTrue(self.gate()["eligible"])
        (self.worktree / "local.cfg").write_text("A=2")
        self.assertFalse(self.gate()["eligible"])

    def test_real_ignored_dir_needs_rebuildable_declaration(self):
        self.add_worktree()
        (self.worktree / "node_modules").mkdir()
        (self.worktree / "node_modules/dep.js").write_text("dep")
        self.assertFalse(self.gate()["eligible"])
        self.assertTrue(self.gate(rebuildable=["node_modules"])["eligible"])
        self.assertFalse(self.gate(rebuildable=["other"])["eligible"])

    def test_untracked_file_blocks_even_when_rebuildable_declared(self):
        self.add_worktree()
        (self.worktree / "notes.txt").write_text("mine")
        self.assertFalse(self.gate(rebuildable=["node_modules"])["eligible"])

    def test_squash_merged_branch_is_removable_by_no_op_proof(self):
        self.add_worktree()
        self.commit_in(self.worktree, "feature", "new")
        self.assertFalse(self.gate()["eligible"])
        run("git", "-C", str(self.main), "merge", "-q", "--squash", "feat/test")
        run("git", "-C", str(self.main), *COMMIT, "squash")
        result = self.gate()
        self.assertTrue(result["eligible"])
        self.assertEqual(result["merge"], "no-op")

    def test_fast_forward_merge_reports_ancestor(self):
        self.add_worktree()
        self.commit_in(self.worktree, "feature", "new")
        run("git", "-C", str(self.main), "merge", "-q", "--ff-only", "feat/test")
        self.assertEqual(self.gate()["merge"], "ancestor")

    def test_lock_naming_this_branch_is_eligible_and_asks_for_unlock(self):
        self.add_worktree("--lock", "--reason", "agent feat/test 2026-11-03T22:30:00Z")
        result = self.gate()
        self.assertTrue(result["eligible"])
        self.assertTrue(result["unlock"])

    def test_foreign_or_empty_lock_reason_is_ineligible(self):
        self.add_worktree("--lock", "--reason", "agent feat/other 2026-11-03T22:30:00Z")
        self.assertFalse(self.gate()["eligible"])
        run("git", "-C", str(self.main), "worktree", "unlock", str(self.worktree))
        run("git", "-C", str(self.main), "worktree", "lock", str(self.worktree))
        self.assertFalse(self.gate()["eligible"])

    def test_unlocked_worktree_does_not_ask_for_unlock(self):
        self.add_worktree()
        self.assertFalse(self.gate()["unlock"])

    def test_detached_base_worktree_contained_in_base_is_eligible(self):
        self.add_worktree(branch=None)
        result = self.gate(branch=None)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["merge"], "ancestor")

    def test_detached_head_contained_in_fetched_origin_base_is_eligible_when_local_base_lags(self):
        run("git", "-C", str(self.main), "checkout", "-q", "-b", "upstream")
        self.commit_in(self.main, "upstream", "merged on the host")
        ahead = run("git", "-C", str(self.main), "rev-parse", "HEAD")
        run("git", "-C", str(self.main), "checkout", "-q", "main")
        run("git", "-C", str(self.main), "update-ref", "refs/remotes/origin/main", ahead)
        run("git", "-C", str(self.main), "worktree", "add", "-q", "--detach", str(self.worktree), ahead)
        result = self.gate(branch=None)
        self.assertTrue(result["eligible"], result)
        self.assertEqual(result["merge"], "ancestor")

    def test_detached_mode_rejects_a_branch_checkout_and_uncontained_head(self):
        self.add_worktree()
        self.assertFalse(self.gate(branch=None)["eligible"])
        run("git", "-C", str(self.worktree), "checkout", "-q", "--detach")
        self.commit_in(self.worktree, "feature", "new")
        self.assertFalse(self.gate(branch=None)["eligible"])

    def test_detached_lock_names_run_id(self):
        self.add_worktree("--lock", "--reason", "test-review run7", branch=None)
        self.assertFalse(self.gate(branch=None)["eligible"])
        result = self.gate(branch=None, run_id="run7")
        self.assertTrue(result["eligible"])
        self.assertTrue(result["unlock"])


ROOT = Path(__file__).resolve().parents[1]


class SweepTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.main = self.tmp / "main"
        self.main.mkdir()
        run("git", "-C", str(self.main), "init", "-q", "-b", "main")
        (self.main / "x").write_text("base")
        run("git", "-C", str(self.main), "add", ".")
        run("git", "-C", str(self.main), *COMMIT, "base")
        self.config = self.tmp / "workers.json"
        self.config.write_text("{}")
        self.sleepers = []
        self.addCleanup(lambda: [p.kill() for p in self.sleepers])

    def merged_worktree(self, name, *flags):
        path = self.tmp / name
        run("git", "-C", str(self.main), "worktree", "add", "-q", *flags, "-b", f"feat/{name}", str(path))
        (path / f"{name}.txt").write_text(name)
        run("git", "-C", str(path), "add", ".")
        run("git", "-C", str(path), *COMMIT, name)
        run("git", "-C", str(self.main), "merge", "-q", "--ff-only", f"feat/{name}")
        return path

    def backdate(self, path):
        gitdir = Path(run("git", "-C", str(path), "rev-parse", "--absolute-git-dir"))
        old = time.time() - 10 * 3600
        for name in ("index", "logs/HEAD"):
            os.utime(gitdir / name, (old, old))

    def sweep(self, *args, **extra_env):
        env = dict(os.environ, AGENT_SKILLS_CONFIG=str(self.config), PYTHONDONTWRITEBYTECODE="1", **extra_env)
        return subprocess.run([sys.executable, "-m", "agent_skills.safeguard_cli", "sweep", str(self.main),
                               "--base", "main", *args], cwd=ROOT, env=env, capture_output=True, text=True)

    def fixture(self):
        paths = {}
        owner = lambda name: ("--lock", "--reason", f"agent feat/{name} 2026-11-03T00:00:00Z")
        for name in ("done", "held", "leased", "dirty", "recent"):
            paths[name] = self.merged_worktree(name, *owner(name))
        paths["legacy"] = self.merged_worktree("legacy", "--lock")
        (paths["dirty"] / "notes.txt").write_text("mine")
        base = self.tmp / "_base-abc1234-run9"
        run("git", "-C", str(self.main), "worktree", "add", "-q", "--detach", "--lock", "--reason",
            "test-review run9", str(base))
        paths["base"] = base
        self.sleepers.append(subprocess.Popen(["sleep", "60"], cwd=paths["held"]))
        self.lease = self.tmp / "leases.txt"
        self.lease.write_text(f"{paths['leased']}\n")
        self.config.write_text(json.dumps({"worktree_lease_files": [str(self.lease)]}))
        for name, path in paths.items():
            if name != "recent":
                self.backdate(path)
        return paths

    def test_dry_run_lists_only_merged_clean_unheld_candidates_and_removes_nothing(self):
        paths = self.fixture()
        result = self.sweep()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(sorted(Path(c["worktree"]).name for c in report["candidates"]),
                         ["_base-abc1234-run9", "done"])
        held = {Path(h["worktree"]).name for h in report["held"]}
        self.assertEqual(held, {"held", "leased", "recent"})
        self.assertEqual(sorted(Path(k["worktree"]).name for k in report["kept"]), ["dirty", "legacy"])
        self.assertTrue(all(p.exists() for p in paths.values()))

    def test_apply_removes_only_candidates_and_deletes_branches_only_on_ancestor(self):
        paths = self.fixture()
        result = self.sweep("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, gone in (("done", True), ("base", True), ("held", False), ("leased", False),
                           ("dirty", False), ("recent", False), ("legacy", False)):
            self.assertEqual(not paths[name].exists(), gone, name)
        branches = run("git", "-C", str(self.main), "branch", "--format=%(refname:short)").split()
        self.assertNotIn("feat/done", branches)
        self.assertIn("feat/dirty", branches)

    def test_unreadable_lease_file_exits_1_and_removes_nothing(self):
        paths = self.fixture()
        self.config.write_text(json.dumps({"worktree_lease_files": [str(self.tmp / "missing.txt")]}))
        result = self.sweep("--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("safeguard failed", result.stderr)
        self.assertTrue(all(p.exists() for p in paths.values()))

    def test_worktree_whose_git_status_hangs_is_kept_and_the_sweep_continues(self):
        done, stuck = self.merged_worktree("done"), self.merged_worktree("stuck")
        for path in (done, stuck):
            self.backdate(path)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "git"
        fake.write_text(f'#!/bin/sh\ncase "$*" in *"{stuck}"*status*) exec sleep 15;; esac\n'
                        f'exec {shutil.which("git")} "$@"\n')
        fake.chmod(0o755)
        started = time.monotonic()
        result = self.sweep(PATH=f"{bin_dir}:{os.environ['PATH']}", AGENT_SKILLS_GIT_TIMEOUT="1")
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([Path(c["worktree"]).name for c in report["candidates"]], ["done"])
        self.assertEqual(report["kept"], [{"worktree": str(stuck), "reason": "git timed out after 1s"}])

    def test_worktree_with_a_broken_symlink_is_kept_and_the_sweep_continues(self):
        (self.main / ".gitignore").write_text(".env\n")
        run("git", "-C", str(self.main), "add", ".gitignore")
        run("git", "-C", str(self.main), *COMMIT, "ignore env")
        done, looped = self.merged_worktree("done"), self.merged_worktree("looped")
        (self.main / ".env").symlink_to(self.main / ".env")
        (looped / ".env").symlink_to(self.main / ".env")
        for path in (done, looped):
            self.backdate(path)
        result = self.sweep()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([Path(c["worktree"]).name for c in report["candidates"]], ["done"])
        self.assertEqual(report["kept"], [{"worktree": str(looped), "reason": "broken symlink: .env"}])

    def test_apply_lets_a_slow_worktree_removal_finish(self):
        done = self.merged_worktree("done")
        self.backdate(done)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "git"
        fake.write_text(f'#!/bin/sh\ncase "$*" in *"worktree remove"*) sleep 2;; esac\n'
                        f'exec {shutil.which("git")} "$@"\n')
        fake.chmod(0o755)
        result = self.sweep("--apply", PATH=f"{bin_dir}:{os.environ['PATH']}", AGENT_SKILLS_GIT_TIMEOUT="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(done.exists())

    def test_json_lease_file_holds_every_absolute_path_it_names(self):
        paths = self.fixture()
        self.lease.write_text(json.dumps({"worktrees": {"leased": {
            "path": str(paths["leased"]), "baseRepo": str(self.main), "leasedBy": "session-1"}}}))
        result = self.sweep()
        self.assertEqual(result.returncode, 0, result.stderr)
        held = {Path(h["worktree"]).name for h in json.loads(result.stdout)["held"]}
        self.assertEqual(held, {"held", "leased", "recent"})

    def test_squash_merged_worktree_is_removed_but_its_branch_is_kept(self):
        path = self.tmp / "squashed"
        run("git", "-C", str(self.main), "worktree", "add", "-q", "-b", "feat/squashed", str(path))
        (path / "s.txt").write_text("s")
        run("git", "-C", str(path), "add", ".")
        run("git", "-C", str(path), *COMMIT, "s")
        run("git", "-C", str(self.main), "merge", "-q", "--squash", "feat/squashed")
        run("git", "-C", str(self.main), *COMMIT, "squash")
        self.backdate(path)
        result = self.sweep("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(path.exists())
        self.assertIn("feat/squashed", run("git", "-C", str(self.main), "branch", "--format=%(refname:short)").split())
