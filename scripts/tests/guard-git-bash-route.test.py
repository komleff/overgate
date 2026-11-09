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
        for name, value in (("os_name", lambda: "nt"), ("_hook_environ", lambda: self.hook_env),
                            ("_is_file", files(*GFW_FILES)), ("_launch", self.launch)):
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
        self.assertEqual(args[1:], ["-s"], "argv git не идёт командной строкой Windows")
        self.assertIn('exec git "$@"', kwargs.get("input", ""))
        count = int(env["OVERGATE_GUARD_GIT_ARGC"])
        argv = [env[f"OVERGATE_GUARD_GIT_ARG_{index}"] for index in range(count)]
        child_env = {key: value for key, value in env.items() if not key.startswith("OVERGATE_GUARD_GIT_")}
        return REAL_RUN([GIT, *argv], env=child_env, cwd=kwargs.get("cwd"), stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, text=True, encoding="utf-8")

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
                # Окружение команды получает только запущенный bash для git.
                self.assertEqual(self.calls[0][1].get("CLAUDE_CODE_GIT_BASH_PATH"), evil)

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
