#!/usr/bin/env bash
# Bootstrap только канонического checkout; generated hooks bd не заменяют OverGate guards.
set -euo pipefail
if [ -n "${GIT_INDEX_FILE:-}" ]; then
  echo 'STOP: GIT_INDEX_FILE override запрещён для Beads bootstrap; canonical Git index должен быть проверен.' >&2
  exit 1
fi
bootstrap_source_dir="${BASH_SOURCE[0]%/*}"
[ "$bootstrap_source_dir" = "${BASH_SOURCE[0]}" ] && bootstrap_source_dir=.
BOOTSTRAP_SCRIPT_DIR="$(cd "$bootstrap_source_dir" && pwd -P)"
. "$BOOTSTRAP_SCRIPT_DIR/lib/bd-env.sh"
bd_env_sanitize_git
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
. "$ROOT/scripts/lib/bd-env.sh"
if bd_env_legacy_fenced; then
  echo 'STOP: legacy writer fenced for reviewed managed cutover; bd-bootstrap disabled.' >&2
  exit 1
fi
bd_env_assert_main_checkout bd-bootstrap || exit 1
# bd init вызывает git commit и захватывает весь уже staged index, включая файлы проекта.
# До любой Beads-команды сохраняем границу коммита: staged файлы разбирает агент в PR.
if ! git diff --cached --quiet --; then
  echo 'STOP: Git index содержит staged файлы; bd init мог бы включить их в автоматический Beads commit. Сохраните и разберите staged изменения до bootstrap.' >&2
  exit 1
fi
# Env overrides не должны перенаправить единственный writer или запустить server вместо embedded.
if [ -n "${BEADS_DIR:-}${BEADS_DB:-}" ] || [ "${BEADS_DOLT_SERVER_MODE:-0}" = 1 ] || [ "${BEADS_DOLT_PROXIED_SERVER:-0}" = 1 ] || [ "${BEADS_DOLT_SHARED_SERVER:-0}" = 1 ] || [ "${BEADS_DOLT_SHARED_SERVER:-}" = true ]; then
  echo 'STOP: Beads database/server environment override; expected main embedded checkout.' >&2
  exit 1
fi
if ! command -v bd >/dev/null 2>&1; then
  echo 'STOP: нужен bd 1.2.2. Агент устанавливает по инструкции ОС: https://github.com/gastownhall/beads#installation (macOS/Linux/Windows Git Bash). Helper ничего не скачивает.' >&2
  exit 1
fi
# Existing server допустим только живой; эта каноническая проба не запускает bd/server.
if [ -e "$ROOT/.beads/metadata.json" ] && { [ -e "$ROOT/.beads/embeddeddolt" ] || [ -e "$ROOT/.beads/dolt" ]; }; then
  bd_env_resolve_main_db "$ROOT" || { echo 'STOP: existing Beads database unavailable; no auto-start/overwrite.' >&2; exit 1; }
fi
# og-4py (ADR §3.39): сетевые вызовы Python-части получают обычный вход пользователя через
# приватный файл переноса; путь передаётся аргументом, не окружением, поэтому дочерние
# bd-sync-*.sh его не наследуют и готовят свой. Файл удаляет EXIT-ловушка этого shell.
bd_env_network_prepare "$ROOT" || { echo 'STOP: network Git environment unavailable (fail-closed).' >&2; exit 1; }
"$ROOT/.claude/tools/run-python.sh" -I - "$ROOT" "$BD_ENV_NETWORK_CONFIG" <<'PY'
import hashlib,json,os,re,shutil,stat,subprocess,sys,tempfile
from pathlib import Path
root=Path(sys.argv[1])
network_config=sys.argv[2]
def call(*args,env=None):
    r=subprocess.run([shutil.which(args[0]) or args[0],*args[1:]],capture_output=True,text=True,encoding='utf-8',env=env)
    if r.returncode:raise RuntimeError('command failed: '+' '.join(args[:4])+'; '+r.stderr.strip())
    return r.stdout
def net(*args):return call('git',*args,env=dict(os.environ,GIT_CONFIG_GLOBAL=network_config,GIT_CONFIG_NOSYSTEM='1'))
def bash_command():
    if os.name!='nt':return 'bash'
    candidates=[Path(p)/'bash.exe' for p in os.environ.get('PATH','').split(os.pathsep)]
    candidates += [Path('C:/Program Files/Git/usr/bin/bash.exe'),Path('C:/Program Files/Git/bin/bash.exe')]
    for p in candidates:
        if p.is_file() and 'system32' not in str(p).lower():return str(p)
    raise RuntimeError('native Git Bash required; WSL unsupported')
def bd(*args):return call('bd','--sandbox',*args)
def value(key):
    v=json.loads(bd('config','get',key,'--json'))
    if v.get('key')!=key or not isinstance(v.get('value'),str):raise RuntimeError('invalid config response '+key)
    return v['value']
def remotes():
    v=json.loads(bd('dolt','remote','list','--json'))
    if not isinstance(v,list) or any(not isinstance(x,dict) or not re.fullmatch(r'[A-Za-z0-9_.-]+',x.get('name','')) for x in v):raise RuntimeError('invalid Dolt remote response')
    return v
def postcondition():
    metadata=json.loads((root/'.beads/metadata.json').read_text(encoding='utf-8'))
    mode=metadata.get('dolt_mode')
    path={'embedded':'embeddeddolt','server':'dolt'}.get(mode)
    if path is None or not (root/'.beads'/path).is_dir():raise RuntimeError('invalid existing database mode/path; no overwrite')
    if value('export.auto')!='false' or value('backup.git-push')!='false' or value('sync.remote')!='' or remotes():raise RuntimeError('unsafe existing Beads config; no overwrite')
    if not isinstance(json.loads(bd('ready','--json')),list):raise RuntimeError('bd ready invalid JSON')
def fresh_prefix(name):
    # Имя задачи проходит и bd DB identifier, и неизменённую Beads ID грамматику gate.
    slug=re.sub(r'[^A-Za-z0-9-]+','-',name).strip('-')
    if not slug:slug='project-'+hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]
    if not slug[0].isalpha() or len(slug)<2:slug='p-'+slug
    return slug
def pin_fresh_prefix(prefix):
    # Только после нового пустого init; существующую конфигурацию другого проекта не переписываем.
    config=root/'.beads/config.yaml'
    if config.is_symlink() or not config.is_file():raise RuntimeError('fresh init config.yaml missing or unsafe')
    original=config.read_bytes()
    if re.search(rb'(?m)^\s*issue-prefix\s*:',original):
        raise RuntimeError('fresh init has pre-existing active issue-prefix; no rewrite')
    effective=json.loads(bd('config','list','--json'))
    if not isinstance(effective,dict) or effective.get('issue_prefix')!=prefix or value('issue_prefix')!=prefix:
        raise RuntimeError('fresh init effective issue prefix mismatch')
    with tempfile.TemporaryDirectory(prefix='overgate-bd-empty-') as tmp:
        exported=Path(tmp)/'empty.jsonl';bd('export','--all','-o',str(exported))
        if exported.read_bytes():raise RuntimeError('fresh init contains task state; no config pin')
    pinned=original+(b'' if original.endswith(b'\n') else b'\n')+('issue-prefix: '+json.dumps(prefix)+'\n').encode('utf-8')
    temporary=config.with_name(config.name+'.overgate-pin-tmp')
    try:
        with temporary.open('xb') as output:
            output.write(pinned);output.flush();os.fsync(output.fileno())
        os.chmod(temporary,stat.S_IMODE(config.stat().st_mode))
        os.replace(temporary,config)
    finally:
        if temporary.exists():temporary.unlink()
    if value('issue_prefix')!=prefix or config.read_bytes()!=pinned:
        raise RuntimeError('fresh issue prefix pin read-back mismatch; no publication')
def clone_recovery():
    beads=root/'.beads'
    if os.environ.get('BD_SYNC_FORCE') or os.environ.get('BD_SYNC_REMOTE','origin')!='origin' or os.environ.get('BD_SYNC_BRANCH','beads-backup')!='beads-backup':
        raise RuntimeError('fresh clone refuses force or noncanonical sync route')
    metadata_path=beads/'metadata.json';config_path=beads/'config.yaml'
    for name in ('metadata.json','config.yaml'):
        if call('git','ls-files','--error-unmatch','--','.beads/'+name).strip()!='.beads/'+name:
            raise RuntimeError('fresh clone requires tracked .beads/'+name)
    allowed={'metadata.json','config.yaml','.gitignore','README.md','interactions.jsonl'}
    if any(p.name not in allowed or p.is_symlink() or not p.is_file() for p in beads.iterdir()):
        raise RuntimeError('fresh clone has unknown/local Beads state; no init or restore')
    if call('git','status','--porcelain','--','.beads',env=dict(os.environ,GIT_OPTIONAL_LOCKS='0')).strip():
        raise RuntimeError('fresh clone has modified Beads files; no init or restore')
    intents=root/'.bd-intents'
    if intents.exists() and any(intents.rglob('*.jsonl')):
        raise RuntimeError('fresh clone has pending intents; no init or restore')
    seen=subprocess.run(['git','config','--local','--get','beads-sync.lastSeen'],capture_output=True,text=True,encoding='utf-8')
    if seen.returncode not in (0,1) or seen.stdout.strip():
        raise RuntimeError('fresh clone has prior sync state; no init or restore')
    metadata_bytes=metadata_path.read_bytes();config_bytes=config_path.read_bytes()
    metadata=json.loads(metadata_bytes)
    if not isinstance(metadata,dict) or metadata.get('backend')!='dolt' or metadata.get('dolt_mode')!='embedded' or not isinstance(metadata.get('project_id'),str) or not metadata['project_id'] or not isinstance(metadata.get('dolt_database'),str) or not metadata['dolt_database']:
        raise RuntimeError('fresh clone metadata mode/project_id invalid; no init')
    active=[]
    for line in config_bytes.decode('utf-8').splitlines():
        match=re.fullmatch(r'issue-prefix:\s*([^#]*?)(?:\s+#.*)?',line)
        if match:
            prefix_value=match[1].strip().strip('"\'')
            active.append(prefix_value)
    if len(active)>1 or active and not active[0]:
        raise RuntimeError('tracked issue-prefix ambiguous')
    if not active:
        raise RuntimeError('active project-owned tracked issue-prefix required; caller receipt/SHA and clone/database names are not provenance')
    expected=os.environ.get('BD_BOOTSTRAP_PREFIX','')
    if os.environ.get('BD_BOOTSTRAP_PREFIX_RECEIPT') or os.environ.get('BD_BOOTSTRAP_PREFIX_RECEIPT_SHA256'):
        raise RuntimeError('caller receipt/SHA route removed; use tracked project issue-prefix')
    prefix=active[0]
    if expected and expected!=prefix:raise RuntimeError('explicit prefix differs from tracked project config')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]+',prefix):
        raise RuntimeError('verified issue prefix invalid')
    expected_r=os.environ.get('BD_BOOTSTRAP_EXPECTED_R','')
    if expected_r and not re.fullmatch(r'[0-9a-f]{40}',expected_r):
        raise RuntimeError('expected beads-backup SHA invalid')
    def remote_tip():
        remote=net('ls-remote','--exit-code','--heads','origin','refs/heads/beads-backup').strip()
        match=re.fullmatch(r'([0-9a-f]{40})\s+refs/heads/beads-backup',remote)
        if not match:raise RuntimeError('frozen beads-backup SHA unavailable')
        return match[1]
    base=remote_tip()
    if expected_r and base!=expected_r:
        raise RuntimeError('frozen beads-backup SHA missing or advanced; no init')
    if net('ls-remote','origin','refs/dolt/data').strip():
        raise RuntimeError('unexpected Dolt remote history; no JSONL clone init')
    net('fetch','-q','origin','+refs/heads/beads-backup:refs/remotes/origin/beads-backup')
    if call('git','rev-parse','refs/remotes/origin/beads-backup').strip()!=base:
        raise RuntimeError('beads-backup changed during fetch; no init')
    snapshot=call('git','show',base+':.beads/issues.jsonl')
    issues=[];rows=[]
    for line in snapshot.splitlines():
        if not line.strip():continue
        row=json.loads(line)
        if not isinstance(row,dict):raise RuntimeError('published snapshot row invalid')
        if row.get('_type') not in ('issue','memory'):
            raise RuntimeError('published snapshot row type unsupported')
        if row['_type']=='issue':
            issue_id=row.get('id')
            if not isinstance(issue_id,str) or not issue_id.startswith(prefix+'-') or not isinstance(row.get('title'),str) or not row['title'] or not isinstance(row.get('status'),str) or not isinstance(row.get('issue_type'),str) or type(row.get('priority')) is not int:
                raise RuntimeError('published snapshot namespace differs from verified prefix')
            issues.append(issue_id)
        rows.append(row)
    if not issues and snapshot:raise RuntimeError('published snapshot has no issue namespace to verify')
    if len(issues)!=len(set(issues)):raise RuntimeError('published snapshot has duplicate issue ID')
    edge_types={'blocks','tracks','related','parent-child','discovered-from','until','caused-by','validates','relates-to','supersedes'}
    for row in rows:
        if row['_type']!='issue':continue
        edges=row.get('dependencies',[])
        if not isinstance(edges,list):raise RuntimeError('published snapshot dependency list invalid')
        for edge in edges:
            if not isinstance(edge,dict) or edge.get('issue_id')!=row['id'] or edge.get('type') not in edge_types or not isinstance(edge.get('depends_on_id'),str):
                raise RuntimeError('published snapshot dependency edge invalid')
            target=edge['depends_on_id']
            if target.startswith(prefix+'-') and target not in issues:
                raise RuntimeError('published snapshot dependency target missing')
    git_dir=Path(call('git','rev-parse','--path-format=absolute','--git-dir').strip())
    if (git_dir/'bd-receipts').exists():raise RuntimeError('fresh clone has pending Beads receipts')
    index_path=Path(call('git','rev-parse','--path-format=absolute','--git-path','index').strip())
    index_bytes=index_path.read_bytes();head=call('git','rev-parse','HEAD').strip()
    def unchanged():
        changed=[]
        if metadata_path.read_bytes()!=metadata_bytes:changed.append('metadata')
        if config_path.read_bytes()!=config_bytes:changed.append('config')
        if index_path.read_bytes()!=index_bytes:changed.append('index')
        if call('git','rev-parse','HEAD').strip()!=head:changed.append('HEAD')
        if changed:raise RuntimeError('tracked '+','.join(changed)+' changed during clone restore; stop')
    if remote_tip()!=base:
        raise RuntimeError('beads-backup advanced before init')
    # bd init может переписать Git index даже без нового commit; отдельный индекс
    # сохраняет исходные staged/stat bytes до и после восстановления.
    with tempfile.TemporaryDirectory(prefix='overgate-bd-init-') as tmp:
        isolated_index=Path(tmp)/'index';isolated_index.write_bytes(index_bytes)
        call('bd','--sandbox','init','--skip-agents','--skip-hooks','--non-interactive','--remote','','--prefix',prefix,
             env=dict(os.environ,GIT_INDEX_FILE=str(isolated_index)))
    unchanged()
    if value('issue_prefix')!=prefix or remotes():raise RuntimeError('fresh clone prefix or Dolt remote mismatch after init')
    restore_env=dict(os.environ,BD_SYNC_EXPECTED_SHA=base)
    call(bash_command(),'scripts/bd-sync-restore.sh',env=restore_env)
    unchanged()
    if value('issue_prefix')!=prefix or remotes() or value('export.auto')!='false' or value('backup.git-push')!='false' or value('sync.remote')!='':
        raise RuntimeError('fresh clone Beads configuration differs after restore')
    if call('git','config','--local','--get','beads-sync.lastSeen').strip()!=base:
        raise RuntimeError('fresh clone lastSeen mismatch')
    if remote_tip()!=base:
        raise RuntimeError('beads-backup advanced during restore; local state retained, no publish')
    with tempfile.TemporaryDirectory(prefix='overgate-bd-readback-') as tmp:
        exported=Path(tmp)/'snapshot.jsonl';bd('export','--all','-o',str(exported))
        def normalized(raw):return sorted((json.loads(line) for line in raw.splitlines() if line.strip()),key=lambda row:json.dumps(row,sort_keys=True))
        if normalized(exported.read_text(encoding='utf-8'))!=normalized(snapshot):
            raise RuntimeError('fresh clone full-object readback differs from frozen snapshot')
    print('Beads clone restored: '+base+'; issue prefix '+prefix+'; '+str(len(issues))+' issues; no publication')
publication=False
try:
    if (root/'.beads').is_symlink() or (root/'.beads/metadata.json').is_symlink():raise RuntimeError('unsafe Beads symlink')
    if (root/'.beads').exists() and not (root/'.beads/metadata.json').exists():raise RuntimeError('partial existing .beads; no overwrite')
    manifest=json.loads((root/'.agents/distribution-manifest.json').read_text(encoding='utf-8'))
    supported=manifest['beads_version'];version=call('bd','--version').strip()
    match=re.fullmatch(r'bd version (\d+\.\d+\.\d+)(?: \([^\n]*\))?',version)
    def parts(v):return tuple(map(int,v.split('.')))
    if not match or not (parts(supported['min'])<=parts(match[1])<parts(supported['max_exclusive'])):raise RuntimeError('supported bd '+supported['min']+' only; install exact version for OS: https://github.com/gastownhall/beads/releases/tag/v1.2.2')
    if (root/'.beads/metadata.json').exists() and not (root/'.beads/embeddeddolt').exists() and not (root/'.beads/dolt').exists():
        clone_recovery();sys.exit(0)
    if not (root/'.beads/metadata.json').exists():
        # --remote '' исключает авто-Dolt origin; sandbox блокирует побочную auto-push публикацию.
        if net('ls-remote','--heads','origin','beads-backup').strip() or net('ls-remote','origin','refs/dolt/data').strip():
            raise RuntimeError('remote Beads state exists; fresh init would create competing local state')
        prefix=fresh_prefix(root.name)
        init_args=['init','--skip-agents','--skip-hooks','--non-interactive','--remote','']
        if prefix!=root.name:init_args+=['--prefix',prefix]
        print('Beads fresh prefix: '+prefix)
        bd(*init_args)
        if json.loads((root/'.beads/metadata.json').read_text(encoding='utf-8')).get('dolt_mode')!='embedded':raise RuntimeError('fresh init must be embedded; no export')
        bd('config','set','export.auto','false');bd('config','set','backup.git-push','false')
        bd('config','unset','sync.remote')
        for remote in remotes():bd('dolt','remote','remove',remote['name'])
        pin_fresh_prefix(prefix)
    postcondition()
    published=net('ls-remote','--heads','origin','beads-backup').strip()
    if published:
        seen=subprocess.run(['git','config','--local','--get','beads-sync.lastSeen'],capture_output=True,text=True,encoding='utf-8')
        if seen.returncode not in (0,1) or not seen.stdout.strip():
            raise RuntimeError('existing local database has published snapshot but no lastSeen; pending/divergent state retained, no automatic restore')
    if not published:
        publication=True
        call(bash_command(),'scripts/bd-sync-export.sh')
    postcondition()
    if not net('ls-remote','--heads','origin','beads-backup').strip():raise RuntimeError('origin/beads-backup missing after export')
    print('Beads: ready; origin/beads-backup exists')
except (OSError,ValueError,KeyError,TypeError,RuntimeError) as error:
    print('STOP: '+str(error)+('; publication may already have occurred; inspect remote, no automatic rollback' if publication else '; snapshot not published by bootstrap'),file=sys.stderr)
    sys.exit(1)
PY
