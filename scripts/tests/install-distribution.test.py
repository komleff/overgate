#!/usr/bin/env python3
"""AC-07: реальные isolated Git fixtures; source drift, conflict, rollback bytes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / 'scripts/install-overgate.py'

def git(root, *args):
    return subprocess.check_output(['git','-C',str(root),*args], stderr=subprocess.DEVNULL).decode().strip()

def init(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root,'init','-q','-b','fixture')
    git(root,'config','user.email','fixture@example.invalid')
    git(root,'config','user.name','Fixture')

def snapshot(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*')
            if p.is_file() and '.git' not in p.parts and '.overgate-backups' not in p.parts}

class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory(); cls.source=Path(cls.shared.name)/'source';init(cls.source)
        manifest=json.loads((ROOT/'.agents/distribution-manifest.json').read_text())
        paths={x['source'] for x in manifest['files']} | {'.agents/distribution-manifest.json','scripts/install-overgate.py'}
        for name in paths:
            p=cls.source/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
        git(cls.source,'add','.');git(cls.source,'commit','-qm','source fixture')
        cls.sha=git(cls.source,'rev-parse','HEAD')

    @classmethod
    def tearDownClass(cls): cls.shared.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.target=self.root/'target';init(self.target)
        self.contract=self.root/'contract.md';self.contract.write_text('AC: preserve project bytes; closure; rollback\n')
        self.plan=self.root/'plan.json';self.approval=self.root/'approval.json'

    def call(self,*args,ok=True):
        run=subprocess.run([sys.executable,str(INSTALLER),*map(str,args)],text=True,capture_output=True)
        if ok:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        else:self.assertNotEqual(run.returncode,0,run.stdout+run.stderr)
        return run

    def make_plan(self):
        return self.call('plan','--source',self.source,'--source-sha',self.sha,'--target',self.target,
                         '--contract',self.contract,'--target-pr','https://github.com/example/project/pull/1','--output',self.plan)

    def approve(self):
        self.approval.write_text(json.dumps({'verdict':'PLAN_READY','plan_sha256':hashlib.sha256(self.plan.read_bytes()).hexdigest(),
                                            'evidence':'https://github.com/example/project/pull/1#issuecomment-1'}))

    def apply(self,ok=True):return self.call('apply','--plan',self.plan,'--approval',self.approval,ok=ok)

    def test_fresh_has_five_owners_and_runtime_closure(self):
        self.make_plan();self.approve();self.apply()
        self.assertEqual(len(list((self.target/'.agents/skills').glob('*/SKILL.md'))),5)
        self.assertIn('Product authority: оператор',(self.target/'AGENTS.md').read_text())
        run=subprocess.run([sys.executable,str(self.target/'scripts/check-reference.py'),'--root',str(self.target)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        for command,expected in [('git status --short',0),('gh pr merge 1 --auto',2)]:
            guard=subprocess.run([str(self.target/'.claude/tools/run-python.sh'),str(self.target/'.claude/hooks/check-repository-mutation.py')],
                input=json.dumps({'tool_input':{'command':command}}),text=True,capture_output=True,cwd=self.target)
            self.assertEqual(guard.returncode,expected,guard.stdout+guard.stderr)
        ignored=subprocess.run(['git','-C',str(self.target),'check-ignore','.codex/hooks.json'],capture_output=True)
        self.assertEqual(ignored.returncode,1,'tracked adapter must not be ignored')
        result=subprocess.run(['bash',str(self.target/'.agents/project/verify.sh')],capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(json.loads((self.target/'.overgate/install-state.json').read_text())['source_sha'],self.sha)
        payload=json.dumps(snapshot(self.target).keys(),default=list)
        self.assertNotIn('almanac',payload);self.assertNotIn('.env',payload)

    def upgrade_fixture(self):
        manifest=json.loads((ROOT/'.agents/distribution-manifest.json').read_text())
        # Настоящий frozen v3.9 payload, без project data/credentials.
        for item in manifest['files']:
            path=item['target']
            if path in manifest['legacy_blobs']:
                try:data=subprocess.check_output(['git','-C',str(ROOT),'show','466ad2020b8c46e6c14b4bbe67b5335017726542:'+path],stderr=subprocess.DEVNULL)
                except subprocess.CalledProcessError:continue
                p=self.target/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        overrides={'AGENTS.md':'Product authority: project-owner\ncustom route\n','.agents/project/verify.sh':'#!/bin/sh\nprintf project-tests\n',
                   '.memory-bank/activeContext.md':'preserve working context\n','.claude/settings.local.json':'{"env":{"PROJECT_OVERRIDE":"preserve"}}\n'}
        for path,data in overrides.items():
            p=self.target/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
        settings=json.loads((self.target/'.claude/settings.json').read_text());settings['env']['PROJECT']='preserve'
        settings['hooks']['SessionStart']=[{'hooks':[{'type':'command','command':'echo project-session'}]}]
        (self.target/'.claude/settings.json').write_text(json.dumps(settings))
        return overrides

    def test_v39_upgrade_and_rollback_preserve_original_bytes(self):
        overrides=self.upgrade_fixture();before=snapshot(self.target)
        self.make_plan();self.approve();self.apply()
        for path,data in overrides.items():self.assertEqual((self.target/path).read_text(),data)
        settings=json.loads((self.target/'.claude/settings.json').read_text());self.assertEqual(settings['env']['PROJECT'],'preserve')
        self.assertIn('echo project-session',json.dumps(settings))
        state=json.loads((self.target/'.overgate/install-state.json').read_text())
        self.call('rollback','--target',self.target,'--backup',state['backup'])
        self.assertEqual(snapshot(self.target),before)

    def test_custom_managed_role_conflict_stops_before_backup(self):
        self.upgrade_fixture();(self.target/'.agents/PM_ROLE.md').write_text('custom project role')
        before=snapshot(self.target);self.make_plan();self.approve();result=self.apply(ok=False)
        self.assertIn('conflict',result.stderr);self.assertEqual(before,snapshot(self.target))
        self.assertFalse((self.target/'.overgate-backups').exists())

    def test_target_drift_is_rejected(self):
        self.make_plan();self.approve();(self.target/'AGENTS.md').write_text('new owner')
        self.assertIn('drift',self.apply(ok=False).stderr)

    def test_approval_must_bind_exact_plan(self):
        self.make_plan();self.approve();self.plan.write_text(self.plan.read_text()+' ')
        self.assertIn('PLAN_READY',self.apply(ok=False).stderr)

    def test_contract_drift_rejected(self):
        self.make_plan();self.approve();self.contract.write_text('different AC')
        self.assertIn('contract',self.apply(ok=False).stderr)

    def test_missing_dependency_source_refused(self):
        src=self.root/'broken';shutil.copytree(self.source,src)
        (src/'.claude/hooks/shell_grammar.py').unlink();git(src,'add','-u');git(src,'commit','-qm','missing helper')
        run=self.call('plan','--source',src,'--source-sha',git(src,'rev-parse','HEAD'),'--target',self.target,
                      '--contract',self.contract,'--target-pr','https://github.com/example/project/pull/1','--output',self.plan,ok=False)
        self.assertIn('missing',run.stderr)

    def test_source_dirty_or_moved_rejected(self):
        src=self.root/'changed';shutil.copytree(self.source,src)
        (src/'.agents/PM_ROLE.md').write_text('dirty')
        run=self.call('plan','--source',src,'--source-sha',self.sha,'--target',self.target,'--contract',self.contract,
                      '--target-pr','https://github.com/example/project/pull/1','--output',self.plan,ok=False)
        self.assertIn('dirty',run.stderr)
        git(src,'add','-u');git(src,'commit','-qm','moved')
        run=self.call('plan','--source',src,'--source-sha',self.sha,'--target',self.target,'--contract',self.contract,
                      '--target-pr','https://github.com/example/project/pull/1','--output',self.plan,ok=False)
        self.assertIn('movement',run.stderr)

    def test_rollback_refuses_changed_managed_file(self):
        self.make_plan();self.approve();self.apply()
        state=json.loads((self.target/'.overgate/install-state.json').read_text())
        (self.target/'.agents/PM_ROLE.md').write_text('subsequent work')
        self.assertIn('drift',self.call('rollback','--target',self.target,'--backup',state['backup'],ok=False).stderr)

    def test_backup_symlink_rejected_before_write(self):
        self.make_plan();self.approve()
        outside=self.root/'outside';outside.mkdir();(self.target/'.overgate-backups').symlink_to(outside)
        self.assertIn('symlink',self.apply(ok=False).stderr)
        self.assertEqual(list(outside.iterdir()),[])

    def test_custom_runtime_hook_conflict_preserves_target(self):
        self.upgrade_fixture()
        p=self.target/'.claude/settings.json';settings=json.loads(p.read_text())
        settings['hooks']['PreToolUse'].append({'matcher':'Bash','hooks':[{'type':'command','command':'custom check-merge-ready.py'}]})
        p.write_text(json.dumps(settings));before=snapshot(self.target)
        self.make_plan();self.approve();self.assertIn('conflict',self.apply(ok=False).stderr)
        self.assertEqual(snapshot(self.target),before)

if __name__=='__main__':unittest.main()
