#!/usr/bin/env bash
# Bootstrap только канонического checkout; generated hooks bd не заменяют OverGate guards.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
. "$ROOT/scripts/lib/bd-env.sh"
bd_env_assert_main_checkout bd-bootstrap || exit 1
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
if [ -e "$ROOT/.beads/metadata.json" ]; then
  bd_env_resolve_main_db "$ROOT" || { echo 'STOP: existing Beads database unavailable; no auto-start/overwrite.' >&2; exit 1; }
fi
"$ROOT/.claude/tools/run-python.sh" -I - "$ROOT" <<'PY'
import hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1])
def call(*args):
    r=subprocess.run([shutil.which(args[0]) or args[0],*args[1:]],capture_output=True,text=True,encoding='utf-8')
    if r.returncode:raise RuntimeError('command failed: '+' '.join(args[:4])+'; '+r.stderr.strip())
    return r.stdout
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
publication=False
try:
    if (root/'.beads').is_symlink() or (root/'.beads/metadata.json').is_symlink():raise RuntimeError('unsafe Beads symlink')
    if (root/'.beads').exists() and not (root/'.beads/metadata.json').exists():raise RuntimeError('partial existing .beads; no overwrite')
    manifest=json.loads((root/'.agents/distribution-manifest.json').read_text(encoding='utf-8'))
    supported=manifest['beads_version'];version=call('bd','--version').strip()
    match=re.fullmatch(r'bd version (\d+\.\d+\.\d+)(?: \([^\n]*\))?',version)
    def parts(v):return tuple(map(int,v.split('.')))
    if not match or not (parts(supported['min'])<=parts(match[1])<parts(supported['max_exclusive'])):raise RuntimeError('supported bd '+supported['min']+' only; install exact version for OS: https://github.com/gastownhall/beads/releases/tag/v1.2.2')
    if not (root/'.beads/metadata.json').exists():
        # --remote '' исключает авто-Dolt origin; sandbox блокирует побочную auto-push публикацию.
        prefix=fresh_prefix(root.name)
        init_args=['init','--skip-agents','--skip-hooks','--non-interactive','--remote','']
        if prefix!=root.name:init_args+=['--prefix',prefix]
        print('Beads fresh prefix: '+prefix)
        bd(*init_args)
        if json.loads((root/'.beads/metadata.json').read_text(encoding='utf-8')).get('dolt_mode')!='embedded':raise RuntimeError('fresh init must be embedded; no export')
        bd('config','set','export.auto','false');bd('config','set','backup.git-push','false')
        bd('config','unset','sync.remote')
        for remote in remotes():bd('dolt','remote','remove',remote['name'])
    postcondition()
    if not call('git','ls-remote','--heads','origin','beads-backup').strip():
        publication=True
        call(bash_command(),'scripts/bd-sync-export.sh')
    postcondition()
    if not call('git','ls-remote','--heads','origin','beads-backup').strip():raise RuntimeError('origin/beads-backup missing after export')
    print('Beads: ready; origin/beads-backup exists')
except (OSError,ValueError,KeyError,TypeError,RuntimeError) as error:
    print('STOP: '+str(error)+('; publication may already have occurred; inspect remote, no automatic rollback' if publication else '; snapshot not published by bootstrap'),file=sys.stderr)
    sys.exit(1)
PY
