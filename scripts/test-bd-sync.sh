#!/usr/bin/env bash
# Smoke-тест helper-скриптов синхронизации Beads (bd-sync-export.sh / bd-sync-restore.sh).
# Полностью локальный: bare-repo как remote + stub `bd` на PATH. Сети и реального bd НЕ требует.
# Покрывает: syntax, first export, no-op skip, drop-guard (+FORCE override), restore→import,
# worktree-guard. Запуск: bash scripts/test-bd-sync.sh
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
EXPORT="$SCRIPT_DIR/bd-sync-export.sh"
RESTORE="$SCRIPT_DIR/bd-sync-restore.sh"
PASS=0; FAIL=0
ok(){ echo "  PASS: $1"; PASS=$((PASS+1)); }
no(){ echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

bash -n "$EXPORT" && bash -n "$RESTORE" && ok "syntax" || no "syntax"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/bd-sync-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

# Stub `bd`: where → ok; export --all -o F → копирует $FAKE_BD_EXPORT в F; import F → лог.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/bd" <<'STUB'
#!/usr/bin/env bash
sub="$1"; shift || true
case "$sub" in
  where) exit 0 ;;
  export)
    out=""; while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="${2:-}"; shift; done
    [ -n "$out" ] && { cp "${FAKE_BD_EXPORT:-/dev/null}" "$out" 2>/dev/null || : > "$out"; }
    exit 0 ;;
  import) echo "IMPORTED:${1:-}" >> "${FAKE_BD_IMPORT_LOG:-/dev/null}"; exit 0 ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$TMP/bin/bd"
export PATH="$TMP/bin:$PATH"

git init -q --bare "$TMP/remote.git"
git init -q "$TMP/work"
cd "$TMP/work"
git config user.email t@example.com; git config user.name tester
git commit -q --allow-empty -m init
# Регистрируем bare как named remote origin — скрипты строят refs/remotes/<remote>/...,
# что валидно только для именованного remote (в реальности всегда origin).
git remote add origin "$TMP/remote.git"

# 1. Первая публикация (remote пуст) — задачи og-1, og-2.
printf '{"id":"og-1","title":"a"}\n{"id":"og-2","title":"b"}\n' > "$TMP/exp.jsonl"
FAKE_BD_EXPORT="$TMP/exp.jsonl" bash "$EXPORT" >/dev/null 2>&1 && ok "first export" || no "first export"
got=$(git --git-dir="$TMP/remote.git" show beads-backup:.beads/issues.jsonl 2>/dev/null | grep -c '"id"')
[ "$got" = "2" ] && ok "remote snapshot has 2 ids" || no "remote snapshot ids ($got)"

# 2. No-op: тот же снапшот — не должен плодить коммит.
out=$(FAKE_BD_EXPORT="$TMP/exp.jsonl" bash "$EXPORT" 2>&1)
echo "$out" | grep -q "не изменился" && ok "no-op skip" || no "no-op skip"

# 3. Drop-guard: локальный снапшот без og-2 → блок (затёр бы задачу с remote).
printf '{"id":"og-1","title":"a"}\n' > "$TMP/exp1.jsonl"
if FAKE_BD_EXPORT="$TMP/exp1.jsonl" bash "$EXPORT" >/dev/null 2>&1; then no "drop-guard blocks"; else ok "drop-guard blocks"; fi

# 3b. BD_SYNC_FORCE=1 переопределяет drop-guard.
BD_SYNC_FORCE=1 FAKE_BD_EXPORT="$TMP/exp1.jsonl" bash "$EXPORT" >/dev/null 2>&1 && ok "drop-guard FORCE override" || no "FORCE override"

# 4. Restore → вызывает bd import непустым снапшотом.
export FAKE_BD_IMPORT_LOG="$TMP/import.log"; : > "$FAKE_BD_IMPORT_LOG"
bash "$RESTORE" >/dev/null 2>&1 && ok "restore runs" || no "restore runs"
[ -s "$FAKE_BD_IMPORT_LOG" ] && ok "restore invoked bd import" || no "restore invoked bd import"

# 5. Last-seen guard: remote ушёл вперёд с момента последней синхронизации клона A → блок.
#    Клон B независимо публикует новый снапшот (superset, чтобы пройти drop-guard), после чего
#    export из A (его lastSeen устарел) должен fail-closed — иначе затёр бы изменения B.
git clone -q "$TMP/remote.git" "$TMP/cloneB"
( cd "$TMP/cloneB"
  git config user.email b@example.com; git config user.name cloneB
  printf '{"id":"og-1","title":"a"}\n{"id":"og-9","title":"fromB"}\n' > "$TMP/expB.jsonl"
  FAKE_BD_EXPORT="$TMP/expB.jsonl" bash "$EXPORT" >/dev/null 2>&1 ) && ok "cloneB advances remote" || no "cloneB advances remote"
if FAKE_BD_EXPORT="$TMP/exp.jsonl" bash "$EXPORT" >/dev/null 2>&1; then no "last-seen guard blocks stale export"; else ok "last-seen guard blocks stale export"; fi
# После restore lastSeen обновляется → export снова разрешён (если снапшот не теряет задачи).
bash "$RESTORE" >/dev/null 2>&1 || true
printf '{"id":"og-1","title":"a"}\n{"id":"og-9","title":"fromB"}\n{"id":"og-10","title":"new"}\n' > "$TMP/exp3.jsonl"
FAKE_BD_EXPORT="$TMP/exp3.jsonl" bash "$EXPORT" >/dev/null 2>&1 && ok "export ok after restore" || no "export ok after restore"

# 6. Worktree-guard: запуск из linked-worktree → блок.
git -C "$TMP/work" worktree add -q "$TMP/wt" HEAD >/dev/null 2>&1
if (cd "$TMP/wt" && FAKE_BD_EXPORT="$TMP/exp.jsonl" bash "$EXPORT" >/dev/null 2>&1); then no "worktree guard blocks"; else ok "worktree guard blocks"; fi

echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
