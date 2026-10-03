#!/usr/bin/env python3
"""Shared local guard for repository mutations used by Claude and Codex.

Reads a PreToolUse JSON payload from stdin. Exit 0 = allow, exit 2 = block.
Command splitting reuses the existing shell parser package in this directory.
"""

from __future__ import annotations

import os
import sys

EXIT_BLOCK = 2

# The hook directory must not participate in normal module resolution. Python
# puts the script directory first on sys.path; without this closure a sibling
# json.py/re.py can replace stdlib before policy evaluation. Sibling U2 modules
# are loaded explicitly by path below.
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
    import re
    import subprocess
    from typing import Iterable, List, Sequence
    from urllib.parse import urlsplit
except Exception as exc:
    print(
        f"BLOCKED fail-secure: repository mutation guard import failed: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(EXIT_BLOCK)


def _load_sibling(name: str):
    path = os.path.join(_HOOK_DIR, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"shared mutation guard: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


try:
    parser = _load_sibling("commit_command_classifier")
except Exception as exc:
    print(
        f"BLOCKED fail-secure: repository mutation parser package not loaded: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(EXIT_BLOCK)

_PROTECTED = {"main", "master", "refs/heads/main", "refs/heads/master"}
_FORCE_FLAGS = {
    "-f", "--force", "--force-with-lease", "--mirror", "--all", "--branches",
    "--force-if-includes",
}
_EXEC_WRAPPERS = {"env", "command", "exec", "nohup", "sudo", "time"}
_SHELLS = {"bash", "sh", "dash", "zsh"}
_GH_BUILTINS = {
    "alias", "api", "attestation", "auth", "browse", "cache", "codespace",
    "completion", "config", "extension", "gist", "gpg-key", "help", "issue",
    "label", "org", "pr", "project", "release", "repo", "run", "search",
    "secret", "ssh-key", "status", "variable", "workflow",
}
# Сам gh различает регистр у всех опций: `gh alias list --Help` он отвергает как
# неизвестный флаг. Сверка ниже эту строгость не повторяет — длинные написания
# по-прежнему приводятся к нижнему регистру, как было до правки ложных блоков:
# `--METHOD` gh отвергнет, а разбор здесь примет его за `--method`. Поведение
# оставлено прежним намеренно, менять его этот PR не берётся.
# Короткие однобуквенные сверяются точно, и вот почему: у них регистр несёт
# разный смысл (`-H` — заголовок, `-X` — метод; `-h` — справка, опции `-x` нет),
# поэтому слияние написаний сделало бы `gh api -h …` мягче, чем сейчас. Раньше к
# нижнему регистру приводилось слово целиком, и `-X`/`-H` не находились в наборе
# вовсе — отсюда и брался ложный блок на командах чтения.
_GH_API_VALUE_OPTIONS = {
    "-X", "--method", "-H", "--header", "-f", "--raw-field", "-F", "--field",
    "--input", "--cache", "--preview",
    # Опции вывода: значение потребляется как формат и запросом не является.
    "-q", "--jq", "-t", "--template",
}
# Написание `-X` сегодня блокируется целиком (его не было в наборе выше).
# Распознаётся ровно доказанный GET; любое другое значение остаётся блоком, но
# уже с причиной про метод. Длинное написание `--method` этой проверки НЕ
# получает: сегодня оно не-GET пропускает, и закрытие этого пробела — U2-u1zol.
_GH_API_PROVEN_GET_OPTIONS = {"-X"}
_GH_API_FLAG_OPTIONS = {"--paginate", "--slurp", "--silent", "--verbose", "--include"}
_GIT_CONTEXT_ENV_NAMES = {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_NAMESPACE"}
# Значения ниже Git исполняет сам (редактор, pager, ssh, credential helper,
# fsmonitor, внешний diff), поэтому командная строка — носитель команды.
# Литеральная защищённая мутация в таком значении блокируется на любом пути
# передачи; недоказуемое (динамическое) значение исполняемого ключа — fail-closed.
_GIT_EXEC_CONFIG_KEYS = {
    "core.editor", "core.pager", "core.sshcommand", "core.fsmonitor",
    "core.hookspath", "core.askpass", "core.gitproxy", "credential.helper",
    "diff.external", "sequence.editor", "gpg.program", "gpg.ssh.program",
}
# Ключи вида section.<name>.key с тем же смыслом: credential.<url>.helper,
# diff.<driver>.command, filter.<name>.clean/smudge/process, *tool.<tool>.cmd.
_GIT_EXEC_CONFIG_PATTERNS = {
    ("credential", "helper"), ("diff", "command"), ("diff", "textconv"),
    ("filter", "clean"), ("filter", "smudge"), ("filter", "process"),
    ("mergetool", "cmd"), ("difftool", "cmd"), ("merge", "driver"),
    ("remote", "uploadpack"), ("remote", "receivepack"), ("remote", "proxy"),
}
_GIT_EXEC_ENV_NAMES = {
    "GIT_EDITOR", "GIT_PAGER", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_SEQUENCE_EDITOR",
    "GIT_EXTERNAL_DIFF", "GIT_ASKPASS", "GIT_PROXY_COMMAND", "GIT_CONFIG_PARAMETERS",
}
_GIT_CONFIG_VALUE_ENV = re.compile(r"^GIT_CONFIG_VALUE_(\d+)$")
# Mutation policy must distinguish real Git commands from configured aliases.
# The commit classifier intentionally excludes commit-producing commands from
# its fast-path allowlist; that narrower set must not be reused here.
_GUARD_BUILTIN_GIT_SUBCOMMANDS = parser._STABLE_BUILTIN_GIT_SUBCOMMANDS | {
    "am", "archive", "bisect", "bundle", "check-attr", "check-ignore",
    "check-mailmap", "cherry", "cherry-pick", "column", "commit",
    "commit-graph", "commit-tree", "count-objects", "credential", "diagnose",
    "diff-files", "diff-index", "diff-tree", "fast-export", "fast-import",
    "fetch-pack", "fmt-merge-msg", "format-patch", "fsck", "help", "hook",
    "index-pack", "interpret-trailers", "mailinfo", "mailsplit", "maintenance",
    "merge-base", "merge-file", "merge-index", "merge-tree", "mktag", "mktree",
    "multi-pack-index", "name-rev", "notes", "pack-objects", "pack-refs",
    "patch-id", "prune", "prune-packed", "range-diff", "read-tree", "repack",
    "replace", "rerere", "revert", "send-pack", "shortlog", "show-branch",
    "show-index", "sparse-checkout", "stripspace", "unpack-file",
    "unpack-objects", "update-server-info", "upload-archive", "upload-pack",
    "var", "verify-commit", "verify-pack", "verify-tag", "version", "whatchanged",
}
_PUSH_VALUE_OPTIONS = {"--repo", "--receive-pack", "--exec", "--push-option", "-o"}
_PUSH_VALUE_PREFIXES = (
    "--repo=", "--receive-pack=", "--exec=", "--push-option=",
    "--signed=", "--recurse-submodules=",
)
_PUSH_FLAG_OPTIONS = {
    "-v", "--verbose", "-q", "--quiet", "--tags", "-n", "--dry-run", "--porcelain",
    "--thin", "-u", "--set-upstream", "--progress", "--prune", "--no-verify",
    "--follow-tags", "--atomic", "-4", "--ipv4", "-6", "--ipv6",
}
_MUTATION_WORDS = re.compile(
    r"(?i)(gh\s+pr\s+merge|mergePullRequest|enablePullRequestAutoMerge|"
    r"/pulls/[^\s/]+/merge|git\s+push|git/refs/heads/(?:main|master)|"
    r"refs/heads/(?:main|master))"
)


class GuardError(RuntimeError):
    pass


def _basename(value: str) -> str:
    name = os.path.basename(value.rstrip("/\\")).lower()
    return name[:-4] if name.endswith(".exe") else name


def _payload_command(raw: str) -> str:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise GuardError("payload is not a JSON object")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise GuardError("tool_input is missing")
    command = tool_input.get("command")
    if not isinstance(command, str):
        raise GuardError("tool_input.command is missing or not a string")
    return command


def _current_branch() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _is_protected_ref(token: str) -> bool:
    raw = token.strip().lstrip("+")
    if raw in _PROTECTED:
        return True
    if ":" in raw:
        return raw.rsplit(":", 1)[1] in _PROTECTED
    return False


def _git_context_assignment(word: str) -> bool:
    if not parser._ASSIGNMENT.match(word):
        return False
    name = word.split("=", 1)[0]
    return name.startswith("GIT_CONFIG_") or name in _GIT_CONTEXT_ENV_NAMES


def _leading_git_context_override(words: Sequence[str]) -> bool:
    for word in words:
        if word in parser._CONTROL_PREFIXES:
            continue
        if parser._ASSIGNMENT.match(word):
            if _git_context_assignment(word):
                return True
            continue
        break
    return False


def _is_git_exec_config_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _GIT_EXEC_CONFIG_KEYS:
        return True
    parts = lowered.split(".")
    return len(parts) >= 3 and (parts[0], parts[-1]) in _GIT_EXEC_CONFIG_PATTERNS


def _check_git_config_value(key: str, value: str) -> None:
    """Значение не-alias конфигурации Git проверяется как литеральный носитель."""

    if _embedded_mutation_candidate(value):
        raise GuardError(f"git config {key} value contains protected repository mutation")
    if _is_git_exec_config_key(key) and parser._is_dynamic(value):
        raise GuardError(f"dynamic git config {key} value cannot prove safety")


def _check_git_config_spec(config: str) -> None:
    """Проверить `-c key[=value]`, не являющийся alias."""

    key, separator, value = config.partition("=")
    if not key or parser._is_dynamic(key):
        raise GuardError("dynamic git config option cannot prove safety")
    if separator:
        _check_git_config_value(key, value)


def _check_git_config_env(spec: str, environment: dict[str, str]) -> None:
    """`--config-env key=NAME` для не-alias ключа: значение берётся из окружения."""

    key, separator, name = spec.partition("=")
    if not separator or not key or not name or parser._is_dynamic(spec):
        raise GuardError("dynamic git --config-env cannot prove safety")
    if name in environment:
        _check_git_config_value(key, environment[name])
    elif _is_git_exec_config_key(key):
        raise GuardError(f"git --config-env {key} value cannot be resolved")


def _check_git_env_assignments(assignments: dict[str, str]) -> None:
    """Явные присваивания окружения Git — те же носители, что и `-c`."""

    for name, value in assignments.items():
        if name in _GIT_EXEC_ENV_NAMES:
            if _embedded_mutation_candidate(value):
                raise GuardError(f"git environment {name} contains protected repository mutation")
            if parser._is_dynamic(value):
                raise GuardError(f"dynamic git environment {name} cannot prove safety")
            continue
        match = _GIT_CONFIG_VALUE_ENV.match(name)
        if not match:
            continue
        key = assignments.get(f"GIT_CONFIG_KEY_{match.group(1)}")
        if key is None or parser._is_dynamic(key):
            # Ключ не виден в команде: значение может относиться к любому ключу.
            if _embedded_mutation_candidate(value) or parser._is_dynamic(value):
                raise GuardError(f"git environment {name} cannot prove safety")
            continue
        if key.lower().startswith("alias."):
            continue  # alias разбирается маршрутом разрешения alias
        _check_git_config_value(key, value)


def _leading_assignments(words: Sequence[str]) -> dict[str, str]:
    """Capture shell-prefix assignments so Git alias lookup sees command context."""

    result: dict[str, str] = {}
    for word in words:
        if word in parser._CONTROL_PREFIXES:
            continue
        if parser._ASSIGNMENT.match(word):
            name, value = word.split("=", 1)
            result[name] = value
            continue
        break
    return result


def _unwrap_env(
    arguments: Sequence[str], inherited_env: dict[str, str], cwd: str | None,
) -> tuple[List[str], bool, dict[str, str], str | None]:
    """Return env nested command, Git-context flag, and explicit assignments."""

    expanded = list(arguments)
    context_override = False
    env_updates = dict(inherited_env)
    explicit_assignments: dict[str, str] = {}
    env_cwd = cwd
    index = 0
    while index < len(expanded):
        word = expanded[index]
        if parser._ASSIGNMENT.match(word):
            name, value = word.split("=", 1)
            if _git_context_assignment(word) and parser._is_dynamic(value):
                raise GuardError("dynamic env Git context")
            env_updates[name] = value
            explicit_assignments[name] = value
            context_override = context_override or _git_context_assignment(word)
            index += 1
            continue
        if word == "--":
            index += 1
            break
        if not word.startswith("-") or word == "-":
            break
        if parser._is_dynamic(word):
            raise GuardError("dynamic env option")
        if word in ("-S", "--split-string"):
            if index + 1 >= len(expanded):
                raise GuardError("env split-string missing value")
            split = parser._split_env_string(expanded[index + 1])
            if split is None:
                raise GuardError("dynamic env split-string")
            expanded = expanded[:index] + split + expanded[index + 2 :]
            continue
        if word.startswith("--split-string="):
            split = parser._split_env_string(word.split("=", 1)[1])
            if split is None:
                raise GuardError("dynamic env split-string")
            expanded = expanded[:index] + split + expanded[index + 1 :]
            continue
        if word in ("-u", "--unset", "-C", "--chdir"):
            if index + 1 >= len(expanded):
                raise GuardError(f"env option {word} missing value")
            value = expanded[index + 1]
            consumed = 2
        elif word.startswith(("--unset=", "--chdir=")):
            word, value = word.split("=", 1)
            consumed = 1
        elif word in ("-i", "--ignore-environment", "-0", "--null", "-v", "--debug") or (
            word.startswith("-") and set(word[1:]).issubset({"i", "0", "v"})
        ):
            if word == "--ignore-environment" or (not word.startswith("--") and "i" in word):
                env_updates.clear()
                context_override = True
            index += 1
            continue
        else:
            raise GuardError(f"unknown env option: {word}")
        if parser._is_dynamic(value):
            raise GuardError("dynamic env context option")
        if word in {"-u", "--unset"}:
            env_updates.pop(value, None)
        else:
            env_cwd = os.path.abspath(os.path.join(env_cwd or os.getcwd(), value))
        context_override = True
        index += consumed
    _check_git_env_assignments(explicit_assignments)
    return expanded[index:], context_override, env_updates, env_cwd


def _push_refspecs(tail: Sequence[str]) -> List[str]:
    """Resolve push repository/options enough to identify every refspec fail-closed."""

    explicit_repo = False
    positionals: List[str] = []
    index = 0
    while index < len(tail):
        word = tail[index]
        lower = word.lower()

        if word == "--":
            positionals.extend(tail[index + 1 :])
            break

        if lower == "--repo":
            if index + 1 >= len(tail):
                raise GuardError("git push --repo missing repository")
            explicit_repo = True
            index += 2
            continue
        if lower.startswith("--repo="):
            if not word.split("=", 1)[1]:
                raise GuardError("git push --repo has empty repository")
            explicit_repo = True
            index += 1
            continue

        if lower in _PUSH_VALUE_OPTIONS:
            if index + 1 >= len(tail):
                raise GuardError(f"git push option {word} missing value")
            index += 2
            continue
        if lower.startswith(_PUSH_VALUE_PREFIXES):
            index += 1
            continue

        if lower in _FORCE_FLAGS or lower.startswith("--force-with-lease="):
            index += 1
            continue
        if lower in _PUSH_FLAG_OPTIONS or lower in {"--delete", "-d"}:
            index += 1
            continue

        if word.startswith("-"):
            raise GuardError(f"unknown git push option: {word}")

        positionals.append(word)
        index += 1

    # Without --repo, Git's first positional is the repository. With --repo,
    # every positional is a refspec and none may be silently dropped.
    return positionals if explicit_repo else positionals[1:]


def _git_invocation(
    words: Sequence[str],
    depth: int = 0,
    context_override: bool = False,
    alias_context_args: Sequence[str] = (),
    env_overrides: dict[str, str] | None = None,
    git_cwd: str | None = None,
) -> tuple[str | None, List[str], tuple[str, List[str]] | None, bool]:
    """Resolve Git global options and inline aliases before policy checks.

    This mirrors the alias-aware parsing already used by the commit classifier,
    so `git -c alias.x='push origin main' x` cannot bypass the mutation guard.
    Returns (subcommand, tail, shell_alias_payload, context_changed).
    """

    if depth > 8:
        raise GuardError("git alias expansion is too deep")
    args = list(words)
    aliases: dict[str, str] = {}
    unknown_aliases: set[str] = set()
    context_changed = context_override
    alias_context = list(alias_context_args)
    effective_env = dict(os.environ if env_overrides is None else env_overrides)
    index = 0
    while index < len(args):
        word = args[index]
        if parser._is_dynamic(word):
            raise GuardError("dynamic git global option/subcommand")
        if word == "--":
            index += 1
            break

        config, consumed = parser._git_config_value(
            word, args[index + 1] if index + 1 < len(args) else None
        )
        if consumed:
            if config is None:
                raise GuardError("invalid git -c option")
            alias = parser._alias_from_config(config)
            if alias:
                name, value = alias
                aliases[name] = value
                if parser._is_dynamic(value):
                    unknown_aliases.add(name)
            else:
                # Не-alias значение — литеральный носитель (core.editor и т.п.).
                _check_git_config_spec(config)
                # Includes/includeIf and other config can alter alias resolution.
                context_changed = True
            alias_context.extend(args[index : index + consumed])
            index += consumed
            continue

        if word == "--config-env" or word.startswith("--config-env="):
            if word == "--config-env":
                if index + 1 >= len(args):
                    raise GuardError("git --config-env missing value")
                config_env = args[index + 1]
                consumed = 2
            else:
                config_env = word.split("=", 1)[1]
                consumed = 1
            alias_name = parser._alias_from_config_env(config_env)
            if alias_name:
                unknown_aliases.add(alias_name)
            else:
                _check_git_config_env(config_env, effective_env)
            context_changed = True
            alias_context.extend(args[index : index + consumed])
            index += consumed
            continue

        # `-h` доказан безопасным только терминально: `git -h <подкоманда>`
        # ведёт себя как `git help <подкоманда>` и запускает просмотрщик справки
        # из конфигурации. Форма с остатком падает ниже в отказ по неизвестной
        # глобальной опции — как и до этой правки (Code Review, BLOCKER 1).
        if word == "-h" and index + 1 >= len(args):
            alias_context.append(word)
            index += 1
            continue
        if word in parser._GIT_NO_VALUE_OPTIONS:
            alias_context.append(word)
            index += 1
            continue
        if word in parser._GIT_VALUE_OPTIONS:
            if index + 1 >= len(args):
                raise GuardError(f"git option {word} missing value")
            if word in {"-C", "--git-dir", "--work-tree", "--namespace"}:
                context_changed = True
            if parser._is_dynamic(args[index + 1]):
                raise GuardError("dynamic git context option")
            alias_context.extend(args[index : index + 2])
            index += 2
            continue
        if word.startswith(parser._GIT_VALUE_PREFIXES):
            if word.startswith(("-C", "--git-dir=", "--work-tree=", "--namespace=")):
                context_changed = True
            alias_context.append(word)
            index += 1
            continue
        if word == "--exec-path":
            index += 1
            continue
        if word.startswith("-"):
            # Unknown global option: do not silently reinterpret the next token.
            raise GuardError(f"unknown git global option: {word}")
        break

    if index >= len(args):
        return None, [], None, context_changed

    subcommand = args[index]
    tail = args[index + 1 :]
    if subcommand in unknown_aliases:
        raise GuardError(f"git alias {subcommand} value is dynamic")
    if subcommand in aliases:
        expansion = aliases[subcommand]
        if expansion.startswith("!"):
            suffix = " ".join(tail)
            return None, [], (expansion[1:] + ((" " + suffix) if suffix else ""), alias_context), context_changed
        expanded = parser._tokenize(expansion)
        if expanded is None:
            raise GuardError(f"git alias {subcommand} cannot be tokenized")
        return _git_invocation(
            expanded + tail,
            depth + 1,
            context_changed,
            alias_context,
            effective_env,
            git_cwd,
        )

    # A pre-existing local/global/system alias is not visible in argv. Query it
    # only for names that are not stable builtins; aliases cannot shadow Git
    # builtins. This closes `git land` -> `!gh pr merge ...` without blocking
    # optional external git-* commands that are not aliases.
    normalized = subcommand.lower()
    if normalized not in _GUARD_BUILTIN_GIT_SUBCOMMANDS:
        lookup_env = effective_env
        try:
            alias_proc = subprocess.run(
                ["git", *alias_context, "config", "--get", f"alias.{subcommand}"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
                env=lookup_env,
                cwd=git_cwd,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GuardError(f"cannot inspect git alias {subcommand}: {exc}") from exc
        if alias_proc.returncode == 0:
            expansion = alias_proc.stdout.rstrip("\r\n")
            if not expansion:
                raise GuardError(f"git alias {subcommand} is empty")
            if expansion.startswith("!"):
                suffix = " ".join(tail)
                return None, [], (expansion[1:] + ((" " + suffix) if suffix else ""), alias_context), context_changed
            expanded = parser._tokenize(expansion)
            if expanded is None:
                raise GuardError(f"configured git alias {subcommand} cannot be tokenized")
            return _git_invocation(
                expanded + tail,
                depth + 1,
                context_changed,
                alias_context,
                effective_env,
                git_cwd,
            )
        if alias_proc.returncode not in (1,):
            raise GuardError(
                f"git config lookup for alias {subcommand} failed with {alias_proc.returncode}"
            )

    return normalized, tail, None, context_changed


def _git_shell_context(
    context_args: Sequence[str], env: dict[str, str], cwd: str | None
) -> tuple[dict[str, str], str]:
    # Git запускает !alias из корня рабочего дерева; -c наследуется через
    # GIT_CONFIG_PARAMETERS, а -C не должен повторно применяться в дочернем git.
    effective_env = dict(env)
    shell_cwd = cwd or os.getcwd()
    index = 0
    while index < len(context_args):
        word = context_args[index]
        config, consumed = parser._git_config_value(
            word, context_args[index + 1] if index + 1 < len(context_args) else None
        )
        if word == "--config-env" or word.startswith("--config-env="):
            spec = context_args[index + 1] if word == "--config-env" else word.split("=", 1)[1]
            consumed = 2 if word == "--config-env" else 1
            key, separator, name = spec.partition("=")
            if not separator or name not in effective_env or parser._is_dynamic(name):
                raise GuardError("cannot resolve git --config-env for shell alias")
            config = key + "=" + effective_env[name]
        if consumed:
            if config is None:
                raise GuardError("invalid inherited git config")
            quoted = "'" + config.replace("'", "'\\''") + "'"
            effective_env["GIT_CONFIG_PARAMETERS"] = (
                effective_env.get("GIT_CONFIG_PARAMETERS", "") + " " + quoted
            ).strip()
            index += consumed
            continue
        if word in parser._GIT_VALUE_OPTIONS:
            value = context_args[index + 1]
            index += 2
        elif word.startswith("-C"):
            word, value = "-C", word[2:]
            index += 1
        elif "=" in word:
            word, value = word.split("=", 1)
            index += 1
        else:
            index += 1
            continue
        if parser._is_dynamic(value):
            raise GuardError("dynamic git context for shell alias")
        if word == "-C":
            if value:
                shell_cwd = os.path.abspath(os.path.join(shell_cwd, value))
        elif word in {"--git-dir", "--work-tree", "--namespace"}:
            name = {"--git-dir": "GIT_DIR", "--work-tree": "GIT_WORK_TREE", "--namespace": "GIT_NAMESPACE"}[word]
            effective_env[name] = value

    def inspect(argument: str) -> str:
        proc = subprocess.run(
            ["git", "rev-parse", argument], cwd=shell_cwd, env=effective_env,
            check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=2,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            raise GuardError("cannot establish git shell alias working directory")
        return proc.stdout.rstrip("\r\n")

    # Явные относительные пути должны сохранить смысл после перехода в корень.
    if "GIT_DIR" in effective_env:
        effective_env["GIT_DIR"] = inspect("--absolute-git-dir")
    for name in ("GIT_WORK_TREE", "GIT_COMMON_DIR"):
        if name in effective_env:
            effective_env[name] = os.path.abspath(os.path.join(shell_cwd, effective_env[name]))
    shell_cwd = inspect("--absolute-git-dir") if inspect("--is-bare-repository") == "true" else inspect("--show-toplevel")
    return effective_env, shell_cwd


def _check_git(
    args: Sequence[str],
    context_override: bool = False,
    env_overrides: dict[str, str] | None = None,
    git_cwd: str | None = None,
    depth: int = 0,
) -> str | None:
    subcommand, tail, shell_alias, context_changed = _git_invocation(
        args,
        context_override=context_override,
        env_overrides=env_overrides,
        git_cwd=git_cwd,
    )
    if shell_alias is not None:
        shell_env, shell_cwd = _git_shell_context(shell_alias[1], dict(os.environ if env_overrides is None else env_overrides), git_cwd)
        return _check_command(shell_alias[0], git_env=shell_env, git_cwd=shell_cwd,
                              git_context_override=context_changed, depth=depth + 1, alias_shell=True)
    if subcommand == "push":
        lowered = [item.lower() for item in tail]
        if any(item in _FORCE_FLAGS or item.startswith("--force-with-lease=") for item in lowered):
            return "force/mirror/all push is forbidden for AI agents"
        if any(item.startswith("+") for item in tail if item != "+"):
            return "force refspec push is forbidden for AI agents"
        if "--delete" in lowered or "-d" in lowered:
            return "remote branch deletion is forbidden for AI agents"
        refspecs = _push_refspecs(tail)
        # Empty-source refspec deletes a remote ref: `:branch` is equivalent
        # to `--delete branch`. This remains true when repository is supplied
        # through `--repo[=]` and the first positional is already a refspec.
        if any(token.startswith(":") and len(token) > 1 for token in refspecs):
            return "remote branch deletion refspec is forbidden for AI agents"
        for token in refspecs:
            if _is_protected_ref(token):
                return f"direct update of protected branch via git push is forbidden: {token}"
        if not refspecs:
            if context_changed:
                return "git push under overridden git context cannot prove protected-branch safety"
            if (_current_branch() or "").lower() in {"main", "master"}:
                return "git push from protected branch is forbidden for AI agents"
    if subcommand == "update-ref" and any(_is_protected_ref(item) for item in tail):
        return "local protected ref mutation is forbidden for AI agents"
    return None


def _gh_subcommand(args: Sequence[str]) -> tuple[str | None, List[str]]:
    """Normalize gh persistent options before evaluating command semantics.

    Cobra persistent options such as `-R/--repo` may appear before the root
    subcommand, between nested subcommands, or after them. Strip only the
    persistent options we understand from the entire argv, while preserving
    command-specific options such as `api -X PUT`. Unknown *leading* global
    options still fail closed instead of silently hiding the real subcommand.
    """

    value_options = {"-R", "--repo", "--hostname"}
    normalized: List[str] = []
    index = 0

    while index < len(args):
        token = args[index]
        if token in value_options:
            if index + 1 >= len(args):
                raise GuardError(f"gh option {token} missing value")
            index += 2
            continue
        if any(token.startswith(prefix + "=") for prefix in ("--repo", "--hostname")):
            index += 1
            continue
        normalized.append(token)
        index += 1

    if not normalized:
        return None, []

    index = 0
    flag_options = {"--help", "--version", "--debug"}
    while index < len(normalized) and normalized[index] in flag_options:
        index += 1
    if index >= len(normalized):
        return None, []
    if normalized[index] == "--":
        index += 1
        if index >= len(normalized):
            return None, []
    if normalized[index].startswith("-"):
        raise GuardError(f"unknown gh global option: {normalized[index]}")

    return normalized[index].lower(), list(normalized[index + 1 :])


def _gh_api_option_name(word: str) -> str:
    """Имя опции gh api для сверки с наборами выше.

    Длинное написание приводится к нижнему регистру — так было и до правки
    ложных блоков, хотя сам gh регистр у длинных опций различает. Короткое
    возвращается как есть: `-H` и `-h` у gh разные опции, поэтому неизвестное
    короткое (`-x`, `-h`) не находится в наборе и остаётся блоком.
    """

    if word.startswith("--"):
        return word.lower()
    return word


def _gh_api_endpoint(args: Sequence[str]) -> tuple[str | None, bool]:
    """Return gh api endpoint/subcommand and whether the body is opaque."""

    endpoint: str | None = None
    opaque_body = False
    index = 0
    while index < len(args):
        word = args[index]
        lower = word.lower()
        if parser._is_dynamic(word):
            # A dynamic option value/path can hide a protected mutation.
            if endpoint is None:
                raise GuardError("dynamic gh api endpoint/option cannot prove safety")
        if word == "--":
            index += 1
            if index < len(args) and endpoint is None:
                endpoint = args[index]
            break
        option = _gh_api_option_name(word)
        if option in _GH_API_VALUE_OPTIONS:
            if index + 1 >= len(args):
                raise GuardError(f"gh api option {word} missing value")
            value = args[index + 1]
            if option in _GH_API_PROVEN_GET_OPTIONS:
                # Проверка применяется к КАЖДОМУ вхождению: одного значения,
                # которое не доказано как GET, достаточно для блока, сколько бы
                # вхождений ни стояло рядом.
                if parser._is_dynamic(value):
                    raise GuardError(
                        f"gh api method value is dynamic — GET not proven: {word} {value}"
                    )
                if value.upper() != "GET":
                    raise GuardError(
                        f"gh api method is not GET — safety not proven: {word} {value}"
                    )
            if option == "--input":
                opaque_body = True
            if option in {"-f", "--raw-field", "-F", "--field"} and value.lower().startswith("query=@"):
                opaque_body = True
            index += 2
            continue
        if any(lower.startswith(prefix + "=") for prefix in (
            "--method", "--header", "--raw-field", "--field", "--input", "--cache",
            "--preview", "--jq", "--template",
        )):
            value = word.split("=", 1)[1]
            if lower.startswith("--input="):
                opaque_body = True
            if lower.startswith(("--field=", "--raw-field=")) and value.lower().startswith("query=@"):
                opaque_body = True
            index += 1
            continue
        if lower in _GH_API_FLAG_OPTIONS:
            index += 1
            continue
        if word.startswith("-"):
            raise GuardError(f"unknown gh api option: {word}")
        if endpoint is None:
            endpoint = word
        index += 1
    return endpoint, opaque_body


def _literal_gh_mutation_candidate(words: Sequence[str]) -> bool:
    """Apply direct gh semantics to literal gh argv embedded in carriers."""

    for index, word in enumerate(words):
        if _basename(word) != "gh":
            continue
        try:
            subcommand, tail = _gh_subcommand(words[index + 1 :])
            if subcommand is None:
                continue
            if parser._is_dynamic(subcommand) or subcommand not in _GH_BUILTINS:
                return True
            lowered = [item.lower() for item in tail]
            if subcommand == "pr":
                if lowered and (parser._is_dynamic(tail[0]) or lowered[0] == "merge"):
                    return True
            if subcommand == "api":
                endpoint, opaque_body = _gh_api_endpoint(tail)
                low = " ".join(tail).lower()
                if endpoint and parser._is_dynamic(endpoint):
                    return True
                if re.search(r"/pulls/[^\s/]+/merge(?:[/?#\s]|$)", low):
                    return True
                if "mergepullrequest" in low or "enablepullrequestautomerge" in low:
                    return True
                if _is_graphql_endpoint(endpoint) and opaque_body:
                    return True
        except GuardError:
            return True
    return False


def _is_graphql_endpoint(endpoint: str | None) -> bool:
    """Canonicalize gh api endpoint spellings before GraphQL body policy."""

    if not endpoint:
        return False
    raw = endpoint.strip()
    if raw.lower().startswith(("http://", "https://")):
        path = urlsplit(raw).path
    else:
        path = raw.split("?", 1)[0].split("#", 1)[0]
    normalized = path.strip("/").lower()
    return normalized == "graphql"


def _gh_method_is_mutating(args: Sequence[str]) -> bool:
    lowered = [item.lower() for item in args]
    if any(item in {"-f", "-F", "--field", "--raw-field", "--input"} for item in args):
        return True
    for i, item in enumerate(lowered):
        if item in ("-x", "--method") and i + 1 < len(args):
            return args[i + 1].upper() != "GET"
        if item.startswith("--method="):
            return item.split("=", 1)[1].upper() != "GET"
    return False


def _check_gh(args: Sequence[str]) -> str | None:
    subcommand, tail = _gh_subcommand(args)
    if subcommand is None:
        return None
    if parser._is_dynamic(subcommand):
        raise GuardError("dynamic gh subcommand cannot prove safety")
    if subcommand not in _GH_BUILTINS:
        # Unknown root commands may be configured aliases or extensions. Aliases
        # can expand to `pr merge`, so absence of proof is a block.
        raise GuardError(f"unknown gh root command/alias: {subcommand}")

    lowered = [item.lower() for item in tail]

    if subcommand == "alias" and lowered[:1] == ["set"]:
        expansion = " ".join(tail[2:] if len(tail) >= 2 else [])
        expanded = parser._tokenize(expansion)
        if expanded is None or not expanded:
            raise GuardError("gh alias expansion cannot be proven safe")
        if _check_gh(expanded) or _embedded_mutation_candidate(expansion):
            return "gh alias expansion contains protected repository mutation"

    if subcommand == "pr":
        if not tail:
            return None
        if parser._is_dynamic(tail[0]):
            raise GuardError("dynamic gh pr subcommand cannot prove safety")
        if lowered[0] == "merge":
            return "gh pr merge/auto-merge is operator-only"
        return None

    if subcommand != "api":
        return None

    endpoint, opaque_body = _gh_api_endpoint(tail)
    joined = " ".join(tail)
    low = joined.lower()
    if endpoint and parser._is_dynamic(endpoint):
        raise GuardError("dynamic gh api endpoint cannot prove safety")
    if re.search(r"/pulls/[^\s/]+/merge(?:[/?#\s]|$)", low):
        return "GitHub REST pull-request merge mutation is operator-only"
    if "mergepullrequest" in low or "enablepullrequestautomerge" in low:
        return "GitHub GraphQL merge/auto-merge mutation is operator-only"
    if _is_graphql_endpoint(endpoint) and opaque_body:
        return "opaque GraphQL body cannot prove merge safety"
    protected_api = (
        "git/refs/heads/main" in low
        or "git/refs/heads/master" in low
        or "refs/heads/main" in low
        or "refs/heads/master" in low
    )
    if protected_api and _gh_method_is_mutating(tail):
        return "GitHub API mutation of protected branch is forbidden"
    return None


def _embedded_mutation_candidate(text: str) -> bool:
    """Literal protected mutation hidden inside an opaque code carrier.

    Known data-only commands (printf/grep/cat/...) never call this path. For
    unknown executables such as python/node/awk, punctuation is normalized to
    code words so forms like ["gh","pr","merge"] are caught without pretending
    to parse the guest language.
    """

    literal_words = parser._LITERAL_CODE_WORD.findall(text)
    # Preserve original token case for semantic parsers. gh's short repository
    # flag is case-sensitive: `-R` must not become `-r` before
    # _gh_subcommand() normalizes persistent options in carrier argv.
    if _literal_gh_mutation_candidate(literal_words):
        return True

    words = [word.lower() for word in literal_words]
    for index, word in enumerate(words):
        tail = words[index:]
        if len(tail) >= 2 and tail[:2] == ["git", "push"]:
            return True
        if word in {"mergepullrequest", "enablepullrequestautomerge"}:
            return True
        if word in {"refs/heads/main", "refs/heads/master"}:
            return True
    if re.search(r"(?i)/pulls/[^\s/]+/merge(?:[/?#\s]|$)", text):
        return True
    return bool(_MUTATION_WORDS.search(text))


def _wrapper_nested_command(executable: str, args: Sequence[str]) -> List[str]:
    """Resolve the command executed by a known wrapper, failing closed on ambiguity."""

    index = 0
    value_options = {
        "exec": {"-a"},
        "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "--close-from"},
        "time": {"-f", "--format", "-o", "--output"},
        "command": set(),
        "nohup": set(),
    }.get(executable, set())
    no_value = {
        "exec": {"-c", "-l"},
        "sudo": {"-E", "-H", "-n", "-S", "-k", "-K", "-b", "--stdin", "--background"},
        "time": {"-p", "--portability", "-v", "--verbose"},
        "command": {"-p"},
        "nohup": set(),
    }.get(executable, set())

    while index < len(args):
        word = args[index]
        if word == "--":
            index += 1
            break
        if parser._is_dynamic(word):
            raise GuardError(f"dynamic {executable} wrapper argument")
        if executable == "command" and word in {"-v", "-V"}:
            return []
        if word in value_options:
            if index + 1 >= len(args):
                raise GuardError(f"{executable} option {word} missing value")
            index += 2
            continue
        if any(word.startswith(option + "=") for option in value_options if option.startswith("--")):
            index += 1
            continue
        if word in no_value:
            index += 1
            continue
        if word.startswith("-"):
            raise GuardError(f"unknown {executable} wrapper option: {word}")
        break
    return list(args[index:])


def _shell_inline_command(args: Sequence[str]) -> str | None:
    """Return shell -c payload without confusing long options containing 'c'."""

    index = 0
    while index < len(args):
        word = args[index]
        if parser._is_dynamic(word):
            raise GuardError("dynamic shell option cannot prove safety")
        if word == "--":
            return None
        if word in parser._SHELL_NO_EXEC_OPTIONS:
            return None
        if word in parser._SHELL_NO_OPERAND_OPTIONS:
            index += 1
            continue
        if word in parser._SHELL_OPERAND_OPTIONS:
            if index + 1 >= len(args):
                raise GuardError(f"shell option {word} missing value")
            index += 2
            continue
        if word == "-c":
            if index + 1 >= len(args):
                raise GuardError("shell -c missing command")
            return args[index + 1]
        if word.startswith("-") and not word.startswith("--"):
            flags = set(word[1:])
            if not flags.issubset(parser._SHELL_SHORT_FLAG_CHARS | {"c"}):
                raise GuardError(f"unknown shell option: {word}")
            if "c" in flags:
                if index + 1 >= len(args):
                    raise GuardError("shell compact -c missing command")
                return args[index + 1]
            index += 1
            continue
        if word.startswith("-"):
            raise GuardError(f"unknown shell option: {word}")
        return None
    return None


def _check_words(
    words: Sequence[str],
    *,
    git_context_override: bool = False,
    git_env: dict[str, str] | None = None,
    git_cwd: str | None = None,
    depth: int = 0,
    alias_shell: bool = False,
) -> str | None:
    leading_env = _leading_assignments(words)
    merged_git_env = dict(os.environ if git_env is None else git_env)
    merged_git_env.update(leading_env)
    for name, value in leading_env.items():
        if _git_context_assignment(name + "=" + value) and parser._is_dynamic(value):
            raise GuardError("dynamic git environment context")
    _check_git_env_assignments(leading_env)
    git_context_override = git_context_override or _leading_git_context_override(words)
    words = parser._strip_prefixes(words)
    if not words:
        if alias_shell and leading_env:
            raise GuardError("stateful shell alias assignment cannot prove Git context")
        return None
    if parser._is_dynamic(words[0]):
        if alias_shell:
            raise GuardError("dynamic shell alias executable cannot prove Git context")
        tail_text = " ".join(words[1:])
        tail_words = [word.lower() for word in parser._LITERAL_CODE_WORD.findall(tail_text)]
        if (
            _embedded_mutation_candidate(tail_text)
            or (len(tail_words) >= 2 and tail_words[0] == "pr" and "merge" in tail_words[1:])
            or (tail_words and tail_words[0] in {"push", "update-ref"})
        ):
            raise GuardError("dynamic executable may hide protected repository mutation")
    executable = _basename(words[0])
    args = list(words[1:])

    if executable == "env":
        nested, env_context, nested_env, nested_cwd = _unwrap_env(args, merged_git_env, git_cwd)
        if not nested:
            return None
        return _check_words(
            nested,
            git_context_override=git_context_override or env_context,
            git_env=nested_env,
            git_cwd=nested_cwd,
            depth=depth,
            alias_shell=alias_shell,
        )

    if executable in _EXEC_WRAPPERS:
        nested = _wrapper_nested_command(executable, args)
        if not nested:
            return None
        return _check_words(
            nested,
            git_context_override=git_context_override,
            git_env=merged_git_env,
            git_cwd=git_cwd,
            depth=depth,
            alias_shell=alias_shell,
        )

    if executable in _SHELLS:
        payload = _shell_inline_command(args)
        if payload is not None:
            return _check_command(payload, git_env=merged_git_env, git_cwd=git_cwd,
                                  git_context_override=git_context_override, depth=depth + 1, alias_shell=alias_shell)
        if alias_shell:
            raise GuardError("opaque shell alias script cannot prove Git context")
        return None

    if executable == "xargs":
        for i, token in enumerate(args):
            nested_name = _basename(token)
            if nested_name in {"git", "gh"} | _SHELLS | _EXEC_WRAPPERS:
                nested = list(args[i:])
                reason = _check_words(nested, git_env=merged_git_env, git_cwd=git_cwd,
                                      git_context_override=git_context_override, depth=depth, alias_shell=alias_shell)
                if reason:
                    return reason
                # stdin can supply the missing semantic subcommand/refspec.
                if nested_name in {"git", "gh"} and len(nested) <= 1:
                    return "xargs dynamic repository command cannot prove safety"
                if nested_name == "gh" and len(nested) == 2 and nested[1].lower() in {"pr", "api"}:
                    return "xargs dynamic gh subcommand cannot prove safety"
                if nested_name == "git" and len(nested) == 2 and nested[1].lower() == "push":
                    return "xargs dynamic git push cannot prove refspec safety"
                return None
        if alias_shell:
            raise GuardError("opaque shell alias xargs cannot prove Git context")
        return None

    if executable == "git":
        return _check_git(
            args,
            context_override=git_context_override,
            env_overrides=merged_git_env,
            git_cwd=git_cwd,
            depth=depth,
        )
    if executable == "gh":
        return _check_gh(args)

    # Opaque executable may interpret its argv as code. Reuse the commit
    # classifier's single-source list of commands known to consume operands as
    # data; all other carriers are scanned conservatively for literal protected
    # mutation candidates.
    if executable not in parser._NON_CARRIER_COMMANDS:
        if alias_shell:
            raise GuardError("stateful or opaque shell alias command cannot prove Git context")
        opaque = " ".join(args)
        if _embedded_mutation_candidate(opaque):
            return "opaque executable contains protected repository mutation"
    return None


def _segments(command: str) -> Iterable[Sequence[str]]:
    command = parser._splice_line_continuations(command)
    arithmetic_blanked = parser._blank_ranges(command, parser._arithmetic_spans(command))
    heredocs, uncertain_heredoc = parser._heredoc_spans(arithmetic_blanked)
    shell_source = parser._mask_spans(command, heredocs)
    shell_source = parser._blank_ranges(shell_source, parser._comment_spans(shell_source))

    substitutions, uncertain_sub = parser._active_substitutions(shell_source)
    for heredoc in heredocs:
        if heredoc.expands:
            payloads, uncertain = parser._heredoc_substitutions(
                command[heredoc.body_start : heredoc.body_end]
            )
            substitutions.extend(payloads)
            uncertain_sub = uncertain_sub or uncertain

    for payload in substitutions:
        yield from _segments(payload)

    tokenize_source = parser._blank_ranges(shell_source, parser._arithmetic_spans(shell_source))
    tokens = parser._tokenize(tokenize_source)
    if tokens is None or uncertain_sub or uncertain_heredoc:
        if _MUTATION_WORDS.search(command):
            raise GuardError("ambiguous shell syntax contains protected-mutation candidate")
        return
    yield from parser._segments(tokens)


def _check_command(
    command: str, *, git_env: dict[str, str] | None = None,
    git_cwd: str | None = None, git_context_override: bool = False, depth: int = 0,
    alias_shell: bool = False,
) -> str | None:
    if depth > 8:
        raise GuardError("shell/alias expansion is too deep")
    if (
        parser.classify_command(command) is parser.CommandClass.AMBIGUOUS
        and _embedded_mutation_candidate(command)
    ):
        return "ambiguous executable context contains protected repository mutation"

    segments = list(_segments(command))
    # Для !alias доказуем только отдельный вызов и его разобранные обёртки.
    # Составная оболочка может менять cwd/env между сегментами; не подменяем
    # её интерпретацию проверкой каждого сегмента в исходном Git-контексте.
    if alias_shell and (len(segments) != 1 or parser._arithmetic_spans(command)):
        raise GuardError("compound shell alias cannot prove stable Git context")
    for segment in segments:
        reason = _check_words(segment, git_env=git_env, git_cwd=git_cwd,
                              git_context_override=git_context_override, depth=depth, alias_shell=alias_shell)
        if reason:
            return reason
    return None


def main() -> int:
    raw = sys.stdin.read()
    try:
        reason = _check_command(_payload_command(raw))
    except Exception as exc:
        print(
            f"BLOCKED fail-secure: repository mutation guard could not prove safety: {exc}",
            file=sys.stderr,
        )
        return EXIT_BLOCK
    if reason:
        print(
            f"BLOCKED: {reason}. Use a working branch/PR; merge remains operator-only.",
            file=sys.stderr,
        )
        return EXIT_BLOCK
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
