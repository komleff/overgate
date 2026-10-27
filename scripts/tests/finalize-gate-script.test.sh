#!/usr/bin/env bash
# Проверяется исполняемый артефакт: отсутствие скрипта и старый markdown дают RED.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
"$ROOT/.claude/tools/run-python.sh" - "$ROOT" <<'PY'
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])
gate = root / '.claude/skills/finalize-pr/finalize-gate.sh'
assert gate.is_file(), 'AC-01: finalize-gate.sh отсутствует'
skill = (gate.parent / 'SKILL.md').read_text(encoding='utf-8')
assert len(re.findall(r'^\s*```bash$', skill, re.M)) == 1, 'AC-01: исполняемые блоки вне --force'
assert skill.index('```bash') > skill.index('## Emergency override `--force`')
for command in ['bash .claude/skills/finalize-pr/finalize-gate.sh <PR_NUMBER> --check', 'bash .claude/skills/finalize-pr/finalize-gate.sh <PR_NUMBER> --publish <BODY_FILE>']:
    assert skill.count(command)==1, ('AC-01 invocation',command)
assert 'bash /absolute/trusted-worktree/.claude/skills/finalize-pr/finalize-gate.sh <PR_NUMBER> --check' in skill
assert 'Claude Code и Codex' in skill
print('PASS finalize-gate-script artifact')
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
sys.path.insert(0, str(root / 'scripts/tests/lib'))
from claude_hooks import native_bash
bash = native_bash()

def run(args, cwd, env=None, data=None):
    return subprocess.run(list(map(str,args)), cwd=cwd, env=env, input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)

def require(result, code, label, contains=b''):
    assert result.returncode == code and contains in result.stdout, (label, result.returncode, result.stdout.decode(errors='replace'))
    print('PASS', label)

# Побайтное соответствие всех перенесённых блоков frozen source (AC-03).
frozen=subprocess.check_output(['git','cat-file','blob','b7e7ed132df17643ebf5b2d52af0b284ba3ce93e'],cwd=root).decode('utf-8').splitlines(keepends=True)
def original_block(number):
    assert frozen[number-1]=='```bash\n'
    return ''.join(frozen[number:frozen.index('```\n',number)])
actual=gate.read_text(encoding='utf-8')
for number in [57,187,215,243,512,1946]:
    expected=original_block(number).replace('<PR_NUMBER>','${PR_NUMBER}')
    expected=expected.replace('PREFLIGHT_REPO_ROOT=$(git rev-parse --show-toplevel)','PREFLIGHT_REPO_ROOT="$GATE_TREE"').replace('BD_REPO_ROOT=$(git rev-parse --show-toplevel)','BD_REPO_ROOT="$GATE_TREE"')
    assert expected in actual, ('AC-03 transfer drift', number)
base=original_block(1900);base=base[base.index('BASE_SHA='):base.index('ENVELOPE_FINGERPRINT=')].replace('<PR_NUMBER>','${PR_NUMBER}')
assert base in actual, 'AC-03 BASE_SHA drift'
pub=original_block(2041);pub=pub[pub.index('PUBLISHER='):].replace('$REPO_ROOT/','$GATE_TREE/').replace('<PR_NUMBER>','${PR_NUMBER}').replace('<<< "$BODY"','< "$BODY_SNAPSHOT"')
a=pub.index('# Тело подаётся');b=pub.index('FINALIZE_PR_TOKEN',a)
pub=pub[:a]+'# Raw stdin сохраняет все байты проверенного snapshot, включая завершающие LF.\n'+pub[b:]
assert actual.endswith(pub), 'AC-03 publication drift'
assert len(re.findall(r'^\s*#.*проба-условия:', actual,re.M))==3
assert actual.count('FINALIZE_PR_TOKEN=1')==1 and 'export FINALIZE_PR_TOKEN' not in actual
print('PASS exact transferred blocks and specified glue')

with tempfile.TemporaryDirectory(prefix='og159-gate-') as holder:
    temp = Path(holder)
    work = temp / 'work'; work.mkdir()
    trusted = temp / 'trusted tree'; trusted.mkdir()
    for name in subprocess.check_output(['git','ls-files','.claude/hooks','.claude/tools','scripts/lib','scripts/bd-wt.sh','scripts/bd-read.sh'], cwd=root).decode().splitlines():
        dest = trusted / name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, dest)
    entry = trusted / gate.relative_to(root); entry.parent.mkdir(parents=True)
    shutil.copy2(gate, entry)
    for args in [('init','-q','-b','fixture'),('config','user.name','Fixture'),('config','user.email','fixture@example.invalid')]:
        require(run(['git',*args], work), 0, 'git '+args[0])
    (work/'data').write_text('fixture')
    require(run(['git','add','data'],work),0,'git add')
    require(run(['git','commit','-qm','fixture'],work),0,'git fixture commit')
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=work).decode().strip()
    driver = temp/'driver.py'
    driver.write_text(r'''import json, os, pathlib, stat, sys
args=sys.argv[1:]
p=pathlib.Path(os.environ['EVENTS'])
with p.open('a',encoding='utf-8') as f: f.write(json.dumps({'args':args,'token':os.environ.get('FINALIZE_PR_TOKEN')})+'\n')
scenario=os.environ.get('SCENARIO','ok')
if args[0]=='cp':
    if scenario=='copy-error': sys.exit(23)
    if scenario=='copy-timeout':
        import time; time.sleep(30); sys.exit(0)
    import shutil
    shutil.copyfile(args[1],args[2]); sys.exit(0)
if args[0]=='bd': sys.exit(0 if scenario=='defer' or (scenario=='worktree' and args[1]=='--db') else 1)
if args[:2]==['pr','comment']:
    pathlib.Path(os.environ['OUTPUT']).write_bytes(sys.stdin.buffer.read())
    sys.exit(23 if scenario=='publish-error' else 0)
if scenario=='gh-error': sys.exit(23)
head=os.environ['FIXTURE_HEAD']
if '--json' in args:
    field=args[args.index('--json')+1]
    if field=='headRefOid':
        n=sum(1 for line in p.read_text().splitlines() if 'headRefOid' in line)
        if scenario=='head-race' and n>1: head='e'*40
        if scenario=='local-mismatch': head='f'*40
        # Первая сеть наступает после capture; исходник меняется детерминированно.
        if scenario=='source-change': pathlib.Path(os.environ['BODY_SOURCE']).write_bytes(b'changed after capture')
        for snapshot in pathlib.Path.cwd().glob('.overgate-runtime/finalize.*/body'):
            if os.name!='nt':
                assert stat.S_IMODE(snapshot.stat().st_mode)==0o600
                assert stat.S_IMODE(snapshot.parent.stat().st_mode)==0o700
        print(head)
    elif field=='baseRefOid': print('b'*40)
    elif field=='comments':
        body='## CODE REVIEW\nCommit: '+head+'\n'
        if scenario=='no-review': body='unrelated'
        if scenario=='triage-bad': body+='| # | Severity | Finding | File | Status | Beads ID / Rationale |\n| --- | --- | --- | --- | --- | --- |\n| 1 | WARNING | issue | data:1 | | |\n'
        if scenario in ('defer','snapshot','worktree'): body+='| # | Severity | Finding | File | Status | Beads ID / Rationale |\n| --- | --- | --- | --- | --- | --- |\n| 1 | WARNING | issue | data:1 | defer to Beads | og-abcd |\n'
        print(json.dumps({'comments':[{'body':body,'createdAt':'2026-10-28T00:00:00Z'}]}))
    else: raise AssertionError(args)
else: raise AssertionError(args)
''', encoding='utf-8')
    binpath=temp/'bin';binpath.mkdir()
    launcher=(root/'.claude/tools/run-python.sh').as_posix()
    if os.name=='nt':
        (binpath/'gh.cmd').write_text('@"'+sys.executable+'" "'+str(driver)+'" %*\r\n',encoding='utf-8')
    for name in ['gh','bd','cp']:
        stub=binpath/name
        stub.write_text('#!/usr/bin/env bash\nexec "'+launcher+'" "'+driver.as_posix()+'" '+('' if name=='gh' else name+' ')+ '"$@"\n',encoding='utf-8');stub.chmod(0o755)
    for name,scenario in [('mktemp','mktemp-error'),('chmod','mode-error'),('rm','cleanup-error')]:
        tool=shutil.which(name); assert tool
        stub=binpath/name
        stub.write_text('#!/usr/bin/env bash\ncase "$*" in *".overgate-runtime/finalize."*)\nif [ "${SCENARIO-}" = "'+scenario+'" ]; then exit 23; fi\n;;\nesac\nexec "'+Path(tool).as_posix()+'" "$@"\n',encoding='utf-8');stub.chmod(0o755)
    events=temp/'events'; output=temp/'published'; body=work/'body.md'
    env=dict(os.environ,PATH=str(binpath)+os.pathsep+os.environ['PATH'],EVENTS=str(events),OUTPUT=str(output),FIXTURE_HEAD=head,BODY_SOURCE=str(body))
    env.pop('FINALIZE_PR_TOKEN',None)
    def invoke(args, scenario='ok', expected=0, contains=b'', no_network=False):
        events.write_bytes(b''); output.unlink(missing_ok=True)
        result=run([bash,entry,*args],work,dict(env,SCENARIO=scenario))
        require(result, expected, 'gate '+scenario+' '+' '.join(map(str,args[:2])),contains)
        records=[json.loads(line) for line in events.read_text().splitlines()]
        assert all(record['token'] is None for record in records), records
        if no_network: assert not any(record['args'][0]=='pr' for record in records), records
        if '--check' in args or expected: assert not output.exists() or scenario in ('publish-error','cleanup-error')
        leftovers=list((work/'.overgate-runtime').glob('finalize.*'))
        if scenario=='cleanup-error':
            assert len(leftovers)==1, 'rm refusal must be real, not a vacuous stub'
            assert output.exists(), 'cleanup failure follows a successful publisher'
            assert 'НЕ опубликован'.encode() not in result.stdout, 'cleanup must not misreport completed publication'
            for path in leftovers: shutil.rmtree(path)
        else:
            assert not leftovers, 'snapshot cleanup'
        return result
    argbin=temp/'arg-bin';argbin.mkdir()
    argtrace=temp/'arg-tools'
    for tool in ['git','dirname']:
        path=argbin/tool;path.write_text('#!/usr/bin/env bash\necho '+tool+' >> "'+argtrace.as_posix()+'"\nexit 77\n');path.chmod(0o755)
    for args in [[],['13'],['bad','--check'],['13','--check','--publish'],['13','--check','--check'],['13','--publish','--check'],['13','--publish','--publish'],['13','--unknown'],['13','--publish','--unknown'],['13','--publish']]:
        invoke(args, expected=2, contains=b'usage: bash finalize-gate.sh <PR_NUMBER>', no_network=True)
        assert not events.read_bytes(), 'usage invokes no external tools'
        require(run([bash,entry,*args],work,dict(env,PATH=str(argbin)+os.pathsep+env['PATH'])),2,'argument preflight before git/dirname')
        assert not argtrace.exists(), 'external tool called before usage'
    result=invoke(['13','--check'],contains=b'GATE_RESULT=PASS')
    for field,value in [('HEAD_COMMIT',head),('BASE_SHA','b'*40),('EVIDENCE_SHA',head),('UNRESOLVED','0')]:
        assert (field+'='+value).encode() in result.stdout, ('summary',field,result.stdout)
    if os.name!='nt':
        assert ('GATE_TREE='+trusted.resolve().as_posix()).encode() in result.stdout
    gitbin=temp/'git-failure';gitbin.mkdir()
    failing=gitbin/'git';failing.write_text('#!/usr/bin/env bash\nexit 23\n');failing.chmod(0o755)
    events.write_bytes(b'')
    require(run([bash,entry,'13','--check'],work,dict(env,PATH=str(gitbin)+os.pathsep+env['PATH'])),1,'WORK_TREE git tool failure', 'отказ git'.encode())
    assert not events.read_bytes(), 'WORK_TREE failure must precede network'
    for scenario,diagnosis in [('gh-error','gh завершился'),('local-mismatch','не совпадает'),('no-review','нет CODE REVIEW'),('triage-bad','СТОП')]:
        invoke(['13','--check'],scenario,1,diagnosis.encode())
    valid=('## ✅ Готов к merge\n\nCommit: '+head+'\nUnresolved findings: 0').encode()
    for content in [b'',b'invalid','## ✅ Готов к merge\nCommit: '.encode()+head.encode()]:
        body.write_bytes(content); invoke(['13','--publish',body],expected=1,no_network=True)
    invoke(['13','--publish',work],expected=1,no_network=True)
    if os.name!='nt':
        link=work/'link';link.symlink_to(body);invoke(['13','--publish',link],expected=1,no_network=True)
    for scenario in ['copy-error','copy-timeout','mktemp-error','mode-error']:
        body.write_bytes(valid);invoke(['13','--publish',body],scenario,1,no_network=True)
    body.write_bytes(valid.replace(head.encode(),b'f'*40));invoke(['13','--publish',body],expected=1,contains=b'Commit:')
    for invalid in [valid+b'\n\xff', valid+b'\n\x00']:
        body.write_bytes(invalid);invoke(['13','--publish',body],expected=1)
    for scenario in ['head-race','publish-error']:
        body.write_bytes(valid);invoke(['13','--publish',body],scenario,1)
    for suffix in [b'',b'\n',b'\n\n\n']:
        body.write_bytes(valid+suffix);invoke(['13','--publish',body]);assert output.read_bytes()==valid+suffix
    body.write_bytes(valid+b'\n\n');invoke(['13','--publish',body],'source-change');assert output.read_bytes()==valid+b'\n\n'
    body.write_bytes(valid);invoke(['13','--publish',body],'cleanup-error',1, 'rm завершился с кодом 23'.encode());assert output.read_bytes()==valid
    print('PASS QA-F1: cleanup failure is nonzero after publication; earlier copy/publisher error statuses survive successful cleanup')
    # Ловушки в WORK_TREE не исполняются даже при наличии одноимённых helpers.
    trap=temp/'trap'
    for rel in ['.claude/tools/with-timeout.sh','.claude/tools/run-python.sh','.claude/tools/publish-pr-comment.py','scripts/lib/bd-env.sh','scripts/bd-wt.sh','scripts/bd-read.sh','scripts/lib/bd-read-engine.mjs']:
        path=work/rel;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('echo trap >> "'+trap.as_posix()+'"\nexit 99\n');path.chmod(0o755)
    invoke(['13','--check'],'defer',contains=b'GATE_RESULT=PASS');assert not trap.exists()
    body.write_bytes(valid+b'\n');invoke(['13','--publish',body]);assert output.read_bytes()==valid+b'\n';assert not trap.exists()
    snapshot=work/'beads-fixture.jsonl';snapshot.write_text(json.dumps({'id':'og-abcd','title':'Fixture','status':'open','priority':2,'issue_type':'task'})+'\n',encoding='utf-8')
    env['BD_READ_FIXTURE']=str(snapshot)
    invoke(['13','--check'],'snapshot',contains=b'GATE_RESULT=PASS');assert not trap.exists()
    env.pop('BD_READ_FIXTURE')
    # Реальная bd-wt из trusted tree выбирает main DB по git linked checkout.
    (work/'.beads/embeddeddolt').mkdir(parents=True)
    (work/'.beads/metadata.json').write_text('{"dolt_mode":"embedded"}',encoding='utf-8')
    linked=temp/'linked'
    require(run(['git','worktree','add','--detach',linked,head],work),0,'linked worktree fixture')
    for relative in ['.claude/tools/with-timeout.sh','.claude/tools/run-python.sh','scripts/lib/bd-env.sh','scripts/bd-wt.sh','scripts/bd-read.sh','scripts/lib/bd-read-engine.mjs']:
        path=linked/relative;path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(work/relative,path)
    events.write_bytes(b'')
    require(run([bash,entry,'13','--check'],linked,dict(env,SCENARIO='worktree')),0,'GATE_TREE real bd-wt linked route',b'GATE_RESULT=PASS')
    records=[json.loads(line) for line in events.read_text().splitlines()]
    assert any('--db' in record['args'] for record in records), 'bd-wt must execute'
    assert not trap.exists(), 'WORK_TREE closure trap executed'
    assert not list((linked/'.overgate-runtime').glob('finalize.*'))
    missing=trusted/'.claude/tools/with-timeout.sh';saved=missing.read_bytes();missing.unlink()
    invoke(['13','--check'],expected=1,contains=b'with-timeout.sh',no_network=True);assert not trap.exists()
    missing.write_bytes(saved);missing.chmod(0o755)
    for relative in ['.claude/tools/run-python.sh','.claude/tools/publish-pr-comment.py']:
        path=trusted/relative;saved=path.read_bytes();mode=path.stat().st_mode
        path.unlink();body.write_bytes(valid)
        invoke(['13','--publish',body],expected=1)
        assert not trap.exists()
        path.write_bytes(saved);path.chmod(stat.S_IMODE(mode))
    extractor=root/'docs/plans/2026-10-24-og-159-bootstrap-extract.py'
    bootstrap=temp/'bootstrap.sh';again=temp/'again.sh'
    digest=hashlib.sha256(valid+b'\n\n').hexdigest()
    for destination in [bootstrap,again]:
        result=run([sys.executable,extractor,'13',digest,destination],root)
        require(result,0,'bootstrap deterministic extraction')
        assert result.stdout.decode().strip()==hashlib.sha256(destination.read_bytes()).hexdigest()
    assert bootstrap.read_bytes()==again.read_bytes()
    for invalid in ['ABC', 'A'*64, 'a'*63]:
        require(run([sys.executable,extractor,'13',invalid,again],root),2,'bootstrap rejects invalid digest')
    # Временный checkout имеет именно доверенные HEAD blobs; никаких remote-вызовов.
    bootwork=temp/'bootstrap-work'
    require(run(['git','clone','--shared','--no-checkout',root,bootwork],temp),0,'bootstrap local clone')
    require(run(['git','checkout','--detach','b830d5ed7ed31e597b45f7f3c18b8fb6baad6b29'],bootwork),0,'bootstrap trusted checkout')
    shadow=bootwork/'hashlib.py';shadow.write_text('raise RuntimeError("untrusted cwd module executed")\n',encoding='utf-8')
    bootbody=bootwork/'.overgate-runtime/body.md';bootbody.parent.mkdir();bootbody.write_bytes(valid+b'\nwrong digest')
    events.write_bytes(b'');bootenv=dict(env,OG159_BODY_FILE=str(bootbody))
    result=run([bash,bootstrap],bootwork,bootenv)
    require(result,1,'bootstrap digest mismatch', 'digest snapshot'.encode())
    assert not any(json.loads(line)['args'][0]=='pr' for line in events.read_text().splitlines())
    assert not list((bootwork/'.overgate-runtime').glob('finalize.*'))
    # Успех bootstrap публикует тот же byte buffer с проверенным digest.
    boothead=subprocess.check_output(['git','rev-parse','HEAD'],cwd=bootwork).decode().strip()
    bootvalid=valid.replace(head.encode(),boothead.encode())+b'\n\n'
    bootbody.write_bytes(bootvalid)
    result=run([sys.executable,extractor,'13',hashlib.sha256(bootvalid).hexdigest(),bootstrap],root)
    require(result,0,'bootstrap bound extraction')
    events.write_bytes(b'');output.unlink(missing_ok=True)
    require(run([bash,bootstrap],bootwork,dict(bootenv,FIXTURE_HEAD=boothead)),0,'bootstrap raw stdin publish')
    assert output.read_bytes()==bootvalid
    events.write_bytes(b'');output.unlink(missing_ok=True)
    result=run([bash,bootstrap],bootwork,dict(bootenv,FIXTURE_HEAD=boothead,SCENARIO='cleanup-error'))
    require(result,1,'bootstrap checked cleanup failure', 'rm завершился с кодом 23'.encode())
    assert output.read_bytes()==bootvalid, 'successful publication is not undone by cleanup error'
    assert 'НЕ опубликован'.encode() not in result.stdout
    leftovers=list((bootwork/'.overgate-runtime').glob('finalize.*'));assert len(leftovers)==1
    for path in leftovers: shutil.rmtree(path)
    events.write_bytes(b'');output.unlink(missing_ok=True)
    require(run([bash,bootstrap],bootwork,dict(bootenv,FIXTURE_HEAD=boothead,SCENARIO='publish-error')),1,'bootstrap preserves publisher error after successful cleanup')
    assert not list((bootwork/'.overgate-runtime').glob('finalize.*'))
    # Committed drift closure отклоняется раньше сети даже при прежнем body digest.
    changed=bootwork/'.claude/tools/with-timeout.sh';changed.write_bytes(changed.read_bytes()+b'\n# drift\n')
    require(run(['git','config','user.name','Fixture'],bootwork),0,'bootstrap git config')
    require(run(['git','config','user.email','fixture@example.invalid'],bootwork),0,'bootstrap git config')
    require(run(['git','add','.claude/tools/with-timeout.sh'],bootwork),0,'bootstrap git add closure')
    require(run(['git','commit','-qm','closure drift'],bootwork),0,'bootstrap closure fixture commit')
    events.write_bytes(b'');require(run([bash,bootstrap],bootwork,bootenv),1,'bootstrap closure mismatch',b'trusted closure mismatch')
    assert not events.read_bytes(), 'closure must fail before any tool in stub PATH'
    # Реальные adapter routes проверяют формы команд; payload не исполняет gate.
    codex_hook=json.loads((root/'.codex/hooks.json').read_text())['hooks']['PreToolUse'][0]['hooks'][0]
    if os.name=='nt':
        prefix='powershell -NoProfile -Command "'
        command=codex_hook['commandWindows'];assert command.startswith(prefix) and command.endswith('"')
        codex_route=['powershell','-NoProfile','-Command',command[len(prefix):-1]]
    else:
        codex_route=[bash,'-c',codex_hook['command']]
    for command in ['bash .claude/skills/finalize-pr/finalize-gate.sh 13 --check','bash .claude/skills/finalize-pr/finalize-gate.sh 13 --publish body.md','bash "'+entry.as_posix()+'" 13 --check','bash "'+entry.as_posix()+'" 13 --publish body.md']:
        payload=json.dumps({'tool_name':'Bash','tool_input':{'command':command},'cwd':str(root)}).encode()
        hookenv=dict(os.environ,CLAUDE_PROJECT_DIR=str(root));hookenv.pop('FINALIZE_PR_TOKEN',None)
        require(run([bash,root/'.claude/hooks/pre-bash.sh'],root,hookenv,payload),0,'Claude route '+command)
        require(run(codex_route,root,hookenv,payload),0,'Codex route '+command)
print('PASS finalize-gate-script e2e, byte equality, closure and adapters')
PY
