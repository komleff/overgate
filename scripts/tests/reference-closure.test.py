#!/usr/bin/env python3
import importlib.util
import json
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
        m=json.loads((ROOT/'.agents/distribution-manifest.json').read_text())
        for item in m['files']:
            p=self.root/item['target'];p.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/item['source'],p)

    def test_valid(self):self.assertEqual(checker.closure(self.root),[])
    def test_helper_absent(self):
        (self.root/'.claude/hooks/shell_grammar.py').unlink()
        self.assertTrue(any('shell_grammar.py' in x for x in checker.closure(self.root)))
    def test_helper_removed_from_manifest(self):
        p=self.root/'.agents/distribution-manifest.json';m=json.loads(p.read_text())
        m['files']=[x for x in m['files'] if not x['target'].endswith('shell_grammar.py')];p.write_text(json.dumps(m))
        self.assertTrue(any('CLOSURE-001' in x for x in checker.closure(self.root)))
    def test_non_executable_launcher(self):
        (self.root/'.claude/tools/run-python.sh').chmod(0o644)
        self.assertTrue(any('CLOSURE-003' in x for x in checker.closure(self.root)))
    def test_missing_runtime_adapter(self):
        p=self.root/'.codex/hooks.json';m=json.loads(p.read_text());m['hooks']['PreToolUse']=[];p.write_text(json.dumps(m))
        self.assertTrue(any('CLOSURE-004' in x for x in checker.closure(self.root)))

if __name__=='__main__':unittest.main()
