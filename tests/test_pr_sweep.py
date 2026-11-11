"""Native publisher contract with fake gh: authenticated tuples, races and uncertain outcomes."""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / 'skills/test-review/scripts/pr_sweep.py'
HEAD, BASE, OLD = 'a' * 40, 'b' * 40, 'c' * 40
POLICY, ACTOR = 'review-v1', 123
FAKE_GH = r'''#!/usr/bin/env python3
import json,os,sys,time
from pathlib import Path
argv=sys.argv[1:]
p=Path(os.environ['FAKE_GH_DATA']); data=json.loads(p.read_text())
record={'argv':argv}
if argv[:2]==['pr','comment']:
    record['body']=Path(argv[argv.index('--body-file')+1]).read_text()
with open(os.environ['FAKE_GH_LOG'],'a') as out: out.write(json.dumps(record)+'\n')
if argv==['api','user']: result={'id':data.get('actor',123),'login':'reviewer'}
elif argv[0]=='api':
    url=argv[argv.index('GET')+1]
    if '/pulls?' in url:
        result=data['list'].get('/'.join(url.split('/')[1:3]),[[]])
    else:
        parts=url.split('/'); k=parts[1]+'/'+parts[2]+'#'+parts[4]
        result=data.get('comments',{}).get(k,[[]])
elif argv[:2]==['pr','view']:
    result=data['view'][argv[argv.index('-R')+1]+'#'+argv[2]]
elif argv[:2]==['pr','comment']:
    time.sleep(float(os.environ.get('FAKE_GH_DELAY_POST','0')))
    if os.environ.get('FAKE_GH_FAIL_POST'): sys.exit(77)
    k=argv[argv.index('-R')+1]+'#'+argv[2]
    data.setdefault('comments',{}).setdefault(k,[[]])[0].append({'user':{'id':data.get('actor',123)},'body':record['body']})
    if os.environ.get('FAKE_GH_MOVE_AFTER_POST'): data['view'][k]['baseRefOid']='c'*40
    p.write_text(json.dumps(data)); print('https://github.com/o/a/pull/7#issuecomment-1'); sys.exit(0)
else: sys.exit('unexpected fake gh call: '+repr(argv))
print(json.dumps(result))
'''


def binding(repo='o/a', n=7, head=HEAD, base=BASE, policy=POLICY):
    return {'repo': repo, 'pr': n, 'head': head, 'base': base, 'policy': policy, 'reviewer_id': ACTOR}


def comment(n=7, actor=ACTOR, **kwargs):
    return {'user': {'id': actor}, 'body': '<!-- agent-skills:verdict-v2 ' + json.dumps(binding(n=n, **kwargs), sort_keys=True, separators=(',', ':')) + ' -->'}


def legacy_comment(head=HEAD, actor=ACTOR, n=7):
    return {'user': {'id': actor}, 'id': 100 + n,
            'html_url': f'https://github.com/o/a/pull/{n}#issuecomment-{100+n}',
            'body': f'<!-- agent-skills:verdict sha={head} -->'}


def pr(n, time='2026-11-05T00:00:00Z', head=HEAD, base=BASE, draft=False):
    return {'number': n, 'updated_at': time, 'draft': draft, 'head': {'sha': head}, 'base': {'sha': base},
            'title': f'PR {n}', 'user': {'login': 'dev'}, 'html_url': f'https://github.com/o/a/pull/{n}'}


class PrSweepTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve(); (self.dir / 'bin').mkdir()
        executable = self.dir / 'bin/gh'; executable.write_text(FAKE_GH); executable.chmod(0o755)
        self.config, self.data, self.log = (self.dir / n for n in ('config.json','gh.json','gh.log'))
        self.body = self.dir / 'review.md'; self.body.write_text('Exact candidate reviewed; no blockers.\n')
        self.env = {**os.environ, 'PATH': f'{self.dir / "bin"}:{os.environ["PATH"]}',
                    'AGENT_SKILLS_CONFIG': str(self.config), 'FAKE_GH_DATA': str(self.data),
                    'FAKE_GH_LOG': str(self.log), 'PYTHONDONTWRITEBYTECODE': '1'}
        self.configure(); self.gh_data()

    def configure(self, **overrides):
        self.config.write_text(json.dumps({'pr_sweep': {
            'repos': [{'repo': 'o/a', 'checkout': '/src/a'}, {'repo': 'o/b', 'checkout': '/src/b'}],
            'authorization': 'fixture-only local fake gh', 'max_per_run': 3,
            'schema_version': 2, 'mode': 'publish', 'publication_authorization': 'fixture-only v2 publish',
            'reviewer_id': ACTOR, 'review_policy': POLICY, 'publisher_host': socket.gethostname(), **overrides}}))

    def gh_data(self, **overrides):
        self.data.write_text(json.dumps({'list': {'o/a': [[]], 'o/b': [[]]},
            'view': {'o/a#7': {'state': 'OPEN', 'isDraft': False, 'headRefOid': HEAD, 'baseRefOid': BASE}}, **overrides}))

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def command(self, *args):
        return [sys.executable, str(SWEEP), *args]

    def sweep(self, *args):
        return subprocess.run(self.command(*args), capture_output=True, text=True, env=self.env, timeout=10)

    def post_args(self, head=HEAD, base=BASE, policy=POLICY, repo='o/a'):
        return ['post','--repo',repo,'--pr','7','--sha',head,'--base',base,'--policy',policy,
                '--verdict','YES','--body-file',str(self.body)]

    def test_pending_skips_drafts_and_authenticated_exact_tuple_only(self):
        self.gh_data(list={'o/a': [[pr(1,draft=True),pr(2),pr(3),pr(4),pr(5),pr(6)]], 'o/b': [[]]},
            comments={'o/a#2': [[comment(n=2)]], 'o/a#3': [[comment(n=3,actor=999)]],
                      'o/a#4': [[comment(n=4,base=OLD)]], 'o/a#5': [[comment(n=5,policy='old')]]})
        done=self.sweep('pending'); self.assertEqual(done.returncode,0,done.stderr)
        rows=[json.loads(l) for l in done.stdout.splitlines()]
        self.assertEqual([r['number'] for r in rows],[3,4,5])
        self.assertEqual(rows[0]['base_sha'],BASE); self.assertEqual(rows[0]['policy'],POLICY)
        self.assertFalse([c for c in self.calls() if c['argv'][:2]==['pr','comment']])

    def test_pagination_and_oldest_first_cap_across_repositories(self):
        self.gh_data(list={'o/a': [[pr(1,'2026-11-05T00:00:00Z')], [pr(2,'2026-11-03T00:00:00Z')]],
                           'o/b': [[pr(3,'2026-11-04T00:00:00Z')]]})
        self.configure(max_per_run=2)
        done=self.sweep('pending'); self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual([(r['repo'],r['number']) for r in map(json.loads,done.stdout.splitlines())],[('o/a',2),('o/b',3)])
        api=[c['argv'] for c in self.calls() if '/pulls?' in ' '.join(c['argv'])]
        self.assertTrue(all('--paginate' in a and '--slurp' in a for a in api))

    def test_unconfigured_legacy_wrong_host_and_wrong_actor_fail_without_post(self):
        for overrides in ({'authorization':''},{'reviewer_id':None},{'review_policy':''}, {'publisher_host':'other-host'}):
            self.configure(**overrides)
            self.assertNotEqual(self.sweep(*self.post_args()).returncode,0)
        self.configure(); self.gh_data(actor=999)
        self.assertEqual(self.sweep(*self.post_args()).returncode,3)
        self.assertFalse([c for c in self.calls() if c['argv'][:2]==['pr','comment']])

    def test_post_authenticated_tuple_once_and_generic_attribution(self):
        self.gh_data(comments={'o/a#7': [[comment(actor=999)]]})
        done=self.sweep(*self.post_args()); self.assertEqual(done.returncode,0,done.stderr)
        self.assertTrue(json.loads(done.stdout)['current_after_post'])
        posts=[c for c in self.calls() if c['argv'][:2]==['pr','comment']]
        self.assertEqual(len(posts),1); self.assertIn(BASE,posts[0]['body'])
        self.assertNotIn('Claude worker',posts[0]['body'])
        self.assertIn('verdict-v2',posts[0]['body'])
        again=self.sweep(*self.post_args()); self.assertEqual(again.returncode,3)
        self.assertEqual(len([c for c in self.calls() if c['argv'][:2]==['pr','comment']]),1)

    def test_stale_head_base_policy_closed_draft_and_unknown_repository_refuse(self):
        for delta in ({'headRefOid':OLD},{'baseRefOid':OLD},{'state':'CLOSED'},{'isDraft':True}):
            current={'state':'OPEN','isDraft':False,'headRefOid':HEAD,'baseRefOid':BASE,**delta}
            self.gh_data(view={'o/a#7':current})
            self.assertEqual(self.sweep(*self.post_args()).returncode,3)
        self.gh_data()
        for args in (self.post_args(policy='old'),self.post_args(repo='o/unknown'),self.post_args(head='short')):
            self.assertEqual(self.sweep(*args).returncode,3)
        self.assertFalse([c for c in self.calls() if c['argv'][:2]==['pr','comment']])

    def test_concurrent_publishers_cannot_both_post(self):
        env={**self.env,'FAKE_GH_DELAY_POST':'0.6'}
        first=subprocess.Popen(self.command(*self.post_args()),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        try:
            deadline=time.monotonic()+5
            while not any(c['argv'][:2]==['pr','comment'] for c in self.calls()):
                if time.monotonic()>deadline: self.fail('first publisher never reached fake post')
                time.sleep(.01)
            second=self.sweep(*self.post_args())
            out,err=first.communicate(timeout=5)
            self.assertEqual(first.returncode,0,err); self.assertEqual(second.returncode,3,second.stderr)
            self.assertIn('owns this PR',second.stderr)
            self.assertEqual(len([c for c in self.calls() if c['argv'][:2]==['pr','comment']]),1)
        finally:
            if first.poll() is None: first.kill(); first.communicate()

    def test_uncertain_post_is_journaled_and_never_blindly_retried(self):
        self.env['FAKE_GH_FAIL_POST']='1'
        first=self.sweep(*self.post_args()); self.assertNotEqual(first.returncode,0)
        del self.env['FAKE_GH_FAIL_POST']
        second=self.sweep(*self.post_args()); self.assertEqual(second.returncode,3)
        self.assertIn('requires reconciliation',second.stderr)
        self.assertEqual(len([c for c in self.calls() if c['argv'][:2]==['pr','comment']]),1)
        self.gh_data(list={'o/a':[[pr(7)]],'o/b':[[]]})
        pending=self.sweep('pending'); self.assertEqual(pending.stdout,''); self.assertIn('uncertain',pending.stderr)

    def test_post_race_reports_staleness_without_reposting_or_claiming_current(self):
        self.env['FAKE_GH_MOVE_AFTER_POST']='1'
        done=self.sweep(*self.post_args()); self.assertEqual(done.returncode,0,done.stderr)
        self.assertFalse(json.loads(done.stdout)['current_after_post'])
        self.assertIn('became stale',done.stderr)
        self.assertEqual(len([c for c in self.calls() if c['argv'][:2]==['pr','comment']]),1)

    def test_bounded_body_and_no_unrelated_external_writes(self):
        for body in ('','x'*3001):
            self.body.write_text(body); self.assertEqual(self.sweep(*self.post_args()).returncode,3)
        self.body.write_text('local fixture review')
        self.assertEqual(self.sweep(*self.post_args()).returncode,0)
        for call in self.calls():
            a=call['argv']
            self.assertTrue(a[:2] in (['api','user'],['pr','view'],['pr','comment']) or a[:3]==['api','--method','GET'],a)

    def test_shadow_mode_never_posts_or_creates_attempt_journal(self):
        self.configure(mode='shadow', publication_authorization='')
        done=self.sweep(*self.post_args()); self.assertEqual(done.returncode,0,done.stderr)
        result=json.loads(done.stdout); self.assertFalse(result['posted']); self.assertEqual(result['mode'],'shadow')
        self.assertFalse([c for c in self.calls() if c['argv'][:2]==['pr','comment']])
        self.assertFalse((self.dir/'pr-sweep-state').exists())

    def test_legacy_approval_does_not_enable_v2_publication(self):
        self.configure(publication_authorization='')
        self.assertNotEqual(self.sweep(*self.post_args()).returncode,0)
        self.assertFalse(self.calls())

    def test_527_same_head_legacy_review_is_held_not_accepted_as_current_proof(self):
        head='6be010b544d6bdd16aa0dd9241f9c584b4c3ee3d'
        self.gh_data(list={'o/a':[[pr(527,head=head),pr(528)]],'o/b':[[]]},
                     comments={'o/a#527':[[legacy_comment(head=head,n=527)]]})
        done=self.sweep('pending');self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual([r['number'] for r in map(json.loads,done.stdout.splitlines())],[528])
        hold=json.loads(done.stderr);self.assertEqual(hold['number'],527)
        self.assertEqual(hold['held'],'legacy_same_head_review');self.assertFalse(hold['current_v2_proof'])
        self.assertIn('issuecomment-',hold['existing_review_refs'][0])

    def test_same_head_legacy_hold_blocks_publish_and_shadow_without_attempts(self):
        for mode in ('publish','shadow'):
            self.configure(mode=mode)
            self.gh_data(comments={'o/a#7':[[legacy_comment()]]})
            done=self.sweep(*self.post_args());self.assertEqual(done.returncode,3,done.stderr)
            self.assertIn('requires reconciliation',done.stderr)
        self.assertFalse([c for c in self.calls() if c['argv'][:2]==['pr','comment']])
        self.assertFalse(list((self.dir/'pr-sweep-state').glob('*.json')))

    def test_changed_base_or_policy_does_not_waive_same_head_legacy_hold(self):
        self.configure(review_policy='new-policy')
        self.gh_data(view={'o/a#7':{'state':'OPEN','isDraft':False,'headRefOid':HEAD,'baseRefOid':OLD}},
                     comments={'o/a#7':[[legacy_comment()]]})
        done=self.sweep(*self.post_args(base=OLD,policy='new-policy'))
        self.assertEqual(done.returncode,3);self.assertIn('legacy same-head',done.stderr)
        self.assertFalse([c for c in self.calls() if c['argv'][:2]==['pr','comment']])

    def test_changed_head_is_pending_and_old_legacy_does_not_block_new_review(self):
        self.gh_data(list={'o/a':[[pr(7)]],'o/b':[[]]},comments={'o/a#7':[[legacy_comment(head=OLD)]]})
        pending=self.sweep('pending');self.assertEqual(pending.returncode,0,pending.stderr)
        self.assertEqual(json.loads(pending.stdout)['head_sha'],HEAD)
        posted=self.sweep(*self.post_args());self.assertEqual(posted.returncode,0,posted.stderr)
        self.assertTrue(json.loads(posted.stdout)['posted'])
        self.assertEqual(len([c for c in self.calls() if c['argv'][:2]==['pr','comment']]),1)

    def test_forged_other_author_legacy_marker_neither_holds_nor_proves_review(self):
        self.gh_data(list={'o/a':[[pr(7)]],'o/b':[[]]},comments={'o/a#7':[[legacy_comment(actor=999)]]})
        pending=self.sweep('pending');self.assertEqual(pending.returncode,0,pending.stderr)
        self.assertEqual(json.loads(pending.stdout)['number'],7);self.assertEqual(pending.stderr,'')

    def test_stale_changed_head_post_still_refuses_before_legacy_reconciliation(self):
        self.gh_data(comments={'o/a#7':[[legacy_comment(head=OLD)]]})
        done=self.sweep(*self.post_args(head=OLD));self.assertEqual(done.returncode,3)
        self.assertIn('stale',done.stderr)
        self.assertFalse([c for c in self.calls() if c['argv'][:2]==['pr','comment']])


if __name__=='__main__': unittest.main()
