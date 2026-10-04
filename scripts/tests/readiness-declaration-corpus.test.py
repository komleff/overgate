#!/usr/bin/env python3
"""Корпус деклараций готовности: продолжение направлением НЕ снимает запрет.

Инвариант: «ready to merge» / «готов к merge» как декларация готовности ЭТОГО PR
запрещена НЕЗАВИСИМО от того, что идёт после «merge» (into main / branch main /
после CI / в main / конец / пунктуация). Ранний фикс F1 сделал продолжение
словом снимающим декларацию — это была fail-open дыра. НЕ запрещаются: явное
отрицание перед фразой, обсуждение механики слияния (слово-объект слияния сразу
за «merge»), формы без самого кандидата («steps to merge», «how to merge»).
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / ".claude" / "hooks" / "readiness_policy.py"


def load(path: Path):
    name = f"readiness_corpus_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ~15 декларативных форм: обязаны блокироваться (True), включая продолжения
# направлением/условием, которые ранний фикс F1 пропускал.
DECLARATIVE = [
    "ready to merge",
    "готов к merge",
    "ready to merge.",
    "ready to merge into main",
    "ready to merge branch main",
    "ready to merge to production",
    "ready to merge now",
    "Ready to merge into develop",
    "PR ready to merge into main",
    "готов к merge в main",
    "готов к merge после CI",
    "готов к merge — вливаю",
    "готов к merge, вливаю",
    "## ✅ Готов к merge",
    "merge ready",
    "merge is ready",
]

# ~15 НЕ-декларативных форм: обязаны пропускаться (False) — отрицания, механика
# слияния, обсуждение без декларации.
NON_DECLARATIVE = [
    "not ready to merge",
    "не готов к merge",
    "not yet ready to merge",
    "still not ready to merge",
    "почти готов к merge",
    "почти готов к merge в main",
    "ready to merge conflicts manually",
    "ready to merge conflicts by hand",
    "готов к merge конфликтам не будет",
    "готов к merge конфликтов вручную",
    "steps to merge conflicts",
    "how to merge branches",
    "> ready to merge (цитата)",
    "fixed the merge conflict in file",
    "resolved merge conflicts and pushed",
    "review complete, no blockers for merge",
]


def check(policy, corpus, expected: bool) -> list:
    failures = []
    for text in corpus:
        if policy.is_forbidden(text) is not expected:
            failures.append(text)
    return failures


def test_declarative_are_forbidden(policy) -> None:
    bad = check(policy, DECLARATIVE, True)
    assert not bad, f"декларации НЕ заблокированы (fail-open): {bad}"


def test_non_declarative_pass(policy) -> None:
    bad = check(policy, NON_DECLARATIVE, False)
    assert not bad, f"не-декларации ложно заблокированы: {bad}"


def test_mutation_f1_regression_reopens_hole(policy) -> None:
    """Возврат правила «продолжение словом снимает декларацию» открывает fail-open."""

    def restore_f1(text: str) -> str:
        # Возвращаем прежнее правило F1: любое продолжение СЛОВОМ снимает
        # декларацию (ровно дыра). Мутируется проверка слова-продолжения — там,
        # где сейчас исключение только для механики слияния.
        needle = (
            "        if position < length and normalized[position].isalpha():\n"
            "            if _is_merge_mechanics(_following_word(normalized, position)):\n"
            "                continue\n"
            "        return True"
        )
        replacement = (
            "        if position < length and normalized[position].isalpha():\n"
            "            continue\n"
            "        return True"
        )
        return text.replace(needle, replacement, 1)

    tmp = Path(tempfile.mkdtemp(prefix="readiness-f1-mut-"))
    copy = tmp / "readiness_policy.py"
    original = POLICY_PATH.read_text(encoding="utf-8")
    mutated = restore_f1(original)
    if mutated == original:
        raise AssertionError("мутация F1 не применилась — точка мутации не найдена")
    copy.write_text(mutated, encoding="utf-8")
    try:
        mutant = load(copy)
        leaked = [t for t in DECLARATIVE if not mutant.is_forbidden(t)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # Возврат F1 обязан снова пропускать декларации с продолжением направлением.
    assert any(
        "into" in t or "branch" in t or "после" in t or "в main" in t
        for t in leaked
    ), f"мутация F1 не воспроизвела fail-open (пропущено: {leaked})"


def main() -> int:
    policy = load(POLICY_PATH)
    failures = []
    for test in (
        test_declarative_are_forbidden,
        test_non_declarative_pass,
        test_mutation_f1_regression_reopens_hole,
    ):
        try:
            test(policy)
            print(f"  PASS: {test.__name__}")
        except AssertionError as error:
            failures.append((test.__name__, str(error)))
            print(f"  FAIL: {test.__name__} — {error}")
    print(
        f"  корпус: {len(DECLARATIVE)} декларативных / "
        f"{len(NON_DECLARATIVE)} не-декларативных"
    )
    if failures:
        print(f"readiness-declaration-corpus: FAIL ({len(failures)})")
        return 1
    print("readiness-declaration-corpus: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
