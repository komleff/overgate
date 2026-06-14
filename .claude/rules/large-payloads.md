---
description: Правила работы с большими payload'ами в tool_use — защита от socket-closed прерываний
globs: "**/*"
---

# Большие payload'ы — защита от socket-closed

## Проблема

При передаче больших данных через single `tool_use` (Bash inline heredoc, Write content, Edit new_string) Anthropic API стабильно роняет соединение:

```
API Error: The socket connection was closed unexpectedly.
For more information, pass `verbose: true` in the second argument to fetch()
```

Retry не помогает — ошибка детерминистически повторяется через несколько минут. Это **не сетевая нестабильность**, это лимит payload size на стороне tool_use streaming. Зафиксировано минимум на 5-6 incident'ах разных агентов в проекте 2026-05-24.

## Threshold (эмпирический)

- **Безопасно:** payload < ~1.5 KB (≈ 1500 символов).
- **Зона риска:** 1.5–10 KB — иногда проходит, иногда падает.
- **Падает почти всегда:** > 10 KB.

Не полагайся на «маленький размер» интуитивно. Если ты пишешь heredoc больше одного экрана текста — он уже в зоне риска.

## Правила по инструментам

### Bash — НЕ передавай большие строки inline

**Запрещено** (проблема — **размер** payload, ~200 строк inline, а НЕ форма heredoc; сама heredoc-форма с уникальным делимитером корректна — см. ниже):

```bash
gh pr comment 270 --body "$(cat <<'GH_BODY_<RAND>'
... 200 строк markdown ...   # ← проблема в объёме, не в делимитере
GH_BODY_<RAND>
)"
```

```bash
echo "огромный JSON или огромный лог" > file.txt
```

```bash
curl -X POST -d "$(cat <<EOF
... большое тело запроса ...
EOF
)" https://...
```

**Правильно:** сначала Write tool создаёт файл, потом Bash читает его через флаг или редирект.

```text
1. Write tool → D:/tmp/pr-body-270.md (содержимое)
2. Bash → gh pr create --body-file D:/tmp/pr-body-270.md
```

```text
1. Write tool → D:/tmp/payload.json
2. Bash → curl -X POST --data-binary @D:/tmp/payload.json https://...
```

Большинство CLI поддерживают флаги для чтения тела из файла:

| Инструмент | Inline (плохо) | File-based (хорошо) |
|---|---|---|
| `gh pr create` | `--body "..."` | `--body-file file.md` |
| `gh issue create` | `--body "..."` | `--body-file file.md` |
| `gh issue comment` | `--body "..."` | `--body-file file.md` |
| `gh api` | `-f field=...` для большого значения | `--input file.json` |
| `curl` | `-d "$(...)"` | `--data-binary @file` |
| `git commit` | `-m "long message"` | `-F file.txt` |
| `git notes add` | `-m "..."` | `-F file.txt` |
| `git tag` | `-m "..."` | `-F file.txt` |
| `dotnet run` arg | inline | через файл + флаг |

### ⚠️ Особый случай: `gh pr comment` (заблокирован hook'ом вне `/finalize-pr`)

Pre-tool-use hook проекта (`.claude/hooks/check-merge-ready.py`, matcher `Bash(*gh pr comment*)`) **жёстко блокирует шесть разных способов** скрыть содержимое body от inline-валидации:

| Функция hook'а | Что блокируется | Сообщение об ошибке начинается с |
|---|---|---|
| `uses_body_file` | `--body-file file.md` / `-F file.md` | «БЛОКИРОВКА: для `gh pr comment` флаги --body-file / -F запрещены …» |
| `uses_edit_last` | `--edit-last` (открывает редактор для последнего комментария) | «БЛОКИРОВКА: для `gh pr comment` флаг --edit-last запрещён …» |
| `uses_no_body` | `gh pr comment <N>` без `--body` / `-b` / `--body-file` / `-F` (открывает редактор) | «БЛОКИРОВКА: `gh pr comment` без флага --body / -b / --body-file / -F запрещён …» |
| `uses_dangerous_substitution` | `--body "$(cat /file)"` / `--body "$(<file)"` / `--body \`cat file\`` (file-read substitutions) | «БЛОКИРОВКА: для `gh pr comment` запрещены конструкции, скрывающие содержимое body: `$(cat file)`, `$(<file)`, backticks …» |
| `uses_opaque_variable_body` | `--body "$VAR"` / `--body $VAR` / `--body "${VAR}"` (переменная без heredoc-источника в той же команде) | «БЛОКИРОВКА: для `gh pr comment` нельзя подставлять body из переменной …» |
| `uses_opaque_command_substitution_body` | `--body "$(echo $X)"` / `--body "$(head file)"` / `--body "$(printf ...)"` (любая command substitution в позиции `--body`, не file-read) | «БЛОКИРОВКА: для `gh pr comment` нельзя подставлять body через command substitution …» |

Причина одна: hook валидирует содержимое body (включая запрет «ready to merge» декларации). Любой путь, скрывающий реальные байты от regex-проверки, fail-secure блокируется. Это защита Copilot round 31 + Codex round 14/21/27/28, **не** обходить.

Легитимные исключения (видны hook'у):
- Inline literal: `--body '...'` или `--body "..."` без подстановок.
- Heredoc-cat in body: `--body "$(cat <<'GH_BODY_<RAND>' ... GH_BODY_<RAND>)"` — содержимое инлайн в команде.
- Heredoc через переменную: `BODY=$(cat <<'GH_BODY_<RAND>' ... GH_BODY_<RAND>); gh pr comment --body "$BODY"` — `_body_var_has_heredoc` распознаёт привязку.

> ⚠️ **Делимитер heredoc — уникальный и заведомо отсутствующий в теле ДО запуска shell-команды** (`GH_BODY_<RAND>` — не копируй буквально; сгенерируй fresh `openssl rand -hex 8` и вставь суффикс в обе строки делимитера), а не фиксированный `EOF`. Тело комментария/ревью часто содержит цитаты кода/diff (включая сами heredoc-примеры с `EOF`): строка ровно `EOF` в теле закроет heredoc раньше, и хвост уйдёт shell'у (delimiter-collision). Кавычки в делимитере (`<<'...'`) блокируют `$()`/backtick/`$VAR` expansion. Агент обязан проверить подготавливаемое тело до эмиссии команды; если выбранный делимитер встречается как отдельная строка — сгенерировать новый. Канон — `AGENTS.md` секция «Публикация ревью в PR».

Что это значит для агентов:

| Сценарий | Правильный путь |
|---|---|
| Sprint Final-отчёт / любой большой PM-комментарий | Запустить `/finalize-pr <N>` — slash-команда устанавливает `FINALIZE_PR_TOKEN`, hook пропускает все 5 блокировок |
| Не-PM комментарий < 1.5 KB | `gh pr comment <N> --body "..."` (inline literal) — hook видит содержимое, валидирует |
| Не-PM комментарий 1.5-3 KB | Разбить на 2-3 inline `gh pr comment --body "..."` calls, каждый < 1.5 KB |
| Не-PM комментарий > 3 KB (типично — reviewer-субагент с большим findings-блоком) | Пиши findings в файл `D:/tmp/review-<N>-iter<K>.md` (или `$TMPDIR/review-...` на macOS/Linux), передавай **путь** PM в финальном сообщении субагента. PM публикует через `/finalize-pr` или Sprint Pipeline external-review skill. Не пытайся опубликовать сам через workaround |

### Honor system: пути, которые hook **не ловит**

Hook matcher `Bash(*gh pr comment*)` — узкий. Технически через GitHub API проходят:

- `gh api repos/<owner>/<repo>/issues/<PR>/comments --input body.json` (PR — это issue, REST endpoint валиден).
- `gh issue comment <PR_NUMBER> --body-file body.md` (PR-номер принимается как issue-номер, комментарий появляется в PR).

**Это НЕ значит, что обходить можно.** Hook сужен по матчеру для производительности, не для разрешения bypass. Использование этих путей для PR-комментариев — **trust violation**: ты обходишь fail-secure защиту, которая существует по правовой причине (предотвращение `ready to merge` деклараций вне `/finalize-pr` gate). Если поймаешь себя на мысли «можно же через `gh api` или `gh issue comment`» — это red flag, твой комментарий должен идти через PM/`/finalize-pr` или быть разбит на inline куски.

Для **остальных** случаев (создание PR, создание issue, комментарий к issue, curl-payload и т.д.) — обычный file-based pattern из таблицы выше работает легитимно.

### Write — большие файлы лимитированы тем же лимитом

Если генерируешь файл > 10 KB (≈ 200 строк кода или markdown) — **разбей на части**:

1. Первый `Write` создаёт skeleton (frontmatter + заголовки секций, ≤ 5 KB). Placeholder'ы для каждой секции должны быть **уникальными** (`<!-- SEC-INTRO -->`, `<!-- SEC-API -->`, …), иначе `Edit` упадёт с `old_string not unique`. Либо используй `replace_all: true`, если placeholder одинаковый по дизайну.
2. Далее серия `Edit`-вызовов заменяет каждый секционный placeholder на готовый контент (каждый `Edit` ≤ 5 KB).

Альтернатива (хуже, только для совсем больших data-файлов): `Write` несколько мелких файлов-частей, потом `Bash → cat part1 part2 part3 > final`.

**Не делай:**

- Один `Write` с 1000-строчным файлом — упадёт.
- `Write` с base64-кодированным бинарником > 5 KB — упадёт.

### Edit — большой new_string == большой payload

Тот же лимит. Если `new_string` больше ~5 KB — разбей замену на серию мелких `Edit`'ов по отдельным секциям.

Не пытайся одним `Edit` переписать пол-файла — это и архитектурно хрупко, и упадёт по socket.

### Read — лимит другой, проблема не та

`Read` обычно не страдает от socket-closed (это input для агента, не payload tool_use). Но если читаешь файл > 2000 строк — используй `offset` + `limit`, не загружай всё разом (ухудшает context window).

## Что делать, если уже упал

1. **Один retry допустим как дешёвая диагностика** (отсекает редкий transient network case) — но не более. Если упало повторно — это детерминистическая ошибка по payload size, не сетевая, дальнейшие retry бесполезны.
2. **Не уменьшай только на чуть-чуть** — упадёт снова через 1-2 итерации.
3. **Переключись на file-based pattern сразу.** Write tool → файл → reference в Bash через флаг. Это работает.
4. **Сообщи оператору один раз** что переходишь на file-based из-за socket-closed. Не спрашивай разрешения — это правило проекта.

## Чеклист перед большим tool_use

Прежде чем передать большой payload — спроси себя:

- [ ] Размер payload > 1.5 KB?
- [ ] Это inline string в Bash (heredoc, `-d "..."`, `--body "..."`)?
- [ ] Если да на оба — Write tool в файл и file-based флаг.

Если генерируешь большой Write/Edit:

- [ ] Контент > 10 KB?
- [ ] Если да — разбить на skeleton + Edit'ы по секциям.

## Источник правила

- Operator feedback 2026-05-24: «5-6 раз словил прерывание с ошибкой socket-closed, retry не помогает, нужно решить надёжно для всех агентов».
- PM memory `pm-c-2026-05-24-socket-closed-pr` (изначально только для PM, поднято на проектный уровень).
