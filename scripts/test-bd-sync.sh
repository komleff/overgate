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
    [ -n "${FAKE_BD_EXPORT_FAIL:-}" ] && exit 1   # эмуляция сбоя bd export (lock/corruption)
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
if BD_SYNC_EXPECTED_SHA=0000000000000000000000000000000000000000 bash "$RESTORE" >/dev/null 2>&1; then
  no "frozen SHA mismatch blocks restore"
else
  [ ! -s "$FAKE_BD_IMPORT_LOG" ] && ok "frozen SHA mismatch blocks restore before import" || no "frozen SHA mismatch imported tasks"
fi
bash "$RESTORE" >/dev/null 2>&1 && ok "restore runs" || no "restore runs"
[ -s "$FAKE_BD_IMPORT_LOG" ] && ok "restore invoked bd import" || no "restore invoked bd import"

# Git for Windows/MSYS может переписать symbolic rev:path в path-like argument
# (origin/beads-backup:.beads/issues.jsonl → origin\beads-backup;.beads\issues.jsonl).
# Имитируем отказ только symbolic show: restore обязан читать проверенный fetched SHA.
mkdir -p "$TMP/win-git"
cat > "$TMP/win-git/git" <<'GIT_STUB'
#!/usr/bin/env bash
if [ "${1:-}" = show ] && [[ "${2:-}" == origin/*:* ]]; then
  echo 'fatal: symbolic rev:path converted by MSYS' >&2
  exit 128
fi
exec "$BD_SYNC_REAL_GIT" "$@"
GIT_STUB
chmod +x "$TMP/win-git/git"
: > "$FAKE_BD_IMPORT_LOG"
if PATH="$TMP/win-git:$PATH" BD_SYNC_REAL_GIT="$(command -v git)" bash "$RESTORE" >/dev/null 2>&1; then
  [ -s "$FAKE_BD_IMPORT_LOG" ] && ok "restore uses fetched SHA under symbolic rev:path conversion" \
    || no "restore under symbolic conversion skipped import"
else
  no "restore uses fetched SHA under symbolic rev:path conversion"
fi

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
#    5h. Fail-closed: если локальный bd export падает — restore прерывается ДО bd import.
: > "$FAKE_BD_IMPORT_LOG"
if (cd "$TMP/cloneC" && FAKE_BD_EXPORT_FAIL=1 bash "$RESTORE" >/dev/null 2>&1); then
  no "restore fail-closed on export error"
else
  [ ! -s "$FAKE_BD_IMPORT_LOG" ] && ok "restore fail-closed on export error" || no "restore fail-closed (import всё же вызван)"
fi

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

# 7. Managed activation между guard и вторым fetch/lookup не должна позволять
# старому writer удалить marker даже с legacy FORCE или импортировать чужой tip.
git init -q --bare "$TMP/race-export.git"
git init -q --bare "$TMP/race-restore.git"
git init -q "$TMP/race-work"
git -C "$TMP/race-work" config user.email race@example.invalid
git -C "$TMP/race-work" config user.name race
git -C "$TMP/race-work" commit -q --allow-empty -m base
git -C "$TMP/race-work" remote add origin "$TMP/race-export.git"
printf '{"id":"race-1","title":"old"}\n' > "$TMP/race-old.jsonl"
(cd "$TMP/race-work" && FAKE_BD_EXPORT="$TMP/race-old.jsonl" bash "$EXPORT" >/dev/null 2>&1)
race_base=$(git -C "$TMP/race-work" ls-remote origin refs/heads/beads-backup | awk '{print $1}')
git -C "$TMP/race-work" push -q "$TMP/race-restore.git" "$race_base:refs/heads/beads-backup"
race_index="$TMP/race-index"
GIT_INDEX_FILE="$race_index" git -C "$TMP/race-work" read-tree "$race_base"
race_blob=$(printf '%s\n' '{"version":1}' | git -C "$TMP/race-work" hash-object -w --stdin)
GIT_INDEX_FILE="$race_index" git -C "$TMP/race-work" update-index --add --cacheinfo "100644,${race_blob},.beads/overgate-managed-v1.json"
race_tree=$(GIT_INDEX_FILE="$race_index" git -C "$TMP/race-work" write-tree)
race_managed=$(git -C "$TMP/race-work" commit-tree "$race_tree" -p "$race_base" -m managed)
mkdir -p "$TMP/race-bin"
cat > "$TMP/race-bin/git" <<'RACE_GIT'
#!/usr/bin/env bash
if [ "${1:-}" = "$RACE_TRIGGER" ]; then
  count=$(cat "$RACE_COUNTER" 2>/dev/null || printf '0')
  count=$((count+1)); printf '%s' "$count" > "$RACE_COUNTER"
  if [ "$count" -eq 2 ]; then
    "$RACE_REAL_GIT" push -q "$RACE_REMOTE" "$RACE_MANAGED:refs/heads/beads-backup"
  fi
fi
exec "$RACE_REAL_GIT" "$@"
RACE_GIT
chmod +x "$TMP/race-bin/git"
race_real_git=$(command -v git)
printf '{"id":"race-1","title":"old changed"}\n' > "$TMP/race-new.jsonl"
for mode in export restore; do
  remote="$TMP/race-${mode}.git"
  git -C "$TMP/race-work" remote set-url origin "$remote"
  : > "$TMP/race-counter"; : > "$FAKE_BD_IMPORT_LOG"
  script="$EXPORT"; trigger=ls-remote
  [ "$mode" = restore ] && { script="$RESTORE"; trigger=fetch; }
  if (cd "$TMP/race-work" && PATH="$TMP/race-bin:$PATH" RACE_REAL_GIT="$race_real_git" \
      RACE_TRIGGER="$trigger" RACE_COUNTER="$TMP/race-counter" RACE_REMOTE="$remote" \
      RACE_MANAGED="$race_managed" BD_SYNC_FORCE=1 FAKE_BD_EXPORT="$TMP/race-new.jsonl" \
      bash "$script" >/dev/null 2>&1); then
    no "managed activation race stops legacy ${mode}"
  elif [ "$(git --git-dir="$remote" rev-parse refs/heads/beads-backup)" = "$race_managed" ] \
      && [ ! -s "$FAKE_BD_IMPORT_LOG" ]; then
    ok "managed activation race stops legacy ${mode} before mutation"
  else
    no "managed activation race preserved remote/local state for ${mode}"
  fi
done

# 8. Удалённая ветка исчезла после того, как clone видел managed marker.
# Кэшированная история не позволяет старому writer считать это fresh remote.
git -C "$TMP/race-work" remote set-url origin "$TMP/race-export.git"
git -C "$TMP/race-work" fetch -q origin '+refs/heads/beads-backup:refs/remotes/origin/beads-backup'
cached_tip=$(git -C "$TMP/race-work" rev-parse refs/remotes/origin/beads-backup)
[ "$cached_tip" = "$race_managed" ] && ok "managed history cached before remote disappearance" || no "managed history cache setup"
git --git-dir="$TMP/race-export.git" update-ref -d refs/heads/beads-backup
for mode in export restore; do
  script="$EXPORT"; [ "$mode" = restore ] && script="$RESTORE"
  : > "$FAKE_BD_IMPORT_LOG"
  if (cd "$TMP/race-work" && BD_SYNC_FORCE=1 FAKE_BD_EXPORT="$TMP/race-new.jsonl" bash "$script" >/dev/null 2>&1); then
    no "missing remote with cached managed state stops legacy ${mode}"
  elif [ -z "$(git --git-dir="$TMP/race-export.git" for-each-ref refs/heads/beads-backup)" ] \
      && [ ! -s "$FAKE_BD_IMPORT_LOG" ]; then
    ok "missing remote with cached managed state stops legacy ${mode}"
  else
    no "missing remote with cached managed state preserves branch/import for ${mode}"
  fi
done

# 9. Worktree-guard: запуск из linked-worktree → блок (с проверкой что worktree реально создан).
if git -C "$TMP/work" worktree add -q "$TMP/wt" HEAD >/dev/null 2>&1 && [ -e "$TMP/wt/.git" ]; then
  if (cd "$TMP/wt" && FAKE_BD_EXPORT="$TMP/exp.jsonl" bash "$EXPORT" >/dev/null 2>&1); then no "worktree guard blocks"; else ok "worktree guard blocks"; fi
else
  no "worktree setup (add failed)"
fi

echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
