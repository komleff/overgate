#!/usr/bin/env python3
"""Unit-тесты для check-merge-ready.py.

Запуск (кросс-платформенно):
  - Linux/macOS:  python3 .claude/hooks/test_check_merge_ready.py
  - Windows:      py -3 .claude/hooks/test_check_merge_ready.py
                  (или `python .claude/hooks/test_check_merge_ready.py`)

На Windows `python3` — Microsoft Store alias, который не является валидным
интерпретатором и возвращает exit 9009. Используй `py -3` или `python`.

Тестовое покрытие:
- Точный маркер `## ✅ Готов к merge` → блокируется
- Обсуждения/цитаты с «готов к merge» → пропускаются
- Обход через --body-file / -F → блокируется
- Обход через $(cat file) / $(<file) / backtick subst → блокируется
- `<<<` (here-string) НЕ блокируется: gh pr comment не читает stdin без --body-file -,
  а false-positive на текст body с `<<<` был бы критичнее
- Legitimate markdown с backticks → пропускается
- Heredoc `$(cat <<'EOF'...EOF)` — содержимое видно, блокируется/пропускается по контенту
- FINALIZE_PR_TOKEN → bypass
- Пустая команда или отсутствие `tool_input.command` → fail-secure блокировка
"""
import json
import os
import subprocess
import sys
from typing import Optional


HOOK = os.path.join(os.path.dirname(__file__), "check-merge-ready.py")


def run(cmd: Optional[str], with_token: bool = False) -> int:
    """Запустить hook с payload и вернуть exit code."""
    env = {k: v for k, v in os.environ.items() if k != "FINALIZE_PR_TOKEN"}
    if with_token:
        env["FINALIZE_PR_TOKEN"] = "1"
    if cmd is None:
        payload = json.dumps({"tool_input": {}})
    else:
        payload = json.dumps({"tool_input": {"command": cmd}})
    # sys.executable — кросс-платформенно: Linux/macOS найдут python3, Windows
    # использует текущий интерпретатор вместо несуществующего `python3`.
    result = subprocess.run(
        [sys.executable, HOOK],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode


TESTS = [
    # === Блокировка: точный маркер `## ✅ Готов к merge` ===
    ("gh pr comment 1 --body '## ✅ Готов к merge\n\nCommit: abc'", 1, "final marker RU"),
    ("gh pr comment 1 --body '## Готов к merge'", 1, "без ✅"),
    ("gh pr comment 1 --body '## Ready to merge'", 1, "EN ready to merge"),
    ("gh pr comment 1 --body '## merge-ready'", 1, "EN merge-ready"),
    ("gh pr comment 1 --body '## READY TO MERGE'", 1, "uppercase"),
    ("gh pr comment 1 --body '## ready_to_merge'", 1, "underscores"),
    # GPT-5.4 external review (round 12) — CRITICAL bypass прежнего H2-only:
    # фраза без `##` на отдельной строке должна блокироваться.
    ("gh pr comment 1 --body 'ready to merge'", 1, "bare ready to merge"),
    ("gh pr comment 1 --body 'Готов к merge'", 1, "bare готов к merge"),
    ("gh pr comment 1 --body 'merge ready'", 1, "bare merge ready"),
    ("gh pr comment 1 --body 'PR is ready to merge'", 1, "PR is ready to merge"),
    # === Copilot round 22 CRITICAL: пунктуация `.!?` обходила терминатор ===
    ("gh pr comment 1 --body 'PR is ready to merge.'", 1, "PR is ready to merge + dot"),
    ("gh pr comment 1 --body 'PR is ready to merge!'", 1, "PR is ready to merge + bang"),
    ("gh pr comment 1 --body 'PR is ready to merge?'", 1, "PR is ready to merge + question"),
    ("gh pr comment 1 --body '## ✅ Готов к merge.'", 1, "final marker RU + dot"),
    ("gh pr comment 1 --body '## ✅ Готов к merge!'", 1, "final marker RU + bang"),
    ("gh pr comment 1 --body '## ✅ Готов к merge?'", 1, "final marker RU + question"),
    # === big-heroes-ase: запятая как terminator (regression v3.5) ===
    # Pre-existing bypass: фраза «готов к merge, <продолжение>» обходила hook
    # с запятой-разделителем. Репродьюсер: PM_ROLE §2.5 Шаг 8 и
    # sprint-pr-cycle Фаза 4.5.7 содержат «готов к merge, landing artifacts
    # уже внутри» — если PM копирует дословно в gh pr comment, hook должен
    # блокировать, а не пропускать как «обсуждение».
    ("gh pr comment 14 --body 'PR готов к merge, landing inside'", 1, "ase: comma terminator RU"),
    ("gh pr comment 1 --body 'ready to merge, landing inside'", 1, "ase: comma terminator EN"),
    ("gh pr comment 1 --body '## ✅ Готов к merge, landing artifacts уже внутри'", 1, "ase: RU marker + запятая + продолжение"),
    # === big-heroes-nw5: semicolon и ellipsis как terminator (Tester gate v3.5) ===
    # После закрытия bd-ase запятой Tester обнаружил class-coverage gap:
    # `;` и `…` (U+2026) — symmetric punctuation-terminators, обходят hook
    # тем же способом. Расширяем класс: [.!?,] → [.!?,;…].
    ("gh pr comment 15 --body '## ✅ Готов к merge; landing commit следом'", 1, "nw5: semicolon terminator RU"),
    ("gh pr comment 15 --body 'ready to merge; see CI'", 1, "nw5: semicolon terminator EN"),
    ("gh pr comment 15 --body 'готов к merge… если X'", 1, "nw5: ellipsis U+2026 terminator RU"),
    # Symmetry semantic для discussion-continuations: `когда X` и `как только X`
    # ведут себя как `если X` — запятая делает их terminator, декларация readiness
    # с продолжением. Явно фиксируем через coverage.
    ("gh pr comment 1 --body 'готов к merge, когда X'", 1, "nw5: symmetry — запятая + когда"),
    ("gh pr comment 1 --body 'готов к merge, как только X'", 1, "nw5: symmetry — запятая + как только"),
    # === dolt-ihl: ASCII ':' + CJK + full-width terminators (Pass 1 external F-1) ===
    # GPT-5.4 + GPT-5.3-Codex independent repro показал bypass через 5 terminators,
    # не покрытых прежним classом [.!?,;\u2026]:
    #   - `:` (ASCII colon) — частый separator в markdown-списках и декларациях.
    #   - `。` (U+3002) — CJK ideographic full stop.
    #   - `！` (U+FF01) — full-width exclamation mark.
    #   - `？` (U+FF1F) — full-width question mark.
    #   - `，` (U+FF0C) — full-width comma.
    # Расширяем class до [.!?,;:\u2026\u3002\uff01\uff1f\uff0c].
    # 5 bypass-кейсов (по одному на каждый новый terminator):
    ("gh pr comment 1 --body 'ready to merge: landing'", 1, "ihl: colon terminator EN"),
    ("gh pr comment 1 --body 'готов к merge。следующий шаг'", 1, "ihl: CJK full stop U+3002 RU"),
    ("gh pr comment 1 --body 'ready to merge！next'", 1, "ihl: full-width exclamation U+FF01"),
    ("gh pr comment 1 --body 'ready to merge？maybe'", 1, "ihl: full-width question U+FF1F"),
    ("gh pr comment 1 --body 'готов к merge，landing artifacts inside'", 1, "ihl: full-width comma U+FF0C"),
    # 5 symmetric discussion-continuation кейсов (терминатор + продолжение) —
    # подтверждают, что расширение class-coverage покрывает реальные
    # narrative-попытки обхода.
    ("gh pr comment 1 --body '## ✅ Готов к merge: landing commit follows'", 1, "ihl: RU marker + colon terminator"),
    ("gh pr comment 1 --body '## ✅ Готов к merge。landing commit следом'", 1, "ihl: RU marker + CJK full stop"),
    ("gh pr comment 1 --body 'ready to merge！see CI'", 1, "ihl: EN + full-width exclamation + продолжение"),
    ("gh pr comment 1 --body 'ready to merge？see you later'", 1, "ihl: EN + full-width question + продолжение"),
    ("gh pr comment 1 --body '## Готов к merge，если X'", 1, "ihl: RU ## + full-width comma + продолжение"),
    # === dolt-0di: G1 systemic Unicode punctuation terminators (Pass 2) ===
    # Pass 2 Tester gate выявил 12+ Unicode punctuation codepoints, обходящих
    # прежний enumeration terminator class [.!?,;:\u2026\u3002\uff01\uff1f\uff0c].
    # Fix: unicodedata.category(ch).startswith('P') — любая Unicode
    # punctuation семантически отделяет declaration от продолжения, не нужен
    # enumeration. Регрессия-guard для всех 12 символов.
    ("gh pr comment 1 --body 'ready to merge、landing'", 1, "G1: U+3001 ideographic comma"),
    ("gh pr comment 1 --body 'готов к merge：next'", 1, "G1: U+FF1A full-width colon"),
    ("gh pr comment 1 --body 'ready to merge；next'", 1, "G1: U+FF1B full-width semicolon"),
    ("gh pr comment 1 --body 'ready to merge،next'", 1, "G1: U+060C Arabic comma"),
    ("gh pr comment 1 --body 'ready to merge؛next'", 1, "G1: U+061B Arabic semicolon"),
    ("gh pr comment 1 --body 'ready to merge؟'", 1, "G1: U+061F Arabic question"),
    ("gh pr comment 1 --body 'ready to merge׃next'", 1, "G1: U+05C3 Hebrew sof pasuq"),
    ("gh pr comment 1 --body 'ready to merge᠂next'", 1, "G1: U+1802 Mongolian comma"),
    ("gh pr comment 1 --body 'ready to merge։next'", 1, "G1: U+0589 Armenian full stop"),
    ("gh pr comment 1 --body 'ready to merge・next'", 1, "G1: U+30FB Japanese middle dot"),
    ("gh pr comment 1 --body 'ready to merge．next'", 1, "G1: U+FF0E full-width period"),
    # === dolt-0di: G2 combining diacritic / accent bypass (Pass 2) ===
    # NFKC-нормализация стабилизирует compatibility forms; спейсом-акцент
    # `\u00b4` (ACUTE ACCENT) классифицируется как Sk (symbol modifier), но
    # стоит он ПЕРЕД terminator `:` → hook всё равно должен увидеть phrase
    # `ready to merge` → acute — content continuation → `:` → terminator.
    # Combining U+0301 на `é` в конце `mergé` делает phrase ortographically
    # другим, regex НЕ матчит `merge`. Это защита по другому механизму
    # (phrase orthography), оставляем как регрессионный baseline.
    ("gh pr comment 1 --body 'ready to merge\u00b4:landing'", 1, "G2: acute accent U+00B4 + colon"),
    ("gh pr comment 1 --body 'ready to merge\u0301:landing'", 1, "G2: combining acute U+0301 + colon"),
    # === Pass 3 Copilot CP-1: NBSP / em-space horizontal whitespace ===
    # После html.unescape `&nbsp;` → U+00A0 (NBSP). Прежний skip-loop класс
    # `c in " \t"` пропускал только ASCII SPACE/TAB. Хотя NFKD обычно
    # декомпозирует NBSP в regular space (покрывая этот кейс), defense-in-depth
    # требует explicit c.isspace() and c not in "\n\r" — любой horizontal
    # whitespace должен быть прозрачен для terminator-check, независимо от
    # нормализации. Это широкая G2-closure: все Zs, Zl (кроме \n), и ASCII
    # \t/\v/\f → skip. Регрессия-guard: после fix CP-1 эти кейсы продолжают
    # блокироваться даже если будущий rewrite нормализации изменит маппинг.
    ("gh pr comment 1 --body 'ready to merge\u00a0:landing'", 1, "CP-1: NBSP + colon terminator"),
    ("gh pr comment 1 --body 'готов к merge\u00a0：next'", 1, "CP-1: NBSP + fullwidth colon"),
    ("gh pr comment 1 --body 'ready to merge\u2003:next'", 1, "CP-1: em space + colon"),
    ("gh pr comment 1 --body 'ready to merge\u00a0after X'", 0, "CP-1 sanity: NBSP + narrative не блокирует"),
    # === Copilot round 28: zero-width char / HTML entity bypass ===
    ("gh pr comment 1 --body 'ready\u200bto merge'", 1, "zero-width space bypass"),
    ("gh pr comment 1 --body '## ✅ Готов\u200b к merge'", 1, "ZWSP in RU marker"),
    ("gh pr comment 1 --body 'ready&#x200b;to merge'", 1, "HTML entity ZWSP bypass"),
    ("gh pr comment 1 --body 'ready\ufeffto merge'", 1, "BOM char bypass"),
    # === Пропуск: обсуждения и цитаты ===
    ("gh pr comment 1 --body 'не готов к merge — тесты красные'", 0, "отрицание"),
    ("gh pr comment 1 --body 'почти готов к merge, жду review'", 0, "«почти готов» — negation wins"),
    ("gh pr comment 1 --body '## Готов к merge после исправлений'", 0, "## + продолжение без terminator"),
    # big-heroes-ase (v3.5): запятая теперь terminator. Прежние кейсы с
    # «готов к merge, если X» (ранее expected 0 как «обсуждение») переведены
    # в block: фраза с запятой неотличима от декларации с продолжением.
    # Narrative-фразы без terminator (например «готов к merge in the future»)
    # продолжают проходить — см. тесты ниже.
    ("gh pr comment 1 --body 'готов к merge, если X'", 1, "ase: запятая terminator (было 0)"),
    ("gh pr comment 1 --body '## Готов к merge, если X'", 1, "ase: ## + запятая terminator (было 0)"),
    # Narrative без terminator — не блокируется (позитивный sanity для task 3).
    ("gh pr comment 1 --body 'готов к merge in the future'", 0, "narrative без terminator"),
    ("gh pr comment 1 --body 'PR будет готов к merge после CI'", 0, "narrative с negation «будет»"),
    # === Пропуск: markdown blockquote (GPT-5.4 round 15 WARNING) ===
    ("gh pr comment 1 --body '> ready to merge'", 0, "blockquote bare EN"),
    ("gh pr comment 1 --body '> готов к merge'", 0, "blockquote bare RU"),
    ("gh pr comment 1 --body '> Вердикт: ready to merge'", 0, "blockquote с префиксом"),
    ("gh pr comment 1 --body \"> Reviewer cited: ready to merge\"", 0, "blockquote double-quote"),
    ("gh pr comment 1 --body '>> nested quote ready to merge'", 0, "nested blockquote"),
    (
        "gh pr comment 1 --body 'Контекст обсуждения\n> cited ready to merge\nпродолжение'",
        0,
        "multi-line body: blockquote строка внутри",
    ),
    # === Fail-secure ===
    (None, 1, "нет tool_input.command"),
    # === Защита от bypass ===
    ("gh\tpr\tcomment 1 --body '## ✅ Готов к merge'", 1, "tab whitespace bypass"),
    ("gh \t pr  comment 1 --body-file x.md", 1, "mixed whitespace + body-file"),
    ("gh pr comment 1 --body-file x.md", 1, "--body-file"),
    ("gh pr comment 1 -F x.md", 1, "-F"),
    ("gh pr comment 1 --body \"$(cat /tmp/x)\"", 1, "$(cat /path)"),
    ("gh pr comment 1 --body \"$(<file.md)\"", 1, "$(<file)"),
    ("gh pr comment 1 --body \"`cat /tmp/x`\"", 1, "backtick cat"),
    # Bypass через непрозрачную переменную — запрещённая фраза в $BODY,
    # hook видит только имя переменной. Основной случай Copilot round 12.
    ("gh pr comment 1 --body \"$BODY\"", 1, "--body \"$BODY\" (opaque var)"),
    ("gh pr comment 1 --body $BODY", 1, "--body $BODY без кавычек"),
    ("gh pr comment 1 --body \"${BODY}\"", 1, "--body \"${BODY}\""),
    ("gh pr comment 1 --body \"${BODY:-default}\"", 1, "--body default-expansion"),
    ("gh pr comment 1 --body=$BODY", 1, "--body=$BODY (=syntax)"),
    # === Copilot round 24: concatenation bypass — $VAR в любой позиции ===
    # Прежний regex ловил только `--body "$VAR"` (переменная в начале).
    # `--body "Prefix: $BODY"` проходил — фраза в переменной невидима hook'у.
    ("gh pr comment 1 --body \"Prefix: $BODY\"", 1, "concat: prefix + $BODY"),
    ("gh pr comment 1 --body \"Result: ${BODY}\"", 1, "concat: prefix + ${BODY}"),
    ("gh pr comment 1 --body \"## Title\n$BODY\"", 1, "concat: title + newline + $BODY"),
    ("gh pr comment 1 --body=prefix$BODY", 1, "concat: unquoted prefix$BODY"),
    # Single-quoted: $BODY — литерал, не раскрывается shell'ом, не блокируем.
    ("gh pr comment 1 --body 'Prefix: $BODY'", 0, "single-quoted $BODY — literal, pass"),
    # === Legitimate markdown ===
    ("gh pr comment 1 --body 'использует `bd show` для проверки'", 0, "inline backticks"),
    ("gh pr comment 1 --body 'regex `bd-[a-z]+` захардкожен'", 0, "markdown regex"),
    ("gh pr comment 1 --body 'пример here-string: cmd <<<\"input\" в bash'", 0, "<<< внутри body — текст"),
    # === Heredoc: содержимое видно hook'у ===
    ("gh pr comment 1 --body \"$(cat <<'EOF'\n## ✅ Готов к merge\nEOF\n)\"", 1, "heredoc final"),
    ("gh pr comment 1 --body \"$(cat <<'EOF'\nLooks good\nEOF\n)\"", 0, "heredoc clean"),
    # === Heredoc-awareness: review-pass публикация через $BODY=heredoc ===
    # Codex GPT-5.4 P1 (round 13): _OPAQUE_VAR_BODY блокировал шаблон PM-публикации
    # review-pass в sprint-pr-cycle:325 и external-review:319, делая pipeline
    # нефункциональным. Heredoc-присваивание делает содержимое видимым hook'у —
    # is_forbidden проверит фразу по raw команде.
    (
        "BODY=$(cat <<'EOF'\n## Внутреннее ревью (Claude) — review-pass\nCommit: abc123\nОтчёт по 4 аспектам.\nEOF\n)\n"
        "gh pr comment 1 --body \"$BODY\"",
        0,
        "review-pass publish (heredoc + $BODY)",
    ),
    (
        "BODY=$(cat <<'EOF'\n## Внешнее ревью (Sprint Final) — Режим: B\nCommit: abc123\nEOF\n)\n"
        "gh pr comment 1 --body \"$BODY\"",
        0,
        "external review publish (heredoc + $BODY)",
    ),
    # Даже с heredoc и $BODY — merge-ready фраза в heredoc ловится is_forbidden.
    (
        "BODY=$(cat <<'EOF'\n## ✅ Готов к merge\nEOF\n)\n"
        "gh pr comment 1 --body \"$BODY\"",
        1,
        "heredoc+$BODY с merge-ready — блокируется",
    ),
    # === Copilot round 20 CRITICAL: heredoc-lookalike bypass ===
    # Прежний _HEREDOC_PRESENT ловил любой `<<TOKEN`. Достаточно было
    # дописать `# <<EOF` в команду — hook считал heredoc присутствующим,
    # снимал opaque-body блокировку, merge-ready в $BODY проходил.
    (
        "gh pr comment 1 --body \"$BODY\" # heredoc-lookalike <<EOF",
        1,
        "bypass heredoc-lookalike в комментарии",
    ),
    (
        "gh pr comment 1 --body \"$BODY\" # harmless <<TOKEN text",
        1,
        "bypass heredoc-lookalike с TOKEN",
    ),
    (
        "FAKE=<<EOF\ngh pr comment 1 --body \"$BODY\"",
        1,
        "bypass через literal <<EOF без cat",
    ),
    # === Command substitution в --body без heredoc — block ===
    # Codex round 14 CRITICAL + D-02: bypass через $(echo $VAR), $(head/tail/sed/awk/xxd),
    # $(printf %s $VAR), $(perl/python/node -e ...) — любой инструмент кроме heredoc-cat.
    ("gh pr comment 1 --body \"$(echo $BODY)\"", 1, "$(echo $VAR) bypass"),
    ("gh pr comment 1 --body \"$(printf %s $BODY)\"", 1, "$(printf %s $VAR) bypass"),
    ("gh pr comment 1 --body \"$(head /tmp/x)\"", 1, "$(head file) bypass"),
    ("gh pr comment 1 --body \"$(tail -1 /tmp/x)\"", 1, "$(tail file) bypass"),
    ("gh pr comment 1 --body \"$(sed -n 1p /tmp/x)\"", 1, "$(sed file) bypass"),
    ("gh pr comment 1 --body \"$(awk 1 /tmp/x)\"", 1, "$(awk file) bypass"),
    ("gh pr comment 1 --body \"$(xxd /tmp/x)\"", 1, "$(xxd file) bypass"),
    ("gh pr comment 1 --body \"$(perl -e 'print qq/ready to merge/')\"", 1, "$(perl) bypass"),
    ("gh pr comment 1 --body \"$(python3 -c 'print(\"x\")')\"", 1, "$(python) bypass"),
    ("gh pr comment 1 --body=$(echo $BODY)", 1, "--body=$(echo) without quotes"),
    # === Copilot round 27: command substitution в неначальной позиции body ===
    # Прежний regex ловил только `--body "$(..."` (cmd-subst в начале).
    # `--body "Prefix $(head /tmp/x)"` проходил — содержимое скрыто от hook'а.
    ("gh pr comment 1 --body \"Prefix $(head /tmp/x)\"", 1, "cmd-subst with prefix"),
    ("gh pr comment 1 --body \"$(head /tmp/x) suffix\"", 1, "cmd-subst with suffix"),
    ("gh pr comment 1 --body \"## Title\n$(head /tmp/x)\"", 1, "cmd-subst after newline"),
    ("gh pr comment 1 --body=prefix$(echo test)", 1, "cmd-subst unquoted with prefix"),
    # Heredoc в той же команде — снимает command-subst блокировку, ТОЛЬКО если
    # heredoc-cat непосредственно в позиции --body. Посторонний heredoc для другой
    # переменной НЕ снимает блокировку (Copilot round 21 CRITICAL).
    #
    # Паттерн `--body "$(echo $BODY)"` блокируется даже при наличии heredoc для
    # BODY — $(echo ...) скрывает реальное содержимое. Легитимный способ:
    # `--body "$BODY"` (opaque-var-check проверит привязку heredoc к BODY).
    (
        "BODY=$(cat <<'EOF'\n## Clean review\nEOF\n)\n"
        "gh pr comment 1 --body \"$(echo $BODY)\"",
        1,
        "heredoc+cmd-subst: $(echo) скрывает содержимое даже с heredoc для BODY",
    ),
    (
        "BODY=$(cat <<'EOF'\n## ✅ Готов к merge\nEOF\n)\n"
        "gh pr comment 1 --body \"$(echo $BODY)\"",
        1,
        "heredoc + $(echo $BODY) с merge-ready — block (cmd-subst opaque)",
    ),
    # === Copilot round 21 CRITICAL: «посторонний» (alien) heredoc bypass ===
    # Heredoc для переменной X НЕ должен снимать opaque-блокировку для $BODY.
    (
        "X=$(cat <<'EOF'\ninnocent text\nEOF\n)\n"
        "gh pr comment 1 --body \"$BODY\"",
        1,
        "alien heredoc X= не снимает opaque-block для $BODY",
    ),
    (
        "X=$(cat <<'EOF'\ninnocent text\nEOF\n)\n"
        "gh pr comment 1 --body \"${BODY}\"",
        1,
        "alien heredoc X= не снимает opaque-block для ${BODY}",
    ),
    (
        "X=$(cat <<'EOF'\ninnocent text\nEOF\n)\n"
        "gh pr comment 1 --body \"$(echo $BODY)\"",
        1,
        "alien heredoc X= не снимает cmd-subst block",
    ),
    # Правильная привязка: heredoc для BODY + --body "$BODY" — ОК.
    (
        "BODY=$(cat <<'EOF'\n## Clean review\nEOF\n)\n"
        "gh pr comment 1 --body \"$BODY\"",
        0,
        "heredoc BODY= + --body $BODY — привязка корректна, pass",
    ),
    # === Copilot round 31 CRITICAL: editor-mode bypass ===
    # `gh pr comment <N>` без --body / -b / --body-file / -F → gh открывает
    # интерактивный редактор, содержимое вводится вне строки команды и
    # скрыто от hook'а. Это реальный bypass hard gate.
    ("gh pr comment 1", 1, "bypass editor mode: без --body"),
    ("gh pr comment 42 --repo x/y", 1, "bypass editor mode: без --body (с --repo)"),
    # `--edit-last` редактирует последний комментарий через редактор,
    # содержимое тоже скрыто от hook'а.
    ("gh pr comment 1 --edit-last", 1, "bypass --edit-last без body"),
    ("gh pr comment 1 --edit-last --body '## ok'", 1, "bypass --edit-last даже с --body (редактор всё равно откроется)"),
    # -b как короткий вариант --body — содержимое видно, пропуск.
    ("gh pr comment 1 -b 'normal comment'", 0, "-b короткая форма --body"),
    ("gh pr comment 1 -b '## ready to merge'", 1, "-b с запрещённой фразой блокируется"),
    # Round 33 CRITICAL: -b с opaque-переменными и command substitution.
    # Раньше 4 regex хардкодили --body, -b проходила без проверки.
    ('gh pr comment 1 -b "$BODY"', 1, "-b с opaque var $BODY блокируется"),
    ('gh pr comment 1 -b "${BODY}"', 1, "-b с opaque var ${BODY} блокируется"),
    ('gh pr comment 1 -b "$(head /tmp/x)"', 1, "-b с cmd-subst $(head) блокируется"),
    ('gh pr comment 1 -b "$(echo $BODY)"', 1, "-b с cmd-subst $(echo $VAR) блокируется"),
    ('gh pr comment 1 -b "Prefix $BODY"', 1, "-b с concat prefix+$BODY блокируется"),
    # === Pass 4 E-1 WARNING: opening punctuation false positive ===
    # GPT-5.4 + GPT-5.3-Codex Pass 3: systemic startswith('P') блокировал
    # Ps (Open) и Pi (Initial quote) — но `(`, `[`, `{`, «, ' — это
    # openers clauses / subordinate, а не sentence terminators.
    # Bypass workflow: `ready to merge (if CI passes)` ложно блок'ался.
    # Fix: class = Po ∪ Pf (Other punct + Final quote) — минимальная
    # семантически-корректная terminator-класс.
    ("gh pr comment 1 --body 'ready to merge (if CI passes)'", 0, "E-1: open paren = narrative continuation"),
    ("gh pr comment 1 --body 'ready to merge [tracking issue]'", 0, "E-1: open bracket = narrative"),
    ("gh pr comment 1 --body 'ready to merge {if deps resolve}'", 0, "E-1: open brace = narrative"),
    ("gh pr comment 1 --body 'готов к merge «после review»'", 0, "E-1: initial quote « = narrative"),
    ("gh pr comment 1 --body 'ready to merge \u2018after X\u2019'", 0, "E-1: initial single quote U+2018 = narrative"),
    # E-1 regression: real terminators продолжают block.
    ("gh pr comment 1 --body 'ready to merge.'", 1, "E-1 regression: period still block"),
    ("gh pr comment 1 --body 'ready to merge。'", 1, "E-1 regression: CJK period block"),
    ("gh pr comment 1 --body 'ready to merge!'", 1, "E-1 regression: bang block"),
    ("gh pr comment 1 --body 'ready to merge: next'", 1, "E-1 regression: colon (Po) still block"),
    # E-1 Pf sanity: closing quote — terminator (Final quote category Pf).
    ("gh pr comment 1 --body 'ready to merge\u201d next'", 1, "E-1: closing Pf quote U+201D = terminator"),
    ("gh pr comment 1 --body 'ready to merge» next'", 1, "E-1: closing Pf quillemet » = terminator"),
    # === Pass 5 E-5 WARNING: backtick (Sk) в skip-loop — удалить Sk ===
    # Developer Pass 2 добавил Sk/Lm в skip-set для G2 combining diacritic
    # U+00B4 (ACUTE ACCENT, Sk). Но backtick U+0060 — тоже Sk: skip-loop
    # проглатывал closing backtick после phrase в легитимных inline code
    # span командах, затем встречал shell-quote и ложно считал её
    # terminator-ом. Bypass legitimate workflow:
    # `gh pr comment 1 --body 'Use \`ready to merge\`'` ложно блокировался.
    # Fix: убрать Sk/Lm из skip-set. G2 остаётся закрытым через NFKD
    # normalization — combining marks разносятся, Mn/Mc/Me strip'аются.
    ("gh pr comment 1 --body 'Use `ready to merge`'", 0, "E-5: quoted inline code passes"),
    ("gh pr comment 1 --body 'Example: `готов к merge` phrase'", 0, "E-5: RU quoted inline code"),
    ("gh pr comment 1 --body 'Here is `merge ready` in docs'", 0, "E-5: bare phrase in inline code"),
    # E-5 regression: G2 combining diacritic still blocks via NFKD decomposition
    # (не через Sk skip). U+00B4 acute accent под NFKD → U+0020 + U+0301 →
    # space+combining → strip Mn → clean phrase. Terminator-check видит `:`.
    ("gh pr comment 1 --body 'ready to merg\u00e9:landing'", 1, "E-5 regression: precomposed é NFKD decomposes"),
    ("gh pr comment 1 --body 'ready to merge\u0301:landing'", 1, "E-5 regression: combining acute U+0301 still block"),
    ("gh pr comment 1 --body 'ready to merge\u00b4:landing'", 1, "E-5 regression: acute accent Sk via NFKD path"),
    # === v3.5 Option B revert: Pe (close) / Pd (dash) удалены из terminator class ===
    # Pass 6 E-7 расширил terminator class до Po+Pf+Pe+Pd. Pe/Pd overmatch
    # открыл surface overmatch: `/`/`.` в paths/branches (big-heroes-3ed, E-15)
    # и `:` в backtick-quoted inline code (big-heroes-16e, E-14). Каждый
    # tactical fix Pe/Pd overmatch вскрывал новые findings — overfitting cycle.
    # Option B (big-heroes-nw5): вернули Po+Pf (Pass 4 E-1 baseline, proven
    # minimum). Systemic Python rewrite — big-heroes-55m (v3.6 sprint-opener),
    # big-heroes-ytx (Po overmatch).
    #
    # Sanity: после revert `(ready to merge)` и `ready to merge — landing`
    # больше НЕ блокируются (narrative) — known limitation v3.5.
    # Deferred coverage — big-heroes-ytx (v3.6 Python rewrite).
    ("gh pr comment 1 --body '(ready to merge)'", 0, "Option B revert: Pe close paren — narrative (deferred big-heroes-ytx v3.6)"),
    ("gh pr comment 1 --body 'ready to merge — landing'", 0, "Option B revert: Pd em-dash — narrative (deferred big-heroes-ytx v3.6)"),
    # E-1 regression (Po+Pf baseline): open-punct (Ps) / initial quote (Pi)
    # продолжают рассматриваться как narrative.
    ("gh pr comment 1 --body 'ready to merge (if CI passes)'", 0, "E-1 baseline: narrative open paren (Ps)"),
    ("gh pr comment 1 --body 'ready to merge [tracking]'", 0, "E-1 baseline: narrative open bracket (Ps)"),
]


def main() -> int:
    failures = []
    for cmd, expected, description in TESTS:
        actual = run(cmd)
        mark = "✓" if actual == expected else "✗"
        print(f"{mark} {description}: exit={actual} expected={expected}")
        if actual != expected:
            failures.append(description)

    # FINALIZE_PR_TOKEN bypass — даже точный маркер проходит
    token_cmd = "gh pr comment 1 --body '## ✅ Готов к merge'"
    actual = run(token_cmd, with_token=True)
    mark = "✓" if actual == 0 else "✗"
    print(f"{mark} FINALIZE_PR_TOKEN bypass: exit={actual} expected=0")
    if actual != 0:
        failures.append("FINALIZE_PR_TOKEN bypass")

    total = len(TESTS) + 1
    passed = total - len(failures)
    print(f"\nИтого: {passed}/{total}")
    if failures:
        print("Провалены:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
