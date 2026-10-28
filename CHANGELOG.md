# Changelog

Все значимые изменения OverGate документируются в этом файле.
Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/); версия = версия спецификации пайплайна с SemVer-суффиксом.

## [Unreleased] — v4.0.0-rc.4 candidate, WI-1

До выпуска требуется отдельный WI-2 og-7sr; stable/Latest не меняется.

### Added
- QUICKSTART для неспециалиста; helpers Memory Bank (шесть файлов), bd1.2.2 bootstrap и
  усиление/readback GitHub main protection с явными исходами2/3/4/5/6.
- --mode auto/bypass и --no-beads; component payload/closure, tracker defer открытого issue
  только в no-beads. Explicit Claude CLI startup документирует effective mode boundary.

### Changed
- Settings source auto без U2 deny; known rc.1–rc.3 canonical fingerprints обновляют точные
  установки, custom permissions/mode сохраняются. Codex пустой deny артефакт снимается.
- Install-state format2 без абсолютных путей, legacy upgrade и all-or-nothing rollback сохранены.
- ADR3.33 фиксирует установку, authorisation protection и trusted upstream финализацию WI-1.


### Fixed
- Bootstrap og-159 генерируется независимо от тела: actual scriptSHA можно включить в FINAL,
  а проверенный bodySHA передаётся runtime из отдельного attestation без самоссылочного цикла.
- **RV-F1 (og-159):** collation вызывающей среды больше не смешивает русские имена колонок
  triage: byte locale назначается только parser awk; окружение остальных инструментов сохраняется.
- **og-159:** автоматические проверки `/finalize-pr` и публикация выполняются единым
  managed `finalize-gate.sh` для Claude Code и Codex. `--check` не публикует; `--publish`
  использует private snapshot тела и сохраняет его точные bytes. Trusted code берётся из
  дерева скрипта, данные — из текущего checkout; отказ инструмента останавливает гейт.
- Добавлен детерминированный bootstrap-извлекатель из frozen rc.3 для финализации самого
  og-159. Ручные проверки PM и operator-only merge сохранены; guards не меняются.

## [v4.0.0-rc.3] — побайтное соответствие установленного проекта, 2026-10-24

Prerelease; stable `v3.9.0` остаётся Latest. Контракт — `docs/plans/2026-10-24-v4.0.0-rc.3.md`.
Изменён только установщик `scripts/install-overgate.py`; payload guards, dispatcher, bd-обёртки
и skills не менялись.

### Fixed
- **`.codex/hooks.json` больше не получает `"permissions": {"deny": []}`.** Merge settings создаёт
  `permissions` и его поля только если они есть в source; project-owned ключи сохраняются.
- **Upgrade с rc.1/rc.2 без overrides побайтно (байты и mode) равен source** во всех managed- и
  settings-файлах: settings больше не пересортировываются (`sort_keys`), если merge ничего не меняет.
- **`.gitignore` больше не переводится в LF и не получает второй фрагмент.** Блок фрагмента
  ищется построчно без учёта EOL; найденный целый блок оставляет файл побайтно неизменным.
- Повторный `plan` сразу после `apply` — все operations с `before == after`, без conflicts.

### Changed
- Правило записи settings: результат merge по смыслу (строго по типам: `true` ≠ `1`) равен
  source → байты source; иначе равен файлу проекта → файл не меняется; иначе JSON в порядке
  ключей проекта, новые ключи в конце, `indent=2`, без `sort_keys`, UTF-8 без `\u`, финальный LF.
- `.gitignore` fresh (нет файла или 0 байт) = ровно байты фрагмента; в rc.2 было `\n\n` + фрагмент.
- Фрагмента нет → байты проекта сохраняются, недостающий перевод строки в конце добавляется,
  затем пустая строка и фрагмент в EOL файла (CRLF, если все строки CRLF, иначе LF).
- Несколько целых блоков фрагмента сводятся к первому; прочие байты не меняются.
- **Новый conflict upgrade:** заголовок `# OverGate personal state (managed fragment)` вне целого
  блока → `conflict: managed .gitignore fragment modified; resolve in target PR`, без записи.
  В rc.2 к такому файлу дописывался второй фрагмент. Разрешение — в target PR, затем новый план.
- Legacy-строка `.codex/` (v3.9) удаляется ровно с её EOL; прочие байты сохраняются.
- Формат плана, журнала rollback и `install-state.json`, порядок operations и conflict-политика
  для managed-файлов не изменены.

### Limits and migration
- Побайтное соответствие после upgrade заявлено только для точных установок rc.1 и rc.2: merge
  переносит из source только hooks и `deny`. Для upgrade v3.9 → rc.3 оно не заявляется.
- Проект с project overrides settings получает только необходимые изменения: без пересортировки,
  а без добавленных данных — без записи.
- Windows не хранит POSIX execute bit: fixtures сверяют mode только на POSIX, байты — везде.

## [v4.0.0-rc.2] — перенос исправлений пайплайна после rc.1, 2026-10-23

Prerelease; stable `v3.9.0` остаётся Latest. Источники: U2 `4a7354ea766854cca3fa1cbb2d15f1044522ff55`
(#862, #859) и установленный rc.1-проект U2 Lab `5586b43356841b8e0b0156dc129bf31e5a436224` (#30),
в обезличенном виде; file-level provenance — `docs/baselines/2026-10-01-delivery-first-provenance.json`.

### Changed
- **`scripts/bd-wt.sh` фильтрует подкоманды в любом окружении, включая основной checkout.**
  Проходит только allowlist `ready show list search blocked children create q update close reopen
  dep comment comments note label`; прочие подкоманды, пустая подкоманда и неизвестный глобальный
  флаг → код 2 до запуска bd. Раньше в основном checkout обёртка была полным pass-through.
- **`--global` больше не разрешённый глобальный флаг обёртки** — отказ кодом 2 в любой позиции.
  Также отклоняются `-C`/`--directory`, `--ignore-schema-skew`, `--repo`, флаги чтения локального
  файла (`--body-file` и скрытый в `--help` алиас `--description-file` у `create`/`update`,
  `--design-file`, `--reason-file`, `--file`, `--graph`, `-f`, `--metadata @файл`) и непустые
  `BEADS_DIR`/`BEADS_DB`; `--db` по-прежнему запрещён. Длинный текст — `--stdin`/`--description`.
- Предписания запуска `scripts/bd-*.sh` в docs, rules, сообщениях скриптов и finalize — `bash scripts/...`:
  прямой запуск файла без аргументов гейт коммита блокирует (задокументированное поведение гейта).
- Тексты recovery-ограничений нейтральны к версии: `DECLARED_LIMIT` rc.1 и отложенный `og-7sr`
  действуют и в rc.2.

### Added
- `bd_env_resolve_main_db` в `scripts/lib/bd-env.sh`: основная база по `dolt_mode` из
  `.beads/metadata.json` — `embedded` → `.beads/embeddeddolt` без сервера, `server` → `.beads/dolt`
  и живой dolt-сервер; отсутствующий/неизвестный режим, нечитаемый metadata, нет каталога базы или
  исправного Python — fail-closed с путём и причиной. Python — через `.claude/tools/run-python.sh`.
  Прежние функции `bd-env.sh` сохранены.
- Лексический страж bash 3.2 `scripts/tests/shell-nonascii-expansion.test.py`: `$имя` вплотную к
  не-ASCII в shell-поверхности и `command` хуков; опоры перечисления против пустого зелёного прогона.
- Тесты обёртки на заглушке bd: embedded/server, fail-closed metadata, allowlist и запрещённые
  флаги в обеих формах вызова, вызов launcher проекта. Шаг Git Bash в `windows-native` CI.
- Upgrade-фикстура из точной установки `v4.0.0-rc.1`: чистый upgrade, адресный conflict по каждому
  изменённому проектом `bd-wt.sh`/`bd-env.sh`, побайтный rollback.

### Documentation
- Порядок доступа к Beads по окружениям из U2 ADR-0042: основной checkout, локальная
  worktree через `bd-wt.sh`, облако через снимок и pending-заявки `.bd-intents/` (PR #8).
- Чтение exact-SHA снимка и публикация PR через авторизованный GitHub-коннектор без
  обязательного login Git CLI; конечное ожидание и сверка результата после timeout записи.
- Исправлен blanket-запрет worktree-мутаций: обёртка пишет в основную базу.
- Указана фактическая граница поставки: applier не включён; подключение trusted tooling,
  lifecycle очереди, частичные сбои и обновление preserved project rules описаны явно.
- Класс локального окружения (обёртка, allowlist, embedded/server, ограничение блокировки
  embedded Dolt) — `.claude/rules/beads.md`, `HOW_TO_USE.md`, `INSTALL.md`, `PIPELINE_ADR` §3.7.

### Limits and migration
- Preserve-файлы `AGENTS.md` и `.claude/rules/beads.md` upgrade не обновляет: правила `bash scripts/...`
  и класса локального окружения перенести в них вручную по diff reference-файлов между тегами.
- Проект с изменёнными managed `scripts/bd-wt.sh`/`scripts/lib/bd-env.sh` получает conflict по
  каждому файлу; override разрешается в target PR, тихой перезаписи нет.
- Allow-правила settings для обёрток не поставляются: managed `allow` уже содержит `Bash(*)`, а
  allowlist обёртки — защитный слой, не граница безопасности. Applier/engine Beads не поставляется.
- Штатной команды bd 1.2.x для восстановления `dolt_mode` не найдено: при отказе — к оператору.

## [v4.0.0-rc.1] — candidate refresh, 2026-10-03

### Changed
- Delivery First: FAST/PRODUCT/CRITICAL, budget 2/5/6, Plan Review до реализации, независимая QA,
  один scoped Code Review, affected rechecks и одна финализация после landing.
- Mandatory four-aspect/second/external/Copilot/dual-finalize routes superseded в active instructions;
  historical ADR сохранены. Product authority задаётся проектом, fallback — оператор.
- Reference `/verify` исполняет реальный единый suite; project verification template отделён.

### Added
- Шесть delivery owners и пять generic skills с conditional triggers, без обязательной designer-роли.
- Claude dispatcher с mutation, commit и readiness guards; Codex adapter сохраняет единственный
  source U2 repository guard, без commit/readiness hook entries. Source parser/policy/timeout/publisher closure.
- Explicit inventory, frozen-source plan/apply, preserved overrides, pre-write backup и byte-restoring rollback.
- Read-only `verify-reference` CI job, structural negatives, static positive/non-trigger scenarios,
  behavioural runtime tests и fresh/v3.9 upgrade/rollback fixtures.
- File-level provenance из frozen U2 `c450fa7b0d90fecf970f9931011255ea836da258`.

- Portable Claude Bash dispatcher из U2 #829: одна managed запись, root по расположению файла,
  последовательные guards, сужение реального project test budget; macOS Bash 3.2 interpolation fix.
- Нативный read-only Windows CI для dispatcher и installed fresh/previous-RC/v3.9/rollback.

### Limits and migration
- [INSTALL.md](.agents/INSTALL.md) — единственный RC installation/upgrade/rollback путь.
- Stable Dreadnought и прежние beta/v3.9 refs не меняются; RC release остаётся prerelease/not Latest.
- Claude сессия для полного dispatcher запускается из checkout root; subdirectory/package
  монорепо работает в recovery режиме. Только одна unquoted absolute `cd`, путь из
  латиницы/цифр/`_ : / . -`. Пробелы/кириллица/скобки/кавычки требуют новой сессии в root;
  расширение recovery и косметические внутренние U2 prefixes отложены в `og-7sr`.
- Вне любого Git-репозитория Claude Bash hook блокирует кодом 2, но выводит заглушку
  `cd <корень репозитория>`. Это принятый оператором `DECLARED_LIMIT` rc.1 для совместимости
  с U2; ожидаемый путь — новая сессия из root. Literal hint вне Git отложен в `og-7sr`.
  Для собственного subdirectory напечатанная literal absolute recovery остаётся обязательной.
- Source installer требует чистый Git checkout с exact SHA; release ZIP без `.git` не подходит.
- Windows/live runtime activation не подтверждаются static fixtures; окончательное platform evidence — в PR.
- Local hooks не защищают remote writes; ручные accepted-risk checks и shared-account trust limit сохранены.
- U2 Almanac/domain content исключён. Полная лицензия на U2 этим переносом не заявляется.

## [v3.9.0-beta.1] — 2026-06-16

**Первый публичный beta-релиз.** OverGate — переносимый AI-пайплайн разработки для solo-оператора, управляющего флотом ИИ-агентов (PM-оркестрация, разделение ролей, hard-гейты перед merge, кросс-модельное adversarial-ревью). Релиз рассчитан на ранних адаптеров, которые устанавливают пайплайн в свои проекты через [`.agents/INSTALL.md`](.agents/INSTALL.md) и присылают фидбек.

### Added
- `LICENSE` — MIT.
- `CHANGELOG.md` (этот файл).
- Таблица пререквизитов (Python, `gh`, Node.js, `bd`, инструменты внешнего ревью) в `README.md` и `.agents/INSTALL.md §A`.
- Fail-closed гейт на незаполненные `<PLACEHOLDER>` в **исполняемых блоках** `/verify` + **advisory** (не блокирующее предупреждение) для `.claude/rules/tests.md` (baseline-числа) при установке (`.agents/INSTALL.md`).
- Helper-скрипты синхронизации Beads: `scripts/bd-sync-export.sh`, `bd-sync-restore.sh`, `bd-sync-common.sh` (PR #3).

### Changed
- **Де-догфудинг** generic-артефактов: убраны операционные U2-утечки — hardcoded Windows-пути dogfood-репо → `<REPO_ROOT>`, хост публичного сайта → `<SITE_HOST>`, npm-скоп tooling → `@overgate/openai-review`. Provenance-упоминания U2 (родословная, reference baseline) сохранены намеренно.
- Правила Beads и `AGENTS.md` приведены к **bd 1.0.2**: синхронизация через служебную ветку `beads-backup` (`bd export`/`bd import`), Dolt-remote и `bd dolt push/pull` отключены (PR #1, #3).
- Cost-warning для Mode A-legacy внешнего ревью (Platform API дорогой; предпочтителен Codex CLI + ChatGPT subscription).
- Канон heredoc-делимитеров для безопасной публикации больших payload'ов в PR (PR #2).

### Fixed
- `/verify` Шаг 1: `npm ci` запускается из корня репозитория в npm-workspace структуре (раньше из leaf-папки не доустанавливались `vite`/`vitest`) — баг `og-xxj` (PR #4).

### Removed
- Tracked Python-байткод `.claude/skills/sync-site-gdd/scripts/__pycache__/find-missing.cpython-314.pyc`.

### Known limitations (beta)
- `og-mk4` (P3) — hardening helper-скриптов bd-sync (целостность JSONL первого export, drop-guard на гибридном tip, детерминизм порядка ключей). Не дефект контракта синхронизации.
- Узкое окно совместимости трекера: helper-скрипты завязаны на command surface **bd 1.0.2**.
- EXAMPLE-артефакты (`/verify`, `.claude/rules/tests.md`, `/sync-docs`, `/sync-site-gdd`) поставляются с `<PLACEHOLDER>` — требуют адаптации под стек проекта (см. `.agents/INSTALL.md §B.4`).

[v3.9.0-beta.1]: https://github.com/komleff/overgate/releases/tag/v3.9.0-beta.1
