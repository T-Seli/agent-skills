"""pr_sweep.py with a fake gh: pending heads, the cap and order, refusals, one verdict comment, no writes but it."""
import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / "skills" / "test-review" / "scripts" / "pr_sweep.py"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
record = {"argv": argv}
if argv[:2] == ["pr", "comment"]:
    record["body"] = open(argv[argv.index("--body-file") + 1]).read()
with open(os.environ["FAKE_GH_LOG"], "a") as fh:
    fh.write(json.dumps(record) + "\n")
data = json.load(open(os.environ["FAKE_GH_DATA"]))
if argv[:2] == ["pr", "list"]:
    out = data["list"][argv[argv.index("-R") + 1]]
elif argv[:2] == ["pr", "view"]:
    out = data["view"]["%s#%s" % (argv[argv.index("-R") + 1], argv[2])]
elif argv[0] == "api":
    parts = argv[argv.index("GET") + 1].split("/")  # repos/<owner>/<name>/issues/<n>/comments
    out = data.get("comments", {}).get("%s/%s#%s" % (parts[1], parts[2], parts[4]), [[]])
elif argv[:2] == ["pr", "comment"]:
    print("https://github.com/example/pull/1#issuecomment-1")
    sys.exit(0)
else:
    sys.exit("fake gh: unexpected call %s" % argv)
print(json.dumps(out))
'''
HEAD, OLD = "a" * 40, "b" * 40


def marker(sha):
    return {"body": f"**Ready to merge: NO**\n<!-- agent-skills:verdict sha={sha} -->\n"}


def pr(number, updated, head=HEAD, draft=False):
    return {"number": number, "headRefOid": head, "isDraft": draft, "title": f"PR {number}",
            "author": {"login": "dev"}, "updatedAt": updated, "url": f"https://github.com/x/pull/{number}"}


class PrSweepTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        (self.dir / "bin").mkdir()
        (self.dir / "bin" / "gh").write_text(FAKE_GH)
        (self.dir / "bin" / "gh").chmod(0o755)
        self.config, self.data, self.log = (self.dir / n for n in ("workers.json", "gh.json", "gh.log"))
        self.env = {**os.environ, "PATH": f"{self.dir / 'bin'}:{os.environ['PATH']}", "HOME": str(self.dir),
                    "AGENT_SKILLS_CONFIG": str(self.config), "FAKE_GH_DATA": str(self.data),
                    "FAKE_GH_LOG": str(self.log), "PYTHONDONTWRITEBYTECODE": "1"}
        self.configure()
        self.body = self.dir / "review.md"
        self.body.write_text("Tests pass on the head; no blockers.\n")

    def configure(self, **overrides):
        sweep = {"repos": [{"repo": "o/a", "checkout": "~/Developer/a"}, {"repo": "o/b", "checkout": "/src/b"}],
                 "authorization": "PR sweep may post one verdict per head (2026-10-20)", **overrides}
        self.config.write_text(json.dumps({"max_depth": 2, "pr_sweep": sweep}))

    def gh_data(self, **data):
        self.data.write_text(json.dumps({"list": {"o/a": [], "o/b": []}, **data}))

    def sweep(self, *args):
        return subprocess.run([sys.executable, str(SWEEP), *args], capture_output=True, text=True, env=self.env)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def post(self, *extra, sha=HEAD, repo="o/a"):
        return self.sweep("post", "--repo", repo, "--pr", "7", "--sha", sha, "--verdict", "YES",
                          "--body-file", str(self.body), *extra)

    def test_pending_skips_drafts_and_reviewed_heads_but_not_older_verdicts(self):
        self.gh_data(list={"o/a": [pr(1, "2026-10-01T00:00:00Z", draft=True), pr(2, "2026-10-02T00:00:00Z"),
                                   pr(3, "2026-10-03T00:00:00Z"), pr(4, "2026-10-04T00:00:00Z")], "o/b": []},
                     comments={"o/a#2": [[{"body": "looks fine"}], [marker(HEAD)]], "o/a#3": [[marker(OLD)]]})
        done = self.sweep("pending")
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([r["number"] for r in rows], [3, 4])
        self.assertEqual(rows[0], {"repo": "o/a", "checkout": str(self.dir / "Developer" / "a"), "number": 3,
                                   "head_sha": HEAD, "title": "PR 3", "author": "dev",
                                   "url": "https://github.com/x/pull/3"})
        argvs = [c["argv"] for c in self.calls()]
        self.assertIn(["pr", "list", "-R", "o/a", "--state", "open", "--json",
                       "number,headRefOid,isDraft,title,author,updatedAt,url", "--limit", "100"], argvs)
        self.assertNotIn("repos/o/a/issues/1/comments", [a for argv in argvs for a in argv])
        self.assertFalse([a for a in argvs if a[:2] == ["pr", "comment"]])

    def test_pending_is_oldest_first_and_capped_across_repos(self):
        self.gh_data(list={"o/a": [pr(1, "2026-10-05T00:00:00Z"), pr(2, "2026-10-01T00:00:00Z")],
                           "o/b": [pr(3, "2026-10-03T00:00:00Z"), pr(4, "2026-10-02T00:00:00Z"),
                                   pr(5, "2026-10-04T00:00:00Z")]})
        order = [("o/a", 2), ("o/b", 4), ("o/b", 3)]
        for cap, expected in ((None, order), (2, order[:2])):
            with self.subTest(max_per_run=cap):
                self.configure(**({} if cap is None else {"max_per_run": cap}))
                done = self.sweep("pending")
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual([(r["repo"], r["number"]) for r in map(json.loads, done.stdout.splitlines())],
                                 expected)

    def test_pending_with_nothing_pending_exits_zero(self):
        self.gh_data()
        done = self.sweep("pending")
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def test_unconfigured_sweep_exits_1_before_any_gh_call(self):
        cases = {"no file": None, "no key": {}, "empty": {"pr_sweep": {}},
                 "no repos": {"pr_sweep": {"repos": [], "authorization": "yes"}},
                 "no authorization": {"pr_sweep": {"repos": [{"repo": "o/a", "checkout": "/a"}],
                                                   "authorization": ""}}}
        for name, cfg in cases.items():
            with self.subTest(name):
                self.config.unlink(missing_ok=True)
                if cfg is not None:
                    self.config.write_text(json.dumps(cfg))
                for args in (("pending",), ("post", "--repo", "o/a", "--pr", "7", "--sha", HEAD,
                                            "--verdict", "NO", "--body-file", str(self.body))):
                    done = self.sweep(*args)
                    self.assertEqual(done.returncode, 1)
                    self.assertIn("PR sweep not configured", done.stderr)
        self.assertEqual(self.calls(), [])

    def test_post_writes_one_verdict_comment_for_the_reviewed_head(self):
        self.gh_data(view={"o/a#7": {"state": "OPEN", "isDraft": False, "headRefOid": HEAD}},
                     comments={"o/a#7": [[marker(OLD)]]})
        done = self.post()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout),
                         {"repo": "o/a", "number": 7, "sha": HEAD, "verdict": "YES", "posted": True})
        comments = [c for c in self.calls() if c["argv"][:2] == ["pr", "comment"]]
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["argv"][:5], ["pr", "comment", "7", "-R", "o/a"])
        self.assertEqual(comments[0]["argv"][5], "--body-file")
        self.assertFalse(Path(comments[0]["argv"][6]).exists())
        self.assertEqual(comments[0]["body"].splitlines(), [
            "**Ready to merge: YES**", f"Reviewed head: `{HEAD[:12]}`", "",
            "Tests pass on the head; no blockers.", "",
            "_Automated review by Thomas's Claude worker. It never approves, merges or deploys._",
            f"<!-- agent-skills:verdict sha={HEAD} -->"])

    def test_post_refuses_without_posting(self):
        open_pr = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD}
        cases = {"moved head": ({"headRefOid": OLD}, [[]], {}, "stale"),
                 "existing marker": ({}, [[{"body": "hi"}], [marker(HEAD)]], {}, "already posted"),
                 "closed": ({"state": "CLOSED"}, [[]], {}, "CLOSED"),
                 "merged": ({"state": "MERGED"}, [[]], {}, "MERGED"),
                 "draft": ({"isDraft": True}, [[]], {}, "draft"),
                 "unknown repo": ({}, [[]], {"repo": "o/other"}, "not a configured"),
                 "oversize body": ({}, [[]], {"text": "x" * 3001}, "3001 characters"),
                 "empty body": ({}, [[]], {"text": " \n"}, "0 characters")}
        for name, (view, pages, extra, reason) in cases.items():
            with self.subTest(name):
                self.log.unlink(missing_ok=True)
                self.gh_data(view={"o/a#7": {**open_pr, **view}}, comments={"o/a#7": pages})
                self.body.write_text(extra.get("text", "No blockers.\n"))
                done = self.post(repo=extra.get("repo", "o/a"))
                self.assertEqual(done.returncode, 3, done.stderr)
                self.assertIn(reason, json.loads(done.stdout)["refused"])
                self.assertFalse([c for c in self.calls() if c["argv"][:2] == ["pr", "comment"]])

    def test_source_has_no_path_to_approve_merge_or_write_through_the_api(self):
        tree = ast.parse(SWEEP.read_text())
        runners = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and isinstance(n.func.value, ast.Name) and n.func.value.id in ("subprocess", "os")]
        self.assertEqual([ast.unparse(n.func) for n in runners], ["subprocess.run"])
        self.assertEqual(ast.unparse(runners[0].args[0]), "['gh', *args]")
        gh_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "gh"]
        self.assertEqual(len(gh_calls), 4)
        commands = set()
        for call in gh_calls:
            self.assertFalse([a for a in call.args if isinstance(a, ast.Starred)], ast.unparse(call))
            words = [a.value for a in call.args if isinstance(a, ast.Constant)]
            commands.add(tuple(words[:2]) if words[0] == "pr" else tuple(words[:3]))
            self.assertFalse({"review", "merge", "approve", "--approve", "-X", "-f", "-F", "--field",
                              "--raw-field", "--input"} & set(words), ast.unparse(call))
        self.assertEqual(commands, {("pr", "list"), ("pr", "view"), ("pr", "comment"), ("api", "--method", "GET")})


if __name__ == "__main__":
    unittest.main()
