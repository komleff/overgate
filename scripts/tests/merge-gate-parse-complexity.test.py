#!/usr/bin/env python3
"""Разбор покрыт пределом времени на ВСЕХ фазах и близок к линейному по длине.

Инвариант: один бюджет времени покрывает весь разбор — лексинг, обход команд,
вложенные публикации, запасной вердикт и дедупликацию. Незавершённая фаза
инертность входа не доказывает, поэтому истечение предела на любой из них даёт
`ShellParseLimitExceeded`. Отдельно: стоимость разбора близка к линейной по длине
входа, а не квадратична — иначе широкий вход выводит разбор за предел обработчика
раньше, чем предел успевает сработать.
"""

from __future__ import annotations

import contextlib
import importlib.util
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = ROOT / ".claude" / "hooks"
PARSER_PATH = HOOKS_DIR / "shell_comment_parser.py"


def load_parser(path: Path = PARSER_PATH):
    # Уникальное имя модуля на каждую загрузку: мутационные копии не должны
    # затирать друг друга и исходный разборщик в sys.modules.
    name = f"parser_under_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_mutated(transform):
    """Загрузить копию разборщика с изменённым исходником.

    Каталог хуков копируется целиком, потому что разборщик грузит соседей
    (`shell_grammar`) по своему каталогу. `transform` меняет только текст
    разборщика.
    """
    tmp = Path(tempfile.mkdtemp(prefix="parse-complexity-mut-"))
    for item in HOOKS_DIR.glob("*.py"):
        shutil.copy2(item, tmp / item.name)
    parser_copy = tmp / "shell_comment_parser.py"
    original = parser_copy.read_text(encoding="utf-8")
    mutated = transform(original)
    if mutated == original:
        raise AssertionError("мутация не изменила исходник — точка мутации не найдена")
    parser_copy.write_text(mutated, encoding="utf-8")
    return load_parser(parser_copy), tmp


def wide_source(command_count: int) -> str:
    """Широкий вход: много top-level команд, как в воспроизведении находки."""
    return "gh pr comment;" * command_count


def doubling_ratio(analyze, repeats: int = 5) -> float:
    """Отношение стоимости разбора входа 2N к входу N.

    Меряется ПРОЦЕССОРНОЕ время процесса (`time.process_time`), а не настенное:
    посторонняя нагрузка машины в него не входит. Берётся МИНИМУМ из нескольких
    замеров: всплески (вытеснение, прерывания) только добавляют время, поэтому
    минимум — несмещённая оценка чистой стоимости, а один всплеск его не сдвигает.
    Малый и большой входы чередуются — обе оценки получаются в одинаковых условиях.
    """
    small_source = wide_source(_SCALE_SMALL)
    large_source = wide_source(_SCALE_LARGE)
    small_samples = []
    large_samples = []
    for _ in range(repeats):
        for source, samples in (
            (small_source, small_samples),
            (large_source, large_samples),
        ):
            started = time.process_time()
            analyze(source)
            samples.append(time.process_time() - started)
    base = min(small_samples)
    double = min(large_samples)
    return double / base if base > 0 else float("inf")


class _TickClock:
    """Заглушка часов разборщика: каждое обращение — один «тик».

    `monotonic()` возвращает счётчик и увеличивает его на 1. Так «время» разбора
    равно числу сверок с дедлайном и не зависит ни от скорости, ни от нагрузки
    машины — тест покрытия фаз становится детерминированным.
    """

    def __init__(self) -> None:
        self.ticks = 0

    def monotonic(self) -> float:
        value = self.ticks
        self.ticks += 1
        return float(value)


@contextlib.contextmanager
def tick_clock(module):
    """Подменить атрибут `time` у загруженного модуля разборщика на счётчик тиков.

    Подмена только на время блока; исходный модуль `time` восстанавливается в
    `finally`, а после блока проверяется, что подмена не утекла."""
    original = module.time
    clock = _TickClock()
    module.time = clock
    try:
        yield clock
    finally:
        module.time = original
    assert module.time is time, "подмена часов разборщика не восстановлена"


# Предел для замеров в тиках: конечный (иначе сверки с дедлайном часы не читают),
# но недостижимый за время разбора.
_UNREACHABLE_TICKS = 10 ** 12


def phase_ticks(parser, source: str) -> tuple[int, int]:
    """Тики лексинга и тики полного разбора — в сверках с дедлайном.

    Лексинг: ровно та работа, что идёт в `analyze_shell` ДО постлексерных фаз
    (нормализация переносов + лексер), с бюджетом с конечным дедлайном. Полный
    разбор сверх лексинга делает 2 постоянных обращения к часам (вычисление
    дедлайна и стартовая сверка) плюс сверки постлексерных фаз."""
    with tick_clock(parser) as clock:
        budget = parser._ParseBudget(
            deadline=clock.monotonic() + _UNREACHABLE_TICKS, max_depth=8
        )
        started = clock.ticks
        spliced = parser.shell_grammar.splice_line_continuations(source)
        parser._Lexer(spliced, budget).scan()
        lexer_ticks = clock.ticks - started

        started = clock.ticks
        parser.analyze_shell(
            source, time_limit_seconds=_UNREACHABLE_TICKS, max_depth=8
        )
        full_ticks = clock.ticks - started
    return lexer_ticks, full_ticks


# Постоянные обращения полного разбора к часам сверх лексинга: вычисление
# дедлайна и стартовая сверка. Они не относятся к постлексерной фазе.
_FIXED_FULL_TICKS = 2
# Сколько сверок постлексерной фазы нужно сверх постоянных, чтобы фаза считалась
# заметной и предел между лексингом и полным разбором гарантированно падал в неё.
_MIN_POST_LEXER_TICKS = 2


def test_wide_input_hits_time_limit(parser) -> None:
    """Широкий вход при малом пределе блокируется, а не возвращает тихий результат."""
    source = wide_source(16000)
    started = time.monotonic()
    try:
        parser.analyze_shell(source, time_limit_seconds=0.05, max_depth=8)
    except parser.ShellParseLimitExceeded:
        elapsed = time.monotonic() - started
        # Предел сработал вовремя, а не после многосекундного разбора.
        assert elapsed < 1.0, f"предел сработал слишком поздно: {elapsed:.2f}s"
        return
    raise AssertionError(
        "широкий вход не бросил ShellParseLimitExceeded при пределе 0.05 с"
    )


def mid_limit_ticks(parser, source: str) -> float:
    """Предел в тиках — середина между тиками лексинга и тиками полного разбора.

    Часы в тиках детерминированы, поэтому предел ровно разделяет фазы: лексер
    (он держит свою проверку времени) проходит целиком, а предел истекает на
    сверках постлексерной фазы. Попадание предела в лексер сделало бы мутационную
    проверку ложно-зелёной — условие заметности фазы ниже это исключает."""
    lexer_ticks, full_ticks = phase_ticks(parser, source)
    post_lexer_ticks = full_ticks - lexer_ticks - _FIXED_FULL_TICKS
    print(
        f"  тики покрытия фаз: лексинг={lexer_ticks} полный={full_ticks} "
        f"постлексерные={post_lexer_ticks}"
    )
    # Постлексерная фаза должна занимать заметную долю — иначе тест бессмысленен.
    # Два постоянных обращения полного разбора это условие не выполняют.
    assert post_lexer_ticks >= _MIN_POST_LEXER_TICKS, (
        f"постлексерная фаза пренебрежимо мала: лексинг={lexer_ticks} тиков, "
        f"полный={full_ticks} тиков, постлексерных сверок {post_lexer_ticks} "
        f"< {_MIN_POST_LEXER_TICKS}"
    )
    return (lexer_ticks + full_ticks) / 2


def test_post_lexer_phase_is_covered(parser) -> None:
    """Предел МЕЖДУ фронтом (нормализация+лексинг) и полным срабатывает в постлексерной фазе."""
    source = wide_source(16000)
    mid_limit = mid_limit_ticks(parser, source)
    with tick_clock(parser):
        try:
            parser.analyze_shell(source, time_limit_seconds=mid_limit, max_depth=8)
        except parser.ShellParseLimitExceeded:
            return
    raise AssertionError(
        "предел между фронтом разбора и полным не сработал — "
        "постлексерная фаза не покрыта проверкой времени"
    )


# Размеры для замера сложности. При удвоении входа линейная стоимость даёт ~2x,
# квадратичная — ~4x; порог 3.0 разделяет их с запасом. Размеры небольшие
# намеренно: квадратичный МУТАНТ на них укладывается в пару секунд (на широком
# входе он растёт как N², и большие N сделали бы мутационную проверку неподъёмной).
_SCALE_SMALL = 4000
_SCALE_LARGE = 8000
_SCALE_RATIO_THRESHOLD = 3.0


def test_parse_scales_near_linearly(parser) -> None:
    """Время разбора N и 2N команд НЕ учетверяется — стоимость линейна, не квадратична."""
    ratio = doubling_ratio(parser.analyze_shell)
    assert ratio < _SCALE_RATIO_THRESHOLD, (
        f"время выросло в {ratio:.2f}x при удвоении входа — стоимость близка к "
        f"квадратичной ({_SCALE_SMALL} → {_SCALE_LARGE} команд)"
    )
    return ratio


def test_mutation_post_lexer_check_removed_misses(parser) -> None:
    """Снятие проверки времени в постлексерной фазе перестаёт блокировать широкий вход."""
    source = wide_source(16000)
    # Предел считается по исправному разборщику: лексер у мутанта тот же.
    mid_limit = mid_limit_ticks(parser, source)

    def strip_post_lexer_checks(text: str) -> str:
        # Проверки времени постлексерных фаз — вызовы `budget.checkpoint()`.
        # В лексере используется `self.budget.check_time()`, поэтому его покрытие
        # мутация не трогает: остаётся видно, что защиту держат именно эти фазы.
        return text.replace("budget.checkpoint()", "None  # мутация: проверка снята")

    mutated, tmp = load_mutated(strip_post_lexer_checks)
    try:
        # При пределе между лексингом и полным разбором лексер проходит, а
        # постлексерная фаза без проверки уже не бросает — мутант «пропускает».
        # Часы мутанта подменяются отдельно: это свой загруженный модуль.
        with tick_clock(mutated):
            try:
                mutated.analyze_shell(
                    source, time_limit_seconds=mid_limit, max_depth=8
                )
            except mutated.ShellParseLimitExceeded:
                raise AssertionError(
                    "мутант со снятой постлексерной проверкой всё равно бросил лимит — "
                    "проверка не покрывает целевую фазу"
                )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mutation_quadratic_backstop_breaks_linearity(parser) -> None:
    """Возврат линейного просмотра признанных спанов делает стоимость квадратичной."""

    def restore_linear_scan(text: str) -> str:
        needle = "index = bisect.bisect_left(merged_span_starts, match_end) - 1"
        replacement = (
            "index = max((i for i, s in enumerate(merged_span_starts) "
            "if s < match_end), default=-1)"
        )
        return text.replace(needle, replacement)

    mutated, tmp = load_mutated(restore_linear_scan)
    try:
        ratio = doubling_ratio(mutated.analyze_shell)
        print(f"  замер мутанта с линейным просмотром: {ratio:.2f}x")
        # На тех же размерах, что и тест сложности: квадратичный мутант обязан
        # перешагнуть порог, иначе тест сложности его не поймал бы.
        assert ratio >= _SCALE_RATIO_THRESHOLD, (
            f"мутант с линейным просмотром не показал квадратичный рост "
            f"({ratio:.2f}x при удвоении) — тест сложности не ловит регресс"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_short_commands_never_hit_limit(parser) -> None:
    """Короткие обычные команды проходят под штатным пределом без ложного блока."""
    for command in (
        "gh pr comment 1 --body 'обычный отчёт'",
        "git status --short",
        "echo a && echo b && echo c",
        "(cd foo && make)",
    ):
        # Не должно бросать даже при малом, но реалистичном пределе.
        parser.analyze_shell(command, time_limit_seconds=2.0, max_depth=8)


def main() -> int:
    parser = load_parser()
    failures = []
    ratio = None
    for test in (
        test_wide_input_hits_time_limit,
        test_post_lexer_phase_is_covered,
        test_parse_scales_near_linearly,
        test_mutation_post_lexer_check_removed_misses,
        test_mutation_quadratic_backstop_breaks_linearity,
        test_short_commands_never_hit_limit,
    ):
        try:
            result = test(parser)
            if test is test_parse_scales_near_linearly:
                ratio = result
            print(f"  PASS: {test.__name__}")
        except AssertionError as error:
            failures.append((test.__name__, str(error)))
            print(f"  FAIL: {test.__name__} — {error}")

    if ratio is not None:
        print(
            f"  замер линейности: время {_SCALE_LARGE}/{_SCALE_SMALL} = "
            f"{ratio:.2f}x (линейно < {_SCALE_RATIO_THRESHOLD}x)"
        )

    if failures:
        print(f"merge-gate-parse-complexity: FAIL ({len(failures)})")
        return 1
    print("merge-gate-parse-complexity: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
