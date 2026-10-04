#!/usr/bin/env bash
# Тесты scripts/bd-wt.sh: pass-through из main, --db из worktree, отказ
# export/import/dolt (в т.ч. после глобального флага), мёртвый сервер, не-git.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"
WT_SH="$ROOT/scripts/bd-wt.sh"
STUB="$ROOT/scripts/tests/lib/bd-stub.mjs"
chmod +x "$STUB" 2>/dev/null
export BD_BIN="$STUB"

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
MAIN="$T/main"
git init -q "$MAIN"
git -C "$MAIN" config user.email t@t.t
git -C "$MAIN" config user.name t
git -C "$MAIN" commit -q --allow-empty -m init
mkdir -p "$MAIN/.beads/dolt"
echo 99999999 > "$MAIN/.beads/dolt-server.pid"   # заведомо мёртвый pid
echo 50999 > "$MAIN/.beads/dolt-server.port"

# --- отказ export/import/dolt (до детекта окружения) ---
out="$(cd "$MAIN" && "$WT_SH" export 2>&1)"; rc=$?
assert_eq "$rc" "2" "refuse: export → exit 2"
out="$(cd "$MAIN" && "$WT_SH" --db /tmp/x dolt push 2>&1)"; rc=$?
assert_eq "$rc" "2" "refuse: dolt после глобального флага --db X → exit 2"
out="$(cd "$MAIN" && "$WT_SH" import foo 2>&1)"; rc=$?
assert_eq "$rc" "2" "refuse: import → exit 2"

# --- из основного checkout: pass-through без --db ---
L="$T/log.main"; : > "$L"
( cd "$MAIN" && BD_STUB_LOG="$L" "$WT_SH" ready ) >/dev/null 2>&1
log="$(cat "$L")"
assert_contains "$log" "ready" "main: команда ready проброшена"
assert_not_contains "$log" "--db" "main: --db НЕ подставлен"

# --- не git-репозиторий → exit 1 ---
out="$(cd "$T" && "$WT_SH" ready 2>&1)"; rc=$?
assert_eq "$rc" "1" "не git-репо → exit 1"

# --- worktree ---
WTREE="$T/wt"
git -C "$MAIN" worktree add -q "$WTREE" -b wtbranch

L2="$T/log.wt"; : > "$L2"
out="$(cd "$WTREE" && BD_STUB_LOG="$L2" BD_ENV_ASSUME_DOLT_ALIVE=1 "$WT_SH" ready 2>&1)"; rc=$?
assert_eq "$rc" "0" "worktree+живой сервер: exit 0"
log="$(cat "$L2")"
assert_contains "$log" "--db" "worktree: --db подставлен"
assert_contains "$log" "$MAIN/.beads/dolt" "worktree: --db указывает на базу основного checkout"

# --- worktree + мёртвый сервер → exit 3 ---
out="$(cd "$WTREE" && "$WT_SH" ready 2>&1)"; rc=$?
assert_eq "$rc" "3" "worktree+мёртвый сервер: exit 3"

# --- отказ от пользовательского --db (обёртка ставит его сама) ---
out="$(cd "$MAIN" && "$WT_SH" --db /tmp/x show U2-1 2>&1)"; rc=$?
assert_eq "$rc" "2" "refuse: пользовательский --db value → exit 2"
out="$(cd "$MAIN" && "$WT_SH" --db=/tmp/x show U2-1 2>&1)"; rc=$?
assert_eq "$rc" "2" "refuse: --db=… → exit 2"

finish
