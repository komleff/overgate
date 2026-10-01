#!/usr/bin/env python3
"""Frozen-source plan/apply/rollback. Никакой сети, credentials или force overwrite."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import uuid

MANIFEST = '.agents/distribution-manifest.json'
STATE = '.overgate/install-state.json'

class InstallError(Exception): pass

def digest(data): return hashlib.sha256(data).hexdigest()
def json_bytes(value): return (json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
def git(root,*args):
    run=subprocess.run(['git','-C',str(root),*args],capture_output=True)
    if run.returncode: raise InstallError('git failed: '+ ' '.join(args[:2]))
    return run.stdout

def safe(root,path):
    p=PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or str(p)!=path or not p.parts:
        raise InstallError('unsafe managed path: '+path)
    if any(x.startswith('.env') or x in {'.git','.beads','.memory-bank'} or 'credential' in x.lower() or 'secret' in x.lower() for x in p.parts):
        raise InstallError('forbidden managed path: '+path)
    result=root/path
    for part in [result,*result.parents]:
        if part == root.parent: break
        if part.is_symlink(): raise InstallError('symlink managed path: '+path)
    if result.exists() and not result.is_file(): raise InstallError('managed path is not regular: '+path)
    return result

def current(root,path):
    p=safe(root,path)
    if not p.exists(): return None
    return {'sha256':digest(p.read_bytes()),'mode':p.stat().st_mode & 0o777}

def load_manifest(source,sha):
    if not re.fullmatch('[0-9a-f]{40}',sha): raise InstallError('source SHA must be exact 40 hex')
    if git(source,'rev-parse','HEAD').decode().strip()!=sha: raise InstallError('source movement: HEAD differs from frozen SHA')
    try:m=json.loads(git(source,'show',sha+':'+MANIFEST))
    except (ValueError,InstallError) as e: raise InstallError('missing/invalid distribution manifest') from e
    paths=[];targets=[]
    for entry in m['files']:
        safe(source,entry['source']); paths.append(entry['source']); targets.append(entry['target'])
    if len(targets)!=len(set(targets)): raise InstallError('duplicate target inventory')
    if git(source,'status','--porcelain','--untracked-files=all','--',*sorted(set(paths))):
        raise InstallError('dirty copied source surfaces; commit or select a clean source')
    payload={}
    for path in set(paths):
        try:data=git(source,'show',sha+':'+path);meta=git(source,'ls-tree',sha,'--',path).decode().split()
        except InstallError as e:raise InstallError('missing source dependency: '+path) from e
        if not meta or meta[0] not in {'100644','100755'}:raise InstallError('missing/unsafe source dependency: '+path)
        payload[path]=(data,0o755 if meta[0]=='100755' else 0o644)
    skills={x for x in payload if x.startswith('.agents/skills/') and x.endswith('/SKILL.md')}
    expected={f'.agents/skills/{x}/SKILL.md' for x in ('canon-router','product-gap','product-handoff','diagnose','handoff')}
    actual=set(git(source,'ls-tree','-r','--name-only',sha,'--','.agents/skills').decode().splitlines())
    if skills!=expected or {x for x in actual if x.endswith('SKILL.md')}!=expected:
        raise InstallError('missing/nested/orphan skill payload')
    return m,payload

def merge_settings(existing,new,legacy):
    if existing is None:return new
    try:before=json.loads(existing);after=json.loads(new)
    except ValueError as e:raise InstallError('conflict: runtime settings must be valid JSON') from e
    old_entries=legacy.get('hooks',{}).get('PreToolUse',[])
    managed_names=('check-repository-mutation.py','check-tests-before-commit.sh','check-merge-ready.py')
    kept=[]
    for entry in before.get('hooks',{}).get('PreToolUse',[]):
        if entry in old_entries or entry in after['hooks']['PreToolUse']:continue
        if any(name in json.dumps(entry) for name in managed_names):
            raise InstallError('conflict: custom managed runtime hook; resolve in target PR')
        kept.append(entry)
    before.setdefault('hooks',{})['PreToolUse']=kept+after['hooks']['PreToolUse']
    # Env, SessionStart, project permissions и прочие overrides остаются; required deny дополняет их.
    for field in ('deny',):
        values=before.setdefault('permissions',{}).setdefault(field,[])
        for value in after.get('permissions',{}).get(field,[]):
            if value not in values:values.append(value)
    return json_bytes(before)

def make_plan(source,sha,target,contract,target_pr):
    source=source.resolve();target=target.resolve();contract=contract.resolve()
    if source==target:raise InstallError('source and target must be separate checkouts')
    if not re.fullmatch(r'https://[^/]+/[^/]+/[^/]+/pull/[1-9][0-9]*',target_pr):raise InstallError('target Draft PR URL required')
    git(target,'rev-parse','--show-toplevel')
    branch=git(target,'branch','--show-current').decode().strip()
    if not branch or branch in {'main','master'}:raise InstallError('target must be a named working branch')
    if not contract.is_file() or not contract.read_bytes().strip():raise InstallError('Verification Contract required')
    m,payload=load_manifest(source,sha)
    previous={}
    if safe(target,STATE).exists():
        previous=json.loads((target/STATE).read_text()).get('installed',{})
    operations=[];conflicts=[]
    for entry in m['files']:
        path=entry['target'];p=safe(target,path);old=current(target,path);data,mode=payload[entry['source']]
        policy=entry.get('policy','managed')
        if policy=='preserve' and old is not None:continue
        if policy=='ignore':
            old_text=p.read_text() if old else ''
            old_text='\n'.join(x for x in old_text.splitlines() if x.strip()!='.codex/')
            data=(old_text.rstrip()+'\n\n'+data.decode()).encode()
        elif policy=='settings':
            try:data=merge_settings(p.read_bytes() if old else None,data,m.get('legacy_settings',{}))
            except InstallError as e:conflicts.append(f'{path}: {e}');continue
        elif old is not None and old['sha256']!=digest(data):
            prior=previous.get(path,{}).get('sha256')
            blob=git(target,'hash-object',str(p)).decode().strip()
            if old['sha256']!=prior and blob!=m.get('legacy_blobs',{}).get(path):
                conflicts.append(path+': conflict with project override; no force overwrite');continue
        operations.append({'source':entry['source'],'target':path,'before':old,'after':{'sha256':digest(data),'mode':mode},
                           'data':base64.b64encode(data).decode() if policy in {'settings','ignore'} else None})
    return {'format':1,'source':str(source),'source_sha':sha,'target':str(target),'branch':branch,
            'target_pr':target_pr,'contract':str(contract),'contract_sha256':digest(contract.read_bytes()),
            'operations':operations,'conflicts':conflicts,'state_before':current(target,STATE)}

def write_atomic(root,path,data,mode):
    p=safe(root,path);p.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.overgate-write-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,mode);os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)

def restore(root,entries):
    for item in reversed(entries):
        p=safe(root,item['target'])
        if item['before'] is None:
            if p.exists():p.unlink()
        else:write_atomic(root,item['target'],base64.b64decode(item['data']),item['before']['mode'])

def apply(plan_path,approval_path):
    raw=plan_path.read_bytes();plan=json.loads(raw);approval=json.loads(approval_path.read_bytes())
    if approval.get('verdict')!='PLAN_READY' or approval.get('plan_sha256')!=digest(raw) or not approval.get('evidence','').startswith(plan['target_pr']+'#'):
        raise InstallError('PLAN_READY must bind exact plan bytes and evidence in same target PR')
    if digest(Path(plan['contract']).read_bytes())!=plan['contract_sha256']:raise InstallError('contract drift after Plan Review')
    now=make_plan(Path(plan['source']),plan['source_sha'],Path(plan['target']),Path(plan['contract']),plan['target_pr'])
    if now!=plan:raise InstallError('target/source plan drift after Plan Review; regenerate plan in same PR')
    if plan['conflicts']:raise InstallError('conflicts require explicit project resolution: '+'; '.join(plan['conflicts']))
    root=Path(plan['target']);_,payload=load_manifest(Path(plan['source']),plan['source_sha'])
    if (root/'.overgate-backups').is_symlink():raise InstallError('symlink backup directory')
    backup=root/'.overgate-backups'/uuid.uuid4().hex
    backup.mkdir(parents=True)
    entries=[]
    for operation in plan['operations']+[{'target':STATE,'before':plan['state_before']}]:
        path=operation['target'];p=safe(root,path)
        entries.append({'target':path,'before':operation['before'],'data':base64.b64encode(p.read_bytes()).decode() if p.exists() else None})
    journal={'format':1,'target':str(root),'source_sha':plan['source_sha'],'plan_sha256':digest(raw),'entries':entries,'after':{},'complete':False}
    backup_file=backup/'rollback.json';backup_file.write_bytes(json_bytes(journal))
    # Все before bytes сохранены ДО первой target mutation; повторная проверка закрывает preflight race.
    if any(current(root,x['target'])!=x['before'] for x in entries):raise InstallError('target drift before first write')
    try:
        for op in plan['operations']:
            data=base64.b64decode(op['data']) if op['data'] is not None else payload[op['source']][0]
            if digest(data)!=op['after']['sha256']:raise InstallError('payload fingerprint mismatch')
            write_atomic(root,op['target'],data,op['after']['mode'])
        installed={op['target']:op['after'] for op in plan['operations']}
        state={'format':1,'source':plan['source'],'source_sha':plan['source_sha'],'target_pr':plan['target_pr'],
               'plan_sha256':digest(raw),'approval':approval,'backup':str(backup_file),'installed':installed}
        write_atomic(root,STATE,json_bytes(state),0o644)
        journal['after']={x['target']:current(root,x['target']) for x in entries};journal['complete']=True
        backup_file.write_bytes(json_bytes(journal))
    except BaseException:
        restore(root,entries)
        raise
    print('Applied frozen source '+plan['source_sha']+'; backup: '+str(backup_file))

def rollback(target,backup):
    root=target.resolve();journal=json.loads(backup.read_bytes())
    if journal.get('target')!=str(root) or not journal.get('complete'):raise InstallError('invalid/incomplete rollback manifest')
    for entry in journal['entries']:
        path=entry['target'];safe(root,path)
        if current(root,path)!=journal['after'].get(path):raise InstallError('rollback drift: '+path)
        if entry['before'] and digest(base64.b64decode(entry['data']))!=entry['before']['sha256']:raise InstallError('corrupt rollback bytes: '+path)
    restore(root,journal['entries'])
    print('Rollback restored managed bytes; project state untouched')

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('plan')
    for flag in ('source','target','contract','output'):p.add_argument('--'+flag,required=True,type=Path)
    p.add_argument('--source-sha',required=True);p.add_argument('--target-pr',required=True)
    p=sub.add_parser('apply');p.add_argument('--plan',required=True,type=Path);p.add_argument('--approval',required=True,type=Path)
    p=sub.add_parser('rollback');p.add_argument('--target',required=True,type=Path);p.add_argument('--backup',required=True,type=Path)
    args=parser.parse_args()
    try:
        if args.command=='plan':
            plan=make_plan(args.source,args.source_sha,args.target,args.contract,args.target_pr)
            args.output.write_bytes(json_bytes(plan));print('Plan written; conflicts='+str(len(plan['conflicts']))+'; SHA256='+digest(args.output.read_bytes()))
        elif args.command=='apply':apply(args.plan,args.approval)
        else:rollback(args.target,args.backup)
    except (InstallError,OSError,ValueError,KeyError,TypeError) as e:
        print('STOP: '+str(e),file=sys.stderr);return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
