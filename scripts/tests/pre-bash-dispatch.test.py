#!/usr/bin/env python3
"""Единственная запись PreToolUse(Bash) из настоящего settings.json и диспетчер pre-bash.sh.

Запись исполняется так, как её исполняет Claude Code: `[<bash>, "-c", <текст записи>]`
из нативного процесса, payload на stdin, заданные cwd и CLAUDE_PROJECT_DIR. На Windows
это даёт ту же семантику разбора командной строки, что у хуков (пара `\\` в аргументе
схлопывается — «канарейка» ниже это доказывает), поэтому единица запускается нативно
(`py -3 scripts/tests/pre-bash-dispatch.test.py`), а не только в контейнере.

Инварианты:
  - ровно одна запись Bash, без обратных слэшей, ссылается на диспетчер, предел 600 с;
  - в корне checkout: чтение проходит при любой форме CLAUDE_PROJECT_DIR; публикация
    merge-readiness и коммит с красными тестами блокируются кодом 2;
  - запись ищет диспетчер только в каталоге сессии: из подпапки checkout и из чужого
    каталога проходит только `cd <корень>`, остальное — 2;
  - сообщения несут факты (ROOT/PWD/CLAUDE_PROJECT_DIR) и команду восстановления;
  - мутации записи и диспетчера красят набор.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / ".claude" / "settings.json"
DISPATCHER = ROOT / ".claude" / "hooks" / "pre-bash.sh"
WINDOWS = os.name == "nt"


def git_bash() -> str:
    """Git Bash по полному пути: голое имя из нативного процесса уходит в WSL-релей System32."""
    if not WINDOWS:
        return "bash"
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / "bash.exe"
        if candidate.is_file() and "system32" not in str(candidate).lower():
            return str(candidate)
    for candidate in (r"C:\Program Files\Git\usr\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe"):
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("Git Bash не найден")


BASH = git_bash()


def bash_entries() -> list[dict]:
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return [hook for entry in data["hooks"]["PreToolUse"]
            if entry.get("matcher") == "Bash" for hook in entry["hooks"]]


ENTRY = bash_entries()[0]["command"] if bash_entries() else ""


def run(command_text: str, payload_command: str, cwd: Path | str, project_dir: str | None = None,
        extra_env: dict | None = None, timeout: int = 120) -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    # Гейт коммита экспортирует сужение окна набору тестов; унаследованное значение
    # исказило бы сценарии бюджета (Code Review, находка 2).
    env.pop("OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS", None)
    # Python-проверки печатают по-русски: кодировка задаётся явно, как в settings.json (env).
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    if extra_env:
        env.update(extra_env)
    # Claude Code передаёт payload без \u-экранирования (JSON.stringify): диспетчер сверяет
    # команду восстановления с корнем буквально, и с кириллицей в пути экранирование
    # фикстуры давало бы ложное расхождение.
    payload = json.dumps({"tool_input": {"command": payload_command}, "cwd": str(cwd)}, ensure_ascii=False)
    proc = subprocess.run([BASH, "-c", command_text], input=payload, cwd=str(cwd), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    return proc.returncode, proc.stderr


def make_tree(mutation: tuple[str, str] | None = None, drop: str | None = None) -> Path:
    """Временный git-репозиторий с копией .claude/hooks и .claude/tools."""
    tree = Path(tempfile.mkdtemp(prefix="overgate-pre-bash-"))
    for sub in ("hooks", "tools"):
        shutil.copytree(ROOT / ".claude" / sub, tree / ".claude" / sub,
                        ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
    subprocess.run(["git", "init", "-q", str(tree)], check=True)
    subprocess.run(["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    verifier=tree/".agents/project/verify.sh"
    verifier.parent.mkdir(parents=True, exist_ok=True)
    verifier.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    if drop:
        (tree / ".claude" / "hooks" / drop).unlink()
    if mutation:
        target = tree / ".claude" / "hooks" / "pre-bash.sh"
        source = target.read_text(encoding="utf-8")
        assert source.count(mutation[0]) == 1, f"мутация неприменима: {mutation[0]!r}"
        target.write_text(source.replace(mutation[0], mutation[1]), encoding="utf-8", newline="\n")
    return tree


OUTSIDE = Path(tempfile.mkdtemp(prefix="overgate-outside-"))
BLOCK_MARKERS = ("CLAUDE_PROJECT_DIR=[", "PWD=[", "cd ")
# Каталог с оператором оболочки в имени и подложенным файлом диспетчера: `cd <OUTSIDE>/x;true`
# для оболочки — две команды, для проверки формы восстановления — не путь (Code Review, круг 1).
TRAP = OUTSIDE / "x;true"
(TRAP / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
(TRAP / ".claude" / "hooks" / "pre-bash.sh").write_text("exit 0\n", encoding="utf-8")


class StaticInvariants(unittest.TestCase):
    def test_exactly_one_entry_without_backslashes(self):
        hooks = bash_entries()
        self.assertEqual(len(hooks), 1, "записей PreToolUse с matcher Bash должно быть ровно одна")
        self.assertNotIn("\\", ENTRY, "обратный слэш в записи схлопывается при запуске из нативного процесса")
        self.assertNotIn("'", ENTRY.split("bash -c '", 1)[1].rstrip("'"),
                         "одинарная кавычка внутри записи оборвёт её текст")
        self.assertIn(".claude/hooks/pre-bash.sh", ENTRY)
        self.assertEqual(hooks[0].get("timeout"), 600, "предел записи — бюджет гейта тестов")
        self.assertTrue(DISPATCHER.is_file())

    def test_canary_backslash_pair_semantics(self):
        """На Windows пара `\\` в аргументе схлопывается (код 2), на POSIX — нет (код 0)."""
        canary = 'X=D:/a/b; if [ "${X//\\\\//}" = "$X" ]; then exit 0; fi; exit 2'
        code, _ = run(canary, "true", ROOT)
        self.assertEqual(code, 2 if WINDOWS else 0, "запуск не повторяет семантику Claude Code на этой платформе")


class RootScenarios(unittest.TestCase):
    """Каталог сессии — корень checkout: диспетчер найден, проверки работают."""

    def test_read_passes_with_any_project_dir_form(self):
        forms = [None, str(ROOT), str(OUTSIDE / "nope")]
        if WINDOWS:
            forms += [str(ROOT).replace("\\", "/"), str(ROOT).lower()]
        for form in forms:
            with self.subTest(project_dir=form):
                code, err = run(ENTRY, "git log -1 --oneline", ROOT, form)
                self.assertEqual(code, 0, err)

    def test_merge_readiness_publication_is_blocked(self):
        code, err = run(ENTRY, 'gh pr comment 1 --body "ready to merge"', ROOT, str(ROOT))
        self.assertEqual(code, 2, err)

    def test_commit_follows_test_gate_verdict(self):
        tree=make_tree()
        verifier=tree/".agents/project/verify.sh"
        verifier.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
        code, err = run(ENTRY, "git commit -m x", tree, str(tree))
        self.assertEqual(code, 2, err)
        self.assertIn("тесты падают", err)
        verifier.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
        code, err = run(ENTRY, "git commit -m x", tree, str(tree))
        self.assertEqual(code, 0, err)


class SessionDirectory(unittest.TestCase):
    """Каталог сессии без диспетчера (подпапка checkout или чужой каталог): только cd в корень."""

    def test_only_cd_to_checkout_root_passes(self):
        root = ROOT.as_posix()
        table = {
            f"cd {root}": 0,
            f"cd {OUTSIDE.as_posix()}": 2, f"cd {root} && ls": 2, f'cd "{root}"': 2, "cd": 2,
            f"cd -P {root}": 2, f"cd {root} -P": 2, f"cd {TRAP.as_posix()}": 2,
            f"pushd {root}": 2, "ls": 2, "git log -1 --oneline": 2, "git commit -m x": 2,
            "git push origin main": 2, "gh pr comment 1 --body hi": 2, 'bash -c "git ci -m x"': 2,
        }
        # Переменная не влияет на поиск диспетчера: не задана, указывает на корень или мимо.
        cases = ((OUTSIDE, None), (OUTSIDE, str(OUTSIDE / "nope")), (ROOT / "scripts", str(ROOT)))
        for cwd, project_dir in cases:
            for command, expected in table.items():
                with self.subTest(cwd=str(cwd), project_dir=project_dir, command=command):
                    code, err = run(ENTRY, command, cwd, project_dir)
                    self.assertEqual(code, expected, err)
                    if expected == 2:
                        for marker in BLOCK_MARKERS:
                            self.assertIn(marker, err)

    def test_printed_recovery_command_passes(self):
        """Из подпапки подсказка называет корень, и напечатанная команда проходит сама."""
        code, err = run(ENTRY, "ls", ROOT / "scripts", None)
        self.assertEqual(code, 2, err)
        recovery = err.split("Восстановление: ", 1)[1].splitlines()[0].strip()
        self.assertTrue(recovery.startswith("cd "), recovery)
        code, err = run(ENTRY, recovery, ROOT / "scripts", None)
        self.assertEqual(code, 0, err)

    def test_complex_root_recovery_and_exact_literal_parser(self):
        for name in ('space path','кириллица','path(parentheses)',"quote'path",'dollar$path'):
            with self.subTest(name=name):
                # TemporaryDirectory снимает readonly с Git objects на NTFS;
                # ошибки очистки не игнорируются и остаются провалом fixture.
                with tempfile.TemporaryDirectory(prefix="overgate-path-case-", ignore_cleanup_errors=False) as directory:
                    tree=make_tree();holder=Path(directory);target=holder/name
                    shutil.move(str(tree),target)
                    nested=target/'nested';nested.mkdir()
                    bash_root=subprocess.run([BASH,'-c','pwd -P'],cwd=target,capture_output=True,
                                             text=True,encoding='utf-8')
                    self.assertEqual(bash_root.returncode,0,bash_root.stderr)
                    root=bash_root.stdout.strip()
                    code,err=run(ENTRY,'ls',nested,str(OUTSIDE))
                    self.assertEqual(code,2,err)
                    recovery=err.split('Восстановление: ',1)[1].splitlines()[0]
                    expected="cd '"+root.replace("'", "'\"'\"'")+"'"
                    self.assertEqual(recovery,expected)
                    code,err=run(ENTRY,recovery,nested,str(OUTSIDE))
                    self.assertEqual(code,0,err)
                    completed=subprocess.run([BASH,'-c',recovery+' && pwd -P'],cwd=nested,capture_output=True,text=True,encoding='utf-8')
                    self.assertEqual(completed.returncode,0,completed.stderr)
                    self.assertEqual(completed.stdout.strip(),root)
                    for bad in (recovery+'; true',recovery+' && true',recovery+'\ntrue',
                                'cd "'+target.as_posix()+'"', 'cd '+target.as_posix(),
                                'cd $(echo '+target.as_posix()+')', 'cd $HOME', 'cd ../'):
                        code,err=run(ENTRY,bad,nested,str(target))
                        self.assertEqual(code,2,(bad,err))
                    sentinel=holder/'must-not-exist'
                    for bad in (recovery+'; touch '+sentinel.as_posix(),
                                'cd $(touch '+sentinel.as_posix()+')',
                                recovery+' && touch '+sentinel.as_posix()):
                        code,err=run(ENTRY,bad,nested,str(target))
                        self.assertEqual(code,2,(bad,err))
                        self.assertFalse(sentinel.exists(),bad)
                    code,err=run(ENTRY,'git log -1 --oneline',target,str(target))
                    self.assertEqual(code,0,err)

    def test_proven_root_blocks_second_checkout_and_unknown_root_hint_is_honest(self):
        own=make_tree();other=make_tree();nested=own/'nested';nested.mkdir()
        for command in ('cd '+other.as_posix(),"cd '"+other.as_posix()+"'"):
            code,err=run(ENTRY,command,nested,str(other))
            self.assertEqual(code,2,err)
        code,err=run(ENTRY,'ls',OUTSIDE,None)
        self.assertEqual(code,2,err)
        self.assertNotIn('Восстановление: cd ',err)
        self.assertIn('новую сессию',err)

    def test_full_json_field_is_parsed_without_first_match_shortcut(self):
        tree=make_tree();nested=tree/'nested';nested.mkdir()
        recovery="cd '"+tree.resolve().as_posix()+"'"
        payload=json.dumps({'tool_input':{'command':'ls','description':recovery},'other':{'command':recovery}})
        completed=subprocess.run([BASH,'-c',ENTRY],input=payload,cwd=nested,capture_output=True,
                                 text=True,encoding='utf-8')
        self.assertEqual(completed.returncode,2,completed.stderr)

    def test_git_environment_cannot_replace_cwd_checkout_identity(self):
        own=make_tree();other=make_tree();nested=own/'nested';nested.mkdir()
        def recovery_for(tree):
            completed=subprocess.run([BASH,'-c','pwd -P'],cwd=tree,capture_output=True,
                                     text=True,encoding='utf-8')
            self.assertEqual(completed.returncode,0,completed.stderr)
            return "cd '"+completed.stdout.strip().replace("'", "'\"'\"'")+"'"
        own_recovery=recovery_for(own)
        other_recovery=recovery_for(other)
        env={'GIT_DIR':str(other/'.git'),'GIT_WORK_TREE':str(other)}
        code,err=run(ENTRY,own_recovery,nested,str(other),env)
        self.assertEqual(code,0,err)
        code,err=run(ENTRY,other_recovery,nested,str(other),env)
        self.assertEqual(code,2,err)

    @unittest.skipIf(WINDOWS, "Windows interpreter fallback is covered by native QA")
    def test_recovery_needs_no_optional_node_binary(self):
        tree=make_tree();nested=tree/'nested';nested.mkdir()
        with tempfile.TemporaryDirectory(prefix='overgate-no-node-') as directory:
            for name in ('bash','cat','git','python3'):
                found=shutil.which(name)
                self.assertIsNotNone(found)
                (Path(directory)/name).symlink_to(Path(found).resolve())
            recovery="cd '"+tree.resolve().as_posix()+"'"
            code,err=run(ENTRY,recovery,nested,None,{'PATH':directory})
            self.assertEqual(code,0,err)

    def test_windows_drive_spelling_only_maps_to_same_proven_root(self):
        prefix=' -c "import json,os,sys;'
        self.assertIn(prefix,ENTRY)
        parser='import json,os,sys;'+ENTRY.split(prefix,1)[1].split('" 2>/dev/null',1)[0]
        for root,command,expected in (
                ('/d/own/root','cd /d/own/root',0),
                ('/d/own/root','cd D:/own/root',0),
                ('D:/own/root','cd /d/own/root',0),
                ('D:/own/root','cd D:/own/root',0),
                ('D:/own/complex path',"cd '/d/own/complex path'",0),
                ('D:/own/root','cd C:/own/root',1),
                ('D:/own/root','cd /c/own/root',1),
                ('D:/own/root','cd D:/other/root',1),
                ('D:/own/root','cd D:own/root',1),
                ('D:/own/root','cd /d/own/root && true',1)):
            with self.subTest(root=root,command=command):
                env={**os.environ,'R':root}
                payload=json.dumps({'tool_input':{'command':command}})
                result=subprocess.run([sys.executable,'-c',parser],input=payload,env=env,
                                      capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(result.returncode,expected,result.stderr)
                if expected==0:self.assertEqual(result.stdout,command[3:].strip("'"))

    @unittest.skipUnless(WINDOWS, 'native Git Bash drive aliases need Windows')
    def test_native_windows_same_root_drive_aliases(self):
        tree=make_tree();nested=tree/'nested';nested.mkdir()
        native=tree.resolve().as_posix()
        bash_root=subprocess.run([BASH,'-c','pwd -P'],cwd=tree,capture_output=True,
                                 text=True,encoding='utf-8')
        self.assertEqual(bash_root.returncode,0,bash_root.stderr)
        msys=bash_root.stdout.strip()
        if not native[1:3]==':/' or not all(ch.isascii() and
                (ch.isalnum() or ch in '_:/.-') for ch in native):
            self.skipTest('native fixture path is not a simple drive path')
        self.assertTrue(msys.startswith('/'+native[0].lower()+'/'),msys)
        for path in (native,msys):
            with self.subTest(path=path):
                code,err=run(ENTRY,'cd '+path,nested,None)
                self.assertEqual(code,0,err)
        other='D' if native[0].upper()!='D' else 'C'
        for path in (other+native[1:],'/'+other.lower()+msys[2:]):
            with self.subTest(foreign=path):
                code,err=run(ENTRY,'cd '+path,nested,None)
                self.assertEqual(code,2,err)

    def test_relative_cd_into_checkout_is_blocked(self):
        """Из родителя checkout `cd <имя каталога>` — относительный путь, не форма восстановления."""
        tree = make_tree()
        code, err = run(ENTRY, f"cd {tree.name}", tree.parent, str(tree))
        self.assertEqual(code, 2, err)


class CrossCheckout(unittest.TestCase):
    """Переменная указывает на повреждённый checkout A, сессия в корне checkout B: работают проверки B."""

    def test_guards_of_session_checkout_run(self):
        a = make_tree()
        (a / ".claude" / "tools" / "run-python.sh").unlink()
        b = make_tree()
        (b / ".claude" / "hooks" / "check-merge-ready.py").write_text(
            'import sys\nprint("B-GUARD", file=sys.stderr)\nsys.exit(2)\n', encoding="utf-8")
        code, err = run(ENTRY, "ls", b, str(a))
        self.assertEqual(code, 2, err)
        self.assertIn("B-GUARD", err)


GATE_STUB = (
    "#!/usr/bin/env bash\n"
    'L=570; O="${OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS-}"\n'
    'if [ -n "$O" ] && [ "$O" -lt "$L" ]; then L="$O"; fi\n'
    'if [ "${1-}" = "--print-timeout-seconds" ]; then echo "$L"; exit 0; fi\n'
    "cat >/dev/null\n"
    'echo "LEFT=[${OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS-}]" >&2\n'
    "exit 2\n"
)
SLOW_GUARD_STUB = "import time\ntime.sleep(3)\n"


def budget_tree(mutation=None) -> Path:
    """Дерево, где быстрая фаза занимает ≥ 3 с, а гейт печатает полученный остаток окна."""
    tree = make_tree(mutation=mutation)
    (tree / ".claude" / "hooks" / "check-merge-ready.py").write_text(SLOW_GUARD_STUB, encoding="utf-8")
    gate = tree / ".claude" / "hooks" / "check-tests-before-commit.sh"
    gate.write_text(GATE_STUB, encoding="utf-8", newline="\n")
    gate.chmod(0o755)
    return tree


def gate_tree(gate_text: str, mutation: tuple[str, str]) -> Path:
    """Дерево с заданной заглушкой гейта и одной правкой копии диспетчера, без медленных проверок."""
    tree = make_tree(mutation=mutation)
    gate = tree / ".claude" / "hooks" / "check-tests-before-commit.sh"
    gate.write_text(gate_text, encoding="utf-8", newline="\n")
    gate.chmod(0o755)
    return tree


def printed_left(err: str) -> int | None:
    marker = "LEFT=["
    if marker not in err:
        return None
    value = err.split(marker, 1)[1].split("]", 1)[0]
    return int(value) if value.isdigit() else None


class GateBudget(unittest.TestCase):
    """Окно прогона гейта сужается на длительность быстрой фазы (Plan Review, находка 1)."""

    def test_gate_window_shrinks_by_quick_phase(self):
        tree = budget_tree()
        code, err = run(ENTRY, "git commit -m x", tree, str(tree))
        self.assertEqual(code, 2, err)
        left = printed_left(err)
        self.assertIsNotNone(left, err)
        # Нагрузка машины только укрепляет утверждение: чем дольше быстрая фаза, тем меньше остаток.
        self.assertLessEqual(left, 570 - 4, "окно гейта не сужено на быструю фазу (≥ 3 с + 1 с округления)")
        self.assertGreater(left, 0)

    def test_existing_narrower_override_is_kept(self):
        tree = budget_tree()
        code, err = run(ENTRY, "git commit -m x", tree, str(tree),
                        {"OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS": "100"})
        self.assertEqual(code, 2, err)
        left = printed_left(err)
        self.assertIsNotNone(left, err)
        self.assertLessEqual(left, 96)

    def test_dispatcher_not_passing_remaining_budget_is_caught(self):
        tree = budget_tree(mutation=('export OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS="$GATE_LEFT"', ": no-export"))
        code, err = run(ENTRY, "git commit -m x", tree, str(tree))
        self.assertEqual(code, 2, err)
        self.assertIsNone(printed_left(err), "мутация без передачи остатка не ловится")

    # Сценарии зависания идут на копии диспетчера с уменьшенными пределами: проверяется,
    # что запрос предела и сам гейт обёрнуты помощником времени, а не величина 10 или 20 с.
    # Так единица укладывается в секунды и не тормозит гейт коммита.

    def test_gate_hanging_on_limit_query_is_blocked(self):
        """Зависший запрос предела режется пределом быстрой проверки, а не 600 с записи."""
        tree = gate_tree("#!/usr/bin/env bash\nsleep 30\nexit 0\n", ("QUICK_LIMIT=10", "QUICK_LIMIT=2"))
        started = time.monotonic()
        code, err = run(ENTRY, "git commit -m x", tree, str(tree), timeout=25)
        elapsed = time.monotonic() - started
        self.assertEqual(code, 2, err)
        self.assertIn("не сообщил предел", err)
        # Предел 2 с + секунда добивания помощника + быстрые проверки на загруженной машине.
        self.assertLessEqual(elapsed, 12, f"зависший запрос предела отрезан за {elapsed:.1f} с")

    def test_gate_hanging_in_run_is_blocked_by_outer_limit(self):
        """Гейт, зависший до своего помощника времени, режется внешним пределом «остаток + N с»."""
        hanging = GATE_STUB.replace("exit 2\n", "sleep 20\nexit 0\n")
        tree = gate_tree(hanging, ('"$((GATE_LEFT + 20))"', '"$((GATE_LEFT + 2))"'))
        code, err = run(ENTRY, "git commit -m x", tree, str(tree),
                        {"OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS": "10"}, timeout=40)
        self.assertEqual(code, 2, err)
        self.assertIn("не уложилась", err)
        unwrapped = gate_tree(hanging, ('sh "$TIMEOUT_HELPER" "$((GATE_LEFT + 20))" bash "$HOOK_DIR/check-tests-before-commit.sh"',
                                        'bash "$HOOK_DIR/check-tests-before-commit.sh"'))
        code, _ = run(ENTRY, "git commit -m x", unwrapped, str(unwrapped),
                      {"OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS": "10"}, timeout=40)
        self.assertEqual(code, 0, "гейт без внешнего предела не ловится")


class DispatcherMessages(unittest.TestCase):
    def test_missing_guard_file_blocks_with_facts(self):
        tree = make_tree(drop="check-merge-ready.py")
        code, err = run(ENTRY, "ls", tree, str(tree))
        self.assertEqual(code, 2, err)
        for marker in ("нет файла проверки", "ROOT=[", "PWD=[", "Восстановление"):
            self.assertIn(marker, err)
        # Напечатанная команда восстановления обязана проходить сама (Code Review, круг 3).
        recovery = err.split("Восстановление: ", 1)[1].splitlines()[0].strip()
        self.assertTrue(recovery.startswith("git -C "), recovery)
        code, err = run(ENTRY, recovery, tree, str(tree))
        self.assertEqual(code, 0, err)

    def test_dispatcher_blocking_its_own_recovery_command_is_caught(self):
        tree = make_tree(mutation=(") exit 0 ;;", ") : ;;"), drop="check-merge-ready.py")
        _, err = run(ENTRY, "ls", tree, str(tree))
        recovery = err.split("Восстановление: ", 1)[1].splitlines()[0].strip()
        code, _ = run(ENTRY, recovery, tree, str(tree))
        self.assertEqual(code, 2, "диспетчер, блокирующий собственную команду восстановления, не ловится")

    def test_guard_crash_blocks_with_facts(self):
        tree = make_tree()
        (tree / ".claude" / "hooks" / "check-merge-ready.py").write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
        code, err = run(ENTRY, "ls", tree, str(tree))
        self.assertEqual(code, 2, err)
        self.assertIn("кодом 7", err)


class Mutations(unittest.TestCase):
    """Каждое ослабление обязано дать красный исход хотя бы одного сценария выше."""

    def test_entry_passing_everything_in_degraded_mode_is_caught(self):
        mutated = ENTRY[: ENTRY.rindex("exit 2'")] + "exit 0'"
        self.assertNotEqual(mutated, ENTRY)
        code, _ = run(mutated, "git commit -m x", OUTSIDE, None)
        self.assertEqual(code, 0, "деградация, пропускающая всё, не ловится сценарием коммита")

    def test_entry_without_cd_target_check_is_caught(self):
        mutated = ENTRY.replace('[ -f "$T/.claude/hooks/pre-bash.sh" ]; then exit 0', "true; then exit 0", 1)
        self.assertNotEqual(mutated, ENTRY)
        # Windows TEMP может содержать short-name RUNNER~1: такая форма
        # не различает наличие проверки цели в принятом recovery parser.
        target=ROOT / "missing-dispatcher-target"
        self.assertFalse((target / ".claude/hooks/pre-bash.sh").exists())
        command=f"cd {target.as_posix()}"
        real,err=run(ENTRY,command,OUTSIDE,None)
        self.assertEqual(real,2,err)
        code, err = run(mutated, command, OUTSIDE, None)
        self.assertEqual(code, 0, "снятая проверка цели cd не ловится сценарием cd наружу: "+err)

    def test_entry_without_dispatcher_exec_is_caught(self):
        """Без exec диспетчера запись всегда в деградации, где проходит только cd; через
        диспетчер гейт публикации пропускает `gh pr view` — разница и ловит мутацию."""
        mutated = ENTRY.replace("exec bash", "true", 1)
        self.assertNotEqual(mutated, ENTRY)
        real, err = run(ENTRY, "gh pr view 1 --json state", ROOT, str(ROOT))
        self.assertEqual(real, 0, err)
        code, _ = run(mutated, "gh pr view 1 --json state", ROOT, str(ROOT))
        self.assertEqual(code, 2, "запись без диспетчера не ловится сценарием gh pr view")

    def test_dispatcher_ignoring_block_code_is_caught(self):
        tree = make_tree(mutation=("2) exit 2 ;;", "2) return 0 ;;"))
        code, _ = run(ENTRY, 'gh pr comment 1 --body "ready to merge"', tree, str(tree))
        self.assertEqual(code, 0, "диспетчер, игнорирующий код 2, не ловится")

    def test_entry_finding_dispatcher_outside_session_directory_is_caught(self):
        """Если запись ищет диспетчер по переменной, из подпапки проходили бы обычные команды."""
        mutated = ENTRY.replace("H=./.claude/hooks/pre-bash.sh", "H=${CLAUDE_PROJECT_DIR-.}/.claude/hooks/pre-bash.sh", 1)
        self.assertNotEqual(mutated, ENTRY)
        code, _ = run(mutated, "ls", ROOT / "scripts", str(ROOT))
        self.assertEqual(code, 0, "запись, ищущая диспетчер вне каталога сессии, не ловится")


if __name__ == "__main__":
    unittest.main(verbosity=2)
