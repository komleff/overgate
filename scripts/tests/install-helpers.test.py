#!/usr/bin/env python3
"""AC06–08: реальные Git checkout и записывающие вызовы заглушки CLI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent/'lib'))
from claude_hooks import native_bash
ROOT=Path(__file__).resolve().parents[2]
BASH=shutil.which(native_bash()) or native_bash()

STUB=r'''
import json,os,pathlib,sys
root=pathlib.Path(os.environ['OG_FIXTURE']); args=sys.argv[2:];kind=sys.argv[1]
with (root/'calls').open('a') as f:f.write(json.dumps([kind,*args])+'\n')
s=(root/'scenario').read_text(encoding='utf-8').strip()
if os.environ.get('OG_FAIL')==' '.join(args):sys.exit(9)
if kind=='bd':
 a=[x for x in args if x not in ('--sandbox','--json')]
 if a==['--version']: print('bd version '+os.environ.get('OG_VERSION','1.2.2')+' (fixture)');sys.exit()
 if a and a[0]=='init':
  (root/'.beads').mkdir(exist_ok=True);(root/'.beads/embeddeddolt').mkdir(exist_ok=True)
  (root/'.beads/metadata.json').write_text('{"dolt_mode":"embedded"}')
  (root/'bdconfig').write_text('{}');sys.exit()
 config=json.loads((root/'bdconfig').read_text(encoding='utf-8')) if (root/'bdconfig').exists() else {}
 if a[:2]==['config','set']:config[a[2]]=a[3];(root/'bdconfig').write_text(json.dumps(config))
 elif a[:2]==['config','unset']:config.pop(a[2],None);(root/'bdconfig').write_text(json.dumps(config))
 elif a[:2]==['config','get']: print(json.dumps({'key':a[2],'value':config.get(a[2],'')}))
 elif a[:3]==['dolt','remote','list']:print('[]')
 elif a[:1]==['ready']:
  counter=root/'ready-count';n=int(counter.read_text(encoding='utf-8')) if counter.exists() else 0;counter.write_text(str(n+1))
  if os.environ.get('OG_READY_FAIL_AFTER') and n>=int(os.environ['OG_READY_FAIL_AFTER']):sys.exit(9)
  print('[]')
 elif a[:1]==['export']:
  pathlib.Path(a[a.index('-o')+1]).write_text('')
 else:sys.exit(12)
 sys.exit()
if args[:2]==['auth','status']:sys.exit(1 if s=='auth' else 0)
if args[:2]==['repo','view']:print('example/project');sys.exit()
endpoint=args[args.index('api')+1]
if endpoint=='repos/example/project':print(json.dumps({'permissions':{'admin':s!='admin'},'default_branch':'main','private':True}));sys.exit()
if endpoint.endswith('/branches/main'):
 print(json.dumps({'protected':s=='ruleset' or (root/'protection').exists()}));sys.exit()
if '--method' in args and args[args.index('--method')+1]=='PUT':
 data=json.load(sys.stdin)
 if s in ('tariff','forbidden'):
  print(json.dumps({'message':'Upgrade to GitHub Pro or make this repository public to enable this feature.' if s=='tariff' else 'Resource not accessible by integration','status':'403'}));sys.exit(1)
 (root/'put').write_text(json.dumps(data))
 if s!='mismatch':
  out=dict(data)
  reviews=out.get('required_pull_request_reviews')
  if reviews is not None:
   for key in ('dismiss_stale_reviews','require_code_owner_reviews','require_last_push_approval'):reviews.setdefault(key,False)
   reviews.setdefault('required_approving_review_count',0)
   for key in ('dismissal_restrictions','bypass_pull_request_allowances'):reviews.setdefault(key,{'users':[],'teams':[],'apps':[]})
  if (root/'protection').exists():
   prior=json.loads((root/'protection').read_text(encoding='utf-8'))
   if 'required_signatures' in prior:out['required_signatures']=prior['required_signatures']
  for key in ('enforce_admins','allow_force_pushes','allow_deletions','required_linear_history','required_conversation_resolution','lock_branch','allow_fork_syncing','block_creations'):
   if key in out:out[key]={'enabled':out[key]}
  if s=='strict-loss':out['required_pull_request_reviews']['dismiss_stale_reviews']=False
  if s=='allowance-loss':out['required_pull_request_reviews']['bypass_pull_request_allowances']={'users':[],'teams':[],'apps':[]}
  if s=='status-loss':out['required_status_checks']=None
  if s=='restriction-loss':out['restrictions']=None
  if s=='signature-loss':out.pop('required_signatures',None)
  (root/'protection').write_text(json.dumps(out))
 print(json.dumps(data));sys.exit()
if not (root/'protection').exists():print('{"message":"Branch not protected","status":"404"}');sys.exit(1)
print((root/'protection').read_text(encoding='utf-8'))
'''

class Helpers(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'Мои проекты demo';self.root.mkdir()
        self.git('init','-q','-b','fixture');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        for name in ('scripts','bin'):(self.root/name).mkdir()
        shutil.copytree(ROOT/'.claude/tools',self.root/'.claude/tools')
        shutil.copytree(ROOT/'scripts/lib',self.root/'scripts/lib')
        shutil.copytree(ROOT/'.agents/templates',self.root/'.agents/templates')
        for name in ('og-init-memory-bank.sh','og-protect-main.sh','bd-bootstrap.sh','bd-sync-common.sh','bd-sync-export.sh'):
            if (ROOT/'scripts'/name).exists():shutil.copy2(ROOT/'scripts'/name,self.root/'scripts'/name)
        shutil.copy2(ROOT/'.agents/distribution-manifest.json',self.root/'.agents/distribution-manifest.json')
        (self.root/'scenario').write_text('fresh');(self.root/'stub.py').write_text(STUB)
        for kind in ('gh','bd'):
            p=self.root/'bin'/kind;p.write_text('#!/usr/bin/env bash\nexec "$OG_PYTHON" "$OG_FIXTURE/stub.py" '+kind+' "$@"\n');p.chmod(0o755)
            (self.root/'bin'/(kind+'.cmd')).write_text('@"'+sys.executable+'" "%OG_FIXTURE%/stub.py" '+kind+' %*\r\n')
        self.env=dict(os.environ,OG_FIXTURE=str(self.root),OG_PYTHON=sys.executable,PATH=str(self.root/'bin')+os.pathsep+os.environ['PATH'])
        self.env.pop('CLAUDE_PROJECT_DIR',None)
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.DEVNULL).decode().strip()
    def run_helper(self,name,code=0):
        r=subprocess.run([BASH,'scripts/'+name+'.sh'],cwd=self.root,env=self.env,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(r.returncode,code,r.stdout+r.stderr);return r.stdout+r.stderr
    def calls(self):return [json.loads(s) for s in (self.root/'calls').read_text(encoding='utf-8').splitlines()] if (self.root/'calls').exists() else []
    def memory(self):self.run_helper('og-init-memory-bank')
    def test_memory_fresh_and_partial_noop(self):
        self.memory();files=list((self.root/'.memory-bank').glob('*.md'));self.assertEqual(len(files),6)
        for p in files:self.assertEqual(p.read_bytes(),(self.root/'.agents/templates/memory-bank'/p.name).read_bytes())
        (self.root/'.memory-bank/progress.md').unlink();p=self.root/'.memory-bank/activeContext.md';p.write_text('own')
        self.assertIn('progress.md',self.run_helper('og-init-memory-bank'));self.assertEqual(p.read_text(encoding='utf-8'),'own');self.assertFalse((self.root/'.memory-bank/progress.md').exists())
    def test_protection_fresh_and_noop(self):
        self.memory();self.run_helper('og-protect-main');p=json.loads((self.root/'put').read_text(encoding='utf-8'))
        self.assertEqual(p['required_pull_request_reviews']['required_approving_review_count'],0)
        self.assertIs(p['enforce_admins'],True);self.assertIs(p['allow_deletions'],False);self.assertIs(p['allow_force_pushes'],False)
        (self.root/'put').unlink();self.run_helper('og-protect-main');self.assertFalse((self.root/'put').exists())
    def test_protection_stricter_rules_survive_update(self):
        original={'required_status_checks':{'url':'api','strict':True,'contexts':['CI'],'checks':[{'context':'CI','app_id':7}]},'required_pull_request_reviews':{'dismiss_stale_reviews':True,'require_code_owner_reviews':True,'required_approving_review_count':2,'require_last_push_approval':True,'dismissal_restrictions':{'users':[{'login':'owner'}],'teams':[{'slug':'reviewers'}],'apps':[{'slug':'review-app'}]}},'restrictions':{'users':[{'login':'owner'}],'teams':[{'slug':'devs'}],'apps':[]},'enforce_admins':{'enabled':False},'allow_force_pushes':{'enabled':False},'allow_deletions':{'enabled':False},'required_linear_history':{'enabled':True},'required_conversation_resolution':{'enabled':True},'lock_branch':{'enabled':True},'required_signatures':{'enabled':True}}
        (self.root/'protection').write_text(json.dumps(original));self.run_helper('og-protect-main');p=json.loads((self.root/'put').read_text(encoding='utf-8'))
        self.assertEqual(p['required_status_checks']['checks'],[{'context':'CI','app_id':7}]);self.assertEqual(p['restrictions']['teams'],['devs'])
        self.assertEqual(p['required_pull_request_reviews']['required_approving_review_count'],2)
        self.assertEqual(p['required_pull_request_reviews']['dismissal_restrictions']['users'],['owner'])
        self.assertIs(p['required_linear_history'],True);self.assertIs(p['lock_branch'],True)
    def test_protection_readback_rejects_loss_of_any_real_constraint(self):
        original={'required_status_checks':{'strict':True,'contexts':['CI'],'checks':[{'context':'CI','app_id':7}]},'required_pull_request_reviews':{'dismiss_stale_reviews':True,'require_code_owner_reviews':True,'require_last_push_approval':True,'required_approving_review_count':2,'bypass_pull_request_allowances':{'users':[{'login':'trusted'}],'teams':[],'apps':[]}},'restrictions':{'users':[{'login':'owner'}],'teams':[],'apps':[]},'enforce_admins':{'enabled':False},'allow_force_pushes':{'enabled':False},'allow_deletions':{'enabled':False},'required_signatures':{'enabled':True}}
        for scenario in ('strict-loss','allowance-loss','status-loss','restriction-loss','signature-loss'):
            with self.subTest(scenario=scenario):
                (self.root/'protection').write_text(json.dumps(original));(self.root/'scenario').write_text(scenario)
                output=self.run_helper('og-protect-main',6);self.assertIn('Операция могла примениться',output)
        (self.root/'protection').write_text(json.dumps(original));(self.root/'scenario').write_text('fresh');self.run_helper('og-protect-main')
        payload=json.loads((self.root/'put').read_text(encoding='utf-8'))
        self.assertEqual(payload['required_pull_request_reviews']['bypass_pull_request_allowances']['users'],['trusted'])

    def test_protection_r8_appends_without_rewriting_existing_context(self):
        self.memory();path=self.root/'.memory-bank/progress.md';before=b'project context  \n\n\n';path.write_bytes(before)
        (self.root/'scenario').write_text('auth');self.run_helper('og-protect-main',3)
        self.assertTrue(path.read_bytes().startswith(before))

    def test_protection_expected_codes_and_memory_r8(self):
        for scenario,code in (('admin',2),('auth',3),('tariff',4),('ruleset',5),('mismatch',6),('forbidden',6)):
            with self.subTest(scenario=scenario):
                for name in ('protection','put','calls'):(self.root/name).unlink(missing_ok=True)
                (self.root/'scenario').write_text(scenario);self.memory();output=self.run_helper('og-protect-main',code)
                self.assertIn('PR',output)
                if code in (2,3,4,5):self.assertIn('R8',(self.root/'.memory-bank/progress.md').read_text(encoding='utf-8'))
        shutil.rmtree(self.root/'.memory-bank');(self.root/'scenario').write_text('auth');self.run_helper('og-protect-main',3);self.assertFalse((self.root/'.memory-bank').exists())
    def remote(self):
        remote=Path(self.temp.name)/'remote.git';subprocess.check_call(['git','init','-q','--bare',str(remote)])
        self.git('remote','add','origin',str(remote));return remote
    def ready_database(self):
        (self.root/'.beads/embeddeddolt').mkdir(parents=True);(self.root/'.beads/metadata.json').write_text('{"dolt_mode":"embedded"}')
        (self.root/'bdconfig').write_text(json.dumps({'export.auto':'false','backup.git-push':'false'}))
    def test_beads_fresh_postconditions_remote_snapshot_and_noop(self):
        self.remote();self.run_helper('bd-bootstrap');calls=self.calls();self.assertIn(['bd','--sandbox','init','--skip-agents','--skip-hooks','--non-interactive','--remote','','--prefix','demo'],calls)
        self.assertTrue(self.git('ls-remote','--heads','origin','beads-backup'))
        ready=next(i for i,c in enumerate(calls) if 'ready' in c);export=next(i for i,c in enumerate(calls) if 'export' in c);self.assertLess(ready,export)
        (self.root/'calls').unlink();self.run_helper('bd-bootstrap');self.assertFalse(any('init' in c or 'export' in c or 'set' in c for c in self.calls()))
    def test_existing_live_server_is_preserved_and_dead_server_stops_before_bd(self):
        self.remote();self.ready_database();(self.root/'.beads/dolt').mkdir()
        meta=self.root/'.beads/metadata.json';meta.write_text('{"dolt_mode":"server"}')
        before=meta.read_bytes();self.env['BD_ENV_ASSUME_DOLT_ALIVE']='1'
        self.run_helper('bd-bootstrap');self.assertEqual(meta.read_bytes(),before)
        self.assertFalse(any('init' in c or 'set' in c for c in self.calls()))
        (self.root/'calls').unlink();self.env.pop('BD_ENV_ASSUME_DOLT_ALIVE')
        self.run_helper('bd-bootstrap',1);self.assertEqual(self.calls(),[])

    def test_beads_existing_database_missing_remote_retries_export(self):
        self.remote();self.ready_database();self.run_helper('bd-bootstrap');self.assertTrue(any('export' in c for c in self.calls()));self.assertFalse(any('init' in c for c in self.calls()))
    def test_beads_versions_fail_closed(self):
        self.remote()
        for version in ('1.2.1','1.2.3','2.0.0','bogus','1.2.2-beta'):
            with self.subTest(version=version):
                self.env['OG_VERSION']=version;self.assertIn('1.2.2',self.run_helper('bd-bootstrap',1));self.assertFalse((self.root/'.beads').exists())
        self.env.pop('OG_VERSION');self.run_helper('bd-bootstrap')
    def test_beads_failures_stop_before_export(self):
        self.remote()
        for args in ('--sandbox init --skip-agents --skip-hooks --non-interactive --remote  --prefix demo','--sandbox config set export.auto false','--sandbox config set backup.git-push false','--sandbox config unset sync.remote','--sandbox dolt remote list --json','--sandbox ready --json'):
            with self.subTest(args=args):
                shutil.rmtree(self.root/'.beads',ignore_errors=True);(self.root/'calls').unlink(missing_ok=True);(self.root/'bdconfig').unlink(missing_ok=True)
                self.env['OG_FAIL']=args;self.run_helper('bd-bootstrap',1);self.assertFalse(any('export' in c for c in self.calls()));self.assertEqual(self.git('ls-remote','--heads','origin','beads-backup'),'')
    def test_fresh_prefix_basename_is_portable_and_gate_compatible(self):
        # Исполняем pure функцию, извлечённую из production helper, без второй копии алгоритма.
        import ast,hashlib,re
        source=(ROOT/'scripts/bd-bootstrap.sh').read_text(encoding='utf-8')
        body=source.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
        tree=ast.parse(body);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='fresh_prefix')
        module=ast.Module(body=[node],type_ignores=[]);namespace={'re':re,'hashlib':hashlib};exec(compile(module,'production-fresh-prefix','exec'),namespace)
        expected={'simple':'simple','demo app':'demo-app','Мои проекты':'project-'+hashlib.sha256('Мои проекты'.encode()).hexdigest()[:8],'001_demo':'p-001-demo','___':'project-'+hashlib.sha256(b'___').hexdigest()[:8],'a':'p-a','x.y_z':'x-y-z'}
        for basename,prefix in expected.items():
            with self.subTest(basename=basename):
                self.assertEqual(namespace['fresh_prefix'](basename),prefix)
                self.assertRegex(prefix+'-abc123',r'^[A-Za-z][A-Za-z0-9-]+-[a-z0-9]+$')
                self.assertRegex(prefix,r'^[A-Za-z][A-Za-z0-9-]*$')

    def test_beads_missing_cli_gives_exact_version_install_hint(self):
        only=self.root/'missing-bin';only.mkdir()
        gitpath=shutil.which('git');p=only/'git';p.write_text('#!/bin/sh\nexec "'+gitpath+'" "$@"\n');p.chmod(0o755)
        self.env['PATH']=str(only)
        text=self.run_helper('bd-bootstrap',1);self.assertIn('1.2.2',text);self.assertIn('ОС',text);self.assertEqual(self.calls(),[])
    def test_beads_existing_unsafe_config_not_overwritten(self):
        self.remote();self.ready_database();p=self.root/'bdconfig';p.write_text('{"export.auto":"true","backup.git-push":"false"}')
        before=p.read_bytes();self.run_helper('bd-bootstrap',1);self.assertEqual(p.read_bytes(),before)
        self.assertFalse(any('init' in c or 'set' in c or 'export' in c for c in self.calls()))
    def test_beads_postexport_failure_reports_possible_complete_publication(self):
        self.remote();self.env['OG_READY_FAIL_AFTER']='1'
        output=self.run_helper('bd-bootstrap',1);self.assertIn('publication may already have occurred',output)
        self.assertTrue(self.git('ls-remote','--heads','origin','beads-backup'))
        self.assertTrue(any('export' in c for c in self.calls()))

    def test_beads_worktree_stops_before_any_bd_call(self):
        (self.root/'seed').write_text('x');self.git('add','seed');self.git('commit','-qm','seed')
        wt=Path(self.temp.name)/'linked';self.git('worktree','add','-q','-b','linked',str(wt))
        (wt/'scripts').mkdir();helper=ROOT/'scripts/bd-bootstrap.sh'
        self.assertTrue(helper.exists());shutil.copy2(helper,wt/'scripts/bd-bootstrap.sh');shutil.copytree(ROOT/'scripts/lib',wt/'scripts/lib')
        r=subprocess.run([BASH,'scripts/bd-bootstrap.sh'],cwd=wt,env=self.env,capture_output=True)
        self.assertNotEqual(r.returncode,0);self.assertEqual(self.calls(),[])

if __name__=='__main__':unittest.main()
