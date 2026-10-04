#!/usr/bin/env python3
"""
Hook: блокировка фраз merge-readiness в `gh pr comment` вне /finalize-pr.

Принимает на stdin JSON с payload tool_input от Claude Code, извлекает команду
и проверяет, содержит ли она запрещённую формулировку («готов к merge» /
«ready to merge» / «merge-ready» и вариации).

Защита от обхода:
- Case-insensitive по кириллице и латинице (re.IGNORECASE корректно работает
  с Unicode, в отличие от grep -i в локали C).
- Нормализация `_` и `-` в пробел, чтобы ловить `ready_to_merge`,
  `ready-to-merge`, `MERGE_READY`.
- Переносы строк отдельно не нормализуются: жадный `\\s*` между словами
  паттерна сам матчит пробелы, табы и переносы строк как whitespace.

Про FINALIZE_PR_TOKEN. Переменная читается из ОКРУЖЕНИЯ самого hook-процесса.
Приписать её к команде нельзя: PreToolUse hook исполняется отдельным процессом
ДО Bash-команды и inline-присваивания внутри её текста не видит. Поэтому запись
`FINALIZE_PR_TOKEN=1 gh pr comment …` рабочим маршрутом НЕ является и остаётся
заблокированной (.agents/PIPELINE_ADR.md §3.23). Штатный маршрут публикации —
доверенный `.claude/tools/publish-pr-comment.py`: он зовёт `gh` сам, минуя Bash
и его hook, а token живёт только в окружении его собственного процесса. Проверка
здесь — safety guard, а не security boundary.

Возвращает:
- exit 0  — команда разрешена (запрещённой формулировки в доказанном body нет)
- exit 2  — блокировка. Именно 2: по контракту hooks Claude Code блокирует
           PreToolUse только код 2; код 1 считается неблокирующей ошибкой,
           и действие выполняется. См. .claude/rules/ и план PR-1.
"""
import os
import sys

# Код блокировки PreToolUse. Только 2 блокирует вызов инструмента;
# 1 — неблокирующая ошибка, команда выполнится (контракт hooks Claude Code).
# Константа объявлена до импортов: любой отказ загрузки обязан завершиться
# именно этим кодом, а не всплыть трассировкой с неблокирующим кодом 1.
EXIT_BLOCK = 2

# Каталог обработчиков не имеет права участвовать в разрешении имён модулей.
# Python сам ставит каталог запускаемого скрипта первым в sys.path, поэтому
# одноимённый файл рядом подменяет модуль стандартной библиотеки, и предикат
# гейта отключается молча — с кодом «пропустить». Убираем каталог из пути ДО
# первого импорта стандартной библиотеки; соседние модули пакета грузятся ниже
# по явному пути файла.
#
# Очистка здесь безусловна: файл — точка входа обработчика и в бою ниоткуда не
# импортируется. У классификатора коммитов та же очистка привязана к запуску
# скриптом: он ещё и библиотека для тестов, и там разрешение имён — забота
# вызывающего.
#
# Сверка идёт по разрешённым путям: интерпретатор кладёт в пути поиска путь с
# раскрытыми символьными ссылками, а `abspath` их сохраняет. Без общего вида
# каталог остаётся в путях всюду, где до него ведёт символьная ссылка.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
_EXCLUDED_DIR = os.path.realpath(_HOOK_DIR)
sys.path[:] = [
    entry
    for entry in sys.path
    if os.path.realpath(entry or os.getcwd()) != _EXCLUDED_DIR
]

try:
    import importlib.util
    import json
    import time

    def _load_sibling(name: str):
        """Загрузить соседний модуль пакета обработчиков по явному пути файла.

        Уже загруженный ТОТ ЖЕ файл берётся повторно: политика формулировки
        обязана быть одним объектом на процесс, иначе публикатор и гейт разойдутся
        в вердикте, оставаясь «одинаковыми по тексту». Совпадение проверяется по
        файлу, а не по имени, — чужой одноимённый модуль так не подхватится.
        """

        path = os.path.join(_HOOK_DIR, name + ".py")
        existing = sys.modules.get(name)
        if existing is not None and getattr(existing, "__file__", None):
            try:
                if os.path.samefile(existing.__file__, path):
                    return existing
            except OSError:
                pass
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"не найден модуль пакета обработчиков: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    _parser = _load_sibling("shell_comment_parser")
    _policy = _load_sibling("readiness_policy")
    DEFAULT_MAX_SUBSTITUTION_DEPTH = _parser.DEFAULT_MAX_SUBSTITUTION_DEPTH
    ShellParseLimitExceeded = _parser.ShellParseLimitExceeded
    analyze_shell = _parser.analyze_shell
    ReadinessCheckLimitExceeded = _policy.ReadinessCheckLimitExceeded
    is_forbidden = _policy.is_forbidden
except BaseException as _import_error:  # noqa: BLE001 — отказ обязан быть громким
    # Неисправный или подменённый модуль пакета — это НЕ доказательство
    # безопасности команды. Трассировка дала бы код 1, а он для PreToolUse
    # неблокирующий: команда ушла бы в работу без проверки.
    sys.stderr.write(
        "БЛОКИРОВКА: гейт публикации не смог загрузить собственные модули "
        f"({_import_error}). Команда не пропускается: проверить тело "
        "публикации нечем.\n"
    )
    raise SystemExit(EXIT_BLOCK)

# Собственный предел фазы РАЗБОРА, секунды.
#
# Почему свой, а не только объявленный диспетчеру в .claude/settings.json:
# по своему пределу диспетчер снимает обработчик, а снятый обработчик кода
# выхода не возвращает — блокирует же только код 2. То есть публикация уходила бы
# БЕЗ проверки тела ровно там, где разбор дорог. Стоимость разбора растёт
# экспоненциально по глубине вложенных подстановок: замер 2026-08-12 (macOS)
# 16 уровней — 0,61 с, 18 — 2,43 с, 19 — 4,87 с, 21 — 19,4 с при длине команды
# 111 символов.
#
# Арифметика бюджета обработчика: запуск интерпретатора (~0,2 с) + разбор
# (≤ 2 с) + печать причины (~0,01 с) ≈ 2,3 с при объявленном диспетчеру пределе
# 5 с. Запас более чем двукратный, а предел разбора строго меньше объявленного.
# Соответствие чисел проверяется тестом scripts/tests/merge-gate-parse-budget.test.sh.
PARSE_TIME_LIMIT_SECONDS = 2.0

# Предел вложенности разбора. Он же — основная защита: 8 уровней покрывают любую
# рабочую запись с запасом, а глубже разбор всё равно ничего не доказывает.
# Предел времени остаётся внешней страховкой на случай, когда дорога не глубина,
# а ширина (много подстановок подряд).
PARSE_MAX_DEPTH = DEFAULT_MAX_SUBSTITUTION_DEPTH


def _test_narrowed_parse_limit() -> float:
    """Действующий предел разбора с учётом тестового крючка.

    Крючок умеет только СУЖАТЬ окно: берётся минимум с рабочим пределом, поэтому
    он не может превратить блокирующий гейт в пропускающий. Значение вне формата
    «положительное число секунд» игнорируется — остаётся рабочий предел.
    """
    override = os.environ.get("OVERGATE_MERGE_GATE_TEST_MAX_PARSE_SECONDS")
    if not override:
        return PARSE_TIME_LIMIT_SECONDS
    try:
        requested = float(override)
    except (TypeError, ValueError):
        return PARSE_TIME_LIMIT_SECONDS
    if requested <= 0:
        return PARSE_TIME_LIMIT_SECONDS
    return min(PARSE_TIME_LIMIT_SECONDS, requested)


# Собственный предел фазы ПРОВЕРКИ ФОРМУЛИРОВКИ, секунды.
#
# Предел разбора выше защищал только первую фазу. Вторая фаза шла после него без
# предела — и на длинном входе выходила за бюджет обработчика целиком: диспетчер
# снимал обработчик, а снятый обработчик кода выхода не возвращает и блокирует
# только код 2. Инвариант простой: ограничена КАЖДАЯ фаза, и истечение предела
# любой из них — блокировка.
#
# Бюджет обработчика: запуск интерпретатора (~0,2 с) + разбор (≤ 2 с) + проверка
# формулировки (≤ 1 с) + печать причины (~0,01 с) ≈ 3,3 с при объявленном
# диспетчеру пределе 5 с. Соответствие чисел проверяется тестом
# scripts/tests/merge-gate-parse-budget.test.sh.
READINESS_TIME_LIMIT_SECONDS = 1.0


def _test_narrowed_readiness_limit() -> float:
    """Действующий предел проверки формулировки с учётом тестового крючка.

    Крючок, как и у фазы разбора, умеет только СУЖАТЬ окно: берётся минимум с
    рабочим пределом. Значение вне формата «положительное число секунд»
    игнорируется — остаётся рабочий предел.
    """
    override = os.environ.get("OVERGATE_MERGE_GATE_TEST_MAX_READINESS_SECONDS")
    if not override:
        return READINESS_TIME_LIMIT_SECONDS
    try:
        requested = float(override)
    except (TypeError, ValueError):
        return READINESS_TIME_LIMIT_SECONDS
    if requested <= 0:
        return READINESS_TIME_LIMIT_SECONDS
    return min(READINESS_TIME_LIMIT_SECONDS, requested)


class HookError(Exception):
    """Сигнал безопасной остановки hook'а с блокировкой команды."""


def extract_command(raw_stdin: str) -> str:
    """Получить текст команды из payload hook'а Claude Code.

    Fail-secure: если JSON невалиден, бросаем исключение → hook блокирует
    команду (exit 2). Отсутствие `tool_input.command` — тоже HookError:
    broad matcher `Bash` доставляет hook все Bash-команды, а общий
    `shell_comment_parser.py` отделяет кандидаты публикации от quoted data.
    Поле `command` обязано присутствовать; пустая строка была бы fail-open
    при изменении формата payload.

    Значение нестрокового типа — тоже HookError, а не путь до разбора: разбор
    строки на числе или списке падал бы трассировкой, а трассировка даёт код 1,
    который для PreToolUse НЕ блокирует. Проверка типа переводит этот случай в
    обычную блокировку.
    """
    try:
        payload = json.loads(raw_stdin)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HookError(
            f"check-merge-ready: невалидный JSON на stdin ({exc}). "
            "Hook блокирует команду fail-secure."
        ) from exc
    if not isinstance(payload, dict):
        raise HookError(
            "check-merge-ready: payload hook'а не является объектом. "
            "Hook блокирует команду fail-secure."
        )
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        raise HookError(
            "check-merge-ready: tool_input в payload не является объектом. "
            "Hook блокирует команду fail-secure."
        )
    command = tool_input.get("command")
    if not isinstance(command, str):
        raise HookError(
            "check-merge-ready: tool_input.command отсутствует или не является "
            "строкой. Hook блокирует команду fail-secure."
        )
    if not command:
        raise HookError(
            "check-merge-ready: в payload отсутствует tool_input.command. "
            "Hook блокирует команду fail-secure."
        )
    return command


def main() -> int:
    # Легитимный вызов из /finalize-pr — пропускаем
    if os.environ.get("FINALIZE_PR_TOKEN"):
        return 0

    raw = sys.stdin.read()

    try:
        command = extract_command(raw)
    except HookError as exc:
        sys.stderr.write(str(exc) + "\n")
        return EXIT_BLOCK

    # Единый stateful-проход связывает реальные top-level публикации с body.
    # Маскирование heredoc до лексического доказательства не используется.
    # Разбор идёт под собственными пределами: незавершённый разбор — не
    # доказательство инертности, поэтому его истечение блокирует команду.
    try:
        analysis = analyze_shell(
            command,
            time_limit_seconds=_test_narrowed_parse_limit(),
            max_depth=PARSE_MAX_DEPTH,
        )
    except ShellParseLimitExceeded as exc:
        sys.stderr.write(
            f"БЛОКИРОВКА: разбор команды не завершён ({exc}), поэтому команда "
            "не пропускается: доказать отсутствие публикации с запрещённой "
            "формулировкой невозможно.\n"
            "Упрости команду — вложенные подстановки в разборе не нужны; "
            "для большого review-body используй "
            "`.claude/tools/publish-pr-comment.py`.\n"
        )
        return EXIT_BLOCK
    publications = analysis.publications

    # Разбор, который система не смогла завершить полностью и однозначно, по
    # определению не доказывает инертность входа. Такой вход блокируется НЕЗАВИСИМО
    # от того, найдены ли в нём публикации: если разбор оборвался ДО того, как
    # публикация могла быть обнаружена, пустой список публикаций — не
    # доказательство их отсутствия. Признак поднимается только при реально
    # незавершённом разборе (оборванная конструкция, незакрытая группа,
    # рассогласованная скобка), а не при штатных разобранных конструкциях
    # (подоболочка, группа, подстановка процесса, extglob, backtick).
    if analysis.global_ambiguous:
        sys.stderr.write(
            "БЛОКИРОВКА: команду не удалось разобрать полностью и однозначно, "
            "поэтому отсутствие публикации с запрещённой формулировкой доказать "
            "нельзя.\n"
            "Упрости команду; для большого review-body используй "
            "`.claude/tools/publish-pr-comment.py`.\n"
        )
        return EXIT_BLOCK

    # Hard gate доверяет только top-level прямолинейной последовательности.
    # Для ветвлений, функций, подстановок и иных неоднозначных контекстов
    # фактическую достижимость публикации доказать нельзя — fail-closed.
    if any(publication.ambiguous for publication in publications):
        sys.stderr.write(
            "БЛОКИРОВКА: публикация находится вне поддержанной "
            "прямолинейной shell-последовательности; её итоговое body "
            "невозможно доказуемо проверить.\n"
        )
        return EXIT_BLOCK

    # Блокируем --body-file / -F для gh pr comment вне /finalize-pr: body
    # передаётся файлом/stdin и hook не может надёжно проверить содержимое.
    # Это bypass hard gate (нашёл Copilot auto-reviewer). Для легитимных
    # длинных отчётов используется /finalize-pr с FINALIZE_PR_TOKEN.
    if any(publication.body_kind == "body_file" for publication in publications):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` флаги --body-file / -F "
            "запрещены без FINALIZE_PR_TOKEN, потому что hook не может "
            "провалидировать содержимое файла.\n"
            "Для большого review-body используй "
            "`.claude/tools/publish-pr-comment.py`; для readiness — "
            "/finalize-pr <PR_NUMBER>.\n"
        )
        return EXIT_BLOCK

    # Блокируем --edit-last: редактирует последний комментарий через
    # интерактивный редактор, содержимое скрыто от hook'а.
    # Copilot round 31: fail-secure блокировка.
    if any(publication.body_kind == "edit_last" for publication in publications):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` флаг --edit-last запрещён "
            "без FINALIZE_PR_TOKEN — содержимое редактируется вне "
            "командной строки и hook не может его проверить.\n"
            "Используй inline --body '...' ИЛИ /finalize-pr <PR_NUMBER>.\n"
        )
        return EXIT_BLOCK

    # Блокируем вызов без явного --body / -b / --body-file / -F:
    # gh открывает интерактивный редактор, содержимое скрыто от hook'а.
    # Copilot round 31: fail-secure блокировка editor mode.
    if any(publication.body_kind == "missing" for publication in publications):
        sys.stderr.write(
            "БЛОКИРОВКА: `gh pr comment` без флага --body / -b / "
            "--body-file / -F запрещён без FINALIZE_PR_TOKEN — "
            "gh откроет редактор и hook не сможет проверить содержимое.\n"
            "Используй inline --body '...', доверенный publish-pr-comment.py "
            "или /finalize-pr <PR_NUMBER>.\n"
        )
        return EXIT_BLOCK

    # Блокируем command substitution, скрывающие реальное содержимое body
    # от hook'а: `$(cat /file)`, `$(<file)`, backticks с чтением файла.
    # Legitimate heredoc `$(cat <<'EOF' ... EOF)` остаётся разрешённым
    # (содержимое инлайн, regex его видит). Here-string `<<<` НЕ блокируется
    # отдельно: `gh pr comment` не читает stdin без `--body-file -`,
    # который уже блокируется выше.
    if any(
        publication.body_kind == "opaque_substitution"
        for publication in publications
    ):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` запрещены конструкции, "
            "скрывающие содержимое body от hook'а: "
            "`$(cat file)`, `$(<file)`, backticks `cat file`.\n"
            "Используй inline --body '...', heredoc `$(cat <<'EOF' ... EOF)` "
            "либо доверенный publish-pr-comment.py; readiness — только "
            "через /finalize-pr <PR_NUMBER>.\n"
        )
        return EXIT_BLOCK

    # Блокируем `--body "$VAR"` / `--body $VAR` / `--body "${VAR}"` —
    # body берётся из переменной, hook видит только литерал имени переменной,
    # а реальный текст ему недоступен. Это bypass: запрещённая фраза легко
    # прячется в переменную (`BODY="## ✅ Готов к merge"; gh pr comment 1 --body "$BODY"`).
    if any(
        publication.body_kind == "opaque_variable"
        for publication in publications
    ):
        sys.stderr.write(
            "БЛОКИРОВКА: для `gh pr comment` нельзя подставлять body из "
            "переменной (`--body \"$VAR\"`, `--body ${VAR}`): hook видит "
            "только имя переменной, не её содержимое.\n"
            "Используй inline --body '...', heredoc `$(cat <<'EOF' ... EOF)` "
            "либо доверенный publish-pr-comment.py; readiness — только "
            "через /finalize-pr <PR_NUMBER>.\n"
        )
        return EXIT_BLOCK

    # Последняя проверка — сама запрещённая формулировка в ДОКАЗАННОМ body.
    # Сюда доходит только то, чьё тело разбор восстановил дословно: инлайн-литерал
    # и heredoc с квотированным делимитером. Непрозрачные формы (`--body-file`,
    # `--edit-last`, отсутствующий флаг, любые подстановки и переменные в позиции
    # `--body`) отсеяны ветками выше — их тело не восстановимо, и они блокируются
    # независимо от содержимого.
    #
    # Фаза идёт под СВОИМ пределом времени — вторым, независимым от предела
    # разбора. Незавершённая проверка доказательством отсутствия формулировки
    # не является, поэтому её истечение блокирует.
    readiness_deadline = time.monotonic() + _test_narrowed_readiness_limit()
    try:
        forbidden = any(
            publication.body is not None
            and is_forbidden(publication.body, deadline=readiness_deadline)
            for publication in publications
        )
    except ReadinessCheckLimitExceeded as exc:
        sys.stderr.write(
            f"БЛОКИРОВКА: проверка формулировки не завершена ({exc}), поэтому "
            "команда не пропускается: доказать отсутствие запрещённой "
            "формулировки невозможно.\n"
            "Для большого review-body используй "
            "`.claude/tools/publish-pr-comment.py`.\n"
        )
        return EXIT_BLOCK
    if forbidden:
        sys.stderr.write(
            "БЛОКИРОВКА: фразы 'готов к merge' / 'ready to merge' / 'merge-ready' "
            "разрешены только через /finalize-pr "
            "(см. .claude/skills/finalize-pr/SKILL.md).\n"
            "Используй /finalize-pr <PR_NUMBER>.\n"
        )
        return EXIT_BLOCK

    return 0


def _guarded_main() -> int:
    """Запуск с общим fail-closed завершением.

    Любая непредусмотренная ошибка внутри гейта — это отсутствие вердикта, а не
    вердикт «пропустить». Без этой обёртки исключение всплывало бы трассировкой
    и давало код 1, который для PreToolUse НЕ блокирует: команда ушла бы в
    работу непроверенной.
    """

    try:
        return main()
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 — вердикта нет, значит блокируем
        sys.stderr.write(
            f"БЛОКИРОВКА: гейт публикации завершился ошибкой ({error!r}). "
            "Команда не пропускается: вердикта о теле публикации нет.\n"
        )
        return EXIT_BLOCK


if __name__ == "__main__":
    sys.exit(_guarded_main())
