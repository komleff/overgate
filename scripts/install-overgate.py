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
LEGACY_FENCE_HELPERS = ('scripts/bd-wt.sh','scripts/bd-sync-common.sh','scripts/bd-sync-export.sh',
                        'scripts/bd-sync-restore.sh','scripts/bd-bootstrap.sh','scripts/lib/bd-env.sh')
LEGACY_FENCE_CLOSURE = (*LEGACY_FENCE_HELPERS,'scripts/bd-upgrade-preserve.py',
                        'scripts/bd-upgrade-fence.py','scripts/install-overgate.py')

class InstallError(Exception): pass

def digest(data): return hashlib.sha256(data).hexdigest()
# Формат плана, журнала и install-state не меняется: для них остаётся sort_keys.
def json_bytes(value): return (json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
# Правило 3 записи settings: порядок ключей target, новые ключи в конце, без sort_keys.
def settings_bytes(value): return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
# «Равно по смыслу»: канонический JSON строг к типам (true, 1 и 1.0 различаются), в отличие от ==.
def canonical(value): return json.dumps(value,sort_keys=True,ensure_ascii=False)
def git_environment(extra=None):
    env={name:value for name,value in os.environ.items()
         if not name.startswith('GIT_') or name in ('GIT_AUTHOR_NAME','GIT_AUTHOR_EMAIL','GIT_AUTHOR_DATE',
                                                  'GIT_COMMITTER_NAME','GIT_COMMITTER_EMAIL','GIT_COMMITTER_DATE')}
    env.update({'GIT_CONFIG_GLOBAL':'NUL' if os.name=='nt' else '/dev/null',
                'GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0'})
    if extra:
        if any(name.startswith('GIT_') for name in extra):raise InstallError('Git environment override denied')
        env.update(extra)
    return env
def git(root,*args):
    run=subprocess.run(['git','-C',str(root),*args],capture_output=True,env=git_environment())
    if run.returncode: raise InstallError('git failed: '+ ' '.join(args[:2]))
    return run.stdout

def origin_identity(root):
    fetch=git(root,'remote','get-url','origin').decode('utf-8').strip()
    pushes=git(root,'remote','get-url','--push','--all','origin').decode('utf-8').splitlines()
    if not fetch or not pushes or any(not item for item in pushes):
        raise InstallError('origin fetch/push destination unavailable')
    return [fetch,pushes]

def origin_sha256(root):return digest(json_bytes(origin_identity(root)))

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

def beads_inventory(root):
    # Инвентаризация не обновляет refs целевого checkout и не открывает Dolt.
    common=Path(git(root,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip())
    observed={};reasons=[]
    for name,base in (('.beads',root/'.beads'),('.bd-intents',root/'.bd-intents'),
                      ('git/bd-receipts',common/'bd-receipts'),('git/bd-apply.lock.d',common/'bd-apply.lock.d'),
                      ('git/overgate-bd-managed',common/'overgate-bd-managed'),
                      ('git/overgate-bd-publisher-control',common/'overgate-bd-publisher-control')):
        if not base.exists() and not base.is_symlink():continue
        items=[]
        for item in [base,*sorted(base.rglob('*'))] if base.is_dir() and not base.is_symlink() else [base]:
            relative='.' if item==base else item.relative_to(base).as_posix()
            if item.is_symlink():items.append({'path':relative,'kind':'symlink'});reasons.append(name+': symlink');continue
            if item.is_file():
                with item.open('rb') as stream:
                    hasher=hashlib.sha256()
                    for chunk in iter(lambda:stream.read(1024*1024),b''):hasher.update(chunk)
                items.append({'path':relative,'kind':'file','sha256':hasher.hexdigest(),'size':item.stat().st_size})
            elif item.is_dir():items.append({'path':relative,'kind':'directory'})
            else:items.append({'path':relative,'kind':'unknown'});reasons.append(name+': unknown entry')
        observed[name]=items;reasons.append(name+': retained state')
    config=subprocess.run(['git','-C',str(root),'config','--local','--null','--get-regexp',r'^(overgate\.beads|beads-sync\.|beads\.|core\.hooksPath)'],capture_output=True,env=git_environment())
    if config.returncode not in (0,1):reasons.append('local Git writer config unreadable')
    elif config.stdout:
        observed['git_config_sha256']=digest(config.stdout)
        if any(prefix in config.stdout for prefix in (b'overgate.beads',b'beads-sync.',b'beads.')):
            reasons.append('registered Beads writer/override')
    prompt_env=git_environment()
    try:
        remote=subprocess.run(['git','-C',str(root),'ls-remote','--exit-code','--heads','origin','refs/heads/beads-backup'],
                              capture_output=True,env=prompt_env,timeout=30)
        if remote.returncode==2 and not remote.stdout:remote_state={'status':'verified-absent','R':None}
        elif remote.returncode==0 and re.fullmatch(rb'[0-9a-f]{40}\trefs/heads/beads-backup\n?',remote.stdout):
            remote_state={'status':'present','R':remote.stdout.split(b'\t',1)[0].decode()};reasons.append('remote beads-backup present')
        else:remote_state={'status':'unknown','R':None};reasons.append('remote beads-backup unavailable')
    except subprocess.TimeoutExpired:
        remote_state={'status':'unknown','R':None};reasons.append('remote beads-backup timed out')
    return {'remote':remote_state,'local':observed,'blocked':bool(reasons),'reasons':sorted(set(reasons))}

def preservation_packet(root,inventory,packet_path):
    if packet_path is None:return None
    if packet_path.is_symlink():raise InstallError('preservation packet symlink denied')
    packet_path=packet_path.resolve()
    if not packet_path.is_file() or root==packet_path or root in packet_path.parents:
        raise InstallError('preservation packet must be an existing private regular file outside target')
    raw=packet_path.read_bytes();packet=json.loads(raw)
    if packet.get('version')!=1 or packet.get('outcome') not in ('verified-clean','pending-retained') or packet.get('complete_writer_list') is not True:
        raise InstallError('preservation packet invalid/incomplete')
    prior_fence=packet.get('fence_packet_sha256')
    if prior_fence is not None and (not isinstance(prior_fence,str) or not re.fullmatch(r'[0-9a-f]{64}',prior_fence)):
        raise InstallError('preservation fence receipt invalid')
    state=root/STATE
    state_hash=digest(state.read_bytes()) if state.is_file() else None
    if packet.get('target')!=str(root) or packet.get('target_head')!=git(root,'rev-parse','HEAD').decode().strip() or packet.get('target_state_sha256')!=state_hash:
        raise InstallError('preservation target/installed-state mismatch')
    if inventory['remote']['status']!='present' or packet.get('R')!=inventory['remote']['R']:
        raise InstallError('preservation frozen remote R mismatch')
    if packet.get('origin_sha256')!=origin_sha256(root):raise InstallError('preservation origin changed')
    snapshot=Path(packet.get('snapshot_path',''))
    if not snapshot.is_absolute() or snapshot.is_symlink() or not snapshot.is_file() or root in snapshot.resolve().parents:
        raise InstallError('preservation snapshot artifact missing/unsafe')
    if packet.get('snapshot_sha256')!=digest(snapshot.read_bytes()):raise InstallError('preservation snapshot bytes changed')
    writers=packet.get('writers')
    if not isinstance(writers,list) or not writers or str(root) not in [item.get('root') for item in writers]:
        raise InstallError('preservation explicit writer list missing target')
    if len({item.get('root') for item in writers})!=len(writers):raise InstallError('preservation duplicate writer')
    for item in writers:
        writer=Path(item['root'])
        if not writer.is_dir() or writer.resolve()!=writer or item.get('head')!=git(writer,'rev-parse','HEAD').decode().strip():
            raise InstallError('preservation writer unavailable/advanced')
        if origin_sha256(writer)!=packet['origin_sha256']:
            raise InstallError('preservation writer origin changed')
        actual=beads_inventory(writer)
        if actual!=item.get('inventory') or actual['remote']!=inventory['remote']:
            raise InstallError('preservation writer local/remote state drift')
        hook=Path(item['hook_path'])
        if hook.is_symlink() or (hook.exists() and (not hook.is_file() or digest(hook.read_bytes())!=item.get('hook_sha256'))) \
           or (not hook.exists() and item.get('hook_sha256') is not None):
            raise InstallError('preservation writer hook drift')
    return {'path':str(packet_path),'sha256':digest(raw),'outcome':packet['outcome'],'R':packet['R'],
            'writers':[item['root'] for item in writers]}

def verified_legacy_fences(packet_path):
    packet_bytes=Path(packet_path).read_bytes()
    packet=json.loads(packet_bytes)
    packet_hash=packet.get('fence_packet_sha256')
    if not isinstance(packet_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',packet_hash):
        raise InstallError('legacy fence pre-switch packet missing')
    roots=[item['root'] for item in packet['writers']]
    receipts=[]
    for name in roots:
        root=Path(name)
        marker=root/'.git/overgate-bd-legacy-fence.json'
        if marker.is_symlink() or not marker.is_file():raise InstallError('legacy writer fence missing: '+name)
        raw=marker.read_bytes();value=json.loads(raw)
        if value.get('version')!=1 or value.get('R')!=packet['R'] or value.get('actor')!=packet['actor'] \
           or value.get('target')!=packet['target'] or value.get('writers')!=roots \
           or value.get('head')!=packet['target_head']:
            raise InstallError('legacy writer fence binding changed: '+name)
        receipt=value.get('packet_sha256')
        if receipt!=packet_hash \
           or git(root,'config','--local','--get','overgate.beadsLegacyFence').decode().strip()!=receipt:
            raise InstallError('legacy writer fence config changed: '+name)
        state_path=root/STATE
        if not state_path.is_file() or state_path.is_symlink() \
           or state_path.read_bytes()!=git(root,'show','HEAD:'+STATE) \
           or git(root,'status','--porcelain','--untracked-files=no','--',STATE,*LEGACY_FENCE_CLOSURE).strip():
            raise InstallError('legacy writer installed state/closure drift: '+name)
        state=json.loads(state_path.read_bytes())
        if state.get('beads') is not True or state.get('beads_protocol')!='legacy-v0' \
           or not isinstance(state.get('installed'),dict):
            raise InstallError('legacy writer installed state/closure invalid: '+name)
        pins=value.get('helper_sha256')
        if not isinstance(pins,dict) or set(pins)!=set(LEGACY_FENCE_HELPERS):
            raise InstallError('legacy writer helper fence incomplete: '+name)
        for helper in LEGACY_FENCE_CLOSURE:
            expected=pins.get(helper) if helper in LEGACY_FENCE_HELPERS else None
            file=root/helper
            if not helper.startswith('scripts/') or not file.is_file() or file.is_symlink() \
               or digest(file.read_bytes())!=digest(git(root,'show','HEAD:'+helper)) \
               or state['installed'].get(helper,{}).get('sha256')!=digest(file.read_bytes()) \
               or (expected is not None and digest(file.read_bytes())!=expected):
                raise InstallError('legacy writer helper fence drift: '+name+'/'+helper)
        receipts.append({'root':name,'sha256':digest(raw)})
    return receipts

def observable_mode(mode):
    # Native Windows показывает только read-only, а не Git executable bit.
    return (0o666 if mode & 0o200 else 0o444) if sys.platform=='win32' else mode

def projected_entries(manifest,beads):
    return [e for e in manifest['files'] if beads or e.get('component')!='beads']

def validate_payload(manifest,payload,beads=True):
    # Validate the projected install from frozen bytes, not the source tree where an
    # omitted manifest dependency may still exist. No target/backup writes here.
    with tempfile.TemporaryDirectory(prefix='overgate-preflight-') as directory:
        root=Path(directory)
        for entry in projected_entries(manifest,beads):
            path=safe(root,entry['target']);data,mode=payload[entry['source']]
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(mode)
        checker=root/'scripts/check-reference.py'
        if not checker.is_file():raise InstallError('missing payload checker: scripts/check-reference.py')
        result=subprocess.run([sys.executable,'-I','-B',str(checker),'--root',str(root)]+([] if beads else ['--no-beads']),
                              cwd=root,capture_output=True,text=True,env=git_environment())
        if result.returncode:
            raise InstallError('payload preflight failed: '+(result.stdout+result.stderr).strip())

def load_manifest(source,sha,beads=True):
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
    validate_payload(m,payload,beads)
    return m,payload

def merge_settings(existing,new,legacy,previous_rc=None,clean_codex=False):
    if existing is None:return new
    try:before=json.loads(existing);original=json.loads(existing);after=json.loads(new)
    except ValueError as e:raise InstallError('conflict: runtime settings must be valid JSON') from e
    if clean_codex and isinstance(before.get('permissions'),dict) and before['permissions'].get('deny')==[]:
        del before['permissions']['deny']
        if not before['permissions']:del before['permissions']
    old_entries=legacy.get('hooks',{}).get('PreToolUse',[])+(previous_rc or {}).get('hooks',{}).get('PreToolUse',[])
    managed_names=('pre-bash.sh','check-repository-mutation.py','check-tests-before-commit.sh','check-merge-ready.py')
    kept=[]
    for entry in before.get('hooks',{}).get('PreToolUse',[]):
        if entry in old_entries or entry in after['hooks']['PreToolUse']:continue
        if any(name in json.dumps(entry) for name in managed_names):
            raise InstallError('conflict: custom managed runtime hook; resolve in target PR')
        kept.append(entry)
    before.setdefault('hooks',{})['PreToolUse']=kept+after['hooks']['PreToolUse']
    # Env, SessionStart, project permissions и прочие overrides остаются; required deny дополняет их.
    for field in ('deny',):
        # permissions и его поля создаются, только если они есть в source: Codex adapter их не имеет.
        if field not in after.get('permissions',{}):continue
        values=before.setdefault('permissions',{}).setdefault(field,[])
        for value in after['permissions'][field]:
            if value not in values:values.append(value)
    # Правило записи: 1) равно source → байты source; 2) равно target → байты target;
    # 3) иначе детерминированная сериализация в порядке ключей target.
    merged=canonical(before)
    if merged==canonical(after):return new
    if merged==canonical(original):return existing
    return settings_bytes(before)

def claude_variant(data,mode):
    if mode=='auto':return data
    changed,count=re.subn(rb'("defaultMode"\s*:\s*)"auto"',rb'\1"bypassPermissions"',data)
    if count!=1:raise InstallError('source defaultMode must be auto exactly once')
    return changed

def select_claude(existing,new,manifest,requested,notes):
    if existing is None:return claude_variant(new,requested or 'auto'),requested or 'auto'
    old=json.loads(existing)
    fingerprint=digest(canonical(old).encode('utf-8'))
    known=manifest.get('known_settings_fingerprints',{})
    if fingerprint not in known:
        if requested:raise InstallError('режим проекта со своими settings меняется вручную в target PR')
        notes.append('permissions проекта сохранены')
        return merge_settings(existing,new,manifest.get('legacy_settings',{}),manifest.get('previous_rc_settings',{})),'custom'
    prior=known[fingerprint]
    mode=requested or (prior if prior in ('auto','bypass') else 'auto')
    desired=claude_variant(new,mode)
    if canonical(old)!=canonical(json.loads(desired)):
        notes.append('смена режима: '+str(old.get('permissions',{}).get('defaultMode'))+' → '+mode)
    return desired,mode

def render_agents(data,beads):
    if beads:return data
    return re.sub(rb'<!-- overgate:beads -->.*?<!-- /overgate:beads -->\r?\n?',b'',data,flags=re.S)

FRAGMENT_HEADER='# OverGate personal state (managed fragment)'

def split_lines(text):
    # Граница строки — только '\n'; каждая строка хранит свой EOL, чтобы сохранить байты.
    parts=text.split('\n')
    return [x+'\n' for x in parts[:-1]]+([parts[-1]] if parts[-1] else [])

def line_body(line):
    # Сравнение без учёта EOL: CRLF и LF равны, отсутствие EOL у последней строки тоже.
    line=line[:-1] if line.endswith('\n') else line
    return line[:-1] if line.endswith('\r') else line

def merge_gitignore(existing,fragment):
    # Таблица §4.1: сначала удаляется legacy-строка `.codex/`, затем ищется блок фрагмента.
    lines=[x for x in split_lines(existing.decode('utf-8')) if line_body(x).strip()!='.codex/']
    block=[line_body(x) for x in split_lines(fragment.decode('utf-8'))]
    bodies=[line_body(x) for x in lines];size=len(block)
    starts=[i for i in range(len(lines)-size+1) if bodies[i:i+size]==block]
    covered={j for i in starts for j in range(i,i+size)}
    # Заголовок вне целого блока — изменённый проектом фрагмент: решение за target PR.
    if any(body.strip()==FRAGMENT_HEADER and i not in covered for i,body in enumerate(bodies)):
        raise InstallError('conflict: managed .gitignore fragment modified; resolve in target PR')
    if starts:
        # Повторные целые блоки удаляются, первый и прочие байты остаются как есть.
        repeated={j for i in starts[1:] for j in range(i,i+size)}
        return ''.join(x for i,x in enumerate(lines) if i not in repeated).encode('utf-8')
    kept=''.join(lines)
    if not kept:return fragment
    ended=[x for x in lines if x.endswith('\n')]
    eol='\r\n' if ended and all(x.endswith('\r\n') for x in ended) else '\n'
    if not kept.endswith('\n'):kept+=eol
    return (kept+eol+''.join(body+eol for body in block)).encode('utf-8')

def make_plan(source,sha,target,contract,target_pr,mode=None,no_beads=False,preservation=None,switch_managed=False):
    requested_mode=mode
    source=source.resolve();target=target.resolve();contract=contract.resolve()
    if source==target:raise InstallError('source and target must be separate checkouts')
    if not re.fullmatch(r'https://[^/]+/[^/]+/[^/]+/pull/[1-9][0-9]*',target_pr):raise InstallError('target Draft PR URL required')
    git(target,'rev-parse','--show-toplevel')
    branch=git(target,'branch','--show-current').decode().strip()
    if not branch or branch in {'main','master'}:raise InstallError('target must be a named working branch')
    if not contract.is_file() or not contract.read_bytes().strip():raise InstallError('Verification Contract required')
    state={}
    state_exists=safe(target,STATE).exists()
    if state_exists:
        state=json.loads((target/STATE).read_text(encoding='utf-8'))
        if not isinstance(state,dict):raise InstallError('invalid install-state object; refuse unknown prior installation')
    beads=state.get('beads') is not False
    if state_exists and no_beads and beads:raise InstallError('смена режима Beads при upgrade запрещена')
    if not state_exists:beads=not no_beads
    prior_protocol=state.get('beads_protocol', 'legacy-v0' if beads else 'none') if state_exists else None
    protocol=prior_protocol if state_exists else ('legacy-v0' if preservation and beads else 'managed-v1' if beads else 'none')
    if protocol not in ('managed-v1','legacy-v0','none') or (protocol=='none')!= (not beads):
        raise InstallError('invalid Beads protocol in previous install-state')
    inventory=beads_inventory(target)
    packet=preservation_packet(target,inventory,Path(preservation)) if preservation else None
    if packet and (not beads or prior_protocol!='legacy-v0' or not inventory['blocked']):
        raise InstallError('preservation packet applies only to an existing legacy-v0 Beads target')
    fences=None
    if switch_managed:
        if not packet or packet['outcome']!='verified-clean' or not state_exists or prior_protocol!='legacy-v0':
            raise InstallError('explicit managed switch requires clean reviewed legacy preservation')
        fences=verified_legacy_fences(packet['path'])
        protocol='managed-v1'
    m,payload=load_manifest(source,sha,beads)
    previous=state.get('installed',{})
    operations=[];conflicts=[];notes=[];agent_mode='auto'
    for entry in projected_entries(m,beads):
        path=entry['target'];p=safe(target,path);old=current(target,path);data,mode=payload[entry['source']]
        if entry['source']=='.agents/templates/AGENTS.template.md':data=render_agents(data,beads)
        policy=entry.get('policy','managed')
        if policy=='preserve' and old is not None:continue
        if policy=='ignore':
            try:data=merge_gitignore(p.read_bytes() if old else b'',data)
            except InstallError as e:conflicts.append(f'{path}: {e}');continue
        elif policy=='settings':
            legacy=m.get('legacy_settings',{});previous_rc=m.get('previous_rc_settings',{})
            if path=='.codex/hooks.json':
                legacy={};previous_rc=m.get('previous_rc_codex_settings',{})
            try:
                if path=='.claude/settings.json':data,agent_mode=select_claude(p.read_bytes() if old else None,data,m,requested_mode,notes)
                else:data=merge_settings(p.read_bytes() if old else None,data,legacy,previous_rc,clean_codex=True)
            except InstallError as e:
                if requested_mode is not None and path=='.claude/settings.json':raise
                conflicts.append(f'{path}: {e}');continue
        elif old is not None and old['sha256']!=digest(data):
            prior=previous.get(path,{}).get('sha256')
            blob=git(target,'hash-object',str(p)).decode().strip()
            if old['sha256']!=prior and blob!=m.get('legacy_blobs',{}).get(path):
                conflicts.append(path+': conflict with project override; no force overwrite');continue
        operations.append({'source':entry['source'],'target':path,'before':old,'after':{'sha256':digest(data),'mode':observable_mode(mode)},
                           'data':base64.b64encode(data).decode() if policy in {'settings','ignore'} or (entry['source']=='.agents/templates/AGENTS.template.md' and not beads) else None})
    return {'format':1,'source':str(source),'source_sha':sha,'target':str(target),'branch':branch,
            'target_pr':target_pr,'contract':str(contract),'contract_sha256':digest(contract.read_bytes()),
            'mode':agent_mode,'requested_mode':requested_mode,'beads':beads,'beads_protocol':protocol,
            'beads_inventory':inventory,'preservation':packet,'switch_managed':switch_managed,
            'legacy_fences':fences,'no_beads':no_beads,'notes':notes,'manifest_version':m['version'],
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
    now=make_plan(Path(plan['source']),plan['source_sha'],Path(plan['target']),Path(plan['contract']),plan['target_pr'],
                  plan.get('requested_mode'),plan.get('no_beads',False),
                  plan.get('preservation',{}).get('path') if plan.get('preservation') else None,plan.get('switch_managed',False))
    if now!=plan:raise InstallError('target/source plan drift after Plan Review; regenerate plan in same PR')
    if plan['conflicts']:raise InstallError('conflicts require explicit project resolution: '+'; '.join(plan['conflicts']))
    if plan['beads_inventory']['blocked'] and not plan['preservation']:
        raise InstallError('Beads preservation required before install: '+'; '.join(plan['beads_inventory']['reasons']))
    root=Path(plan['target']);_,payload=load_manifest(Path(plan['source']),plan['source_sha'],plan['beads'])
    if (root/'.overgate-backups').is_symlink():raise InstallError('symlink backup directory')
    backup=root/'.overgate-backups'/uuid.uuid4().hex
    backup.mkdir(parents=True)
    entries=[]
    for operation in plan['operations']+[{'target':STATE,'before':plan['state_before']}]:
        path=operation['target'];p=safe(root,path)
        entries.append({'target':path,'before':operation['before'],'data':base64.b64encode(p.read_bytes()).decode() if p.exists() else None})
    journal={'format':1,'target':str(root),'source_sha':plan['source_sha'],'plan_sha256':digest(raw),'entries':entries,
             'switch_managed':plan.get('switch_managed',False),'legacy_R':plan.get('preservation',{}).get('R') if plan.get('preservation') else None,
             'after':{},'complete':False}
    backup_file=backup/'rollback.json';backup_file.write_bytes(json_bytes(journal))
    # Все before bytes сохранены ДО первой target mutation; повторная проверка закрывает preflight race.
    if any(current(root,x['target'])!=x['before'] for x in entries):raise InstallError('target drift before first write')
    try:
        for op in plan['operations']:
            data=base64.b64decode(op['data']) if op['data'] is not None else payload[op['source']][0]
            if digest(data)!=op['after']['sha256']:raise InstallError('payload fingerprint mismatch')
            write_atomic(root,op['target'],data,op['after']['mode'])
        installed={op['target']:op['after'] for op in plan['operations']}
        state={'format':2,'source_sha':plan['source_sha'],'manifest_version':plan['manifest_version'],
               'mode':plan['mode'],'beads':plan['beads'],'beads_protocol':plan['beads_protocol'],'installed':installed}
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
    state_path=safe(root,STATE)
    if state_path.is_file():
        state=json.loads(state_path.read_bytes())
        if state.get('beads_protocol')=='managed-v1':
            inventory=beads_inventory(root)
            if journal.get('switch_managed'):
                if inventory['remote']!={'status':'present','R':journal.get('legacy_R')}:
                    raise InstallError('rollback after published/unknown Beads state denied; preserve managed ledger and snapshot')
                fence=root/'.git/overgate-bd-legacy-fence.json'
                if fence.is_symlink() or not fence.is_file() or \
                   'git/overgate-bd-publisher-control' in inventory['local']:
                    raise InstallError('reviewed publisher setup/fence state must be resolved before rollback')
            else:
                if inventory['remote']['status']!='verified-absent':
                    raise InstallError('rollback after published/unknown Beads state denied; preserve managed ledger and snapshot')
                if inventory['blocked']:
                    raise InstallError('rollback with local Beads state requires preservation before removing managed helpers')
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
    p.add_argument('--mode',choices=('auto','bypass'));p.add_argument('--no-beads',action='store_true')
    p.add_argument('--preservation',type=Path)
    p.add_argument('--switch-managed',action='store_true')
    p=sub.add_parser('apply');p.add_argument('--plan',required=True,type=Path);p.add_argument('--approval',required=True,type=Path)
    p=sub.add_parser('rollback');p.add_argument('--target',required=True,type=Path);p.add_argument('--backup',required=True,type=Path)
    args=parser.parse_args()
    try:
        if args.command=='plan':
            plan=make_plan(args.source,args.source_sha,args.target,args.contract,args.target_pr,args.mode,args.no_beads,args.preservation,args.switch_managed)
            args.output.write_bytes(json_bytes(plan))
            for note in plan['notes']:print(note)
            print('Plan written; conflicts='+str(len(plan['conflicts']))+'; SHA256='+digest(args.output.read_bytes()))
        elif args.command=='apply':apply(args.plan,args.approval)
        else:rollback(args.target,args.backup)
    except (InstallError,OSError,ValueError,KeyError,TypeError) as e:
        print('STOP: '+str(e),file=sys.stderr);return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
