#!/usr/bin/env bash
# Фикстура гейта триажа /finalize-pr (U2-m5b1): разбор строк таблицы findings.
#
# Тест извлекает bash-логику ИЗ САМОГО СКИЛЛА и прогоняет её на подставных отчётах.
# Дублировать логику в тесте нельзя: тогда он проверял бы копию, а не действующий
# артефакт, — ровно тот класс дефекта, ради которого фикстура и заводится.
set -uo pipefail
# В assertions grep дочитывает pipe до конца: -q мог оборвать printf/grep слева
# и превратить найденный маркер в ненулевой результат конвейера (U2-4cp5l).
# Отрицательные пробы проверяют PIPESTATUS: отсутствие — только 0/1 у printf/grep;
# у фильтрующего grep слева также допустим 1 (фильтр не оставил строк).

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$ROOT/.claude/skills/finalize-pr/SKILL.md"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
ok() { pass=$((pass + 1)); printf 'ok %d - %s\n' "$pass" "$1"; }
not_ok() { fail=$((fail + 1)); printf 'not ok - %s\n' "$1" >&2; }

# --- извлечение логики из скилла -------------------------------------------
# Берём участок от объявления SEP до конца проверки TRIAGE_FAILED.
# Сетевое получение тел отчётов пропускаем и подставляем REVIEW_BODIES из фикстуры:
# предмет проверки — нормализация, разбор и страховка, не вызов `gh pr view`.
EXTRACT="$TMP/triage-logic.sh"
# ⚠️ Финальный блок берётся ИЗ СКИЛЛА целиком, включая его `exit 1`. Синтезировать выход
# в тесте нельзя: тогда удаление `exit 1` из скилла (полный отказ построчной половины гейта)
# фикстура не заметит — она подставит свой. Проверяем это ниже явной проверкой.
# ⚠️ Хвостовой блок печатается ОДИН раз: правило захвата печатает строку, правило хвоста
# только помечает её и выходит на закрывающем `fi`. Прежний порядок правил печатал хвост
# дважды, и извлечение переставало быть точной копией скилла.
# ⚠️ Границу пропускаемого блока задают ПАРНЫЕ маркеры скилла `triage-fetch:start` /
# `triage-fetch:end`, а не форма его первой строки. Прежнее правило `/^REVIEW_BODIES=\$\(timeout/`
# угадывало форму: любая правка вызова (обёртка ограничения времени, проверки исхода,
# перенос jq в отдельный оператор) молча ломала границу — пропускался не тот участок,
# и фикстура гоняла обрубок. Это тот же класс дефекта, который чинит сам разбор ниже,
# поэтому граница здесь тоже объявлена явно, а её наличие проверяется отдельно.
awk '
  /^SEP=\$\(printf/                 { capture = 1 }
  /^# triage-fetch:start/           { skipping = 1 }
  skipping && /^# triage-fetch:end/ { skipping = 0; next }
  capture && !skipping              { print }
  /^if \[ "\$TRIAGE_FAILED" = "1" \]; then/ { in_tail = 1; next }
  in_tail && /^fi$/                 { exit }
' "$SKILL" > "$EXTRACT"

# Маркеры границы обязаны существовать в скилле ровно по одному разу. Иначе awk выше либо
# не пропустит сетевой вызов (тест пойдёт в сеть и покраснеет непредсказуемо), либо
# пропустит участок до конца файла (извлечение станет обрубком). Проверка адресная:
# сообщение должно называть причину, а не «что-то не извлеклось».
for marker in '# triage-fetch:start' '# triage-fetch:end'; do
  if [ "$(grep -c -F -x "$marker" "$SKILL")" != "1" ]; then
    not_ok "маркер '$marker' встречается в SKILL.md не один раз — граница блока сетевого получения тел потеряна"
    printf '\n1..%d\n' "$((pass + fail))"
    exit 1
  fi
done

# Phase 2 / U2-4he: живые владельцы не имеют права воскресить обязательный dual-finalize
# landing. Блок стоит ЗДЕСЬ, на верхнем уровне, а не внутри ветки отказа проверки маркеров
# выше: при переносе пакета он оказался в теле того `if`, то есть исполнялся бы только на
# сломанном дереве и сразу перед `exit 1`. На здоровом дереве ветка не берётся — и пять
# утверждений ниже не выполнялись ни разу (Code Review PR #759, C-1).
#
# Невакуумность проверяется здесь же, мутацией на временных копиях: подстановка
# `--pre-landing` владельцу и удаление `ACCEPTED_RISK` из finalize обязаны дать отказ.
# Без этой проверки перестановка блока снова была бы недоказуема — зелёный прогон сам по
# себе не отличает «проверка держит норму» от «проверка не исполняется».
single_finalize_owner_verdict() { # <файл-владельца>
  if grep -Eq -- '--pre-landing|PRE_LANDING|LANDING_WARNING|dual-invocation|второй[[:space:]]+/finalize-pr' "$1"; then
    printf 'legacy'
  else
    printf 'clean'
  fi
}

single_finalize_accepted_risk_verdict() { # <файл-скилла>
  if grep -F 'ACCEPTED_RISK' "$1" >/dev/null; then
    printf 'present'
  else
    printf 'lost'
  fi
}

SINGLE_FINALIZE_OWNERS=(
  "$SKILL"
  "$ROOT/.claude/skills/sprint-pr-cycle/SKILL.md"
  "$ROOT/.agents/INSTALL.md"
  "$ROOT/.agents/HOW_TO_USE.md"
)
for owner in "${SINGLE_FINALIZE_OWNERS[@]}"; do
  if [ "$(single_finalize_owner_verdict "$owner")" = "clean" ]; then
    ok "single-finalize contract: ${owner#$ROOT/} has no legacy dual-invocation token"
  else
    not_ok "single-finalize contract: legacy dual-invocation token remains in ${owner#$ROOT/}"
  fi
done
if [ "$(single_finalize_accepted_risk_verdict "$SKILL")" = "present" ]; then
  ok "single-finalize contract: ACCEPTED_RISK gate remains"
else
  not_ok "single-finalize contract: ACCEPTED_RISK gate was lost"
fi

# Мутация 1: владельцу возвращают `--pre-landing` — вердикт обязан стать `legacy`.
SINGLE_FINALIZE_MUT="$TMP/single-finalize-mutation"
mkdir -p "$SINGLE_FINALIZE_MUT"
cp "$ROOT/.agents/HOW_TO_USE.md" "$SINGLE_FINALIZE_MUT/owner-with-pre-landing.md"
printf '\nЗапусти второй проход: /finalize-pr <PR> --pre-landing\n' \
  >> "$SINGLE_FINALIZE_MUT/owner-with-pre-landing.md"
if [ "$(single_finalize_owner_verdict "$SINGLE_FINALIZE_MUT/owner-with-pre-landing.md")" = "legacy" ]; then
  ok "single-finalize contract: мутация «--pre-landing у владельца» краснеет (проверка невакуумна)"
else
  not_ok "single-finalize contract: мутация «--pre-landing у владельца» не поймана — проверка владельцев ничего не удерживает"
fi

# Мутация 2: из копии finalize убран `ACCEPTED_RISK` — вердикт обязан стать `lost`.
grep -v -F 'ACCEPTED_RISK' "$SKILL" > "$SINGLE_FINALIZE_MUT/finalize-without-accepted-risk.md"
if [ "$(single_finalize_accepted_risk_verdict "$SINGLE_FINALIZE_MUT/finalize-without-accepted-risk.md")" = "lost" ]; then
  ok "single-finalize contract: мутация «нет ACCEPTED_RISK» краснеет (проверка невакуумна)"
else
  not_ok "single-finalize contract: мутация «нет ACCEPTED_RISK» не поймана — проверка ACCEPTED_RISK ничего не удерживает"
fi

# Сетевой вызов обязан остаться ЗА границей извлечения: если он попал в извлечение,
# прогон уходит в сеть и его результат перестаёт быть утверждением о разборе.
# Строки-комментарии из проверки исключаются: соседний комментарий скилла упоминает
# `gh pr view` по делу, и запрет на упоминание превратил бы проверку в запрет объяснять.
if ! { grep -vE '^[[:space:]]*#' "$EXTRACT" | grep >/dev/null 'gh pr view'; search_status=("${PIPESTATUS[@]}");
  [ "${search_status[0]}" -le 1 ] && [ "${search_status[1]}" -eq 1 ]; }; then
  not_ok "в извлечение попал сетевой вызов 'gh pr view' — маркеры границы очерчивают не тот блок"
  printf '\n1..%d\n' "$((pass + fail))"
  exit 1
fi

# Обратная сторона той же границы: REVIEW_BODIES подаёт фикстура, поэтому присвоения этой
# переменной в извлечении быть не должно — иначе подставленные тела затираются пустыми.
if grep -q '^REVIEW_BODIES=' "$EXTRACT"; then
  not_ok "в извлечении осталось присвоение REVIEW_BODIES — тела фикстуры затираются, кейсы становятся ложно-зелёными"
  printf '\n1..%d\n' "$((pass + fail))"
  exit 1
fi

# Извлечение обязано быть исполнимым целиком: необъявленная переменная под `set -u`
# оборвала бы прогон и все кейсы «гейт краснеет» стали бы ложно-зелёными.
if ! grep -q '^SEP=' "$EXTRACT" || ! grep -q '^TRIAGE_FAILED=0' "$EXTRACT"; then
  not_ok "извлечение неполное: нет объявления SEP или TRIAGE_FAILED — тест проверял бы обрывок"
  printf '\n1..%d\n' "$((pass + fail))"
  exit 1
fi

# Хвост с реальным выходом обязан быть в извлечении: если скилл перестал завершаться
# ошибкой при TRIAGE_FAILED=1, тест обязан это увидеть, а не подставить свой выход.
# ⚠️ Проверка АДРЕСНАЯ — `exit 1` именно под хвостовым условием. Прежняя проверка искала
# любой `exit 1` в извлечении и проходила на выходах страховок: мутация хвоста её не роняла.
if ! grep -A1 -F 'if [ "$TRIAGE_FAILED" = "1" ]; then' "$EXTRACT" | grep -E >/dev/null '^[[:space:]]*exit 1$'; then
  not_ok "в извлечении нет 'exit 1' под хвостовым условием скилла — построчная половина гейта не завершается ошибкой"
  printf '\n1..%d\n' "$((pass + fail))"
  exit 1
fi

# Извлечение обязано быть ТОЧНОЙ копией участка скилла: хвостовое условие встречается
# в нём ровно один раз. Прежний порядок правил awk печатал хвост дважды, и тест гонял
# не то, что лежит в скилле.
if [ "$(grep -c -F 'if [ "$TRIAGE_FAILED" = "1" ]; then' "$EXTRACT")" != "1" ]; then
  not_ok "хвостовое условие в извлечении встречается не один раз — извлечение не является точной копией скилла"
  printf '\n1..%d\n' "$((pass + fail))"
  exit 1
fi

if ! grep -q 'TRIAGE_ROWS=' "$EXTRACT"; then
  not_ok "не удалось извлечь логику разбора из $SKILL — изменилась структура скилла"
  printf '\n1..%d\n' "$((pass + fail))"
  exit 1
fi
ok "логика разбора извлечена из действующего SKILL.md"

# --- помощник ограничения времени: тоже ИЗ СКИЛЛА -------------------------------------
# Гейт зовёт `bd show` и `gh pr view` через `run_with_timeout`. Синтезировать эту обёртку
# в фикстуре нельзя: тогда ветка проверки задачи через `bd` и проверки исхода сетевого
# вызова прогонялись бы против тестовой подделки, а не против действующего артефакта.
# Границу задают те же парные маркеры, что использует scripts/tests/with-timeout.test.sh.
HELPER="$TMP/timeout-helper.sh"
awk '
  /^<!-- timeout-helper-preflight:start -->/ { f = 1; next }
  /^<!-- timeout-helper-preflight:end -->/   { exit }
  f && !/^```/                               { print }
' "$SKILL" > "$HELPER"
if ! grep -q '^run_with_timeout() {' "$HELPER"; then
  not_ok "из SKILL.md не извлекается preflight помощника ограничения времени — ветки bd и сетевого вызова прогонялись бы против подделки"
  printf '\n1..%d\n' "$((pass + fail))"
  exit 1
fi
ok "помощник ограничения времени извлечён из действующего SKILL.md"

# Прогон извлечённой логики на теле отчёта. Базовый PATH намеренно узкий и БЕЗ `bd`:
# по умолчанию исполняется запасной путь по форме идентификатора, рабочая база не трогается.
# Вторым аргументом кейс подкладывает каталог с заглушкой `bd` — тогда исполняется
# приоритетная ветка «проверка существования задачи».
# Третьим аргументом кейс задаёт РАБОЧИЙ КАТАЛОГ прогона. Он нужен веткам, которые ищут
# файлы репозитория через `git rev-parse --show-toplevel` (помощник ограничения времени и
# читатель снимка `scripts/bd-read.sh`): подставной корень позволяет проверить их исполнением,
# не трогая ни сеть, ни настоящий снимок `origin/beads-backup`.
run_gate() {
  local body_file="$1"
  local extra_path="${2:-}"
  local workdir="${3:-${SNAP_ROOT:-}}"
  # Сборка построчно, БЕЗ heredoc: неэкранированный heredoc раскрыл бы `$(...)`,
  # `$VAR` и обратные слэши внутри извлечённого кода ещё при создании файла,
  # и на прогон ушёл бы не тот текст, что лежит в скилле.
  {
    # ⚠️ НЕ `pipefail` — см. пояснение у `run_piece`. Скилл исполняется агентом в обычной
    # оболочке, где `pipefail` не установлен. Включив его здесь, фикстура сделала бы конвейеры
    # fail-closed САМА и объявила бы починенным то, что в бою по-прежнему пропускает отказ.
    printf 'set -u\n'
    printf 'HEAD_COMMIT="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"\n'
    cat "$HELPER"
    # Фикстура подаёт тела уже с разделителем Record Separator между отчётами —
    # ровно так, как их отдаёт jq в скилле (`.body + "\u001e"`).
    printf 'REVIEW_BODIES=$(cat %s)\n' "$body_file"
    cat "$EXTRACT"
    printf 'exit 0\n'
  } > "$TMP/run.sh"
  local path="/usr/bin:/bin:/usr/sbin:/sbin"
  [ -n "$extra_path" ] && path="$extra_path:$path"
  if [ -n "$workdir" ]; then
    ( cd "$workdir" && env PATH="$path" bash "$TMP/run.sh" 2>&1 )
  else
    env PATH="$path" bash "$TMP/run.sh" 2>&1
  fi
}
gate_code() { run_gate "$1" "${2:-}" "${3:-}" >/dev/null 2>&1; echo $?; }

# Подставной КОРЕНЬ РЕПОЗИТОРИЯ для прогона. Гейт ищет свои файлы через
# `git rev-parse --show-toplevel`, поэтому и помощник ограничения времени, и читатель снимка
# `scripts/bd-read.sh` берутся из этого корня. Подставной корень даёт кейсу управлять окружением
# Beads, не трогая ни сеть, ни настоящий снимок `origin/beads-backup`.
#   reader=snapshot   — снимок читается; задачи, перечисленные третьим аргументом, в нём есть,
#                       любые другие — нет (так проверяется, что идентификатор реально доходит
#                       до читателя, а не «одобряется» заглушкой скопом);
#   reader=unreadable — снимка нет вовсе: любой вызов читателя завершается ошибкой;
#   reader=none       — читателя снимка в корне нет (окружение без bd и без bd-read.sh).
# Четвёртым аргументом кейс может попросить корень БЕЗ канон-библиотеки beads (`nolib`):
# тогда класс окружения определить нечем, и это отдельный исход, а не «не основной checkout».
make_snapshot_root() {
  local name="$1" reader="$2" known="${3:-}" lib="${4:-}"
  local root="$TMP/root-$name"
  if [ ! -d "$root" ]; then
    mkdir -p "$root/.claude" "$root/scripts"
    # Каталог помощников копируется целиком: `with-timeout.sh` при отсутствии нативного
    # `timeout` (обычная macOS) исполняется через соседний `run-python.sh`, и без него
    # обёртка завершилась бы кодом 127 на каждом кейсе.
    cp -R "$ROOT/.claude/tools" "$root/.claude/tools"
    # Канон-библиотека beads кладётся в подставной корень целиком: гейт определяет класс
    # окружения её функцией `bd_env_is_main_checkout`, а не второй копией критерия. Без неё
    # класс был бы «неизвестен», и кейсы про авторитетный ответ прямого `bd` проверяли бы
    # запасной путь вместо своей ветки.
    mkdir -p "$root/scripts/lib"
    [ "$lib" = "nolib" ] || cp "$ROOT/scripts/lib/bd-env.sh" "$root/scripts/lib/bd-env.sh"
    git -C "$root" init -q >/dev/null 2>&1
    case "$reader" in
      snapshot)
        {
          printf '#!/bin/sh\n'
          printf 'if [ "$1" = "show" ]; then\n'
          printf '  for known in %s; do\n' "${known:-__снимок-пуст__}"
          printf '    [ "$2" = "$known" ] && exit 0\n'
          printf '  done\n'
          printf '  exit 1\n'
          printf 'fi\n'
          printf 'exit 0\n'
        } > "$root/scripts/bd-read.sh"
        chmod +x "$root/scripts/bd-read.sh"
        ;;
      unreadable)
        printf '#!/bin/sh\nexit 1\n' > "$root/scripts/bd-read.sh"
        chmod +x "$root/scripts/bd-read.sh"
        ;;
    esac
  fi
  printf '%s' "$root"
}

# Окружение ПО УМОЛЧАНИЮ: `bd` в PATH нет, снимок читается, и в нём лежат все идентификаторы,
# которыми кейсы разбора пользуются как заведомо законными. Так кейсы про разбор таблиц
# проверяют разбор, а не наличие задачи, — и при этом не уходят ни в сеть, ни в живую базу.
SNAPSHOT_KNOWN_IDS='U2-abcd U2-t233 U2-h9hh U2-m5b1 U2-a08 U2-9nz8 U2-1gfa big-heroes-abc'
SNAP_ROOT="$(make_snapshot_root default snapshot "$SNAPSHOT_KNOWN_IDS")"

# Подставная СВЯЗАННАЯ git-worktree — второй документированный класс окружения (ADR-0042).
# Там прямой `bd` с auto-discovery открывает ПУСТУЮ базу и отвечает «задачи нет» на любой
# идентификатор, а канонический маршрут — обёртка scripts/bd-wt.sh с явным `--db`. Дерево
# создаётся настоящим `git worktree add`: класс окружения гейт определяет по git, и подделка
# каталогом эту ветку не проверила бы.
#   $1 — имя; $2 — режим обёртки (found|refuse|dead|none); $3 — режим читателя снимка
#   (snapshot|unreadable|none); $4 — список задач, известных снимку.
# Обе заглушки отмечают факт вызова файлами `.called-bd-wt` / `.called-bd-read` в корне —
# так кейс проверяет не только исход, но и то, какие маршруты гейт вообще дёргал.
make_worktree_root() {
  local name="$1" wt="$2" reader="$3" known="${4:-}"
  local main="$TMP/wtmain-$name" linked="$TMP/wtlinked-$name"
  if [ ! -d "$linked" ]; then
    mkdir -p "$main"
    git -C "$main" init -q >/dev/null 2>&1
    git -C "$main" -c user.email=t@u2 -c user.name=u2 commit -q --allow-empty -m init >/dev/null 2>&1
    git -C "$main" worktree add -q "$linked" -b "wt-$name" >/dev/null 2>&1
    mkdir -p "$linked/.claude" "$linked/scripts/lib"
    cp -R "$ROOT/.claude/tools" "$linked/.claude/tools"
    cp "$ROOT/scripts/lib/bd-env.sh" "$linked/scripts/lib/bd-env.sh"
    case "$wt" in
      found)
        {
          printf '#!/bin/sh\n'
          printf ': > "%s/.called-bd-wt"\n' "$linked"
          printf 'for known in %s; do\n' "${known:-__нет-задач__}"
          printf '  [ "$3" = "$known" ] && exit 0\n'
          printf 'done\n'
          printf 'exit 1\n'
        } > "$linked/scripts/bd-wt.sh" ;;
      refuse)
        printf '#!/bin/sh\n: > "%s/.called-bd-wt"\nexit 1\n' "$linked" > "$linked/scripts/bd-wt.sh" ;;
      dead)
        printf '#!/bin/sh\n: > "%s/.called-bd-wt"\nexit 3\n' "$linked" > "$linked/scripts/bd-wt.sh" ;;
    esac
    [ "$wt" = "none" ] || chmod +x "$linked/scripts/bd-wt.sh"
    case "$reader" in
      snapshot)
        {
          printf '#!/bin/sh\n'
          printf ': > "%s/.called-bd-read"\n' "$linked"
          printf 'if [ "$1" = "show" ]; then\n'
          printf '  for known in %s; do\n' "${known:-__снимок-пуст__}"
          printf '    [ "$2" = "$known" ] && exit 0\n'
          printf '  done\n'
          printf '  exit 1\n'
          printf 'fi\n'
          printf 'exit 0\n'
        } > "$linked/scripts/bd-read.sh"
        chmod +x "$linked/scripts/bd-read.sh" ;;
      unreadable)
        printf '#!/bin/sh\n: > "%s/.called-bd-read"\nexit 1\n' "$linked" > "$linked/scripts/bd-read.sh"
        chmod +x "$linked/scripts/bd-read.sh" ;;
    esac
  fi
  rm -f "$linked/.called-bd-wt" "$linked/.called-bd-read"
  printf '%s' "$linked"
}

# Подставной ОСНОВНОЙ checkout, у которого обе заглушки запасных маршрутов ОТМЕЧАЮТ факт
# вызова файлами `.called-bd-wt` / `.called-bd-read`. Нужен обратной стороне находки об
# авторитетности прямого `bd`: там, где его ответ авторитетен, запасные маршруты дёргать
# незачем, и кейс обязан доказать это вызовом, а не рассуждением. Дерево создаётся обычным
# `git init` (не `git worktree add`) — именно это и делает его основным checkout'ом в глазах
# канонической `bd_env_is_main_checkout`.
#   $1 — имя; $2 — список задач, известных снимку.
make_main_root_marked() {
  local name="$1" known="${2:-}"
  local root="$TMP/mainmarked-$name"
  if [ ! -d "$root" ]; then
    mkdir -p "$root/.claude" "$root/scripts/lib"
    cp -R "$ROOT/.claude/tools" "$root/.claude/tools"
    cp "$ROOT/scripts/lib/bd-env.sh" "$root/scripts/lib/bd-env.sh"
    git -C "$root" init -q >/dev/null 2>&1
    printf '#!/bin/sh\n: > "%s/.called-bd-wt"\nexit 1\n' "$root" > "$root/scripts/bd-wt.sh"
    chmod +x "$root/scripts/bd-wt.sh"
    {
      printf '#!/bin/sh\n'
      printf ': > "%s/.called-bd-read"\n' "$root"
      printf 'if [ "$1" = "show" ]; then\n'
      printf '  for known in %s; do\n' "${known:-__снимок-пуст__}"
      printf '    [ "$2" = "$known" ] && exit 0\n'
      printf '  done\n'
      printf '  exit 1\n'
      printf 'fi\n'
      printf 'exit 0\n'
    } > "$root/scripts/bd-read.sh"
    chmod +x "$root/scripts/bd-read.sh"
  fi
  rm -f "$root/.called-bd-wt" "$root/.called-bd-read"
  printf '%s' "$root"
}

# Заглушка `bd` с заданным кодом возврата. Каталог свой на каждую заглушку, чтобы PATH
# кейса содержал ровно ту, которую кейс проверяет.
#   $1 — имя; $2 — код возврата `bd show`; $3 — код возврата ПРОБЫ `bd list` (умолчание 0).
# Проба отвечает на другой вопрос, чем `show`: «база задач вообще отвечает?». Умолчание 0 —
# «отвечает», потому что у большинства кейсов предмет проверки не окружение Beads, а разбор.
# Заглушка обязана различать команды: с единым кодом на всё она изображала бы отказ Dolt там,
# где кейс имеет в виду «задачи нет», и наоборот (внешнее ревью PR #634, проход 10).
make_bd_stub() {
  local dir="$TMP/bd-$1" probe="${3:-0}"
  mkdir -p "$dir"
  {
    printf '#!/bin/sh\n'
    printf 'if [ "$1" = "list" ]; then exit %s; fi\n' "$probe"
    printf 'exit %s\n' "$2"
  } > "$dir/bd"
  chmod +x "$dir/bd"
  printf '%s' "$dir"
}

# Заглушка `git`, которая КОРЕНЬ ОТДАЁТ, а на запросах класса окружения падает заданным кодом.
# Ровно эта форма и есть находка внешнего прохода 10: корень читается, все проверки кода
# возврата вокруг него проходят, а определение класса окружения внутри канон-библиотеки не
# отрабатывает — и его отказ прежде читался как содержательный ответ «не основной checkout».
#   $1 — имя; $2 — корень, который заглушка печатает; $3 — код отказа на запросах класса.
make_git_stub() {
  local dir="$TMP/git-$1"
  mkdir -p "$dir"
  {
    printf '#!/bin/sh\n'
    printf 'for a in "$@"; do\n'
    printf '  if [ "$a" = "--show-toplevel" ]; then printf %s\\\\n "%s"; exit 0; fi\n' '%s' "$2"
    printf 'done\n'
    printf 'exit %s\n' "$3"
  } > "$dir/git"
  chmod +x "$dir/git"
  printf '%s' "$dir"
}

hdr='| # | Severity | Заголовок | Файл:строка | Статус | Beads ID / Обоснование |'
sep='|---|---|---|---|---|---|'

# --- кейсы ------------------------------------------------------------------

# 1. Голый статус, валидный ID — проходит.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/plain-ok.md"
[ "$(gate_code "$TMP/plain-ok.md")" = "0" ] \
  && ok "голый статус с валидным ID проходит" \
  || not_ok "голый статус с валидным ID должен проходить"

# 2. РЕГРЕСС U2-m5b1: полужирный статус с валидным ID — тоже проходит (раньше строка не матчилась вовсе).
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | **defer to Beads** | **U2-abcd** |\n' "$hdr" "$sep" > "$TMP/bold-ok.md"
[ "$(gate_code "$TMP/bold-ok.md")" = "0" ] \
  && ok "полужирный статус с валидным ID проходит" \
  || not_ok "полужирный статус с валидным ID должен проходить"

# 3. ГЛАВНОЕ: полужирный статус с невалидным ID — гейт краснеет (до фикса молчал).
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | **defer to Beads** | позже |\n' "$hdr" "$sep" > "$TMP/bold-bad-id.md"
[ "$(gate_code "$TMP/bold-bad-id.md")" != "0" ] \
  && ok "полужирный статус с невалидным Beads ID останавливает гейт" \
  || not_ok "REGRESS U2-m5b1: невалидный ID под полужирным статусом прошёл молча"

# 4. Полужирный reject с пустым обоснованием — краснеет.
printf '%s\n%s\n| 1 | INFO | x | a.cs:1 | **reject with rationale** | — |\n' "$hdr" "$sep" > "$TMP/bold-empty.md"
[ "$(gate_code "$TMP/bold-empty.md")" != "0" ] \
  && ok "полужирный reject без обоснования останавливает гейт" \
  || not_ok "reject без обоснования под полужирным статусом прошёл молча"

# 5. Таблица есть, статус записан неизвестной формой — громкий АДРЕСНЫЙ стоп, не молчание.
#    Проверяется текст сообщения: стоп обязан называть саму строку и её статус, а не общее
#    «что-то не разобралось».
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | отложено в трекер | U2-abcd |\n' "$hdr" "$sep" > "$TMP/unknown-form.md"
out=$(run_gate "$TMP/unknown-form.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "строка таблицы с неизвестным статусом даёт адресный стоп"
else
  not_ok "строка с неизвестным статусом не дала адресного стопа (код $code)"
fi

# 6. Легитимная пустота «нет замечаний» — ложного стопа нет.
printf '%s\n%s\n| — | — | нет замечаний | — | — | — |\n' "$hdr" "$sep" > "$TMP/no-findings.md"
[ "$(gate_code "$TMP/no-findings.md")" = "0" ] \
  && ok "строка «нет замечаний» не вызывает ложный стоп" \
  || not_ok "ложный стоп на легитимной строке «нет замечаний»"

# 7. Заглушка «нет замечаний» в ОДНОМ отчёте не должна глушить проверку ДРУГОГО, где
#    таблица замечаний есть. Разбор обязан быть поотчётным, а не по сумме тел (найдено
#    исполнением при доводке PR).
RS=$(printf '\036')
{
  printf '%s\n%s\n| — | — | нет замечаний | — | — | — |\n' "$hdr" "$sep"
  printf '%s' "$RS"
  printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | отложено в трекер | U2-abcd |\n' "$hdr" "$sep"
} > "$TMP/two-reports.md"
out=$(run_gate "$TMP/two-reports.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "заглушка в одном отчёте не глушит проверку другого"
else
  not_ok "чужая заглушка «нет замечаний» погасила проверку соседнего отчёта (код $code)"
fi

# 8. Экранированный разделитель в ячейке не сдвигает колонки (защита прежнего раунда цела).
printf '%s\n%s\n| 1 | WARNING | a \\| b | a.cs:1 | **defer to Beads** | U2-abcd |\n' "$hdr" "$sep" > "$TMP/escaped.md"
[ "$(gate_code "$TMP/escaped.md")" = "0" ] \
  && ok "экранированный разделитель в ячейке не ломает разбор" \
  || not_ok "экранированный разделитель сдвинул колонки"

# 8a. Экранированный разделитель ВОССТАНАВЛИВАЕТСЯ в каждой колонке: диагностика обязана
#     назвать ячейку так, как её написал автор отчёта, а не показать служебный байт. Без
#     этого кейса подмена байта-разделителя в восстановлении номера и обоснования проходила
#     незамеченной — ни одна проверка на служебный байт не смотрит.
printf '%s\n%s\n| 1 \\| 2 | WARNING | x | a.cs:1 | defer to Beads | U2-abc\\|d |\n' "$hdr" "$sep" > "$TMP/escaped-payload.md"
out=$(run_gate "$TMP/escaped-payload.md"); code=$?
if [ "$code" != "0" ] \
   && printf '%s' "$out" | grep -F >/dev/null '#1 | 2' \
   && printf '%s' "$out" | grep -F >/dev/null "U2-abc|d"; then
  ok "экранированный разделитель восстановлен в номере и обосновании"
else
  not_ok "экранированный разделитель не восстановлен: диагностика показывает служебный байт (код $code)"
fi

# 8b. То же для колонки статуса.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer \\| to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/escaped-status.md"
out=$(run_gate "$TMP/escaped-status.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "defer | to Beads"; then
  ok "экранированный разделитель восстановлен в колонке статуса"
else
  not_ok "экранированный разделитель не восстановлен в статусе (код $code)"
fi

# 9. Таблица с отступом. Отступ снимается при расщеплении на ячейки, поэтому строка обязана
#    быть РАЗОБРАНА И ОТБРАКОВАНА по своему содержимому, а не остановить гейт по побочной
#    причине. Проверяется текст сообщения: он различает «строка разобрана и отбракована»
#    (адресный диагноз про Beads ID) и «строка не разобрана» (страховка-сирота).
printf '%s\n%s\n | 1 | WARNING | x | a.cs:1 | defer to Beads | позже |\n' "$hdr" "$sep" > "$TMP/indented.md"
out=$(run_gate "$TMP/indented.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "строка таблицы с отступом разбирается и отбраковывается адресно"
else
  not_ok "строка с отступом не разобрана: стоп пришёл не от проверки её содержимого (код $code)"
fi

# 9a. Обратная сторона того же свойства: та же строка с отступом и ВАЛИДНЫМ идентификатором
#     обязана пройти. Без этой половины кейс 9 был бы неотличим от «отступ всегда краснит».
printf '%s\n%s\n | 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/indented-ok.md"
[ "$(gate_code "$TMP/indented-ok.md")" = "0" ] \
  && ok "строка таблицы с отступом и валидным ID проходит" \
  || not_ok "ложный стоп на строке с отступом и валидным ID"

# 10. Таблица в цитате — то же самое: символ цитаты снимается, строка проверяется по
#     содержимому. Парная половина (цитата + валидный ID) — ниже, отдельным кейсом.
printf '%s\n%s\n> | 1 | WARNING | x | a.cs:1 | defer to Beads | позже |\n' "$hdr" "$sep" > "$TMP/quoted.md"
out=$(run_gate "$TMP/quoted.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "строка таблицы в цитате разбирается и отбраковывается адресно"
else
  not_ok "строка в цитате не разобрана: стоп пришёл не от проверки её содержимого (код $code)"
fi

# 11. «нет замечаний» в ПРОЗЕ отчёта не должно глушить проверку его же таблицы (F4).
printf 'По гигиене — нет замечаний.\n\n%s\n%s\n| 1 | WARNING | x | a.cs:1 | отложено в трекер | U2-abcd |\n' "$hdr" "$sep" > "$TMP/prose-stub.md"
[ "$(gate_code "$TMP/prose-stub.md")" != "0" ] \
  && ok "«нет замечаний» в прозе не глушит проверку таблицы" \
  || not_ok "заглушка в прозе погасила проверку таблицы замечаний"

# 12. В таблице соседствуют шаблонный статус и статус в ином регистре: вторая строка обязана
#     получить адресный стоп, а не уехать под прикрытием первой.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n| 2 | INFO | y | b.cs:2 | Fix now | — |\n' "$hdr" "$sep" > "$TMP/partial.md"
out=$(run_gate "$TMP/partial.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "статус в ином регистре рядом с шаблонным даёт адресный стоп"
else
  not_ok "строка со статусом в ином регистре уехала под прикрытием шаблонной соседки (код $code)"
fi

# --- теневые строки и невидимые символы -------------------------------------------------

# Неразрывный пробел U+00A0: обрезка краевых пробелов его намеренно не трогает, поэтому
# ячейка «defer to Beads<U+00A0>» до строгого сравнения доходит как есть и валидной не
# считается.
NBSP=$(printf '\302\240')

# 13. Неразрывный пробел после статуса: строка разбирается, но её статус строгое сравнение
#     не узнаёт. Без ветки по умолчанию она уходила молча вместе с невалидным ID.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads%s| позже |\n' "$hdr" "$sep" "$NBSP" > "$TMP/nbsp.md"
out=$(run_gate "$TMP/nbsp.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "неразрывный пробел после статуса даёт адресный стоп"
else
  not_ok "строка с неразрывным пробелом в статусе прошла молча — нет ветки по умолчанию в case (код $code)"
fi

# 14. Строка с отступом РЯДОМ с обычной: соседка её не покрывает, обе проверяются.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n | 2 | WARNING | y | b.cs:2 | defer to Beads | позже |\n' "$hdr" "$sep" > "$TMP/shadow-indent.md"
out=$(run_gate "$TMP/shadow-indent.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "строка с отступом рядом с обычной проверяется отдельно"
else
  not_ok "отступная строка прошла молча под прикрытием соседки (код $code)"
fi

# 15. Строка, у которой первая ячейка — прочерк: она НЕ разделитель шапки (разделителем
#     считается строка, где из дефисов состоят ВСЕ ячейки), поэтому обязана проверяться.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n| - | WARNING | y | b.cs:2 | отложено в трекер | позже |\n' "$hdr" "$sep" > "$TMP/shadow-dash.md"
out=$(run_gate "$TMP/shadow-dash.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "строка с прочерком в первой ячейке не зачтена как разделитель и проверяется"
else
  not_ok "строка с прочерком в первой ячейке зачтена как разделитель и прошла молча (код $code)"
fi

# 16. Строка после литерального байта-разделителя записей принадлежит УЖЕ ДРУГОМУ отчёту и
#     не имеет права читаться по шапке соседнего отчёта. Своей шапки у неё нет, поэтому
#     колонку статуса брать неоткуда — исход обязан быть громким и адресным ИМЕННО ПО ЭТОЙ
#     строке: в сообщении её собственный номер и её собственная ячейка статуса.
#     Кейс различает две развилки: при наследовании чужой шапки статус искался бы пятой
#     ячейкой, в строке из трёх её нет, и в сообщении оказался бы пустой статус вместо
#     `defer to Beads`. (Прежняя редакция кейса ждала здесь диагноз про Beads ID: колонку
#     статуса разбор подбирал по содержанию строки. Подбор снят внешним ревью PR #634 —
#     он же выбирал не ту колонку в шапках со свободными именами, — и безшапочный блок
#     теперь останавливает гейт, а не разбирается догадкой. Инвариант кейса тот же:
#     чужая шапка на строку не распространяется.)
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n%s| 2 | defer to Beads | позже |\n' "$hdr" "$sep" "$RS" > "$TMP/shadow-rs.md"
out=$(run_gate "$TMP/shadow-rs.md"); code=$?
if [ "$code" != "0" ] \
   && printf '%s' "$out" | grep -F >/dev/null '#2' \
   && printf '%s' "$out" | grep -F >/dev/null 'defer to Beads'; then
  ok "строка после байта-разделителя читается как своя, а не по шапке соседнего отчёта"
else
  not_ok "строка после литерального байта-разделителя прочитана по чужой шапке (код $code)"
fi

# --- формы записи статуса и привязка признака заглушки ----------------------

# 17. Статус в подчёркиваниях с невалидным ID: общая нормализация обязана снять `__`, иначе
#     строгое сравнение статус не узнает и вместо адресного диагноза про Beads ID придёт
#     «нераспознанный статус» — потому и проверяется текст сообщения, а не только код.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | __defer to Beads__ | позже |\n' "$hdr" "$sep" > "$TMP/underscore.md"
out=$(run_gate "$TMP/underscore.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "статус в подчёркиваниях разбирается, невалидный ID ловится адресно"
else
  not_ok "статус в подчёркиваниях не нормализован: адресной проверки ID не было (код $code)"
fi

# 18. То же для статуса в обратных кавычках.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | `defer to Beads` | позже |\n' "$hdr" "$sep" > "$TMP/backtick.md"
out=$(run_gate "$TMP/backtick.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "статус в обратных кавычках разбирается, невалидный ID ловится адресно"
else
  not_ok "статус в обратных кавычках не нормализован: адресной проверки ID не было (код $code)"
fi

# 19. Заглушка в прозе + строка с отступом: признак заглушки привязан к СТРОКЕ ТАБЛИЦЫ, а не
#     к телу отчёта. Если он начнёт искаться где угодно, строка не дойдёт до проверки, стоп
#     придёт от другой проверки с другим текстом, и этот кейс покраснеет.
printf 'По гигиене — нет замечаний.\n\n%s\n%s\n | 1 | WARNING | x | a.cs:1 | defer to Beads | позже |\n' "$hdr" "$sep" > "$TMP/prose-stub-shadow.md"
out=$(run_gate "$TMP/prose-stub-shadow.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "проза-заглушка не глушит проверку строки с отступом"
else
  not_ok "признак заглушки ищется вне строки таблицы: строка с отступом не проверена (код $code)"
fi

# 20. Законный статус «fix now»: автопроверять нечего, ложного стопа быть не должно —
#     иначе ветка по умолчанию накрывает и валидные строки.
printf '%s\n%s\n| 1 | CRITICAL | x | a.cs:1 | fix now | закрыт аспектом «архитектура» |\n' "$hdr" "$sep" > "$TMP/fixnow.md"
[ "$(gate_code "$TMP/fixnow.md")" = "0" ] \
  && ok "статус «fix now» проходит без ложного стопа" \
  || not_ok "ложный стоп на законном статусе «fix now»"

# 21. Разделитель с выравниванием — не строка данных: он не уходит ни в разбор, ни в
#     страховку, поэтому ложного стопа быть не должно.
printf '%s\n|:---|:---:|---|---|---|---:|\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" > "$TMP/aligned-sep.md"
[ "$(gate_code "$TMP/aligned-sep.md")" = "0" ] \
  && ok "разделитель с выравниванием не считается неразобранной строкой" \
  || not_ok "ложный стоп на разделителе с выравниванием"

# --- разбор привязан к БЛОКУ таблицы, а не к числу колонок ------------------------------
# Шапки ниже — реальные формы из отчётов PR #613-#634: три, четыре и пять колонок.
# До привязки к блоку три-четыре колонки проходили МОЛЧА, пять давали жёсткий стоп.

hdr3='| # | Находка | Статус |'
sep3='|---|---|---|'
hdr4='| # | Severity | Заголовок | Статус |'
sep4='|---|---|---|---|'
hdr5loc='| # | Severity | Заголовок | Файл:строка | Статус |'
hdr5why='| # | Severity | Заголовок | Статус | Обоснование |'
sep5='|---|---|---|---|---|'

# 22. ТРИ колонки без платёжной ячейки в шапке: блок опознан ПО СОДЕРЖАНИЮ — первая строка
#     несёт канонический статус, поэтому таблица признана таблицей замечаний, и вторая
#     строка с нешаблонным статусом получает адресный стоп.
printf '%s\n%s\n| 1 | что-то поехало | fix now |\n| 2 | другое | эскалация |\n' "$hdr3" "$sep3" > "$TMP/cols3-bad.md"
out=$(run_gate "$TMP/cols3-bad.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "таблица на три колонки: канонический статус соседней строки опознаёт блок, нешаблонный даёт адресный стоп"
else
  not_ok "таблица на три колонки прошла молча — опознание блока по содержанию строк не работает (код $code)"
fi

# 23. ТРИ колонки, законный статус — ложного стопа быть не должно.
printf '%s\n%s\n| 1 | что-то поехало | fix now |\n' "$hdr3" "$sep3" > "$TMP/cols3-ok.md"
[ "$(gate_code "$TMP/cols3-ok.md")" = "0" ] \
  && ok "таблица на три колонки с законным статусом проходит" \
  || not_ok "ложный стоп на таблице из трёх колонок с законным статусом"

# 24. ЧЕТЫРЕ колонки: колонки платежа в таблице нет вовсе, а статус требует Beads ID —
#     стоп, а не тишина. Диагноз АДРЕСНЫЙ: чинить надо шапку, а не ячейку.
printf '%s\n%s\n| 1 | WARNING | x | defer to Beads |\n' "$hdr4" "$sep4" > "$TMP/cols4-defer.md"
out=$(run_gate "$TMP/cols4-defer.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не названа колонка идентификатора задачи"; then
  ok "четыре колонки: defer без колонки идентификатора останавливает гейт адресно"
else
  not_ok "четыре колонки: defer без Beads ID прошёл молча (код $code): $(printf '%s' "$out" | head -1)"
fi

# 25. ЧЕТЫРЕ колонки, «fix now» — ложного стопа быть не должно (форма отчётов #614/#615/#624).
printf '%s\n%s\n| 1 | WARNING | x | fix now |\n' "$hdr4" "$sep4" > "$TMP/cols4-ok.md"
[ "$(gate_code "$TMP/cols4-ok.md")" = "0" ] \
  && ok "таблица на четыре колонки с «fix now» проходит" \
  || not_ok "ложный стоп на таблице из четырёх колонок"

# 26. ПЯТЬ колонок (файл вместо обоснования), «fix now» — ложного стопа быть не должно.
#     До фикса такая таблица давала жёсткий стоп «ни одной строки не разобрано».
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | fix now |\n' "$hdr5loc" "$sep5" > "$TMP/cols5-ok.md"
[ "$(gate_code "$TMP/cols5-ok.md")" = "0" ] \
  && ok "таблица на пять колонок с «fix now» проходит" \
  || not_ok "ложный стоп на таблице из пяти колонок"

# 27. ПЯТЬ колонок, где обоснование стоит ЧЕТВЁРТЫМ по счёту от начала: индекс колонки
#     берётся из шапки, а не из фиксированной позиции — пустое обоснование обязано краснеть.
printf '%s\n%s\n| 1 | INFO | x | reject with rationale | — |\n' "$hdr5why" "$sep5" > "$TMP/cols5-reject.md"
out=$(run_gate "$TMP/cols5-reject.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "не имеет обоснования"; then
  ok "пять колонок: колонка обоснования найдена по шапке, пустое обоснование краснеет"
else
  not_ok "пять колонок: обоснование не проверено — позиция колонки угадывается (код $code)"
fi

# 28. Строка БЕЗ ведущей вертикальной черты — законная разметка таблиц: обязана разбираться,
#     а не выпадать и из разбора, и из страховок.
printf '%s\n%s\n1 | WARNING | x | a.cs:1 | defer to Beads | позже |\n' "$hdr" "$sep" > "$TMP/no-lead-pipe.md"
out=$(run_gate "$TMP/no-lead-pipe.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "строка без ведущей вертикальной черты разбирается и проверяется"
else
  not_ok "строка без ведущей черты выпала из проверки (код $code)"
fi

# 29. Пустая первая ячейка: строка обязана ПРОВЕРЯТЬСЯ, а не пропускаться. Прежний цикл
#     пропускал её по пустому номеру, при этом страховка считала отчёт покрытым.
printf '%s\n%s\n|  | WARNING | x | a.cs:1 | defer to Beads | позже |\n' "$hdr" "$sep" > "$TMP/empty-num.md"
out=$(run_gate "$TMP/empty-num.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "строка с пустой первой ячейкой проверяется, а не пропускается"
else
  not_ok "строка с пустой первой ячейкой пропущена циклом (код $code)"
fi

# 30. Посторонняя таблица на шесть колонок, замечаний нет вовсе — ложного стопа быть не должно.
printf 'Сводка внешнего цикла.\n\n| Итерация | Commit | Ревьюер A | Ревьюер B | Находок | Итог |\n%s\n| 1 | abc1234 | clean | clean | 0 | зелено |\n' "$sep" > "$TMP/foreign6.md"
[ "$(gate_code "$TMP/foreign6.md")" = "0" ] \
  && ok "посторонняя таблица на шесть колонок не даёт ложного стопа" \
  || not_ok "ложный стоп на посторонней таблице без единого замечания"

# 31. Посторонняя таблица со своей колонкой «Статус», но без колонки «#» — не таблица
#     замечаний: её строки не разбираются и ложного стопа не дают.
printf '| Требование | Статус |\n|---|---|\n| дока обновлена | выполнено |\n' > "$TMP/foreign-status.md"
[ "$(gate_code "$TMP/foreign-status.md")" = "0" ] \
  && ok "таблица со своей колонкой «Статус» без колонки «#» не считается таблицей замечаний" \
  || not_ok "ложный стоп на посторонней таблице с колонкой «Статус»"

# --- опознание таблицы замечаний ПО СОДЕРЖАНИЮ СТРОК: обе стороны ложного стопа ---------
# Прежний признак («первая ячейка ровно `#`» + ячейка «Статус») ошибался в обе стороны и
# оставлял автору отчёта выбор только между ложным стопом и молчанием. Кейсы ниже держат
# закрытыми обе стороны сразу: посторонние таблицы молчат, настоящие — проверяются.

# 32. ЛОЖНЫЙ СТОП НА ПОСТОРОННЕЙ ТАБЛИЦЕ (сторона А). Таблица требований со своей колонкой
#     «Статус» И колонкой «#» — прежний признак опознавал её как таблицу замечаний, и её
#     «выполнено» давало отказ гейта. Инвариант 6 контракта PR: ложного стопа быть не должно.
printf 'Проверка требований.\n\n| # | Требование | Статус |\n%s\n| 1 | дока обновлена | выполнено |\n| 2 | индекс синхронизирован | выполнено |\n' "$sep3" > "$TMP/req-table.md"
[ "$(gate_code "$TMP/req-table.md")" = "0" ] \
  && ok "таблица требований с колонками «#» и «Статус» не даёт ложного стопа" \
  || not_ok "ложный стоп на таблице требований — опознание снова держится на форме шапки"

# 33. ЛОЖНЫЙ СТОП НА ПОСТОРОННЕЙ ТАБЛИЦЕ (сторона А, вторая форма) — таблица покрытия.
printf '| # | Инвариант | Тест | Статус |\n%s\n| 1 | разбор по шапке | finalize-triage-parse.test.sh:27 | покрыт |\n' "$sep4" > "$TMP/cov-table.md"
[ "$(gate_code "$TMP/cov-table.md")" = "0" ] \
  && ok "таблица покрытия со своей колонкой «Статус» не даёт ложного стопа" \
  || not_ok "ложный стоп на таблице покрытия"

# 34. ЛОЖНЫЙ СТОП НА НАСТОЯЩЕЙ ТАБЛИЦЕ (сторона Б). Шапка `| № | ... | Статус | Beads ID |`
#     несёт полную подпись шаблона reviewer.md — таблица обязана разбираться, а не уходить
#     в страховку-сироту. Прежний признак блокировал готовность на законном отчёте.
printf '| № | Заголовок | Статус | Beads ID |\n%s\n| 1 | что-то | defer to Beads | U2-abcd |\n' "$sep4" > "$TMP/real-numero.md"
[ "$(gate_code "$TMP/real-numero.md")" = "0" ] \
  && ok "настоящая таблица замечаний с шапкой «№ … Статус … Beads ID» разбирается без ложного стопа" \
  || not_ok "ложный стоп на настоящей таблице замечаний с шапкой «№ … Beads ID»"

# 35. Та же шапка, но Beads ID невалиден: строки действительно ПРОВЕРЯЮТСЯ, а не просто
#     «не краснеют». Без этого кейса предыдущий был бы неотличим от полного молчания.
printf '| № | Заголовок | Статус | Beads ID |\n%s\n| 1 | что-то | defer to Beads | позже |\n' "$sep4" > "$TMP/real-numero-bad.md"
out=$(run_gate "$TMP/real-numero-bad.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "шапка «№ … Beads ID»: строки проверяются — невалидный ID ловится адресно"
else
  not_ok "шапка «№ … Beads ID»: строки не проверяются (код $code)"
fi

# 36. Реальная шапка отчёта PR #633 — `| ID | Severity | Находка | Место | Статус |`.
#     Платёжной ячейки в ней нет, поэтому блок опознаётся ПО СОДЕРЖАНИЮ: канонический
#     статус первой строки делает таблицу таблицей замечаний, и вторая строка с нешаблонным
#     статусом получает громкий стоп.
printf '| ID | Severity | Находка | Место | Статус |\n%s\n| F1 | CRITICAL | x | a.cs:1 | fix now |\n| F2 | MINOR | y | b.cs:2 | эскалация |\n' "$sep5" > "$TMP/real-pr633.md"
out=$(run_gate "$TMP/real-pr633.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "шапка «ID … Место … Статус» (форма PR #633): строки проверяются"
else
  not_ok "шапка «ID … Место … Статус»: строки не проверяются (код $code)"
fi

# 37. Та же шапка PR #633, все статусы шаблонные — ложного стопа быть не должно.
printf '| ID | Severity | Находка | Место | Статус |\n%s\n| F1 | CRITICAL | x | a.cs:1 | fix now |\n| F2 | MINOR | y | b.cs:2 | fix now |\n' "$sep5" > "$TMP/real-pr633-ok.md"
[ "$(gate_code "$TMP/real-pr633-ok.md")" = "0" ] \
  && ok "шапка «ID … Место … Статус» с шаблонными статусами проходит без ложного стопа" \
  || not_ok "ложный стоп на реальной шапке отчёта PR #633"

# 37a. РЕАЛЬНАЯ ФОРМА ОТЧЁТОВ PR #645: колонка статуса названа «Решение», ячейки «Статус» в
#      шапке нет вовсе. Колонка обязана находиться ПО СОДЕРЖАНИЮ строк, а сама шапка —
#      опознаваться по строке-разделителю под ней и НЕ уходить в разбор как строка данных.
#      Без любой из этих двух половин на каждой строке законной таблицы триажа был громкий
#      стоп (проверено на телах PR #645 — 42 ложных стопа).
printf '| Класс находки | Решение | Результат |\n%s\n| Сквозной publication adapter | fix now | подключён к штатным путям |\n| Косвенные исполнители shell | fix now | закрыт общим разбором |\n' "$sep3" > "$TMP/pr645-form.md"
out=$(run_gate "$TMP/pr645-form.md"); code=$?
if [ "$code" = "0" ]; then
  ok "шапка «Класс находки | Решение | Результат»: ложного стопа нет ни на шапке, ни на строках"
else
  not_ok "ложный стоп на реальной форме отчётов PR #645 (код $code): $(printf '%s' "$out" | head -1)"
fi

# 37b. Та же форма, но строка неразрешена: строки этой таблицы действительно ПРОВЕРЯЮТСЯ,
#      а не просто «не краснеют».
printf '| Класс находки | Решение | Результат |\n%s\n| Сквозной publication adapter | defer to Beads | позже |\n' "$sep3" > "$TMP/pr645-form-bad.md"
out=$(run_gate "$TMP/pr645-form-bad.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не названа колонка идентификатора задачи"; then
  ok "шапка «Класс находки | Решение | Результат»: строки проверяются"
else
  not_ok "шапка «Класс находки | Решение | Результат»: строки не проверяются (код $code): $(printf '%s' "$out" | head -1)"
fi

# 37c. Лишняя строка из дефисов ПОСРЕДИ таблицы: правило «шапка стоит перед разделителем»
#      обязано срабатывать один раз на блок. Иначе второй разделитель вычеркнул бы
#      предыдущую строку замечания из проверки — молчаливый пропуск.
printf '| Класс находки | Решение | Результат |\n%s\n| x | defer to Beads | позже |\n%s\n| y | fix now | закрыт |\n' "$sep3" "$sep3" > "$TMP/second-delim.md"
out=$(run_gate "$TMP/second-delim.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не названа колонка идентификатора задачи"; then
  ok "лишняя строка из дефисов не вычёркивает предыдущую строку замечания"
else
  not_ok "вторая строка-разделитель вычеркнула строку замечания из проверки (код $code): $(printf '%s' "$out" | head -1)"
fi

# 38. ЗАЯВЛЕННЫЙ ПРЕДЕЛ (контракт PR, предел 1 в новой редакции механизма): блок без полной
#     подписи шаблона, в котором НИ ОДНА строка не несёт канонического статуса и ни одна
#     ячейка не похожа на статус триажа, отличить от посторонней таблицы нечем — он молчит.
#     Кейс фиксирует предел ЯВНО: если поведение изменится, изменение будет замечено.
printf '%s\n%s\n| 1 | что-то поехало | эскалация |\n' "$hdr3" "$sep3" > "$TMP/limit-silent.md"
[ "$(gate_code "$TMP/limit-silent.md")" = "0" ] \
  && ok "заявленный предел: блок без подписи и без канонического статуса молчит (неотличим от посторонней таблицы)" \
  || not_ok "поведение на заявленном пределе изменилось — сверь контракт PR"

# 39. Обратная сторона предела: та же таблица, но статус ЗАЯВЛЕН с припиской — молчания
#     быть не должно, срабатывает страховка-сирота.
printf '%s\n%s\n| 1 | что-то поехало | fix now (правкой формулировки) |\n' "$hdr3" "$sep3" > "$TMP/limit-suffix.md"
out=$(run_gate "$TMP/limit-suffix.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "вне таблицы замечаний"; then
  ok "статус с припиской в блоке без подписи даёт громкий стоп, а не молчание"
else
  not_ok "статус с припиской в блоке без подписи прошёл молча (код $code)"
fi

# 40. Та же страховка обязана быть ШИРЕ разбора: статус с припиской вне распознанного блока
#     тоже ловится. Иначе связка «блок не признан + приписка к статусу» снова даёт тишину.
printf 'Итог прохода.\n\n| 1 | WARNING | x | a.cs:1 | fix now — позже | — |\n' > "$TMP/orphan-suffix.md"
out=$(run_gate "$TMP/orphan-suffix.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "вне таблицы замечаний"; then
  ok "страховка-сирота шире разбора: статус с припиской вне блока ловится"
else
  not_ok "статус с припиской вне распознанного блока прошёл молча (код $code)"
fi

# 41. Строка таблицы в цитате с ВАЛИДНЫМ ID — ложного стопа быть не должно. Вместе с кейсом
#     «цитата с невалидным ID» это закрепляет снятие символа цитаты: без него колонки
#     сдвигаются и валидная строка краснеет.
printf '%s\n%s\n> | 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/quoted-ok.md"
[ "$(gate_code "$TMP/quoted-ok.md")" = "0" ] \
  && ok "строка таблицы в цитате с валидным ID проходит" \
  || not_ok "ложный стоп на цитированной строке с валидным ID — сдвинулись колонки"

# 42. Блок КОНЧАЕТСЯ на первой нетабличной строке: посторонняя таблица ПОСЛЕ таблицы
#     замечаний не должна разбираться по её шапке — иначе своя колонка чужой таблицы
#     попадает в проверку статуса и даёт ложный стоп (так устроены реальные отчёты:
#     таблица замечаний, проза, сводка прогонов).
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | fix now | закрыт аспектом |\n\nПрогоны:\n\n| Гейт | Результат |\n|---|---|\n| фикстура | зелено |\n' "$hdr" "$sep" > "$TMP/block-ends.md"
[ "$(gate_code "$TMP/block-ends.md")" = "0" ] \
  && ok "блок замечаний кончается на нетабличной строке — чужая таблица ниже не разбирается" \
  || not_ok "ложный стоп: шапка таблицы замечаний утекла в постороннюю таблицу ниже"

# --- НАХОДКА внешнего прохода 10: ОПОЗНАНИЕ БЛОКА — СОВОКУПНОСТЬ, а не один признак -------
# Оба пути ниже давали ложный стоп на посторонней таблице (инвариант 6 контракта PR): один
# признак — канонический статус в одной строке из многих — тянул в разбор ВСЮ таблицу, а
# признак шапки набирался КУСКОМ СЛОВА.

# 42a. Таблица требований, где одна строка из трёх написана как `fix now`. Соседние строки
#      («выполнено») к триажу отношения не имеют и краснеть не должны. Стоп остаётся ровно на
#      той строке, которая ЗАЯВИЛА статус триажа, — это объявленное поведение страховки-сироты
#      (кейсы 39-40), и сужать его находка не просила.
printf 'Требования контракта.\n\n| # | Требование | Статус |\n%s\n| 1 | дока обновлена | выполнено |\n| 2 | замечания закрыты | fix now |\n| 3 | индекс синхронизирован | выполнено |\n' "$sep3" > "$TMP/req-one-canon.md"
out=$(run_gate "$TMP/req-one-canon.md"); code=$?
if { printf '%s' "$out" | grep -F >/dev/null "нераспознанный статус"; search_status=("${PIPESTATUS[@]}"); [ "${search_status[*]}" = "0 1" ]; } \
   && printf '%s' "$out" | grep -F >/dev/null "вне таблицы замечаний"; then
  ok "одна строка «fix now» не втягивает в разбор всю постороннюю таблицу — соседнее «выполнено» не краснеет"
else
  not_ok "REGRESS прохода 10: соседняя строка посторонней таблицы дала ложный стоп (код $code): $(printf '%s' "$out" | head -1)"
fi

# 42b. Второй путь того же ложного стопа: шапка совпадала с признаком замечания «Файл»
#      ПОДСТРОКОЙ (`Файлы требования`), таблица получала полную подпись шаблона и разбиралась
#      построчно. Канонических статусов в ней нет вовсе — исход обязан быть полное молчание.
printf 'Сводка требований.\n\n| # | Файлы требования | Статус | Обоснование |\n%s\n| 1 | docs/INDEX.md | выполнено | синхронизирован |\n| 2 | AGENTS.md | выполнено | правок не требует |\n' "$sep4" > "$TMP/req-filesub.md"
[ "$(gate_code "$TMP/req-filesub.md")" = "0" ] \
  && ok "признак замечания не набирается куском слова: «Файлы требования» не называет колонку «Файл»" \
  || not_ok "REGRESS прохода 10: посторонняя таблица опознана по подстроке в имени колонки"

# 42c. Контроль к 42b — иначе он был бы неотличим от «опознание по подписи выключено». Та же
#      таблица, но колонка названа ЦЕЛЫМ именем: подпись шаблона набрана, и «выполнено» краснеет.
#      ⚠️ Кейс закрепляет РАБОТОСПОСОБНОСТЬ опознания, а не «правильность» стопа на посторонней
#      таблице: структурно такой реестр неотличим от таблицы замечаний, стоп — осознанный промах
#      в безопасную сторону, ЗАЯВЛЕННЫЙ ПРЕДЕЛ контракта PR #634 (U2-14fk). Инвариант 6
#      обещает молчание только блокам, НЕ набравшим подписи (итерация 7 внутреннего ревью).
printf '| # | Файл | Статус | Обоснование |\n%s\n| 1 | docs/INDEX.md | выполнено | синхронизирован |\n' "$sep4" > "$TMP/req-filewhole.md"
out=$(run_gate "$TMP/req-filewhole.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "нераспознанный статус"; then
  ok "целое имя «Файл» подпись шаблона по-прежнему набирает — сужение не выключило опознание"
else
  not_ok "опознание по подписи шаблона выключено вместе с подстрокой (код $code): $(printf '%s' "$out" | head -1)"
fi

# 42d. Составное имя ячейки — это набор ЦЕЛЫХ имён, а не подстрока: `Файл:строка` называет
#      колонку «Файл» законно (так публикует шаблон reviewer.md).
printf '| # | Файл:строка | Статус | Обоснование |\n%s\n| 1 | a.cs:1 | выполнено | закрыт |\n' "$sep4" > "$TMP/req-composite.md"
out=$(run_gate "$TMP/req-composite.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "нераспознанный статус"; then
  ok "составное имя «Файл:строка» называет колонку целой своей частью — шаблонные формы не потеряны"
else
  not_ok "составное имя перестало называть колонку: разбор шаблонной шапки сломан (код $code): $(printf '%s' "$out" | head -1)"
fi

# --- страховка ШИРЕ разбора: закрытый класс молчаливого пропуска (U2-m5b1) --------------
# Общее для секции: строка, ЗАЯВЛЯЮЩАЯ статус триажа, обязана дойти до проверки. Не дошла —
# громкий стоп. Форма записи статуса (выделение, обрамляющий шум, регистр) и текст соседних
# ячеек на это влиять не вправе.

# Шапка БЕЗ ячейки «Статус»: имени колонки статуса в ней нет, поэтому колонку приходится
# искать по содержанию строк. Если статус записан РАСПОЗНАВАЕМО, но не канонически (курсив,
# иной регистр, подчёркивания), исход обязан быть громким в любом случае — либо адресный
# «нераспознанный статус», если содержание строки колонку всё-таки указало, либо
# страховка-сирота, если не указало. Молчания нет ни в одном из вариантов.
hdrno='| № | Severity | Заголовок | Решение |'

# 43. Курсивный статус в блоке, у шапки которого имени колонки статуса нет. Общая
#     нормализация одиночный `*` не снимает намеренно, поэтому колонку указывает опознание
#     по содержанию: оно снимает выделение локально и видит канонический статус. Дальше
#     строгий разбор получает ячейку как есть, со звёздочками, и даёт адресный стоп.
#     До фикса: полная тишина.
printf '%s\n%s\n| 1 | WARNING | x | *defer to Beads* |\n' "$hdrno" "$sep4" > "$TMP/italic-orphan.md"
out=$(run_gate "$TMP/italic-orphan.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "курсивный статус в блоке без имени колонки даёт адресный стоп"
else
  not_ok "курсивный статус в блоке без имени колонки прошёл молча (код $code)"
fi

# 43a. Тот же курсивный статус, но в блоке С ячейкой «Статус» в шапке: колонка берётся по
#      имени, а не по содержанию. Исход обязан быть тот же — молчания нет ни в одной из
#      двух развилок поиска колонки.
printf '| № | Severity | Заголовок | Статус |\n%s\n| 1 | WARNING | x | *defer to Beads* |\n' "$sep4" > "$TMP/italic-statuscol.md"
out=$(run_gate "$TMP/italic-statuscol.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "курсивный статус в блоке с колонкой «Статус» даёт адресный стоп"
else
  not_ok "курсивный статус в блоке с колонкой «Статус» прошёл молча (код $code)"
fi

# 44. РЕГРЕСС строгого разбора: тот же курсивный статус в блоке с полной подписью шаблона
#     обязан краснеть как «нераспознанный статус», а не считаться валидным defer. Ни широкое
#     опознание страховки, ни каноническое опознание блока не вправе протечь в `case`.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | *defer to Beads* | U2-abcd |\n' "$hdr" "$sep" > "$TMP/italic-inblock.md"
out=$(run_gate "$TMP/italic-inblock.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "курсивный статус внутри блока остаётся нераспознанным для строгого разбора"
else
  not_ok "REGRESS: курсивный статус зачтён строгим разбором как валидный (код $code)"
fi

# 45. Фраза «нет замечаний» в свободном тексте строки + пустое обоснование при валидном
#     статусе reject. До фикса признак заглушки отбрасывал строку ДО взгляда на её статус.
printf '%s\n%s\n| 1 | INFO | по гигиене нет замечаний | a.cs:1 | reject with rationale | — |\n' "$hdr" "$sep" > "$TMP/stub-phrase-reject.md"
out=$(run_gate "$TMP/stub-phrase-reject.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "не имеет обоснования"; then
  ok "фраза «нет замечаний» в строке не глушит проверку пустого обоснования"
else
  not_ok "строка с распознаваемым статусом отброшена признаком заглушки (код $code)"
fi

# 46. То же для defer: фраза стоит РАНЬШЕ колонки статуса, и прежний ранний возврат признака
#     заглушки не давал увидеть статус в следующей ячейке.
printf '%s\n%s\n| 1 | INFO | нет замечаний по стилю | a.cs:1 | defer to Beads | позже |\n' "$hdr" "$sep" > "$TMP/stub-phrase-defer.md"
out=$(run_gate "$TMP/stub-phrase-defer.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "фраза «нет замечаний» до колонки статуса не глушит проверку Beads ID"
else
  not_ok "ранний возврат признака заглушки скрыл строку с валидным статусом (код $code)"
fi

# 47. Обратная сторона: настоящая заглушка БЕЗ статуса триажа по-прежнему не краснит —
#     привязка признака к отсутствию статуса не должна оборачиваться ложным стопом.
printf '%s\n%s\n| — | — | по стилю нет замечаний | — | — | — |\n' "$hdr" "$sep" > "$TMP/legit-stub.md"
[ "$(gate_code "$TMP/legit-stub.md")" = "0" ] \
  && ok "заглушка «нет замечаний» без статуса триажа не вызывает ложный стоп" \
  || not_ok "ложный стоп на легитимной строке-заглушке"

# 48. Строка целиком из прочерков — тоже законная пустота (вторая половина признака заглушки).
printf '%s\n%s\n| - | - | - | - | - | - |\n' "$hdr" "$sep" > "$TMP/all-dashes.md"
[ "$(gate_code "$TMP/all-dashes.md")" = "0" ] \
  && ok "строка целиком из прочерков не вызывает ложный стоп" \
  || not_ok "ложный стоп на строке из одних прочерков"

# 49. Обрамляющий шум вокруг статуса (кавычки-ёлочки). Каноническим такой статус не
#     считается, имени колонки в шапке нет — значит колонку статуса взять неоткуда и блок
#     таблицей замечаний не признан. Строку обязана поймать страховка-сирота.
printf '%s\n%s\n| 1 | WARNING | x | «fix now» |\n' "$hdrno" "$sep4" > "$TMP/noise-orphan.md"
out=$(run_gate "$TMP/noise-orphan.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "вне таблицы замечаний"; then
  ok "статус в обрамляющем шуме в непризнанном блоке даёт громкий стоп"
else
  not_ok "статус в кавычках в непризнанном блоке прошёл молча (код $code)"
fi

# 50. Иное написание регистра в блоке без имени колонки — та же тишина до фикса.
printf '%s\n%s\n| 1 | WARNING | x | Defer to Beads |\n' "$hdrno" "$sep4" > "$TMP/case-orphan.md"
out=$(run_gate "$TMP/case-orphan.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "статус в ином регистре в блоке без имени колонки даёт адресный стоп"
else
  not_ok "статус в ином регистре в блоке без имени колонки прошёл молча (код $code)"
fi

# 51. Статус в подчёркиваниях И строка без ведущей вертикальной черты одновременно: два
#     признака, каждый из которых поодиночке уже проверен, вместе не должны давать тишину.
printf '%s\n%s\n1 | WARNING | x | _fix now_ |\n' "$hdrno" "$sep4" > "$TMP/underscore-orphan.md"
out=$(run_gate "$TMP/underscore-orphan.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "статус в подчёркиваниях без ведущей черты даёт адресный стоп"
else
  not_ok "статус в подчёркиваниях без ведущей черты прошёл молча (код $code)"
fi

# 52. Строка КОРОЧЕ шапки: колонки статуса в ней нет вовсе (индекс статуса больше числа
#     ячеек), значение пустое. Строка обязана дойти до проверки и получить стоп, а не выпасть
#     по пустому статусу — признак заглушки её тоже не глушит, статус триажа в ней есть.
printf '%s\n%s\n| 1 | WARNING | fix now |\n' "$hdr" "$sep" > "$TMP/short-row.md"
out=$(run_gate "$TMP/short-row.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "строка короче шапки доходит до проверки с пустым статусом"
else
  not_ok "строка короче шапки выпала из проверки (код $code)"
fi

# --- колонка обоснования берётся ПО ШАПКЕ, а не по фиксированной позиции ----------------
# Симметрия к колонке статуса. Обе половины обязаны краснеть от точечного отката индекса:
# без кейсов ниже подмена индекса колонки платежа фиксированной шестой колонкой оставляла
# прогон зелёным, и гейт МОЛЧА пропускал неразрешённое замечание.
# ⚠️ Кейсы ниже держат ФИКСИРОВАННУЮ позицию; откат к смещению «соседняя со статусом» они не
# ловят — колонка платежа стоит здесь сразу за статусом. Этот класс закрывает секция «колонки
# берутся ТОЛЬКО по имени» ниже (кейсы 54a–54c), заведённая по внешнему ревью PR #634.

hdrpay='| # | Severity | Статус | Обоснование | Файл:строка | Заметка |'

# 53. Обоснование стоит ЧЕТВЁРТОЙ колонкой, а шестая непуста: отклонённое замечание с
#     прочерком вместо обоснования обязано краснеть. При откате индекса к шестой колонке
#     гейт видит текст заметки и молчит.
printf '%s\n%s\n| 1 | INFO | reject with rationale | — | a.cs:1 | подробности в треде |\n' "$hdrpay" "$sep" > "$TMP/pay-col4-reject.md"
out=$(run_gate "$TMP/pay-col4-reject.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "не имеет обоснования"; then
  ok "обоснование в четвёртой колонке: пустое обоснование краснеет при непустой шестой"
else
  not_ok "индекс колонки обоснования угадывается: пустое обоснование прошло молча (код $code)"
fi

# 54. То же для defer: в этой шапке названа только колонка обоснования, колонки
#     идентификатора нет. Валидный идентификатор в ШЕСТОЙ («Заметка») его не заменяет —
#     стоп адресный, а не зачёт по чужой колонке.
printf '%s\n%s\n| 1 | WARNING | defer to Beads | позже | b.cs:2 | U2-abcd |\n' "$hdrpay" "$sep" > "$TMP/pay-col4-defer.md"
out=$(run_gate "$TMP/pay-col4-defer.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не названа колонка идентификатора задачи"; then
  ok "колонка идентификатора не названа: defer краснеет адресно, «Заметка» с валидным ID не засчитывается"
else
  not_ok "индекс колонки идентификатора угадывается: defer прошёл по чужой колонке (код $code): $(printf '%s' "$out" | head -1)"
fi

# --- колонки берутся ТОЛЬКО по имени ячейки шапки ---------------------------------------
# Общее для секции (внешнее ревью PR #634, два P1 одного корня): колонка выбиралась
# ПОЗИЦИОННО («соседняя со статусом» — обоснование) или ЭВРИСТИЧЕСКИ («первая ячейка строки
# с каноническим текстом» — статус). Обе развилки давали МОЛЧАЛИВЫЙ ПРОПУСК: проверялась не
# та ячейка, которую написал автор отчёта. Кейсы ниже прогоняют обе.

# 54a. НЕСМЕЖНЫЙ платёж: колонка «Beads ID» стоит не сразу за статусом, а через одну, и она
#      ПУСТА. Соседняя колонка при этом несёт похожий на идентификатор текст. Гейт обязан
#      смотреть в названную колонку и краснеть, а не засчитывать соседа.
hdrgap='| # | Статус | Комментарий | Beads ID |'
printf '%s\n%s\n| 1 | defer to Beads | U2-abcd | |\n' "$hdrgap" "$sep4" > "$TMP/gap-empty-id.md"
out=$(run_gate "$TMP/gap-empty-id.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "несмежная колонка «Beads ID»: пустой идентификатор краснеет, соседняя ячейка не засчитывается"
else
  not_ok "несмежный платёж: пустой Beads ID прошёл молча по соседней ячейке (код $code)"
fi

# 54b. Обратная сторона того же: названная колонка заполнена верно, а соседняя со статусом
#      несёт прозу. Ложного стопа быть не должно — иначе правка меняет промах с одного
#      направления на другое.
printf '%s\n%s\n| 1 | defer to Beads | см. тред | U2-abcd |\n' "$hdrgap" "$sep4" > "$TMP/gap-valid-id.md"
[ "$(gate_code "$TMP/gap-valid-id.md")" = "0" ] \
  && ok "несмежная колонка «Beads ID»: верный идентификатор проходит, проза соседа не мешает" \
  || not_ok "ложный стоп: проза в соседней со статусом колонке принята за Beads ID"

# 54c. То же для обоснования отклонения: названная колонка «Обоснование» несёт прочерк,
#      соседняя со статусом — осмысленный текст. Краснеть обязана названная.
hdrgapw='| # | Статус | Заметка | Обоснование |'
printf '%s\n%s\n| 1 | reject with rationale | подробности в треде | — |\n' "$hdrgapw" "$sep4" > "$TMP/gap-empty-why.md"
out=$(run_gate "$TMP/gap-empty-why.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "не имеет обоснования"; then
  ok "несмежная колонка «Обоснование»: прочерк краснеет, соседняя заметка не засчитывается"
else
  not_ok "несмежное обоснование: прочерк прошёл молча по соседней ячейке (код $code)"
fi

# 54d. СТАТУС берётся по имени колонки, а не «первой канонической ячейкой строки». Шапка
#      PR #645 (`Класс находки | Решение | Результат`), фактическое решение — `эскалация`,
#      а в колонке результата стоит слово `fix now`. До правки разбор брал первую
#      каноническую ячейку строки, то есть РЕЗУЛЬТАТ, и молча засчитывал замечание.
printf '| Класс находки | Решение | Результат |\n%s\n| Безопасность | эскалация | fix now |\n' "$sep3" > "$TMP/wrong-canon-col.md"
out=$(run_gate "$TMP/wrong-canon-col.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "эскалация"; then
  ok "статус берётся из названной колонки решения, а не из первой канонической ячейки строки"
else
  not_ok "первая каноническая ячейка строки принята за статус: 'эскалация' пропущена молча (код $code)"
fi

# 54e. Распознанная таблица замечаний БЕЗ названной колонки статуса. Угадывать соседнюю
#      колонку гейту нечем, поэтому промах решается в безопасную сторону — адресный стоп,
#      называющий причину. До правки колонка бралась по содержанию строки и замечание
#      проходило молча.
#      ⚠️ Утверждение пришпилено к СВОЕЙ диагностике целиком, а не к обрывку «колонки статуса»:
#      этот обрывок печатают и соседние сообщения гейта, поэтому кейс зеленел бы и от чужого
#      стопа. Здесь блок опознан ПО СОДЕРЖАНИЮ (канонический статус + ячейка замечания в шапке).
printf '| # | Severity | Находка | Пометка |\n%s\n| 1 | HIGH | x | fix now |\n' "$sep4" > "$TMP/no-status-col.md"
out=$(run_gate "$TMP/no-status-col.md"); code=$?
if [ "$code" != "0" ] \
   && printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана, но колонки статуса у неё нет" \
   && printf '%s' "$out" | grep -F >/dev/null "статус 'fix now' стоит в колонке без известного гейту имени"; then
  ok "распознанная таблица без названной колонки статуса даёт адресный стоп"
else
  not_ok "таблица без названной колонки статуса разобрана по содержанию строки (код $code)"
fi

# 54e-bis. То же свойство на строке, решение которой записано СВОИМИ СЛОВАМИ. Кейс 54e выше
#      проверяет только половину: там ячейка написана каноническим `fix now`, и стоп приходит
#      через опознание ячейки. Здесь ни одна ячейка строки под канонический статус не подходит,
#      блок опознан ПОДПИСЬЮ ШАПКИ, и стоп обязан прийти всё равно — иначе распознанная таблица
#      с незнакомым именем колонки И незнакомым написанием решения проходит молча
#      (внутреннее ревью PR #634, итерация 5).
printf '| # | Находка | Статус триажа | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep4" > "$TMP/no-status-col-free.md"
out=$(run_gate "$TMP/no-status-col-free.md"); code=$?
if [ "$code" != "0" ] \
   && printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана, но колонки статуса у неё нет" \
   && printf '%s' "$out" | grep -F >/dev/null "замечание #1"; then
  ok "распознанная подписью таблица со свободным написанием решения даёт адресный стоп"
else
  not_ok "таблица с незнакомым именем колонки решения и свободным написанием статуса прошла молча (код $code)"
fi

# --- носитель платежа зависит от СТАТУСА строки ------------------------------------------
# Внешнее ревью PR #634 (P1 на голове 639f1fe7): колонка платежа была ОДНА на все статусы,
# хотя носители у них разные — у `defer to Beads` это идентификатор задачи, у
# `reject with rationale` — текст обоснования. Шапка, назвавшая обе колонки, отдавала обеим
# ролям ПЕРВУЮ из них: `defer` с идентификатором в обосновании и прочерком в своей колонке
# проходил молча, а `reject` при обратном порядке колонок ложно останавливался.
# Кейсы ниже прогоняют обе стороны. Составное имя «Beads ID / Обоснование» (шаблон
# reviewer.md) и шапка, назвавшая лишь одну половину, остаются одной колонкой на обе роли —
# это проверяют кейсы 1–54e выше, поэтому здесь проверяется именно РАЗДЕЛЕНИЕ.

# 54f. Обе колонки названы, `Обоснование` стоит ЛЕВЕЕ: `defer` обязан смотреть в «Beads ID»,
#      а не в первую попавшуюся колонку платежа. Идентификатор лежит в обосновании, своя
#      колонка пуста → стоп.
hdrboth='| # | Severity | Находка | Обоснование | Статус | Beads ID |'
printf '%s\n%s\n| 1 | WARNING | x | U2-abcd | defer to Beads | — |\n' "$hdrboth" "$sep" > "$TMP/both-defer-wrongcol.md"
out=$(run_gate "$TMP/both-defer-wrongcol.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "обе колонки названы: defer читает «Beads ID», идентификатор в обосновании не засчитывается"
else
  not_ok "одна колонка платежа на все статусы: defer зачтён по колонке обоснования (код $code)"
fi

# 54g. Обратная сторона того же: при той же шапке идентификатор стоит в СВОЕЙ колонке, а в
#      обосновании проза. Ложного стопа быть не должно — иначе разделение ролей меняет промах
#      с одного направления на другое.
printf '%s\n%s\n| 1 | WARNING | x | почему отложено | defer to Beads | U2-abcd |\n' "$hdrboth" "$sep" > "$TMP/both-defer-owncol.md"
out=$(run_gate "$TMP/both-defer-owncol.md"); code=$?
if [ "$code" = "0" ]; then
  ok "обе колонки названы: defer с идентификатором в своей колонке проходит"
else
  not_ok "ложный стоп: defer с идентификатором в колонке «Beads ID» отвергнут (код $code): $(printf '%s' "$out" | head -1)"
fi

# 54h. Тот же класс для отклонения: `Beads ID` стоит ЛЕВЕЕ и пуст, обоснование — в своей
#      колонке. `reject` обязан читать обоснование и пройти, а не остановиться по чужой
#      пустой колонке.
hdrboth2='| # | Статус | Beads ID | Обоснование |'
printf '%s\n%s\n| 1 | reject with rationale | — | дубль замечания #2, уже исправлено |\n' "$hdrboth2" "$sep4" > "$TMP/both-reject-owncol.md"
out=$(run_gate "$TMP/both-reject-owncol.md"); code=$?
if [ "$code" = "0" ]; then
  ok "обе колонки названы: reject с обоснованием в своей колонке проходит при пустом «Beads ID»"
else
  not_ok "ложный стоп: reject остановлен по пустой колонке «Beads ID» вместо своего обоснования (код $code): $(printf '%s' "$out" | head -1)"
fi

# 54i. Обратная сторона 54h: при той же шапке обоснование пусто, а «Beads ID» заполнен.
#      Пустое обоснование обязано краснеть — чужая непустая колонка его не закрывает.
printf '%s\n%s\n| 1 | reject with rationale | U2-abcd | — |\n' "$hdrboth2" "$sep4" > "$TMP/both-reject-empty.md"
out=$(run_gate "$TMP/both-reject-empty.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "не имеет обоснования"; then
  ok "обе колонки названы: пустое обоснование краснеет при непустом «Beads ID»"
else
  not_ok "пустое обоснование зачтено по колонке «Beads ID» (код $code)"
fi

# 54j-54m. ВЗАИМНЫЙ ОТКАТ КОЛОНОК ПЛАТЕЖА (внешнее ревью PR #634, P1). Прежняя редакция
#      достраивала недостающую колонку соседней (`bidcol = bwcol` и наоборот), и одна
#      названная колонка обслуживала ПРОТИВОПОЛОЖНЫЙ статус: шапка с одним «Beads ID»
#      засчитывала идентификатор за обоснование отклонения, шапка с одним «Обоснование» —
#      свободный текст за идентификатор задачи. Четыре кейса ниже держат обе стороны:
#      отсутствие своей колонки — ГРОМКИЙ АДРЕСНЫЙ стоп, а не зачёт чужой.

# 54j. Названа только «Обоснование». `defer to Beads` читать идентификатор неоткуда.
hdrwhyonly='| # | Статус | Обоснование |'
printf '%s\n%s\n| 1 | defer to Beads | U2-abcd |\n' "$hdrwhyonly" "$sep3" > "$TMP/only-why-defer.md"
out=$(run_gate "$TMP/only-why-defer.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не названа колонка идентификатора задачи"; then
  ok "названа только «Обоснование»: defer получает адресный стоп, колонка обоснования его не обслуживает"
else
  not_ok "колонка обоснования обслужила defer (код $code): $(printf '%s' "$out" | head -1)"
fi

# 54k. Зеркало 54j — воспроизведение находки ревьюера дословно: шапка называет только
#      «Beads ID», строка отклонена, и в колонке лежит ИДЕНТИФИКАТОР. До правки гейт
#      печатал GATE_SUCCESS и возвращал 0: идентификатор засчитывался за обоснование.
hdridonly='| # | Статус | Beads ID |'
printf '%s\n%s\n| 1 | reject with rationale | U2-abcd |\n' "$hdridonly" "$sep3" > "$TMP/only-id-reject.md"
out=$(run_gate "$TMP/only-id-reject.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не названа колонка обоснования"; then
  ok "названа только «Beads ID»: reject получает адресный стоп, идентификатор за обоснование не засчитывается"
else
  not_ok "идентификатор засчитан за обоснование отклонения (код $code): $(printf '%s' "$out" | head -1)"
fi

# 54l. Составное имя шаблона reviewer.md — ЗАКОННЫЙ случай одной колонки на обе роли, и
#      отката для него не требуется: ячейка подходит обоим словарям частями составного имени. Ложного
#      стопа быть не должно ни на одном из двух статусов.
hdrcomposite='| # | Статус | Beads ID / Обоснование |'
printf '%s\n%s\n| 1 | defer to Beads | U2-abcd |\n| 2 | reject with rationale | дубль замечания #1 |\n' "$hdrcomposite" "$sep3" > "$TMP/composite-both.md"
out=$(run_gate "$TMP/composite-both.md"); code=$?
if [ "$code" = "0" ]; then
  ok "составное имя «Beads ID / Обоснование»: одна колонка обслуживает оба статуса без отката"
else
  not_ok "ложный стоп на составном имени колонки платежа (код $code): $(printf '%s' "$out" | head -1)"
fi

# 54m. Та же составная шапка, но платёж не внесён: строгость на законной форме сохранена —
#      кейс 54l не должен превращаться в дыру.
printf '%s\n%s\n| 1 | reject with rationale | — |\n' "$hdrcomposite" "$sep3" > "$TMP/composite-empty.md"
out=$(run_gate "$TMP/composite-empty.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не имеет обоснования"; then
  ok "составное имя: пустой платёж по-прежнему краснеет"
else
  not_ok "составное имя открыло дыру: пустое обоснование прошло (код $code): $(printf '%s' "$out" | head -1)"
fi

# --- НАГРУЖЕННЫЕ СТРАЖИ ОПОЗНАНИЯ: точечный откат обязан краснить ------------------------
# Внутреннее ревью PR #634, итерация 5: у четырёх условий разбора не было адресного кейса —
# снятие каждого оставляло набор зелёным, а гейт при этом молча пропускал настоящее замечание.
# Кейсы ниже заводятся ПО ОДНОМУ на страж, и каждый проверен в обе стороны: на действующем
# скилле стоп, при точечном откате своего стража — GATE_SUCCESS.

# 54n. Страж «строка, ЗАЯВЛЯЮЩАЯ статус, шапкой не становится» в правиле «строка → шапка».
#      Разделителя под строкой нет намеренно: правило отката шапки (кейс 54o) при этом не
#      работает вовсе, и краснеть обязан именно этот страж.
printf '| 1 | IMPORTANT | Статус | a.cs:2 | defer to Beads | плохой-идентификатор |\n' > "$TMP/row-as-hdr.md"
out=$(run_gate "$TMP/row-as-hdr.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "статус 'defer to Beads'"; then
  ok "строка замечания со словом «Статус» в ячейке шапкой не становится"
else
  not_ok "строка замечания со словом «Статус» вычеркнута из проверки как шапка (код $code)"
fi

# 54o. Тот же страж в правиле ОТКАТА шапки разделителем GFM: под строкой замечания стоит
#      разделитель, и без стража она вычёркивалась бы из проверки как шапка блока.
printf '| 1 | IMPORTANT | Статус | a.cs:2 | defer to Beads | плохой-идентификатор |\n%s\n' "$sep" > "$TMP/row-as-hdr-delim.md"
out=$(run_gate "$TMP/row-as-hdr-delim.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "статус 'defer to Beads'"; then
  ok "строка замечания с разделителем под ней из проверки не вычёркивается"
else
  not_ok "разделитель под строкой замечания вычеркнул её из проверки (код $code)"
fi

# 54p. Страж «ячейка статуса непуста → строка не заглушка» в признаке заглушки. Фраза
#      «нет замечаний» стоит в ЯЧЕЙКЕ СТАТУСА вместе с решением, записанным своими словами:
#      без стража строка глушится по фразе и обязательный стоп выключается.
printf '%s\n%s\n| — | — | — | — | нет замечаний по архитектуре, эскалация | — |\n' "$hdr" "$sep" > "$TMP/stub-by-phrase.md"
out=$(run_gate "$TMP/stub-by-phrase.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "нераспознанный статус"; then
  ok "фраза «нет замечаний» в ячейке статуса строку не глушит"
else
  not_ok "строка с непустой ячейкой статуса заглушена по фразе «нет замечаний» (код $code)"
fi

# 54q. Страж «совпадение ЦЕЛИКОМ не разбирает составное имя» в сравнении со словарём.
#      Шапка называет колонку решения свободным именем «Решение», а составная ячейка
#      «Статус / Обоснование» стоит правее. Без стража точное сравнение начинает разбирать
#      составное имя, колонкой статуса выбирается ячейка «Статус / Обоснование», и гейт
#      проверяет не ту ячейку: настоящее решение `эскалация` уходит молча.
printf '| # | Решение | Статус / Обоснование | Beads ID |\n%s\n| 1 | эскалация | fix now | U2-abcd |\n' "$sep4" > "$TMP/whole-name-order.md"
out=$(run_gate "$TMP/whole-name-order.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "нераспознанный статус 'эскалация'"; then
  ok "точное имя колонки решения главнее составного: проверяется названная колонка"
else
  not_ok "составное имя перебило точное, и решение 'эскалация' прошло молча (код $code)"
fi

# --- ОПОЗНАНИЕ ШАПКИ НЕ ЗАВИСИТ ОТ ИМЕНИ КОЛОНКИ РЕШЕНИЯ ---------------------------------
# Внутреннее ревью PR #634, итерация 5. Шапка признавалась только при ЗНАКОМОМ имени колонки
# статуса, поэтому настоящая таблица замечаний, назвавшая эту колонку своими словами
# («Статус триажа», «Итоговый статус», «Вердикт ревью»), шапкой не признавалась: подпись
# шаблона не вычислялась, опознание не набиралось, а обе страховки печатали только на ячейке,
# написанной каноническим статусом. Решение своими словами не подходило и под них — гейт молчал.

# 54r. Подпись шаблона в шапке признаётся БЕЗ имени колонки решения, и стоп приходит на
#      КАЖДОЙ строке данных, а не только на канонически написанной.
printf '| # | Находка | Статус триажа | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n| 2 | гонка | перенесено | потом |\n' "$sep4" > "$TMP/free-status-hdr.md"
out=$(run_gate "$TMP/free-status-hdr.md"); code=$?
stops=$(printf '%s\n' "$out" | grep -c -F "таблица замечаний опознана, но колонки статуса у неё нет")
if [ "$code" != "0" ] && [ "$stops" = "2" ]; then
  ok "шапка с подписью шаблона признаётся без имени колонки решения: стоп на каждой строке"
else
  not_ok "таблица с незнакомым именем колонки решения проверена не построчно (код $code, стопов $stops)"
fi

# 54s. Обратная сторона того же: ЗАКОННАЯ строка-заглушка в такой таблице ложного стопа не
#      даёт. Иначе кейс 54r закрывался бы ценой отказа гейта на отчёте «замечаний нет».
printf '| # | Severity | Находка | Обоснование |\n%s\n| — | — | нет замечаний | — |\n' "$sep4" > "$TMP/free-status-stub.md"
[ "$(gate_code "$TMP/free-status-stub.md")" = "0" ] \
  && ok "заглушка в таблице без названной колонки решения ложного стопа не даёт" \
  || not_ok "ложный стоп на заглушке в таблице без названной колонки решения"

# 54t. Законная строка-заглушка не ломает ОПОЗНАНИЕ блока. Шапка называет колонку решения
#      свободным именем и ячейки замечания не несёт, поэтому опознание держится на признаке
#      «решение в каждой содержательной строке». Заглушка решения не несёт и признак ронять
#      не вправе: иначе настоящая таблица триажа получает стоп «строка со статусом вне
#      таблицы замечаний» — ложный отказ на законном отчёте (внутреннее ревью PR #634).
printf '| # | Решение | Beads ID |\n%s\n| 1 | defer to Beads | U2-abcd |\n| — |  | нет замечаний |\n' "$sep3" > "$TMP/stub-breaks-recognition.md"
out=$(run_gate "$TMP/stub-breaks-recognition.md"); code=$?
if [ "$code" = "0" ]; then
  ok "строка-заглушка не ломает опознание таблицы со свободной шапкой"
else
  not_ok "заглушка сломала опознание блока: ложный стоп на законной таблице (код $code): $out"
fi

# --- ЧЕТВЁРТЫЙ ПРИЗНАК ПОДПИСИ: слово о решении в шапке ----------------------------------
# Внутреннее ревью PR #634, итерация 6 — оба ревьюера независимо. Подпись из трёх признаков
# (номер + платёж + замечание) набирали ПОСТОРОННИЕ реестры вовсе без колонки решения:
# таблица мутаций из трейла этого же PR получала стоп «колонки статуса нет» на каждой
# строке — нарушение инварианта 6. Четвёртый признак (хоть одна ячейка шапки несёт слово о
# решении ВХОЖДЕНИЕМ) отделяет реестр от таблицы замечаний, не выбирая колонку.
# Кейсы держат ОБЕ стороны: реестры молчат, таблица со словом о решении в имени — стопит.

# 54u. Реестр мутаций из трейла PR: номер + замечание («Файл») + платёж («Обоснование»),
#      ни одного слова о решении. Стопов быть не должно — ни NOSTATCOL, ни страховок.
#      Этот же кейс — детектор отката признака: верни issig к трём признакам, и он краснеет.
printf '| # | Мутация | Файл | Обоснование |\n%s\n| 1 | откат стража | SKILL.md | краснит кейс 57 |\n| 2 | снятие exit | SKILL.md | краснит кейс 12 |\n' "$sep4" > "$TMP/registry-mutations.md"
out=$(run_gate "$TMP/registry-mutations.md"); code=$?
if [ "$code" = "0" ] && { printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана"; search_status=("${PIPESTATUS[@]}"); [ "${search_status[*]}" = "0 1" ]; }; then
  ok "реестр мутаций (номер+замечание+платёж, без слова о решении) не превращается в таблицу замечаний"
else
  not_ok "ложный стоп на реестре мутаций из трейла PR (код $code): $out"
fi

# 54v. Второй живой реестр той же формы: заведённые задачи. Платёж — «Beads ID», замечание
#      — «Замечание», решения нет. От формы отчётов PR #619/#633 его отделяет одно слово.
printf '| # | Замечание | Beads ID |\n%s\n| 1 | словари в трёх копиях | U2-lbwe |\n' "$sep3" > "$TMP/registry-tasks.md"
[ "$(gate_code "$TMP/registry-tasks.md")" = "0" ] \
  && ok "реестр заведённых задач (номер+замечание+Beads ID) стопа не даёт" \
  || not_ok "ложный стоп на реестре заведённых задач"

# 54w. Обратная сторона: слово о решении набирается ВХОЖДЕНИЕМ и через словарь свободных
#      имён («Итог триажа» — словом «Итог»), а не только точным «Статус». Таблица опознана,
#      строгого имени колонки нет — адресный стоп на строке с решением своими словами.
#      Кейс 54r выше держит ту же дорожку для слова «статус» («Статус триажа»).
printf '| # | Находка | Итог триажа | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep4" > "$TMP/free-status-alt.md"
out=$(run_gate "$TMP/free-status-alt.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана, но колонки статуса у неё нет"; then
  ok "слово о решении из словаря свободных имён опознаёт блок целым словом имени: стоп адресный"
else
  not_ok "шапка «Итог триажа» не опознана — молчаливый пропуск вернулся (код $code)"
fi

# 54w2. Слово сопоставляется ЦЕЛИКОМ, а не куском (итерация 7): «Итого строк» не несёт слова
#       «итог», и сводка радиуса остаётся посторонней — молчание, не стоп. Этот же кейс —
#       детектор отката целого слова на вхождение: верни index(), и он краснеет.
printf '| # | Файл | Итого строк | Обоснование |\n%s\n| 1 | SKILL.md | 2831 | пересчитано |\n' "$sep4" > "$TMP/registry-totals.md"
[ "$(gate_code "$TMP/registry-totals.md")" = "0" ] \
  && ok "«Итого строк» не зажигает признак куском слова «итог» — сводка радиуса молчит" \
  || not_ok "ложный стоп на сводке радиуса: признак слова о решении набрался куском чужого слова"

# 54w3. Контроль обратной стороны целого слова: «Итоговый статус» несёт слово «статус»
#       целиком — блок опознан, стоп адресный. Пара к 54w2: вместе они зажимают границу
#       «слово целиком — да, кусок слова — нет» с обеих сторон.
printf '| # | Находка | Итоговый статус | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep4" > "$TMP/free-status-full-word.md"
out=$(run_gate "$TMP/free-status-full-word.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана, но колонки статуса у неё нет"; then
  ok "«Итоговый статус» несёт слово «статус» целиком: блок опознан, стоп адресный"
else
  not_ok "«Итоговый статус» перестал опознаваться — молчаливый пропуск вернулся (код $code)"
fi

# --- ИНВЕРСИЯ ГРАНИЦЫ СЛОВА (итерация 8, CRITICAL) ---------------------------------------
# Прежняя форма ПЕРЕЧИСЛЯЛА ASCII-разделители, и не-ASCII разделитель между словами имени
# (U+00A0, U+2011, а подчёркивание съедала bare()) выключал признак 4 МОЛЧА: таблица с
# полной подписью и неразрешённым замечанием проходила без единой строки. Теперь разделитель
# определён ДОПОЛНЕНИЕМ (любой не-буквенный символ), перечня нет по построению. Кейсы ниже
# зажимают четыре живые формы; 54w4 — детектор отката инверсии на перечисление: верни
# ASCII-split или перечень разделителей, и он краснеет первым.

# 54w4. Неразрывный пробел (U+00A0) между словами имени колонки решения — форма внешних
#       моделей, пишущих тела отчётов. Блок обязан опознаться, стоп адресный.
printf '| # | Находка | Статус\xc2\xa0триажа | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep4" > "$TMP/free-status-nbsp.md"
out=$(run_gate "$TMP/free-status-nbsp.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана, но колонки статуса у неё нет"; then
  ok "U+00A0 между словами имени — разделитель: блок опознан, стоп адресный"
else
  not_ok "неразрывный пробел выключил признак подписи — молчаливый пропуск вернулся (код $code)"
fi

# 54w5. Юникод-дефис (U+2011) — та же граница, другой символ вне ASCII.
printf '| # | Находка | Статус\xe2\x80\x91триажа | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep4" > "$TMP/free-status-nbhyphen.md"
out=$(run_gate "$TMP/free-status-nbhyphen.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана, но колонки статуса у неё нет"; then
  ok "юникод-дефис U+2011 — разделитель: блок опознан, стоп адресный"
else
  not_ok "юникод-дефис выключил признак подписи — молчаливый пропуск вернулся (код $code)"
fi

# 54w6. Подчёркивание. Двойная ловушка: его не было в прежнем перечне И его стирала в ноль
#       bare(), склеивая слова («Итоговый_статус» → «Итоговыйстатус» — слово исчезало).
#       Признак обязан сработать; второе слово стоит НЕ первым в имени (граница «слева»).
printf '| # | Находка | Итоговый_статус | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep4" > "$TMP/free-status-underscore.md"
out=$(run_gate "$TMP/free-status-underscore.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана, но колонки статуса у неё нет"; then
  ok "подчёркивание — разделитель, и bare() слова не склеивает: блок опознан"
else
  not_ok "подчёркивание выключило признак подписи (перечень или склейка bare) — молчание (код $code)"
fi

# 54w8. Словарное слово ВТОРЫМ после U+00A0 (итерация 9, R1): левая граница слова здесь
#       решается веткой БАЙТА-ПРОДОЛЖЕНИЯ в bnd_before — байт перед «статус» равен 0xA0,
#       и он же был бы продолжением буквы «Р»; ветка обязана заглянуть в СВОЙ ведущий байт
#       (0xC2 — не кириллица → граница). Кейс 54w4 держит только слово ПЕРВЫМ (там граница
#       тривиальна: начало строки), и мутация ветки продолжения В СТОРОНУ МОЛЧАНИЯ оставляла
#       набор зелёным — покрытие было асимметрично ровно в опасную сторону.
printf '| # | Находка | Итоговый\xc2\xa0статус | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep4" > "$TMP/free-status-nbsp-second.md"
out=$(run_gate "$TMP/free-status-nbsp-second.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "таблица замечаний опознана, но колонки статуса у неё нет"; then
  ok "U+00A0 перед словарным словом — граница: ветка байта-продолжения смотрит в свой ведущий"
else
  not_ok "слово ВТОРЫМ после U+00A0 не опознано — ветка продолжения bnd_before промахнулась в молчание (код $code)"
fi

# 54w7. Контроль ложной стороны инверсии: «Разрешение» содержит «решение» КУСКОМ — признак
#       не зажигается, реестр остаётся посторонним (итерация 8, находка 4 — закрепление).
printf '| # | Файл | Разрешение | Обоснование |\n%s\n| 1 | texture.png | 2048x2048 | норматив |\n' "$sep4" > "$TMP/registry-resolution.md"
[ "$(gate_code "$TMP/registry-resolution.md")" = "0" ] \
  && ok "«Разрешение» не зажигает признак куском слова «решение» — реестр молчит" \
  || not_ok "ложный стоп на «Разрешение»: инверсия сравнивает не целые слова"

# --- ФРАЗА-ЗАГЛУШКА ПО СЕМАНТИЧЕСКОЙ ПАРЕ (итерация 8, блокер F1) ------------------------
# Буквальная подстрока «нет замечаний» не покрывала живые формы: пять боевых заглушек
# PR #612 написаны «нет блокирующих замечаний» — строка считалась значащей и получала стоп
# с диагнозом «впиши статус», подталкивающим выдумать статус на заглушке. Пара «нет» +
# слово с началом «замечани» покрывает живые формы; строгость держат условия совокупности
# (статус пуст, ничего не похоже на статус, прочих значащих ячеек нет).

# 54s2. Живая форма PR #612: «нет блокирующих замечаний». Стопа быть не должно.
#       Этот же кейс — детектор отката пары на буквальную подстроку.
printf '| # | Severity | Находка | Статус | Beads ID / Обоснование |\n%s\n| — | — | нет блокирующих замечаний | — | — |\n' "$sep5" > "$TMP/stub-blocking-none.md"
out=$(run_gate "$TMP/stub-blocking-none.md"); code=$?
if [ "$code" = "0" ]; then
  ok "«нет блокирующих замечаний» — заглушка: семантическая пара опознаёт перефраз"
else
  not_ok "ложный стоп на живой заглушке «нет блокирующих замечаний» (код $code): $(printf '%s' "$out" | head -1)"
fi

# 54s3. Обратный порядок слов: «замечаний нет».
printf '| # | Severity | Находка | Статус | Beads ID / Обоснование |\n%s\n| — | — | замечаний нет | — | — |\n' "$sep5" > "$TMP/stub-reversed.md"
[ "$(gate_code "$TMP/stub-reversed.md")" = "0" ] \
  && ok "«замечаний нет» — заглушка: порядок слов пары не важен" \
  || not_ok "ложный стоп на заглушке «замечаний нет»"

# 54s4. Контроль строгости: строка с содержательным текстом БЕЗ пары слов заглушкой не
#       становится — «найден обход» при пустом статусе обязан дать стоп, а не молчание.
printf '| # | Severity | Находка | Статус | Beads ID / Обоснование |\n%s\n| — | — | найден обход | — | — |\n' "$sep5" > "$TMP/stub-not-a-stub.md"
[ "$(gate_code "$TMP/stub-not-a-stub.md")" != "0" ] \
  && ok "содержательная строка без пары слов заглушкой не считается: стоп на пустом статусе жив" \
  || not_ok "строка «найден обход» проглочена как заглушка — молчаливый пропуск содержательной строки"

# --- ПРЕДЕЛ 1 ДЕЙСТВУЕТ ПОБЛОЧНО (итерация 7, F1) ----------------------------------------
# Заявленный предел 1 контракта — свойство БЛОКА, а не отчёта: неопознанный блок молчит и
# тогда, когда рядом в том же отчёте стоит валидная таблица замечаний. Кейсы закрепляют обе
# стороны поблочности, чтобы формулировка предела в контракте не расходилась с механизмом.

# 54x. Смешанный отчёт: валидная таблица (fix now) + блок «Отработка» без словарного слова и
#      без канонических статусов. Валидный блок проходит, второй молчит — rc=0. Это ГРАНИЦА
#      заявленного предела 1 (U2-t233), кейс документирует её, а не одобряет.
printf '| # | Severity | Находка | Статус | Beads ID / Обоснование |\n%s\n| 1 | MINOR | мелочь | fix now | исправлено |\n\n| # | Находка | Отработка | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep5" "$sep4" > "$TMP/mixed-two-blocks.md"
[ "$(gate_code "$TMP/mixed-two-blocks.md")" = "0" ] \
  && ok "предел 1 поблочен: валидный сосед не втягивает неопознанный блок в проверку (граница предела, не одобрение)" \
  || not_ok "смешанный отчёт даёт стоп — поблочность предела 1 сломана, валидный блок втянул соседа"

# 54y. Обратная сторона: молчащий сосед НЕ глушит проверку валидного блока. Тот же второй
#      блок, но в первом — reject с пустым обоснованием: стоп обязан прийти.
printf '| # | Severity | Находка | Статус | Beads ID / Обоснование |\n%s\n| 1 | MINOR | мелочь | reject with rationale | — |\n\n| # | Находка | Отработка | Обоснование |\n%s\n| 1 | утечка | эскалация | потом |\n' "$sep5" "$sep4" > "$TMP/mixed-two-blocks-bad.md"
[ "$(gate_code "$TMP/mixed-two-blocks-bad.md")" != "0" ] \
  && ok "молчащий сосед не глушит валидный блок: reject без обоснования остановлен и в смешанном отчёте" \
  || not_ok "молчание неопознанного блока распространилось на валидный: reject с прочерком прошёл"

# 54z. Диагноз страховки-сироты перечисляет ВСЕ ЧЕТЫРЕ признака подписи — включая слово о
#      решении (итерация 7, F3). Автор отчёта чинит шапку по инструкции из сообщения;
#      инструкция из трёх признаков вела бы его в новый отказ.
out=$(run_gate "$TMP/req-one-canon.md")
printf '%s' "$out" | grep -F >/dev/null "со словом о решении" \
  && ok "диагноз сироты называет четвёртый признак подписи — инструкция автору полная" \
  || not_ok "диагноз сироты перечисляет подпись без четвёртого признака: по инструкции шапку не починить"

# --- ЕДИНЫЙ СЛОВАРЬ ПУСТОЙ ЯЧЕЙКИ --------------------------------------------------------
# Внешнее ревью PR #634, P1: перечень «пусто или прочерк» был записан ДВАЖДЫ независимо —
# в разборе (awk) и в построчной проверке обоснования (shell), — и копии разошлись. Разбор
# уже считал прочерком короткое тире `–`, а проверка знала только `-` и `—`; ячейка из
# короткого тире либо из невидимого пробела давала GATE_SUCCESS и код 0 на
# `reject with rationale`. Кейсы ниже проходят ВЕСЬ словарь: каждая форма по отдельности
# обязана краснеть, а осмысленный текст с прочерком внутри — проходить.
# Невидимые формы задаются восьмеричными escape-последовательностями: литеральный байт в
# исходнике теста не виден глазу и при правке теряется молча.
hdrblank='| # | Статус | Beads ID / Обоснование |'
assert_blank_rationale_stops() {
  local cell="$1" label="$2" out code
  printf '%s\n%s\n| 1 | reject with rationale | %s |\n' "$hdrblank" "$sep3" "$cell" > "$TMP/blank-rat.md"
  out=$(run_gate "$TMP/blank-rat.md"); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не имеет обоснования"; then
    ok "визуально пустое обоснование ($label) останавливает гейт"
  else
    not_ok "визуально пустое обоснование ($label) закрыло замечание молча (код $code): $(printf '%s' "$out" | head -1)"
  fi
}
assert_blank_rationale_stops '-' 'дефис-минус'
assert_blank_rationale_stops '—' 'длинное тире'
assert_blank_rationale_stops "$(printf '\342\200\223')" 'короткое тире U+2013 — форма из находки ревьюера'
assert_blank_rationale_stops "$(printf '\342\210\222')" 'минус U+2212'
assert_blank_rationale_stops "$(printf '\342\200\222')" 'цифровое тире U+2012'
assert_blank_rationale_stops "$(printf '\342\200\225')" 'горизонтальная черта U+2015'
assert_blank_rationale_stops "$(printf '\302\240')" 'неразрывный пробел U+00A0'
assert_blank_rationale_stops "$(printf '\342\200\257')" 'узкий неразрывный пробел U+202F'
assert_blank_rationale_stops "$(printf '\342\200\213')" 'пробел нулевой ширины U+200B'
assert_blank_rationale_stops "$(printf '\357\273\277')" 'неразрывный пробел нулевой ширины U+FEFF'
assert_blank_rationale_stops "$(printf '\342\201\240')" 'соединитель слов U+2060'
assert_blank_rationale_stops "$(printf '\342\200\211')" 'тонкий пробел U+2009'
assert_blank_rationale_stops "$(printf '\342\200\207')" 'цифровой пробел U+2007'
assert_blank_rationale_stops "$(printf -- '--\302\240\342\200\223')" 'смесь прочерков и невидимых пробелов'

# Обратная сторона словаря: осмысленное обоснование НЕ должно краснеть оттого, что в нём
# есть прочерк или неразрывный пробел. Иначе расширение словаря превратилось бы в ложный
# стоп на живых отчётах.
printf '%s\n%s\n| 1 | reject with rationale | дубль\302\240замечания #2 — уже исправлено |\n' "$hdrblank" "$sep3" > "$TMP/blank-rat-ok.md"
out=$(run_gate "$TMP/blank-rat-ok.md"); code=$?
if [ "$code" = "0" ]; then
  ok "обоснование с прочерком и неразрывным пробелом ВНУТРИ текста проходит"
else
  not_ok "ложный стоп на осмысленном обосновании с прочерком внутри (код $code): $(printf '%s' "$out" | head -1)"
fi

# Словарь ОДИН на файл: shell-сторона не имеет права нести собственный перечень форм.
# Структурная проверка — она краснеет при откате к сравнениям вида `[ "$rationale" = "—" ]`.
if grep -qF 'payload_is_blank "$rationale"' "$SKILL" \
   && ! grep -qE '\[ "\$rationale" = "(-|—|–)" \]' "$SKILL"; then
  ok "проверка обоснования читает единый словарь, а не вторую копию перечня прочерков"
else
  not_ok "в проверке обоснования снова выписан свой перечень прочерков — две копии словаря разъедутся"
fi
if [ "$(grep -c -E '^BLANK_FORMS=' "$SKILL")" = "1" ] && grep -qF -e '-v BLANKS="$BLANK_FORMS"' "$SKILL"; then
  ok "словарь пустых форм объявлен один раз и передан в разбор параметром"
else
  not_ok "словарь пустых форм объявлен не один раз либо не передан в awk — источник перестал быть единственным"
fi

# --- приоритетная ветка: существование задачи проверяется через `bd` ---------------------
# Базовый PATH фикстуры `bd` не содержит, поэтому без кейсов ниже эта ветка не исполнялась
# НИ РАЗУ: проверялся только запасной путь по форме идентификатора. Заглушка `bd` управляет
# кодом возврата, рабочая база Beads не трогается.

# 55. `bd` есть и задачу находит: приоритетная ветка исполняется и даёт проход.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/bd-found.md"
[ "$(gate_code "$TMP/bd-found.md" "$(make_bd_stub found 0)")" = "0" ] \
  && ok "ветка bd: существующая задача с верной формой идентификатора проходит" \
  || not_ok "ветка bd не исполняется: существующая задача отвергнута"

# 55a. ⚠️ ИЗМЕНЁННЫЙ КОНТРАКТ (внешнее ревью PR #634, P1). Прежде этот кейс утверждал
#      обратное: идентификатор НЕ по форме (`12345`) проходил, «потому что задача существует» —
#      проверка формы была лишь запасным путём при отсутствующем `bd`. Именно этот порядок и
#      есть находка: значение из тела отчёта уходило первым позиционным аргументом `bd show`
#      и разбиралось им как ОПЦИЯ. Теперь форма проверяется первой и безусловно, поэтому
#      значение не по форме останавливает гейт ДАЖЕ когда заглушка отвечает «задача есть».
#      Изменение односторонее — в сторону стопа; проход по существованию задачи стал у́же,
#      ложных пропусков не добавилось. Кейс оставлен, а не удалён: он сторожит сам порядок.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | 12345 |\n' "$hdr" "$sep" > "$TMP/bd-badform.md"
out=$(run_gate "$TMP/bd-badform.md" "$(make_bd_stub found 0)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "ветка bd: значение не по форме останавливает гейт до вызова, даже если bd отвечает «задача есть»"
else
  not_ok "проверка формы не предшествует вызову bd: значение не по форме прошло по ответу bd (код $code)"
fi

# 56. `bd` есть, но задачи нет: стоп с адресным сообщением про `bd show`.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/bd-missing.md"
out=$(run_gate "$TMP/bd-missing.md" "$(make_bd_stub missing 1)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "bd show не находит задачу"; then
  ok "ветка bd: несуществующая задача останавливает гейт, даже если форма идентификатора верна"
else
  not_ok "ветка bd: несуществующая задача прошла молча (код $code)"
fi

# 57. САМ `bd` завершился кодом 124 — это НЕ истечение времени обёртки. Помощник
#     `.claude/tools/with-timeout.sh` переводит собственный 124 команды в 125 именно затем,
#     чтобы потребитель их не путал, и гейт обязан сообщить «задача не найдена», а не
#     «истекло время»: иначе PM чинит окружение Beads вместо отсутствующей задачи.
#     (Ветку настоящего истечения времени — код 124 ОТ ОБЁРТКИ — исполнением проверяет
#     scripts/tests/with-timeout.test.sh; здесь она стоила бы кейсу 10 секунд ожидания.)
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/bd-own124.md"
out=$(run_gate "$TMP/bd-own124.md" "$(make_bd_stub own124 124)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "bd show не находит задачу"; then
  ok "ветка bd: собственный код 124 команды не выдаётся за истечение времени"
else
  not_ok "ветка bd: собственный код 124 команды спутан с истечением времени (код $code)"
fi

# --- НАХОДКА PR #634 (P1): `bd` в окружении НЕТ ------------------------------------------
# Прежде эта ветка не делала ничего: проверенной оказывалась ФОРМА идентификатора, а не
# существование задачи, и `defer to Beads` с выдуманным `U2-thisissuedoesnotexist` доходил до
# GATE_SUCCESS. Окружение без `bd` — не экзотика: в изолированном облачном контейнере его нет
# по устройству (ADR-0042). Поэтому запрет «нет bd — стоп» не годится (он заблокировал бы облако
# целиком), и существование проверяется по снимку `origin/beads-backup` — тем же
# `scripts/bd-read.sh`, которым задачи читаются в облаке.

# 57a. Снимок читается, задачи в нём НЕТ: гейт обязан краснеть, а не засчитывать форму.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-thisissuedoesnotexist |\n' "$hdr" "$sep" > "$TMP/snap-missing.md"
out=$(run_gate "$TMP/snap-missing.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нет в снимке"; then
  ok "без bd: несуществующая задача останавливает гейт по снимку"
else
  not_ok "REGRESS PR #634 P1: без bd несуществующий Beads ID прошёл по одной лишь форме (код $code)"
fi

# 57b. Обратная сторона: задача в снимке ЕСТЬ — ложного стопа быть не должно. Без этой половины
#      кейс 57a был бы неотличим от «нет bd — стоп всегда», а такой стоп заблокировал бы работу
#      в облачном контейнере, где bd отсутствует по устройству.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/snap-found.md"
out=$(run_gate "$TMP/snap-found.md"); code=$?
if [ "$code" = "0" ]; then
  ok "без bd: существующая в снимке задача проходит"
else
  not_ok "ложный стоп: без bd существующая в снимке задача отвергнута (код $code): $(printf '%s' "$out" | head -1)"
fi

# 57c. Ни `bd`, ни читателя снимка в корне репозитория: проверить существование нечем, и гейт
#      промахивается в безопасную сторону — стоп с адресом починки, а не молчаливый зачёт.
out=$(run_gate "$TMP/snap-found.md" "" "$(make_snapshot_root noreader none)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "ни читателя снимка"; then
  ok "без bd и без читателя снимка: гейт останавливается, а не засчитывает форму"
else
  not_ok "без bd и без читателя снимка идентификатор зачтён непроверенным (код $code)"
fi

# 57d. Читатель снимка есть, но сам снимок не читается (нет git-доступа к origin): исход тоже
#      стоп, но диагноз другой — чинить надо доступ, а не заводить задачу.
out=$(run_gate "$TMP/snap-found.md" "" "$(make_snapshot_root unreadable unreadable)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "не читается"; then
  ok "без bd и с нечитаемым снимком: стоп с диагнозом «проверить нечем»"
else
  not_ok "нечитаемый снимок не отличён от отсутствующей задачи либо прошёл молча (код $code)"
fi

# 57d-bis. Истечение времени у маршрута снимка разбирается ОТДЕЛЬНО и ДО пробы читаемости —
#      так же, как у маршрута прямого `bd`. Заглушкой это не проверить: помощник ограничения
#      времени переводит СОБСТВЕННЫЙ код 124 команды в 125 именно затем, чтобы потребитель их
#      не путал, а настоящее истечение стоило бы кейсу 30 секунд ожидания (ту ветку исполнением
#      проверяет scripts/tests/with-timeout.test.sh). Поэтому проверка структурная и адресная:
#      между записью кода возврата читателя снимка и пробой читаемости обязана стоять ветка
#      `-eq 124`. Без неё убитый по времени запрос уходит в пробу, проба отвечает «читатель
#      работает», и гейт печатает «задачи нет в снимке» о задаче, про которую снимок не
#      спрашивали: диагноз называет ОТЧЁТ там, где не уложилось ОКРУЖЕНИЕ.
snap_block=$(awk '/bd_read_exit=\$\?/ { f = 1 } f { print } f && /BD_READ_NO_FETCH=1/ { exit }' "$SKILL")
if printf '%s' "$snap_block" | grep -E >/dev/null '^[[:space:]]*elif \[ "\$bd_read_exit" -eq 124 \]; then'; then
  ok "маршрут снимка: истечение времени разобрано отдельно и раньше пробы читаемости"
else
  not_ok "маршрут снимка: код 124 не отличён от ответа «задачи нет в снимке»"
fi

# 57e. Приоритет ветки: когда `bd` доступен, снимок не спрашивают. Заглушка `bd` отвечает
#      «задача есть» на идентификатор, которого в снимке НЕТ, — гейт обязан пройти.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-onlyinbd |\n' "$hdr" "$sep" > "$TMP/bd-over-snap.md"
out=$(run_gate "$TMP/bd-over-snap.md" "$(make_bd_stub found 0)"); code=$?
if [ "$code" = "0" ]; then
  ok "при доступном bd существование проверяет bd, а не снимок"
else
  not_ok "ветка bd перестала быть приоритетной: задача из bd отвергнута снимком (код $code)"
fi

# --- НАХОДКА PR #634 (P2): отказ ОДНОГО маршрута — не ответ «задачи нет» ------------------
# Регресс предыдущего раунда этого же PR: проверка существования стала строгой, но спрашивала
# ТОЛЬКО прямой `bd`. В связанной git-worktree — самом обычном рабочем окружении проекта —
# прямой auto-discover открывает ПУСТУЮ базу и отвечает «задачи нет» на любой идентификатор
# (ADR-0042, .claude/rules/beads.md), поэтому там ложно блокировалось КАЖДОЕ законное
# `defer to Beads`. Кейсы ниже прогоняют все три документированных класса окружения.

# 57f. Связанная worktree: прямой `bd` отвечает отказом, документированный маршрут
#      scripts/bd-wt.sh задачу находит → проход. Снимок задачи НЕ знает — так доказано, что
#      проход дала именно обёртка, а не запасной путь по снимку.
wt_found="$(make_worktree_root found found snapshot 'U2-abcd')"
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/wt-found.md"
out=$(run_gate "$TMP/wt-found.md" "$(make_bd_stub missing 1)" "$wt_found"); code=$?
if [ "$code" = "0" ] && [ -f "$wt_found/.called-bd-wt" ]; then
  ok "worktree: отказ прямого bd не считается ответом — задачу находит scripts/bd-wt.sh"
else
  not_ok "REGRESS PR #634 P2: в worktree отказ прямого bd ложно блокирует defer-замечание (код $code, обёртка вызвана: $([ -f "$wt_found/.called-bd-wt" ] && echo да || echo нет))"
fi

# 57g. Тот же класс окружения, но задачи нет НИГДЕ: обёртка отказала, снимок читается и задачи
#      в нём нет → стоп с диагнозом «задачи нет». Без этой половины кейс 57f был бы неотличим
#      от «в worktree проверка выключена».
wt_none="$(make_worktree_root nowhere refuse snapshot 'U2-otherissue')"
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/wt-none.md"
out=$(run_gate "$TMP/wt-none.md" "$(make_bd_stub missing 1)" "$wt_none"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нет в снимке"; then
  ok "worktree: когда задачу не нашёл ни один маршрут, гейт останавливается с диагнозом «задачи нет»"
else
  not_ok "worktree: ни один маршрут задачу не нашёл, а гейт не остановился либо назвал не тот адрес починки (код $code): $(printf '%s' "$out" | head -1)"
fi

# 57h. Ни один маршрут ОТВЕТИТЬ не смог: прямой `bd` вне основного checkout не авторитетен,
#      обёртка отказала кодом «мёртвый dolt-сервер», читателя снимка в дереве нет. Исход —
#      тоже стоп, но адрес починки другой: чинить окружение, а не заводить задачу.
wt_mute="$(make_worktree_root mute dead none)"
out=$(run_gate "$TMP/wt-none.md" "$(make_bd_stub missing 1)" "$wt_mute"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "проверить нечем" \
   && { printf '%s' "$out" | grep >/dev/null "нет в снимке"; search_status=("${PIPESTATUS[@]}"); [ "${search_status[*]}" = "0 1" ]; }; then
  ok "worktree: когда ответить не смог ни один маршрут, диагноз — «проверить нечем», а не «задачи нет»"
else
  not_ok "worktree: неотвечающие маршруты выданы за отсутствие задачи либо гейт промолчал (код $code): $(printf '%s' "$out" | head -1)"
fi

# 57i. ⚠️ ПЕРЕПИСАННЫЙ КЕЙС (внешнее ревью PR #634, P1 на голове 639f1fe7). Прежде он
#      утверждал «при ответившем прямом `bd` запасные маршруты не запускаются» и прогонял это
#      в СВЯЗАННОЙ WORKTREE — то есть сторожил ровно тот дефект, который чинится: успех
#      прямого `bd` засчитывался безусловно, хотя вне основного checkout он опрашивает
#      неканоническую auto-discover базу. Утверждение сохранено целиком, но привязано к
#      классу окружения, где оно верно: в ОСНОВНОМ checkout ответ прямого `bd` авторитетен, и
#      лишний процесс с сетевым fetch на каждое defer-замечание там не нужен. Сторона worktree
#      закрыта отдельным кейсом 57j ниже, поэтому покрытие не сузилось, а разделилось.
#      Снимок подставного корня задачу НЕ знает — так доказано, что проход дал именно `bd`.
main_fanout="$(make_main_root_marked fanout 'U2-otherissue')"
out=$(run_gate "$TMP/wt-found.md" "$(make_bd_stub found 0)" "$main_fanout"); code=$?
if [ "$code" = "0" ] && [ ! -f "$main_fanout/.called-bd-wt" ] && [ ! -f "$main_fanout/.called-bd-read" ]; then
  ok "основной checkout: успех прямого bd авторитетен, запасные маршруты не запускаются"
else
  not_ok "перебор маршрутов стал безусловным в основном checkout: вызваны обёртка ($([ -f "$main_fanout/.called-bd-wt" ] && echo да || echo нет)) / снимок ($([ -f "$main_fanout/.called-bd-read" ] && echo да || echo нет)), код $code"
fi

# 57j. НАХОДКА внешнего ревью PR #634 (P1 на голове 639f1fe7): СИММЕТРИЯ авторитетности.
#      Отказ прямого `bd` вне основного checkout ответом уже не считается (кейс 57f), а его
#      УСПЕХ засчитывался безусловно. В связанной worktree прямой `bd` с auto-discovery
#      открывает НЕКАНОНИЧЕСКУЮ базу (ADR-0042, .claude/rules/beads.md): если в случайно
#      созданной там базе есть идентификатор, которого в канонической базе нет, невалидный
#      `defer` проходил гейт молча. Заглушка прямого `bd` отвечает «задача есть» на любой
#      идентификатор, канонические маршруты — «нет» → обязан быть стоп, и оба запасных
#      маршрута обязаны быть ВЫЗВАНЫ (иначе кейс проходил бы и при выключенной проверке).
wt_falsepos="$(make_worktree_root falsepos refuse snapshot 'U2-otherissue')"
out=$(run_gate "$TMP/wt-none.md" "$(make_bd_stub found 0)" "$wt_falsepos"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нет в снимке" \
   && [ -f "$wt_falsepos/.called-bd-wt" ] && [ -f "$wt_falsepos/.called-bd-read" ]; then
  ok "worktree: успех прямого bd не авторитетен — опрошены канонические маршруты, задачи нет → стоп"
else
  not_ok "worktree: успех прямого bd по неканонической базе зачтён молча (код $code, обёртка: $([ -f "$wt_falsepos/.called-bd-wt" ] && echo да || echo нет), снимок: $([ -f "$wt_falsepos/.called-bd-read" ] && echo да || echo нет))"
fi

# --- НАХОДКА внешнего прохода 10: отказ ОПРЕДЕЛЕНИЯ КЛАССА ≠ ответ «не основной checkout» ---
# Класс окружения решает, чей ответ о задаче авторитетен. У его определения три исхода, и
# прежде два последних сливались в один: любой ненулевой код канон-функции читался как «не
# основной checkout», после чего гейт шёл дальше по маршрутам и доходил до GATE_SUCCESS.

# 57k. `git` КОРЕНЬ ОТДАЁТ (все проверки его кода возврата вокруг проходят), а внутри
#      определения класса падает кодом 5. До правки: гейт возвращал 0 и молчал.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/env-broken.md"
out=$(run_gate "$TMP/env-broken.md" "$(make_git_stub envfail "$SNAP_ROOT" 5)" "$SNAP_ROOT"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "класс окружения Beads не определён"; then
  ok "отказ git внутри определения класса окружения останавливает гейт, а не читается как «не основной checkout»"
else
  not_ok "REGRESS прохода 10: отказ определения класса поглощён следующим маршрутом (код $code): $(printf '%s' "$out" | head -1)"
fi

# 57l. Тот же класс исхода по другой причине: канон-библиотеки в корне нет, определить класс
#      нечем. Молчаливо считать «не основной checkout» гейт тоже не вправе.
nolib_root="$(make_snapshot_root nolib snapshot "$SNAPSHOT_KNOWN_IDS" nolib)"
out=$(run_gate "$TMP/env-broken.md" "" "$nolib_root"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "класс окружения Beads не определён"; then
  ok "отсутствие канон-библиотеки beads — тоже неизвестный класс, а не молчаливое «не основной checkout»"
else
  not_ok "класс окружения без канон-библиотеки достроен догадкой (код $code): $(printf '%s' "$out" | head -1)"
fi

# 57m. Отказ базы задач НЕОТЛИЧИМ от «задачи нет» по одному коду возврата `bd show`: и то, и
#      другое даёт 1. Проба `bd list` отвечает на другой вопрос — отвечает ли база вообще.
#      Она не ответила → отрицательный ответ прямого `bd` не авторитетен, слово за снимком.
#      Снимок задачи не знает → стоп с ЕГО адресом починки, а не «bd show не находит задачу».
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-nosuchtask |\n' "$hdr" "$sep" > "$TMP/dolt-down.md"
out=$(run_gate "$TMP/dolt-down.md" "$(make_bd_stub doltdown 1 1)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "нет в снимке" \
   && { printf '%s' "$out" | grep -F >/dev/null "bd show не находит задачу"; search_status=("${PIPESTATUS[@]}"); [ "${search_status[*]}" = "0 1" ]; }; then
  ok "основной checkout: отказ базы задач не выдаётся за ответ «задачи нет» — отвечает снимок"
else
  not_ok "отказ Dolt зачтён как авторитетное «задачи нет» (код $code): $(printf '%s' "$out" | head -1)"
fi

# 57n. Отказали ОБА: база задач не отвечает и снимок не читается. Диагноз обязан назвать оба
#      адреса починки, а не выдать один из них за отсутствие задачи.
mute_root="$(make_snapshot_root doltmute unreadable)"
out=$(run_gate "$TMP/dolt-down.md" "$(make_bd_stub doltdown2 1 1)" "$mute_root"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "проверить нечем" \
   && printf '%s' "$out" | grep -F >/dev/null "не отвечает" && printf '%s' "$out" | grep -F >/dev/null "не читается"; then
  ok "отказ базы задач и нечитаемый снимок дают диагноз «проверить нечем» с обоими адресами починки"
else
  not_ok "при двух отказавших маршрутах диагноз потерян или подменён отсутствием задачи (код $code): $(printf '%s' "$out" | head -1)"
fi

# 57o. Обратная сторона: отказ базы задач не вправе и БЛОКИРОВАТЬ законное замечание. Снимок
#      задачу знает — проход. Без этой половины кейс 57m был бы неотличим от «отказ bd = стоп».
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/dolt-down-ok.md"
out=$(run_gate "$TMP/dolt-down-ok.md" "$(make_bd_stub doltdown3 1 1)"); code=$?
if [ "$code" = "0" ]; then
  ok "отказ базы задач не блокирует законное defer-замечание: авторитетно отвечает снимок"
else
  not_ok "ложный стоп: при отказе базы задач законное defer отвергнуто (код $code): $(printf '%s' "$out" | head -1)"
fi

# --- внешнее ревью #634: исключение строки из проверки и нормализация значения ----------
# Общее для секции: строку из проверки исключает СОВОКУПНОСТЬ признаков, а не совпадение
# одного слова в одной ячейке, и нормализация трогает только ОБРАМЛЕНИЕ ячейки. Каждый кейс
# ниже до правки завершался кодом 0 (молчаливый пропуск) либо давал ложный стоп.

# 65. НАХОДКА 1: строка ДАННЫХ, у которой одна ячейка равна слову «Статус». Прежний признак
#     шапки смотрел ровно на это слово в любой ячейке, принимал строку за шапку соседней
#     таблицы и исключал её из проверки — невалидный Beads ID уходил молча (код 0).
printf '%s\n%s\n| 1 | WARNING | Статус | a.cs:1 | defer to Beads | позже |\n' "$hdr" "$sep" > "$TMP/hdrword-row.md"
out=$(run_gate "$TMP/hdrword-row.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "строка данных со словом «Статус» в ячейке не считается шапкой и проверяется"
else
  not_ok "строка данных со словом «Статус» принята за шапку и исключена из проверки (код $code)"
fi

# 66. Та же подмена, но статус нешаблонный: признак шапки не вправе сводиться к «в строке нет
#     канонического статуса» — строка обязана дойти до проверки и получить адресный стоп.
printf '%s\n%s\n| 1 | WARNING | Статус | a.cs:1 | эскалация | позже |\n' "$hdr" "$sep" > "$TMP/hdrword-unknown.md"
out=$(run_gate "$TMP/hdrword-unknown.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "строка данных со словом «Статус» и нешаблонным статусом даёт адресный стоп"
else
  not_ok "строка со словом «Статус» и нешаблонным статусом прошла молча (код $code)"
fi

# 67. НАХОДКА 2: фраза «нет замечаний» внутри ЗАГОЛОВКА замечания при нераспознанном статусе.
#     Прежний признак заглушки глушил всю строку по фразе в любой ячейке, и обязательный стоп
#     на нераспознанном статусе не наступал (код 0).
printf '%s\n%s\n| 1 | WARNING | по архитектуре нет замечаний, но тест сломан | a.cs:1 | эскалация | U2-abcd |\n' "$hdr" "$sep" > "$TMP/stub-phrase-unknown.md"
out=$(run_gate "$TMP/stub-phrase-unknown.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "фраза «нет замечаний» в заголовке не глушит стоп на нераспознанном статусе"
else
  not_ok "строка с фразой «нет замечаний» в заголовке заглушена при нераспознанном статусе (код $code)"
fi

# 68. Тот же класс, вторая форма: фраза в заголовке при ПУСТОЙ ячейке статуса. Строка
#     осмысленна (номер, severity, файл, идентификатор), поэтому заглушкой не является —
#     пустая ячейка статуса обязана давать стоп, как и обещает описание шага 6.
printf '%s\n%s\n| 1 | WARNING | по архитектуре нет замечаний, но тест сломан | a.cs:1 |  | U2-abcd |\n' "$hdr" "$sep" > "$TMP/stub-phrase-empty.md"
out=$(run_gate "$TMP/stub-phrase-empty.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "осмысленная строка с фразой «нет замечаний» и пустым статусом даёт стоп"
else
  not_ok "осмысленная строка заглушена фразой «нет замечаний» при пустом статусе (код $code)"
fi

# 69. НАХОДКА 3: посторонняя таблица требований `# | Требование | Статус | Обоснование`.
#     Прежняя подпись шаблона держалась на «ячейка-номер + Статус + платёжная ячейка», и
#     колонка «Обоснование» делала эту таблицу таблицей замечаний: её «выполнено» давало
#     отказ гейта — прямое нарушение инварианта 6 контракта PR.
printf 'Проверка требований.\n\n| # | Требование | Статус | Обоснование |\n%s\n| 1 | дока обновлена | выполнено | по факту правки |\n| 2 | индекс синхронизирован | выполнено | строка добавлена |\n' "$sep4" > "$TMP/req-pay-table.md"
out=$(run_gate "$TMP/req-pay-table.md"); code=$?
if [ "$code" = "0" ]; then
  ok "таблица требований с колонкой «Обоснование» не даёт ложного стопа"
else
  not_ok "ложный стоп на таблице требований с колонкой «Обоснование» (код $code): $(printf '%s' "$out" | head -1)"
fi

# 70. Тот же класс, вторая сторона: упоминание статуса триажа В ТЕКСТЕ требования. Страховка
#     опознаёт заявку на статус по совокупности признаков ЯЧЕЙКИ, а не по слову внутри фразы,
#     иначе посторонняя таблица останавливает гейт (тот же инвариант 6).
printf '| # | Требование | Статус |\n%s\n| 1 | замечания класса fix now закрыты | выполнено |\n' "$sep3" > "$TMP/req-mentions-status.md"
out=$(run_gate "$TMP/req-mentions-status.md"); code=$?
if [ "$code" = "0" ]; then
  ok "упоминание статуса в тексте требования не даёт ложного стопа"
else
  not_ok "ложный стоп на упоминании статуса внутри текста требования (код $code): $(printf '%s' "$out" | head -1)"
fi

# 71. НАХОДКА 4: маркер выделения ВНУТРИ значения статуса. Глобальное снятие `**`, `__` и
#     обратных кавычек по всему телу отчёта склеивало ошибочное значение в допустимый статус,
#     и строка проходила строгий case как валидный defer (при валидном ID — код 0).
#     Нормализуется только ОБРАМЛЕНИЕ ячейки, поэтому все три формы обязаны краснеть.
broken_ok=1
for broken in 'de`fer to Beads' 'de**fer to Beads' 'de__fer to Beads'; do
  printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | %s | U2-abcd |\n' "$hdr" "$sep" "$broken" > "$TMP/inner-marker.md"
  out=$(run_gate "$TMP/inner-marker.md"); code=$?
  if [ "$code" = "0" ] || ! printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
    broken_ok=0
    printf 'подробность: форма «%s» дала код %s\n' "$broken" "$code" >&2
  fi
done
[ "$broken_ok" = "1" ] \
  && ok "маркер выделения внутри значения статуса не склеивается в допустимый статус" \
  || not_ok "маркер внутри значения статуса нормализован в допустимый статус — гейт молчит"

# 72. Обратная сторона той же нормализации: НЕПАРНЫЙ маркер по краю тоже не снимается —
#     сомнение решается в сторону стопа, а не в сторону допустимого статуса.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | **defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/unpaired-marker.md"
out=$(run_gate "$TMP/unpaired-marker.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "непарный маркер выделения по краю ячейки не делает статус допустимым"
else
  not_ok "непарный маркер по краю ячейки снят и статус зачтён как допустимый (код $code)"
fi

# 73. Сплошной проход по тому же классу: строку из проверки вычёркивает ещё и правило
#     «шапка стоит перед строкой-разделителем». Строка, ЗАЯВЛЯЮЩАЯ статус триажа, шапкой быть
#     не может — иначе первая же строка замечаний, за которой автор поставил разделитель,
#     исчезает из проверки молча.
printf '| 1 | WARNING | x | a.cs:1 | defer to Beads | позже |\n%s\n| 2 | INFO | y | b.cs:2 | fix now | закрыт |\n' "$sep" > "$TMP/row-before-delim.md"
out=$(run_gate "$TMP/row-before-delim.md"); code=$?
if [ "$code" != "0" ]; then
  ok "строка со статусом перед строкой-разделителем не вычёркивается из проверки"
else
  not_ok "строка со статусом принята за шапку из-за разделителя под ней и пропущена молча (код $code)"
fi

# 73a. ВТОРОЙ ПРОХОД ПО ТОМУ ЖЕ КЛАССУ (внешнее ревью PR #634, P1 на голове 7a283470).
#      Кейс 73 закрывал только строку, которая ЗАЯВЛЯЕТ статус: признак «шапка стоит перед
#      разделителем» держался на содержании ячеек и промахивался на строке, где заявки нет,
#      а слово-синоним имени шапки есть. Строка ДАННЫХ внутри уже опознанной шаблонной
#      таблицы: ячейка заголовка равна слову «Статус», статус неканонический, под строкой —
#      лишний разделитель. До правки такая строка признавалась шапкой соседней таблицы и
#      уходила из проверки молча (код 0, гейт доходил до GATE_SUCCESS).
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | fix now | закрыт |\n| 2 | IMPORTANT | Статус | a.cs:2 | эскалация | U2-abcd |\n%s\n' "$hdr" "$sep" "$sep" > "$TMP/datarow-hdrword-delim.md"
out=$(run_gate "$TMP/datarow-hdrword-delim.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "строка данных со словом «Статус» и разделителем под ней проверяется, а не считается шапкой"
else
  not_ok "REGRESS PR #634: строка данных со словом «Статус» перед разделителем исключена из проверки (код $code)"
fi

# 73b. Та же подмена ПЕРВОЙ строкой данных таблицы: положение строки после разделителя блока
#      уже исключает шапку, поэтому исход не зависит от того, есть ли выше неё другие строки.
printf '%s\n%s\n| 2 | IMPORTANT | Статус | a.cs:2 | эскалация | U2-abcd |\n%s\n' "$hdr" "$sep" "$sep" > "$TMP/datarow-hdrword-first.md"
out=$(run_gate "$TMP/datarow-hdrword-first.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "первая строка данных со словом «Статус» и разделителем под ней тоже проверяется"
else
  not_ok "REGRESS PR #634: первая строка данных со словом «Статус» исключена из проверки (код $code)"
fi

# 73c. Та же форма с КАНОНИЧЕСКИМ статусом и невалидным идентификатором: строка обязана
#      дойти до проверки платежа, а не быть вычеркнутой разделителем под ней.
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | fix now | закрыт |\n| 2 | IMPORTANT | Статус | a.cs:2 | defer to Beads | позже |\n%s\n' "$hdr" "$sep" "$sep" > "$TMP/datarow-hdrword-defer.md"
out=$(run_gate "$TMP/datarow-hdrword-defer.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
  ok "строка данных со словом «Статус» перед разделителем проверяется и по платежу"
else
  not_ok "строка данных со словом «Статус» перед разделителем не проверена по платежу (код $code)"
fi

# 73d. Третья форма того же вычёркивания: шапка блока уже опознана, разделителя под ней автор
#      не поставил, а ниже строки замечания поставил. Правило «строка перед первым разделителем
#      — шапка» обязано молчать здесь тоже: шапка у блока уже есть, значит эта строка — данные.
printf '%s\n| 2 | IMPORTANT | y | b.cs:2 | эскалация | U2-abcd |\n%s\n' "$hdr" "$sep" > "$TMP/hdr-row-delim.md"
out=$(run_gate "$TMP/hdr-row-delim.md"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; then
  ok "строка замечания под уже опознанной шапкой не вычёркивается разделителем ниже"
else
  not_ok "строка замечания под опознанной шапкой вычеркнута разделителем ниже (код $code)"
fi

# --- отказ ИНСТРУМЕНТА разбора ≠ «проверять нечего» (внешнее ревью PR #634, P1) ----------
# Класс дефекта этажом ниже прежних: не строка не проверена, а сам разбор НЕ СОСТОЯЛСЯ, и
# гейт счёл это чистотой. Пустой результат внешнего процесса читался как «замечаний нет»,
# потому что код возврата процесса не проверялся. Кейсы ниже подменяют инструмент разбора
# заглушкой с ненулевым кодом на ШТАТНОМ отчёте, который без подмены проходит: единственная
# разница между зелёным и красным — исход самого инструмента.
#
# Заглушка одного инструмента с заданным кодом возврата. Каталог свой на каждую заглушку,
# чтобы PATH кейса подменял ровно тот инструмент, который кейс проверяет.
make_tool_stub() {
  local dir="$TMP/tool-$1-$2"
  mkdir -p "$dir"
  printf '#!/bin/sh\nexit %s\n' "$2" > "$dir/$1"
  chmod +x "$dir/$1"
  printf '%s' "$dir"
}

# 74a. ОБЯЗАТЕЛЬНЫЙ КЕЙС НАХОДКИ. Шаблонный отчёт со строкой `defer to Beads` и валидным
#      идентификатором (тот самый, что в кейсе 1 даёт код 0), но `awk` подменён заглушкой с
#      кодом 2. До правки: разбор возвращал пустоту, цикл проверки выполнялся НОЛЬ раз, гейт
#      отдавал код 0 без единой строки вывода — нарушение fail-closed инварианта 2 контракта PR.
#      Теперь исход обязан быть стопом, и сообщение обязано называть ОТКАЗ ИНСТРУМЕНТА.
out=$(run_gate "$TMP/plain-ok.md" "$(make_tool_stub awk 2)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "awk завершился с кодом 2"; then
  ok "отказ awk на шаблонном отчёте с defer to Beads останавливает гейт, а не даёт код 0"
else
  not_ok "REGRESS PR #634 P1: отказ awk прочитан как «замечаний нет» (код $code): $(printf '%s' "$out" | head -1)"
fi

# 74b. Диагноз обязан быть АДРЕСНЫМ: отказ инструмента и «строк ноль» — разные адреса
#      починки (окружение против отчёта). Сообщение об отказе не имеет права выглядеть как
#      сообщение об отчёте, иначе PM правит отчёт вместо окружения.
out=$(run_gate "$TMP/plain-ok.md" "$(make_tool_stub awk 2)"); code=$?
if printf '%s' "$out" | grep >/dev/null "отказ ИНСТРУМЕНТА" \
   && { printf '%s' "$out" | grep -E >/dev/null "невалидный Beads ID|нераспознанный статус|вне таблицы замечаний"; search_status=("${PIPESTATUS[@]}"); [ "${search_status[*]}" = "0 1" ]; }; then
  ok "отказ awk диагностируется как отказ инструмента, а не как дефект отчёта"
else
  not_ok "диагноз отказа awk спутан с разбором содержимого отчёта (код $code): $(printf '%s' "$out" | head -1)"
fi

# 74c. Тот же класс на ПОДГОТОВКЕ сырья: `sed` снимает экранирование `\|` до разбора. Его
#      отказ давал разбору пустую строку — таблиц не найдено, цикл ноль раз, код 0. Кейс
#      отдельный от 74a: это другой процесс и другая строка скилла, и один код возврата
#      второй не покрывает.
out=$(run_gate "$TMP/plain-ok.md" "$(make_tool_stub sed 3)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "sed завершился с кодом 3"; then
  ok "отказ sed на подготовке тел отчётов останавливает гейт, а не даёт код 0"
else
  not_ok "отказ sed прочитан как «замечаний нет» (код $code): $(printf '%s' "$out" | head -1)"
fi

# 74d. КОНТРОЛЬНЫЙ КЕЙС: разбор отработал ШТАТНО и вернул ноль строк — поведение прежнее.
#      Без него правка выше была бы неотличима от «любой пустой разбор краснеет», а это
#      сломало бы законный исход «в отчёте нет таблицы замечаний» (заявленный предел U2-t233).
printf 'Внутреннее ревью, проход 3.\n\nЗамечаний нет, вердикт APPROVED.\n' > "$TMP/no-table.md"
out=$(run_gate "$TMP/no-table.md"); code=$?
if [ "$code" = "0" ]; then
  ok "разбор отработал и вернул ноль строк — поведение прежнее, ложного стопа нет"
else
  not_ok "штатный разбор с нулём строк дал стоп — сломан законный исход «таблицы замечаний нет» (код $code): $(printf '%s' "$out" | head -1)"
fi

# 74e/74f сняты вместе с их предметом: структурные проверки `VISIBLE_EXTERNAL` относились к
# legacy-фикстуре «старый Шаг 4: tier/iteration/external», которую этот пакет удалил из
# `.claude/skills/finalize-pr/SKILL.md` по ADR 3.29. Проверяемого текста в скилле больше нет,
# поэтому проверки не описывают никакого поведения. Класс «код возврата одиночного процесса
# не проверен» остаётся покрыт кейсами 74a–74d на живом блоке триажа.

# 58. АНТИ-ДРЕЙФ: набор статусов триажа записан в трёх местах — словарь опознания в awk,
#     метки строгого `case` и НОРМАТИВНЫЙ перечень в шаблоне `.agents/RV_ROLE.md`.
#     Сверять два внутренних списка друг с другом мало: согласованное расширение набора
#     сразу в обоих проходило зелёным, а норма при этом оставалась прежней. Поэтому третьим
#     источником взят сам шаблон — гейт не имеет права знать статусов, которых норма не
#     объявляет, и наоборот. Сравнение структурное: исполнением такое расхождение видно
#     только на той форме отчёта, которой в наборе может и не оказаться.
REVIEWER="$ROOT/.agents/RV_ROLE.md"
norm_statuses=$(awk '
  /^<!-- triage-statuses:start -->/ { f = 1; next }
  /^<!-- triage-statuses:end -->/   { exit }
  f && /^- `[^`]+`/ { s = $0; sub(/^- `/, "", s); sub(/`.*$/, "", s); print tolower(s) }
' "$REVIEWER" | sort)
wide_statuses=$(grep -o 'split("[^"]*", STATUS_LIST' "$SKILL" | sed 's/^split("//; s/", STATUS_LIST$//' | tr ';' '\n' | sort)
strict_statuses=$(awk '
  /^  case "\$status" in/ { c = 1; next }
  c && /^  esac/          { exit }
  c && /^    "[^"]+"\)/   { s = $0; sub(/^    "/, "", s); sub(/"\)$/, "", s); print tolower(s) }
' "$SKILL" | sort)
if [ -z "$norm_statuses" ]; then
  not_ok "в $REVIEWER нет размеченного перечня статусов триажа — анти-дрейф не с чем сверять"
elif [ "$wide_statuses" = "$strict_statuses" ] && [ "$wide_statuses" = "$norm_statuses" ]; then
  ok "набор статусов совпадает у словаря опознания, строгого case и шаблона reviewer.md"
else
  not_ok "набор статусов разошёлся (шаблон: $(printf '%s' "$norm_statuses" | tr '\n' ' ')/ словарь: $(printf '%s' "$wide_statuses" | tr '\n' ' ')/ case: $(printf '%s' "$strict_statuses" | tr '\n' ' '))"
fi

# --- МЕХАНИЗАЦИЯ СВЕРКИ СЛОЁВ ОПИСАНИЯ (итерация 8, смена тактики) -----------------------
# Класс «описание разошлось с механизмом» повторялся три итерации (числа радиуса; норма
# подписи; диагноз сироты) и закрывался рукой. Четвёртой ручной синхронизации нет: перечни
# имён и норма границы слова сверяются МАШИННО — расхождение любого слоя краснит набор.
# Тот же ход, что сверка triage-statuses выше. Источник истины — awk-словари скилла.
# ⚠️ ГРАНИЦА СИЛЫ этой сверки — честно (итерация 9, A3): она держит ТЕКСТ↔ТЕКСТ (перечни
# равны словарям, нормы-зеркала дословно совпадают), но НЕ доказывает ТЕКСТ↔МЕХАНИЗМ —
# что предложение нормы верно ОПИСЫВАЕТ поведение кода, держат поведенческие кейсы выше
# (54w4–54w8, 54s2–54s4), а не эта секция. Слои вне пары «скилл ↔ reviewer.md» (контракт
# в теле PR) машиной не сверяются — их держит ревью.
dict_stathdr=$(sed -n 's/.*STATHDR_N = split("\([^"]*\)".*/\1/p' "$SKILL")
dict_statalt=$(sed -n 's/.*STATALT_N = split("\([^"]*\)".*/\1/p' "$SKILL")
dict_findhdr=$(sed -n 's/.*FINDHDR_N = split("\([^"]*\)".*/\1/p' "$SKILL")
if [ -z "$dict_stathdr" ] || [ -z "$dict_statalt" ] || [ -z "$dict_findhdr" ]; then
  not_ok "словари колонок не извлечены из SKILL.md — сверка слоёв описания не с чем"
else
  ok "три словаря имён извлечены из awk-объявлений скилла"
fi

# Помощник: токены «...» и \`...\` из текста, разделитель — байт SOH (\001): перевод строки
# в значении -v валит BSD awk («newline in string»), и первый вариант сверки на этом ПАДАЛ
# МОЛЧА — пустой stdout при rc=2 читался как «расхождений нет». Отказ инструмента ≠ чистота:
# код возврата каждого прогона сверки проверяется отдельно (fail-closed, инвариант 9).
name_tokens() {
  printf '%s\n' "$1" | awk '
    { n = split($0, a, /«/); for (i = 2; i <= n; i++) { t = a[i]; sub(/».*/, "", t); print t }
      m = split($0, b, /`/); for (i = 2; i <= m; i += 2) print b[i] }' | tr '\n' '\001'
}
# Прогон сверки с проверкой исхода: $1 — токены (через \001), $2 — словари, $3 — REQLAT,
# $4 — подпись проверяемого слоя. Ненулевой awk — краснит сам по себе.
run_setcheck() {
  local toks="$1" dicts="$2" reqlat="$3" label="$4" out rc
  out=$(awk -v TOKENS="$toks" -v DICTS="$dicts" -v REQLAT="$reqlat" -f "$SETCHECK" 2>&1)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    not_ok "$label: сверка слоя не отработала (awk rc=$rc: $(printf '%s' "$out" | head -1)) — отказ инструмента не засчитывается за чистоту"
  elif [ -n "$out" ]; then
    not_ok "$label: $(printf '%s' "$out" | tr '\n' ';')"
  else
    ok "$label"
  fi
}

# Помощник: сверка токенов со словарями. Правила: латиница — без регистра; кириллица —
# точным совпадением с одной из записей (словари несут оба регистра); полнота — каждая
# кириллическая ПАРА словаря (соседние записи) представлена хотя бы одним регистром,
# каждая латинская запись представлена (если REQLAT=1). Печатает расхождения; молчание = ок.
SETCHECK="$TMP/setcheck.awk"
cat > "$SETCHECK" <<'SETCHECK_AWK'
BEGIN {
  nt = split(TOKENS, T, "\001"); nd = split(DICTS, D, ";")
  for (i = 1; i <= nt; i++) { sub(/^[ \t]+/, "", T[i]); sub(/[ \t]+$/, "", T[i]) }
  for (i = 1; i <= nt; i++) if (T[i] != "") {
    okm = 0
    for (j = 1; j <= nd; j++) {
      if (T[i] == D[j]) { okm = 1; break }
      if (D[j] ~ /^[A-Za-z]/ && tolower(T[i]) == tolower(D[j])) { okm = 1; break }
    }
    if (!okm) print "лишнее имя вне словаря: " T[i]
  }
  i = 1
  while (i <= nd) {
    if (D[i] ~ /^[A-Za-z]/) {
      if (REQLAT) {
        okm = 0
        for (k = 1; k <= nt; k++) if (tolower(T[k]) == tolower(D[i])) { okm = 1; break }
        if (!okm) print "в тексте нет словарного имени: " D[i]
      }
      i++
    } else {
      p1 = D[i]; p2 = (i + 1 <= nd && D[i + 1] !~ /^[A-Za-z]/ && D[i + 1] != p1) ? D[i + 1] : ""
      okm = 0
      for (k = 1; k <= nt; k++) if (T[k] == p1 || (p2 != "" && T[k] == p2)) { okm = 1; break }
      if (!okm) print "в тексте нет словарного имени: " p1
      i += (p2 != "") ? 2 : 1
    }
  }
}
SETCHECK_AWK

# 1. Диагноз NOSTATCOL: перечень поддерживаемых имён колонки решения = словари целиком.
nsline=$(grep -F 'Назови колонку статуса в шапке одним из поддерживаемых имён' "$SKILL" | head -1)
if [ -z "$nsline" ]; then
  not_ok "строка диагноза NOSTATCOL не найдена — перечень имён в сообщении не сверить"
else
  run_setcheck "$(name_tokens "$nsline")" "$dict_stathdr;$dict_statalt" 1 "диагноз NOSTATCOL перечисляет ровно словарные имена колонки решения"
fi

# 2. Диагноз страховки-сироты: slash-перечень ячейки замечания = FINDHDR; одиночные имена
#    решения — те же словари ЦЕЛИКОМ (REQLAT=1: расхождение двух диагнозов одной дельты —
#    итерация 8, F4/Minor5: сирота перечислял 5 русских имён против 10 у соседа, и автора
#    с английской шапкой сообщение уводило в ложное «не поддержано»).
orline=$(grep -F 'шапка не несёт подписи шаблона reviewer.md' "$SKILL" | head -1)
if [ -z "$orline" ]; then
  not_ok "строка диагноза сироты не найдена — подпись в сообщении не сверить"
else
  slash_tok=$(name_tokens "$orline" | tr '\001' '\n' | grep -F 'Severity' | head -1)
  slash_parts=$(printf '%s\n' "$slash_tok" | awk '{ n = split($0, a, "/"); for (i = 1; i <= n; i++) { t = a[i]; gsub(/^[ \t]+|[ \t]+$/, "", t); if (t != "") print t } }' | tr '\n' '\001')
  run_setcheck "$slash_parts" "$dict_findhdr" 1 "диагноз сироты несёт перечень ячейки замечания, равный словарю FINDHDR"
  single_toks=$(name_tokens "$orline" | tr '\001' '\n' | grep -v '[/ ]' | grep -v '^$' | tr '\n' '\001')
  run_setcheck "$single_toks" "$dict_stathdr;$dict_statalt" 1 "имена решения в диагнозе сироты равны словарям целиком — оба диагноза говорят одно"
fi

# 3–4. Норма reviewer.md: размеченные блоки перечней = словари. Маркеры — ровно по одному.
for mpair in 'decision-names' 'finding-names' 'word-boundary-norm' 'stub-phrase-norm'; do
  for mk in "<!-- ${mpair}:start -->" "<!-- ${mpair}:end -->"; do
    if [ "$(grep -c -F "$mk" "$REVIEWER")" != "1" ]; then
      not_ok "маркер '$mk' в reviewer.md встречается не один раз — блок сверки потерян"
    fi
  done
done
for mpair in 'word-boundary-norm' 'stub-phrase-norm'; do
  for mk in "# ${mpair}:start" "# ${mpair}:end"; do
    if [ "$(grep -c -F "$mk" "$SKILL")" != "1" ]; then
      not_ok "маркер '$mk' в SKILL.md встречается не один раз — норма-зеркало не извлекается"
    fi
  done
done
dn_block=$(awk '/<!-- decision-names:start -->/{f=1;next} /<!-- decision-names:end -->/{f=0} f' "$REVIEWER")
run_setcheck "$(name_tokens "$dn_block")" "$dict_stathdr;$dict_statalt" 1 "перечень имён решения в норме reviewer.md равен словарям скилла"
fn_block=$(awk '/<!-- finding-names:start -->/{f=1;next} /<!-- finding-names:end -->/{f=0} f' "$REVIEWER")
run_setcheck "$(name_tokens "$fn_block")" "$dict_findhdr" 1 "перечень ячейки замечания в норме reviewer.md равен словарю FINDHDR"

# 5. Нормы-предложения: текст между маркерами в reviewer.md и в комментарии скилла РАВЕН
#    (после нормализации пробелов и снятия решётки комментария). Краснит РАСХОЖДЕНИЕ ТЕКСТОВ
#    двух зеркал; соответствие текста МЕХАНИЗМУ эта проверка не доказывает — его держат
#    поведенческие кейсы (54w4–54w8, 54s2–54s4). Пар две: граница слова и фраза-заглушка.
for npair in 'word-boundary-norm' 'stub-phrase-norm'; do
  n_skill=$(awk -v M="$npair" 'index($0, "# " M ":start"){f=1;next} index($0, "# " M ":end"){f=0} f { sub(/^[ \t]*#[ \t]?/, ""); print }' "$SKILL" | tr '\n' ' ' | awk '{ gsub(/[ \t]+/, " "); sub(/^ /, ""); sub(/ $/, ""); print }')
  n_norm=$(awk -v M="$npair" 'index($0, "<!-- " M ":start -->"){f=1;next} index($0, "<!-- " M ":end -->"){f=0} f' "$REVIEWER" | tr '\n' ' ' | awk '{ gsub(/[ \t]+/, " "); sub(/^ /, ""); sub(/ $/, ""); print }')
  if [ -n "$n_skill" ] && [ "$n_skill" = "$n_norm" ]; then
    ok "норма '$npair' в reviewer.md дословно равна норме в скилле — механизм и текст связаны"
  else
    not_ok "норма '$npair' разошлась: скилл '$n_skill' против reviewer.md '$n_norm'"
  fi
done

# --- fail-closed на сетевом получении отчётов (инвариант 4 контракта PR) ----------------
# Этот участок скилла лежит МЕЖДУ маркерами и в основное извлечение намеренно не попадает,
# поэтому кейсы выше его не исполняют. Отдельная сборка ниже прогоняет ровно его, подменяя
# `gh` заглушкой. Без неё снятие проверки кода возврата не краснило НИЧЕГО: сценарий
# перехватывался соседней проверкой пустого ответа, и половина инварианта 4 держалась
# только на чтении глазами.
FETCH="$TMP/triage-fetch.sh"
awk '
  /^# triage-fetch:start/ { f = 1; next }
  /^# triage-fetch:end/   { exit }
  f                       { print }
' "$SKILL" | sed 's/<PR_NUMBER>/634/g' > "$FETCH"
if ! grep -q 'TRIAGE_JSON=' "$FETCH" || ! grep -q 'REVIEW_BODIES=' "$FETCH"; then
  not_ok "участок сетевого получения тел не извлекается из SKILL.md — инвариант 4 не проверяется исполнением"
else
  ok "участок сетевого получения тел извлечён из действующего SKILL.md"

  # Заглушка `gh`: код возврата и вывод задаёт кейс. Тело — через файл-носитель, а не через
  # bash-`printf %q` в тексте скрипта: тот же класс переносимости, что у make_rc_stub ниже
  # (dash как `/bin/sh` Linux-раннера не понимает ANSI-C форму `$'…'` — см. комментарий там).
  make_gh_stub() {
    local dir
    dir=$(mktemp -d "$TMP/gh-$1.XXXXXX")
    printf '%s' "$2" > "$dir/stub-body"
    {
      printf '#!/bin/sh\n'
      printf 'cat "%s/stub-body"\n' "$dir"
      printf 'exit %s\n' "$3"
    } > "$dir/gh"
    chmod +x "$dir/gh"
    printf '%s' "$dir"
  }
  run_fetch() {
    {
      # ⚠️ НЕ `pipefail` — та же причина, что у `run_piece` и `run_gate`.
      printf 'set -u\n'
      printf 'HEAD_COMMIT="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"\n'
      cat "$HELPER"
      cat "$FETCH"
      printf 'echo ПОЛУЧЕНО\n'
    } > "$TMP/run-fetch.sh"
    env PATH="$1:/usr/bin:/bin:/usr/sbin:/sbin" bash "$TMP/run-fetch.sh" 2>&1
  }

  # 59. Ненулевой код возврата при НЕПУСТОМ валидном выводе. Кейс адресный именно так:
  #     при пустом выводе стоп пришёл бы от соседней проверки, и снятие проверки кода
  #     возврата осталось бы незамеченным.
  #     ⚠️ Утверждение пришпилено к СВОЕЙ диагностике целиком, вместе с кодом. Прежнее
  #     требование «в выводе есть слово „код“» набиралось и посторонним сообщением: вне
  #     git-репозитория преамбула помощника ограничения времени сама печатает «git завершился
  #     с кодом 128» и выходит, и кейс зеленел, ни разу не дойдя до проверяемого места.
  out=$(run_fetch "$(make_gh_stub rc '{"comments":[]}' 1)"); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "не удалось получить triage-комментарии PR (код 1)"; then
    ok "сетевое получение: ненулевой код возврата останавливает гейт даже при валидном выводе"
  else
    not_ok "сетевое получение: ненулевой код возврата при валидном выводе пропущен (код $code)"
  fi

  # 60. Пустой ответ при нулевом коде возврата.
  out=$(run_fetch "$(make_gh_stub empty '' 0)"); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "пустой результат"; then
    ok "сетевое получение: пустой ответ останавливает гейт"
  else
    not_ok "сетевое получение: пустой ответ пропущен (код $code)"
  fi

  # 61. Невалидный JSON при нулевом коде возврата и непустом выводе.
  out=$(run_fetch "$(make_gh_stub bad 'не json' 0)"); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный JSON"; then
    ok "сетевое получение: невалидный JSON останавливает гейт"
  else
    not_ok "сетевое получение: невалидный JSON пропущен (код $code)"
  fi

  # 62. Штатный ответ — ложного стопа быть не должно, иначе три кейса выше были бы зелёными
  #     от любой поломки участка.
  gh_ok='{"comments":[{"body":"review-pass\nCommit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n"}]}'
  out=$(run_fetch "$(make_gh_stub ok "$gh_ok" 0)"); code=$?
  if [ "$code" = "0" ] && printf '%s' "$out" | grep >/dev/null "ПОЛУЧЕНО"; then
    ok "сетевое получение: штатный ответ проходит без ложного стопа"
  else
    not_ok "ложный стоп на штатном ответе сетевого получения (код $code)"
  fi
fi

# --- структурные проверки соседних мест скилла ------------------------------
# Фикстура прогоняет только блок триажа, поэтому соседние шаги гейта она исполнением
# не видит. Эти две проверки закрывают ровно те места, где правка триажа однажды
# сломала соседей (внешнее ревью, находки F1 и F3).

# 63. Шаг 3 обязан отличать «отчёта нет» от «отчёт есть»: при `.body + <что-то>` jq вернёт
#     непустую строку даже когда отчётов ноль, и проверка `[ -z ... ]` не сработает никогда.
if grep -A9 'LAST_INTERNAL=' "$SKILL" | grep -E >/dev/null '^\s*\|\s*\.body // empty\s*$'; then
  ok "шаг 3 использует '.body // empty' — проверка отсутствия отчёта жива"
else
  not_ok "шаг 3: LAST_INTERNAL не использует '.body // empty' — проверка отсутствия review-pass мертва"
fi

# 64. Тела отчётов обязаны разделяться: без разделителя поотчётная страховка деградирует
#     до проверки суммы тел. Разделитель пишется видимым escape, не управляющим байтом —
#     литеральный байт не переживает копирование блока агентом и блокируется харнессом.
if grep -A9 'REVIEW_BODIES=' "$SKILL" | grep >/dev/null '\.body + "\\u001e"'; then
  ok "тела отчётов разделяются видимым escape-разделителем"
else
  not_ok "REVIEW_BODIES: нет видимого разделителя '\\u001e' — страховка деградирует до суммы тел"
fi

# 65. Delivery First content-equivalence обязан быть исполняемым, а не только prose:
#     prior CODE REVIEW несёт Content-Fingerprint, который сравнивается с current package+contract.
if grep -q 'EVIDENCE_SHA="$HEAD_COMMIT"' "$SKILL"    && grep -q 'EVIDENCE_FINGERPRINT' "$SKILL"    && grep -q 'CURRENT_CONTENT_FINGERPRINT' "$SKILL"; then
  ok "Шаг 3 содержит исполняемый content-equivalence route"
else
  not_ok "Шаг 3: content-equivalence остаётся декларативным — нет evidence/current fingerprint binding"
fi

# 66. Triage обязан читать findings с SHA доказанного review evidence, а не безусловно current HEAD.
if grep -q 'TRIAGE_EVIDENCE_SHA="${EVIDENCE_SHA:-$HEAD_COMMIT}"' "$SKILL"    && grep -q -- '--arg head "$TRIAGE_EVIDENCE_SHA"' "$SKILL"; then
  ok "Шаг 6 triage привязан к EVIDENCE_SHA"
else
  not_ok "Шаг 6: triage по-прежнему безусловно привязан к current HEAD"
fi

# --- граница опций для значения из отчёта (внешнее ревью PR #634, P1) -------------------
# Класс дефекта: значение, взятое из ТЕЛА ОТЧЁТА, попадает в командную строку внешней
# команды без границы опций. Для `defer to Beads` payload уходил первым позиционным
# аргументом `bd show`, где `bd` читал его как ОПЦИЮ: `--help` / `-h` / `--version`
# возвращают 0, и гейт засчитывал несуществующую задачу как существующую.
#
# Заглушка ниже повторяет РАЗБОР ОПЦИЙ настоящего CLI, а не просто возвращает код: без
# этого кейсы были бы утверждением о выдуманном `bd`, а не о находке. Задач в заглушке нет
# вовсе — любой идентификатор для неё «не найден», поэтому единственный путь получить 0 —
# именно исполнение справочной опции.
make_bd_optlike_stub() {
  local dir="$TMP/bd-optlike"
  mkdir -p "$dir"
  {
    printf '#!/bin/sh\n'
    printf 'seen_dash=0\n'
    printf 'for a in "$@"; do\n'
    printf '  if [ "$seen_dash" = "0" ] && [ "$a" = "--" ]; then seen_dash=1; continue; fi\n'
    printf '  if [ "$seen_dash" = "0" ]; then\n'
    printf '    case "$a" in\n'
    printf '      --help|-h|--version|-v) exit 0 ;;\n'
    printf '    esac\n'
    printf '  fi\n'
    printf 'done\n'
    printf 'exit 1\n'
  } > "$dir/bd"
  chmod +x "$dir/bd"
  printf '%s' "$dir"
}

# 65-68. Значения, похожие на опции, обязаны давать СТОП при УСТАНОВЛЕННОМ `bd`.
#        До правки все четыре проходили молча (код 0): `bd` печатал справку и возвращал 0.
for optlike in '--help' '-h' '--version' '-U2-abcd'; do
  printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | %s |\n' "$hdr" "$sep" "$optlike" \
    > "$TMP/optlike.md"
  out=$(run_gate "$TMP/optlike.md" "$(make_bd_optlike_stub)"); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
    ok "payload '$optlike' при установленном bd останавливает гейт"
  else
    not_ok "REGRESS PR #634 P1: payload '$optlike' прошёл как существующая задача (код $code)"
  fi
done

# 69-72. Тот же класс на запасном пути — когда `bd` НЕ установлен. Поведение обязано
#        остаться fail-closed: значение не попадает в команду и не считается валидным.
for optlike in '--help' '-h' '--version' '-U2-abcd'; do
  printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | %s |\n' "$hdr" "$sep" "$optlike" \
    > "$TMP/optlike-nobd.md"
  out=$(run_gate "$TMP/optlike-nobd.md"); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; then
    ok "payload '$optlike' без установленного bd останавливает гейт"
  else
    not_ok "payload '$optlike' на запасном пути не дал стопа (код $code)"
  fi
done

# 73. Обратная сторона проверки формы: РЕАЛЬНЫЕ идентификаторы проекта обязаны проходить.
#     Без этого кейса находку P1 закрыли бы регуляркой, отвергающей половину живых ID, и
#     гейт стал бы ложно стопорить каждый законный defer.
real_ids_ok=1
for rid in 'U2-t233' 'U2-h9hh' 'U2-m5b1' 'U2-a08' 'U2-9nz8' 'U2-1gfa' 'big-heroes-abc'; do
  printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | %s |\n' "$hdr" "$sep" "$rid" \
    > "$TMP/real-id.md"
  # Заглушка `bd`, отвечающая «задача есть»: проверяется именно проход формы, не наличие.
  if [ "$(gate_code "$TMP/real-id.md" "$(make_bd_stub found 0)")" != "0" ]; then
    not_ok "проверка формы отвергла реальный Beads ID '$rid' при установленном bd"
    real_ids_ok=0
  fi
  # Тот же идентификатор на запасном пути (без `bd`) — тоже обязан проходить.
  if [ "$(gate_code "$TMP/real-id.md")" != "0" ]; then
    not_ok "проверка формы отвергла реальный Beads ID '$rid' на запасном пути"
    real_ids_ok=0
  fi
done
[ "$real_ids_ok" = "1" ] && ok "реальные Beads ID проекта проходят проверку формы на обоих путях"

# 74. Структурная: форма проверяется ДО внешнего вызова. Порядок и есть содержание фикса —
#     проверка формы после вызова оставила бы `bd` исполнять опцию, а кейсы выше держались бы
#     только на границе `--`. Проверяем по ДЕЙСТВУЮЩЕМУ извлечению, а не по чтению глазами.
#     ⚠️ Строки-комментарии отбрасываются: соседние комментарии скилла упоминают и `bd show`,
#     и само регулярное выражение по делу, и без отбрасывания проверка сравнивала бы позиции
#     пояснений, а не кода.
CODEONLY="$TMP/triage-code-only.sh"
grep -vE '^[[:space:]]*#' "$EXTRACT" > "$CODEONLY"
form_line=$(grep -n -F "grep -qE '^[A-Za-z][A-Za-z0-9-]+-[a-z0-9]+\$'" "$CODEONLY" | head -1 | cut -d: -f1)
bd_line=$(grep -n -F 'bd show' "$CODEONLY" | head -1 | cut -d: -f1)
if [ -n "$form_line" ] && [ -n "$bd_line" ] && [ "$form_line" -lt "$bd_line" ]; then
  ok "проверка формы Beads ID стоит до вызова bd show"
else
  not_ok "проверка формы Beads ID не предшествует вызову bd show (форма: ${form_line:-нет}, bd: ${bd_line:-нет})"
fi

# 75. Структурная: граница опций `--` у вызова `bd show` — вторая защита к проверке формы.
#     Имя переменной обновлено вместе с разделением носителей платежа: `defer to Beads` читает
#     колонку идентификатора (`$bead_id`), отклонение — колонку обоснования (`$rationale`).
if grep -q 'bd show -- "\$bead_id"' "$EXTRACT"; then
  ok "вызов bd show закрывает список опций границей '--'"
else
  not_ok "у вызова bd show нет границы опций '--' — значение из отчёта снова читается как опция"
fi

# 76. Структурная: значение из отчёта не подставляется в позицию аргумента `echo` —
#     `-n` / `-e` там читаются как опции ровно так же, как у `bd show`.
if ! { grep -vE '^[[:space:]]*#' "$EXTRACT" | grep -E >/dev/null 'echo "\$(payload|bead_id|rationale|status|num)"'; search_status=("${PIPESTATUS[@]}");
  [ "${search_status[0]}" -le 1 ] && [ "${search_status[1]}" -eq 1 ]; }; then
  not_ok "значение из отчёта уходит аргументом echo — тот же класс, что и у bd show"
else
  ok "значения из отчёта не попадают в позицию аргумента echo"
fi

# --- отказ UPSTREAM-процесса конвейера ≠ «проверять нечего» (внешнее ревью PR #634, P1) -----
# Класс дефекта этажом выше прежнего: код возврата у шага ПРОВЕРЯЛСЯ, но в конвейере `A | B`
# он принадлежит только `B`. Отказ `A` (нет команды, ненулевой код, частичный вывод) оставался
# невидимым, `B` отрабатывал успешно на том, что успело прийти, и шаг сообщал «всё в порядке»
# о данных, которые не читались. Кейсы ниже задают заглушке ИМЕННО этот вход: ненулевой код
# ПРИ ПРАВДОПОДОБНОМ ВЫВОДЕ. При пустом выводе стоп пришёл бы от соседней проверки пустоты, и
# снятие проверки кода возврата снова осталось бы незамеченным.

# Заглушка произвольной команды: вывод и код возврата задаёт кейс. Каталог свой на каждую,
# чтобы PATH кейса подменял ровно то, что кейс проверяет.
# ⚠️ Тело печатается через `cat` файла-носителя по абсолютному пути, а НЕ внедряется в текст
# скрипта через bash-`printf %q`: заглушку исполняет ядро по шебангу `#!/bin/sh`, и для тела
# с реальным переводом строки (а в старых bash — с любым не-ASCII) `%q` даёт ANSI-C форму
# `$'…'`, которую понимает bash (`/bin/sh` macOS), но не dash (`/bin/sh` Linux-раннера):
# dash печатал литеральный `$` и `\n`, заголовок паспорта остатка не находился, и кейс 138
# краснел ТОЛЬКО в CI. Путь абсолютный, а не `dirname "$0"`: combo-кейсы копируют один
# скрипт в свой каталог, и он обязан печатать тело, замороженное на момент создания.
# Каталог уникален НА ВЫЗОВ (mktemp): повторный вызов с теми же именем и кодом не
# перезаписывает тело, на которое ссылается ранее скопированный стаб.
make_rc_stub() {
  local dir
  dir=$(mktemp -d "$TMP/rcstub-$1-$3.XXXXXX")
  printf '%s' "$2" > "$dir/stub-body"
  {
    printf '#!/bin/sh\n'
    printf 'cat "%s/stub-body"\n' "$dir"
    printf 'exit %s\n' "$3"
  } > "$dir/$1"
  chmod +x "$dir/$1"
  printf '%s' "$dir"
}

# Извлечение bash-блока скилла ПО СОДЕРЖИМОМУ (первый блок, где встречается образец) и
# извлечение блока по ПАРНЫМ МАРКЕРАМ. Оба берут действующий текст скилла: синтезировать
# проверяемые строки в фикстуре нельзя — тогда тест проверял бы копию.
extract_block_with() {
  awk -v needle="$1" '
    $0 ~ /^[[:space:]]*```bash$/ { inside = 1; buffer = ""; matched = 0; next }
    inside && $0 ~ /^[[:space:]]*```$/ {
      if (matched) { printf "%s", buffer; emitted = 1; exit }
      inside = 0; next
    }
    inside { buffer = buffer $0 ORS; if (index($0, needle)) matched = 1 }
    END { if (!emitted) exit 1 }
  ' "$SKILL" | sed 's/<PR_NUMBER>/634/g' > "$2"
  [ -s "$2" ]
}
extract_marked() {
  awk -v s="# $1:start" -v e="# $1:end" '
    index($0, s) { f = 1; next }
    f && index($0, e) { exit }
    f { print }
  ' "$SKILL" | sed 's/<PR_NUMBER>/634/g' > "$2"
  [ -s "$2" ]
}

# Прогон извлечённого куска: помощник ограничения времени берётся ИЗ СКИЛЛА, пролог задаёт
# кейс, рабочий каталог — подставной корень (там лежат .claude/tools для помощника).
# Четвёртым аргументом кейс отключает помощник ограничения времени. Это нужно кейсам, которые
# подменяют `git`: сам помощник ищет свой файл через `git rev-parse --show-toplevel`, и с
# подменённым `git` прогон обрывался бы на преамбуле, не дойдя до проверяемого места.
run_piece() {
  local piece="$1" stub_dir="$2" prelude="$3" no_helper="${4:-}"
  {
    # ⚠️ НЕ `pipefail`. Скилл исполняется агентом в обычной оболочке, где `pipefail` не
    # установлен; включив его в прогоне, фикстура сделала бы конвейеры fail-closed сама и
    # объявила бы починенным то, что в бою по-прежнему пропускает отказ upstream.
    printf 'set -u\n'
    [ -z "$no_helper" ] && cat "$HELPER"
    printf '%s\n' "$prelude"
    cat "$piece"
    printf 'echo КУСОК-ПРОЙДЕН\n'
  } > "$TMP/run-piece.sh"
  ( cd "$SNAP_ROOT" && env PATH="$stub_dir:/usr/bin:/bin:/usr/sbin:/sbin" bash "$TMP/run-piece.sh" 2>&1 )
}

# --- чтения PR: ненулевой код при ПРАВДОПОДОБНОМ выводе (Шаги 1-4 и re-check перед публикацией)
# Каждый кейс подсовывает заглушку, которая печатает то, чего гейт ждёт, и завершается кодом 1.
# До правки такой исход проходил молча: значение непустое, разбор успешен, шаг «пройден» —
# при том что чтение не состоялось. Именно эту форму назвала находка.
HEAD_FAKE=deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
comments_json="{\"comments\":[{\"createdAt\":\"2026-08-13T10:00:00Z\",\"body\":\"review-pass\\nCommit: $HEAD_FAKE\\n\\\"iteration\\\": 3\\nВердикт: APPROVED\"}]}"

assert_read_fails_closed() {
  local piece="$1" label="$2" stub_out="$3" prelude="$4" tool="${5:-gh}"
  local out code
  out=$(run_piece "$piece" "$(make_rc_stub "$tool" "$stub_out" 1)" "$prelude"); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "$tool завершился с кодом 1"; then
    ok "$label: ненулевой $tool при правдоподобном выводе останавливает гейт"
  else
    not_ok "REGRESS PR #634 P1: $label — отказ $tool скрыт успешным разбором (код $code): $(printf '%s' "$out" | head -1)"
  fi
}
assert_read_passes() {
  local piece="$1" label="$2" stub_out="$3" prelude="$4"
  local out code
  out=$(run_piece "$piece" "$(make_rc_stub gh "$stub_out" 0)" "$prelude"); code=$?
  if [ "$code" = "0" ] && printf '%s' "$out" | grep >/dev/null "КУСОК-ПРОЙДЕН"; then
    ok "$label: штатное чтение проходит без ложного стопа"
  else
    not_ok "$label: ложный стоп на штатном чтении (код $code): $(printf '%s' "$out" | head -1)"
  fi
}

# 141-143. Шаг 1 — фиксация HEAD.
STEP1="$TMP/step1.sh"
if ! extract_block_with 'HEAD_COMMIT=$(run_with_timeout' "$STEP1"; then
  not_ok "блок фиксации HEAD не извлекается из SKILL.md"
else
  ok "блок фиксации HEAD извлечён из действующего SKILL.md"
  assert_read_fails_closed "$STEP1" "Шаг 1" "$HEAD_FAKE" ''
  assert_read_passes "$STEP1" "Шаг 1" "$HEAD_FAKE" ''
fi

# 144-147. Шаг 3 — поиск internal review-pass: два процесса, два кода возврата.
STEP3="$TMP/step3.sh"
if ! extract_block_with 'INTERNAL_COMMENTS_JSON=$(run_with_timeout' "$STEP3"; then
  not_ok "блок поиска internal review-pass не извлекается из SKILL.md"
else
  ok "блок поиска internal review-pass извлечён из действующего SKILL.md"
  assert_read_fails_closed "$STEP3" "Шаг 3 (чтение)" "$comments_json" "HEAD_COMMIT=$HEAD_FAKE"
  # Отказ РАЗБОРА проверяется отдельно: один код возврата второй не покрывает. Заглушка `jq`
  # печатает валидное тело и завершается кодом 5 — до правки шаг читал бы это как «отчёта нет».
  combo3="$TMP/rcstub-step3-combo"
  mkdir -p "$combo3"
  cp "$(make_rc_stub gh "$comments_json" 0)/gh" "$combo3/gh"
  cp "$(make_rc_stub jq 'review-pass APPROVED' 5)/jq" "$combo3/jq"
  out=$(run_piece "$STEP3" "$combo3" "HEAD_COMMIT=$HEAD_FAKE"); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "jq завершился с кодом 5"; then
    ok "Шаг 3 (разбор): ненулевой jq при непустом выводе останавливает гейт"
  else
    not_ok "Шаг 3 (разбор): отказ jq прочитан как «internal review-pass нет» (код $code): $(printf '%s' "$out" | head -1)"
  fi
  assert_read_passes "$STEP3" "Шаг 3" "$comments_json" "HEAD_COMMIT=$HEAD_FAKE"
fi

# 154-156. Re-check HEAD перед публикацией: заглушка печатает ТОТ ЖЕ commit и падает кодом 1.
STEPRE="$TMP/step-recheck.sh"
if ! extract_block_with 'HEAD_NOW=$(run_with_timeout' "$STEPRE"; then
  not_ok "блок повторной проверки HEAD не извлекается из SKILL.md"
else
  ok "блок повторной проверки HEAD извлечён из действующего SKILL.md"
  assert_read_fails_closed "$STEPRE" "Re-check HEAD" "$HEAD_FAKE" "HEAD_COMMIT=$HEAD_FAKE"
  assert_read_passes "$STEPRE" "Re-check HEAD" "$HEAD_FAKE" "HEAD_COMMIT=$HEAD_FAKE"
fi

# 157-158. Шаг 2 — сверка локального HEAD. Заглушка `git` печатает ТОТ ЖЕ commit и падает
#          кодом 1: до правки шаг сравнивал строки, они совпадали, и отказ проходил молча.
STEP2="$TMP/step2.sh"
if ! extract_block_with 'LOCAL_HEAD=$(git rev-parse HEAD)' "$STEP2"; then
  not_ok "блок сверки локального HEAD не извлекается из SKILL.md"
else
  ok "блок сверки локального HEAD извлечён из действующего SKILL.md"
  out=$(run_piece "$STEP2" "$(make_rc_stub git "$HEAD_FAKE" 1)" "HEAD_COMMIT=$HEAD_FAKE" no-helper); code=$?
  if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "git завершился с кодом 1"; then
    ok "Шаг 2: ненулевой git при совпадающем выводе останавливает гейт"
  else
    not_ok "REGRESS PR #634 P1: Шаг 2 — отказ git скрыт совпадением строк (код $code): $(printf '%s' "$out" | head -1)"
  fi
fi

# 159-162. Шаг 6, строчный разбор: инструменты внутри цикла проверки. Оба кейса адресные —
#          до правки стоп БЫЛ, но с диагнозом про ОТЧЁТ, хотя сломано ОКРУЖЕНИЕ.
out=$(run_gate "$TMP/plain-ok.md" "$(make_tool_stub tr 4)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "tr завершился с кодом 4"; then
  ok "Шаг 6: отказ tr при восстановлении колонок останавливает гейт своим диагнозом"
else
  not_ok "Шаг 6: отказ tr выдан за дефект отчёта (код $code): $(printf '%s' "$out" | head -1)"
fi
if printf '%s' "$out" | grep >/dev/null "отказ ИНСТРУМЕНТА" \
   && { printf '%s' "$out" | grep >/dev/null "нераспознанный статус"; search_status=("${PIPESTATUS[@]}"); [ "${search_status[*]}" = "0 1" ]; }; then
  ok "Шаг 6: отказ tr не выдаётся за нераспознанный статус"
else
  not_ok "Шаг 6: диагноз отказа tr спутан с содержимым отчёта: $(printf '%s' "$out" | head -1)"
fi

out=$(run_gate "$TMP/plain-ok.md" "$(make_tool_stub grep 2)"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep >/dev/null "grep завершился с кодом 2"; then
  ok "Шаг 6: отказ grep при проверке формы Beads ID останавливает гейт своим диагнозом"
else
  not_ok "Шаг 6: отказ grep выдан за невалидный Beads ID (код $code): $(printf '%s' "$out" | head -1)"
fi
if printf '%s' "$out" | grep >/dev/null "отказ ИНСТРУМЕНТА" \
   && { printf '%s' "$out" | grep >/dev/null "невалидный Beads ID"; search_status=("${PIPESTATUS[@]}"); [ "${search_status[*]}" = "0 1" ]; }; then
  ok "Шаг 6: отказ grep не выдаётся за невалидный идентификатор"
else
  not_ok "Шаг 6: диагноз отказа grep спутан с содержимым отчёта: $(printf '%s' "$out" | head -1)"
fi

# ИСПОЛНЕНИЕМ: чтение корня репозитория в ветке проверки Beads. Внешнее ревью PR #634, P1 —
# `BD_REPO_ROOT="$(git rev-parse …)"` сохраняло только вывод и теряло код возврата. Заглушка
# печатает КОРРЕКТНЫЙ корень и завершается кодом 5: до правки все маршруты Beads находились
# по верным путям, снимок отвечал «задача есть», и гейт печатал GATE_SUCCESS с кодом 0.
# Первый `rev-parse` (preflight помощника ограничения времени) заглушка пропускает штатно —
# иначе кейс останавливался бы раньше и о своём месте ничего не говорил.
gitrc_stub="$TMP/gitrc-stub"
mkdir -p "$gitrc_stub"
{
  printf '#!/bin/sh\n'
  printf 'CNT=%s\n' "$(printf '%q' "$TMP/gitrc-count")"
  printf 'if [ "$1" = "rev-parse" ]; then\n'
  printf '  printf %%s\\\\n %s\n' "$(printf '%q' "$SNAP_ROOT")"
  printf '  n=$(cat "$CNT" 2>/dev/null || echo 0)\n'
  printf '  n=$((n + 1))\n'
  printf '  echo "$n" > "$CNT"\n'
  printf '  [ "$n" -ge 2 ] && exit 5\n'
  printf '  exit 0\n'
  printf 'fi\n'
  printf 'exec /usr/bin/git "$@"\n'
} > "$gitrc_stub/git"
chmod +x "$gitrc_stub/git"
rm -f "$TMP/gitrc-count"
printf '%s\n%s\n| 1 | WARNING | x | a.cs:1 | defer to Beads | U2-abcd |\n' "$hdr" "$sep" > "$TMP/gitrc.md"
out=$(run_gate "$TMP/gitrc.md" "$gitrc_stub" "$SNAP_ROOT"); code=$?
if [ "$code" != "0" ] && printf '%s' "$out" | grep -F >/dev/null "git завершился с кодом 5"; then
  ok "ветка Beads: отказ git при чтении корня останавливает гейт своим диагнозом"
else
  not_ok "ветка Beads: отказ git прочитан как «корень есть» — маршруты искались по пустому пути (код $code): $(printf '%s' "$out" | head -1)"
fi

# СТРУКТУРНО: код возврата publisher'а. Блок публикации фикстура исполнять не вправе (он
# ходит в GitHub), поэтому проверяются обе половины формы — и что она стоит у ВСЕХ трёх
# вызовов. Молчание об отказе публикации — самый дорогой из возможных: оператор считал бы
# PR финализированным по несуществующему комментарию (внешнее ревью PR #634, P1).
publisher_calls=$(grep -c -F 'FINALIZE_PR_TOKEN=1 "$PYTHON_LAUNCHER"' "$SKILL")
publisher_rc_lines=$(grep -A1 -F 'FINALIZE_PR_TOKEN=1 "$PYTHON_LAUNCHER"' "$SKILL" | grep -c -F 'publish_rc=$?')
publisher_rc_checks=$(grep -c -F 'if [ "$publish_rc" -ne 0 ]; then' "$SKILL")
if [ "$publisher_calls" = "3" ] && [ "$publisher_rc_lines" = "3" ] && [ "$publisher_rc_checks" = "3" ]; then
  ok "все три вызова publisher записывают и проверяют код возврата публикации"
else
  not_ok "публикация без проверки кода возврата (вызовов $publisher_calls, записей $publisher_rc_lines, проверок $publisher_rc_checks) — неопубликованный комментарий читался бы как финализация"
fi

# ЕДИНЫЙ сплошной разбор bash-блоков скилла. Один проход выдаёт находки ЧЕТЫРЁХ классов,
#      потому что все они опираются на одно и то же — на умение отличить КОД ОБОЛОЧКИ от текста
#      вокруг него (тел программ `jq`/`awk`, heredoc, комментариев, регулярных выражений).
#      Второй такой разбор разошёлся бы с первым молча, поэтому механизм здесь один.
#
#      Класс 1 — КОНВЕЙЕРЫ. Код возврата конвейера принадлежит последнему процессу, отказ
#      upstream маскируется успехом downstream. Поэтому в командах гейта конвейеров не остаётся
#      ВОВСЕ: вход следующему шагу подаётся строкой через `<<<`.
#      ⚠️ Предмет проверки — ВЕРТИКАЛЬНАЯ ЧЕРТА В ПОЗИЦИИ КОНВЕЙЕРА, а не список имён команд
#      справа от неё. Прежний детектор перечислял имена (`| grep`, `| jq`, …) и работал по
#      ФИЗИЧЕСКИМ строкам — обе половины оказались дырявыми (второй фикс-раунд PR #634):
#        • конвейер с переносом строки (`… "$PR_BODY" |` ⏎ `  grep …)`) не совпадал ни с одним
#          именем, потому что имя уезжало на следующую строку;
#        • конвейер в команду, названную ПЕРЕМЕННОЙ (`… | "$PYTHON_LAUNCHER" …`), не совпадал
#          по построению: имя вычисляется, и в списке его быть не может.
#      Черта ищется посимвольно вне кавычек, поэтому регулярные выражения (`a|b` внутри
#      кавычек), тела `jq`/`awk`, heredoc, `<<<` и комментарии её не порождают; `||` не
#      конвейер и пропускается. Исключений у правила нет намеренно: любая законная
#      альтернатива (метка ветки `case` вида `a|b)`) обязана краснеть и разбираться человеком,
#      а не проходить по молчаливому послаблению — промах здесь дешевле пропуска.
#
#      Класс 2 — ОДИНОЧНЫЕ процессы без проверки кода возврата. Внешнее ревью PR #634 нашло
#      шесть таких мест разом (preflight `git`, `head -30`, `git rev-parse` в ветке Beads,
#      `cat` в теле force-режима и три вызова publisher). Закрывать их поштучно значит ждать
#      седьмого.
#      ⚠️ Детектор построен ОТ ОБРАТНОГО: перечислены РАЗРЕШЁННЫЕ формы, всё прочее — находка.
#      Разрешено ровно три формы:
#        1. следующая строка кода записывает код возврата в переменную (`имя=$?`);
#        2. команда — оболочечная встроенная, внешнего процесса не порождающая (в том числе
#           `command -v`, который лишь ищет имя и процесса не запускает);
#        3. на строку выше стоит явный маркер-исключение `# rc-исключение: <причина>`
#           (или `# rc-исключение-блока:` на весь справочный блок).
#
#      Класс 4 — ВНЕШНЯЯ КОМАНДА В ПОЗИЦИИ УСЛОВИЯ ИЛИ СВЯЗКИ (`if`/`elif`/`while`/`until`/`!`,
#      `&&`, `||`, `;`). Прежде эта позиция вычёркивалась ЦЕЛИКОМ как «там код возврата и есть
#      ответ» — и под послаблением жила находка внешнего прохода 10: определение класса
#      окружения Beads стояло в `if`, отказ `git` внутри него читался как содержательный ответ
#      «не основной checkout», и гейт доходил до GATE_SUCCESS.
#      Различаются два случая, и различает их МАРКЕР, а не догадка разбора:
#        • команда-ПРОБА — её код возврата и ЕСТЬ ответ, промах уводит в безопасную ветку;
#          законна, но объявляется маркером `# проба-условия: <причина>` строкой выше;
#        • команда, чей отказ неотличим от содержательного ответа, — находка: её код возврата
#          обязан записываться и разбираться отдельно от результата.
#      Число маркеров обоих видов зафиксировано кейсами ниже: молча добавить исключение нельзя.
#
#      ⚠️ Все классы меряются по ЛОГИЧЕСКИМ строкам оболочки, а не по физическим. Физическая
#      строка склеивается со следующей, пока команда не закончилась: открыта кавычка, хвост —
#      `\`, `|`, `&&` или `||`. Без склейки продолжение конвейера читалось как отдельная
#      команда и уходило из-под обоих классов (именно так мутация с переносом строки давала
#      полностью зелёный набор).
#
#      ⚠️ Программа разбора лежит ОТДЕЛЬНЫМ ФАЙЛОМ, а не инлайном в подстановке, ровно по одной
#      причине: сплошная проверка утверждает ОТСУТСТВИЕ находок, и её молчание неотличимо от
#      молчания сломанного разбора. Файл позволяет прогнать ТУ ЖЕ программу на образцах с
#      заведомо известным ответом и показать, что у неё есть сигнал (кейсы ниже). Копии
#      программы при этом нет — источник один.
SCANNER="$TMP/skill-scan.awk"
cat > "$SCANNER" <<'SKILL_SCAN_AWK'
  BEGIN {
    SQ = sprintf("%c", 39); DQ = sprintf("%c", 34)
    RCPAT = "^[[:space:]]*(local[[:space:]]+)?[^[:space:]=]+=[$][?][[:space:]]*$"
    # Оболочечные встроенные: внешнего процесса не порождают, отказ окружения им не грозит.
    BI_N = split("printf;echo;true;false;cd;pwd;test;[;read;shift;return;exit;local;export;unset;set;continue;break;.;source;:;eval;trap;wait;declare;typeset;alias", BI, ";")
  }
  !inb && /^[[:space:]]*```bash$/ { inb = 1; blk++; next }
  inb && !inq && hd == "" && pend == 0 && /^[[:space:]]*```$/ { inb = 0; next }
  !inb { next }
  hd != "" {
    t = $0; sub(/^[[:space:]]+/, "", t); sub(/[[:space:]]+$/, "", t)
    if (t == hd) hd = ""
    next
  }
  {
    raw = $0
    # Строка-комментарий распознаётся только НА ГРАНИЦЕ логической строки: внутри незакрытой
    # команды решётка уже разобрана посимвольно, а маркер-исключение относится к следующей
    # логической строке, не к продолжению текущей.
    if (!inq && !pend && raw ~ /^[[:space:]]*#/) {
      if (raw ~ /rc-исключение-блока:/) blkex[blk] = 1
      else if (raw ~ /rc-исключение:/) pendex = 1
      else if (raw ~ /проба-условия:/) pendpr = 1
      next
    }
    started = inq
    scan(raw)
    # Черта в позиции конвейера — находка сразу и независимо от того, чем логическая строка
    # кончится: адрес у неё физический, и так его проще чинить.
    if (PIPEAT) { np++; pln[np] = NR; ptx[np] = trim(CODEPART) }
    # Тело чужой программы (строка НАЧАЛАСЬ внутри кавычек) кодом оболочки не является:
    # в накопитель логической строки оно не идёт, но саму строку не закрывает.
    code = started ? "" : CODEPART
    if (!pend && code ~ /^[[:space:]]*$/ && !inq) next
    # Хранится КОД строки без хвостового комментария (`CODEPART` заполняет `scan`): иначе
    # строка вида `VAR=...   # пояснение` читалась бы как «команда #».
    if (pend) { sub(/^[[:space:]]+/, "", code); acc = acc " " code }
    else      { acc = code; accln = NR }
    tail = acc; sub(/[[:space:]]+$/, "", tail)
    # Логическая строка продолжается: открытая кавычка либо хвост, зовущий продолжение.
    pend = (inq || tail ~ /\\$/ || tail ~ /\|$/ || tail ~ /&&$/)
    if (pend) next
    n++; ln[n] = accln; tx[n] = acc; bl[n] = blk; ex[n] = pendex; pendex = 0; prex[n] = pendpr; pendpr = 0; acc = ""
  }
  END {
    # Незакрытая логическая строка или незакрытый heredoc на конце файла — сами по себе повод
    # не молчать: значит разбор потерял границу и всё, что было за ней, из всех классов выпало.
    if (pend) print "OPEN " accln ": логическая строка не закрыта до конца файла"
    if (hd != "") print "OPEN " NR ": тело heredoc не закрыто делимитером «" hd "» до конца файла"
    for (i = 1; i <= np; i++) print "PIPE " pln[i] ": " ptx[i]
    for (i = 1; i <= n; i++) {
      if (ex[i] || blkex[bl[i]]) continue
      s = trim(tx[i])
      if (s ~ /^[A-Za-z_][A-Za-z0-9_]*\(\)[[:space:]]*\{/) continue
      # метка ветки `case`: строка заканчивается `)` и открывающей скобки не несёт
      if (s ~ /\)$/ && index(s, "(") == 0) continue
      # ⚠️ ПОЗИЦИЯ УСЛОВИЯ БОЛЬШЕ НЕ ВЫЧЁРКИВАЕТСЯ ЦЕЛИКОМ (внешнее ревью PR #634, проход 10).
      # Прежняя редакция пропускала любую строку, начинающуюся с `if`/`elif`/`while`/`until`/`!`,
      # и любую, где встретились `&&` или `||`. Под этим послаблением жила находка: определение
      # класса окружения Beads стояло в позиции условия, и отказ `git` ВНУТРИ него читался как
      # содержательный ответ «не основной checkout».
      # Различаются два случая, и различает их МАРКЕР, а не догадка разбора:
      #   • команда-ПРОБА — её код возврата и ЕСТЬ ответ, а промах уводит в безопасную ветку.
      #     Законна, но обязана быть объявлена маркером `# проба-условия: <причина>` строкой выше;
      #   • команда, чей отказ неотличим от содержательного ответа. Маркера у неё нет, и она
      #     находка: код возврата обязан быть записан и разобран отдельно.
      # Оболочечные встроенные (включая `command -v`) внешнего процесса не порождают, отказ
      # окружения им не грозит — они не требуют ни маркера, ни записи кода возврата.
      nsg = segs(s, sg)
      if (nsg > 1 || s ~ /^(if|elif|while|until|!)([[:space:]]|$)/) {
        if (prex[i]) continue
        for (q = 1; q <= nsg; q++) {
          cq = segcmd(sg[q])
          if (cq != "") print "COND " ln[i] ": " SEGKIND " " cq " в позиции условия/связки без маркера пробы"
        }
        continue
      }
      cmd = segcmd(s)
      if (cmd == "") continue
      what = SEGKIND " " cmd
      # форма 1 — следующая строка кода записывает код возврата
      j = i + 1
      while (j <= n && tx[j] ~ /^[[:space:]]*\)[[:space:]]*$/) j++
      if (j <= n && tx[j] ~ RCPAT) continue
      print "RC " ln[i] ": " what
    }
    # Класс 3 — ЖИВАЯ ЛИ ветка. Записанный код возврата сам по себе ничего не удерживает:
    # ветка `if [ "$X" -ne 0 ]; then echo …; fi` без действия — это проверка, которая ничего
    # не делает, и отказ инструмента проходит ровно как раньше. Поэтому у КАЖДОЙ записи `X=$?`
    # требуется ветка по этой переменной, а у ветки — действие: выход (`exit`/`return`),
    # управление циклом (`continue`/`break`) либо запись состояния (`TRIAGE_FAILED=1`,
    # `beads_found=1`). Только вывод сообщения действием не считается.
    for (i = 1; i <= n; i++) {
      s = trim(tx[i])
      if (s !~ /^[A-Za-z_][A-Za-z0-9_]*=[$][?]$/) continue
      v = s; sub(/=[$][?]$/, "", v)
      # Ветка ищется среди ближайших логических строк: между записью и проверкой законно
      # стоят другие записи (четыре колонки строки замечания разбираются подряд).
      ifl = 0
      for (j = i + 1; j <= i + 8 && j <= n; j++) {
        t = trim(tx[j])
        if (t ~ /^(if|elif)[[:space:]]/ && index(t, DQ "$" v DQ) > 0) { ifl = j; break }
      }
      if (!ifl) { print "DEAD " ln[i] ": код возврата " v " записан, но ветки по нему рядом нет"; continue }
      depth = 1; eff = 0
      for (j = ifl + 1; j <= ifl + 40 && j <= n; j++) {
        t = trim(tx[j])
        if (t ~ /^(if|while|until)[[:space:]]/ || t ~ /^case[[:space:]]/) { depth++; continue }
        if (t == "fi" || t == "done" || t == "esac") { depth--; if (depth == 0) break; continue }
        if (depth != 1) continue
        if (t ~ /^(else|elif)/) break
        if (t ~ /^(exit|return|continue|break)([[:space:]]|$)/) { eff = 1; break }
        if (t ~ /^(local[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=/) { eff = 1; break }
      }
      if (!eff) print "DEAD " ln[ifl] ": ветка по " v " не делает ничего — ни выхода, ни записи состояния"
    }
  }
  function norm(c) { gsub(/["]/, "", c); gsub(SQ, "", c); return c }
  function isbuiltin(c,   k) {
    c = norm(c)
    for (k = 1; k <= BI_N; k++) if (c == BI[k]) return 1
    return 0
  }
  # Разбиение логической строки на КОМАНДНЫЕ ПОЗИЦИИ: границы `&&`, `||`, `;` вне кавычек.
  # Вертикальная черта здесь не граница — она предмет отдельного класса (конвейеры) и до
  # этого места доходить не должна.
  function segs(s, out,   i, c, L, q, cur, k) {
    L = length(s); q = ""; cur = ""; k = 0
    for (i = 1; i <= L; i++) {
      c = substr(s, i, 1)
      if (q != "") { cur = cur c; if (c == q) q = ""; continue }
      if (c == SQ || c == DQ) { q = c; cur = cur c; continue }
      if (c == "&" && substr(s, i + 1, 1) == "&") { k++; out[k] = cur; cur = ""; i++; continue }
      if (c == "|" && substr(s, i + 1, 1) == "|") { k++; out[k] = cur; cur = ""; i++; continue }
      if (c == ";") { k++; out[k] = cur; cur = ""; if (substr(s, i + 1, 1) == ";") i++; continue }
      cur = cur c
    }
    k++; out[k] = cur
    return k
  }
  # Первое СЛОВО строки с учётом кавычек; хвост остаётся в `WORDREST`. Нужен, чтобы отличить
  # префикс окружения перед командой (`IFS="$GS" read -r …`) от самостоятельного присваивания
  # (`VALUE=$(…)`): у первого после слова есть команда, у второго — нет.
  function cutword(s,   i, c, q, L, d) {
    L = length(s); q = ""; d = 0
    for (i = 1; i <= L; i++) {
      c = substr(s, i, 1)
      if (q != "") { if (c == q) q = ""; continue }
      if (c == SQ || c == DQ) { q = c; continue }
      # `$(…)` и `${…}` — часть слова целиком: пробел внутри подстановки слово не рвёт,
      # иначе `SEP=$(printf ' ')` читалось бы как присваивание плюс посторонняя команда.
      if (c == "$" && (substr(s, i + 1, 1) == "(" || substr(s, i + 1, 1) == "{")) { d++; i++; continue }
      if (d > 0 && (c == ")" || c == "}")) { d--; continue }
      if (d == 0 && (c == " " || c == "\t")) break
    }
    WORDREST = substr(s, i)
    return substr(s, 1, i - 1)
  }
  # ВНЕШНЯЯ команда сегмента: "" — команды нет, она ключевое слово либо оболочечная встроенная.
  # Побочно заполняет `SEGKIND` («команда» / «подстановка») — тем же словом, которым находку
  # называл прежний разбор, чтобы адрес починки в сообщении не изменился.
  function segcmd(t,   rhs, p, c, decl) {
    SEGKIND = "команда"
    t = trim(t)
    while (t ~ /^(if|elif|while|until|then|else|do|!)([[:space:]]|$)/) {
      sub(/^(if|elif|while|until|then|else|do|!)[[:space:]]*/, "", t); t = trim(t)
    }
    if (t == "") return ""
    # Закрывающие слова и скобки командой не являются; хвост-перенаправление
    # (`done <<< "$ROWS"`, `} > "$FILE"`) их таковыми не делает.
    if (t ~ /^(fi|done|esac|;;)([[:space:]]|$)/) return ""
    if (t ~ /^[{}()]([[:space:]]|$)/) return ""
    if (t ~ /^(for|case|in|time|function)([[:space:]]|$)/) return ""
    # Объявление (`local a=1 b c=2`) отличается от префикса окружения перед командой
    # (`IFS="$GS" read -r …`) только ключевым словом: после объявления идут ИМЕНА, после
    # префикса — команда. Внешний процесс и там, и там бывает лишь в подстановке справа.
    decl = 0
    if (t ~ /^(local|export|declare|typeset|readonly)([[:space:]]|$)/) {
      decl = 1; sub(/^(local|export|declare|typeset|readonly)[[:space:]]*/, "", t); t = trim(t)
    }
    # Имя переменной сопоставляется как «непробельное без `=`»: имена в скилле бывают
    # кириллическими (`значение_rc`), и латинский класс их не покрывает.
    while (t ~ /^[^[:space:]=]+=/) {
      rhs = cutword(t)
      p = index(rhs, "$(")
      if (p > 0 && substr(rhs, p, 3) != "$((") {
        c = substr(rhs, p + 2); sub(/^[[:space:]]+/, "", c)
        match(c, /^[^[:space:];)]+/); c = norm(substr(c, 1, RLENGTH))
        if (isbuiltin(c)) return ""
        SEGKIND = "подстановка"
        return c
      }
      t = trim(WORDREST)
    }
    if (decl || t == "") return ""
    match(t, /^[^[:space:]]+/); c = substr(t, 1, RLENGTH)
    # `command -v X` — оболочечная встроенная: внешнего процесса нет вовсе.
    if (norm(c) == "command" && t ~ /^command[[:space:]]+-v([[:space:]]|$)/) return ""
    if (isbuiltin(c)) return ""
    return norm(c)
  }
  function trim(s) {
    sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s)
    return s
  }
  function scan(s,   i, c, L, rest, d) {
    L = length(s)
    CODEPART = s
    PIPEAT = 0
    for (i = 1; i <= L; i++) {
      c = substr(s, i, 1)
      if (inq) { if (c == qch) { inq = 0; qch = "" }; continue }
      if (c == SQ || c == DQ) { inq = 1; qch = c; continue }
      if (c == "#") { CODEPART = substr(s, 1, i - 1); return }
      # Вертикальная черта вне кавычек. `||` — не конвейер, обе её черты пропускаются разом,
      # иначе вторая прочиталась бы как самостоятельная и дала бы находку на каждом `[ … ] || [ … ]`.
      if (c == "|") {
        if (substr(s, i + 1, 1) == "|") { i++; continue }
        PIPEAT = i
        continue
      }
      if (c == "<" && substr(s, i, 2) == "<<" && substr(s, i, 3) != "<<<") {
        rest = substr(s, i + 2); sub(/^-/, "", rest)
        # Делимитер берётся как есть и очищается от кавычек ПОСЛЕ выделения. Символьный
        # класс с кавычками здесь недопустим: внутри одинарно-кавыченной awk-программы его
        # пришлось бы склеивать из shell-подстановок, а под `set -u` неизвестная переменная
        # оболочки обрывала бы весь детектор — и он молча «не находил ничего».
        if (match(rest, /^[^[:space:])]+/)) {
          d = substr(rest, RSTART, RLENGTH); gsub(/["]/, "", d); gsub(SQ, "", d)
          if (d != "") hd = d
        }
        i++
      }
    }
  }
SKILL_SCAN_AWK
skill_scan=$(awk -f "$SCANNER" "$SKILL")
# Разбор один, утверждений три — по классу находок. Разделение по префиксу строки, а не
# повторным запуском awk: второй запуск той же программы разошёлся бы с первым при первой же
# правке. `grep` здесь идёт по строке-переменной через `<<<` — тот же канон, что и в скилле.
pipeline_hits=$(grep '^PIPE ' <<< "$skill_scan")
cond_hits=$(grep '^COND ' <<< "$skill_scan")
rc_hits=$(grep '^RC ' <<< "$skill_scan")
dead_hits=$(grep '^DEAD ' <<< "$skill_scan")
open_hits=$(grep '^OPEN ' <<< "$skill_scan")

if [ -z "$pipeline_hits" ]; then
  ok "в командах гейта не осталось конвейеров — код возврата шага принадлежит его единственному процессу"
else
  not_ok "в командах гейта осталась вертикальная черта в позиции конвейера (отказ upstream маскируется успехом downstream): $(printf '%s' "$pipeline_hits" | head -3 | tr '\n' ' ')"
fi

# Класс 4 — внешняя команда в позиции условия/связки. Прежний детектор вычёркивал эту позицию
# ЦЕЛИКОМ, и под послаблением жила находка внешнего прохода 10: определение класса окружения
# Beads стояло в `if`, отказ `git` внутри него читался как ответ «не основной checkout», и гейт
# доходил до GATE_SUCCESS. Законная проба остаётся законной, но объявляется маркером.
if [ -z "$cond_hits" ]; then
  ok "каждая внешняя команда в позиции условия/связки объявлена маркером пробы — молчаливых там нет"
else
  not_ok "внешняя команда в позиции условия/связки без маркера пробы (её отказ читается как содержательный ответ): $(printf '%s' "$cond_hits" | head -4 | tr '\n' ' ')"
fi

if [ -z "$rc_hits" ]; then
  ok "у каждого одиночного процесса в командах гейта код возврата проверяется либо стоит явное исключение"
else
  not_ok "одиночный процесс без проверки кода возврата (отказ читается как «проверять нечего»): $(printf '%s' "$rc_hits" | head -4 | tr '\n' ' ')"
fi

# Второй фикс-раунд PR #634: структурные проверки прежней редакции удовлетворялись МЁРТВЫМ
# кодом. Они требовали, чтобы код возврата был записан и упомянут, — и обезвреживание ветки
# (`exit 1` → `:`) не краснело НИ В ОДНОМ из девяти мест: ветка была на месте, переменная
# читалась, а гейт после отказа инструмента шёл дальше как ни в чём не бывало.
if [ -z "$dead_hits" ]; then
  ok "каждая ветка проверки кода возврата что-то делает — выходит, продолжает цикл или пишет состояние"
else
  not_ok "проверка кода возврата есть, а действия в ней нет — после отказа инструмента гейт идёт дальше: $(printf '%s' "$dead_hits" | head -4 | tr '\n' ' ')"
fi

# Самопроверка разбора: незакрытая логическая строка означает, что склейка потеряла границу,
# и оба класса выше замолчали бы не потому, что находок нет.
if [ -z "$open_hits" ]; then
  ok "разбор bash-блоков скилла завершился на закрытой логической строке — граница склейки не потеряна"
else
  not_ok "разбор bash-блоков скилла оборвался внутри логической строки — оба сплошных класса выше замолчали не по существу: $(printf '%s' "$open_hits" | head -2 | tr '\n' ' ')"
fi

# --- сигнал сплошного разбора: та же программа на образцах с известным ответом --------------
# Три утверждения выше говорят «находок нет». Такое утверждение стоит ровно столько, сколько
# доказано, что программа УМЕЕТ кричать: сломанный разбор молчит точно так же. Поэтому тот же
# файл `$SCANNER` (копии программы нет) прогоняется на образцах, где ответ известен заранее.
# Обе формы, пропущенные прежним детектором, стоят здесь отдельными кейсами.
assert_scan_finds() {
  local sample="$1" prefix="$2" label="$3" out
  out=$(awk -f "$SCANNER" "$sample")
  if printf '%s\n' "$out" | grep >/dev/null "^${prefix} "; then
    ok "$label"
  else
    not_ok "$label — разбор промолчал, значит и молчание на скилле ничего не утверждает: $(printf '%s' "$out" | head -2 | tr '\n' ' ')"
  fi
}

sample_wrapped="$TMP/scan-wrapped.md"
cat > "$sample_wrapped" <<'SAMPLE_WRAPPED'
```bash
VALUE=$(printf '%s\n' "$SRC" |
  grep -m1 -iE '^Tier:')
value_rc=$?
```
SAMPLE_WRAPPED
assert_scan_finds "$sample_wrapped" PIPE \
  "детектор видит конвейер С ПЕРЕНОСОМ СТРОКИ — имя команды на следующей строке его не прячет"

sample_varcmd="$TMP/scan-varcmd.md"
cat > "$sample_varcmd" <<'SAMPLE_VARCMD'
```bash
printf '%s' "$BODY" | "$PYTHON_LAUNCHER" "$PUBLISHER" 1 -
publish_rc=$?
```
SAMPLE_VARCMD
assert_scan_finds "$sample_varcmd" PIPE \
  "детектор видит конвейер в команду, названную ПЕРЕМЕННОЙ — вычисляемого имени в списке быть не может"

# Образец обрывается посреди тела чужой программы: кавычка не закрыта, значит разбор потерял
# границу кода и всё, что за ней, из обоих классов выпало бы молча.
sample_open="$TMP/scan-open.md"
cat > "$sample_open" <<'SAMPLE_OPEN'
```bash
ROWS=$(awk '
  { print $1 }
SAMPLE_OPEN
assert_scan_finds "$sample_open" OPEN \
  "детектор сообщает о незакрытой логической строке, а не заканчивает разбор молча"

sample_norc="$TMP/scan-norc.md"
cat > "$sample_norc" <<'SAMPLE_NORC'
```bash
VALUE=$(grep -m1 x <<< "$SRC")
echo "$VALUE"
```
SAMPLE_NORC
assert_scan_finds "$sample_norc" RC \
  "детектор видит одиночный процесс, у которого код возврата никуда не записан"

# Мёртвая ветка: код возврата записан, ветка по нему есть, а действия в ней нет. Ровно эта
# форма получалась из мутации «`exit 1` → `:`», и прежняя структурная проверка её не видела.
sample_dead="$TMP/scan-dead.md"
cat > "$sample_dead" <<'SAMPLE_DEAD'
```bash
VALUE=$(grep -m1 x <<< "$SRC")
value_rc=$?
if [ "$value_rc" -ne 0 ]; then
  echo "СТОП: не прочитано." >&2
  :
fi
```
SAMPLE_DEAD
assert_scan_finds "$sample_dead" DEAD \
  "детектор видит ОБЕЗВРЕЖЕННУЮ ветку проверки кода возврата — сообщение без выхода веткой не считается"

# Позиция условия. Образец — ТА САМАЯ форма, которой жила находка внешнего прохода 10:
# определение класса окружения стоит в `if`, и его отказ читается как содержательный ответ.
sample_cond="$TMP/scan-cond.md"
cat > "$sample_cond" <<'SAMPLE_COND'
```bash
if command -v bd_env_is_main_checkout >/dev/null 2>&1 && bd_env_is_main_checkout; then
  beads_main_checkout=1
fi
```
SAMPLE_COND
assert_scan_finds "$sample_cond" COND \
  "детектор видит внешнюю команду в позиции условия — форму, которой жила находка прохода 10"

# Обратная сторона: объявленная маркером ПРОБА законна и молчит. Без этой половины кейс выше
# был бы неотличим от «в позиции условия запрещено всё», и маркер стал бы бессмысленным.
sample_cond_ok="$TMP/scan-cond-ok.md"
cat > "$sample_cond_ok" <<'SAMPLE_COND_OK'
```bash
# проба-условия: код возврата и есть ответ, промах уводит в безопасную ветку
if bd_env_is_main_checkout; then
  beads_main_checkout=1
fi
```
SAMPLE_COND_OK
cond_ok_out=$(awk -f "$SCANNER" "$sample_cond_ok")
if [ -z "$cond_ok_out" ]; then
  ok "объявленная маркером проба в позиции условия разбор не тревожит"
else
  not_ok "маркер пробы не работает — законная форма краснеет: $(printf '%s' "$cond_ok_out" | head -2 | tr '\n' ' ')"
fi

# КОНТРОЛЬ. Без него все четыре кейса выше зеленели бы от «разбор кричит на что угодно», а
# сплошные проверки на скилле стали бы вечно красными. Образец собран из ЗАКОННЫХ форм, где
# вертикальная черта стоит по делу: логическое ИЛИ, тело чужой программы, регулярное
# выражение в кавычках, тело heredoc, строка-комментарий.
sample_clean="$TMP/scan-clean.md"
cat > "$sample_clean" <<'SAMPLE_CLEAN'
```bash
# в комментарии черта законна: a | b
if [ -z "$X" ] || [ "$X" = "null" ]; then
  exit 1
fi
ROWS=$(awk '
  /^a|^b/ { print $1 }
  BEGIN { sepr = "c|d" }
' <<< "$SRC")
rows_rc=$?
if [ "$rows_rc" -ne 0 ]; then
  echo "СТОП: разбор не выполнен." >&2
  exit 1
fi
MATCH=$(grep -oE 'x|y' <<< "$ROWS")
match_rc=$?
if [ "$match_rc" -ge 2 ]; then
  FAILED=1
fi
BODY=$(cat <<'INNER_BODY'
таблица | с | чертой
INNER_BODY
)
body_rc=$?
if [ "$body_rc" -ne 0 ]; then
  return 1
fi
```
SAMPLE_CLEAN
clean_out=$(awk -f "$SCANNER" "$sample_clean")
if [ -z "$clean_out" ]; then
  ok "на законных формах (логическое ИЛИ, тело awk, регулярное выражение, heredoc, комментарий) разбор молчит — кейсы выше не от крика на всё подряд"
else
  not_ok "разбор кричит на законной черте: $(printf '%s' "$clean_out" | head -3 | tr '\n' ' ')"
fi

# Маркер-исключение — не глушилка «на всякий случай»: его число в скилле зафиксировано,
# и рост требует осознанного обновления числа вместе с обоснованием в самом маркере.
rc_exemptions=$(grep -c -F 'rc-исключение' "$SKILL")
if [ "$rc_exemptions" = "1" ]; then
  ok "маркеров-исключений ровно 1 — ни один не добавлен молча"
else
  not_ok "число маркеров rc-исключение изменилось ($rc_exemptions вместо 1): исключение из инварианта 9 добавлено или снято без обновления фикстуры"
fi

# То же и по той же причине для маркера пробы в позиции условия. Он объявляет, что код
# возврата команды и ЕСТЬ ответ; молча добавленный маркер вернул бы вычёркивание всей позиции
# `if`/`&&`, под которым и жила находка внешнего прохода 10.
# ⚠️ ЗОНА СЧЁТЧИКА РАВНА ЗОНЕ ДЕЙСТВИЯ ИСКЛЮЧЕНИЯ — весь файл. Сканер экранирует маркер в
# ЛЮБОМ bash-блоке скилла, включая исполняемую преамбулу (preflight помощника ограничения
# времени стоит ВЫШЕ заголовка «Фаза 1»). Прежний счётчик считал только ниже «Фаза 1»:
# маркер, вставленный в преамбулу, получал исключение сканера, не попадая в счёт, — канал
# молчаливого ослабления, проверено исполнением (внутреннее ревью PR #634, итерация 6).
# Форма строки — та же, которой маркер опознаёт сканер: строка-комментарий со словом
# `проба-условия:`. Ожидаемых строк пять: четыре действующих маркера в командах гейта плюс
# нормативный образец Формы 2 в преамбуле — образец лежит в bash-блоке, для сканера он
# действует так же и потому считается наравне с действующими.
# Ожидаемое число записано ОДИН раз: три места ниже читают одну переменную, вторая запись
# числа разъехалась бы молча (тот же класс, что у SEP/GS).
probe_expected=3
probe_exemptions=$(grep -c -E '^[[:space:]]*#.*проба-условия:' "$SKILL")
if [ "$probe_exemptions" = "$probe_expected" ]; then
  ok "строк-маркеров пробы-условия ровно $probe_expected — ни один не добавлен молча"
else
  not_ok "число строк-маркеров проба-условия изменилось ($probe_exemptions вместо $probe_expected): исключение сканера добавлено или снято без обновления фикстуры — счёт идёт по всему файлу, включая преамбулу"
fi

# 171-172. СТРУКТУРНАЯ проверка для места, которое исполнением недостижимо: блок сбора полей
#          паспорта приёмки содержит текстовые заглушки (`UNRESOLVED=$(...)`) и целиком не
#          исполняется. `base` — поле привязки паспорта: отказ чтения давал пустую привязку.
if grep -A2 -F 'BASE_SHA=$(run_with_timeout' "$SKILL" | grep -F >/dev/null 'base_sha_rc=$?'; then
  ok "сбор паспорта: код возврата чтения base записан"
else
  not_ok "сбор паспорта: у BASE_SHA нет записи кода возврата — паспорт издаётся с пустой привязкой"
fi
if grep -A8 -F 'BASE_SHA=$(run_with_timeout' "$SKILL" | grep -F >/dev/null 'if [ "$base_sha_rc" -ne 0 ]; then'; then
  ok "сбор паспорта: код возврата чтения base не только записан, но и проверен"
else
  not_ok "сбор паспорта: base_sha_rc записан, но не проверен — переменная мёртвая"
fi

# СТРУКТУРНЫЕ проверки для шагов, которые заглушкой по образцу не изолируются (их процесс не
# отличим по аргументам от соседнего) либо лежат в блоке публикации, исполнять который фикстура
# не вправе. Проверяются ТРИ половины, а не две: код записан, ветка по нему стоит И ветка
# что-то делает.
#
# ⚠️ Второй фикс-раунд PR #634 закрыл здесь два разных дефекта.
#   1. Мёртвый код удовлетворял проверку. Прежняя редакция требовала лишь встретить в окне
#      `<var>=$?` и `"$<var>"`. Мутация «`exit 1` → `:`» — ветка на месте, делать ей нечего —
#      не краснела ни в одном из девяти мест. Теперь требуется ЛИТЕРАЛ ДЕЙСТВИЯ внутри ветки
#      (по умолчанию `exit 1`; у маршрутов Beads действие другое и передаётся аргументом).
#   2. Якорь был неуникален и проверялся «где-нибудь». `REPO_ROOT=$(git rev-parse
#      --show-toplevel)` стоит в скилле ТРИЖДЫ, а `grep -q` довольствовался любой уцелевшей
#      копией: снятие проверки во втором и третьем шаблонах кейс не замечал. Теперь якорь
#      сверяется с ЦЕЛОЙ строкой (подстрока `REPO_ROOT=…` иначе цепляла бы ещё и
#      `PREFLIGHT_REPO_ROOT=…`, и `BD_REPO_ROOT=…` — у них другие переменные кода возврата),
#      и условие обязано выполняться ВО ВСЕХ вхождениях. Отсутствие якоря — тоже провал:
#      переименованная строка не имеет права молча выключить кейс.
assert_rc_recorded_and_read() {
  local anchor="$1" rcvar="$2" label="$3" effect="${4:-exit 1}" report
  report=$(awk -v anchor="$anchor" -v rcvar="$rcvar" -v eff="$effect" '
    function trim(s) { sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s); return s }
    { line[NR] = $0 }
    END {
      DQ = sprintf("%c", 34)
      for (i = 1; i <= NR; i++) {
        if (trim(line[i]) != anchor) continue
        total++
        rcl = 0
        for (j = i + 1; j <= i + 3 && j <= NR; j++)
          if (trim(line[j]) == rcvar "=$?") { rcl = j; break }
        if (!rcl) { print i ": код возврата не записан"; continue }
        ifl = 0
        for (j = rcl + 1; j <= rcl + 8 && j <= NR; j++) {
          t = trim(line[j])
          if (t ~ /^(if|elif)[[:space:]]/ && index(t, DQ "$" rcvar DQ) > 0) { ifl = j; break }
        }
        if (!ifl) { print i ": ветки по " rcvar " нет — переменная мёртвая"; continue }
        depth = 1; found = 0
        for (j = ifl + 1; j <= ifl + 40 && j <= NR; j++) {
          t = trim(line[j])
          if (t ~ /^(if|while|until)[[:space:]]/ || t ~ /^case[[:space:]]/) { depth++; continue }
          if (t == "fi" || t == "done" || t == "esac") { depth--; if (depth == 0) break; continue }
          if (depth != 1) continue
          if (t ~ /^(else|elif)/) break
          if (t == eff) { found = 1; break }
        }
        if (!found) print ifl ": ветка по " rcvar " не исполняет «" eff "» — проверка есть, действия нет"
      }
      if (total == 0) print "0: якорь в скилле не найден — кейс проверял бы пустоту"
    }
  ' "$SKILL")
  if [ -z "$report" ]; then
    ok "$label: код возврата записан, проверен, и ветка исполняет «${effect}» — во всех вхождениях якоря"
  else
    not_ok "$label: $(printf '%s' "$report" | head -3 | tr '\n' ' ')"
  fi
}
assert_rc_recorded_and_read 'REPO_ROOT=$(git rev-parse --show-toplevel)' repo_root_rc "Публикация (корень репозитория, все три шаблона)"
assert_rc_recorded_and_read 'BASE_SHA=$(run_with_timeout 10 gh pr view <PR_NUMBER> --json baseRefOid -q '"'"'.baseRefOid'"'"')' base_sha_rc "Сбор паспорта (base commit)"
# Места, закрытые по внешнему ревью PR #634 (P1, класс «код возврата одиночного процесса»).
# Исполнением они не изолируются: блок публикации ходит в GitHub, preflight выполняется до
# извлекаемого фикстурой участка, а показ начала отчёта стоит в шаге 3.
# ⚠️ Вызовы стоят ПОСЛЕ объявления `assert_rc_recorded_and_read`: та же проверка, поставленная
# выше по файлу, молча не исполнялась бы («command not found» в stderr не считается провалом).
# Сборка тела force-комментария — единственное место, где команда растянута телом heredoc:
# общий помощник смотрит на 2-8 строк ниже якоря и упёрся бы в текст шаблона. Якорь —
# закрывающий делимитер и скобка подстановки сразу за ним.
if grep -A2 -F 'GH_BODY_<RAND>' "$SKILL" | grep -F >/dev/null 'body_rc=$?' \
   && grep -qF 'if [ "$body_rc" -ne 0 ]; then' "$SKILL"; then
  ok "Force-режим (сборка тела комментария): код возврата процесса записан и прочитан"
else
  not_ok "Force-режим (сборка тела комментария): отказ cat даёт пустое тело, и оно уходит в публикацию"
fi
assert_rc_recorded_and_read 'PREFLIGHT_REPO_ROOT=$(git rev-parse --show-toplevel)' preflight_repo_root_rc "Preflight (корень репозитория)"
assert_rc_recorded_and_read 'head -30 <<< "$LAST_INTERNAL"' head_preview_rc "Шаг 3 (показ начала отчёта)"
# Голый `$?` в условии верен лишь до первой команды, вставленной между вызовом и проверкой,
# и такая вставка не краснеет ничем — поэтому форма именованной переменной обязательна.
# ⚠️ Здесь действие ветки ДРУГОЕ и передаётся аргументом: маршрут Beads не выходит из гейта, он
# помечает найденную задачу. Умолчание `exit 1` дало бы ложный провал на законной форме, а
# «любое действие сойдёт» — вернуло бы дыру, ради которой аргумент и заведён.
assert_rc_recorded_and_read 'run_with_timeout 15 bash "$BD_WT_ROUTE" show -- "$bead_id" >/dev/null 2>&1' bd_wt_exit "Маршрут 2 Beads (обёртка worktree)" 'beads_found=1'
assert_rc_recorded_and_read 'BD_REPO_ROOT=$(git rev-parse --show-toplevel)' bd_repo_root_rc "Ветка Beads (корень репозитория)"

# Помощники фикстуры обязаны быть объявлены ДО своих вызовов: bash не поднимает объявления
# функций, а необъявленная функция под `set -uo pipefail` (без `-e`) печатает ошибку в stderr
# и НЕ увеличивает ни pass, ни fail — кейс исчезает из набора молча. Проверка сплошная.
undefined_helpers=$(awk '
  /^[A-Za-z_][A-Za-z0-9_]*\(\)[[:space:]]*\{/ { name = $0; sub(/\(\).*/, "", name); defined[name] = NR; next }
  /^[[:space:]]*assert_[A-Za-z0-9_]+[[:space:]]/ {
    call = $0; sub(/^[[:space:]]+/, "", call); sub(/[[:space:]].*/, "", call)
    if (!(call in defined)) print NR ": " call
  }
' "$0")
if [ -z "$undefined_helpers" ]; then
  ok "каждый вызов assert-помощника стоит ниже его объявления — ни один кейс не выпадает молча"
else
  not_ok "вызов assert-помощника до объявления (кейс молча не исполняется): $(printf '%s' "$undefined_helpers" | head -3 | tr '\n' ' ')"
fi

printf '\n1..%d\n' "$((pass + fail))"
if [ "$fail" != "0" ]; then
  printf 'ИТОГО finalize-triage-parse.test.sh: PASS=%d FAIL=%d\n' "$pass" "$fail" >&2
  exit 1
fi
printf 'ИТОГО finalize-triage-parse.test.sh: PASS=%d FAIL=0\n' "$pass"
