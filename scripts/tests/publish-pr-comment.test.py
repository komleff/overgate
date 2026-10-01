#!/usr/bin/env python3
"""Поведенческие тесты доверенного публикатора больших PR-комментариев."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".claude" / "tools" / "publish-pr-comment.py"
POLICY = ROOT / ".claude" / "hooks" / "readiness_policy.py"
INSTALL = ROOT / ".agents" / "INSTALL.md"
SETTINGS = ROOT / ".claude" / "settings.json"
EXTERNAL_REVIEW_SKILL = ROOT / ".claude" / "skills" / "external-review" / "SKILL.md"
SPRINT_PR_CYCLE_SKILL = ROOT / ".claude" / "skills" / "sprint-pr-cycle" / "SKILL.md"
FINALIZE_PR_SKILL = ROOT / ".claude" / "skills" / "finalize-pr" / "SKILL.md"
PIPELINE_AUDIT_SKILL = ROOT / ".claude" / "skills" / "pipeline-audit" / "SKILL.md"
PIPELINE_ADR = ROOT / ".agents" / "PIPELINE_ADR.md"


def load_file_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не удалось создать import spec для {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def extract_bash_block(path: Path, heading: str, *, index: int = 0) -> str:
    """Извлечь настоящий shell-фрагмент skill, а не тестовую копию команды."""
    source = path.read_text(encoding="utf-8")
    section = source.split(heading, 1)[1]
    blocks = section.split("```bash")[1:]
    return blocks[index].split("```", 1)[0].strip()


def merge_ready_wrapper() -> str:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return next(
        hook["command"]
        for entry in settings["hooks"]["PreToolUse"]
        for hook in entry.get("hooks", [])
        if "check-merge-ready" in hook.get("command", "")
    )


# Номер PR, который этот тест подаёт публикатору.
TEST_PR = "645"



class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="u2-publisher-test-"))
        self.repo = self.sandbox / "repo"
        self.repo.mkdir()
        state_patch = mock.patch.dict(
            os.environ,
            {"PYTHONDONTWRITEBYTECODE": "1"},
        )
        state_patch.start()
        self.addCleanup(state_patch.stop)
        subprocess.run(
            ["git", "init", "-q", str(self.repo)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.body_path = self.repo / "review.md"
        self.capture_body = self.sandbox / "captured-body.bin"
        self.capture_args = self.sandbox / "captured-args.json"
        self.capture_publisher_token = self.sandbox / "publisher-token.txt"
        self.capture_gh_token = self.sandbox / "gh-token.txt"
        self.fake_bin = self.sandbox / "bin"
        self.fake_bin.mkdir()
        broken_python3 = self.fake_bin / "python3"
        broken_python3.write_text("#!/bin/sh\nexit 9009\n", encoding="utf-8")
        broken_python3.chmod(0o755)
        fake_python = self.fake_bin / "python"
        # Publisher опознаётся по имени скрипта, а не по абсолютному пути: сниппет
        # находит его через `git rev-parse --show-toplevel` изолированного рабочего
        # дерева, и путь там заведомо не совпадает с путём в рабочей копии.
        fake_python.write_text(
            "#!/bin/sh\n"
            f"case \"${{1-}}\" in */{TOOL.name}|{TOOL.name})\n"
            "  printf '%s' \"${FINALIZE_PR_TOKEN-}\" > \"$FAKE_PUBLISHER_TOKEN\"\n"
            "  ;;\n"
            "esac\n"
            f"exec {shlex.quote(sys.executable)} \"$@\"\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        self.legacy_python_bin = self.sandbox / "legacy-python-bin"
        self.legacy_python_bin.mkdir()
        shutil.copy2(fake_python, self.legacy_python_bin / "python3")
        fake_gh = self.fake_bin / "gh"
        fake_gh.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['pr', 'view']:\n"
            "    print(os.environ.get('FAKE_GH_VIEW', '0'))\n"
            "    raise SystemExit(0)\n"
            "body = sys.stdin.buffer.read()\n"
            "if '--body' in args:\n"
            "    body = args[args.index('--body') + 1].encode()\n"
            "pathlib.Path(os.environ['FAKE_GH_BODY']).write_bytes(body)\n"
            "pathlib.Path(os.environ['FAKE_GH_ARGS']).write_text(json.dumps(args))\n"
            "pathlib.Path(os.environ['FAKE_GH_TOKEN']).write_text("
            "os.environ.get('FINALIZE_PR_TOKEN', ''))\n"
            "raise SystemExit(int(os.environ.get('FAKE_GH_EXIT', '0')))\n",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        self.old_cwd = Path.cwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.sandbox)

    def load_tool(self):
        return load_file_module("publish_pr_comment", TOOL)

    def gh_environment(self, exit_code: int = 0):
        return mock.patch.dict(
            os.environ,
            {
                "PATH": str(self.fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                "FAKE_GH_BODY": str(self.capture_body),
                "FAKE_GH_ARGS": str(self.capture_args),
                "FAKE_GH_TOKEN": str(self.capture_gh_token),
                "FAKE_PUBLISHER_TOKEN": str(self.capture_publisher_token),
                "FAKE_GH_EXIT": str(exit_code),
            },
        )

    def test_large_utf8_body_reaches_gh_byte_for_byte(self):
        """Ломается, если отправитель перекодирует/усекает буфер или меняет argv."""
        tool = self.load_tool()
        body = ("## Фикс-раунд №7 — проверка\n\nПринято. 🚀\n" * 12000).encode()
        self.body_path.write_bytes(body)

        with self.gh_environment():
            result = tool.publish_comment(TEST_PR, str(self.body_path))

        self.assertEqual(result, 0)
        self.assertEqual(self.capture_body.read_bytes(), body)
        self.assertEqual(
            json.loads(self.capture_args.read_text()),
            ["pr", "comment", TEST_PR, "--body-file", "-"],
        )

    def test_large_non_forbidden_body_publishes_quickly(self):
        """Ломается, если проверка формулировки нелинейна: крупное тело должно публиковаться быстро."""
        tool = self.load_tool()
        # Много кандидатов-НЕдеклараций подряд (обсуждение механики слияния):
        # линейная проверка проходит быстро, квадратичная вывела бы публикацию за
        # предел. Именно механика, а не декларация — иначе тело было бы запрещено.
        body = ("ready to merge conflicts manually again " * 40000).encode()
        self.body_path.write_bytes(body)

        started = time.monotonic()
        with self.gh_environment():
            result = tool.publish_comment(TEST_PR, str(self.body_path))
        elapsed = time.monotonic() - started

        self.assertEqual(result, 0)
        self.assertEqual(self.capture_body.read_bytes(), body)
        self.assertLess(elapsed, 5.0, f"публикация крупного тела заняла {elapsed:.2f}s")

    def test_readiness_check_timeout_refuses_publication(self):
        """Ломается, если истечение предела проверки формулировки пропускает публикацию."""
        tool = self.load_tool()
        self.body_path.write_text("любой отчёт без формулировки\n", encoding="utf-8")

        def slow_forbidden(text, *, deadline=None):
            # Класс из ТОГО ЖЕ модуля, что ловит публикатор.
            raise tool.readiness_policy.ReadinessCheckLimitExceeded(
                "тест: предел исчерпан"
            )

        with self.gh_environment(), mock.patch.object(
            tool.readiness_policy, "is_forbidden", slow_forbidden
        ):
            with self.assertRaises(tool.PublishError):
                tool.publish_comment(TEST_PR, str(self.body_path))
        # Истечение предела — отказ, а не публикация непроверенного тела.
        self.assertFalse(self.capture_body.exists())

    def test_path_replacement_after_read_cannot_change_sent_bytes(self):
        """Ломается, если gh повторно читает путь после проверки."""
        tool = self.load_tool()
        original = "## Фикс-раунд №8 — исходный буфер\n".encode()
        replacement = "## Фикс-раунд №9 — подменённое содержимое\n".encode()
        self.body_path.write_bytes(original)
        def replace_path():
            swapped = self.repo / "replacement.md"
            swapped.write_bytes(replacement)
            os.replace(swapped, self.body_path)

        with self.gh_environment():
            result = tool.publish_comment(
                TEST_PR, str(self.body_path), _after_read=replace_path
            )

        self.assertEqual(result, 0)
        self.assertEqual(self.capture_body.read_bytes(), original)
        self.assertEqual(self.body_path.read_bytes(), replacement)

    def test_final_symlink_is_rejected_without_calling_gh(self):
        """Ломается, если O_NOFOLLOW/regular-file gate исчезнет."""
        tool = self.load_tool()
        outside = self.sandbox / "outside.md"
        outside.write_text("нейтральный отчёт\n", encoding="utf-8")
        self.body_path.symlink_to(outside)

        with self.gh_environment(), self.assertRaises(tool.PublishError):
            tool.publish_comment(TEST_PR, str(self.body_path))

        self.assertFalse(self.capture_body.exists())

    def test_final_symlink_inside_repo_is_rejected_without_o_nofollow(self):
        """Ломается, если запрет symlink держится только на O_NOFOLLOW."""
        tool = self.load_tool()
        target = self.repo / "inside.md"
        target.write_text("нейтральный отчёт\n", encoding="utf-8")
        self.body_path.symlink_to(target)

        with (
            self.gh_environment(),
            mock.patch.object(tool.os, "O_NOFOLLOW", 0, create=True),
            self.assertRaises(tool.PublishError),
        ):
            tool.publish_comment(TEST_PR, str(self.body_path))

        self.assertFalse(self.capture_body.exists())

    def test_path_outside_repository_is_rejected_without_calling_gh(self):
        """Ломается, если containment проверяется строковым prefix или не проверяется."""
        tool = self.load_tool()
        outside_dir = self.sandbox / "repo-neighbor"
        outside_dir.mkdir()
        outside = outside_dir / "review.md"
        outside.write_text("нейтральный отчёт\n", encoding="utf-8")

        with self.gh_environment(), self.assertRaises(tool.PublishError):
            tool.publish_comment(TEST_PR, str(outside))

        self.assertFalse(self.capture_body.exists())

    def test_missing_and_empty_sources_are_rejected(self):
        """Ломается, если недоступный либо пустой источник доходит до gh."""
        tool = self.load_tool()
        cases = [self.repo / "missing.md", self.body_path]
        self.body_path.write_bytes(b"")

        with self.gh_environment():
            for path in cases:
                with self.subTest(path=path), self.assertRaises(tool.PublishError):
                    tool.publish_comment(TEST_PR, str(path))

        self.assertFalse(self.capture_body.exists())

    def test_binary_and_non_utf8_sources_are_rejected(self):
        """Ломается, если strict UTF-8/NUL/C0 validation ослабнет."""
        tool = self.load_tool()
        cases = {
            "non-utf8": b"report\xff",
            "nul": b"report\x00tail",
            "c0": b"report\x01tail",
        }

        with self.gh_environment():
            for label, body in cases.items():
                self.body_path.write_bytes(body)
                with self.subTest(label=label), self.assertRaises(tool.PublishError):
                    tool.publish_comment(TEST_PR, str(self.body_path))

        self.assertFalse(self.capture_body.exists())

    def test_allowed_control_bytes_reach_gh_unchanged(self):
        """Ломается, если фильтр C0 сузится и закроет табуляцию или возврат каретки.

        Отрицательная сторона фильтра проверена выше; без этой положительной
        стороны ужесточение набора разрешённых управляющих байтов молча закрыло бы
        единственный маршрут больших комментариев: отчёт с табуляцией в таблице
        либо файл с CRLF отвергался бы, и ни один тест не покраснел бы.
        """
        tool = self.load_tool()
        cases = {
            "tab": "| раунд\tвердикт |\n".encode(),
            "cr": "строка отчёта\r\n".encode(),
            "lone-cr": "строка отчёта\rхвост\n".encode(),
            "all-allowed": "| a\tb |\r\nхвост\n".encode(),
        }

        for label, body in cases.items():
            with self.subTest(label=label):
                self.capture_body.unlink(missing_ok=True)
                self.body_path.write_bytes(body)

                with self.gh_environment():
                    result = tool.publish_comment(TEST_PR, str(self.body_path))

                self.assertEqual(result, 0)
                self.assertEqual(self.capture_body.read_bytes(), body)

    def test_readiness_phrase_without_token_is_rejected_by_shared_policy(self):
        """Ломается, если publisher разрешит readiness без capability token."""
        tool = self.load_tool()
        policy = load_file_module("readiness_policy", POLICY)
        self.body_path.write_text("## ✅ Готов к merge\n", encoding="utf-8")

        with self.gh_environment(), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FINALIZE_PR_TOKEN", None)
            with self.assertRaises(tool.PublishError):
                tool.publish_comment(TEST_PR, str(self.body_path))

        merge_hook = load_file_module(
            "check_merge_ready_shared_policy",
            ROOT / ".claude" / "hooks" / "check-merge-ready.py",
        )
        self.assertIs(merge_hook.is_forbidden, policy.is_forbidden)
        self.assertFalse(self.capture_body.exists())

    def test_readiness_phrase_with_inline_process_token_is_published(self):
        """Ломается, если publisher не видит token своего процесса finalize-pr."""
        tool = self.load_tool()
        body = "## ✅ Готов к merge\n".encode()
        self.body_path.write_bytes(body)

        with self.gh_environment(), mock.patch.dict(
            os.environ, {"FINALIZE_PR_TOKEN": "1"}
        ):
            result = tool.publish_comment(TEST_PR, str(self.body_path))

        self.assertEqual(result, 0)
        self.assertEqual(self.capture_body.read_bytes(), body)

    def test_negation_is_clause_local(self):
        """Ломается, если отрицание предыдущей клаузы отменяет декларацию после неё."""
        tool = self.load_tool()
        bodies = (
            "Not ready to merge; ready to merge.\n",
            "Not ready to merge yet ready to merge.\n",
            "Not ready to merge though ready to merge.\n",
            "Not ready to merge — ready to merge.\n",
            "Не готов к merge всё же готов к merge.\n",
            "Не готов к merge всё-таки готов к merge.\n",
            "Не готов к merge — готов к merge.\n",
        )

        for body in bodies:
            with self.subTest(body=body):
                self.body_path.write_text(body, encoding="utf-8")
                with self.gh_environment(), mock.patch.dict(
                    os.environ, {}, clear=False
                ):
                    os.environ.pop("FINALIZE_PR_TOKEN", None)
                    with self.assertRaises(tool.PublishError):
                        tool.publish_comment(TEST_PR, str(self.body_path))

                self.assertFalse(self.capture_body.exists())

    def test_shell_like_prefix_is_not_a_markdown_blockquote(self):
        """Ломается, если raw body получает shell-only blockquote exemption."""
        tool = self.load_tool()
        self.body_path.write_text("body='> ready to merge'", encoding="utf-8")

        with self.gh_environment(), self.assertRaises(tool.PublishError):
            tool.publish_comment(TEST_PR, str(self.body_path))

        self.assertFalse(self.capture_body.exists())

    def test_markdown_blockquote_remains_allowed(self):
        """Ломается, если policy перестанет отличать настоящий Markdown blockquote."""
        tool = self.load_tool()
        body = "> ready to merge\n".encode()
        self.body_path.write_bytes(body)

        with self.gh_environment():
            result = tool.publish_comment(TEST_PR, str(self.body_path))

        self.assertEqual(result, 0)
        self.assertEqual(self.capture_body.read_bytes(), body)

    def test_gh_exit_code_is_preserved(self):
        """Ломается, если publisher скрывает ошибку gh или заменяет её код."""
        tool = self.load_tool()
        self.body_path.write_text("нейтральный отчёт\n", encoding="utf-8")

        with self.gh_environment(exit_code=37):
            result = tool.publish_comment(TEST_PR, str(self.body_path))

        self.assertEqual(result, 37)
        self.assertEqual(self.capture_body.read_bytes(), self.body_path.read_bytes())

    def test_invalid_pr_number_is_rejected_before_gh(self):
        """Ломается, если PR argument может превратиться в опцию gh."""
        tool = self.load_tool()
        self.body_path.write_text("нейтральный отчёт\n", encoding="utf-8")

        with self.gh_environment():
            for value in ("", "0", "01", "-1", "--repo", "12x", "9" * 5000):
                with self.subTest(value=value), self.assertRaises(tool.PublishError):
                    tool.publish_comment(value, str(self.body_path))

        self.assertFalse(self.capture_body.exists())

    def test_cli_error_does_not_echo_body(self):
        """Ломается, если validation diagnostic раскрывает тело комментария."""
        tool = self.load_tool()
        secret = "SECRET-BODY ready to merge"
        self.body_path.write_text(secret, encoding="utf-8")

        with mock.patch.object(sys, "stderr") as stderr:
            result = tool.main([TEST_PR, str(self.body_path)])

        self.assertEqual(result, tool.EXIT_REJECTED)
        rendered = "".join(str(call) for call in stderr.write.call_args_list)
        self.assertNotIn(secret, rendered)

    def _snippet_workdir(self, label: str) -> Path:
        """Отдельное рабочее дерево прогона сниппета.

        Сниппеты читают и пишут относительные пути (`contract.txt`, `task.txt`,
        `.review-responses/`) и находят publisher через `git rev-parse
        --show-toplevel`. Прогон в рабочей копии затирал бы и удалял файлы живого
        внешнего ревью с теми же именами, а два параллельных прогона дрались бы за
        них. Поэтому каждому сниппету отводится собственный git-репозиторий в
        песочнице, а `.claude` подключается в него ссылкой — рабочее дерево
        проекта тест не трогает вовсе.
        """
        workdir = self.sandbox / f"work-{label}"
        workdir.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(workdir)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (workdir / ".claude").symlink_to(ROOT / ".claude")
        return workdir

    def _external_review_fixtures(self, workdir: Path, head: str) -> None:
        """Файлы, которые Шаг 5.3 читает байт-в-байт при сборке отчёта."""
        raw_dir = workdir / ".review-responses"
        raw_dir.mkdir()
        for fixture, content in (
            (workdir / "contract.txt", "контракт прохода\n"),
            (workdir / "task.txt", "задание ревьюеру\n"),
            (raw_dir / f"mode-a-reviewer-a-{head}.md", "raw Reviewer A\n"),
            (raw_dir / f"mode-a-reviewer-b-{head}.md", "raw Reviewer B\n"),
        ):
            fixture.write_text(content, encoding="utf-8")



if __name__ == '__main__':
    unittest.main()
