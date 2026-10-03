#!/usr/bin/env python3
"""AC-07: реальные isolated Git fixtures; source drift, conflict, rollback bytes."""
import importlib.util
from unittest import mock
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / 'scripts/install-overgate.py'
sys.path.insert(0,str(ROOT/'scripts/tests/lib'))
from claude_hooks import native_bash
BASH=native_bash()

def git(root, *args):
    return subprocess.check_output(['git','-C',str(root),*args], stderr=subprocess.DEVNULL).decode().strip()

def init(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root,'init','-q','-b','fixture')
    git(root,'config','user.email','fixture@example.invalid')
    git(root,'config','user.name','Fixture')

def snapshot(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*')
            if p.is_file() and '.git' not in p.parts and '.overgate-backups' not in p.parts}

class SnapshotTests(unittest.TestCase):
    def test_snapshot_manifest_keys_preserve_bytes_on_both_path_flavors(self):
        # Ключи snapshot сверяются с POSIX-путями manifest даже на Windows;
        # содержимое остаётся исходными байтами, включая CRLF и non-UTF-8.
        relative='.claude/rules/large-payloads.md'
        content=b'legacy policy\r\n\xff\n'
        with tempfile.TemporaryDirectory() as holder:
            root=Path(holder);path=root/relative
            path.parent.mkdir(parents=True);path.write_bytes(content)
            for flavor in (PurePosixPath, PureWindowsPath):
                with self.subTest(flavor=flavor.__name__):
                    node=mock.Mock(wraps=path);node.parts=path.parts
                    node.relative_to.return_value=flavor(relative)
                    tree=mock.Mock();tree.rglob.return_value=[node]
                    self.assertEqual(snapshot(tree),{relative:content})

class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory(); cls.source=Path(cls.shared.name)/'source';init(cls.source)
        manifest=json.loads((ROOT/'.agents/distribution-manifest.json').read_text(encoding='utf-8'))
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
        self.assertIn('Product authority: оператор',(self.target/'AGENTS.md').read_text(encoding='utf-8'))
        run=subprocess.run([sys.executable,str(self.target/'scripts/check-reference.py'),'--root',str(self.target)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        for command,expected in [('git status --short',0),('gh pr merge 1 --auto',2)]:
            guard=subprocess.run([BASH,'-c','sh .claude/tools/run-python.sh .claude/hooks/check-repository-mutation.py'],
                input=json.dumps({'tool_input':{'command':command}}),text=True,encoding='utf-8',errors='replace',capture_output=True,cwd=self.target)
            self.assertEqual(guard.returncode,expected,guard.stdout+guard.stderr)
        ignored=subprocess.run(['git','-C',str(self.target),'check-ignore','.codex/hooks.json'],capture_output=True)
        self.assertEqual(ignored.returncode,1,'tracked adapter must not be ignored')
        result=subprocess.run([BASH,'.agents/project/verify.sh'],cwd=self.target,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(json.loads((self.target/'.overgate/install-state.json').read_text(encoding='utf-8'))['source_sha'],self.sha)
        payload=json.dumps(snapshot(self.target).keys(),default=list)
        self.assertNotIn('almanac',payload);self.assertNotIn('.env',payload)

    def upgrade_fixture(self):
        manifest=json.loads((ROOT/'.agents/distribution-manifest.json').read_text(encoding='utf-8'))
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
            p=self.target/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data,newline='\n')
        settings=json.loads((self.target/'.claude/settings.json').read_text(encoding='utf-8'));settings['env']['PROJECT']='preserve'
        settings['hooks']['SessionStart']=[{'hooks':[{'type':'command','command':'echo project-session'}]}]
        (self.target/'.claude/settings.json').write_text(json.dumps(settings),encoding='utf-8')
        return overrides

    def test_v39_upgrade_and_rollback_preserve_original_bytes(self):
        overrides=self.upgrade_fixture();before=snapshot(self.target)
        self.make_plan();self.approve();self.apply()
        for path,data in overrides.items():self.assertEqual((self.target/path).read_text(encoding='utf-8'),data)
        rule='.claude/rules/large-payloads.md'
        self.assertNotEqual(hashlib.sha256(before[rule]).hexdigest(),hashlib.sha256((self.target/rule).read_bytes()).hexdigest())
        frozen=subprocess.check_output(['git','-C',str(self.source),'show',self.sha+':'+rule])
        self.assertEqual((self.target/rule).read_bytes(),frozen)
        settings=json.loads((self.target/'.claude/settings.json').read_text(encoding='utf-8'));self.assertEqual(settings['env']['PROJECT'],'preserve')
        self.assertIn('echo project-session',json.dumps(settings))
        state=json.loads((self.target/'.overgate/install-state.json').read_text(encoding='utf-8'))
        self.call('rollback','--target',self.target,'--backup',state['backup'])
        self.assertEqual(snapshot(self.target),before)

    def test_v39_upgrade_and_rollback_with_crlf_source_checkout(self):
        # Чистый checkout может иметь CRLF, хотя frozen Git blob хранит LF.
        # Эталон установки — committed bytes; shell LF policy остаётся явной.
        clone=self.root/'source-crlf'
        subprocess.check_call(['git','clone','-q','--no-checkout',str(self.source),str(clone)])
        git(clone,'config','core.autocrlf','true')
        (clone/'.git/info/attributes').write_bytes((ROOT/'.gitattributes').read_bytes())
        git(clone,'checkout','-q','--detach',self.sha)
        self.source=clone
        rule='.claude/rules/large-payloads.md'
        frozen=subprocess.check_output(['git','-C',str(self.source),'show',self.sha+':'+rule])
        self.assertNotIn(b'\r\n',frozen)
        self.assertIn(b'\r\n',(self.source/rule).read_bytes())
        self.assertEqual(git(self.source,'status','--porcelain'),'')
        self.test_v39_upgrade_and_rollback_preserve_original_bytes()

    def test_previous_rc_upgrade_custom_hooks_and_rollback(self):
        manifest=json.loads((ROOT/'.agents/distribution-manifest.json').read_text(encoding='utf-8'))
        settings={'env':{'PROJECT':'preserve'},'hooks':manifest['previous_rc_settings']['hooks']}
        custom={'matcher':'Bash','hooks':[{'type':'command','command':'echo project-custom'}]}
        settings['hooks']['PreToolUse'].append(custom)
        path=self.target/'.claude/settings.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(settings),encoding='utf-8')
        verifier=self.target/'.agents/project/verify.sh';verifier.parent.mkdir(parents=True);verifier.write_text('#!/bin/sh\nexit 0\n',newline='\n')
        before=snapshot(self.target);self.make_plan();plan=json.loads(self.plan.read_text(encoding='utf-8'))
        paths=[op['target'] for op in plan['operations']]
        settings_index=paths.index('.claude/settings.json')
        for helper in ('.claude/hooks/pre-bash.sh','.claude/tools/run-python.sh','.claude/tools/with-timeout.sh'):
            self.assertLess(paths.index(helper),settings_index)
        self.approve();self.apply()
        after=json.loads(path.read_text(encoding='utf-8'))
        self.assertIn(custom,after['hooks']['PreToolUse'])
        from claude_hooks import dispatcher_entry
        self.assertEqual(dispatcher_entry(self.target)['timeout'],600)
        managed=[h for e in after['hooks']['PreToolUse'] for h in e['hooks'] if 'pre-bash.sh' in h['command']]
        self.assertEqual(len(managed),1)
        for entry in manifest['previous_rc_settings']['hooks']['PreToolUse'][:-1]:
            self.assertNotIn(entry,after['hooks']['PreToolUse'])
        state=json.loads((self.target/'.overgate/install-state.json').read_text(encoding='utf-8'))
        entries=json.loads(Path(state['backup']).read_text(encoding='utf-8'))['entries']
        restored=[e['target'] for e in reversed(entries)]
        self.assertLess(restored.index('.claude/settings.json'),restored.index('.claude/hooks/pre-bash.sh'))
        self.call('rollback','--target',self.target,'--backup',state['backup'])
        self.assertEqual(snapshot(self.target),before)

    def test_custom_dispatcher_hook_conflict_before_writes(self):
        p=self.target/'.claude/settings.json';p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'hooks':{'PreToolUse':[{'matcher':'Bash','hooks':[{'type':'command','command':'bash .claude/hooks/pre-bash.sh --custom','timeout':600}]}]}}))
        before=snapshot(self.target);self.make_plan();self.approve();self.apply(ok=False)
        self.assertEqual(snapshot(self.target),before)
        self.assertFalse((self.target/'.overgate-backups').exists())

    def test_installed_real_gate_receives_remaining_budget(self):
        self.make_plan();self.approve();self.apply()
        import sys
        sys.path.insert(0,str(ROOT/'scripts/tests/lib'))
        from claude_hooks import entry_command
        import importlib.util
        spec=importlib.util.spec_from_file_location('dispatch_tests',ROOT/'scripts/tests/pre-bash-dispatch.test.py')
        dispatch=importlib.util.module_from_spec(spec);spec.loader.exec_module(dispatch)
        guard=self.target/'.claude/hooks/check-merge-ready.py'
        guard.write_text('import time\ntime.sleep(3)\n')
        verifier=self.target/'.agents/project/verify.sh'
        verifier.write_text('#!/bin/sh\nbash .claude/hooks/check-tests-before-commit.sh --print-timeout-seconds >&2\nexit 1\n',newline='\n')
        entry=entry_command(self.target)
        code,err=dispatch.run(entry,'git commit -m x',self.target,extra_env={'OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS':'100'})
        self.assertEqual(code,2,err)
        limits=[int(line) for line in err.splitlines() if line.isdigit()]
        self.assertEqual(len(limits),1,err);self.assertLessEqual(limits[0],96)
        dispatcher=self.target/'.claude/hooks/pre-bash.sh'
        dispatcher.write_text(dispatcher.read_text(encoding='utf-8').replace('export OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS=', 'export U2_COMMIT_GATE_TEST_MAX_SECONDS='),newline='\n')
        code,err=dispatch.run(entry,'git commit -m x',self.target,extra_env={'OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS':'100'})
        self.assertEqual(code,2,err)
        self.assertIn('100',err.splitlines(),'producer/consumer mismatch must leave real gate unsqueezed')

    def test_dispatcher_manifest_omission_before_write(self):
        src,sha=self.source_without_entry('.claude/hooks/pre-bash.sh');before=snapshot(self.target)
        run=self.call('plan','--source',src,'--source-sha',sha,'--target',self.target,
                      '--contract',self.contract,'--target-pr','https://github.com/example/project/pull/1','--output',self.plan,ok=False)
        self.assertIn('CLOSURE-001',run.stderr);self.assertEqual(snapshot(self.target),before)
        self.assertFalse(self.plan.exists());self.assertFalse((self.target/'.overgate-backups').exists())

    def test_interrupted_apply_restores_settings_before_dispatcher(self):
        self.make_plan();self.approve();before=snapshot(self.target)
        spec=importlib.util.spec_from_file_location('installer',INSTALLER)
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        write=installer.write_atomic;calls=[];removed=[];unlink=Path.unlink
        def recording_unlink(path,*args,**kwargs):
            if path.is_relative_to(self.target.resolve()):removed.append(path.relative_to(self.target.resolve()).as_posix())
            return unlink(path,*args,**kwargs)
        def interrupted(root,path,data,mode):
            calls.append(path)
            if path==installer.STATE:raise OSError('injected write failure')
            return write(root,path,data,mode)
        with mock.patch.object(installer,'write_atomic',interrupted), mock.patch.object(Path,'unlink',recording_unlink):
            with self.assertRaises(OSError):installer.apply(self.plan,self.approval)
        self.assertEqual(snapshot(self.target),before)
        self.assertIn('.claude/settings.json',calls)
        self.assertLess(removed.index('.claude/settings.json'),removed.index('.claude/hooks/pre-bash.sh'))

    def test_custom_managed_role_conflict_stops_before_backup(self):
        self.upgrade_fixture();(self.target/'.agents/PM_ROLE.md').write_text('custom project role')
        before=snapshot(self.target);self.make_plan();self.approve();result=self.apply(ok=False)
        self.assertIn('conflict',result.stderr);self.assertEqual(before,snapshot(self.target))
        self.assertFalse((self.target/'.overgate-backups').exists())

    def test_custom_publication_rule_conflict_preserves_target(self):
        self.upgrade_fixture()
        rule=self.target/'.claude/rules/large-payloads.md'
        rule.write_text(rule.read_text(encoding='utf-8')+'\nProject publication override\n')
        before=snapshot(self.target);self.make_plan();self.approve();result=self.apply(ok=False)
        self.assertIn('.claude/rules/large-payloads.md',result.stderr)
        self.assertEqual(snapshot(self.target),before)
        self.assertFalse((self.target/'.overgate-backups').exists())

    def test_target_drift_is_rejected(self):
        self.make_plan();self.approve();(self.target/'AGENTS.md').write_text('new owner')
        self.assertIn('drift',self.apply(ok=False).stderr)

    def test_approval_must_bind_exact_plan(self):
        self.make_plan();self.approve();self.plan.write_text(self.plan.read_text(encoding='utf-8')+' ')
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

    def source_without_entry(self,path):
        src=self.root/'broken';shutil.copytree(self.source,src)
        manifest=src/'.agents/distribution-manifest.json';data=json.loads(manifest.read_text(encoding='utf-8'))
        data['files']=[item for item in data['files'] if item['target']!=path]
        manifest.write_text(json.dumps(data));git(src,'add','-u');git(src,'commit','-qm','omitted required inventory entry')
        self.assertTrue((src/path).is_file(),'source file remains: only manifest inventory is broken')
        return src,git(src,'rev-parse','HEAD')

    def test_missing_dependency_inventory_refused_before_plan_or_write(self):
        src,sha=self.source_without_entry('.claude/hooks/shell_grammar.py');before=snapshot(self.target)
        run=self.call('plan','--source',src,'--source-sha',sha,'--target',self.target,
                      '--contract',self.contract,'--target-pr','https://github.com/example/project/pull/1','--output',self.plan,ok=False)
        self.assertIn('CLOSURE-001',run.stderr)
        self.assertEqual(snapshot(self.target),before)
        self.assertFalse(self.plan.exists())
        self.assertFalse((self.target/'.overgate-backups').exists())

    def test_approved_incomplete_inventory_refused_before_apply_write(self):
        self.make_plan();plan=json.loads(self.plan.read_text(encoding='utf-8'))
        missing='.claude/hooks/shell_grammar.py';src,sha=self.source_without_entry(missing)
        # Simulate a plan emitted by the old installer; approval does not replace payload validation.
        plan['source']=str(src.resolve());plan['source_sha']=sha
        plan['operations']=[op for op in plan['operations'] if op['target']!=missing]
        for op in plan['operations']:
            if op['target']=='.agents/distribution-manifest.json':
                op['after']['sha256']=hashlib.sha256((src/op['source']).read_bytes()).hexdigest()
        self.plan.write_text(json.dumps(plan));self.approve();before=snapshot(self.target)
        result=self.apply(ok=False);self.assertIn('CLOSURE-001',result.stderr)
        self.assertEqual(snapshot(self.target),before)
        self.assertFalse((self.target/'.overgate-backups').exists())

    def test_missing_checker_inventory_refused_before_write(self):
        src,sha=self.source_without_entry('scripts/check-reference.py');before=snapshot(self.target)
        run=self.call('plan','--source',src,'--source-sha',sha,'--target',self.target,
                      '--contract',self.contract,'--target-pr','https://github.com/example/project/pull/1','--output',self.plan,ok=False)
        self.assertIn('missing',run.stderr)
        self.assertEqual(snapshot(self.target),before)
        self.assertFalse((self.target/'.overgate-backups').exists())

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
        state=json.loads((self.target/'.overgate/install-state.json').read_text(encoding='utf-8'))
        (self.target/'.agents/PM_ROLE.md').write_text('subsequent work')
        self.assertIn('drift',self.call('rollback','--target',self.target,'--backup',state['backup'],ok=False).stderr)

    def test_backup_symlink_rejected_before_write(self):
        self.make_plan();self.approve()
        outside=self.root/'outside';outside.mkdir();(self.target/'.overgate-backups').symlink_to(outside)
        self.assertIn('symlink',self.apply(ok=False).stderr)
        self.assertEqual(list(outside.iterdir()),[])

    def test_custom_runtime_hook_conflict_preserves_target(self):
        self.upgrade_fixture()
        p=self.target/'.claude/settings.json';settings=json.loads(p.read_text(encoding='utf-8'))
        settings['hooks']['PreToolUse'].append({'matcher':'Bash','hooks':[{'type':'command','command':'custom check-merge-ready.py'}]})
        p.write_text(json.dumps(settings),encoding='utf-8');before=snapshot(self.target)
        self.make_plan();self.approve();self.assertIn('conflict',self.apply(ok=False).stderr)
        self.assertEqual(snapshot(self.target),before)

if __name__=='__main__':unittest.main()
