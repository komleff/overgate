---
title: "og-159 — гейт /finalize-pr исполняется скриптом целиком"
status: draft
version: "0.1"
date: 2026-10-24
tags: [overgate, finalize-pr, pipeline-governance, release-candidate]
beads: og-159
related:
  - docs/plans/2026-10-24-v4.0.0-rc.4.md
  - .claude/skills/finalize-pr/SKILL.md
---

# og-159 — гейт `/finalize-pr` исполняется скриптом целиком

**Решение оператора 2026-10-24:** гейт `/finalize-pr` должен исполняться скриптом целиком. og-159
делается первым, до реализации WI-1 rc.4 (PR #12): WI-1 меняет triage parser и финализируется
доверенной версией гейта (план rc.4 §0, AC-16).

**Режим:** CRITICAL — меняется hard gate перед merge (pipeline governance, PM_ROLE §10).
Budget 6: Plan Review, QA, Code Review, affected QA, scoped re-review, резерв.

**База:** `main` `b830d5ed7ed31e597b45f7f3c18b8fb6baad6b29` (тег `v4.0.0-rc.3`),
`.claude/skills/finalize-pr/SKILL.md` blob `b7e7ed132df17643ebf5b2d52af0b284ba3ce93e`.

## 1. Target → as-built → gap

**Target.** В сессии проекта, установленного OverGate, PM запускает гейт одной командой. Все
автоматические проверки skill (preflight, шаги 1–6 с разбором triage, повторная проверка HEAD) и
публикация readiness идут в одном процессе, под действующими guard'ами, без обхода и без ручного
исполнения по шагам.

**As-built.** `SKILL.md` — 2214 строк, 11 bash-блоков. Агент переносит блоки в отдельные
Bash-вызовы. Между вызовами переменные и функции не сохраняются (`HEAD_COMMIT`, `run_with_timeout`,
`SEP`), а guard'ы блокируют сами блоки. В PR #10 и #11 гейт выполнен вручную, awk-разбор triage
не исполнялся (паспорта FINAL, 2026-10-23).

**Воспроизведение 2026-10-24** (сессия OverGate, хуки rc.3). Текст каждого блока подан диспетчеру
`.claude/hooks/pre-bash.sh` как payload PreToolUse; команда не исполнялась:

| Блок SKILL.md (строки) | Что делает | Исход | Guard |
|---|---|---|---|
| 57–92 | preflight помощника времени | 2 | публикация в PR: «вне прямолинейной shell-последовательности» |
| 187–207 | шаг 1, HEAD PR | 2 | защита репозитория: «ambiguous executable context» |
| 215–231 | шаг 2, локальный HEAD | 2 | гейт коммита: «может скрывать git commit» |
| 243–471 | шаг 3, review evidence | 2 | защита репозитория |
| 512–1787 | шаг 6, triage | 2 | защита репозитория |
| 1946–1965 | re-check HEAD | 2 | защита репозитория |
| 1900, 1988, 2041 | сбор полей, шаблоны публикации | 2 | защита репозитория |
| все исполняемые блоки одной командой | — | 2 | защита репозитория |
| `bash <файл> 12` | запуск файла-скрипта | 0 | — |
| `.claude/tools/run-python.sh <файл.py> 12` | запуск python-файла | 0 | — |

Проверка осуществимости: проверочные блоки 57, 187, 215, 243, 512, 1946 из `main` склеены в один
файл и запущены одним `bash` на смерженном PR #11 из detached worktree на его HEAD `068b6d6`.
Прошли все проверки, включая awk-разбор triage, код выхода 0, без публикации.

**Gap.** Нет исполняемого артефакта гейта: логика живёт только в markdown, и путь её исполнения
в сессии закрыт guard'ами. Причина не в guard'ах: они правильно не доказывают безопасность
многострочных команд с `$(…)`, функциями и вызовами неизвестных исполняемых.

## 2. Решения HOW

### 2.1 Скрипт гейта

Новый файл `.claude/skills/finalize-pr/finalize-gate.sh` (исполняемый, managed). Интерфейс:

```text
bash .claude/skills/finalize-pr/finalize-gate.sh <PR_NUMBER> --check
bash .claude/skills/finalize-pr/finalize-gate.sh <PR_NUMBER> --publish <BODY_FILE>
```

- Проверочные блоки SKILL.md переносятся **дословно**, в прежнем порядке, на верхнем уровне
  файла (без функций и отступов): preflight (57), шаг 1 (187), шаг 2 (215), шаг 3 (243), шаг 6
  (512), re-check HEAD (1946). Комментарии переносятся вместе с кодом.
- Отличия от дословного текста — только «клей», каждое отличие перечисляется в PR:
  - `<PR_NUMBER>` → `${PR_NUMBER}`;
  - разбор аргументов до первого внешнего вызова: номер PR — только цифры, ровно один режим,
    `--publish` требует путь; иначе код 2 и usage без сетевых вызовов;
  - помощники гейта (`with-timeout.sh`, `run-python.sh`, `publish-pr-comment.py`, validators)
    берутся из дерева, в котором лежит сам скрипт (`GATE_TREE` — три уровня вверх от каталога
    скрипта); локальный HEAD и content fingerprint — из checkout текущего каталога
    (`git rev-parse --show-toplevel`). Это даёт запуск доверенной версии гейта из отдельной
    worktree доверенного SHA, стоя в checkout PR HEAD (план rc.4 AC-16);
  - итоговая сводка `--check`: `GATE_RESULT=PASS`, `GATE_TREE`, `HEAD_COMMIT`, `BASE_SHA`,
    `EVIDENCE_SHA`, `UNRESOLVED=0`; код 0.
- `--publish`:
  1. те же проверки целиком;
  2. тело читается из `BODY_FILE` **один раз** в переменную; дальше проверяются и публикуются
     только эти байты;
  3. тело обязано начинаться строкой `## ✅ Готов к merge`, содержать строку
     `Commit: <HEAD_COMMIT>` и строку `Unresolved findings: 0`; иначе стоп без публикации;
  4. re-check HEAD (блок 1946) непосредственно перед публикацией;
  5. `FINALIZE_PR_TOKEN=1 "$PYTHON_LAUNCHER" "$PUBLISHER" "$PR_NUMBER" - <<< "$BODY"` — token
     получает только процесс publisher; код возврата проверяется.
- `--check` publisher не вызывает ни при каком исходе.

### 2.2 SKILL.md

- Исполняемые проверочные блоки и шаблоны публикации фаз 1 и 2 удаляются. Вместо них — раздел
  «Исполнение»: две формы вызова, правило «гейт исполняется только этим скриптом, одним вызовом»;
  отказ скрипта или guard'а → стоп и эскалация оператору; ручное исполнение по шагам не
  принимается.
- Описательная часть шагов 1–8 остаётся: что проверяется и почему. Ручные проверки PM (смысл
  `reject with rationale`, `APPROVED` по аспекту `fix now`, шаги 7–8, паспорт) остаются ручными.
- Шаблон тела для `BODY_FILE` — markdown без исполняемого кода; файл кладётся в ignored
  `.overgate-runtime/`.
- `--force`, re-check HEAD как отдельный блок и сбор полей шаблона — см. §3 OUT.

### 2.3 Фикстуры

- `scripts/tests/finalize-triage-parse.test.sh`: источник извлечения `SKILL.md` → скрипт. Маркеры
  `triage-fetch:start/end`, якоря `SEP=$(printf` и хвост `TRIAGE_FAILED` сохраняются; число и
  состав кейсов не меняются. Проверки single-finalize владельцев и `ACCEPTED_RISK` остаются на
  `SKILL.md`.
- Новая `scripts/tests/finalize-gate-script.test.sh` (подключается в `scripts/verify-reference.sh`):
  - диспетчер `.claude/hooks/pre-bash.sh` пропускает обе формы вызова — регрессия og-159;
  - `SKILL.md` не содержит исполняемых проверочных блоков (`run_with_timeout`, `gh pr view`
    внутри bash-ограждений), кроме разделов из §3 OUT;
  - end-to-end на подставных `gh`/`bd` в `PATH`, во временном git-репозитории: исходы §5 AC-04…AC-07.

### 2.4 Поставка

- `.agents/distribution-manifest.json`: новый managed-файл; бит исполнения сохраняется при
  установке. Для прежнего blob `SKILL.md` — существующий механизм `legacy_blobs`, как в rc.3.
- `CHANGELOG.md`: запись в секцию следующего rc.
- Memory Bank — по завершении, landing в той же ветке.

### 2.5 Bootstrap финализации og-159 (PM_ROLE §10)

PR og-159 меняет сам гейт и не сертифицирует себя новой версией. Финализация — доверенным текстом
`main@b830d5e` (SKILL.md blob `b7e7ed1`), исполненным скриптом целиком:
- проверочные блоки 57, 187, 215, 243, 512, 1946 детерминированно извлекаются в один файл
  (извлекатель и файл — в `.overgate-runtime/`, их sha256 — в FINAL);
- к файлу дописывается публикация из шаблона фазы 2 доверенного SKILL.md с телом из файла;
- файл запускается одним `bash` из checkout PR HEAD; `with-timeout.sh`, `run-python.sh` и
  `publish-pr-comment.py` в PR не меняются — равенство blob с `b830d5e` фиксируется в FINAL;
- не исполнился — стоп и эскалация оператору.

Осуществимость проверена на PR #11 (§1).

## 3. Scope

**IN:** `.claude/skills/finalize-pr/finalize-gate.sh`, `.claude/skills/finalize-pr/SKILL.md`,
`scripts/tests/finalize-triage-parse.test.sh`, `scripts/tests/finalize-gate-script.test.sh`,
`scripts/verify-reference.sh`, `.agents/distribution-manifest.json`, `CHANGELOG.md`, Memory Bank.

**OUT:**
- логика проверок: условия стопа, разбор triage, content equivalence — переносятся без изменения
  смысла; правила `defer` меняет WI-1 (AC-11) уже в скрипте;
- `--force` — остаётся ручным маршрутом по команде оператора, его блок не переносится;
  заявленный предел, задача в Beads;
- автоматизация шагов 7–8, паспорта и accepted risk;
- guard'ы и диспетчер хуков; guard'ы не проверяют содержимое файлов-скриптов — существующее
  свойство, не меняется;
- дефект: шаг 3 при повторном запуске на том же HEAD принимает опубликованный FINAL-комментарий
  за review evidence (в нём есть `CODE REVIEW` и `Commit: <HEAD>`) — задача в Beads;
- шаг 2 называется «Проверка `/verify`», но проверяет только совпадение HEAD; `/verify` PM
  запускает отдельно — без изменений.

## 4. Шаги

1. План → Draft PR → Plan Review 1/6 → `PLAN_READY`.
2. RED: новая фикстура на `main` падает (скрипта нет, SKILL.md содержит исполняемые блоки).
3. Скрипт: дословный перенос + клей §2.1.
4. SKILL.md §2.2; перенацеливание `finalize-triage-parse` §2.3.
5. GREEN: новая фикстура и все прежние; `bash scripts/verify-reference.sh`; CI macOS +
   windows-native.
6. Manifest, проверка fresh install во временный проект, CHANGELOG.
7. Живой запуск `--check` в этой сессии на PR og-159 и на смерженном PR #11 (AC-10).
8. QA 2/6, Code Review 3/6, triage; blocker fix → affected QA и scoped re-review.
9. Landing Memory Bank; bootstrap-финализация §2.5; merge — оператор.

## 5. Verification Contract

| AC | Ожидаемое поведение | Метод |
|---|---|---|
| AC-01 | `SKILL.md` объявляет ровно две формы вызова скрипта и не содержит исполняемых проверочных блоков вне §3 OUT | фикстура |
| AC-02 | Диспетчер `.claude/hooks/pre-bash.sh` проекта пропускает обе формы вызова (код 0) | фикстура; RED-таблица §1 в PR |
| AC-03 | Проверочный код скрипта совпадает с блоками SKILL.md@`b830d5e` за вычетом перечисленного клея §2.1 | diff в PR (разовый) + Code Review |
| AC-04 | `--check`: все проверки прошли → код 0 и сводка `GATE_RESULT=PASS`; отказ `gh` (диагноз называет инструмент), локальный HEAD ≠ PR HEAD, нет CODE REVIEW evidence, строка triage без статуса → код 1 с прежним сообщением; publisher не вызывается ни в одном исходе | фикстура (подставные `gh`/`bd`) |
| AC-05 | `--publish`: публикация только после всех проверок; тело без заголовка, с чужим `Commit:` или `Unresolved findings` ≠ 0 → стоп без публикации; HEAD сменился до re-check → стоп без публикации; отказ publisher → код 1; успех → `gh` получил ровно байты тела, token виден только publisher | фикстура |
| AC-06 | Аргументы: номер не из цифр, нет режима, оба режима, неизвестный флаг, `--publish` без пути → код 2 и usage до любого внешнего вызова | фикстура |
| AC-07 | Скрипт, запущенный по абсолютному пути из другого дерева, берёт помощников из своего дерева, а HEAD — из checkout текущего каталога; нет помощника в своём дереве → стоп, даже если он есть в текущем checkout | фикстура |
| AC-08 | `finalize-triage-parse` извлекает логику из скрипта, число кейсов прежнее, всё зелёное; validators зелёные; `verify-reference` и CI (macOS, windows-native) зелёные | `/verify`, CI |
| AC-09 | Fresh install во временный проект кладёт исполняемый скрипт; upgrade с rc.3 обновляет SKILL.md; проверка reference проходит | установщик во временный проект |
| AC-10 | В сессии OverGate `--check` проходит guard'ы и выполняется до конца на PR og-159 (final candidate) и на PR #11 | журнал в PR |
| AC-11 | og-159 финализирован bootstrap'ом §2.5; FINAL указывает `b830d5e`, blob `b7e7ed1`, sha256 файла bootstrap, PR HEAD и равенство blob помощников | evidence в PR |

**Инварианты:** перенос не ослабляет ни одной проверки; отказ инструмента — стоп, а не «проверять
нечего»; readiness публикует только процесс publisher после всех проверок и re-check HEAD;
`--check` ничего не публикует; merge — оператор.

**Риски:**
- R1 — смысловое расхождение при переносе → AC-03, неизменный набор `finalize-triage-parse`.
- R2 — guard'ы не видят содержимое скрипта; скрипт, изменённый в PR, мог бы выдать ложную
  готовность → финализация доверенной версией (§2.5; план rc.4 AC-16), merge — оператор.
- R3 — Windows: `bash` из Git Bash, бит исполнения → CI windows-native, AC-09; живая проверка —
  в чек-листе rc.4 §5.4.
- R4 — пересечение с WI-1: после merge og-159 triage parser живёт в скрипте. Scope WI-1 задан
  каталогом `.claude/skills/finalize-pr/`, AC-16 уже допускает «SHA merge og-159»; план WI-1 v0.6
  не меняется, ветка WI-1 перебазируется на `main` после merge og-159.

## 6. Rollback

Revert PR: SKILL.md возвращается к блокам, скрипт и фикстура удаляются. Установленные проекты
откатываются upgrade на предыдущий rc. Данных и миграций нет.
