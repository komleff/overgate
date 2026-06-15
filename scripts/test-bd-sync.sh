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

# 5. Last-seen / freshness guard.
#    5a. Свежий клон B с непустым контентом, но БЕЗ restore (lastSeen пуст) → export блокируется
#        (защита от stale same-id overwrite при пустом lastSeen).
git clone -q "$TMP/remote.git" "$TMP/cloneB"
git -C "$TMP/cloneB" config user.email b@example.com
git -C "$TMP/cloneB" config user.name cloneB
printf '{"id":"og-1","title":"a"}\n{"id":"og-9","title":"fromB"}\n' > "$TMP/expB.jsonl"
if (cd "$TMP/cloneB" && FAKE_BD_EXPORT="$TMP/expB.jsonl" bash "$EXPORT" >/dev/null 2>&1); then
  no "empty-lastSeen blocks export"
else ok "empty-lastSeen blocks export"; fi
#    5b. После restore у клона B lastSeen установлен → export superset проходит и двигает remote.
( cd "$TMP/cloneB" && bash "$RESTORE" >/dev/null 2>&1 \
  && FAKE_BD_EXPORT="$TMP/expB.jsonl" bash "$EXPORT" >/dev/null 2>&1 ) \
  && ok "cloneB export ok after restore" || no "cloneB export ok after restore"
#    5c. Клон A (lastSeen устарел, remote двинул B) → stale export блокируется.
if FAKE_BD_EXPORT="$TMP/exp.jsonl" bash "$EXPORT" >/dev/null 2>&1; then no "stale export blocked"; else ok "stale export blocked"; fi
#    5d. Чистый restore у A (локальное состояние == base@lastSeen, og-1) → conflict-guard НЕ срабатывает.
( FAKE_BD_EXPORT="$TMP/exp1.jsonl" bash "$RESTORE" >/dev/null 2>&1 ) && ok "clean restore ok" || no "clean restore ok"
#    5e. После restore у A lastSeen обновлён → export superset проходит.
printf '{"id":"og-1","title":"a"}\n{"id":"og-9","title":"fromB"}\n{"id":"og-10","title":"new"}\n' > "$TMP/exp3.jsonl"
FAKE_BD_EXPORT="$TMP/exp3.jsonl" bash "$EXPORT" >/dev/null 2>&1 && ok "export ok after restore" || no "export ok after restore"
#    5f. Conflict-guard: A имеет дивергентные локальные правки И remote ушёл вперёд → restore блокируется.
( cd "$TMP/cloneB" && FAKE_BD_EXPORT="$TMP/expB.jsonl" bash "$RESTORE" >/dev/null 2>&1 \
  && printf '{"id":"og-1"}\n{"id":"og-9"}\n{"id":"og-10"}\n{"id":"og-12","title":"B2"}\n' > "$TMP/expB2.jsonl" \
  && FAKE_BD_EXPORT="$TMP/expB2.jsonl" bash "$EXPORT" >/dev/null 2>&1 ) && ok "cloneB advances remote again" || no "cloneB advances remote again"
printf '{"id":"og-1"}\n{"id":"og-9"}\n{"id":"og-10"}\n{"id":"og-77","title":"local-only"}\n' > "$TMP/expDiv.jsonl"
if FAKE_BD_EXPORT="$TMP/expDiv.jsonl" bash "$RESTORE" >/dev/null 2>&1; then no "restore conflict blocked"; else ok "restore conflict blocked"; fi
#    5g. empty-lastSeen + непустая дивергентная локальная БД → restore блокируется (зеркало export).
git clone -q "$TMP/remote.git" "$TMP/cloneC"
git -C "$TMP/cloneC" config user.email c@example.com
git -C "$TMP/cloneC" config user.name cloneC
printf '{"id":"og-1"}\n{"id":"og-50","title":"local-only-C"}\n' > "$TMP/expC.jsonl"
if (cd "$TMP/cloneC" && FAKE_BD_EXPORT="$TMP/expC.jsonl" bash "$RESTORE" >/dev/null 2>&1); then
  no "restore empty-lastSeen conflict blocked"
else ok "restore empty-lastSeen conflict blocked"; fi

# 6. Branch whitelist: только beads-backup / beads-backup-* допустимы; всё прочее отвергается
#    (whitelist, не blacklist — feature/x тоже схлопнул бы рабочую ветку до snapshot).
for bad in main feature/x refs/heads/main ../evil; do
  if BD_SYNC_BRANCH="$bad" FAKE_BD_EXPORT="$TMP/exp3.jsonl" bash "$EXPORT" >/dev/null 2>&1; then
    no "branch whitelist rejects '$bad'"
  else ok "branch whitelist rejects '$bad'"; fi
done
# beads-backup-* допустим (полноценный export в вариантную ветку проходит).
( cd "$TMP/cloneB" && BD_SYNC_BRANCH=beads-backup-alt FAKE_BD_EXPORT="$TMP/expB.jsonl" bash "$EXPORT" >/dev/null 2>&1 ) \
  && ok "branch whitelist allows beads-backup-alt" || no "branch whitelist allows beads-backup-alt"

# 7. Worktree-guard: запуск из linked-worktree → блок (с проверкой что worktree реально создан).
if git -C "$TMP/work" worktree add -q "$TMP/wt" HEAD >/dev/null 2>&1 && [ -e "$TMP/wt/.git" ]; then
  if (cd "$TMP/wt" && FAKE_BD_EXPORT="$TMP/exp.jsonl" bash "$EXPORT" >/dev/null 2>&1); then no "worktree guard blocks"; else ok "worktree guard blocks"; fi
else
  no "worktree setup (add failed)"
fi

echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
