#!/usr/bin/env python3
"""AC-07: реальные isolated Git fixtures; source drift, conflict, rollback bytes."""
import importlib.util
import base64
import errno
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
# Точный commit тега v4.0.0-rc.1: эталон upgrade-фикстуры rc.1 → текущий source.
RC1_SHA = '633937250fa8f47b49f928c1d8781ab17fe8c8e3'
# Точный commit тега v4.0.0-rc.2: вторая база upgrade, для которой заявлено побайтное соответствие.
RC2_SHA = '073595ae6fb51c16fa49576acca40d94d068af83'
RC3_SHA = 'b830d5ed7ed31e597b45f7f3c18b8fb6baad6b29'
PR_URL = 'https://github.com/example/project/pull/1'
GITIGNORE_HEADER = b'# OverGate personal state (managed fragment)'
# NTFS не хранит POSIX execute bits (как в reference-closure): mode сверяется только вне Windows.
POSIX_MODES = os.name != 'nt'
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

def load_installer():
    spec=importlib.util.spec_from_file_location('installer_under_test',INSTALLER)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def crlf(data):
    return data.replace(b'\n',b'\r\n')

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

    def call(self,*args,ok=True,installer=INSTALLER):
        run=subprocess.run([sys.executable,str(installer),*map(str,args)],text=True,capture_output=True)
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

    def install_tag(self,sha,name):
        # Точная установка прежнего RC: отдельный clone источника на exact SHA тега, тот же
        # installer этого RC и тот же PLAN_READY binding, что у реального проекта.
        clone=self.root/name
        subprocess.check_call(['git','clone','-q','--shared','--no-checkout',str(ROOT),str(clone)],
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        git(clone,'checkout','-q','--detach',sha)
        installer=clone/'scripts/install-overgate.py'
        self.call('plan','--source',clone,'--source-sha',sha,'--target',self.target,'--contract',self.contract,
                  '--target-pr',PR_URL,'--output',self.plan,installer=installer)
        self.approve();self.call('apply','--plan',self.plan,'--approval',self.approval,installer=installer)
        state=json.loads((self.target/'.overgate/install-state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['source_sha'],sha)
        return clone

    def install_rc1(self):return self.install_tag(RC1_SHA,'source-rc1')

    def source_blob(self,path):
        return subprocess.check_output(['git','-C',str(self.source),'show',self.sha+':'+path])

    def source_manifest(self):return json.loads(self.source_blob('.agents/distribution-manifest.json'))

    def source_mode(self,path):
        return 0o755 if git(self.source,'ls-tree',self.sha,'--',path).split()[0]=='100755' else 0o644

    def assert_conformance(self,preserved=None):
        # AC-01/AC-02: managed и settings — байты и mode Git blob source; preserve — шаблон
        # при fresh либо прежние байты проекта при upgrade.
        for entry in self.source_manifest()['files']:
            policy=entry.get('policy','managed');p=self.target/entry['target']
            if policy in {'managed','settings'}:
                self.assertEqual(p.read_bytes(),self.source_blob(entry['source']),entry['target'])
                # NTFS не хранит POSIX execute bit: там сравниваются только байты.
                if POSIX_MODES:
                    self.assertEqual(p.stat().st_mode & 0o777,self.source_mode(entry['source']),entry['target'])
            elif policy=='preserve':
                expected=preserved[entry['target']] if preserved and entry['target'] in preserved else self.source_blob(entry['source'])
                self.assertEqual(p.read_bytes(),expected,entry['target'])

    def assert_replan_noop(self):
        # AC-04: повторный plan сразу после apply ничего не меняет; install-state.json не operation.
        self.make_plan();plan=json.loads(self.plan.read_text(encoding='utf-8'))
        self.assertEqual(plan['conflicts'],[])
        for op in plan['operations']:
            self.assertNotEqual(op['target'],'.overgate/install-state.json')
            if POSIX_MODES:self.assertEqual(op['before'],op['after'],op['target'])
            # NTFS отдаёт st_mode 0o666 для любого обычного файла, mode source там не представим:
            # сравнивается только sha256; на POSIX — sha256 и mode.
            else:self.assertEqual(op['before']['sha256'],op['after']['sha256'],op['target'])

    def rollback_to(self,before):
        state=json.loads((self.target/'.overgate/install-state.json').read_text(encoding='utf-8'))
        self.call('rollback','--target',self.target,'--backup',state['backup'])
        self.assertEqual(snapshot(self.target),before)

    def plan_inprocess(self):
        # Тот же make_plan рабочего installer; payload собирается один раз на source,
        # чтобы таблицы политик не повторяли preflight checker на каждую строку.
        installer=load_installer();key=(str(self.source),self.sha);cache=type(self).__dict__.get('_payloads')
        if cache is None:cache={};type(self)._payloads=cache
        if key not in cache:cache[key]=installer.load_manifest(self.source,self.sha)
        with mock.patch.object(installer,'load_manifest',return_value=cache[key]):
            return installer.make_plan(self.source,self.sha,self.target,self.contract,PR_URL)

    def planned(self,plan,path):
        ops=[op for op in plan['operations'] if op['target']==path]
        self.assertEqual(len(ops),1,plan['conflicts'])
        return base64.b64decode(ops[0]['data'])

    def test_fresh_install_is_byte_exact_and_idempotent(self):
        # AC-01 + AC-04 (fresh).
        self.make_plan();self.approve();self.apply()
        self.assert_conformance()
        self.assertEqual((self.target/'.gitignore').read_bytes(),self.source_blob('.agents/templates/gitignore.fragment'))
        self.assertNotIn('permissions',json.loads((self.target/'.codex/hooks.json').read_text(encoding='utf-8')))
        self.assert_replan_noop()

    def check_exact_rc_upgrade(self,sha,name):
        # AC-02 + AC-04 + AC-07: точная установка тега без overrides → upgrade → source rc.3.
        self.install_tag(sha,name);before=snapshot(self.target)
        self.make_plan();plan=json.loads(self.plan.read_text(encoding='utf-8'))
        self.assertEqual(plan['conflicts'],[])
        self.approve();self.apply()
        self.assert_conformance(preserved=before)
        ignore=(self.target/'.gitignore').read_bytes()
        self.assertEqual(ignore,before['.gitignore'])
        self.assertEqual(ignore.count(GITIGNORE_HEADER),1)
        self.assertIn(self.source_blob('.agents/templates/gitignore.fragment'),ignore)
        self.assert_replan_noop()
        self.rollback_to(before)

    def test_rc1_exact_install_upgrade_is_byte_exact(self):self.check_exact_rc_upgrade(RC1_SHA,'source-rc1')

    def test_rc2_exact_install_upgrade_is_byte_exact(self):self.check_exact_rc_upgrade(RC2_SHA,'source-rc2')

    def test_rc3_upgrade_adds_executable_gate_and_replaces_skill(self):
        self.check_exact_rc_upgrade(RC3_SHA, 'source-rc3')

    def test_fresh_installs_executable_finalize_gate(self):
        self.make_plan(); self.approve(); self.apply()
        path = self.target / '.claude/skills/finalize-pr/finalize-gate.sh'
        self.assertEqual(path.read_bytes(), self.source_blob('.claude/skills/finalize-pr/finalize-gate.sh'))
        if POSIX_MODES:
            self.assertEqual(path.stat().st_mode & 0o777, 0o755)
        skill = (path.parent / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('Общий маршрут Claude Code и Codex', skill)
        self.assertNotIn('HEAD_COMMIT=$(run_with_timeout', skill)
        run=subprocess.run([BASH,path.as_posix(),'13','--unknown'],cwd=self.target,capture_output=True,text=True)
        self.assertEqual(run.returncode,2,run.stdout+run.stderr)
        self.assertIn('usage: bash finalize-gate.sh <PR_NUMBER>',run.stderr)

    def test_gitignore_policy_table(self):
        # AC-05: каждая строка таблицы §4.1 VC, вход → ожидаемые байты, через make_plan.
        fragment=self.source_blob('.agents/templates/gitignore.fragment');fcr=crlf(fragment)
        cases=[
            ('missing',None,fragment),
            ('empty',b'',fragment),
            ('block-at-end',b'node_modules/\n\n'+fragment,None),
            ('block-not-at-end',b'dist/\n'+fragment+b'\nnode_modules/\n',None),
            ('crlf-block-in-crlf-file',b'dist/\r\n\r\n'+fcr+b'build/\r\n',None),
            ('crlf-block-in-lf-file',b'dist/\n'+fcr+b'build/\n',None),
            ('pyc-without-final-eol',b'dist/\n\n'+fragment[:-1],None),
            ('crlf-pyc-without-final-eol',b'dist/\r\n\r\n'+fcr[:-2],None),
            ('lf-no-fragment',b'node_modules/\n',b'node_modules/\n\n'+fragment),
            ('lf-no-final-eol',b'node_modules/',b'node_modules/\n\n'+fragment),
            ('crlf-no-fragment',b'a\r\nb\r\n',b'a\r\nb\r\n\r\n'+fcr),
            ('crlf-no-final-eol',b'a\r\nb',b'a\r\nb\r\n\r\n'+fcr),
            ('mixed-eol-no-fragment',b'a\r\nb\n',b'a\r\nb\n\n'+fragment),
            ('legacy-codex-line',b'a\r\n.codex/\r\nb\r\n',b'a\r\nb\r\n\r\n'+fcr),
            ('legacy-only',b'.codex/\n',fragment),
            ('legacy-with-fragment',b'x\n.codex/\n\n'+fragment,b'x\n\n'+fragment),
            ('legacy-after-fragment-crlf',b'x\r\n\r\n'+fcr+b'.codex/\r\ny\r\n',b'x\r\n\r\n'+fcr+b'y\r\n'),
        ]
        path=self.target/'.gitignore'
        for name,existing,expected in cases:
            with self.subTest(case=name):
                if existing is None:
                    if path.exists():path.unlink()
                else:path.write_bytes(existing)
                plan=self.plan_inprocess();self.assertEqual(plan['conflicts'],[])
                self.assertEqual(self.planned(plan,'.gitignore'),existing if expected is None else expected)

    def test_gitignore_duplicate_blocks_collapse_to_first(self):
        # A2 (PLAN_READY): два и более целых блока → остаётся первый, повторные удаляются,
        # прочие байты не меняются.
        fragment=self.source_blob('.agents/templates/gitignore.fragment');fcr=crlf(fragment)
        cases=[
            ('two-lf',fragment+b'\nmid\n\n'+fragment+b'tail\n',fragment+b'\nmid\n\n'+b'tail\n'),
            ('three-mixed-eol',b'a\r\n'+fcr+b'b\n'+fragment+b'c\n'+fragment[:-1],b'a\r\n'+fcr+b'b\nc\n'),
        ]
        for name,existing,expected in cases:
            with self.subTest(case=name):
                (self.target/'.gitignore').write_bytes(existing)
                plan=self.plan_inprocess();self.assertEqual(plan['conflicts'],[])
                self.assertEqual(self.planned(plan,'.gitignore'),expected)

    def test_gitignore_modified_fragment_conflicts_without_write(self):
        # AC-05 строка 3: заголовок есть, тело отличается → conflict, без записи и backup.
        fragment=self.source_blob('.agents/templates/gitignore.fragment')
        modified=[fragment.replace(b'*.pyc\n',b'*.pyo\n'),fragment.replace(b'__pycache__/\n',b''),
                  b'dist/\n'+fragment+b'\n'+fragment.replace(b'*.pyc\n',b'')]
        message='.gitignore: conflict: managed .gitignore fragment modified; resolve in target PR'
        for index,data in enumerate(modified):
            with self.subTest(case=index):
                (self.target/'.gitignore').write_bytes(data)
                plan=self.plan_inprocess()
                self.assertEqual(plan['conflicts'],[message])
                self.assertNotIn('.gitignore',[op['target'] for op in plan['operations']])
        before=snapshot(self.target);self.make_plan();self.approve();result=self.apply(ok=False)
        self.assertIn('managed .gitignore fragment modified',result.stderr)
        self.assertEqual(snapshot(self.target),before);self.assertFalse((self.target/'.overgate-backups').exists())

    def test_crlf_gitignore_apply_replan_and_rollback(self):
        # AC-04 (CRLF-сценарий) + AC-07: вставка в EOL файла, повторный plan — no-op, rollback побайтный.
        original=b'node_modules/\r\ndist/\r\n';(self.target/'.gitignore').write_bytes(original)
        before=snapshot(self.target);self.make_plan();self.approve();self.apply()
        fragment=self.source_blob('.agents/templates/gitignore.fragment')
        self.assertEqual((self.target/'.gitignore').read_bytes(),original+b'\r\n'+crlf(fragment))
        self.assert_replan_noop()
        self.rollback_to(before)

    def test_codex_and_claude_settings_merge_permissions_only_from_source(self):
        # AC-03 (C1): Codex adapter не получает permissions; Claude deny дополняется как в rc.2.
        source_settings=json.loads(self.source_blob('.claude/settings.json'))
        required=source_settings['permissions']['deny']
        codex={'env':{'PROJECT':'preserve'},'hooks':{'PreToolUse':[]},'project_key':[1,2]}
        claude={'permissions':{'deny':['Bash(project-deny *)',required[1]]},'env':{'PROJECT':'preserve'}}
        for path,data in (('.codex/hooks.json',codex),('.claude/settings.json',claude)):
            p=self.target/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data),encoding='utf-8')
        plan=self.plan_inprocess();self.assertEqual(plan['conflicts'],[])
        merged=json.loads(self.planned(plan,'.codex/hooks.json'))
        self.assertNotIn('permissions',merged)
        self.assertEqual(merged['env'],codex['env']);self.assertEqual(merged['project_key'],[1,2])
        merged=json.loads(self.planned(plan,'.claude/settings.json'))
        self.assertEqual(merged['permissions']['deny'],['Bash(project-deny *)',required[1]]+[x for x in required if x!=required[1]])
        self.assertNotIn('allow',merged['permissions'])

    def test_settings_write_rule_source_and_unchanged_target(self):
        # AC-06 (C3, R1): (1) равно source → байты source; (2) merge ничего не добавил → байты
        # target; строгие типы: true и 1 различаются, поэтому проект с 1 не перезаписывается source.
        paths=('.claude/settings.json','.codex/hooks.json')
        sources={path:self.source_blob(path) for path in paths}
        for path in paths:(self.target/path).parent.mkdir(parents=True,exist_ok=True)
        def project(path):
            data=json.loads(sources[path]);data.setdefault('env',{})['PROJECT']='preserve'
            if 'permissions' in data:data['permissions']['allow'].append('Bash(make test)')
            return json.dumps(data).encode()
        def numeric(path):
            # Managed hooks заменяются по identity entry, поэтому тип проверяется на project-ключе.
            if path!='.claude/settings.json':return sources[path]
            data=json.loads(sources[path]);data['skipDangerousModePermissionPrompt']=1
            return (json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()
        cases=[
            ('sorted-rc2-output',lambda path:(json.dumps(json.loads(sources[path]),ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(),
             lambda path,data:sources[path]),
            ('crlf-source-bytes',lambda path:crlf(sources[path]),lambda path,data:sources[path]),
            ('project-allow-env-compact',project,lambda path,data:data),
            ('strict-types',numeric,lambda path,data:data),
        ]
        for name,build,expect in cases:
            with self.subTest(case=name):
                inputs={path:build(path) for path in paths}
                for path in paths:(self.target/path).write_bytes(inputs[path])
                plan=self.plan_inprocess();self.assertEqual(plan['conflicts'],[])
                for path in paths:self.assertEqual(self.planned(plan,path),expect(path,inputs[path]),path)

    def test_settings_write_rule_keeps_target_key_order(self):
        # AC-06 (3) + A1: merge добавил данные → порядок ключей target, новые ключи в конце,
        # indent=2, ensure_ascii=False, финальный LF; затем повторный plan — no-op, rollback побайтный.
        source_settings=json.loads(self.source_blob('.claude/settings.json'))
        custom={'matcher':'Bash','hooks':[{'type':'command','command':'echo проверка проекта'}]}
        target={'zeta':'проект','hooks':{'SessionStart':[],'PreToolUse':[custom]},'env':{'B':'1','A':'2'}}
        p=self.target/'.claude/settings.json';p.parent.mkdir(parents=True)
        p.write_bytes(json.dumps(target,ensure_ascii=True).encode())
        before=snapshot(self.target);self.make_plan();self.approve();self.apply()
        expected={'zeta':'проект','hooks':{'SessionStart':[],'PreToolUse':[custom]+source_settings['hooks']['PreToolUse']},
                  'env':{'B':'1','A':'2'},'permissions':{'deny':source_settings['permissions']['deny']}}
        data=p.read_bytes()
        self.assertEqual(data,(json.dumps(expected,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        self.assertIn('echo проверка проекта'.encode('utf-8'),data);self.assertNotIn(b'\\u',data)
        self.assertEqual(list(json.loads(data)),['zeta','hooks','env','permissions'])
        self.assert_replan_noop()
        self.rollback_to(before)

    def test_rc1_exact_install_upgrades_cleanly_and_rolls_back(self):
        rc1=self.install_rc1();before=snapshot(self.target)
        self.make_plan();plan=json.loads(self.plan.read_text(encoding='utf-8'))
        self.assertEqual(plan['conflicts'],[])
        targets=[op['target'] for op in plan['operations']]
        for path in ('scripts/bd-wt.sh','scripts/lib/bd-env.sh'):self.assertIn(path,targets)
        self.approve();self.apply()
        for path in ('scripts/bd-wt.sh','scripts/lib/bd-env.sh','.agents/distribution-manifest.json'):
            frozen=subprocess.check_output(['git','-C',str(self.source),'show',self.sha+':'+path])
            self.assertEqual((self.target/path).read_bytes(),frozen,path)
        # Preserve-файлы проекта upgrade не трогает: их правки переносятся вручную по diff.
        for path in ('.claude/rules/beads.md','AGENTS.md'):
            self.assertEqual((self.target/path).read_bytes(),before[path],path)
        state=json.loads((self.target/'.overgate/install-state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['source_sha'],self.sha)
        self.call('rollback','--target',self.target,'--backup',state['backup'])
        self.assertEqual(snapshot(self.target),before)
        rc1_wrapper=subprocess.check_output(['git','-C',str(rc1),'show',RC1_SHA+':scripts/bd-wt.sh'])
        self.assertEqual((self.target/'scripts/bd-wt.sh').read_bytes(),rc1_wrapper)

    def test_rc1_project_override_of_beads_wrapper_conflicts_per_file(self):
        self.install_rc1()
        overridden=('scripts/bd-wt.sh','scripts/lib/bd-env.sh')
        for path in overridden:
            p=self.target/path
            p.write_bytes(p.read_bytes()+b'# project override: embedded Dolt adaptation\n')
        backups=sorted((self.target/'.overgate-backups').iterdir())
        before=snapshot(self.target);self.make_plan();plan=json.loads(self.plan.read_text(encoding='utf-8'))
        for path in overridden:
            self.assertEqual([c for c in plan['conflicts'] if c.startswith(path+':')],
                             [path+': conflict with project override; no force overwrite'])
        self.assertEqual(len(plan['conflicts']),2,plan['conflicts'])
        self.approve();result=self.apply(ok=False)
        for path in overridden:self.assertIn(path+': conflict with project override',result.stderr)
        self.assertEqual(snapshot(self.target),before)
        self.assertEqual(sorted((self.target/'.overgate-backups').iterdir()),backups)

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
        dispatcher.write_text(dispatcher.read_text(encoding='utf-8').replace('export OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS=', 'export U2_COMMIT_GATE_TEST_MAX_SECONDS='),encoding='utf-8',newline='\n')
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
        rule.write_text(rule.read_text(encoding='utf-8')+'\nProject publication override\n',encoding='utf-8')
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
        outside=self.root/'outside';outside.mkdir()
        try:(self.target/'.overgate-backups').symlink_to(outside,target_is_directory=True)
        except OSError as error:
            if sys.platform=='win32' and getattr(error,'winerror',None)==1314:
                self.skipTest('Windows WinError1314: directory symlink creation privilege unavailable; security test NOT RUN')
            raise
        self.assertIn('symlink',self.apply(ok=False).stderr)
        self.assertEqual(list(outside.iterdir()),[])

    def test_unicode_fixtures_with_cp1251_default(self):
        # Реальные записи файлов под не-UTF-8 default, без PYTHONUTF8 override.
        original=Path.write_text
        def locale_write(path,data,encoding=None,errors=None,newline=None):
            return original(path,data,encoding=encoding or 'cp1251',errors=errors,newline=newline)
        for name in ('test_custom_publication_rule_conflict_preserves_target',
                     'test_installed_real_gate_receives_remaining_budget'):
            with self.subTest(name=name),mock.patch.object(Path,'write_text',locale_write):
                result=unittest.TestResult();InstallTests(name).run(result)
                self.assertEqual(result.errors,[])
                self.assertEqual(result.failures,[])
                self.assertEqual(result.skipped,[])

    def test_symlink_capability_handling_is_exact(self):
        for platform,winerror,skip in (('win32',1314,True),('win32',5,False),('darwin',1314,False)):
            error=OSError(errno.EACCES,'injected symlink capability error');error.winerror=winerror
            with self.subTest(platform=platform,winerror=winerror):
                with mock.patch.object(sys,'platform',platform),mock.patch.object(Path,'symlink_to',side_effect=error) as create:
                    result=unittest.TestResult();InstallTests('test_backup_symlink_rejected_before_write').run(result)
                self.assertTrue(create.call_args.kwargs.get('target_is_directory'))
                self.assertEqual(len(result.skipped),int(skip))
                self.assertEqual(len(result.errors),int(not skip))
                self.assertEqual(result.failures,[])
                if skip:self.assertIn('1314',result.skipped[0][1])

    def test_custom_runtime_hook_conflict_preserves_target(self):
        self.upgrade_fixture()
        p=self.target/'.claude/settings.json';settings=json.loads(p.read_text(encoding='utf-8'))
        settings['hooks']['PreToolUse'].append({'matcher':'Bash','hooks':[{'type':'command','command':'custom check-merge-ready.py'}]})
        p.write_text(json.dumps(settings),encoding='utf-8');before=snapshot(self.target)
        self.make_plan();self.approve();self.assertIn('conflict',self.apply(ok=False).stderr)
        self.assertEqual(snapshot(self.target),before)

    def test_previous_rc_codex_upgrade_custom_hook_and_rollback(self):
        # Exact прежний OverGate adapter; custom Bash hook не managed identity.
        old=json.loads(subprocess.check_output(['git','-C',str(ROOT),'show',
            '2998f6d001bf877ff118162bfb611da3459cd274:.codex/hooks.json']))
        custom={'matcher':'^Bash$','hooks':[{'type':'command','command':'echo codex-project'}]}
        old['hooks']['PreToolUse'].append(custom);old['env']={'PROJECT':'preserve'}
        path=self.target/'.codex/hooks.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(old),encoding='utf-8')
        before=snapshot(self.target);self.make_plan();self.approve();self.apply()
        after=json.loads(path.read_text(encoding='utf-8'))
        expected=json.loads((self.source/'.codex/hooks.json').read_text(encoding='utf-8'))['hooks']['PreToolUse']
        self.assertEqual(after['hooks']['PreToolUse'],[custom]+expected)
        self.assertEqual(len(expected),1);self.assertEqual(after['env'],{'PROJECT':'preserve'})
        # AC-03: в source Codex adapter нет permissions — merge их не создаёт.
        self.assertNotIn('permissions',after)
        state=json.loads((self.target/'.overgate/install-state.json').read_text(encoding='utf-8'))
        self.call('rollback','--target',self.target,'--backup',state['backup'])
        self.assertEqual(snapshot(self.target),before)

    def test_custom_codex_managed_variant_conflicts_before_write(self):
        old=json.loads(subprocess.check_output(['git','-C',str(ROOT),'show',
            '2998f6d001bf877ff118162bfb611da3459cd274:.codex/hooks.json']))
        old['hooks']['PreToolUse'][1]['hooks'][0]['timeout']=599
        path=self.target/'.codex/hooks.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(old),encoding='utf-8')
        before=snapshot(self.target);self.make_plan();self.approve();result=self.apply(ok=False)
        self.assertIn('custom managed runtime hook',result.stderr)
        self.assertEqual(snapshot(self.target),before);self.assertFalse((self.target/'.overgate-backups').exists())

if __name__=='__main__':unittest.main()
