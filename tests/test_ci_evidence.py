"""Execution evidence must distinguish assertion failures from an incomplete run."""
import copy
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from agent_skills.ci_evidence import complete_tap, validate_comparison


def tap(failed=False, newline=True):
    lines = ['TAP version 13', '# Subtest: a', f'{"not ok" if failed else "ok"} 1 - a',
             '1..1', '# tests 1', f'# pass {0 if failed else 1}', f'# fail {1 if failed else 0}',
             '# cancelled 0', '# skipped 0', '# todo 0']
    return {'stdout': '\n'.join(lines) + ('\n' if newline else ''), 'exit_code': 1 if failed else 0, 'signal': None}


def identity():
    return {'repo':'fixture/repo','head':'a'*40,'tested_commit':'b'*40,'tested_tree':'c'*40,'base':'d'*40,
            'workflow':'server-tests@exact-sha','runner':'test-diff@exact-sha','command':'fixture test',
            'lockfiles':{'lock':'digest'},'dependency_setup':'candidate deps shared with base',
            'runtime':'node-24','os':'ubuntu','services':[]}


class CiEvidence(unittest.TestCase):
    def receipt(self, head=None, base=None):
        return {'identity':identity(),'candidate':head or tap(),'baseline':base or tap()}

    def test_complete_success_and_missing_final_newline(self):
        self.assertTrue(validate_comparison(self.receipt(tap(newline=False)),identity())['eligible'])

    def test_complete_baseline_assertions_preserved_and_new_failures_rejected(self):
        self.assertTrue(validate_comparison(self.receipt(tap(True),tap(True)),identity())['eligible'])
        result=validate_comparison(self.receipt(tap(True),tap()),identity())
        self.assertFalse(result['eligible']); self.assertEqual(result['new_failures'],['a'])

    def test_partial_tap_counts_cannot_replace_complete_process(self):
        for stdout in ('TAP version 13\nok 1 - a\n# tests 1\n',
                       tap()['stdout'].replace('1..1\n',''),
                       tap()['stdout'].replace('ok 1 - a\n',''),
                       tap()['stdout'] + '# tests 1\n',
                       tap()['stdout'] + 'Bail out! crashed\n'):
            with self.subTest(stdout=stdout), self.assertRaises(ValueError):
                complete_tap({'stdout':stdout,'exit_code':0,'signal':None})

    def test_zero_baseline_and_candidate_both_rejected(self):
        zero={'stdout':'TAP version 13\n1..0\n# tests 0\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n','exit_code':0,'signal':None}
        for receipt in (self.receipt(zero,tap()),self.receipt(tap(),zero)):
            with self.assertRaises(ValueError): validate_comparison(receipt,identity())

    def test_signal_infrastructure_exit_and_inconsistent_success_rejected(self):
        for changed in ({'signal':'SIGTERM'},{'exit_code':None},{'exit_code':2},{'exit_code':1}):
            with self.assertRaises(ValueError): complete_tap({**tap(),**changed})
        with self.assertRaises(ValueError): complete_tap({**tap(True),'exit_code':0})

    def test_cancelled_or_inconsistent_summary_rejected(self):
        for text in (tap()['stdout'].replace('# cancelled 0','# cancelled 1'),
                     tap()['stdout'].replace('# tests 1','# tests 2'),
                     tap(True)['stdout'].replace('# fail 1','# fail 0')):
            with self.assertRaises(ValueError): complete_tap({**tap(),'stdout':text})

    def test_ambiguous_names_and_hidden_suite_failure_cannot_be_reused(self):
        duplicate=tap(True)
        duplicate['stdout']=duplicate['stdout'].replace('1..1','ok 2 - a\n1..2').replace('# tests 1','# tests 2').replace('# pass 0','# pass 1')
        hidden=tap(True); hidden['stdout'] += "  failureType: 'subtestsFailed'\n"
        for process in (duplicate,hidden):
            with self.assertRaises(ValueError): complete_tap(process)

    def test_each_source_or_environment_change_invalidates_receipt(self):
        for field in identity():
            receipt=self.receipt(); receipt['identity'][field]='changed'
            with self.subTest(field=field), self.assertRaises(ValueError): validate_comparison(receipt,identity())
        with self.assertRaises(ValueError): validate_comparison(self.receipt(),{'head':'a'*40})

    def test_head_and_merge_candidate_are_distinct(self):
        expected=identity(); expected['tested_commit']=expected['head']
        with self.assertRaises(ValueError): validate_comparison(self.receipt(),expected)

    def test_legacy_comparison_summary_cannot_be_green_evidence(self):
        with self.assertRaises(ValueError):
            validate_comparison({'identity':identity(),'candidate':{'tests':13838,'failures':44},'baseline':{'tests':13815,'failures':44}},identity())

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable for actual nested TAP regression')
    def test_real_node_nested_regression_cannot_hide_behind_same_suite_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'nested.test.mjs'
            def capture(second_fails):
                p.write_text("import {describe,it} from 'node:test'; import assert from 'node:assert/strict';\n"
                             "describe('suite',()=>{it('old failure',()=>assert.fail('old'));"
                             f"it('second',()=>assert.equal({str(second_fails).lower()},false));" + "});\n")
                run=subprocess.run(['node','--test','--test-reporter=tap',str(p)],capture_output=True,text=True)
                self.assertEqual(run.returncode,1,run.stderr)
                return {'stdout':run.stdout,'exit_code':run.returncode,'signal':None}
            before,after=capture(False),capture(True)
            self.assertIn('not ok 1 - suite',before['stdout'])
            self.assertIn('not ok 1 - suite',after['stdout'])
            # Both unchanged nested failures and a new nested failure are held,
            # rather than incorrectly admitted by comparing just suite names.
            for head in (before,after):
                with self.assertRaisesRegex(ValueError,'nested failing TAP'):
                    validate_comparison(self.receipt(head,before),identity())

    def test_release_bound_cli_handles_missing_and_complete_receipts(self):
        helper=Path(__file__).resolve().parents[1]/'skills/workflow-contracts/scripts/ci-evidence'
        with tempfile.TemporaryDirectory() as tmp:
            receipt=Path(tmp)/'receipt.json'; expected=Path(tmp)/'expected.json'
            receipt.write_text(json.dumps(self.receipt())); expected.write_text(json.dumps(identity()))
            done=subprocess.run([str(helper),str(receipt),'--expected',str(expected)],capture_output=True,text=True)
            self.assertEqual(done.returncode,0,done.stderr); self.assertTrue(json.loads(done.stdout)['eligible'])
            receipt.write_text('{}')
            done=subprocess.run([str(helper),str(receipt),'--expected',str(expected)],capture_output=True,text=True)
            self.assertEqual(done.returncode,1); self.assertFalse(json.loads(done.stdout)['eligible'])


if __name__=='__main__': unittest.main()
