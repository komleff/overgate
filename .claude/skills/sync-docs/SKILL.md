---
name: sync-docs
description: (EXAMPLE doc-навигация) Синхронизация навигации проекта — индексы документов, реестр ADR, memory-bank — после merge документов или ADR в main. Используй когда в main появились новые ADR/доктрины/спеки или завершён milestone, и индексы навигации устарели. Триггеры: «обнови индексы», «sync docs», «синхронизируй навигацию», «после merge PR #N надо обновить INDEX». Не трогает содержимое самих ADR — только записи в индексах. (Пути и связанный site-sync — пример из U2; адаптируй под свой проект.)
user-invocable: true
---

> ⚙️ EXAMPLE doc-навигация. Пути (`docs/INDEX.md`, ADR-INDEX, memory-bank) — пример из U2; адаптируй под свой проект. Плейсхолдеры: `<DOC_INDEX>` (главный индекс документов), `<ADR_INDEX>` (реестр ADR), `<MEMORY_BANK>` (каталог оперативного контекста).

# Sync Docs — синхронизация навигации проекта

`/sync-docs` приводит навигационные документы и memory-bank проекта в соответствие с актуальным состоянием `main`. Один запуск = один PR с правкой 4 файлов (`<DOC_INDEX>`, `<ADR_INDEX>`, `<MEMORY_BANK>/activeContext.md`, `<MEMORY_BANK>/progress.md`).

## Что скилл делает и что не делает

Делает:
- Находит документы, появившиеся в `main` после последней синхронизации, и **дописывает** записи в индексы.
- Обновляет шапку (`version`, `date`) каждого правленого индекса с лаконичной строкой истории.
- Добавляет в `activeContext.md` секцию о завершённом milestone (если триггер — завершение работы), обновляет дату.
- Добавляет в `progress.md` подраздел в «Что готово» и актуализирует метрики.

Не делает:
- Не правит содержимое самих ADR, доктрин, спек. Если запись в INDEX противоречит файлу — фиксирует в выводе как finding, но не правит файл.
- Не удаляет записи об устаревших документах. Меняет их статус на `superseded` / `reference`.
- Не трогает `docs/gdd/site/content/manifest.json` — это область `/sync-site-gdd`.
- Не правит «Текущий фокус» в `activeContext.md` — это зона активного PM. Добавляет новые секции, не переписывает существующие.

## Когда не запускать

- В main с последней синхронизации нет нового — все кандидаты уже в INDEX.
- Триггер — изменение текста уже учтённого документа без bump'а `version` или `status` в frontmatter. Запись в INDEX от такого не меняется.
- Изменения только в коде, тестах, CI, `.claude/`, `.agents/`. Доменных документов не появилось.

## Промпт активации

```
/sync-docs

Триггер: <merge PR #N | завершение milestone X | архивация Y | оператор просит вручную>
База синхронизации: <commit hash | "auto — git log по INDEX.md">
```

Если триггер не указан — скилл сам определит окно по `git log --first-parent main -1 -- docs/INDEX.md`.

## Workflow

### Шаг 1 — Определить окно синхронизации

```bash
cd <REPO_ROOT>
git fetch origin

# База: коммит последней правки INDEX.md в main
BASE=$(git log --first-parent origin/main -1 --format=%H -- docs/INDEX.md)
echo "База синхронизации: $BASE"

# Что появилось в main с этой базы
git log --first-parent ${BASE}..origin/main --name-status -- docs/ .memory-bank/
```

Собери список:
- новые файлы (`A`)
- удалённые (`D`)
- переименованные (`R`)
- модифицированные с изменением `version` или `status` в frontmatter (`M` + сверка frontmatter)

### Шаг 2 — Сверить с индексами

У документов разные «домашние» индексы:
- `docs/architecture/ADR-NNNN-*.md` → запись должна быть в `docs/architecture/ADR-INDEX.md`. В `docs/INDEX.md` ADR упомянуты только сводно (через запись про сам ADR-INDEX), поштучно их там нет — это **не** пропуск.
- Все остальные ГД-релевантные документы → запись в `docs/INDEX.md`.

Поэтому `grep -L file1 file2` использовать нельзя: он выдаст имя файла, в котором паттерна нет, даже когда документ корректно зарегистрирован в «своём» индексе. Сверяй по домашнему индексу:

```bash
for f in <список новых файлов из шага 1>; do
  slug=$(basename "$f" .md)
  case "$f" in
    docs/architecture/ADR-[0-9]*)
      home="docs/architecture/ADR-INDEX.md" ;;
    *)
      home="docs/INDEX.md" ;;
  esac
  grep -q "$slug" "$home" || echo "missing in $home: $f"
done
```

Для модифицированных — прочитай frontmatter (`version`, `status`) и сравни со строкой в INDEX. Если разошлись — кандидат на правку.

> **Если не уверен в категории/тегах документа** — спроси оператора через `AskUserQuestion` с 2-4 вариантами. Не угадывай: каталог INDEX зафиксирован, ошибочный тег засчитывается как content-drift и потом ловится `bd doctor --check=conventions`.

### Шаг 3 — Создать worktree

```powershell
git worktree add <REPO_ROOT>-sync-docs-<YYYY-MM-DD> -B docs/sync-indexes-<YYYY-MM-DD> origin/main
cd <REPO_ROOT>-sync-docs-<YYYY-MM-DD>
```

Worktree обязателен — основной репо `<REPO_ROOT>` может содержать незакоммиченную работу оператора.

> **Не делай `git worktree add` из WSL / Linux-mount** — может обнулить `.git/config` основного репо. Только нативный Windows git.
> **Не делай worktree в корне `D:\`** — рабочие папки агентов держим внутри `D:\GitHub\` (общая гигиена воркспейсов).

### Шаг 4 — Применить правки

#### 4.1. `docs/architecture/ADR-INDEX.md`

- Новые строки строго в порядке возрастания `ADR-NNNN`. Сквозная нумерация не нарушается.
- Шаблон строки реестра:
  ```
  | ADR-NNNN | <теги> | <active/draft/superseded/deprecated> | <решение одной фразой> | [ADR-NNNN](ADR-NNNN-<slug>.md) |
  ```
  Теги — область: `architecture`, `network`, `physics`, `ux`, `gd`, `monetization`, `narrative`, `brand`, `world`, `social`, `base`, `combat`, `economy`, `client`, `server`.
- Шапка: `version` bump'ается минор-ом (`0.7` → `0.8` при добавлении ADR; `0.7.1` если только косметика).
- В «История изменений» — **одна** строка на bump:
  ```
  | <X.Y> | <YYYY-MM-DD> | <что изменилось, лаконично> |
  ```

#### 4.2. `docs/INDEX.md`

- Новые строки — в соответствующие группы «Каталог документов». Статус и версия **строго** совпадают с frontmatter файла-источника.
- Шаблон строки каталога:
  ```
  | [path/to/file.md](path/to/file.md) | <primary/active/draft/reference/superseded> | <X.Y> | <одной фразой о чём документ> | <теги> |
  ```
- При появлении принципиально новой темы (новая роль / новый рабочий процесс) — строка в «Быстрый старт по ролям»:
  ```
  | <Роль или задача — одной фразой> | [file1](path1) → [file2](path2) → [file3](path3) | <зачем такая цепочка> |
  ```
  Не больше 5 файлов в цепочке.
- Если у `ADR-INDEX` поднялась версия — обновить и его запись в каталоге ADR.
- Шапка `version` bump'ается минор-ом. Одна строка в истории.

#### 4.3. `.memory-bank/activeContext.md`

- Шапка: дата последнего обновления → текущая.
- Если триггер — завершение milestone — добавь секцию `## <Тема> — COMPLETE <YYYY-MM-DD>` со ссылками на ключевые файлы.
- **Не правь** существующую секцию «Текущий фокус» — это зона активного PM. Если фокус устарел и нужно сменить — это отдельная задача, эскалируй оператору.
- **Архивация-триггер:** если файл > 100 KB или завершённых секций больше 8 — пометь оператору:
  > activeContext.md разрастается (NN KB, M секций). Рекомендую перенести секции X, Y, Z в `docs/archive/sessions/<YYYY-MM>.md`.

  Сам архивацию не делай — это отдельная задача.

#### 4.4. `.memory-bank/progress.md`

- Новый подраздел в «Что работает (✅ завершено)» либо обновление позиций в «Что в процессе» / «Что не начато».
- Актуализация метрик внизу (количество активных документов с frontmatter, тесты) — если изменилось.

### Шаг 5 — Превентивная защита от truncation

Если хотя бы один из правленых файлов:
- содержит больше 80 строк кириллицы, или
- больше 30 KB,

то **не используй Edit** для правок. Используй python-скрипт с явным UTF-8:

```python
from pathlib import Path
p = Path("docs/INDEX.md")
text = p.read_text(encoding="utf-8")
# ... модификации ...
p.write_text(new_text, encoding="utf-8")
```

Edit на длинных кириллических markdown-файлах исторически обрезает хвосты — это задокументированный паттерн отказа в memory `feedback_edit_truncation.md`.

### Шаг 6 — Проверка перед коммитом

```bash
git diff --stat
```

Чеклист:
- В diff ровно 4 файла. Если больше — scope creep, делай отдельным PR.
- Каждая правка **увеличивает** файл (truncation-guard).
- В каждом правленом индексе обновлены `version` и `date` в frontmatter.
- Tail-строка каждого индекса = новая запись истории или новая строка каталога.
- `git diff` показывает только добавления и точечные правки шапки. Никаких массовых перетасовок строк (то был бы признак CRLF/encoding-проблемы).

```powershell
# Размеры — должны быть больше предыдущих
(Get-Item docs/INDEX.md).Length
(Get-Item docs/architecture/ADR-INDEX.md).Length
(Get-Item .memory-bank/activeContext.md).Length
(Get-Item .memory-bank/progress.md).Length
```

### Шаг 7 — Коммит

```bash
git add docs/architecture/ADR-INDEX.md docs/INDEX.md .memory-bank/activeContext.md .memory-bank/progress.md
git commit -F commit-msg.txt
```

Шаблон `commit-msg.txt`:

```
docs(canon): синхронизация индексов после <триггер>

ADR-INDEX.md vA → vB:
- <что добавлено, по одной строке на ADR>

docs/INDEX.md vA → vB:
- <что добавлено, по разделам>

.memory-bank/activeContext.md:
- <что обновлено>

.memory-bank/progress.md:
- <что обновлено>
```

Используй `-F commit-msg.txt`, не inline `-m "..."` — длинные кириллические сообщения в `-m` иногда ломаются на Windows-консоли.

### Шаг 8 — Push + PR

```bash
git push -u origin docs/sync-indexes-<YYYY-MM-DD>

gh pr create \
  --base main \
  --head docs/sync-indexes-<YYYY-MM-DD> \
  --title "docs(canon): sync индексов после <триггер>" \
  --body-file pr-body.txt
```

> `--body-file` для `gh pr comment` блокируется hook'ом вне `/finalize-pr`. Для `gh pr create` — разрешён.

Шаблон `pr-body.txt`:

```
Синхронизация навигации и memory-bank после <триггер>.

<2-3 строки контекста: что произошло в main, почему индексы нужно подтянуть>

Изменения:
- ADR-INDEX.md vA → vB: <короткий список>
- docs/INDEX.md vA → vB: <короткий список>
- .memory-bank/activeContext.md: <короткое>
- .memory-bank/progress.md: <короткое>

Содержательных правок в самих доктринах и ADR нет — только навигация и контекст.

Tier ревью: Light (только .md, без логики).

— Doc Sync (Claude Opus 4.7)
```

> **Подпись обязательна.** AGENTS.md строка 120 требует подпись модели в комментариях GitHub. Формат — `— [Роль] ([Модель])` по AGENT_ROLES §0.

### Шаг 9 — После merge оператором

```powershell
cd <REPO_ROOT>
git worktree remove <REPO_ROOT>-sync-docs-<YYYY-MM-DD>
git branch -D docs/sync-indexes-<YYYY-MM-DD>
```

Если есть временные файлы в `.tmp/sync-docs-<YYYY-MM-DD>/` — удалить.

### Шаг 10 — Подсказать `/sync-site-gdd`

Если среди добавленных в INDEX документов есть **ГД-релевантные** — ADR, доктрины бренда, GDD/PvE/Marketing/Audit/Gameplay-спеки — упомяни в финальном отчёте:

> Среди добавленных документов есть ГД-релевантные (<список>). После merge этого PR запусти `/sync-site-gdd`, чтобы они появились на <SITE_HOST>.

Технические спеки (`docs/specs/tech/`), research, infrastructure-документы — на сайт не идут, `/sync-site-gdd` не нужен.

## Защитные паттерны (резюме)

- **sha256 на трёх рубежах** (если работаешь по handoff с готовыми файлами): эталон → копия в worktree → перед коммитом.
- **PowerShell-worktree, не WSL** — защита от обнуления `.git/config`.
- **python+UTF-8 для длинных кириллических файлов** — защита от Edit truncation.
- **Tail-проверка** — последняя строка файла после правки должна быть новой записью истории/каталога.
- **scope-граница с PM** — не трогай «Текущий фокус» в `activeContext.md`.

## Запреты

- Не править содержимое ADR, доктрин, спек — только записи в индексах.
- Не удалять записи об устаревших документах — меняй статус на `superseded`/`reference`.
- Не push в `main` напрямую.
- Не делать `git worktree add` через WSL/bound-mount.
- Не делать worktree в корне `D:\` — только внутри `D:\GitHub\`.
- Не переключать ветку в основном `<REPO_ROOT>` — там может быть uncommitted работа оператора.
- Не «улучшать» структуру индексов без отдельной задачи. Цель — добавить актуальное, не переписывать существующее.

## Канонические ссылки

- `AGENTS.md` — подпись модели обязательна.
- `.agents/AGENT_ROLES.md` §0 — формат подписи `— [Роль] ([Модель])`.
- `.agents/AGENT_ROLES.md` §3 — tier ревью (Light для .md-only).
- `docs/STYLE.md` — оформление frontmatter и snake_case имён.
- `.claude/rules/universal.md` — git workflow, атомарность.
- Связанный скилл — `/sync-site-gdd` для `<SITE_HOST>`.
