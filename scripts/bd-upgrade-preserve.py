#!/usr/bin/env python3
"""Read-only legacy Beads preservation packet for a separately reviewed upgrade."""
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
import tempfile

SCRIPT=Path(__file__).resolve()
spec=importlib.util.spec_from_file_location('overgate_installer',SCRIPT.with_name('install-overgate.py'))
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class PreservationError(Exception):pass
def sha(data):return hashlib.sha256(data).hexdigest()
def write_private(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as output:
        output.write(data);output.flush();os.fsync(output.fileno())
def call(args,cwd,label,env=None,timeout=60):
    run=subprocess.run([str(item) for item in args],cwd=cwd,env=env if env is not None else installer.git_environment(),
                       capture_output=True,timeout=timeout)
    if run.returncode:raise PreservationError(label+' failed (exit '+str(run.returncode)+')')
    return run.stdout
def git(root,*args):return call(['git','-C',root,*args],root,'Git '+str(args[0])).decode().strip()

def writer(root,origin):
    if not root.is_dir() or root.is_symlink() or Path(git(root,'rev-parse','--show-toplevel')).resolve()!=root:
        raise PreservationError('writer root must be an authorized standalone checkout')
    common=Path(git(root,'rev-parse','--path-format=absolute','--git-common-dir')).resolve()
    directory=Path(git(root,'rev-parse','--path-format=absolute','--git-dir')).resolve()
    if common!=directory:raise PreservationError('linked worktree cannot be a legacy writer')
    if installer.origin_identity(root)!=origin:raise PreservationError('writer origin differs from target')
    inventory=installer.beads_inventory(root)
    hook_config=subprocess.run(['git','-C',str(root),'config','--local','--get','core.hooksPath'],
                               capture_output=True,env=installer.git_environment())
    if hook_config.returncode not in (0,1):raise PreservationError('writer hooksPath unreadable')
    try: hooks_path=hook_config.stdout.decode('utf-8','strict').strip()
    except UnicodeDecodeError as exc:raise PreservationError('writer hooksPath is not UTF-8') from exc
    hook_dir=(Path(hooks_path) if hook_config.returncode==0 else common/'hooks')
    if not hook_dir.is_absolute():hook_dir=root/hook_dir
    hook_dir=hook_dir.resolve()
    if not (hook_dir==common or common in hook_dir.parents or hook_dir==root or root in hook_dir.parents):
        raise PreservationError('writer hook path outside owned checkout')
    hook=hook_dir/'pre-push'
    if hook.is_symlink() or (hook.exists() and not hook.is_file()):raise PreservationError('writer pre-push hook unsafe')
    return {'root':str(root),'head':git(root,'rev-parse','HEAD'),'inventory':inventory,
            'hook_path':str(hook),'hook_sha256':sha(hook.read_bytes()) if hook.exists() else None,
            'hook_mode':hook.stat().st_mode & 0o777 if hook.exists() else None,
            'hooks_path_config':hooks_path if hook_config.returncode==0 else None}

def fence_receipt(root):
    marker=root/'.git/overgate-bd-legacy-fence.json'
    configured=subprocess.run(['git','-C',str(root),'config','--local','--get','overgate.beadsLegacyFence'],
                              capture_output=True,env=installer.git_environment())
    if configured.returncode not in (0,1):raise PreservationError('legacy fence config unreadable')
    if not marker.exists() and configured.returncode==1:return None
    if marker.is_symlink() or not marker.is_file() or configured.returncode!=0:
        raise PreservationError('legacy fence partially installed')
    value=json.loads(marker.read_bytes());receipt=value.get('packet_sha256')
    if not isinstance(receipt,str) or not re.fullmatch(r'[0-9a-f]{64}',receipt) \
       or configured.stdout.decode('utf-8','strict').strip()!=receipt:
        raise PreservationError('legacy fence receipt mismatch')
    return receipt

def remote_snapshot(target,R):
    origin=installer.origin_identity(target)[0]
    with tempfile.TemporaryDirectory(prefix='overgate-legacy-remote-') as name:
        bare=Path(name).resolve()
        call(['git','init','-q','--bare',bare],bare.parent,'disposable Git init')
        call(['git','-C',bare,'remote','add','origin',origin],bare,'disposable remote registration')
        call(['git','-C',bare,'fetch','-q','--no-tags','origin','refs/heads/beads-backup'],bare,'disposable remote fetch',timeout=120)
        if git(bare,'rev-parse','FETCH_HEAD')!=R:raise PreservationError('remote R advanced during frozen read')
        return call(['git','-C',bare,'show',R+':.beads/issues.jsonl'],bare,'frozen legacy snapshot read')

def local_export(root,binary,temp,actor):
    beads=root/'.beads'
    if beads.is_symlink() or not beads.is_dir():raise PreservationError('legacy local Beads directory missing/unsafe')
    meta=beads/'metadata.json'
    if not meta.is_file() or meta.is_symlink():raise PreservationError('legacy metadata missing/unsafe')
    value=json.loads(meta.read_bytes())
    if value.get('backend')!='dolt' or value.get('dolt_mode')!='embedded':
        raise PreservationError('legacy DB mode not qualified for automatic clean evidence')
    candidates=[beads/name for name in ('dolt','embeddeddolt') if (beads/name).is_dir() and not (beads/name).is_symlink()]
    if len(candidates)!=1:raise PreservationError('legacy embedded DB path unknown/ambiguous')
    output=temp/(root.name+'-local.jsonl')
    env={key:value for key,value in installer.git_environment().items() if not key.startswith(('BEADS_','DOLT_','BD_'))}
    env.update({'GIT_CONFIG_GLOBAL':'NUL' if os.name=='nt' else '/dev/null','GIT_CONFIG_NOSYSTEM':'1',
                'BD_DISABLE_METRICS':'1','DOLT_METRICS_DISABLED':'1','DOLT_ROOT_PATH':str(temp/'dolt-global')})
    call([binary,'--db',candidates[0],'--actor',actor,'--readonly','export','--all','-o',output],root,
         'read-only legacy export',env,180)
    return output.read_bytes()

def packet(args):
    if Path(args.target).is_symlink() or any(Path(item).is_symlink() for item in args.writer_root):
        raise PreservationError('legacy writer symlink path denied')
    target=Path(args.target).resolve();writers=[Path(item).resolve() for item in args.writer_root]
    if not writers or target not in writers or len(set(writers))!=len(writers):
        raise PreservationError('explicit complete writer list must include target and contain no duplicates')
    requested_output=Path(args.output);output=requested_output.resolve();snapshot_path=output.with_suffix('.snapshot.jsonl')
    if not requested_output.is_absolute() or requested_output.is_symlink() or output.exists() or snapshot_path.exists() or any(root==output or root in output.parents for root in writers):
        raise PreservationError('packet and snapshot must be new private paths outside all writer checkouts')
    state_path=target/'.overgate/install-state.json'
    state=json.loads(state_path.read_bytes()) if state_path.is_file() else {}
    if state.get('beads') is not True or state.get('beads_protocol','legacy-v0')!='legacy-v0':
        raise PreservationError('previous legacy-v0 install state required')
    if not re.fullmatch(r'agent-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',args.actor,re.I):
        raise PreservationError('explicit actor UUID required')
    origin=installer.origin_identity(target)
    before=[writer(root,origin) for root in writers]
    fence_receipts=[fence_receipt(root) for root in writers]
    if len(set(fence_receipts))!=1:raise PreservationError('legacy fence receipts incomplete/inconsistent')
    fence_packet_sha256=fence_receipts[0]
    frozen={item['inventory']['remote']['R'] for item in before}
    if len(frozen)!=1 or None in frozen or any(item['inventory']['remote']['status']!='present' for item in before):
        raise PreservationError('all listed writers must observe one present frozen remote R')
    R=frozen.pop();snapshot=remote_snapshot(target,R)
    with tempfile.TemporaryDirectory(prefix='overgate-legacy-local-') as name:
        temp=Path(name).resolve()
        binary=Path(args.bd_bin).resolve()
        if not binary.is_file() or binary.is_symlink():raise PreservationError('qualified native CLI unavailable')
        qualified=call(['node','--input-type=module','-e',
            "import {qualifyBinary} from './scripts/lib/bd-managed-cli.mjs'; process.stdout.write(qualifyBinary(process.argv[1]))",
            binary],SCRIPT.parents[1],'native CLI qualification').decode()
        local={str(root):local_export(root,binary,temp,args.actor) for root in writers}
    after=[writer(root,origin) for root in writers]
    if before!=after or [fence_receipt(root) for root in writers]!=fence_receipts:
        raise PreservationError('legacy state drift during read-only preservation')
    pending=any(any(name in item['inventory']['local'] for name in ('.bd-intents','git/bd-receipts','git/bd-apply.lock.d'))
                for item in before)
    if args.outcome=='verified-clean':
        if pending or any(data!=snapshot for data in local.values()):
            raise PreservationError('clean outcome contradicts pending/local task state')
    elif args.outcome=='pending-retained':
        if not pending and all(data==snapshot for data in local.values()):
            raise PreservationError('retained pending outcome needs actual divergent/pending state')
    else:raise PreservationError('unsupported preservation outcome')
    if installer.beads_inventory(target)['remote']['R']!=R:raise PreservationError('remote R changed during packet write')
    value={'version':1,'outcome':args.outcome,'complete_writer_list':True,'target':str(target),
           'target_state_sha256':sha(state_path.read_bytes()),'target_head':git(target,'rev-parse','HEAD'),
           'origin_sha256':installer.origin_sha256(target),'fence_packet_sha256':fence_packet_sha256,
           'R':R,'snapshot_path':str(snapshot_path),
           'snapshot_sha256':sha(snapshot),'actor':args.actor,'cli_sha256':qualified,
           'writers':before,'local_export_sha256':{root:sha(data) for root,data in local.items()}}
    write_private(snapshot_path,snapshot)
    write_private(output,installer.json_bytes(value))
    return {'packet':str(output),'packet_sha256':sha(output.read_bytes()),'snapshot_sha256':sha(snapshot),'R':R,
            'outcome':args.outcome,'writers':len(writers)}

def parse():
    parser=argparse.ArgumentParser()
    for name in ('target','bd-bin','actor','outcome','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--writer-root',action='append',required=True)
    return parser.parse_args()

if __name__=='__main__':
    try:print(json.dumps(packet(parse()),sort_keys=True))
    except (PreservationError,installer.InstallError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
        print('STOP: '+str(error),file=sys.stderr)
        raise SystemExit(1)
