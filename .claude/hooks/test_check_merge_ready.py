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
EXIT_BLOCK = 2


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
    # Task 0 regression: matcher вызывает hook для любой Bash-команды, но
    # readiness проверяется только в body доказанной публикации.
    ("printf '%s' 'PR ready to merge: final'", 0, "не-gh readiness-текст проходит"),
    # Инцидент передачи #645 §5: с матчером по имени инструмента is_forbidden
    # не должен судить произвольные Bash-команды с фразой — только body публикации.
    (
        'git commit -m "PR готов к merge"',
        0,
        "git commit с readiness-фразой в сообщении не блокируется",
    ),
    (
        "printf '%s' \"gh pr comment 1 --body 'PR ready to merge: final'\"",
        0,
        "цитируемый пример gh pr comment не является публикацией",
    ),
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
    ("gh pr comment 1 --body 'ready to merge\u00a0after X'", 1, "CP-1: NBSP + продолжение направлением — декларация"),
    # === Copilot round 28: zero-width char / HTML entity bypass ===
    ("gh pr comment 1 --body 'ready\u200bto merge'", 1, "zero-width space bypass"),
    ("gh pr comment 1 --body '## ✅ Готов\u200b к merge'", 1, "ZWSP in RU marker"),
    ("gh pr comment 1 --body 'ready&#x200b;to merge'", 1, "HTML entity ZWSP bypass"),
    ("gh pr comment 1 --body 'ready\ufeffto merge'", 1, "BOM char bypass"),
    # === Пропуск: обсуждения и цитаты ===
    ("gh pr comment 1 --body 'не готов к merge — тесты красные'", 0, "отрицание"),
    ("gh pr comment 1 --body 'почти готов к merge, жду review'", 0, "«почти готов» — negation wins"),
    (
        "gh pr comment 1 --body 'Not ready to merge; ready to merge.'",
        1,
        "отрицание действует только внутри своей клаузы",
    ),
    (
        "gh pr comment 1 --body 'Not ready to merge but ready to merge.'",
        1,
        "EN: adversative conjunction starts a new readiness clause",
    ),
    (
        "gh pr comment 1 --body 'NOT ready to merge\tBUT   READY to merge.'",
        1,
        "EN: conjunction boundary is case/whitespace insensitive",
    ),
    (
        "gh pr comment 1 --body 'Not ready to merge however ready to merge.'",
        1,
        "EN: conjunctive adverb starts a new readiness clause",
    ),
    (
        "gh pr comment 1 --body 'Not ready to merge and ready to merge.'",
        1,
        "EN: coordinating conjunction starts a new readiness clause",
    ),
    (
        "gh pr comment 1 --body 'Not ready to merge or ready to merge.'",
        1,
        "EN: alternative conjunction starts a new readiness clause",
    ),
    (
        "gh pr comment 1 --body 'Not ready to merge yet ready to merge.'",
        1,
        "EN: repeated readiness candidate bounds negation without conjunction allowlist",
    ),
    (
        "gh pr comment 1 --body 'Not ready to merge though ready to merge.'",
        1,
        "EN: unknown conjunction cannot extend negation across readiness candidates",
    ),
    (
        "gh pr comment 1 --body 'Not ready to merge — ready to merge.'",
        1,
        "EN: dash separates repeated readiness declarations",
    ),
    (
        "gh pr comment 1 --body 'Не готов к merge но готов к merge.'",
        1,
        "RU: противительный союз начинает новую клаузу readiness",
    ),
    (
        "gh pr comment 1 --body 'НЕ готов к merge\tНО   ГОТОВ к merge.'",
        1,
        "RU: граница союза не зависит от регистра/пробелов",
    ),
    (
        "gh pr comment 1 --body 'Не готов к merge однако готов к merge.'",
        1,
        "RU: противительное наречие начинает новую клаузу",
    ),
    (
        "gh pr comment 1 --body 'Не готов к merge и готов к merge.'",
        1,
        "RU: сочинительный союз начинает новую клаузу",
    ),
    (
        "gh pr comment 1 --body 'Не готов к merge всё же готов к merge.'",
        1,
        "RU: repeated readiness candidate bounds negation without adverb allowlist",
    ),
    (
        "gh pr comment 1 --body 'Не готов к merge всё-таки готов к merge.'",
        1,
        "RU: hyphenated unknown adverb cannot extend negation",
    ),
    (
        "gh pr comment 1 --body 'Не готов к merge — готов к merge.'",
        1,
        "RU: dash separates repeated readiness declarations",
    ),
    (
        "gh pr comment 1 --body 'Not ready to merge but almost ready to merge.'",
        0,
        "EN: отрицание внутри новой клаузы сохраняется",
    ),
    (
        "gh pr comment 1 --body 'Не готов к merge но почти готов к merge.'",
        0,
        "RU: отрицание внутри новой клаузы сохраняется",
    ),
    ("gh pr comment 1 --body '## Готов к merge после исправлений'", 1, "## + продолжение направлением — декларация"),
    # big-heroes-ase (v3.5): запятая теперь terminator. Прежние кейсы с
    # «готов к merge, если X» (ранее expected 0 как «обсуждение») переведены
    # в block: фраза с запятой неотличима от декларации с продолжением.
    # Narrative-фразы без terminator (например «готов к merge in the future»)
    # продолжают проходить — см. тесты ниже.
    ("gh pr comment 1 --body 'готов к merge, если X'", 1, "ase: запятая terminator (было 0)"),
    ("gh pr comment 1 --body '## Готов к merge, если X'", 1, "ase: ## + запятая terminator (было 0)"),
    # Narrative без terminator — не блокируется (позитивный sanity для task 3).
    ("gh pr comment 1 --body 'готов к merge in the future'", 1, "продолжение направлением — декларация (safe side)"),
    ("gh pr comment 1 --body 'PR будет готов к merge после CI'", 0, "narrative с negation «будет»"),
    (
        "gh pr comment 1 --body \"body='> ready to merge'\"",
        1,
        "raw body с shell-like prefix не является markdown blockquote",
    ),
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
    (
        "printf '%s' \"`gh pr comment 1 --body 'neutral text'`\"",
        1,
        "active backtick publication is ambiguous",
    ),
    (
        "printf '%s' \"$(gh pr comment 1 --body 'neutral text')\"",
        1,
        "active nested publication is ambiguous",
    ),
    # Command words are compared after shell quote/escape removal.
    (
        "g''h p\"r\" c'omment' 1 --body 'ready to merge'",
        1,
        "adjacent quoted command segments reconstruct gh pr comment",
    ),
    (
        r"g\h p\r com\ment 1 --body 'ready to merge'",
        1,
        "escaped command letters reconstruct gh pr comment",
    ),
    (
        "g\\\nh pr comment 1 --body 'ready to merge'",
        1,
        "continued command word reconstructs gh pr comment",
    ),
    # Execution prefixes остаются частью того же stateful-разбора: parser
    # должен найти фактически запускаемый executable, не сканируя обычные
    # аргументы как независимые команды.
    (
        "command gh pr comment 1 --body 'ready to merge'",
        1,
        "command modifier preserves publication candidate",
    ),
    (
        "command printf '%s' 'gh pr comment is documentation'",
        0,
        "neutral command modifier arguments do not become candidates",
    ),
    (
        "command {output_fd}>/dev/null gh pr comment 1 --body 'ready to merge'",
        1,
        "brace-named FD redirect preserves execution after modifier",
    ),
    (
        "command {output_fd}>/dev/null printf '%s' 'gh pr comment is documentation'",
        0,
        "neutral brace-named FD redirect remains allowed",
    ),
    (
        "/usr/bin/gh pr comment 1 --body 'ready to merge'",
        1,
        "literal executable path preserves publication candidate",
    ),
    (
        "gh.exe pr comment 1 --body 'ready to merge'",
        1,
        "Windows executable suffix preserves publication candidate",
    ),
    (
        "/mingw64/bin/GH.EXE pr comment 1 --body 'ready to merge'",
        1,
        "Windows executable suffix is case-insensitive",
    ),
    (
        "GH pr comment 1 --body 'ready to merge'",
        1,
        "Windows extensionless executable name is case-insensitive",
    ),
    (
        "gh.exe pr comment 1 --body-file report.md",
        1,
        "Windows executable suffix cannot bypass opaque body gate",
    ),
    (
        "gh.exe pr comment 1 --body 'Neutral review report.'",
        0,
        "Windows executable suffix preserves neutral publication",
    ),
    (
        "gh pr comment 1 --body 'Neutral review report.' || true",
        1,
        "masked publication status is not accepted as proven success",
    ),
    (
        "gh --repo=owner/repo pr comment 645 --body 'PR is ready to merge.'",
        1,
        "attached --repo=value before pr cannot bypass readiness gate",
    ),
    (
        "gh -Rowner/repo pr comment 645 --body 'PR is ready to merge.'",
        1,
        "attached -Rvalue before pr cannot bypass readiness gate",
    ),
    (
        "gh -R=owner/repo pr --repo=owner/repo comment 645 --body 'PR is ready to merge.'",
        1,
        "repeated attached repo options around pr cannot bypass readiness gate",
    ),
    (
        "gh --repo=owner/repo pr comment 645 --body 'Neutral review report.'",
        0,
        "attached repo option preserves neutral publication",
    ),
    (
        "opaque-runner --payload \"gh --repo=owner/repo pr comment 645 --body 'ready to merge.'\"",
        1,
        "attached repo option remains visible inside literal carrier payload",
    ),
    (
        "/usr/bin/printf '%s' 'gh pr comment is documentation'",
        0,
        "neutral executable path arguments do not become candidates",
    ),
    (
        "</dev/null gh pr comment 1 --body 'ready to merge'",
        1,
        "leading redirect preserves publication candidate",
    ),
    (
        "</dev/null printf '%s' 'gh pr comment is documentation'",
        0,
        "neutral leading redirect arguments do not become candidates",
    ),
    (
        "<<'INPUT' gh pr comment 1 --body 'ready to merge'\n"
        "neutral input\n"
        "INPUT\n",
        1,
        "leading heredoc redirect preserves publication candidate",
    ),
    (
        "bash -c \"gh pr comment 1 --body 'ready to merge'\"",
        1,
        "literal shell payload is analyzed recursively",
    ),
    (
        "bash -c \"printf '%s' 'gh pr comment is documentation'\"",
        0,
        "neutral literal shell payload remains allowed",
    ),
    (
        "bash --norc -c \"gh pr comment 1 --body 'ready to merge'\"",
        1,
        "literal shell payload survives known wrapper options",
    ),
    (
        "bash --norc -c \"printf '%s' 'gh pr comment is documentation'\"",
        0,
        "neutral shell payload with wrapper options remains allowed",
    ),
    (
        'bash -c "$SHELL_PAYLOAD"',
        1,
        "opaque shell payload is candidate-scoped ambiguous",
    ),
    (
        "if true; then gh pr comment 1 --body 'ready to merge'; fi",
        1,
        "inline control segment preserves publication candidate",
    ),
    (
        "if true; then printf '%s' 'gh pr comment is documentation'; fi",
        0,
        "neutral inline control segment remains allowed",
    ),
    (
        "publish(){ gh pr comment 1 --body 'ready to merge'; }",
        1,
        "inline function group preserves publication candidate",
    ),
    (
        "publish(){ printf '%s' 'gh pr comment is documentation'; }",
        0,
        "neutral inline function group remains allowed",
    ),
    (
        "case x in x) gh pr comment 1 --body 'ready to merge';; esac",
        1,
        "inline case branch preserves publication candidate",
    ),
    (
        "case x in x) printf '%s' 'gh pr comment is documentation';; esac",
        0,
        "neutral inline case branch remains allowed",
    ),
    (
        "! gh pr comment 1 --body 'ready to merge'",
        1,
        "negated control prefix preserves publication candidate",
    ),
    (
        "! gh pr comment 1 --body 'Neutral review report.'",
        1,
        "negated publication status is not accepted as proven success",
    ),
    (
        "gh pr comment 1 --body 'Neutral review report.' &",
        1,
        "background publication status is not accepted as proven success",
    ),
    (
        "! printf '%s' 'gh pr comment is documentation'",
        0,
        "neutral negated command remains allowed",
    ),
    (
        "env -S \"gh pr comment 1 --body 'ready to merge'\"",
        1,
        "env literal split-string payload is analyzed recursively",
    ),
    (
        "env -S \"printf '%s' 'gh pr comment is documentation'\"",
        0,
        "neutral env split-string payload remains allowed",
    ),
    (
        'env -S "$ENV_SPLIT_PAYLOAD"',
        1,
        "opaque env split-string payload is candidate-scoped ambiguous",
    ),
    # === Уровень 1: остаток argv после env split-string разбирается ===
    # env -S <строка> исполняет split(строка) + оставшиеся argv как команду
    # целиком. Публикация в хвосте argv обязана распознаваться, а не теряться.
    (
        "env -S gh pr comment 645 --body 'ready to merge'",
        1,
        "публикация в хвосте argv после env -S распознаётся",
    ),
    (
        "env --split-string=gh pr comment 645 --body 'ready to merge'",
        1,
        "публикация после --split-string=gh распознаётся",
    ),
    (
        "env -S 'gh pr' comment 645 --body 'ready to merge'",
        1,
        "публикация из частичной split-string плюс хвост распознаётся",
    ),
    # Нейтральный split-string остаётся разрешённым (payload — data-команда).
    (
        "env -S 'printf %s' 'gh pr comment is documentation'",
        0,
        "нейтральный env split-string с хвостом-данными проходит",
    ),
    # === Уровень 1: доверенная привязка сведена к shell-грамматике ===
    # `BODY =value` (с пробелом) в bash НЕ присваивание, прежнее значение
    # остаётся; такая запись не даёт доверенной heredoc-привязки, и body
    # переменной остаётся непрозрачным → блок.
    (
        "BODY='ready to merge'; BODY =$(cat <<'TOK'\nsafe\nTOK\n); "
        "gh pr comment 645 --body \"$BODY\"",
        1,
        "пробел вокруг = не создаёт доверенную привязку",
    ),
    # Настоящее присваивание (без пробела) heredoc-привязку сохраняет.
    (
        "BODY=$(cat <<'TOK'\nОбычный безопасный отчёт\nTOK\n)\n"
        "gh pr comment 645 --body \"$BODY\"",
        0,
        "смежное NAME=value сохраняет доверенную heredoc-привязку",
    ),
    # === Уровень 2: запасной вердикт по литералу в активном коде ===
    # Литерал `gh … pr … comment` целиком в активном top-level коде, для
    # которого структурный разбор не дал доказанной публикации, эскалируется в
    # ambiguous (fail-closed блок) — страховка от будущих расхождений с shell.
    # data-команда со своими argv структурной публикации не даёт (scan пропущен),
    # поэтому здесь работает именно запасной вердикт по активному литералу.
    (
        "echo gh pr comment 645 --body 'ready to merge'",
        1,
        "активный литерал без доказанной публикации блокируется страховкой",
    ),
    (
        "future-exec-runner gh pr comment 645 --body 'ready to merge'",
        1,
        "литерал в активном коде неизвестного carrier блокируется",
    ),
    # Цитаты литерала доказательно инертны и НЕ эскалируются.
    (
        "printf '%s' 'gh pr comment 1 --body ready to merge'",
        0,
        "литерал в одинарных кавычках инертен",
    ),
    (
        "echo ok # gh pr comment 1 --body ready to merge",
        0,
        "литерал в комментарии инертен",
    ),
    (
        "cat <<'EOF'\ngh pr comment 1 --body ready to merge\nEOF",
        0,
        "литерал в quoted heredoc инертен",
    ),
    (
        "opaque-runner --payload \"gh pr comment 1 --body 'ready to merge'\"",
        1,
        "unknown execution carrier with literal publication is fail-closed",
    ),
    (
        "eval \"gh pr comment 1 --body 'ready to merge'\"",
        1,
        "shell builtin carrier is covered by the generic ambiguity boundary",
    ),
    (
        "xargs sh -c \"gh pr comment 1 --body 'ready to merge'\"",
        1,
        "multi-command carrier is covered by the generic ambiguity boundary",
    ),
    (
        "bash -O extglob -c \"gh pr comment 1 --body 'ready to merge'\"",
        1,
        "shell option operand preserves following literal payload",
    ),
    (
        "bash -O extglob -c \"printf '%s' 'gh pr comment is documentation'\"",
        0,
        "neutral shell option operand payload remains allowed",
    ),
    (
        'bash "$SHELL_OPTION" -c "printf neutral"',
        1,
        "opaque shell wrapper option is candidate-scoped ambiguous",
    ),
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
    (
        "gh pr comment 1 --body re'ady to 'merge",
        1,
        "compound shell word is outside the proven body subset",
    ),
    (
        "gh pr comment 1 --body 'rea''dy to merge'",
        1,
        "adjacent single-quoted body segments use their shell value",
    ),
    (
        'gh pr comment 1 --body "rea""dy to merge"',
        1,
        "adjacent double-quoted body segments use their shell value",
    ),
    (
        'gh pr comment 1 --body "ready to \\\nmerge"',
        1,
        "continued double-quoted body uses its shell value",
    ),
    (
        "gh pr comment 1 --body 'neutral' --body \"$BODY\"",
        1,
        "multiple body sources are ambiguous",
    ),
    (
        "gh pr comment 1 --body neutral*pattern",
        1,
        "unquoted globbing is not a literal body",
    ),
    # Ambiguity is candidate-scoped: unrelated shell syntax is not a reason to
    # block a Bash invocation that contains no real or suspected publication.
    ("printf '%s' \"`date`\"", 0, "neutral active backticks pass"),
    (
        "helper() {\nprintf '%s' neutral\n}",
        0,
        "neutral function body passes",
    ),
    ("value=$((1 + 2))", 0, "neutral arithmetic expansion passes"),
    # === Раскрываемое (unquoted) тело heredoc: подстановки исполняются ===
    # Гейт распознаёт публикацию в $()/backtick/арифметике тела heredoc с
    # unquoted-делимитером как opaque-контекст (candidate-ambiguous → блок).
    (
        "cat <<EOF\n$(gh pr comment 1 --body 'ready to merge')\nEOF",
        1,
        "публикация в теле unquoted heredoc распознаётся",
    ),
    (
        "cat <<EOF\n`gh pr comment 1 --body 'ready to merge'`\nEOF",
        1,
        "backtick-публикация в теле unquoted heredoc распознаётся",
    ),
    (
        "cat <<EOF\n$(( $(gh pr comment 1 --body 'ready to merge') ))\nEOF",
        1,
        "публикация в арифметике внутри тела unquoted heredoc распознаётся",
    ),
    # Тело heredoc с quoted-делимитером раскрытия не имеет и остаётся инертным.
    (
        "cat <<'EOF'\n$(gh pr comment 1 --body 'ready to merge')\nEOF",
        0,
        "quoted heredoc остаётся инертным (нет раскрытия)",
    ),
    # Обычный текст в теле unquoted heredoc публикацией не становится.
    (
        "cat <<EOF\nобычный текст без подстановок\nEOF",
        0,
        "нейтральное тело unquoted heredoc проходит",
    ),
    # === Записи, начинающиеся с `$((`, разбираются общей веткой `$(` ===
    # `$((` начинается с тех же символов, что `$(`. Когда содержимое не является
    # арифметическим выражением, shell исполняет запись как подстановку команды,
    # поэтому её тело целиком идёт в opaque-контекст и осматривается fail-closed.
    # Спец-маршрута у `$((` нет — иначе тело выпадало бы из анализа.
    (
        "echo \"$((gh pr comment 1 --body 'ready to merge') )\"",
        1,
        "кандидат в теле записи $((...) ) распознаётся",
    ),
    (
        "echo \"$((cd /tmp) && gh pr comment 1 --body 'ready to merge')\"",
        1,
        "кандидат в теле записи $((...) && ...) распознаётся",
    ),
    (
        "cat <<EOF\n$((gh pr comment 1 --body 'ready to merge') )\nEOF",
        1,
        "кандидат в записи $((...) ) внутри тела unquoted heredoc распознаётся",
    ),
    (
        "cat <<EOF\n$((cd /tmp) && gh pr comment 1 --body 'ready to merge')\nEOF",
        1,
        "кандидат в записи $((...) && ...) внутри unquoted heredoc распознаётся",
    ),
    (
        "echo \"$(( $(gh pr comment 1 --body 'ready to merge') ))\"",
        1,
        "вложенная подстановка внутри арифметики распознаётся",
    ),
    # Вложенная группа `( ... )` — часть тела подстановки, а не её конец: остаток
    # тела за группой обязан оставаться под анализом.
    (
        "echo \"$( (cd /tmp) && gh pr comment 1 --body 'ready to merge' )\"",
        1,
        "кандидат за вложенной группой внутри подстановки распознаётся",
    ),
    # Настоящая арифметика без команды в теле публикацией не становится.
    ("N=$(( (A + B) * 2 ))", 0, "арифметика со вложенными скобками проходит"),
    ("echo \"$(( COUNT + 1 ))\"", 0, "нейтральная арифметика в аргументе проходит"),
    ("echo \"$( (cd /tmp) && ls )\"", 0, "нейтральная группа в подстановке проходит"),
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
    # Доверие определяется последней привязкой до вызова, а не историей имени.
    (
        "BODY=$(cat <<'EOF'\n## Initial review\nEOF\n)\n"
        "BODY='updated review'\n"
        "gh pr comment 1 --body \"$BODY\"",
        2,
        "последняя привязка BODY не heredoc — переменная непрозрачна",
    ),
    (
        "BODY=$(cat <<'FIRST'\n## First review\nFIRST\n)\n"
        "gh pr comment 1 --body \"$BODY\"\n"
        "BODY=$(cat <<'SECOND'\n## Second review\nSECOND\n)\n"
        "gh pr comment 2 --body \"$BODY\"",
        1,
        "несколько публикаций не маскируют статус первой успешным хвостом",
    ),
    (
        "BODY=$(cat <<'FIRST'\n## First review\nFIRST\n)\n"
        "gh pr comment 1 --body \"$BODY\"\n"
        "BODY='updated review'\n"
        "gh pr comment 2 --body \"$BODY\"",
        2,
        "доверенная привязка первого вызова не разрешает непрозрачный второй",
    ),
    (
        "BODY='initial review'\n"
        "gh pr comment 1 --body \"$BODY\"\n"
        "BODY=$(cat <<'SECOND'\n## Second review\nSECOND\n)\n"
        "gh pr comment 2 --body \"$BODY\"",
        2,
        "поздняя доверенная привязка не разрешает непрозрачный первый вызов",
    ),
    # Доверенная привязка существует только в прямолинейной исполняемой
    # последовательности. Литеральные области и неоднозначная достижимость не
    # устанавливают доказуемого итогового значения переменной.
    (
        "NOTE='neutral literal\n"
        "BODY=$(cat <<'INNER'\n## Literal example\nINNER\n)\n"
        "'\n"
        "gh pr comment 1 --body \"$BODY\"",
        2,
        "heredoc-привязка внутри литеральной области не получает доверия",
    ),
    (
        "if test -n \"$OPTIONAL_INPUT\"; then\n"
        "BODY=$(cat <<'TOK'\n## Conditional review\nTOK\n)\n"
        "fi\n"
        "gh pr comment 1 --body \"$BODY\"",
        2,
        "условная привязка не доказывает итоговое значение после ветвления",
    ),
    (
        "if test -n \"$OPTIONAL_INPUT\"; then\n"
        "gh pr comment 1 --body 'Neutral review'\n"
        "fi",
        2,
        "условная публикация с literal body блокируется fail-closed",
    ),
    (
        "BODY=$(cat <<'TOK'\n## Initial review\nTOK\n)\n"
        "unset BODY\n"
        "gh pr comment 1 --body \"$BODY\"",
        2,
        "изменение через shell-механизм отзывает доверие к привязке",
    ),
    # Текст тела не является shell-кодом: похожий на body-флаг маркер внутри
    # literal heredoc не должен участвовать в анализе команды.
    (
        "gh pr comment 1 --body \"$(cat <<'TOK'\n"
        "Neutral documentation marker: --body \\\"$PLACEHOLDER\\\"\n"
        "TOK\n)\"",
        0,
        "body-флаг внутри literal heredoc не считается флагом команды",
    ),
    (
        "gh pr comment 1\n"
        "gh pr comment 2 --body 'Neutral review'",
        2,
        "каждая из нескольких публикаций обязана иметь доказуемое body",
    ),
    # Лексическое состояние переносится между физическими строками. Похожая
    # на привязку последовательность внутри открытой double quote не является
    # shell-присваиванием и не задаёт итоговое значение BODY.
    (
        "NOTE=\"neutral literal\n"
        "BODY=$(cat <<'INNER'\n## Literal example\nINNER\n)\n"
        "#\"\n"
        "gh pr comment 1 --body \"$BODY\"",
        2,
        "многострочная quote не превращает текстовую привязку в top-level assignment",
    ),
    # Heredoc introducer распознаётся только в активном shell-контексте. Текст
    # внутри quote не может скрыть следующую реальную публикацию.
    (
        "NOTE=\"neutral literal\n"
        "<<'MASK'\n"
        "\"\n"
        "gh pr comment 1\n"
        "MASK",
        2,
        "heredoc-подобный текст внутри quote не маскирует реальный вызов",
    ),
    # Завершённый direct heredoc остаётся распознаваемым, но несколько публикаций
    # в одном Bash-вызове не дают PostToolUse доказать успех каждой отдельно.
    (
        "gh pr comment 1 --body \"$(cat <<'ONE'\n## First review\nONE\n)\"\n"
        "gh pr comment 2 --body \"$(cat <<'TWO'\n## Second review\nTWO\n)\"",
        1,
        "два direct heredoc-вызова не скрывают статус первого",
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
    ("gh pr comment 1 -b'normal comment'", 0, "-bVALUE attached: безопасное body проходит"),
    ("gh pr comment 1 -b'## ready to merge'", 1, "-bVALUE attached: запрещённое body блокируется"),
    ("gh pr comment 1 -b='normal comment'", 0, "-b=VALUE attached: безопасное body проходит"),
    ("gh pr comment 1 -b='## ready to merge'", 1, "-b=VALUE attached: запрещённое body блокируется"),
    (
        "gh pr comment 1 --body '## ready to merge' -b'normal comment'",
        0,
        "повторённый mixed body: фактическое последнее безопасное значение проходит",
    ),
    (
        "gh pr comment 1 -b'normal comment' --body='## ready to merge'",
        1,
        "повторённый mixed body: фактическое последнее запрещённое значение блокируется",
    ),
    (
        "gh -Rowner/repo pr -R=owner/repo comment 1 -b'normal comment'",
        0,
        "соседняя attached -RVALUE грамматика сохраняет attached body",
    ),
    ("gh pr comment 1 -Freport.md", 1, "соседняя -FVALUE форма остаётся fail-closed"),
    # Round 33 CRITICAL: -b с opaque-переменными и command substitution.
    # Раньше 4 regex хардкодили --body, -b проходила без проверки.
    ('gh pr comment 1 -b "$BODY"', 1, "-b с opaque var $BODY блокируется"),
    ('gh pr comment 1 -b "${BODY}"', 1, "-b с opaque var ${BODY} блокируется"),
    ('gh pr comment 1 -b "$(head /tmp/x)"', 1, "-b с cmd-subst $(head) блокируется"),
    ('gh pr comment 1 -b "$(echo $BODY)"', 1, "-b с cmd-subst $(echo $VAR) блокируется"),
    ('gh pr comment 1 -b "Prefix $BODY"', 1, "-b с concat prefix+$BODY блокируется"),
    # === Граница декларации: пересмотр после находки «терминатор слишком узок» ===
    # История: класс терминаторов сводили к Po ∪ Pf, чтобы «ready to merge
    # (if CI passes)» читалось как повествование. Плата вскрылась состязательным
    # внутренним ревью на 28face47: ЛЮБОЙ иной знак снимал срабатывание, и
    # принятый в проекте стиль заголовка — с галочкой, тире, скобкой, эмодзи,
    # вертикальной чертой таблицы — проходил гейт. На это напарывался честный
    # агент, оформляя обычный отчёт, раньше недобросовестного.
    #
    # Разделить два множества нельзя: «(проход 3)» и «(if CI passes)» отличаются
    # смыслом, а не знаком. Выбрана безопасная сторона: декларацию завершает
    # всё, что не буква и не цифра; продолжение СЛОВОМ («ready to merge branch
    # main») декларацией по-прежнему не считается. Лишняя блокировка дешевле
    # пропуска: у формулировки есть штатный маршрут (/finalize-pr), у пропуска —
    # нет.
    ("gh pr comment 1 --body 'ready to merge (if CI passes)'", 1, "граница: открывающая круглая скобка завершает декларацию"),
    ("gh pr comment 1 --body 'ready to merge [tracking issue]'", 1, "граница: открывающая квадратная скобка завершает"),
    ("gh pr comment 1 --body 'ready to merge {if deps resolve}'", 1, "граница: открывающая фигурная скобка завершает"),
    ("gh pr comment 1 --body 'готов к merge «после review»'", 1, "граница: открывающая кавычка завершает"),
    ("gh pr comment 1 --body 'ready to merge \u2018after X\u2019'", 1, "граница: открывающая одинарная кавычка завершает"),
    # E-1 regression: real terminators продолжают block.
    ("gh pr comment 1 --body 'ready to merge.'", 1, "E-1 regression: period still block"),
    ("gh pr comment 1 --body 'ready to merge。'", 1, "E-1 regression: CJK period block"),
    ("gh pr comment 1 --body 'ready to merge!'", 1, "E-1 regression: bang block"),
    ("gh pr comment 1 --body 'ready to merge: next'", 1, "E-1 regression: colon (Po) still block"),
    # E-1 Pf sanity: closing quote — terminator (Final quote category Pf).
    ("gh pr comment 1 --body 'ready to merge\u201d next'", 1, "E-1: closing Pf quote U+201D = terminator"),
    ("gh pr comment 1 --body 'ready to merge» next'", 1, "E-1: closing Pf quillemet » = terminator"),
    # Обратная кавычка вокруг формулировки тем же правилом — не буква и не
    # цифра, значит декларацию завершает. Цитировать формулировку в отчёте
    # по-прежнему можно: достаточно не оставлять её самостоятельной фразой
    # (продолжение словом ниже проверяется отдельно).
    ("gh pr comment 1 --body 'Use `ready to merge`'", 1, "граница: обратная кавычка завершает декларацию"),
    ("gh pr comment 1 --body 'Example: `готов к merge` phrase'", 1, "граница: обратная кавычка завершает по-русски"),
    ("gh pr comment 1 --body 'Here is `merge ready` in docs'", 1, "граница: обратная кавычка вокруг merge ready"),
    # E-5 regression: G2 combining diacritic still blocks via NFKD decomposition
    # (не через Sk skip). U+00B4 acute accent под NFKD → U+0020 + U+0301 →
    # space+combining → strip Mn → clean phrase. Terminator-check видит `:`.
    ("gh pr comment 1 --body 'ready to merg\u00e9:landing'", 1, "E-5 regression: precomposed é NFKD decomposes"),
    ("gh pr comment 1 --body 'ready to merge\u0301:landing'", 1, "E-5 regression: combining acute U+0301 still block"),
    ("gh pr comment 1 --body 'ready to merge\u00b4:landing'", 1, "E-5 regression: acute accent Sk via NFKD path"),
    # Закрывающая скобка и тире — тот же класс. Прежний цикл «расширили —
    # получили новые находки — сузили обратно» кончился именно здесь: набор
    # знаков подгонялся под примеры, поэтому каждый следующий пример его ломал.
    # Правило теперь не перечисляет знаки, а спрашивает про границу слова.
    ("gh pr comment 1 --body '(ready to merge)'", 1, "граница: закрывающая скобка завершает декларацию"),
    ("gh pr comment 1 --body 'ready to merge — landing'", 1, "граница: тире завершает декларацию"),
    # Повтор тех же форм — контроль, что правило одно, а не таблица исключений.
    ("gh pr comment 1 --body 'ready to merge (if CI passes)'", 1, "граница: открывающая скобка (повтор формы) завершает"),
    ("gh pr comment 1 --body 'ready to merge [tracking]'", 1, "граница: открывающая квадратная скобка (повтор формы) завершает"),
    # «ready to merge» — декларация готовности PR НЕЗАВИСИМО от продолжения
    # (into main / branch main / после CI). Ранний фикс F1 сделал продолжение
    # словом снимающим декларацию — это была fail-open дыра, закрыта. Исключение
    # ровно одно: слово-объект слияния сразу за фразой (обсуждение механики).
    ("gh pr comment 1 --body 'ready to merge branch main'", 1, "продолжение направлением — декларация (F1-регресс закрыт)"),
    ("gh pr comment 1 --body 'ready to merge into main'", 1, "продолжение into — декларация"),
    ("gh pr comment 1 --body 'готов к merge после CI'", 1, "продолжение условием по-русски — декларация"),
    # Исключение: обсуждение МЕХАНИКИ слияния (слово-объект сразу за «merge»).
    ("gh pr comment 1 --body 'ready to merge conflicts manually'", 0, "механика слияния (conflicts) — не декларация"),
    ("gh pr comment 1 --body 'готов к merge конфликтам не будет'", 0, "механика слияния (конфликтам) — не декларация"),
    # Честные заголовки отчётов, которые прежний узкий класс пропускал.
    ("gh pr comment 1 --body '## ✅ Готов к merge ✅'", 1, "заголовок с галочкой блокируется"),
    ("gh pr comment 1 --body '## Готов к merge — сводка'", 1, "заголовок с тире блокируется"),
    ("gh pr comment 1 --body '### Ready to merge 🎉'", 1, "заголовок с эмодзи блокируется"),
    ("gh pr comment 1 --body '| Готов к merge | да |'", 1, "ячейка таблицы блокируется"),
    ("gh pr comment 1 --body '- [x] Готов к merge'", 1, "пункт чеклиста блокируется"),
    # Отрицание и цитата срабатывание снимают — это не изменилось.
    ("gh pr comment 1 --body 'Не готов к merge'", 0, "отрицание снимает срабатывание"),
    ("gh pr comment 1 --body '> Готов к merge — цитата чужого отчёта'", 0, "markdown-цитата снимает срабатывание"),
]


def main() -> int:
    failures = []
    for cmd, expected, description in TESTS:
        # Исторические записи использовали 1 как абстрактный признак block.
        # Исполнимый контракт hook-а после восстановления — конкретный exit 2.
        if expected == 1:
            expected = EXIT_BLOCK
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
