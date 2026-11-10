#!/usr/bin/env python3
"""og-5l6 (AC-02): маршрут git guard на Windows и выбор Git Bash.

Модульный тест маршрута `nt` на любой ОС: подменяются `os_name`, окружение
процесса хука, проверка существования кандидатов и launcher. Launcher-подмена
разбирает протокол передачи argv (окружение + `bash -s`) и исполняет настоящий
git, поэтому решения guard проверяются на реальных alias. На Windows дополнительно
проверяется реальный Git Bash runner (обе раскладки покрыты модульно).
"""
from __future__ import annotations

import importlib.util
import ntpath
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = ROOT / ".claude/hooks/check-repository-mutation.py"
sys.path.insert(0, str(ROOT / "scripts/tests/lib"))
from claude_hooks import native_bash  # noqa: E402

GIT = shutil.which("git")
REAL_RUN = subprocess.run
GFW = "C:\\Program Files\\Git"
GFW_FILES = {
    GFW + "\\cmd\\git.exe",
    GFW + "\\mingw64\\bin\\git.exe",
    GFW + "\\bin\\git.exe",
    GFW + "\\bin\\bash.exe",
    GFW + "\\usr\\bin\\bash.exe",
}
STUBS = {
    "C:\\Windows\\System32\\bash.exe",
    "C:\\Users\\u\\AppData\\Local\\Microsoft\\WindowsApps\\bash.exe",
}


def load_guard():
    spec = importlib.util.spec_from_file_location("guard_under_test", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = load_guard()
ROUTE = GUARD.git_route


def files(*paths):
    known = {ntpath.normcase(p) for p in paths}
    return lambda path: ntpath.normcase(ntpath.normpath(path)) in known


class ResolverTests(unittest.TestCase):
    def resolve(self, path, existing, override=None):
        environ = {"PATH": path}
        if override is not None:
            environ["CLAUDE_CODE_GIT_BASH_PATH"] = override
        return ROUTE.resolve_bash(environ, files(*existing))

    def test_mingw_layout_from_git_bash_path(self):
        # PATH процесса хука, запущенного из Git Bash: <root>/mingw64/bin раньше остального.
        path = ";".join([GFW + "\\mingw64\\bin", GFW + "\\usr\\bin", "C:\\Windows\\System32"])
        self.assertEqual(self.resolve(path, GFW_FILES | STUBS), GFW + "\\bin\\bash.exe")

    def test_cmd_layout_from_native_path(self):
        path = ";".join(["C:\\Windows\\System32", GFW + "\\cmd"])
        self.assertEqual(self.resolve(path, GFW_FILES | STUBS), GFW + "\\bin\\bash.exe")

    def test_usr_bin_bash_when_bin_wrapper_absent(self):
        existing = GFW_FILES - {GFW + "\\bin\\bash.exe"}
        self.assertEqual(self.resolve(GFW + "\\cmd", existing), GFW + "\\usr\\bin\\bash.exe")

    def test_wsl_stubs_before_git_bash_are_not_selected(self):
        path = ";".join(["C:\\Windows\\System32", "C:\\Users\\u\\AppData\\Local\\Microsoft\\WindowsApps",
                         GFW + "\\mingw64\\bin"])
        self.assertEqual(self.resolve(path, GFW_FILES | STUBS), GFW + "\\bin\\bash.exe")

    def test_override_of_same_installation(self):
        for override in (GFW + "\\usr\\bin\\bash.exe", "c:/program files/git/bin/bash.exe"):
            with self.subTest(override=override):
                self.assertEqual(self.resolve(GFW + "\\cmd", GFW_FILES, override), override)

    def test_override_rejections(self):
        other = {"D:\\Git2\\bin\\bash.exe", "D:\\Git2\\usr\\bin\\bash.exe", "D:\\Git2\\cmd\\git.exe"}
        for override in ("C:\\Windows\\System32\\bash.exe",
                         "C:\\Users\\u\\AppData\\Local\\Microsoft\\WindowsApps\\bash.exe",
                         "D:\\Git2\\bin\\bash.exe", "C:\\msys64\\usr\\bin\\bash.exe",
                         "/c/Program Files/Git/bin/bash.exe", "bash.exe"):
            with self.subTest(override=override):
                with self.assertRaises(ROUTE.RouteError):
                    self.resolve(GFW + "\\cmd", GFW_FILES | STUBS | other, override)

    def test_missing_override_file(self):
        with self.assertRaises(ROUTE.RouteError):
            self.resolve(GFW + "\\cmd", GFW_FILES - {GFW + "\\bin\\bash.exe"}, GFW + "\\bin\\bash.exe")

    def test_non_git_for_windows_installations(self):
        cases = {
            "Cygwin": ("C:\\cygwin64\\bin", {"C:\\cygwin64\\bin\\git.exe", "C:\\cygwin64\\bin\\bash.exe"}),
            "MSYS2 usr": ("C:\\msys64\\usr\\bin", {"C:\\msys64\\usr\\bin\\git.exe", "C:\\msys64\\usr\\bin\\bash.exe"}),
            "MSYS2 mingw": ("C:\\msys64\\mingw64\\bin", {"C:\\msys64\\mingw64\\bin\\git.exe",
                                                        "C:\\msys64\\usr\\bin\\bash.exe"}),
            "no git": ("C:\\Windows\\System32", STUBS),
            "no bash": (GFW + "\\cmd", {GFW + "\\cmd\\git.exe"}),
        }
        for name, (path, existing) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ROUTE.RouteError):
                    self.resolve(path, existing)

    def test_first_git_of_other_installation_is_not_skipped(self):
        # Реальный запуск возьмёт первый git.exe; неоднозначность не обходится поиском дальше.
        path = ";".join(["C:\\msys64\\mingw64\\bin", GFW + "\\cmd"])
        existing = GFW_FILES | {"C:\\msys64\\mingw64\\bin\\git.exe", "C:\\msys64\\usr\\bin\\bash.exe"}
        with self.assertRaises(ROUTE.RouteError):
            self.resolve(path, existing)

    def test_relative_and_msys_path_entries_are_ignored(self):
        path = ";".join([".", "/usr/bin", GFW + "\\cmd"])
        existing = GFW_FILES | {".\\git.exe", "\\usr\\bin\\git.exe"}
        self.assertEqual(self.resolve(path, existing), GFW + "\\bin\\bash.exe")


@unittest.skipIf(GIT is None, "git is required")
class NtRouteGuardTests(unittest.TestCase):
    """Решения guard на маршруте `nt` с подменённым launcher и настоящим git."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "alias-repo")
        REAL_RUN([GIT, "init", "-q", self.repo], check=True)
        for name, value in (("land", "!gh pr merge 756 --squash"), ("safe", "!git status --short"),
                            ("ship", "push origin main")):
            REAL_RUN([GIT, "-C", self.repo, "config", f"alias.{name}", value], check=True)
        self.calls = []
        self.behavior = "git"
        self.hook_env = {"PATH": GFW + "\\mingw64\\bin;" + GFW + "\\usr\\bin"}
        ROUTE._RESOLVED.clear()
        self.addCleanup(ROUTE._RESOLVED.clear)
        patches = [("os_name", lambda: "nt"), ("_hook_environ", lambda: self.hook_env),
                   ("_is_file", files(*GFW_FILES)), ("_launch", self.launch)]
        if os.name != "nt":
            patches.append(("GIT_BASH_OSTYPES", "*"))  # OSTYPE настоящего bash — darwin/linux-gnu
        for name, value in patches:
            patcher = mock.patch.object(ROUTE, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def launch(self, args, **kwargs):
        env = dict(kwargs.get("env") or {})
        self.calls.append((list(args), env, kwargs.get("cwd"), kwargs.get("input")))
        if self.behavior == "oserror":
            raise OSError("launch failed")
        if self.behavior == "not-msys":
            return subprocess.CompletedProcess(args, ROUTE.EXIT_NOT_MSYS, "", None)
        self.assertEqual(args[-1], "-s", "argv git не идёт командной строкой Windows")
        self.assertIn('git "$@"', kwargs.get("input", ""))
        # Протокол исполняет настоящий bash (на Windows — Git Bash), подменён только путь.
        return REAL_RUN([native_bash(), *args[1:]], **kwargs)

    def verdict(self, command):
        try:
            return "block" if GUARD._check_command(command) else "allow"
        except GUARD.GuardError as exc:
            return "block: " + str(exc)

    def bash_paths(self):
        return {call[0][0] for call in self.calls}

    def test_dangerous_alias_blocks_through_hook_git_bash(self):
        self.assertTrue(self.verdict(f"git -C '{self.repo}' land").startswith("block"))
        self.assertTrue(self.verdict(f"git -C '{self.repo}' ship").startswith("block"))
        self.assertEqual(self.bash_paths(), {GFW + "\\bin\\bash.exe"})

    def test_safe_alias_allows_through_hook_git_bash(self):
        self.assertEqual(self.verdict(f"git -C '{self.repo}' safe"), "allow")
        self.assertEqual(self.bash_paths(), {GFW + "\\bin\\bash.exe"})
        self.assertTrue(self.calls)

    def test_command_assignments_do_not_change_bash_selection(self):
        evil = "C:\\Users\\u\\evil\\bash.exe"
        for command in (
            f"CLAUDE_CODE_GIT_BASH_PATH='{evil}' git -C '{self.repo}' land",
            f"env CLAUDE_CODE_GIT_BASH_PATH='{evil}' git -C '{self.repo}' land",
            f"PATH='C:\\Users\\u\\evil' CLAUDE_CODE_GIT_BASH_PATH='{evil}' git -C '{self.repo}' land",
        ):
            with self.subTest(command=command):
                self.calls.clear()
                self.assertTrue(self.verdict(command).startswith("block"))
                self.assertEqual(self.bash_paths(), {GFW + "\\bin\\bash.exe"})
                # Окружение команды доходит только до git (транспортом), не до процесса bash.
                bash_env = self.calls[0][1]
                self.assertNotIn("CLAUDE_CODE_GIT_BASH_PATH", bash_env)
                self.assertIn(f"CLAUDE_CODE_GIT_BASH_PATH={evil}",
                              [value for key, value in bash_env.items() if key.startswith("OVERGATE_GUARD_GIT_ENV_")])

    def test_hook_override_of_other_installation_blocks(self):
        self.hook_env["CLAUDE_CODE_GIT_BASH_PATH"] = "D:\\Git2\\bin\\bash.exe"
        result = self.verdict(f"git -C '{self.repo}' safe")
        self.assertTrue(result.startswith("block") and "different installations" in result, result)
        self.assertEqual(self.calls, [])

    def test_missing_git_bash_blocks(self):
        self.hook_env["PATH"] = "C:\\Windows\\System32"
        result = self.verdict(f"git -C '{self.repo}' safe")
        self.assertTrue(result.startswith("block") and "git.exe not found" in result, result)

    def test_launch_error_and_non_msys_bash_block(self):
        for behavior, reason in (("oserror", "launch failed"), ("not-msys", "not Git Bash")):
            with self.subTest(behavior=behavior):
                self.behavior = behavior
                result = self.verdict(f"git -C '{self.repo}' safe")
                self.assertTrue(result.startswith("block") and reason in result, result)

    def test_unreachable_git_dir_blocks_on_nt_route(self):
        missing = os.path.join(self.tmp.name, "missing", ".git")
        for command in (f"git --git-dir='{missing}' land", f"GIT_DIR='{missing}' git land"):
            with self.subTest(command=command):
                result = self.verdict(command)
                self.assertIn("cannot open the explicit repository context", result)

    def test_builtin_does_not_need_git_bash(self):
        self.hook_env["PATH"] = ""
        self.assertEqual(self.verdict("git status --short"), "allow")
        self.assertEqual(self.calls, [])


@unittest.skipIf(GIT is None, "git is required")
class NtRouteBashIsolationTests(unittest.TestCase):
    """Code Review PR #19, BLOCKER 1: окружение команды не управляет процессом bash.

    Маршрут `nt` исполняется настоящим bash (на macOS/Linux — локальным, на Windows —
    Git Bash): launcher подменяет только путь к bash. Переменные стартовой обработки
    bash из окружения команды не должны обрывать сборку argv: иначе lookup отвечал
    «нет alias», и опасная команда проходила.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "alias-repo")
        REAL_RUN([GIT, "init", "-q", self.repo], check=True)
        for name, value in (("land", "!gh pr merge 756 --squash"), ("safe", "!git status --short"),
                            ("ship", "push origin main")):
            REAL_RUN([GIT, "-C", self.repo, "config", f"alias.{name}", value], check=True)
        self.bash_env = os.path.join(self.tmp.name, "bash-env.sh")
        self.patches = [("os_name", lambda: "nt"), ("_hook_bash", lambda: GFW + "\\bin\\bash.exe"),
                        ("_launch", self.launch)]
        if os.name != "nt":
            # OSTYPE настоящего bash здесь darwin/linux-gnu; фильтр проверяется отдельно.
            self.patches.append(("GIT_BASH_OSTYPES", "*"))
        for name, value in self.patches:
            patcher = mock.patch.object(ROUTE, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def launch(self, args, **kwargs):
        self.assertEqual(args[0], GFW + "\\bin\\bash.exe")
        return REAL_RUN([native_bash(), *args[1:]], **kwargs)

    def verdict(self, command):
        try:
            return "block" if GUARD._check_command(command) else "allow"
        except GUARD.GuardError as exc:
            return "block: " + str(exc)

    def lookup(self, extra_env):
        env = dict(os.environ, **extra_env)
        return ROUTE.run_git(["-C", self.repo, "config", "--get", "alias.ship"], env=env, cwd=None)

    def write_bash_env(self, text):
        with open(self.bash_env, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    def test_bash_env_exit_does_not_hide_alias(self):
        self.write_bash_env("exit 1\n")
        for alias in ("ship", "land"):
            for command in (f"BASH_ENV='{self.bash_env}' git -C '{self.repo}' {alias}",
                            f"env BASH_ENV='{self.bash_env}' git -C '{self.repo}' {alias}",
                            f"ENV='{self.bash_env}' git -C '{self.repo}' {alias}"):
                with self.subTest(command=command):
                    self.assertTrue(self.verdict(command).startswith("block"))

    def test_bash_env_cannot_reset_transport(self):
        self.write_bash_env("OVERGATE_GUARD_GIT_ARGC=0\nOVERGATE_GUARD_GIT_ENVC=0\n")
        self.assertTrue(self.verdict(f"BASH_ENV='{self.bash_env}' git -C '{self.repo}' ship").startswith("block"))

    def test_xtrace_ps4_arithmetic_does_not_break_argv(self):
        for ps4 in ("$((i=99))", "$((__overgate_i=99))"):
            with self.subTest(ps4=ps4):
                command = f"env SHELLOPTS=xtrace PS4='{ps4}' git -C '{self.repo}' ship"
                self.assertTrue(self.verdict(command).startswith("block"))

    def test_startup_variables_do_not_reach_bash(self):
        self.write_bash_env("exit 1\n")
        cases = (
            {"BASH_ENV": self.bash_env},
            {"POSIXLY_CORRECT": "1", "ENV": self.bash_env},
            {"SHELLOPTS": "xtrace", "PS4": "$((__overgate_i=99))"},
            {"SHELLOPTS": "xtrace", "PS4": "$((i=99))", "BASH_XTRACEFD": "1"},
            {"BASHOPTS": "extdebug", "BASH_COMPAT": "31"},
            {"BASH_FUNC_exec%%": "() { exit 1; }"},
            {"BASH_FUNC_set%%": "() { exit 1; }"},
            {"BASH_FUNC_[%%": "() { return 1; }"},
        )
        for hostile in cases:
            with self.subTest(hostile=sorted(hostile)):
                proc = self.lookup(hostile)
                self.assertEqual((proc.returncode, proc.stdout.strip()), (0, "push origin main"))

    def test_ostype_from_command_does_not_pass_filter(self):
        if os.name == "nt":
            self.skipTest("на Windows настоящий OSTYPE уже msys/cygwin; фильтр проверен на POSIX")
        with mock.patch.object(ROUTE, "GIT_BASH_OSTYPES", "msys*|cygwin*"):
            with self.assertRaises(ROUTE.RouteError):
                self.lookup({"OSTYPE": "msys"})
            self.assertIn("not Git Bash", self.verdict(f"OSTYPE=msys git -C '{self.repo}' safe"))

    def test_safe_alias_allows_and_command_env_reaches_git(self):
        self.assertEqual(self.verdict(f"git -C '{self.repo}' safe"), "allow")
        config = os.path.join(self.tmp.name, "global.gitconfig")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write("[alias]\n\tcfgland = !gh pr merge 756 --squash\n\tcfgsafe = !git status --short\n")
        self.assertTrue(self.verdict(f"GIT_CONFIG_GLOBAL='{config}' git -C '{self.repo}' cfgland").startswith("block"))
        self.assertEqual(self.verdict(f"GIT_CONFIG_GLOBAL='{config}' git -C '{self.repo}' cfgsafe"), "allow")
        self.assertEqual(self.verdict(f"git -C '{self.repo}' cfgland"), "allow")

    def test_command_environment_reaches_git(self):
        # Имена `name`/`i` (прежние служебные переменные скрипта) не мешают окружению git.
        proc = ROUTE.run_git(["var", "GIT_EDITOR"], env=dict(os.environ, name="kept", i="kept",
                                                            GIT_EDITOR="og-editor"), cwd=self.repo)
        self.assertEqual(proc.stdout.strip(), "og-editor")


class TransportTests(unittest.TestCase):
    """argv доходит до программы без изменений, транспортные переменные ей не видны."""

    ARGV = ["a b", "it's", 'say "hi"', "back\\slash", "*", "?", "$HOME", "", "-C", "line\nbreak",
            "/d/x y", "кириллица", "'", '"', "\\"]

    def run_script(self, argv, program):
        script = ROUTE.bash_script(program=program, ostype="*")
        return REAL_RUN([native_bash(), "-s"], input=script.encode("utf-8"),
                        env=ROUTE.bash_environment(argv, os.environ), stdout=subprocess.PIPE, check=True).stdout

    def test_argv_round_trip(self):
        output = self.run_script(self.ARGV, "printf '%s\\0'")
        self.assertEqual(output.split(b"\0")[:-1], [arg.encode("utf-8") for arg in self.ARGV])

    def test_transport_variables_are_unset(self):
        output = self.run_script([], "env").decode("utf-8", "replace")
        self.assertNotIn("OVERGATE_GUARD_GIT_", output)

    @unittest.skipIf(os.name == "nt", "на Windows OSTYPE Git Bash — msys/cygwin")
    def test_default_ostype_filter_rejects_non_msys_shell(self):
        # Фильтр по умолчанию (msys*|cygwin*) отвергает bash Linux/macOS/WSL (linux-gnu, darwin).
        result = REAL_RUN([native_bash(), "-s"], input=ROUTE.bash_script(program="true"),
                          env=ROUTE.bash_environment([], os.environ), stdout=subprocess.PIPE, text=True)
        self.assertEqual(result.returncode, ROUTE.EXIT_NOT_MSYS)

    def test_foreign_shell_is_refused(self):
        script = ROUTE.bash_script(program="true", ostype="og-no-such-ostype")
        result = REAL_RUN([native_bash(), "-s"], input=script, env=ROUTE.bash_environment([], os.environ),
                          stdout=subprocess.PIPE, text=True)
        self.assertEqual(result.returncode, ROUTE.EXIT_NOT_MSYS)


@unittest.skipUnless(os.name == "nt", "real Git for Windows route")
class RealWindowsRouteTests(unittest.TestCase):
    def test_hook_environment_resolves_git_bash_and_runs_git(self):
        ROUTE._RESOLVED.clear()
        bash = ROUTE.resolve_bash(os.environ, os.path.isfile)
        self.assertTrue(ntpath.normcase(bash).endswith(("\\bin\\bash.exe", "\\usr\\bin\\bash.exe")), bash)
        proc = ROUTE.run_git(["--version"], env=dict(os.environ), cwd=None)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.startswith("git version"), proc.stdout)


if __name__ == "__main__":
    unittest.main()
