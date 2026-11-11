"""New Git snapshots and bytecode-free history CLI; never mutate live releases."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from agent_skills.release_package import package
from agent_skills.release_maintenance import _verify_release_root

ROOT=Path(__file__).resolve().parents[1]


class Packaging(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.source=self.root/'source';self.source.mkdir()
        self.git('init','-q');self.git('remote','add','origin','https://github.com/fixture/repo.git')
        for name,body in {'agent_skills/catalog.json':'{}\n','skills/workflow-contracts/contracts.md':'contract\n','global/CLAUDE.md':'agreement\n','install.sh':'#!/bin/sh\nexit 0\n'}.items():
            p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
        (self.source/'install.sh').chmod(0o755)
        self.commit()

    def git(self,*args):
        return subprocess.run(['git','-C',str(self.source),*args],check=True,capture_output=True,text=True).stdout.strip()

    def commit(self):
        self.git('add','.')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
        self.sha=self.git('rev-parse','HEAD')

    def test_exact_new_snapshot_and_existing_destination_refusal(self):
        dest=self.root/'snapshot';result=package(self.source,dest,self.sha,'fixture/repo')
        self.assertTrue(result['strict_tree_verified']);self.assertFalse(result['activated'])
        self.assertTrue((dest/'install.sh').stat().st_mode&0o111)
        _verify_release_root(dest,self.source,result['pin'])
        with self.assertRaisesRegex(ValueError,'new absolute'):package(self.source,dest,self.sha,'fixture/repo')
        self.assertEqual((dest/'global/CLAUDE.md').read_text(),'agreement\n')

    def test_dirty_wrong_source_and_symlink_archive_refuse(self):
        (self.source/'new.txt').write_text('unreviewed')
        with self.assertRaisesRegex(ValueError,'outside the source'):package(self.source,self.source/'package',self.sha,'fixture/repo')
        with self.assertRaisesRegex(ValueError,'dirty'):package(self.source,self.root/'dirty',self.sha,'fixture/repo')
        (self.source/'new.txt').unlink()
        with self.assertRaisesRegex(ValueError,'repository mismatch'):package(self.source,self.root/'wrong',self.sha,'other/repo')
        (self.source/'alias').symlink_to('/outside-fixture');self.commit()
        with self.assertRaisesRegex(ValueError,'regular files'):package(self.source,self.root/'symlink',self.sha,'fixture/repo')
        self.assertFalse((self.root/'symlink').exists())

    def test_history_wrapper_preserves_release_tree_while_plain_import_reproduces_cache(self):
        skill=self.source/'skills/task-history'
        shutil.copytree(ROOT/'skills/task-history',skill,ignore=shutil.ignore_patterns('__pycache__'))
        self.commit();dest=self.root/'snapshot';result=package(self.source,dest,self.sha,'fixture/repo')
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONDONTWRITEBYTECODE','PYTHONPYCACHEPREFIX')}
        config=self.root/'workers.json';config.write_text('{}');env['AGENT_SKILLS_CONFIG']=str(config)
        for mode,args in (('history',['configured']),('markdown',['--help']),('capture',['--help'])):
            run=subprocess.run([str(dest/'skills/task-history/scripts/history-cli'),mode,*args],env=env,capture_output=True,text=True)
            self.assertEqual(run.returncode,1 if args==['configured'] else 0,run.stderr)
        _verify_release_root(dest,self.source,result['pin'])
        # Reproduce the observed class of pollution only in this owned test copy.
        raw=subprocess.run(['python3','-c',f'import sys;sys.path.insert(0,{str(dest/"skills/task-history")!r});import checkpoint_capture'],env=env,capture_output=True,text=True)
        self.assertEqual(raw.returncode,0,raw.stderr)
        self.assertTrue((dest/'skills/task-history/__pycache__').exists())
        with self.assertRaisesRegex(ValueError,'contents differ'):_verify_release_root(dest,self.source,result['pin'])


if __name__=='__main__':unittest.main()
