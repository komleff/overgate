#!/usr/bin/env python3
"""Безопасно опубликовать большое дословное тело PR-комментария.

Инструмент проверяет и передаёт ``gh`` один и тот же bytes-буфер. Путь к файлу
никогда не передаётся ``gh``, поэтому подмена пути после проверки не меняет
публикуемое содержимое.
"""

from __future__ import annotations

import os
import sys

# Инвариант поиска модулей: имена модулей разрешаются только по стандартным
# путям интерпретатора, а соседние модули пакета грузятся по явному пути файла.
# Каталог запускаемого скрипта Python ставит первым сам, поэтому оба рабочих
# каталога (инструментов и обработчиков) из путей поиска убираются — до первого
# импорта стандартной библиотеки. При импорте инструмента как библиотеки (тесты)
# пути не трогаем: там разрешение имён — забота вызывающего.
_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOK_DIR = os.path.join(os.path.dirname(_TOOL_DIR), "hooks")
if __name__ == "__main__":
    # Сверка идёт по разрешённым путям: интерпретатор кладёт в пути поиска путь
    # с раскрытыми символьными ссылками, а `abspath` их сохраняет. Без общего
    # вида каталог остаётся в путях всюду, где до него ведёт ссылка.
    _EXCLUDED_DIRS = {os.path.realpath(_TOOL_DIR), os.path.realpath(_HOOK_DIR)}
    sys.path[:] = [
        entry
        for entry in sys.path
        if os.path.realpath(entry or os.getcwd()) not in _EXCLUDED_DIRS
    ]

import importlib.util  # noqa: E402 — после приведения путей поиска
from pathlib import Path  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from typing import Callable, Sequence  # noqa: E402

# Предел времени проверки формулировки, секунды. Проверка линейна по длине тела
# (контракт §3.4), поэтому предел не режет легитимные крупные отчёты, а служит
# страховкой от патологического ввода. Истечение — отказ в публикации
# (безопасная сторона), а не тихий пропуск непроверенного тела.
_READINESS_TIME_LIMIT_SECONDS = 5.0


def _load_hook_module(name: str):
    """Загрузить модуль пакета обработчиков по явному пути файла.

    Уже загруженный ТОТ ЖЕ файл берётся повторно, чтобы политика формулировки
    оставалась одним объектом на процесс: публикатор и гейт обязаны отвечать
    одинаково. Совпадение проверяется по файлу, а не по имени.
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


try:
    readiness_policy = _load_hook_module("readiness_policy")
except BaseException as _import_error:  # noqa: BLE001 — отказ обязан быть громким
    # Публикация возможна только с работающей проверкой формулировки. Отказ
    # загрузки — это отсутствие проверки, поэтому инструмент отказывает в
    # публикации своим кодом отказа, а не продолжает работу.
    sys.stderr.write(
        "publish-pr-comment: отказ: не загружена политика формулировки "
        f"({_import_error}). Публикация не выполняется.\n"
    )
    raise SystemExit(2)


EXIT_REJECTED = 2
_ALLOWED_C0 = frozenset((0x09, 0x0A, 0x0D))


class PublishError(Exception):
    """Проверка источника или запуск публикации не состоялись."""


def _repository_root() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as exc:
        raise PublishError("не удалось запустить git для определения корня") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise PublishError("текущая директория не принадлежит git-репозиторию")
    return os.path.realpath(result.stdout.strip())


def _inside_repository(repo_root: str, resolved_path: str) -> bool:
    try:
        return os.path.commonpath((repo_root, resolved_path)) == repo_root
    except ValueError:
        return False


def _validate_body(body: bytes) -> bytes:
    if not body:
        raise PublishError("источник body пуст")
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PublishError("источник body не является строгим UTF-8") from exc
    if any(byte < 0x20 and byte not in _ALLOWED_C0 for byte in body):
        raise PublishError("источник body содержит запрещённые управляющие байты")
    # Проверка идёт под собственным пределом времени: незавершённая проверка —
    # не доказательство отсутствия readiness-декларации, поэтому её истечение
    # отказывает в публикации, а не пропускает непроверенное тело.
    deadline = time.monotonic() + _READINESS_TIME_LIMIT_SECONDS
    try:
        forbidden = readiness_policy.is_forbidden(text, deadline=deadline)
    except readiness_policy.ReadinessCheckLimitExceeded as exc:
        raise PublishError(
            f"проверка формулировки не уложилась в предел ({exc}); тело "
            "слишком велико для проверки — публикация не выполняется"
        ) from exc
    if forbidden and not os.environ.get("FINALIZE_PR_TOKEN"):
        raise PublishError(
            "readiness-декларации разрешены только через /finalize-pr"
        )
    return body


def _read_validated_body(body_path: str) -> bytes:
    if body_path == "-":
        try:
            body = sys.stdin.buffer.read()
        except (AttributeError, OSError) as exc:
            raise PublishError("не удалось прочитать body из stdin") from exc
        return _validate_body(body)

    repo_root = _repository_root()
    source_path = os.path.abspath(os.fspath(body_path))
    try:
        initial_path_stat = os.lstat(source_path)
    except OSError as exc:
        raise PublishError("источник body недоступен или небезопасен") from exc
    if stat.S_ISLNK(initial_path_stat.st_mode):
        raise PublishError("источник body не должен быть символической ссылкой")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = None
    try:
        descriptor = os.open(source_path, flags)
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise PublishError("источник body должен быть обычным файлом")

        resolved_path = os.path.realpath(source_path)
        if not _inside_repository(repo_root, resolved_path):
            raise PublishError("источник body должен находиться внутри репозитория")

        path_stat = os.lstat(source_path)
        if stat.S_ISLNK(path_stat.st_mode):
            raise PublishError(
                "источник body не должен быть символической ссылкой"
            )
        if (opened_stat.st_dev, opened_stat.st_ino) != (
            path_stat.st_dev,
            path_stat.st_ino,
        ):
            raise PublishError("источник body изменился во время проверки")

        chunks = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        body = b"".join(chunks)
    except PublishError:
        raise
    except OSError as exc:
        raise PublishError("источник body недоступен или небезопасен") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass

    return _validate_body(body)



def publish_comment(
    pr_number: str,
    body_path: str,
    *,
    _after_read: Callable[[], None] | None = None,
) -> int:
    """Проверить body и вернуть исходный код ``gh pr comment``.

    ``_after_read`` — детерминированный seam race-теста. CLI его не принимает;
    производственный путь всегда вызывает функцию без callback.
    """
    if not (
        1 <= len(pr_number) <= 20
        and pr_number.isascii()
        and pr_number.isdigit()
        and pr_number[0] != "0"
    ):
        raise PublishError("PR_NUMBER должен быть положительным целым числом")

    body = _read_validated_body(body_path)
    if _after_read is not None:
        _after_read()

    try:
        result = subprocess.run(
            ["gh", "pr", "comment", pr_number, "--body-file", "-"],
            input=body,
            check=False,
            env={
                key: value
                for key, value in os.environ.items()
                if key != "FINALIZE_PR_TOKEN"
            },
        )
    except OSError as exc:
        raise PublishError("не удалось запустить gh") from exc
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2:
        sys.stderr.write(
            "Использование: publish-pr-comment.py <PR_NUMBER> <BODY_PATH|->\n"
        )
        return EXIT_REJECTED
    try:
        return publish_comment(arguments[0], arguments[1])
    except PublishError as exc:
        sys.stderr.write(f"publish-pr-comment: отказ: {exc}\n")
        return EXIT_REJECTED


if __name__ == "__main__":
    sys.exit(main())
