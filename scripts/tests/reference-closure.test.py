#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('checker',ROOT/'scripts/check-reference.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)

class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        m=json.loads((ROOT/'.agents/distribution-manifest.json').read_text(encoding='utf-8'))
        for item in m['files']:
            p=self.root/item['target'];p.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/item['source'],p)

    def edit_settings(self, mutate):
        p=self.root/'.claude/settings.json';data=json.loads(p.read_text(encoding='utf-8'));mutate(data);p.write_text(json.dumps(data),encoding='utf-8')
    def test_dispatcher_missing(self):
        p=self.root/'.claude/hooks/pre-bash.sh'
        if p.exists():p.unlink()
        self.assertTrue(any('pre-bash.sh' in x for x in checker.closure(self.root)))
    def test_dispatcher_removed_from_manifest(self):
        p=self.root/'.agents/distribution-manifest.json';data=json.loads(p.read_text(encoding='utf-8'))
        data['files']=[x for x in data['files'] if x['target']!='.claude/hooks/pre-bash.sh'];p.write_text(json.dumps(data),encoding='utf-8')
        self.assertTrue(any('CLOSURE-001' in x for x in checker.closure(self.root)))
    def test_duplicate_managed_entry(self):
        self.edit_settings(lambda d:d['hooks']['PreToolUse'].append(d['hooks']['PreToolUse'][0]))
        self.assertTrue(any('CLOSURE-004' in x for x in checker.closure(self.root)))
    def test_backslash_entry(self):
        self.edit_settings(lambda d:d['hooks']['PreToolUse'][0]['hooks'][0].update(command='bash \\ bad'))
        self.assertTrue(any('CLOSURE-004' in x for x in checker.closure(self.root)))
    def test_settings_before_dispatcher_is_refused(self):
        p=self.root/'.agents/distribution-manifest.json';data=json.loads(p.read_text(encoding='utf-8'))
        settings=next(x for x in data['files'] if x['target']=='.claude/settings.json')
        data['files'].remove(settings);data['files'].insert(0,settings);p.write_text(json.dumps(data),encoding='utf-8')
        self.assertTrue(any('CLOSURE-005' in x for x in checker.closure(self.root)))
    def test_mixed_legacy_and_dispatcher(self):
        old=json.loads((ROOT/'.agents/distribution-manifest.json').read_text(encoding='utf-8'))['previous_rc_settings']['hooks']['PreToolUse'][0]
        self.edit_settings(lambda d:d['hooks']['PreToolUse'].append(old))
        self.assertTrue(any('CLOSURE-004' in x for x in checker.closure(self.root)))
    def test_valid(self):self.assertEqual(checker.closure(self.root),[])
    def test_helper_absent(self):
        (self.root/'.claude/hooks/shell_grammar.py').unlink()
        self.assertTrue(any('shell_grammar.py' in x for x in checker.closure(self.root)))
    def test_helper_removed_from_manifest(self):
        p=self.root/'.agents/distribution-manifest.json';m=json.loads(p.read_text(encoding='utf-8'))
        m['files']=[x for x in m['files'] if not x['target'].endswith('shell_grammar.py')];p.write_text(json.dumps(m),encoding='utf-8')
        self.assertTrue(any('CLOSURE-001' in x for x in checker.closure(self.root)))
    @unittest.skipIf(os.name=='nt','NTFS uses explicit native Git Bash, not POSIX execute bits')
    def test_non_executable_launcher(self):
        (self.root/'.claude/tools/run-python.sh').chmod(0o644)
        self.assertTrue(any('CLOSURE-003' in x for x in checker.closure(self.root)))
    def test_invalid_helper_syntax_on_windows(self):
        if os.name!='nt':self.skipTest('native NTFS closure case')
        (self.root/'.claude/tools/run-python.sh').write_text('if then; broken')
        self.assertTrue(any('CLOSURE-003' in x for x in checker.closure(self.root)))
    def test_missing_runtime_adapter(self):
        p=self.root/'.codex/hooks.json';m=json.loads(p.read_text(encoding='utf-8'));m['hooks']['PreToolUse']=[];p.write_text(json.dumps(m),encoding='utf-8')
        self.assertTrue(any('CLOSURE-004' in x for x in checker.closure(self.root)))

if __name__=='__main__':unittest.main()
