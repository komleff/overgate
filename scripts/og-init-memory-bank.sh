#!/usr/bin/env bash
# Существующий контекст принадлежит проекту, даже если каркас неполный.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PYTHON="$ROOT/.claude/tools/run-python.sh"
"$PYTHON" -I - "$ROOT" <<'PY'
from pathlib import Path
import os,shutil,sys,tempfile
root=Path(sys.argv[1]);dest=root/'.memory-bank'
names=('projectbrief','productContext','systemPatterns','techContext','activeContext','progress')
if dest.is_symlink():raise SystemExit('STOP: .memory-bank symlink')
if dest.exists():
    if not dest.is_dir():raise SystemExit('STOP: .memory-bank is not directory')
    missing=[n+'.md' for n in names if not (dest/(n+'.md')).is_file()]
    print('Memory Bank: no-op; missing: '+(', '.join(missing) or 'none'))
else:
    # Готовый каталог переименовывается целиком: ошибка шаблона не оставляет полкаркаса.
    stage=Path(tempfile.mkdtemp(prefix='overgate-memory-',dir=root.parent))
    try:
        for name in names:shutil.copyfile(root/'.agents/templates/memory-bank'/(name+'.md'),stage/(name+'.md'))
        # rename не заменяет уже созданный непустой каталог проекта.
        os.rename(stage,dest)
    finally:
        if stage.exists():shutil.rmtree(stage)
    print('Memory Bank: created six files')
PY
