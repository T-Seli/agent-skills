import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_skills.release_maintenance import maintain_release


COMMIT = "a" * 40
TREE = "b" * 40
BODY = "c" * 64
OLD_COMMIT = "d" * 40
OLD_TREE = "e" * 40


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def observation(state="unknown", *, commit=None, tree=None, dimension="loaded"):
    if state == "verified":
        session = None if dimension == "installed" else "session-1"
        body = None if dimension == "installed" else BODY
        checkpoint = "resume"
        receipt = "fixture:receipt"
    else:
        commit = tree = session = body = checkpoint = None
        receipt = None
    return {"state": state, "commit": commit, "tree": tree, "receipt_ref": receipt,
            "session_id": session, "body_sha256": body, "checkpoint": checkpoint}


def manifest():
    return {"schema_version": 1, "targets": [
        {"id": "local-codex", "adapter": "codex", "runtime": "codex-cli",
         "activation": "native-installer", "required": True,
         "manual_action": None, "unsupported_reason": None},
    ]}


def state(commit=COMMIT, tree=TREE, installed=None):
    return {"schema_version": 1, "checkpoint": "resume",
            "desired": {"source": "owner/repo", "commit": commit, "tree": tree},
            "targets": {"local-codex": {
                "active_task": False,
                "rollback_ref": "release:previous",
                "current_session_id": "session-1",
                "expected_body_sha256": BODY,
                "installed": installed or observation("pending"),
                "loaded": observation(),
                "behavior_verified": observation(),
            }}}


def request(action, parameters, commit=COMMIT, tree=TREE, observed="automatic"):
    return {"schema_version": 1, "checkpoint": "resume",
            "approval": {"ref": "approval:fixture", "action": action,
                         "source": "owner/repo", "commit": commit, "tree": tree},
            "admission": {"expected_reviewer_mode": "automatic",
                          "observed_reviewer_mode": observed,
                          "receipt_ref": "fixture:reviewer-mode" if observed else None},
            "parameters": parameters}


class ReleaseMaintenanceTests(unittest.TestCase):
    def repository(self, root):
        origin = root / "owner" / "repo.git"
        seed = root / "seed"
        main = root / "main"
        origin.parent.mkdir()
        run("git", "init", "-q", "--bare", "--initial-branch=main", str(origin))
        run("git", "clone", "-q", str(origin), str(seed))
        run("git", "-C", str(seed), "config", "user.name", "Fixture")
        run("git", "-C", str(seed), "config", "user.email", "fixture@example.invalid")
        (seed / "release.txt").write_text("one\n")
        run("git", "-C", str(seed), "add", "release.txt")
        run("git", "-C", str(seed), "commit", "-qm", "initial")
        run("git", "-C", str(seed), "push", "-q", "origin", "main")
        run("git", "clone", "-q", str(origin), str(main))
        return origin, seed, main

    def advance(self, seed, main):
        (seed / "release.txt").write_text("two\n")
        run("git", "-C", str(seed), "add", "release.txt")
        run("git", "-C", str(seed), "commit", "-qm", "advance")
        run("git", "-C", str(seed), "push", "-q", "origin", "main")
        run("git", "-C", str(main), "fetch", "-q", "origin")
        return run("git", "-C", str(main), "rev-parse", "origin/main")

    def main_parameters(self, main, sha, owner="fixture-owner"):
        lock = Path(run("git", "-C", str(main), "rev-parse", "--path-format=absolute",
                        "--git-common-dir")) / "deploy.lock"
        lock.mkdir()
        (lock / "owner").write_text(owner + "\n")
        return {"main": str(main), "base": "main", "repository": "owner/repo",
                "fetched_sha": sha, "lock_path": str(lock), "lock_owner": owner}

    def test_fast_forward_preserves_ignored_content_and_exact_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, seed, main = self.repository(Path(tmp))
            (main / ".git/info/exclude").write_text("ignored-cache/\n")
            ignored = main / "ignored-cache/probe.txt"
            ignored.parent.mkdir()
            ignored.write_text("preserve\n")
            sha = self.advance(seed, main)
            params = self.main_parameters(main, sha)
            result = maintain_release(manifest(), state(sha),
                                      request("fast-forward-main", params, commit=sha))
            receipt = result["action_receipt"]
            self.assertEqual(receipt["result"], "fast-forwarded")
            self.assertEqual(run("git", "-C", str(main), "rev-parse", "main"), sha)
            self.assertEqual(ignored.read_text(), "preserve\n")
            self.assertEqual(receipt["ignored_content"], "preserved-not-enumerated")
            self.assertFalse(result["system_wide_claim"])

    def test_dirty_diverged_wrong_lock_and_missing_mode_never_advance(self):
        for case in ("dirty", "diverged", "lock", "mode"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                _, seed, main = self.repository(Path(tmp))
                sha = self.advance(seed, main)
                before = run("git", "-C", str(main), "rev-parse", "main")
                params = self.main_parameters(main, sha)
                if case == "dirty":
                    (main / "user-work.txt").write_text("keep\n")
                elif case == "diverged":
                    run("git", "-C", str(main), "config", "user.name", "Fixture")
                    run("git", "-C", str(main), "config", "user.email", "fixture@example.invalid")
                    (main / "local.txt").write_text("local\n")
                    run("git", "-C", str(main), "add", "local.txt")
                    run("git", "-C", str(main), "commit", "-qm", "local")
                    before = run("git", "-C", str(main), "rev-parse", "main")
                elif case == "lock":
                    (Path(params["lock_path"]) / "owner").write_text("someone-else\n")
                value = request("fast-forward-main", params, commit=sha,
                                observed=None if case == "mode" else "automatic")
                with self.assertRaises(ValueError):
                    maintain_release(manifest(), state(sha), value)
                self.assertEqual(run("git", "-C", str(main), "rev-parse", "main"), before)
                if case == "dirty":
                    self.assertEqual((main / "user-work.txt").read_text(), "keep\n")

    def test_fast_forward_never_overwrites_ignored_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, seed, main = self.repository(Path(tmp))
            (main / ".git/info/exclude").write_text("generated.txt\n")
            protected = main / "generated.txt"
            protected.write_text("user-owned\n")
            (seed / "generated.txt").write_text("release-owned\n")
            run("git", "-C", str(seed), "add", "generated.txt")
            run("git", "-C", str(seed), "commit", "-qm", "add generated path")
            run("git", "-C", str(seed), "push", "-q", "origin", "main")
            run("git", "-C", str(main), "fetch", "-q", "origin")
            sha = run("git", "-C", str(main), "rev-parse", "origin/main")
            before = run("git", "-C", str(main), "rev-parse", "main")
            params = self.main_parameters(main, sha)
            with self.assertRaisesRegex(ValueError, "preserve working content"):
                maintain_release(manifest(), state(sha),
                                 request("fast-forward-main", params, commit=sha))
            self.assertEqual(run("git", "-C", str(main), "rev-parse", "main"), before)
            self.assertEqual(protected.read_text(), "user-owned\n")

    def test_activation_requires_reconciled_action_pin_and_rollback_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / COMMIT[:7]
            release.mkdir()
            (release / ".release-pin.json").write_text(json.dumps({
                "source": "owner/repo", "commit": COMMIT, "tree": TREE}))
            installer = release / "install.sh"
            installer.write_text("#!/bin/sh\nexit 0\n")
            calls = []

            def runner(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0,
                                                   stdout="rollback receipt: /fixture/rollback\n",
                                                   stderr="")

            old = observation("verified", commit=OLD_COMMIT, tree=OLD_TREE,
                              dimension="installed")
            params = {"release_root": str(release), "target": "codex",
                      "safe_checkpoint_ref": "fixture:safe-window"}
            result = maintain_release(manifest(), state(installed=old),
                                      request("activate-local-release", params), runner=runner)
            receipt = result["action_receipt"]
            self.assertEqual(calls[0][0], [str(installer.resolve()), "--target=codex"])
            self.assertEqual(receipt["rollback_refs"], {"local-codex": "release:previous"})
            self.assertEqual(receipt["installer_rollback_receipt"], "/fixture/rollback")
            self.assertTrue(result["post_action_reconciliation_required"])
            self.assertFalse(receipt["settings_or_trust_changed"])

            (release / ".release-pin.json").write_text(json.dumps({
                "source": "owner/repo", "commit": "f" * 40, "tree": TREE}))
            with self.assertRaisesRegex(ValueError, "pin differs"):
                maintain_release(manifest(), state(installed=old),
                                 request("activate-local-release", params), runner=runner)
            self.assertEqual(len(calls), 1)

    def test_activation_rejects_unrecommended_or_loaded_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / COMMIT[:7]
            release.mkdir()
            (release / ".release-pin.json").write_text(json.dumps({
                "source": "owner/repo", "commit": COMMIT, "tree": TREE}))
            (release / "install.sh").write_text("#!/bin/sh\nexit 0\n")
            params = {"release_root": str(release), "target": "codex",
                      "safe_checkpoint_ref": "fixture:safe-window"}
            ready = state(installed=observation("verified", commit=COMMIT, tree=TREE,
                                                dimension="installed"))
            with self.assertRaisesRegex(ValueError, "not recommended"):
                maintain_release(manifest(), ready,
                                 request("activate-local-release", params))

            value = state(installed=observation("verified", commit=OLD_COMMIT,
                                                tree=OLD_TREE, dimension="installed"))
            value["targets"]["local-codex"]["loaded"] = observation(
                "verified", commit=OLD_COMMIT, tree=OLD_TREE)
            with self.assertRaisesRegex(ValueError, "runtime-loaded drift"):
                maintain_release(manifest(), value,
                                 request("activate-local-release", params))


if __name__ == "__main__":
    unittest.main()
