#!/usr/bin/env bash
# Единственная запись защиты в пакете; поручение установить подтверждает эту запись.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
"$ROOT/.claude/tools/run-python.sh" -I - "$ROOT" <<'PY'
import copy,json,re,shutil,subprocess,sys
from pathlib import Path
from urllib.parse import quote
root=Path(sys.argv[1])
write_attempted=False
def run(*args,data=None):return subprocess.run([shutil.which(args[0]) or args[0],*args[1:]],input=data,capture_output=True,text=True,encoding='utf-8')
def outcome(code,text):
    line='R8: protection code '+str(code)+' — '+text+'. Записать в target PR; '+('сверить правила ruleset' if code==5 else 'защита main helper-ом не подтверждена')+'.'
    if code==6 and write_attempted:line+=' Операция могла примениться; состояние защиты не подтверждено, STOP.'
    print(line)
    # Не создаём второй каркас и не следуем symlink к чужому context.
    p=root/'.memory-bank/progress.md'
    if code in (2,3,4,5) and (root/'.memory-bank').is_dir() and not (root/'.memory-bank').is_symlink() and p.is_file() and not p.is_symlink():
        content=p.read_text(encoding='utf-8')
        if line not in content:
            with p.open('a',encoding='utf-8',newline='') as stream:stream.write('\n'+line+'\n')
    raise SystemExit(code)
def api(endpoint,method=None,payload=None):
    args=['gh','api',endpoint]
    if method:args+=['--method',method,'--input','-']
    r=run(*args,data=json.dumps(payload) if payload is not None else None)
    try:value=json.loads(r.stdout)
    except ValueError:raise RuntimeError('invalid GitHub JSON: '+endpoint)
    if not isinstance(value,dict):raise RuntimeError('invalid GitHub response: '+endpoint)
    return r.returncode,value
def checked(endpoint):
    code,value=api(endpoint)
    if code:raise RuntimeError('GitHub read failed: '+endpoint+' '+str(value.get('message','')))
    return value
def tariff_unavailable(info,response):
    # Только известное тарифное тело private repo; ошибки auth/rate-limit не превращаются в skip.
    message=str(response.get('message','')).strip()
    return (info.get('private') is True and str(response.get('status'))=='403' and
            re.fullmatch(r'Upgrade to GitHub (?:Pro|Team) or make this repository public to enable this feature\.',message,re.I) is not None)
def enabled(value):return value is True or isinstance(value,dict) and value.get('enabled') is True
def identities(value):
    if value is None:return None
    return {kind:[x['login' if kind=='users' else 'slug'] if isinstance(x,dict) else x for x in value.get(kind,[])] for kind in ('users','teams','apps')}
def review_policy(reviews):
    if reviews is None:return None
    # Отсутствующий default и явный default эквивалентны; реальные ограничения не отбрасываются.
    out={key:reviews.get(key,False) for key in ('dismiss_stale_reviews','require_code_owner_reviews','require_last_push_approval')}
    if any(type(v) is not bool for v in out.values()):raise RuntimeError('invalid review boolean')
    count=reviews.get('required_approving_review_count',0)
    if type(count) is not int or not 0<=count<=6:raise RuntimeError('invalid approving review count')
    out['required_approving_review_count']=count
    for key in ('dismissal_restrictions','bypass_pull_request_allowances'):
        actors=identities(reviews.get(key))
        if actors is not None and any(actors.values()):out[key]=actors
    return out
def normalize(value):
    out={}
    status=value.get('required_status_checks')
    if status is None:out['required_status_checks']=None
    else:
        out['required_status_checks']={'strict':status['strict'],'contexts':status.get('contexts',[])}
        if 'checks' in status:out['required_status_checks']['checks']=[{'context':x['context'],**({'app_id':x['app_id']} if x.get('app_id') is not None else {'app_id':-1})} for x in status['checks']]
    out['required_pull_request_reviews']=review_policy(value.get('required_pull_request_reviews'))
    out['restrictions']=identities(value.get('restrictions'))
    for key in ('enforce_admins','allow_force_pushes','allow_deletions','required_linear_history','required_conversation_resolution','lock_branch','allow_fork_syncing','block_creations'):
        if key in value:out[key]=enabled(value[key])
    return out
def compliant(value):
    return isinstance(value.get('required_pull_request_reviews'),dict) and enabled(value.get('enforce_admins')) and value.get('allow_force_pushes',{}).get('enabled') is False and value.get('allow_deletions',{}).get('enabled') is False
try:
    try:auth=run('gh','auth','status')
    except FileNotFoundError:outcome(3,'пропущено: нет gh auth/CLI')
    if auth.returncode:outcome(3,'пропущено: нет gh auth')
    identity=run('gh','repo','view','--json','nameWithOwner','--jq','.nameWithOwner')
    repo=identity.stdout.strip()
    if identity.returncode or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise RuntimeError('repository identity unavailable')
    info=checked('repos/'+repo)
    if info.get('permissions',{}).get('admin') is not True:outcome(2,'нет прав admin')
    branch=info.get('default_branch')
    if not isinstance(branch,str) or not branch:raise RuntimeError('default branch unavailable')
    endpoint='repos/'+repo+'/branches/'+quote(branch,safe='')
    initial=checked(endpoint)
    if not isinstance(initial.get('protected'),bool):raise RuntimeError('branch protected field missing')
    rc,existing=api(endpoint+'/protection')
    if rc:
        if tariff_unavailable(info,existing):outcome(4,'недоступно на тарифе')
        if str(existing.get('status'))!='404':raise RuntimeError('classic protection unreadable')
        if initial['protected']:outcome(5,'защищено ruleset')
        if existing.get('message')!='Branch not protected':raise RuntimeError('unexpected protection 404')
        existing={}
    before=normalize(existing);desired=copy.deepcopy(before)
    desired.update(enforce_admins=True,allow_force_pushes=False,allow_deletions=False)
    if desired['required_pull_request_reviews'] is None:desired['required_pull_request_reviews']=review_policy({'required_approving_review_count':0})
    changed=not initial['protected'] or not compliant(existing)
    if changed:
        write_attempted=True
        rc,response=api(endpoint+'/protection','PUT',desired)
        if rc:
            message=str(response.get('message',''))
            if tariff_unavailable(info,response):outcome(4,'недоступно на тарифе')
            raise RuntimeError('protection PUT refused: '+message)
    final=checked(endpoint);actual=checked(endpoint+'/protection')
    normalized=normalize(actual)
    if final.get('protected') is not True or not compliant(actual) or any(normalized.get(k)!=v for k,v in desired.items()):raise RuntimeError('protection readback mismatch')
    # Signing rules живут в отдельном endpoint; PUT их не меняет, чтение обнаруживает потерю.
    if enabled(existing.get('required_signatures')) and not enabled(actual.get('required_signatures')):raise RuntimeError('required signatures lost on readback')
    print('Protection: verified '+repo+'/'+branch+(' updated' if changed else ' no-op')+'; evidence for target PR')
except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError) as error:
    outcome(6,'STOP: '+str(error))
PY
