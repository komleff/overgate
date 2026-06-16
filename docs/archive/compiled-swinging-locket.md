# План: первый публичный beta-релиз OverGate (v3.9.0-beta.1)

## Context

`overgate` — переносимый AI-пайплайн разработки (мета-продукт: роли, скиллы, хуки, правила, ADR-процесс), отчуждённый из dogfood-проекта U2 как канонический reference-шаблон. Задача оператора: подготовить **первый публичный beta-релиз для публичного тестирования**. «Тестирование» здесь = сторонние solo-операторы устанавливают пайплайн в свои проекты через `.agents/INSTALL.md`.

**Проверенное состояние репозитория (на момент плана):**

- Репозиторий **уже PUBLIC**, Issues включены, но **`licenseInfo: null`** → по умолчанию «все права защищены», что юридически противоречит цели «копируй в свой проект». «Релиз» = не «сделать публичным», а **оформить корректный tagged/announced beta**.
- Вся функциональная работа **смержена в `origin/main`**: PR #1 (beads-правила + AGENTS.md), #2 (heredoc-канон), #3 (синхронизация bd 1.0.2, 7 итераций внешнего ревью). Открытых PR нет. Локальный HEAD на 1 коммит позади main (только merge-commit).
- Тег `v3.9` существует, **GitHub Release не создан**.
- Беклог Beads чист: 1 открытая задача `og-mk4` (P3, hardening bd-sync, **не блокер**).
- Memory-bank — заглушки-шаблоны (by design, заполняются при установке).

**Что мешает релизу (выявлено разведкой, проверено `git grep` по tracked):**

1. **Нет LICENSE** (release-блокер при публичном репо).
2. **Операционные U2-утечки в tracked-файлах** (адаптер скопирует сломанный/чужой reference).
3. **Гигиена:** закоммичен `.pyc`; 504K untracked-мусора не покрыты `.gitignore`; завершённый план PR #3 не заархивирован; `.agents/skills/` — расходящийся stale-дубль `.claude/skills/`.
4. **Нет CHANGELOG / GitHub Release.**
5. **Onboarding-риски портируемости:** `<PLACEHOLDER>` в `/verify` не защищены fail-closed гейтом (в отличие от `AGENTS.md`); пререквизиты (Python/gh/Node/bd-версия) не задокументированы как требования.

**Решения оператора (зафиксированы):**

- Лицензия — **MIT**.
- Идентификатор релиза — **`v3.9.0-beta.1`** (сохраняет сквозную версию спеки пайплайна v3.9, добавляет beta-маркер; без dual-numbering).
- Объём — **Lean + onboarding-hardening** (блокеры + закрытие «ломается при первой установке»).

### Preconditions (до начала реализации — внешнее Critical-ревью, iter-1)

- **[BLOCKER] Релиз заблокирован на `og-xxj`.** P1-баг «`/verify` Шаг 1: `npm ci` из leaf-папки не работает в npm-workspace структуре» исправляется отдельным агентом — фикс правит **generic-логику shipped-шаблона** `verify/SKILL.md` (Шаг 1), а НЕ overgate-специфику. **Причина блокировки: beta обязана нести исправленный shipped-шаблон.** Последовательность: **сперва merge `og-xxj` → затем release-PR создаётся/ребейзится поверх обновлённого `main`** (который уже несёт фикс). **Release-PR сам `verify/SKILL.md` НЕ редактирует** (Execution шаг 3, §2.1) — он наследует фикс через `main`. (Мнимого конфликта «оба PR трогают `verify/SKILL.md`» нет: release-PR его не трогает.)
- ✅ **[RESOLVED] Правообладатель MIT** — оператор подтвердил **`Dmitriy Komlev`**. Строка: `Copyright (c) 2026 Dmitriy Komlev` (Workstream 1.1).
- ✅ **[RESOLVED] `Edit(.gitignore)` авторизован** оператором — правка идёт **в release-PR** (§3.2), добавляемые строки: `.review-responses/`, `__pycache__/`, `*.pyc`.

### Что НЕ трогаем (легитимная provenance — оставить как есть)

Эти U2-упоминания корректны и описывают происхождение/reference baseline:
- `AGENTS.md:16,60` (объяснение, что U2 = dogfood-инстанс), `README.md:5` (provenance-строка), `.agents/INSTALL.md:22` (reference baseline PR #185), `.agents/REFERENCES.md:117` (родословная).
- `.review-responses/**` — исторические артефакты ревью (untracked; не редактировать содержимое).

---

## Workstream 1 — Release-блокеры

### 1.1 LICENSE (MIT)
- Создать `LICENSE` в корне: стандартный текст MIT, `Copyright (c) 2026 Dmitriy Komlev` (правообладатель подтверждён оператором — см. Preconditions).
- В `README.md` добавить секцию `## License` со ссылкой на `LICENSE` (MIT). Можно бейдж.

### 1.2 npm-скоп `@u2` → нейтральный
- `.claude/tools/package.json:2` и `.claude/tools/package-lock.json:2,8`: `"name": "@u2/openai-review"` → `"@overgate/openai-review"` (или unscoped `overgate-openai-review`). Все три вхождения синхронно. Пакет не публикуется в npm — имя косметическое, но не должно нести чужой скоп.

### 1.3 Де-догфудинг операционных утечек

**`D:\GitHub\u2` (hardcoded Windows-пути в инструкциях скиллов)** → заменить на плейсхолдер `<REPO_ROOT>` (для install-команд) и `<REPO_ROOT>-sync-...-<YYYY-MM-DD>` (для worktree-путей), консистентно с конвенцией плейсхолдеров проекта:
- `.claude/skills/README.md:10,20`
- `.claude/skills/architect/README.md:15,21`
- `.claude/skills/project-manager/README.md:15,21`
- `.claude/skills/sync-docs/SKILL.md:49,94,95,98,254,255,284`
- `.claude/skills/sync-site-gdd/SKILL.md:79,100,101,233,234`

**`docs.u2game.space` в generic-тексте** → плейсхолдер `<SITE_HOST>` (для EXAMPLE-скиллов это уже конвенция; роль Doc Sync — generic, конкретный хост в ней недопустим):
- `.agents/AGENT_ROLES.md:295,323` (generic-роль Doc Sync — **обязательно**).
- `.claude/skills/sync-docs/SKILL.md:265,294` (шаблоны сообщений → `<SITE_HOST>`).
- `.claude/skills/sync-site-gdd/SKILL.md:7` и `scripts/find-missing.py:6` (EXAMPLE-комментарий) → тоже `<SITE_HOST>`.
- **Заменить ВСЕ вхождения `u2game`** (включая комментарий `find-missing.py`), чтобы `git grep "u2game"` был **пустым** — критерий де-догфудинга однозначный (см. §Verification).

### 1.4 CHANGELOG.md
- Создать `CHANGELOG.md` (формат Keep a Changelog). Первая запись **`## [v3.9.0-beta.1] — 2026-06-16`** с разделами:
  - *First public beta* — что это за релиз, на кого рассчитан.
  - Сводка влитого: beads-правила и AGENTS.md (#1), heredoc-канон (#2), синхронизация bd 1.0.2 + helper-скрипты (#3).
  - Release-prep: MIT-лицензия, де-догфудинг, onboarding-hardening.
  - *Known limitations (beta)*: ссылка на `og-mk4` (P3 hardening), узкое окно совместимости bd 1.0.2.

### 1.5 GitHub Release (после merge — см. §Execution)
- Аннотированный тег `v3.9.0-beta.1` на смерженный main.
- `gh release create v3.9.0-beta.1 --prerelease --notes-file <CHANGELOG-фрагмент>`. Outward-facing publish → выполнять **после** merge и с авторизацией оператора.

---

## Workstream 2 — Onboarding-hardening (closing "ломается при первой установке")

### 2.1 Fail-closed гейт на незаполненные `<PLACEHOLDER>` в `/verify` и `tests.md`
- Зеркалить существующий гейт `AGENTS.md` (он грепает `<[A-Z][A-Z_]{2,}>` и падает fail-closed — см. `.agents/INSTALL.md` §B.6).
- Добавить в `.agents/INSTALL.md` (шаг приёмки §B/§D) проверку, что в `.claude/skills/verify/SKILL.md` и `.claude/rules/tests.md` не осталось стек-плейсхолдеров (`<CLIENT_BUILD_CMD>`, `<TEST_CMD>`, `<WARNING_BASELINE>` и т.п.) после адаптации. Без гейта `/verify` молча запускает литерал `<TEST_CMD>` → падает в первом же спринте.
- **Правка ТОЛЬКО в `.agents/INSTALL.md`** (флоу установки в target-проект). Сам шаблон `verify/SKILL.md` / `tests.md` **не редактируется** — overgate как reference поставляет их с `<PLACEHOLDER>` намеренно. Гейт **не запускается против самого overgate** (здесь плейсхолдеры — норма, overgate ≠ installed instance).

### 2.2 Документировать пререквизиты
- В `.agents/INSTALL.md` §A (оператор быстро читает) + краткая таблица в `README.md`: **Supported software / prerequisites**:
  - Python 3.x в PATH (`py`/`python3`/`python`) — нужен для hook `check-merge-ready.py` и EXAMPLE-скилла sync-site-gdd. Без него hook блокирует `gh pr comment`.
  - `gh` CLI установлен и authenticated.
  - Node.js ≥ 18.17.0 (для `openai-review.mjs`).
  - `bd` ≥ 1.0.2 (helper-скрипты завязаны на command surface 1.0.2; добавить проверку `bd --version` в §B.1 sanity-check).
  - Для внешнего ревью: Codex CLI + ChatGPT subscription (Mode A primary) **или** `$OPENAI_API_KEY` (Mode A-legacy, дорого); при отсутствии — graceful degradation Mode C/D (уже реализовано, явно отметить для новичка).
- В `.agents/INSTALL.md` §A явно упомянуть fallback `INSTALL_ALLOW_NPM_DRIFT=1` (сейчас спрятан в §B.3).

### 2.3 Cost-warning Mode A-legacy
- 1 строка в `.claude/skills/external-review/SKILL.md` (Шаг 2): «Mode A-legacy (Platform API) дорогой — месячный лимит сжигается за час; предпочитай ChatGPT subscription (Mode A primary)». Источник уже есть в `CODEX_AUTH.md`.

---

## Workstream 3 — Гигиена репозитория

### 3.1 Убрать tracked `.pyc`
- `git rm --cached .claude/skills/sync-site-gdd/scripts/__pycache__/find-missing.cpython-314.pyc` (Python-байткод, не должен трекаться).

### 3.2 `.gitignore` — **в release-PR через operator pre-authorization**
> ⚠️ `Edit(.gitignore)` заблокирован deny-правилом (`.claude/settings.json`). Чтобы защита **попала в tagged beta и прошла Critical review**, оператор **пред-авторизует Edit** (см. Preconditions), и правка идёт **в release-PR** — НЕ отдельным post-merge-коммитом (тот обошёл бы ревью). Не импровизировать обходом deny.
- Добавить в корневой `.gitignore`: `.review-responses/`, `__pycache__/`, `*.pyc`.
- **Если оператор не авторизует Edit** — `.gitignore` явно **выносится из scope/verification релиза** (не заявлять в beta защиту, которой в нём нет). Тогда `.review-responses/` остаётся untracked-мусором working-tree (не в дистрибутиве, т.к. untracked).

### 3.3 Архивация завершённого плана PR #3
- `docs/plans/peppy-whistling-puppy.md` (план уже реализованного и смерженного PR #3) → переместить в `docs/archive/` (per PM-роль: завершённый план архивируется). Этот файл (`compiled-swinging-locket.md`) — активный план релиза, остаётся в `docs/plans/`.

### 3.4 `.agents/skills/` — отложено в governance-follow-up (в релизе НЕ трогаем)
- `.agents/skills/` (untracked, 348K) — расходящееся зеркало/дубль канона `.claude/skills/` (Codex-harness, пути `.Codex/`). Канон, который грузит Claude Code и который tracked — `.claude/skills/`.
- **Согласовано с планом фикса `og-xxj`** (`pm-agents-agent-roles-md-temporal-glade.md` §Follow-up): судьба `.agents/skills/` — **отдельное governance-решение** (tracked 2nd harness-слой с описанием в README/INSTALL **либо** удалить как cruft), оформляется отдельной Beads-задачей, которую заводит og-xxj-агент. Verify-баг в зеркале закрывается там же. **Не часть release-PR и не часть багфикса.**
- **Для релиза действий не требуется:** `.agents/skills/` untracked → в tagged beta **не попадает** в любом случае. Релиз не блокируется и **не принимает решение за** governance-follow-up. (Прежнее «предложить удаление» снято — чтобы не преемптить отдельное решение.)

---

## Execution (последовательность)

> Пуш в main запрещён; всё через ветку + PR; merge — оператор. Тег/Release — после merge.

1. **Ветка** `chore/release-v3.9.0-beta.1` от свежего `origin/main`.
2. Реализовать Workstreams 1–3. Нюансы: §1.5 Release — post-merge; §3.2 `.gitignore` — **в этом PR** после pre-auth `Edit` оператором (Preconditions); §3.4 `.agents/skills/` — working-tree cleanup с согласия оператора (вне диффа). Комментарии в коде/доках — на русском.
3. **Verification релиз-PR — НЕ через адаптацию shipped `/verify`.** overgate — reference-шаблон: `verify/SKILL.md` и `tests.md` обязаны остаться с `<PLACEHOLDER>` (иначе теряется переносимость дистрибутива). **Запрещено** заполнять/менять плейсхолдеры shipped `/verify`/`tests.md` под overgate. Для этого PR — явный блок: `bash scripts/test-bd-sync.sh` + grep-гейты де-догфудинга (§Verification) + `bd ready --json` + `/pipeline-audit` (затронуты нормативные артефакты).
4. **PR** через `gh pr create`. **Tier: Critical** — затрагиваются нормативные артефакты пайплайна (`.claude/skills/*/SKILL.md`, `.agents/*.md`, `.claude/rules/tests.md`). Это `/sprint-pr-cycle` (4 аспекта, 2 прохода + Tester gate) + **Sprint Final → `/external-review`** (релиз в main).
5. Triage findings → fix-cycle до APPROVED обоих ревьюеров (commit-bound). PM — единственный владелец публикации.
6. **`/finalize-pr <N>`** — hard gate. Pre-merge landing inline (Memory-bank `activeContext`/`progress`, архивация плана, при необходимости Beads).
7. **Оператор мержит.**
8. **После merge (авторизация оператора):** аннотированный тег `v3.9.0-beta.1` на main → `gh release create v3.9.0-beta.1 --prerelease` с нотами из CHANGELOG. (`.gitignore` уже **внутри** PR — §3.2, прошёл ревью; `.agents/skills/` cleanup — working-tree, §3.4, вне диффа.)

> Опция: можно разнести на Light-PR (LICENSE/CHANGELOG/README/гигиена) + Critical-PR (скиллы/агенты/правила/INSTALL), чтобы Light влился быстро. Рекомендация — **один cohesive release-prep PR на Critical tier**: релиз — единый логический юнит, меньше ревью-оверхеда.

---

## Verification

- **Де-догфудинг (ключевой гейт — operational-артефакты; RECORDS исключены).** Все греп-гейты ниже выполняются с pathspec-исключением record-локаций: `-- . ':(exclude)docs/plans' ':(exclude)docs/archive' ':(exclude).review-responses'`. RECORDS (этот контракт §1.3-спека, планы, `.review-responses`) ЛЕГИТИМНО содержат литералы де-догфудинга для описания работы — это не операционные утечки; без исключения греп нашёл бы их в самом контракте (ложный self-fail, что и поймал ревьюер iter-4). Критерии (греп с указанным исключением):
  - `git grep -n -i "D:[/\\\\]GitHub[/\\\\]u2"` → **пусто** (то же для `~/GitHub/u2`, `/path/to/u2`, bare-folder `` `u2` `` в operational-доках, `u2-pr-` → переименован в `og-pr-`).
  - `git grep -n "u2game"` → **пусто** (все вхождения заменены, включая комментарий `find-missing.py`).
  - `git grep -n "@u2/"` → **пусто**.
  - `git grep -n "<SITE_HOST>"` → только **ожидаемые** места (без привязки к номерам строк — они дрейфуют при правках): роль Doc Sync `AGENT_ROLES.md`, EXAMPLE-скиллы `sync-docs`/`sync-site-gdd`, `find-missing.py`, adaptation-table `INSTALL.md`. **Критерий — adjacency:** в найденных местах рядом нет `u2game`/`docs.u2game.space`.
  - Provenance-строки (`AGENTS.md`, `README.md:5`, `INSTALL.md:22`, `REFERENCES.md`) **сохранены** (`git grep -n "komleff/u2"` → только они).
- **LICENSE:** файл существует; `gh repo view --json licenseInfo` после merge показывает MIT; README ссылается.
- **Гигиена:** `git ls-files | grep -E "pyc|pycache"` → пусто; `git check-ignore .review-responses/` → возвращает путь (`.gitignore`-правка в этом же PR, §3.2 — если оператор авторизовал Edit); `docs/plans/peppy-whistling-puppy.md` в `docs/archive/`.
- **Onboarding-гейт (исполнимо, тестирует РЕАЛЬНЫЙ awk|grep конвейер гейта, не только grep; shipped-файл НЕ мутируется):**
  - Извлечь блоки как гейт: `BLK=$(awk 'BEGIN{b=sprintf("%c",96);F="^[[:space:]]*" b b b} $0~F{f=!f;next} f' .claude/skills/verify/SKILL.md)`.
  - Шаблон: `printf '%s\n' "$BLK" | grep -qE '<[A-Z][A-Z_]{2,}>'` → exit 0 (плейсхолдеры в fenced-блоках → гейт сработал бы).
  - Игнор прозы: число `<…>` в `$BLK` < числа во всём файле — прозу-легенду и блок «Пример (U2 reference)» гейт не видит (gate извлекает только bash-блоки).
  - После адаптации (заполнены командные блоки): `$BLK` без `<…>` → grep exit 1 → гейт пропускает.
  - Robustness (broadened): fixture с отступленным ```sh + плейсхолдером → toggle-awk ЛОВИТ (старый `^```bash` пропускал); прозовый токен вне fence в `$BLK` НЕ попадает.
  - `tests.md` — **advisory** (не fail-closed): `grep -qE '<…>' .claude/rules/tests.md` → есть → echo-предупреждение, установку не блокирует.
  - Пререквизиты — INSTALL §A.1 + README-таблица; `INSTALL_ALLOW_NPM_DRIFT` в §A; `bd --version` surface в §B.1. Shipped `verify/SKILL.md`/`tests.md` остаётся с плейсхолдерами (не редактируется).
- **Регрессии пайплайна:** `bash scripts/test-bd-sync.sh` 23/23; `bd ready --json` валиден (основной acceptance-gate; **`bd doctor` в embedded-mode НЕ поддерживается** — красный там не считать провалом, см. INSTALL §A.3); `/pipeline-audit` без drift (затронуты нормативные артефакты — инварианты имён ролей/команд).
- **Release:** `gh release list` показывает `v3.9.0-beta.1` (prerelease); `git tag -l` содержит новый тег; ноты соответствуют CHANGELOG.

## Риски / заметки

- **Critical tier + Sprint Final** = полный внешний ревью-цикл (Codex CLI / GPT-5.5+5.3). Самый дорогой шаг по времени; основной объём правок — markdown, ревью пройдёт быстро, но external-review обязателен для релиза в main.
- `.gitignore` — **в release-PR** через operator pre-authorization Edit (§3.2, Preconditions), не post-merge. Удаление `.agents/skills/` — working-tree cleanup с согласия оператора (§3.4, вне диффа). Не обходить deny.
- beta = ожидаемы шероховатости; `og-mk4` (P3) и узкое окно bd 1.0.2 вынесены в CHANGELOG «Known limitations», не блокируют релиз. `og-xxj` (P1) — **блокирует** (Preconditions).
- Лицензия/правообладатель и pre-auth `.gitignore` — оформлены как **Preconditions** (выше), а не заметки в конце.
