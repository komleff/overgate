#!/usr/bin/env bash
# Тесты scripts/bd-read.sh на фикстурах (BD_READ_FIXTURE — без сети и git).
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/scripts/tests/lib/assert.sh"
READ="$ROOT/scripts/bd-read.sh"
FIX="$ROOT/scripts/tests/fixtures/issues.jsonl"
NODEPS="$ROOT/scripts/tests/fixtures/issues-nodeps.jsonl"

# --- ready: учитывает граф зависимостей ---
out="$(BD_READ_FIXTURE="$FIX" "$READ" ready 2>&1)"; rc=$?
assert_eq "$rc" "0" "ready: exit 0"
assert_contains "$out" "U2-O1" "ready: O1 (без блокеров)"
assert_contains "$out" "U2-O2" "ready: O2 (блокер закрыт)"
assert_contains "$out" "U2-P1" "ready: P1 (parent-child не блокирует)"
assert_not_contains "$out" "U2-O3" "ready: O3 исключён (блокер открыт)"
assert_not_contains "$out" "U2-O4" "ready: O4 исключён (блокер отсутствует в снимке)"
assert_not_contains "$out" "U2-C1" "ready: закрытые не показываются"
assert_not_contains "$out" "U2-O5" "ready: O5 исключён (ребро без type → консервативно блокирует)"
assert_not_contains "$out" "U2-O6" "ready: O6 исключён (кривое ребро → консервативно блокирует)"
assert_not_contains "$out" "U2-O7" "ready: O7 исключён (parent-child без depends_on_id → форма невалидна → блокирует)"

# --- list --status open ---
out="$(BD_READ_FIXTURE="$FIX" "$READ" list --status open 2>&1)"
assert_contains "$out" "U2-O3" "list open: включает O3"
assert_not_contains "$out" "U2-C1" "list open: исключает closed"
assert_not_contains "$out" "mem-1" "list: служебная _type:memory отфильтрована"

# --- show ---
out="$(BD_READ_FIXTURE="$FIX" "$READ" show U2-O3 2>&1)"
assert_contains "$out" "Blocked by" "show O3: секция Blocked by"
assert_contains "$out" "U2-O1" "show O3: блокер O1"

out="$(BD_READ_FIXTURE="$FIX" "$READ" show U2-NOPE 2>&1)"; rc=$?
assert_ne "$rc" "0" "show несуществующего → ошибка"

# --- fail-closed: снимок без поля dependencies ---
out="$(BD_READ_FIXTURE="$NODEPS" "$READ" ready 2>&1)"; rc=$?
assert_eq "$rc" "2" "ready fail-closed: нет поля dependencies → exit 2"
assert_contains "$out" "fail-closed" "ready fail-closed: понятное сообщение"

# --- повреждённый снимок → fail-closed (не молчаливый пропуск строки) ---
TMPF="$(mktemp)"
printf '%s\n' '{"id":"U2-A","status":"open","dependencies":[]}' 'broken{' > "$TMPF"
out="$(BD_READ_FIXTURE="$TMPF" "$READ" list 2>&1)"; rc=$?
assert_eq "$rc" "2" "read fail-closed: битая строка снимка → exit 2"
rm -f "$TMPF"

# --- пустой (валидный) снимок: ready → «нет задач», не schema-error ---
EMPTY="$(mktemp)"; : > "$EMPTY"
out="$(BD_READ_FIXTURE="$EMPTY" "$READ" ready 2>&1)"; rc=$?
assert_eq "$rc" "0" "ready: пустой снимок → exit 0"
assert_contains "$out" "нет задач" "ready: пустой снимок → (нет задач), не ошибка"
rm -f "$EMPTY"

# --- fetch fail-closed по умолчанию (нет origin, нет BD_READ_NO_FETCH) ---
RT="$(mktemp -d)"; git init -q "$RT"
git -C "$RT" config user.email t@t.t; git -C "$RT" config user.name t
git -C "$RT" commit -q --allow-empty -m init
out="$(cd "$RT" && "$READ" list 2>&1)"; rc=$?
assert_ne "$rc" "0" "bd-read: fetch не удался (нет origin) → fail-closed (ненулевой код)"
rm -rf "$RT"

# --- ready --assignee: фильтр по исполнителю ---
AF="$(mktemp)"
printf '%s\n' '{"id":"U2-RA","status":"open","assignee":"alice","dependencies":[]}' '{"id":"U2-RB","status":"open","assignee":"bob","dependencies":[]}' > "$AF"
out="$(BD_READ_FIXTURE="$AF" "$READ" ready --assignee alice 2>&1)"
assert_contains "$out" "U2-RA" "ready --assignee: alice показан"
assert_not_contains "$out" "U2-RB" "ready --assignee: bob отфильтрован"
rm -f "$AF"

# --- sanitize: control/ANSI в title не попадает в human-вывод ---
SF="$(mktemp)"
node -e 'require("fs").writeFileSync(process.argv[1], JSON.stringify({id:"U2-SAN",status:"open",issue_type:"task",title:"a"+String.fromCharCode(27)+"[31mRED",dependencies:[]})+"\n")' "$SF"
out="$(BD_READ_FIXTURE="$SF" "$READ" list 2>&1)"; rc=$?
assert_eq "$rc" "0" "bd-read sanitize: list exit 0"
assert_contains "$out" "U2-SAN" "bd-read sanitize: задача показана"
assert_not_contains "$out" "$(printf '\033')" "bd-read sanitize: ESC не попадает в вывод"
rm -f "$SF"

# --- РЕАЛЬНЫЙ формат snapshot: bd опускает массив dependencies → доверяем dependency_count ---
RF="$(mktemp)"
printf '%s\n' \
  '{"id":"U2-RC0","status":"open","dependency_count":0,"title":"no array, count 0"}' \
  '{"id":"U2-RC1","status":"open","dependency_count":3,"title":"count>0 без массива"}' \
  '{"id":"U2-RC2","status":"open","dependencies":[],"dependency_count":0,"title":"пустой массив"}' > "$RF"
out="$(BD_READ_FIXTURE="$RF" "$READ" ready 2>&1)"; rc=$?
assert_eq "$rc" "0" "real-format ready: не fail-closed (есть dependency_count)"
assert_contains "$out" "U2-RC0" "real-format ready: count 0 без массива → ready"
assert_contains "$out" "U2-RC2" "real-format ready: пустой массив → ready"
assert_not_contains "$out" "U2-RC1" "real-format ready: count>0 без массива → консервативно НЕ ready"
rm -f "$RF"

finish
