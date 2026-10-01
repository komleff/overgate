#!/usr/bin/env python3
"""Проверка формулировки готовности линейна по длине входа.

Инвариант (контракт §3.4): `readiness_policy.is_forbidden` работает по индексам
без копирования суффикса на каждое совпадение, поэтому её стоимость линейна по
длине входа. Прежняя версия копировала `normalized[match.end():]` на КАЖДОМ
кандидате — тот же класс квадратичности, что чинили в разборщике оболочки.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = ROOT / ".claude" / "hooks"
POLICY_PATH = HOOKS_DIR / "readiness_policy.py"

# Много кандидатов подряд — так на каждом совпадении копирование суффикса дало бы
# квадратичную стоимость. Копия — это memcpy с малой константой, поэтому её
# сверхлинейность видна лишь на достаточно больших N; квадратичный мутант на этих
# размерах всё же укладывается в пару секунд.
_SCALE_SMALL = 32000
_SCALE_LARGE = 64000
_SCALE_RATIO_THRESHOLD = 3.0
# Насколько сверхлинейнее должен быть мутант с копированием суффикса относительно
# исправного кода на тех же размерах. Наблюдаемая разница ~1.0; порог 0.5 — с
# запасом и не зависит от абсолютной скорости машины.
_MUTANT_RATIO_MARGIN = 0.5


def load(path: Path):
    name = f"readiness_under_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_mutated(transform):
    tmp = Path(tempfile.mkdtemp(prefix="readiness-mut-"))
    copy = tmp / "readiness_policy.py"
    original = POLICY_PATH.read_text(encoding="utf-8")
    mutated = transform(original)
    if mutated == original:
        raise AssertionError("мутация не изменила исходник — точка мутации не найдена")
    copy.write_text(mutated, encoding="utf-8")
    return load(copy), tmp


def candidates(n: int) -> str:
    # НЕ-декларативные кандидаты подряд: каждый снимается механикой слияния, и
    # проход НЕ замыкается на первом совпадении, а идёт по всем n. Так квадратичная
    # копия суффикса (мутант) успевает проявиться — на декларации проверка вышла бы
    # True на первом же кандидате и стоимость была бы O(1).
    return "ready to merge conflicts manually " * n


def doubling_ratio(fn, repeats: int = 5) -> float:
    """Отношение стоимости проверки входа 2N к входу N.

    Меряется ПРОЦЕССОРНОЕ время процесса (`time.process_time`), а не настенное:
    посторонняя нагрузка машины в него не входит. Берётся МИНИМУМ из нескольких
    замеров: всплески (вытеснение, прерывания) только добавляют время, поэтому
    минимум — несмещённая оценка чистой стоимости, а один всплеск его не сдвигает.
    Малый и большой входы чередуются — обе оценки получаются в одинаковых условиях.
    """
    small_text = candidates(_SCALE_SMALL)
    large_text = candidates(_SCALE_LARGE)
    small_samples = []
    large_samples = []
    for _ in range(repeats):
        for text, samples in ((small_text, small_samples), (large_text, large_samples)):
            started = time.process_time()
            fn(text)
            samples.append(time.process_time() - started)
    base = min(small_samples)
    double = min(large_samples)
    return double / base if base > 0 else float("inf")


# Отношение исправного кода меряется ОДИН раз и переиспользуется проверкой
# мутанта: так пять замеров вместо трёх не растягивают прогон.
_correct_ratio_cache: dict[int, float] = {}


def correct_doubling_ratio(policy) -> float:
    key = id(policy)
    if key not in _correct_ratio_cache:
        _correct_ratio_cache[key] = doubling_ratio(policy.is_forbidden)
    return _correct_ratio_cache[key]


def test_scales_near_linearly(policy) -> float:
    ratio = correct_doubling_ratio(policy)
    assert ratio < _SCALE_RATIO_THRESHOLD, (
        f"время выросло в {ratio:.2f}x при удвоении входа — стоимость близка к "
        f"квадратичной (порог {_SCALE_RATIO_THRESHOLD}x)"
    )
    return ratio


def test_mutation_suffix_copy_breaks_linearity(policy) -> None:
    """Возврат копирования суффикса на каждом совпадении делает стоимость сверхлинейной.

    Копия — memcpy с малой константой, поэтому абсолютный порог хрупок. Проверка
    сравнивает мутанта с ИСПРАВНЫМ кодом на тех же размерах и требует заметно
    большей сверхлинейности — это не зависит от абсолютной скорости машины.
    """

    def restore_suffix_copy(text: str) -> str:
        needle = "        length = len(normalized)\n        position = match.end()"
        replacement = (
            "        _tail = normalized[match.end():]\n"
            "        length = match.end() + len(_tail)\n"
            "        position = match.end()"
        )
        return text.replace(needle, replacement, 1)

    correct_ratio = correct_doubling_ratio(policy)
    mutated, tmp = load_mutated(restore_suffix_copy)
    try:
        mutant_ratio = doubling_ratio(mutated.is_forbidden)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(
        f"  замер мутанта с копированием суффикса: {mutant_ratio:.2f}x против "
        f"{correct_ratio:.2f}x (разница {mutant_ratio - correct_ratio:.2f})"
    )
    assert mutant_ratio - correct_ratio >= _MUTANT_RATIO_MARGIN, (
        f"мутант с копированием суффикса не заметно сверхлинейнее исправного "
        f"({mutant_ratio:.2f}x против {correct_ratio:.2f}x, разница "
        f"{mutant_ratio - correct_ratio:.2f} < {_MUTANT_RATIO_MARGIN})"
    )


def test_semantics_unchanged(policy) -> None:
    """Оптимизация не меняет вердикты на характерных формах."""
    expectations = {
        "## ✅ Готов к merge": True,
        "Не готов к merge": False,
        "ready to merge.": True,
        # Продолжение направлением — декларация (fail-open F1-регресс закрыт).
        "ready to merge branch main": True,
        "ready to merge into main": True,
        "готов к merge после CI": True,
        # Обсуждение механики слияния — не декларация.
        "готов к merge конфликтам не будет": False,
        "ready to merge conflicts manually": False,
        "> Готов к merge (цитата)": False,
        "| Готов к merge | да |": True,
        "почти готов к merge": False,
        "обычный отчёт ревью": False,
    }
    for text, expected in expectations.items():
        assert policy.is_forbidden(text) is expected, (
            f"вердикт изменился на {text!r}: {policy.is_forbidden(text)} != {expected}"
        )


def main() -> int:
    policy = load(POLICY_PATH)
    failures = []
    ratio = None
    for test in (
        test_scales_near_linearly,
        test_mutation_suffix_copy_breaks_linearity,
        test_semantics_unchanged,
    ):
        try:
            result = test(policy)
            if test is test_scales_near_linearly:
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
        print(f"readiness-policy-complexity: FAIL ({len(failures)})")
        return 1
    print("readiness-policy-complexity: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
