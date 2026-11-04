#!/usr/bin/env python3
"""Trusted-main fresh activation; task data stays in an explicit private work directory."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

class ActivationError(Exception): pass

ZERO='0'*40
SCRIPT=Path(__file__).resolve()
ROOT=SCRIPT.parents[1]
spec=importlib.util.spec_from_file_location('overgate_installer',SCRIPT.with_name('install-overgate.py'))
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

def sha(data):return hashlib.sha256(data).hexdigest()

def call(args,cwd,label,env=None,timeout=60):
    result=subprocess.run([str(x) for x in args],cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise ActivationError(label+' failed (exit '+str(result.returncode)+')')
    return result.stdout.strip()

def git(root,*args):return call(['git','-C',root,*args],root,'Git '+str(args[0]))

def trusted(root):
    if not root.is_dir() or root.is_symlink() or root.resolve()!=root:raise ActivationError('trusted standalone checkout required')
    if Path(git(root,'rev-parse','--show-toplevel')).resolve()!=root:raise ActivationError('trusted root mismatch')
    common=Path(git(root,'rev-parse','--path-format=absolute','--git-common-dir')).resolve()
    directory=Path(git(root,'rev-parse','--path-format=absolute','--git-dir')).resolve()
    if common!=directory or (root/'.git').is_symlink() or not (root/'.git').is_dir():
        raise ActivationError('trusted standalone main checkout required')
    if git(root,'symbolic-ref','--quiet','--short','HEAD')!='main':raise ActivationError('trusted main branch required')
    head=git(root,'rev-parse','HEAD')
    remote=git(root,'ls-remote','--heads','origin','refs/heads/main').split()
    if remote!=[head,'refs/heads/main']:raise ActivationError('trusted exact origin/main required')
    if git(root,'status','--porcelain','--untracked-files=no'):
        raise ActivationError('trusted main tracked worktree/index must be clean')
    return head

def installed(root,head):
    state_path=root/'.overgate/install-state.json'
    if not state_path.is_file() or state_path.is_symlink():raise ActivationError('installed state missing')
    state_bytes=state_path.read_bytes()
    original=subprocess.run(['git','show',head+':.overgate/install-state.json'],cwd=root,capture_output=True)
    if original.returncode or state_bytes!=original.stdout:
        raise ActivationError('installed state differs from trusted main')
    state=json.loads(state_bytes)
    if state.get('beads_protocol')!='managed-v1' or state.get('beads') is not True:
        raise ActivationError('managed-v1 install state required')
    manifest_path=root/'.agents/distribution-manifest.json'
    manifest=json.loads(manifest_path.read_bytes())
    for entry in manifest['files']:
        if entry.get('component')!='beads' or entry.get('policy')!='managed':continue
        name=entry['target'];file=root/name
        if not file.is_file() or file.is_symlink():raise ActivationError('installed managed closure incomplete: '+name)
        data=file.read_bytes()
        if state.get('installed',{}).get(name,{}).get('sha256')!=sha(data):
            raise ActivationError('installed managed closure fingerprint differs: '+name)
        original=subprocess.run(['git','show',head+':'+name],cwd=root,capture_output=True)
        if original.returncode or original.stdout!=data:
            raise ActivationError('installed managed closure differs from trusted main: '+name)
    return state

def inventory(root):
    result=installer.beads_inventory(root)
    if result['remote']['status']!='verified-absent' or result['blocked']:
        raise ActivationError('Beads preservation required before activation: '+'; '.join(result['reasons']))
    return result

def native_env(root):
    env={key:value for key,value in os.environ.items() if not key.startswith(('BEADS_','DOLT_','BD_','GIT_CONFIG_'))
         and key not in ('GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_INDEX_FILE')}
    env.update({'GIT_CONFIG_GLOBAL':'NUL' if os.name=='nt' else '/dev/null','GIT_CONFIG_NOSYSTEM':'1',
                'GIT_TERMINAL_PROMPT':'0','BD_DISABLE_METRICS':'1','DOLT_METRICS_DISABLED':'1',
                'DOLT_ROOT_PATH':str(root/'.git/overgate-bd-activation/dolt-global')})
    return env

def native_init(root,binary,prefix,actor,work):
    if (root/'.beads').exists() or (root/'.beads').is_symlink():raise ActivationError('local Beads state appeared before native init')
    index=Path(git(root,'rev-parse','--path-format=absolute','--git-path','index'))
    if os.environ.get('GIT_INDEX_FILE') or (index.exists() and index.is_symlink()):
        raise ActivationError('canonical Git index override/unsafe index denied')
    before=(git(root,'rev-parse','HEAD'),index.read_bytes() if index.exists() else None)
    exclude=root/'.git/info/exclude';exclude_before=exclude.read_bytes() if exclude.exists() else None
    if subprocess.run(['git','-C',str(root),'diff','--cached','--quiet','--'],capture_output=True).returncode:
        raise ActivationError('staged Git index denied before native init')
    env=native_env(root)
    db=root/'.beads/dolt'
    call([binary,'--db',db,'--actor',actor,'init','--prefix',prefix,'--non-interactive',
          '--skip-agents','--skip-hooks','--stealth'],root,'native bd init',env,180)
    if (git(root,'rev-parse','HEAD'),index.read_bytes() if index.exists() else None)!=before:
        raise ActivationError('native bd init changed HEAD/index; stop and preserve local state')
    if git(root,'status','--porcelain','--untracked-files=no'):
        raise ActivationError('native bd init changed tracked files; stop and preserve local state')
    if installer.beads_inventory(root)['remote']['status']!='verified-absent':
        raise ActivationError('remote changed during native init; stop before publication')
    config=json.loads(call([binary,'--db',db,'--readonly','config','list','--json'],root,'native prefix read-back',env))
    if config.get('issue_prefix')!=prefix:raise ActivationError('native issue prefix differs from project-owned prefix')
    metadata=json.loads((root/'.beads/metadata.json').read_bytes())
    if metadata.get('backend')!='dolt' or metadata.get('dolt_mode')!='embedded' or not metadata.get('project_id'):
        raise ActivationError('native Beads metadata invalid')
    exported=work/(root.name+'-empty.jsonl')
    call([binary,'--db',db,'export','--all','-o',exported],root,'native empty export',env,180)
    if exported.read_bytes():raise ActivationError('native init contains issue state; stop before publication')
    return {'head':before[0],'index_sha256':sha(before[1] or b''),
            'git_exclude_before_sha256':sha(exclude_before) if exclude_before is not None else None,
            'git_exclude_after_sha256':sha(exclude.read_bytes()) if exclude.exists() else None,
            'metadata_sha256':sha((root/'.beads/metadata.json').read_bytes())}

def bash():
    if os.name!='nt':return 'bash'
    candidates=[Path('C:/Program Files/Git/bin/bash.exe')]
    candidates += [Path(p)/'bash.exe' for p in os.environ.get('PATH','').split(os.pathsep)]
    candidates += [Path('C:/Program Files/Git/usr/bin/bash.exe')]
    for candidate in candidates:
        if candidate.is_file() and 'system32' not in str(candidate).lower():return str(candidate)
    raise ActivationError('native Git Bash unavailable')

def main(args):
    if os.environ.get('GIT_INDEX_FILE'):raise ActivationError('GIT_INDEX_FILE override denied')
    if any(os.environ.get(name) for name in ('BEADS_DIR','BEADS_DB','BD_SYNC_FORCE','BD_SYNC_REMOTE','BD_SYNC_BRANCH',
                                           'BD_APPLY_SKIP_SYNC_CHECK','DOLT_ROOT_PATH')):
        raise ActivationError('Beads/Dolt writer environment override denied')
    primary=ROOT.resolve()
    publisher=Path(args.publisher_root).resolve();peer=Path(args.peer_root).resolve()
    if len({primary,publisher,peer})!=3:raise ActivationError('three distinct checkouts required')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*',args.prefix):raise ActivationError('project prefix invalid')
    if not re.fullmatch(r'agent-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',args.actor,re.I):
        raise ActivationError('actor must be a unique agent UUID')
    if not args.title.strip() or len(args.title)>8000:raise ActivationError('explicit project task title required')
    if SCRIPT!=primary/'scripts/bd-activate.py':raise ActivationError('trusted activation helper path required')
    head=trusted(primary);installed(primary,head);inventory(primary)
    work=Path(args.work_dir).resolve()
    if not Path(args.work_dir).is_absolute() or work.exists() or any(work==root or root in work.parents for root in (primary,publisher,peer)):
        raise ActivationError('private activation work directory must be new and outside checkouts')
    work.mkdir(parents=True,mode=0o700)
    raw=work/'raw-intents.jsonl'
    raw.write_text(''.join(json.dumps(item,separators=(',',':'))+'\n' for item in (
        {'intent_id':'activation-create','op':'create','handle':'tmp:first-task','title':args.title},
        {'intent_id':'activation-claim','op':'claim','ref':'tmp:first-task'})),encoding='utf-8')
    queue={'queue':str(raw),'queue_sha256':sha(raw.read_bytes()),'base':ZERO,'actor':args.actor}
    try:
        if not publisher.is_dir() or not peer.is_dir():raise ActivationError('publisher/peer checkout unavailable; queue retained')
        for root in (publisher,peer):
            if trusted(root)!=head:raise ActivationError('publisher/peer trusted main differs from primary')
            installed(root,head);inventory(root)
        origins=[(git(root,'remote','get-url','origin'),git(root,'remote','get-url','--push','origin'))
                 for root in (primary,publisher,peer)]
        if origins[0]!=origins[1] or origins[0]!=origins[2]:raise ActivationError('publisher/peer origin differs')
        binary=Path(args.bd_bin).resolve()
        if not binary.is_file() or binary.is_symlink():raise ActivationError('qualified native bd binary unavailable')
        qualified=call(['node','--input-type=module','-e',
            "import {qualifyBinary} from './scripts/lib/bd-managed-cli.mjs'; process.stdout.write(qualifyBinary(process.argv[1]))",
            binary],publisher,'native CLI qualification')
        if not re.fullmatch(r'[0-9a-f]{64}',qualified):raise ActivationError('native CLI fingerprint invalid')
        primary_init=native_init(primary,binary,args.prefix,args.actor,work)
        peer_init=native_init(peer,binary,args.prefix,args.actor,work)
        for key,value in (('overgate.beadsPublisher',str(publisher)),('overgate.beadsCli',str(binary)),
                          ('overgate.beadsPrefix',args.prefix)):
            git(peer,'config','--local','--replace-all',key,value)
        setup=work/'publisher-setup.json'
        call(['node','scripts/bd-publisher-setup.mjs','--primary-root',primary,'--publisher-root',publisher,
              '--qualified-cli',binary,'--output',setup],publisher,'publisher setup prepare')
        call(['node','scripts/bd-publisher-setup.mjs','--install',setup],publisher,'publisher setup install')
        preservation=publisher/'.git/overgate-bd-managed/preservation'
        preservation.mkdir(parents=True)
        manifest=preservation/'preservation.json'
        manifest.write_text(json.dumps({'version':1,'base':ZERO,'actor':args.actor,'outcome':'verified-absent','artifacts':{}})+'\n')
        shell=bash()
        entry=lambda *commands:json.loads(call([shell,'scripts/bd-apply-intents.sh',*commands],publisher,'trusted managed apply',
                                          {**os.environ,'BD_BIN':str(binary)},180))
        if entry('--bootstrap',manifest).get('status')!='bootstrapped':raise ActivationError('verified-absent bootstrap failed')
        prepared=work/'prepared.v2.jsonl'
        if entry('--prepare','--base',ZERO,'--actor',args.actor,'--output',prepared,raw).get('status')!='prepared':
            raise ActivationError('typed queue preparation failed')
        result=entry(prepared)
        if result.get('status')!='published' or not re.fullmatch(r'[0-9a-f]{40}',result.get('published_sha','')):
            raise ActivationError('managed publication not confirmed')
        claims=result.get('claims',[])
        if len(claims)!=1 or claims[0].get('confirmed') is not True or not claims[0].get('id','').startswith(args.prefix+'-'):
            raise ActivationError('real task ID/claim not confirmed')
        task_id=claims[0]['id'];published=result['published_sha']
        (work/'published.json').write_text(json.dumps({'id':task_id,'published_sha':published})+'\n')
        read=json.loads(call([shell,'scripts/bd-read.sh','show',task_id,'--json'],peer,'peer published read-back'))
        if read.get('id')!=task_id or read.get('status')!='in_progress' or read.get('assignee')!=args.actor:
            raise ActivationError('peer task fields differ from publication')
        if git(peer,'rev-parse','refs/remotes/origin/beads-backup')!=published:
            raise ActivationError('peer read-back SHA differs from published SHA')
        return {'status':'activated','id':task_id,'claim_confirmed':True,'published_sha':published,'peer_sha':published,
                'binary_sha256':qualified,'queue_sha256':queue['queue_sha256'],'primary_init':primary_init,'peer_init':peer_init}
    except (ActivationError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
        raise ActivationError(str(error)+'; queue/base/actor retained: '+json.dumps(queue,sort_keys=True)) from error

def parse():
    parser=argparse.ArgumentParser()
    for name in ('publisher-root','peer-root','bd-bin','prefix','actor','title','work-dir'):
        parser.add_argument('--'+name,required=True)
    return parser.parse_args()

if __name__=='__main__':
    try:print(json.dumps(main(parse()),sort_keys=True))
    except (ActivationError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
        print('STOP: '+str(error),file=sys.stderr)
        raise SystemExit(1)
