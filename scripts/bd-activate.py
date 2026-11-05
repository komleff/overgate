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
import uuid

class ActivationError(Exception): pass

ZERO='0'*40
SCRIPT=Path(__file__).resolve()
ROOT=SCRIPT.parents[1]
spec=importlib.util.spec_from_file_location('overgate_installer',SCRIPT.with_name('install-overgate.py'))
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

def sha(data):return hashlib.sha256(data).hexdigest()

def call(args,cwd,label,env=None,timeout=60):
    result=subprocess.run([str(x) for x in args],cwd=cwd,env=env or installer.git_environment(),capture_output=True,text=True,timeout=timeout)
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
    original=subprocess.run(['git','show',head+':.overgate/install-state.json'],cwd=root,capture_output=True,env=installer.git_environment())
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
        original=subprocess.run(['git','show',head+':'+name],cwd=root,capture_output=True,env=installer.git_environment())
        if original.returncode or original.stdout!=data:
            raise ActivationError('installed managed closure differs from trusted main: '+name)
    return state

def inventory(root):
    result=installer.beads_inventory(root)
    if result['remote']['status']!='verified-absent' or result['blocked']:
        raise ActivationError('Beads preservation required before activation: '+'; '.join(result['reasons']))
    return result

def origin_state(root):
    fetch=git(root,'remote','get-url','origin')
    pushes=git(root,'remote','get-url','--push','--all','origin').splitlines()
    if not fetch or not pushes:raise ActivationError('origin fetch/push destination unavailable')
    return (fetch,pushes)

def local_git_values(root,key):
    result=subprocess.run(['git','-C',str(root),'config','--local','--null','--get-all',key],
                          capture_output=True,env=installer.git_environment())
    if result.returncode==1:return []
    if result.returncode!=0:raise ActivationError('publisher local Git config unavailable: '+key)
    return [value.decode('utf-8') for value in result.stdout.rstrip(b'\0').split(b'\0')]

def publisher_identity_auth(root,push_destinations):
    names=local_git_values(root,'user.name');emails=local_git_values(root,'user.email')
    local_identity=len(names)==len(emails)==1 and names[0].strip() and emails[0].strip()
    service_identity=all(os.environ.get(key,'').strip() for key in
                         ('GIT_AUTHOR_NAME','GIT_AUTHOR_EMAIL','GIT_COMMITTER_NAME','GIT_COMMITTER_EMAIL'))
    if not (local_identity or service_identity):
        raise ActivationError('publisher Git identity unavailable under isolated config; set repo-local user.name/user.email or explicit service author/committer identity')
    for identity in ('GIT_AUTHOR_IDENT','GIT_COMMITTER_IDENT'):
        if not git(root,'var',identity):raise ActivationError('publisher Git identity unavailable: '+identity)
    helpers=[value for value in local_git_values(root,'credential.helper') if value]
    for destination in push_destinations.splitlines():
        if re.match(r'^https://',destination,re.I):
            if not helpers:raise ActivationError('publisher HTTPS authentication unavailable under isolated config; configure a trusted repo-local credential.helper or use SSH agent origin')
        elif re.match(r'^(ssh://|[^/\s]+@[^/:\s]+:)',destination,re.I):
            if not os.environ.get('SSH_AUTH_SOCK'):
                raise ActivationError('publisher SSH authentication unavailable; start SSH agent or configure trusted repo-local HTTPS credential.helper')
        elif not (Path(destination).is_absolute() or destination.startswith('file://')):
            raise ActivationError('publisher push origin transport unsupported under isolated config')

def native_env(root):
    env={key:value for key,value in installer.git_environment().items() if not key.startswith(('BEADS_','DOLT_','BD_'))}
    env.update({'GIT_CONFIG_GLOBAL':'NUL' if os.name=='nt' else '/dev/null','GIT_CONFIG_NOSYSTEM':'1',
                'GIT_TERMINAL_PROMPT':'0','BD_DISABLE_METRICS':'1','DOLT_METRICS_DISABLED':'1',
                'DOLT_ROOT_PATH':str(root/'.git/overgate-bd-activation/dolt-global')})
    return env

def native_init(root,binary,prefix,actor,work,prior=None,allow_published=False):
    if prior is None and ((root/'.beads').exists() or (root/'.beads').is_symlink()):
        raise ActivationError('local Beads state appeared before native init; preserve it for reviewed recovery')
    if prior is not None and (root/'.beads').is_symlink():raise ActivationError('resumed Beads directory symlink denied')
    index=Path(git(root,'rev-parse','--path-format=absolute','--git-path','index'))
    if os.environ.get('GIT_INDEX_FILE') or (index.exists() and index.is_symlink()):
        raise ActivationError('canonical Git index override/unsafe index denied')
    before=(git(root,'rev-parse','HEAD'),index.read_bytes() if index.exists() else None)
    exclude=root/'.git/info/exclude';exclude_before=exclude.read_bytes() if exclude.exists() else None
    if subprocess.run(['git','-C',str(root),'diff','--cached','--quiet','--'],capture_output=True,env=installer.git_environment()).returncode:
        raise ActivationError('staged Git index denied before native init')
    env=native_env(root)
    db=root/'.beads/dolt'
    if prior is None:
        call([binary,'--db',db,'--actor',actor,'init','--prefix',prefix,'--non-interactive',
              '--skip-agents','--skip-hooks','--stealth'],root,'native bd init',env,180)
    elif not (root/'.beads/metadata.json').is_file():raise ActivationError('resumed native metadata missing; preserve checkpoint')
    if (git(root,'rev-parse','HEAD'),index.read_bytes() if index.exists() else None)!=before:
        raise ActivationError('native bd init changed HEAD/index; stop and preserve local state')
    if git(root,'status','--porcelain','--untracked-files=no'):
        raise ActivationError('native bd init changed tracked files; stop and preserve local state')
    if not allow_published and installer.beads_inventory(root)['remote']['status']!='verified-absent':
        raise ActivationError('remote changed during native init; stop before publication')
    config=json.loads(call([binary,'--db',db,'--readonly','config','list','--json'],root,'native prefix read-back',env))
    if config.get('issue_prefix')!=prefix:raise ActivationError('native issue prefix differs from project-owned prefix')
    metadata=json.loads((root/'.beads/metadata.json').read_bytes())
    if metadata.get('backend')!='dolt' or metadata.get('dolt_mode')!='embedded' or not metadata.get('project_id'):
        raise ActivationError('native Beads metadata invalid')
    exported=work/(root.name+'-empty.jsonl')
    call([binary,'--db',db,'export','--all','-o',exported],root,'native empty export',env,180)
    if exported.read_bytes():raise ActivationError('native init contains issue state; stop before publication')
    receipt={'head':before[0],'index_sha256':sha(before[1] or b''),
            'git_exclude_before_sha256':sha(exclude_before) if exclude_before is not None else None,
            'git_exclude_after_sha256':sha(exclude.read_bytes()) if exclude.exists() else None,
            'metadata_sha256':sha((root/'.beads/metadata.json').read_bytes()),
            'config_sha256':sha((root/'.beads/config.yaml').read_bytes())}
    if prior is not None:
        receipt['git_exclude_before_sha256']=prior['git_exclude_before_sha256']
        if receipt!=prior:raise ActivationError('resumed native state drift; preserve database and queue')
    return receipt

def bash():
    if os.name!='nt':return 'bash'
    candidates=[Path('C:/Program Files/Git/bin/bash.exe')]
    candidates += [Path(p)/'bash.exe' for p in os.environ.get('PATH','').split(os.pathsep)]
    candidates += [Path('C:/Program Files/Git/usr/bin/bash.exe')]
    for candidate in candidates:
        if candidate.is_file() and 'system32' not in str(candidate).lower():return str(candidate)
    raise ActivationError('native Git Bash unavailable')

STAGES=('queued','primary-init','peer-init','setup','bootstrapped','prepared','published','complete')
def stage_at(journal,name):return STAGES.index(journal['stage'])>=STAGES.index(name)
def checkpoint(work,journal,stage,**updates):
    if stage not in STAGES or STAGES.index(stage)<STAGES.index(journal['stage']):
        raise ActivationError('activation checkpoint regression')
    value={**journal,**updates,'stage':stage}
    target=work/'activation-checkpoint.json';temporary=work/('activation-checkpoint.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x',encoding='utf-8') as output:
        json.dump(value,output,sort_keys=True);output.write('\n');output.flush();os.fsync(output.fileno())
    os.replace(temporary,target)
    journal.clear();journal.update(value)
def fail_at(point):
    if os.environ.get('OVERGATE_BD_ACTIVATE_TEST_FAIL_AT')==point:
        raise ActivationError('injected activation stop after '+point)

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
    head=trusted(primary);installed(primary,head)
    origin_sha256=sha(json.dumps(origin_state(primary),separators=(',',':')).encode())
    requested_work=Path(args.work_dir);work=requested_work.resolve()
    if not requested_work.is_absolute() or requested_work.is_symlink() or any(work==root or root in work.parents for root in (primary,publisher,peer)):
        raise ActivationError('private activation work directory must be outside checkouts')
    if args.resume:
        if not work.is_dir() or work.is_symlink() or work.resolve()!=work:
            raise ActivationError('exact private activation work directory required for resume')
    else:
        inventory(primary)
        if work.exists() or work.is_symlink():raise ActivationError('private activation work directory must be new')
        work.mkdir(parents=True,mode=0o700)
    raw=work/'raw-intents.jsonl'
    raw_bytes=''.join(json.dumps(item,separators=(',',':'))+'\n' for item in (
        {'intent_id':'activation-create','op':'create','handle':'tmp:first-task','title':args.title},
        {'intent_id':'activation-claim','op':'claim','ref':'tmp:first-task'})).encode('utf-8')
    bound={'primary':str(primary),'publisher':str(publisher),'peer':str(peer),'head':head,
           'actor':args.actor,'prefix':args.prefix,'title':args.title,'binary':str(Path(args.bd_bin).resolve()),
           'raw_sha256':sha(raw_bytes),'origin_sha256':origin_sha256}
    if args.resume:
        checkpoint_file=work/'activation-checkpoint.json'
        if not checkpoint_file.is_file() or checkpoint_file.is_symlink() or raw.is_symlink() or not raw.is_file():
            raise ActivationError('activation checkpoint/queue missing or unsafe; preserve state')
        journal=json.loads(checkpoint_file.read_bytes())
        if not isinstance(journal,dict) or not isinstance(journal.get('bound'),dict):
            raise ActivationError('activation checkpoint invalid; preserve queue and native state')
        if journal['bound'].get('origin_sha256')!=origin_sha256:
            raise ActivationError('activation checkpoint origin changed; preserve queue and native state')
        if journal.get('version')!=1 or journal.get('bound')!=bound or journal.get('stage') not in STAGES or raw.read_bytes()!=raw_bytes:
            raise ActivationError('activation checkpoint/queue binding changed; preserve state')
    else:
        with raw.open('xb') as output:output.write(raw_bytes);output.flush();os.fsync(output.fileno())
        journal={'version':1,'stage':'queued','bound':bound}
        checkpoint(work,journal,'queued')
    queue={'queue':str(raw),'queue_sha256':bound['raw_sha256'],'base':ZERO,'actor':args.actor}
    try:
        if not publisher.is_dir() or not peer.is_dir():raise ActivationError('publisher/peer checkout unavailable; queue retained')
        for root in (publisher,peer):
            if trusted(root)!=head:raise ActivationError('publisher/peer trusted main differs from primary')
            installed(root,head)
            if not args.resume:inventory(root)
        origins=[origin_state(root) for root in (primary,publisher,peer)]
        if origins[0]!=origins[1] or origins[0]!=origins[2]:raise ActivationError('publisher/peer origin differs')
        publisher_identity_auth(publisher,'\n'.join(origins[1][1]))
        if args.resume:
            remote_states=[installer.beads_inventory(root)['remote'] for root in (primary,publisher,peer)]
            if len({json.dumps(item,sort_keys=True) for item in remote_states})!=1 or remote_states[0]['status']=='unknown':
                raise ActivationError('resumed remote task state unavailable/drifted; preserve queue')
            remote_state=remote_states[0]
            if stage_at(journal,'published'):
                if remote_state!={'status':'present','R':journal['published']['published_sha']}:
                    raise ActivationError('published activation R changed before peer read-back')
            elif remote_state['status']=='present':
                active=publisher/'.git/overgate-bd-managed/active.json'
                pending=json.loads(active.read_bytes()) if active.is_file() and not active.is_symlink() else {}
                if not stage_at(journal,'prepared') or pending.get('candidate')!=remote_state['R']:
                    raise ActivationError('remote appeared without this retained candidate; preserve queue')
            elif remote_state['status']!='verified-absent':
                raise ActivationError('resumed remote is not verified absent')
        binary=Path(args.bd_bin).resolve()
        if not binary.is_file() or binary.is_symlink():raise ActivationError('qualified native bd binary unavailable')
        qualified=call(['node','--input-type=module','-e',
            "import {qualifyBinary} from './scripts/lib/bd-managed-cli.mjs'; process.stdout.write(qualifyBinary(process.argv[1]))",
            binary],publisher,'native CLI qualification')
        if not re.fullmatch(r'[0-9a-f]{64}',qualified):raise ActivationError('native CLI fingerprint invalid')
        if journal.get('binary_sha256') not in (None,qualified):raise ActivationError('qualified CLI changed on resume')
        checkpoint(work,journal,journal['stage'],binary_sha256=qualified)
        primary_init=native_init(primary,binary,args.prefix,args.actor,work,journal.get('primary_init') if stage_at(journal,'primary-init') else None,
                                 stage_at(journal,'published'))
        if not stage_at(journal,'primary-init'):checkpoint(work,journal,'primary-init',primary_init=primary_init)
        peer_init=native_init(peer,binary,args.prefix,args.actor,work,journal.get('peer_init') if stage_at(journal,'peer-init') else None,
                              stage_at(journal,'published'))
        if not stage_at(journal,'peer-init'):checkpoint(work,journal,'peer-init',peer_init=peer_init)
        fail_at('after-peer-init')
        for key,value in (('overgate.beadsPublisher',str(publisher)),('overgate.beadsCli',str(binary)),
                          ('overgate.beadsPrefix',args.prefix)):
            current=subprocess.run(['git','-C',str(peer),'config','--local','--get',key],capture_output=True,text=True,env=installer.git_environment())
            if current.returncode not in (0,1) or current.returncode==0 and current.stdout.strip()!=value:
                raise ActivationError('peer reader registration changed; preserve queue')
            if current.returncode==1:git(peer,'config','--local','--replace-all',key,value)
        setup=work/'publisher-setup.json'
        if not setup.exists():
            if stage_at(journal,'setup'):raise ActivationError('publisher setup plan missing on resume')
            call(['node','scripts/bd-publisher-setup.mjs','--primary-root',primary,'--publisher-root',publisher,
                  '--qualified-cli',binary,'--output',setup],publisher,'publisher setup prepare')
        call(['node','scripts/bd-publisher-setup.mjs','--install',setup],publisher,'publisher setup install')
        if not stage_at(journal,'setup'):checkpoint(work,journal,'setup')
        fail_at('after-setup')
        preservation=publisher/'.git/overgate-bd-managed/preservation'
        preservation.mkdir(parents=True,exist_ok=True)
        manifest=preservation/'preservation.json'
        manifest_bytes=(json.dumps({'version':1,'base':ZERO,'actor':args.actor,'outcome':'verified-absent','artifacts':{}})+'\n').encode()
        if manifest.exists():
            if manifest.is_symlink() or manifest.read_bytes()!=manifest_bytes:raise ActivationError('bootstrap preservation manifest changed')
        else:
            with manifest.open('xb') as output:output.write(manifest_bytes);output.flush();os.fsync(output.fileno())
        shell=bash()
        entry=lambda *commands:json.loads(call([shell,'scripts/bd-apply-intents.sh',*commands],publisher,'trusted managed apply',
                                          installer.git_environment({'BD_BIN':str(binary)}),180))
        if not stage_at(journal,'bootstrapped'):
            if entry('--bootstrap',manifest).get('status')!='bootstrapped':raise ActivationError('verified-absent bootstrap failed')
            checkpoint(work,journal,'bootstrapped')
        fail_at('after-bootstrap')
        prepared=work/'prepared.v2.jsonl'
        if not stage_at(journal,'prepared'):
            if prepared.exists():raise ActivationError('uncheckpointed prepared queue collision; preserve it for review')
            if entry('--prepare','--base',ZERO,'--actor',args.actor,'--output',prepared,raw).get('status')!='prepared':
                raise ActivationError('typed queue preparation failed')
            checkpoint(work,journal,'prepared',prepared_sha256=sha(prepared.read_bytes()))
        if prepared.is_symlink() or not prepared.is_file() or sha(prepared.read_bytes())!=journal['prepared_sha256']:
            raise ActivationError('prepared queue changed on resume; preserve state')
        result=journal['published'] if stage_at(journal,'published') else entry(prepared)
        if result.get('status')!='published' or not re.fullmatch(r'[0-9a-f]{40}',result.get('published_sha','')):
            raise ActivationError('managed publication not confirmed')
        claims=result.get('claims',[])
        if len(claims)!=1 or claims[0].get('confirmed') is not True or not claims[0].get('id','').startswith(args.prefix+'-'):
            raise ActivationError('real task ID/claim not confirmed')
        task_id=claims[0]['id'];published=result['published_sha']
        if not stage_at(journal,'published'):checkpoint(work,journal,'published',published=result)
        fail_at('after-push')
        published_file=work/'published.json';published_bytes=(json.dumps({'id':task_id,'published_sha':published})+'\n').encode()
        if published_file.exists():
            if published_file.is_symlink() or published_file.read_bytes()!=published_bytes:raise ActivationError('published receipt changed')
        else:
            with published_file.open('xb') as output:output.write(published_bytes);output.flush();os.fsync(output.fileno())
        read=json.loads(call([shell,'scripts/bd-read.sh','show',task_id,'--json'],peer,'peer published read-back'))
        if read.get('id')!=task_id or read.get('status')!='in_progress' or read.get('assignee')!=args.actor:
            raise ActivationError('peer task fields differ from publication')
        if git(peer,'rev-parse','refs/remotes/origin/beads-backup')!=published:
            raise ActivationError('peer read-back SHA differs from published SHA')
        completed={'status':'activated','id':task_id,'claim_confirmed':True,'published_sha':published,'peer_sha':published,
                   'binary_sha256':qualified,'queue_sha256':queue['queue_sha256'],'primary_init':primary_init,'peer_init':peer_init}
        checkpoint(work,journal,'complete',completed=completed)
        return completed
    except (ActivationError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
        raise ActivationError(str(error)+'; queue/base/actor retained: '+json.dumps(queue,sort_keys=True)) from error

def parse():
    parser=argparse.ArgumentParser()
    for name in ('publisher-root','peer-root','bd-bin','prefix','actor','title','work-dir'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--resume',action='store_true')
    return parser.parse_args()

if __name__=='__main__':
    try:print(json.dumps(main(parse()),sort_keys=True))
    except (ActivationError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
        print('STOP: '+str(error),file=sys.stderr)
        raise SystemExit(1)
