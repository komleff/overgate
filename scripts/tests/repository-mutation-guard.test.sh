#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNNER="$ROOT/.claude/tools/run-python.sh"
HOOK="$ROOT/.claude/hooks/check-repository-mutation.py"
SETTINGS="$ROOT/.claude/settings.json"
CODEX_HOOKS="$ROOT/.codex/hooks.json"
fail=0
pass=0

GUARD_TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$GUARD_TEST_TMP"' EXIT
HEREDOC_MERGE="$(printf '%s\n' "bash <<'U2_REVIEW'" "gh pr merge 756 --squash" "U2_REVIEW")"
HEREDOC_DATA="$(printf '%s\n' "cat <<'U2_REVIEW'" "gh pr merge 756 --squash" "U2_REVIEW")"
ALIAS_REPO="$GUARD_TEST_TMP/alias-repo"
git init -q "$ALIAS_REPO"
git -C "$ALIAS_REPO" config alias.land '!gh pr merge 756 --squash'
git -C "$ALIAS_REPO" config alias.outer '!git land'
git -C "$ALIAS_REPO" config alias.wrapped '!env FOO=bar sh -c "git land"'
git -C "$ALIAS_REPO" config alias.safe '!git status --short'
mkdir -p "$ALIAS_REPO/sub"
SAFE_REPO="$GUARD_TEST_TMP/safe-repo"
git init -q "$SAFE_REPO"
git -C "$SAFE_REPO" config alias.land commit
git -C "$SAFE_REPO" config alias.relative '!git -C ../alias-repo outer'
git -C "$SAFE_REPO" config alias.changedir '!cd ../alias-repo && git outer'
git -C "$SAFE_REPO" config alias.exportdir "!export GIT_DIR='$ALIAS_REPO/.git'; git outer"
git -C "$SAFE_REPO" config alias.unsetdir '!unset GIT_DIR; git outer'
git -C "$SAFE_REPO" config alias.evaldir '!eval "cd ../alias-repo"; git outer'
git -C "$SAFE_REPO" config alias.functiondir '!f() { cd ../alias-repo; git outer; }; f'
git -C "$SAFE_REPO" config alias.sourcedir '!. ./context.sh; git outer'
git -C "$SAFE_REPO" config alias.dynamicdir '!"$SHELL_COMMAND" ../alias-repo; git outer'
git -C "$SAFE_REPO" config alias.nesteddir '!sh -c "cd ../alias-repo && git outer"'
git -C "$SAFE_REPO" config alias.assigndir "!GIT_DIR='$ALIAS_REPO/.git'; git outer"
printf "export GIT_DIR='%s/.git'\n" "$ALIAS_REPO" > "$SAFE_REPO/context.sh"


payload() {
  "$RUNNER" - "$1" <<'PY'
import json, sys
print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))
PY
}

expect_block() {
  local name="$1" command="$2" out rc
  out="$(payload "$command" | "$RUNNER" "$HOOK" 2>&1)"; rc=$?
  if [ "$rc" -eq 2 ]; then printf 'PASS block: %s\n' "$name"; pass=$((pass+1))
  else printf 'FAIL expected block: %s (rc=%s, out=%s)\n' "$name" "$rc" "$out" >&2; fail=$((fail+1)); fi
}
expect_allow() {
  local name="$1" command="$2" out rc
  out="$(payload "$command" | "$RUNNER" "$HOOK" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then printf 'PASS allow: %s\n' "$name"; pass=$((pass+1))
  else printf 'FAIL expected allow: %s (rc=%s, out=%s)\n' "$name" "$rc" "$out" >&2; fail=$((fail+1)); fi
}
# Блок без проверки причины зелен и тогда, когда команда заблокирована не тем
# правилом, которое кейс утверждает: так ложный блок по ошибке разбора выглядел
# как настоящая защита. Помощник проверяет и код возврата 2, и текст причины.
expect_block_reason() {
  local name="$1" command="$2" reason="$3" out rc
  out="$(payload "$command" | "$RUNNER" "$HOOK" 2>&1)"; rc=$?
  if [ "$rc" -ne 2 ]; then
    printf 'FAIL expected block: %s (rc=%s, out=%s)\n' "$name" "$rc" "$out" >&2; fail=$((fail+1)); return
  fi
  case "$out" in
    *"$reason"*) printf 'PASS block+reason: %s\n' "$name"; pass=$((pass+1)) ;;
    *) printf 'FAIL block reason mismatch: %s (ожидалось «%s», получено: %s)\n' "$name" "$reason" "$out" >&2; fail=$((fail+1)) ;;
  esac
}

expect_block "gh merge" "gh pr merge 756 --squash"
expect_block "gh auto merge" "gh pr merge 756 --auto"
expect_block "gh -R merge" "gh -R example/project pr merge 756 --squash"
expect_block "gh --repo merge" "gh --repo example/project pr merge 756 --squash"
expect_block "gh --repo= merge" "gh --repo=example/project pr merge 756 --squash"
expect_block "gh pr -R merge" "gh pr -R example/project merge 756 --squash"
expect_block "gh pr --repo merge" "gh pr --repo example/project merge 756 --squash"
expect_block "gh pr --repo= merge" "gh pr --repo=example/project merge 756 --squash"
expect_block "gh api -R REST merge" "gh api -R example/project -X PUT repos/example/project/pulls/756/merge"
expect_block "gh api --repo GraphQL merge" "gh api --repo example/project graphql -f query='mutation { mergePullRequest(input:{pullRequestId:\"x\"}) { clientMutationId } }'"
expect_block "gh -R REST merge" "gh -R example/project api -X PUT repos/example/project/pulls/756/merge"
expect_block "gh --repo GraphQL merge" "gh --repo example/project api graphql -f query='mutation { mergePullRequest(input:{pullRequestId:\"x\"}) { clientMutationId } }'"
expect_block "Windows gh.exe merge" "gh.exe pr merge 756 --squash"
expect_block "push main" "git push origin main"
expect_block "push HEAD main" "git push origin HEAD:main"
expect_block "Windows git.exe main" "git.exe push origin main"
expect_block "Windows absolute git.exe" "/mingw64/bin/GIT.EXE push origin HEAD:main"
expect_block "push full ref" "git push origin feature:refs/heads/main"
expect_block "force push" "git push --force origin feature"
expect_block "mirror push" "git push --mirror origin"
expect_block "delete branch" "git push origin --delete feature"
expect_block "delete refspec" "git push origin :feature"
expect_block "delete full refspec" "git push origin :refs/heads/feature"
expect_block "push --repo protected refspec" "git push --repo=origin HEAD:main"
expect_block "push --repo deletion refspec" "git push --repo=origin :feature"
expect_block "REST merge" "gh api -X PUT repos/example/project/pulls/756/merge"
expect_block "GraphQL merge" "gh api graphql -f query='mutation { mergePullRequest(input:{pullRequestId:\"x\"}) { clientMutationId } }'"
expect_block "nested shell" "bash -c 'gh pr merge 756 --squash'"
expect_block "command substitution" 'echo $(gh pr merge 756 --squash)'
expect_block "python carrier" 'python3 -c "import subprocess; subprocess.run([\"gh\",\"pr\",\"merge\",\"756\"])"'
expect_block "env python carrier" 'env python3 -c "import subprocess; subprocess.run([\"gh\",\"pr\",\"merge\",\"756\"])"'
expect_block "shell heredoc carrier" "$HEREDOC_MERGE"
expect_block "awk carrier" 'awk "BEGIN{system(\"gh pr merge 756 --squash\")}" /dev/null'
expect_block "git inline alias push" "git -c alias.ship='push origin main' ship"
expect_block "git shell alias merge" "git -c alias.land='!gh pr merge 756 --squash' land"
expect_block "git config env alias context" "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.land GIT_CONFIG_VALUE_0='!gh pr merge 756 --squash' git land"
expect_block "git -C configured alias context" "git -C '$ALIAS_REPO' land"
expect_block "nested shell alias -C context" "git -C '$ALIAS_REPO' outer"
expect_block "nested shell alias git-dir context" "git --git-dir='$ALIAS_REPO/.git' outer"
expect_block "nested shell alias subdirectory context" "git -C '$ALIAS_REPO/sub' outer"
expect_block "nested shell wrapper alias context" "git -C '$ALIAS_REPO' wrapped"
expect_block "shell wrapper Git environment" "GIT_DIR='$ALIAS_REPO/.git' sh -c 'git outer'"
expect_block "nested shell alias inline config" "git -c alias.outer='!git inner' -c alias.inner='!gh pr merge 756 --squash' outer"
expect_block "nested shell alias config environment" "GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=alias.outer GIT_CONFIG_VALUE_0='!git inner' GIT_CONFIG_KEY_1=alias.inner GIT_CONFIG_VALUE_1='!gh pr merge 756 --squash' git outer"
for stateful_alias in changedir exportdir evaldir functiondir sourcedir nesteddir; do
  expect_block "stateful shell alias $stateful_alias" "git -C '$SAFE_REPO' $stateful_alias"
done
expect_block "stateful shell alias unset" "GIT_DIR='$SAFE_REPO/.git' git -C '$ALIAS_REPO' unsetdir"
expect_block "stateful shell alias assignment" "GIT_DIR='$SAFE_REPO/.git' git -C '$SAFE_REPO' assigndir"
expect_block "stateful shell alias dynamic executable" "SHELL_COMMAND=cd git -C '$SAFE_REPO' dynamicdir"
expect_block "shell alias relative nested -C" "git -C '$SAFE_REPO' relative"
expect_block "env chdir preserves alias context" "env -C '$ALIAS_REPO' sh -c 'git outer'"
expect_block "env unset removes inherited Git context" "GIT_DIR='$SAFE_REPO/.git' env -u GIT_DIR git -C '$ALIAS_REPO' outer"
expect_block "env clear removes inherited Git context" "GIT_DIR='$SAFE_REPO/.git' env -i git -C '$ALIAS_REPO' outer"
expect_block "env dynamic Git context" 'env GIT_DIR="$REPO/.git" sh -c "git outer"'
expect_block "dynamic git context path" 'git -C "$REPO" outer'
expect_block "dynamic git environment path" 'GIT_DIR="$REPO/.git" git outer'
PERSISTENT_ALIAS_OUT="$(payload "git land" | \
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.land \
  GIT_CONFIG_VALUE_0='!gh pr merge 756 --squash' \
  "$RUNNER" "$HOOK" 2>&1)"
PERSISTENT_ALIAS_RC=$?
if [ "$PERSISTENT_ALIAS_RC" -eq 2 ]; then
  printf 'PASS block: configured git alias merge\n'; pass=$((pass+1))
else
  printf 'FAIL expected block: configured git alias merge (rc=%s, out=%s)\n' \
    "$PERSISTENT_ALIAS_RC" "$PERSISTENT_ALIAS_OUT" >&2
  fail=$((fail+1))
fi
expect_block "carrier gh nested repo option" "timeout 5 gh pr -R example/project merge 756 --squash"
expect_block "eval gh nested repo option" "eval 'gh pr --repo example/project merge 756 --squash'"
expect_block "python argv gh nested repo option" 'python3 -c "import subprocess; subprocess.run([\"gh\",\"pr\",\"-R\",\"example/project\",\"merge\",\"756\"])"'
expect_block "shell long option before -c" "bash --norc -c 'gh pr merge 756 --squash'"
expect_block "nohup python carrier" 'nohup python3 -c "import subprocess; subprocess.run([\"gh\",\"pr\",\"merge\",\"756\"])"'
expect_block "xargs dynamic gh" "printf '%s\n' 'pr merge 756' | xargs gh"
expect_block "dynamic gh subcommand" 'gh "$GH_SUBCOMMAND" 756'
expect_block "dynamic executable merge tail" '"$GH" pr merge 756 --squash'
expect_block "REST merge query suffix" "gh api -X PUT 'repos/example/project/pulls/756/merge?x=1'"
expect_block "REST merge slash suffix" "gh api -X PUT repos/example/project/pulls/756/merge/"
expect_block "unknown gh alias invocation" "gh land 756"
expect_block "dangerous gh alias definition" "gh alias set land 'pr merge'"
expect_block "opaque GraphQL query file" "gh api graphql -F query=@mutation.graphql"
expect_block "opaque GraphQL input" "gh api graphql --input mutation.json"
expect_block "opaque GraphQL slash endpoint" "gh api --input mutation.json /graphql"
expect_block "opaque GraphQL trailing slash" "gh api --input mutation.json graphql/"
expect_block "opaque GraphQL full URL" "gh api --input mutation.json https://api.github.com/graphql"
expect_block "force refspec" "git push origin +HEAD:feature"

# Исполняемые ключи конфигурации и переменные окружения Git — носители команды,
# которую Git запустит сам (редактор, pager, ssh, credential helper, fsmonitor).
# Литеральная защищённая мутация в их значении обязана блокироваться на любом
# пути передачи: -c, --config-env, GIT_CONFIG_VALUE_n, ведущее присваивание, env.
EXEC_MERGE='sh -c "gh pr merge 756 --squash" --'
expect_block "exec config core.editor commit" "git -c core.editor='$EXEC_MERGE' commit"
expect_block "exec config core.editor commit message" "git -c core.editor='$EXEC_MERGE' commit -m x"
expect_block "exec config core.editor -C commit" "git -c core.editor='$EXEC_MERGE' -C '$ALIAS_REPO' commit"
expect_block "exec config core.editor inline commit alias" "git -c alias.ci=commit -c core.editor='$EXEC_MERGE' ci"
expect_block "exec config core.editor shell alias commit" "git -c alias.x='!git -c core.editor=\"gh pr merge 756 --squash\" commit' x"
expect_block "exec config attached -c core.editor" "git -ccore.editor='$EXEC_MERGE' commit"
expect_block "exec config core.pager status" "git -c core.pager='gh pr merge 756 --squash' status"
expect_block "exec config core.fsmonitor status" "git -c core.fsmonitor='$EXEC_MERGE' status"
expect_block "exec config credential.helper fetch" "git -c credential.helper='!gh pr merge 756 --squash' fetch origin"
expect_block "exec config sequence.editor rebase" "git -c sequence.editor='$EXEC_MERGE' rebase -i HEAD~1"
expect_block "exec config diff.external diff" "git -c diff.external='$EXEC_MERGE' diff"
expect_block "exec config core.sshCommand fetch" "git -c core.sshCommand='$EXEC_MERGE' fetch origin"
expect_block "exec config --config-env core.editor" "EDITOR_CMD='$EXEC_MERGE' git --config-env=core.editor=EDITOR_CMD commit"
expect_block "exec config GIT_CONFIG_VALUE core.editor" "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.editor GIT_CONFIG_VALUE_0='$EXEC_MERGE' git commit"
expect_block "exec env GIT_EDITOR commit" "GIT_EDITOR='$EXEC_MERGE' git commit"
expect_block "exec env GIT_SSH_COMMAND fetch" "GIT_SSH_COMMAND='$EXEC_MERGE' git fetch origin"
expect_block "exec env GIT_SEQUENCE_EDITOR rebase" "GIT_SEQUENCE_EDITOR='$EXEC_MERGE' git rebase -i HEAD~1"
expect_block "exec env via env wrapper" "env GIT_EDITOR='$EXEC_MERGE' git commit"
expect_block "exec env GIT_CONFIG_PARAMETERS" "GIT_CONFIG_PARAMETERS=\"'core.editor=gh pr merge 756 --squash'\" git commit"
expect_block "dynamic exec config value" 'git -c core.editor="$EDITOR_CMD" commit'
expect_block "dynamic exec env value" 'GIT_EDITOR="$EDITOR_CMD" git commit'
expect_block "dynamic exec env via env wrapper" 'env GIT_SSH_COMMAND="$SSH_CMD" git fetch origin'
expect_block "dynamic git config spec" 'git -c "$CONFIG" commit -m x'
expect_block "unresolved --config-env exec key" "git --config-env=core.editor=U2_GUARD_TEST_UNSET_EDITOR commit"

expect_allow "working branch push" "git push origin pipeline/phase2-cross-agent-core"
expect_allow "push --repo working refspec" "git push --repo=origin HEAD:pipeline/phase2-cross-agent-core"
expect_allow "env python safe" 'env python3 -c "print(\"safe\")"'
expect_allow "heredoc data stays inert" "$HEREDOC_DATA"
expect_allow "shell long option safe -c" "bash --norc -c 'printf safe'"
expect_allow "nohup safe executable" "nohup printf safe"
expect_allow "GraphQL inline read query" "gh api graphql -f query='{ viewer { login } }'"
expect_allow "GraphQL slash inline read query" "gh api /graphql -f query='{ viewer { login } }'"
expect_allow "PR create" "gh pr create --title x --body y"
expect_allow "PR comment" "gh pr comment 756 --body ok"
expect_allow "PR view" "gh pr view 756"
expect_allow "PR view with -R" "gh -R example/project pr view 756"
expect_allow "PR view with nested -R" "gh pr -R example/project view 756"
expect_allow "PR view with nested --repo" "gh pr --repo example/project view 756"
expect_allow "REST graphql repository opaque body" "gh api repos/example/graphql --method PATCH --input repo-settings.json"
expect_allow "REST graphql repository full URL opaque body" "gh api https://api.github.com/repos/example/graphql --method PATCH --input repo-settings.json"
expect_allow "API GET with nested --repo" "gh api --repo example/project repos/example/project"
expect_allow "API GET with --repo" "gh --repo example/project api repos/example/project"
expect_allow "fetch" "git fetch origin"
expect_allow "status" "git status --short"
expect_allow "nested safe shell alias context" "git -C '$ALIAS_REPO/sub' safe"
expect_allow "nested safe shell inline commit alias" "git -c alias.outer='!git inner' -c alias.inner=commit outer -m safe"
expect_allow "git -C commit builtin" "git -C '$ALIAS_REPO' commit -m safe"
expect_allow "git -C cherry-pick builtin" "git -C '$ALIAS_REPO' cherry-pick deadbeef"
expect_allow "git -C revert builtin" "git -C '$ALIAS_REPO' revert deadbeef"
expect_allow "git -c identity commit builtin" "git -c user.email=u2@example.invalid -c user.name=U2 commit -m safe"
expect_allow "GIT_DIR commit builtin" "GIT_DIR='$ALIAS_REPO/.git' git commit -m safe"
expect_allow "env identity commit builtin" "env FOO=bar git -c user.name=U2 commit -m safe"
expect_allow "GIT_CONFIG_COUNT commit alias" "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.ci GIT_CONFIG_VALUE_0=commit git ci -m safe"
expect_allow "GIT_CONFIG_COUNT scalar commit alias" "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.scalar GIT_CONFIG_VALUE_0=commit git scalar -m safe"
expect_allow "exec config literal editor commit" "git -c core.editor=vim commit"
expect_allow "exec config literal pager status" "git -c core.pager=cat status"
expect_allow "exec config literal hooksPath commit" "git -c core.hooksPath=/tmp/hooks commit -m x"
expect_allow "exec env literal GIT_EDITOR commit" "GIT_EDITOR=true git commit -m safe"
expect_allow "exec env literal via env wrapper" "env GIT_PAGER=cat git log -1"
expect_allow "resolved --config-env literal editor" "EDITOR_CMD=vim git --config-env=core.editor=EDITOR_CMD commit -m safe"
expect_allow "GIT_CONFIG_VALUE literal editor commit" "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.editor GIT_CONFIG_VALUE_0=vim git commit -m safe"
expect_allow "dynamic non-exec config value" 'git -c user.name="$NAME" commit -m safe'
expect_allow "quoted inert text" "printf '%s' 'gh pr merge 756 --squash'"

# --- U2-e5d9a: формы только для чтения --------------------------------------
# G-1: опции вывода и заголовка блокировались как «unknown gh api option»
# только из-за того, что их написание не совпадало с набором.
expect_allow "gh api --jq read" "gh api repos/o/r/pulls/1 --jq .state"
expect_allow "gh api -q read" "gh api repos/o/r/pulls/1 -q .state"
expect_allow "gh api --jq= read" "gh api repos/o/r/pulls/1 --jq=.state"
expect_allow "gh api --template read" "gh api repos/o/r/pulls/1 --template '{{.state}}'"
expect_allow "gh api -t read" "gh api repos/o/r/pulls/1 -t '{{.state}}'"
expect_allow "gh api --template= read" "gh api repos/o/r/pulls/1 --template='{{.state}}'"
expect_allow "gh api -H read" "gh api -H 'Accept: application/json' repos/o/r"
expect_allow "gh api --header read" "gh api --header 'Accept: application/json' repos/o/r"
expect_allow "gh api -X GET read" "gh api -X GET repos/o/r/pulls/1"
expect_allow "gh api -X get lowercase" "gh api -X get repos/o/r/pulls/1"
expect_allow "gh api --method GET read" "gh api --method GET repos/o/r/pulls/1"
expect_allow "gh api --method=get read" "gh api --method=get repos/o/r/pulls/1"
expect_allow "gh api -X GET protected ref read" "gh api -X GET repos/o/r/git/refs/heads/main"

# `-X` с не-GET значением остаётся блоком; меняется только причина — раньше она
# была про неизвестную опцию, теперь про недоказанный метод.
expect_block_reason "gh api -X POST comment" \
  "gh api -X POST repos/o/r/issues/1/comments -f body=x" "method is not GET"
expect_block_reason "gh api -X PUT contents" \
  "gh api -X PUT repos/o/r/contents/f -f branch=main -f content=y" "method is not GET"
expect_block_reason "gh api -X POST merges" \
  "gh api -X POST repos/o/r/merges -f base=main -f head=x" "method is not GET"
expect_block_reason "gh api -X DELETE repo" \
  "gh api -X DELETE repos/o/r" "method is not GET"
expect_block_reason "gh api -X PUT pull merge" \
  "gh api -X PUT repos/o/r/pulls/1/merge" "method is not GET"
expect_block_reason "gh api --method PUT pull merge" \
  "gh api --method PUT repos/o/r/pulls/1/merge" "pull-request merge mutation is operator-only"
# Правило применяется к КАЖДОМУ вхождению: одного не-GET достаточно.
expect_block_reason "gh api -X GET then PUT" \
  "gh api -X GET -X PUT repos/o/r/contents/f -f branch=main" "method is not GET"
expect_block_reason "gh api -X PUT then GET" \
  "gh api -X PUT -X GET repos/o/r/contents/f -f branch=main" "method is not GET"
expect_block_reason "gh api -X empty value" \
  "gh api -X '' repos/o/r/pulls/1" "method is not GET"
expect_block_reason "gh api -X dynamic value" \
  'gh api -X "$M" repos/o/r/contents/f -f branch=main' "method value is dynamic"
expect_block_reason "gh api -X missing value" \
  "gh api repos/o/r/pulls/1 -X" "missing value"
# Слитное написание метода не распознаётся и остаётся блоком в обе стороны.
expect_block_reason "gh api -XPUT joined" \
  "gh api -XPUT repos/o/r/contents/f -f branch=main" "unknown gh api option: -XPUT"
expect_block_reason "gh api -XGET joined" \
  "gh api -XGET repos/o/r/pulls/1" "unknown gh api option: -XGET"
# Регистр коротких опций различает их так же, как их различает сам gh.
expect_block_reason "gh api -x lowercase unknown" \
  "gh api -x PUT repos/o/r/contents/f -f branch=main" "unknown gh api option: -x"
expect_block_reason "gh api -h lowercase unknown" \
  "gh api -h repos/o/r" "unknown gh api option: -h"
expect_block_reason "gh api --help unknown" \
  "gh api --help repos/o/r" "unknown gh api option: --help"
expect_block_reason "gh api --jq missing value" \
  "gh api repos/o/r/pulls/1 --jq" "missing value"
# Правила пути и полей продолжают действовать поверх доказанного GET.
expect_block_reason "gh api -X GET pull merge path" \
  "gh api -X GET repos/o/r/pulls/1/merge" "pull-request merge mutation is operator-only"
expect_block_reason "gh api -X GET protected ref with field" \
  "gh api -X GET repos/o/r/git/refs/heads/main -f x=1" "mutation of protected branch is forbidden"

# G-2: `--version` и терминальный `-h` завершают git и подкоманду не запускают.
# `--help` остаётся блоком — с ним git открывает просмотрщик справки из
# конфигурации. `-h` с остатком ведёт себя так же и тоже остаётся блоком.
expect_allow "git --version" "git --version"
expect_allow "git -h" "git -h"
expect_allow "git -h after parsed option" "git -c core.pager=less -h"
expect_allow "git version subcommand" "git version"
expect_allow "git version --build-options" "git version --build-options"
expect_allow "git --version ignores subcommand" "git --version check-ignore -v f.md"
expect_block "git --help stays blocked" "git --help"
expect_block_reason "git -h with subcommand" \
  "git -h check-ignore -v f.md" "unknown git global option: -h"
expect_block_reason "git -h with commit" \
  "git -h commit" "unknown git global option: -h"
# Защищённая мутация в исполняемом ключе рядом с новой формой чтения по-прежнему
# блокируется — разбор глобальных опций до неё доходит.
expect_block_reason "exec config merge next to --version" \
  "git --version -c core.pager='gh pr merge 1 --squash'" \
  "git config core.pager value contains protected repository mutation"
expect_block_reason "exec config push next to --version" \
  "git --version -c core.pager='git push origin main'" \
  "git config core.pager value contains protected repository mutation"

# K-2: подкоманды только для чтения — guard их и раньше пропускал, кейсы
# закрепляют отсутствие регрессии.
expect_allow "git check-ignore" "git check-ignore -v f.md"
expect_allow "git merge-base" "git merge-base main HEAD"
expect_allow "git var" "git var GIT_AUTHOR_IDENT"

# §6.4: когда вердикт гейта уходит с ambiguous на ordinary, правило «ambiguous
# executable context» больше не срабатывает, и форму обязан держать другой путь —
# скан значения любого `-c key=value`. Эти кейсы делают проверку постоянной.
expect_block_reason "pager.version value carries merge" \
  "git -c pager.version='gh pr merge 1 --squash' version" \
  "git config pager.version value contains protected repository mutation"
expect_block_reason "pager.version value carries push" \
  "git -c pager.version='git push origin main' version" \
  "git config pager.version value contains protected repository mutation"
expect_block_reason "pager.check-ignore value carries merge" \
  "git -c pager.check-ignore='gh pr merge 1 --squash' check-ignore -v f.md" \
  "git config pager.check-ignore value contains protected repository mutation"
expect_allow "pager.version inert value" "git -c pager.version=less version"

# Слияние держит guard, но разными путями. Без слова-опции на `sh` вердикт
# гейта — ordinary, и срабатывает собственное правило `gh pr merge`. Со словом
# `--squash` гейт даёт ambiguous (известный ложный блок, `U2-xv0u1`), и guard
# блокирует раньше — по непрозрачному контексту. Заблокировано в обоих случаях.
expect_block_reason "gh pr merge without options" \
  "gh pr merge 1" "gh pr merge/auto-merge is operator-only"
expect_block_reason "gh pr merge with --squash" \
  "gh pr merge 1 --squash" "ambiguous executable context contains protected repository mutation"
expect_allow "option word ending in sh" "foo --squash"
expect_allow "option word wash" "foo --wash"

# K-3 (б): `which` аргумент не исполняет — разрешённое ослабление скана argv.
# Для остальных носителей скан сохраняется.
expect_allow "which git" "which git"
expect_allow "which quoted merge" "which 'gh pr merge 1'"
expect_block_reason "cp quoted merge still scanned" \
  "cp 'gh pr merge 1' d/" "opaque executable contains protected repository mutation"
# Нагрузка без слова-опции на `sh`: тогда вердикт гейта — ordinary, и проверяется
# именно скан argv, а не блок по непрозрачному контексту.
expect_block_reason "find -exec merge still scanned" \
  "find . -exec gh pr merge 1 \\;" "opaque executable contains protected repository mutation"

# --- Мутация: снятие проверки метода и возврат носителя в список команд-данных -
# Обе мутации снимают защиту, а не точность: после них не-GET запрос и спрятанная
# в argv команда слияния проходят guard. Кейсы обязаны это поймать.
GUARD_MUT_DIR="$(mktemp -d)"
cp "$ROOT"/.claude/hooks/*.py "$GUARD_MUT_DIR/"
"$RUNNER" - "$GUARD_MUT_DIR" <<'PYX'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
guard = root / "check-repository-mutation.py"
text = guard.read_text(encoding="utf-8")
# Проверка «метод доказан как GET» снята: любое значение `-X` принимается.
mutated = text.replace('            if option in _GH_API_PROVEN_GET_OPTIONS:',
                       '            if False:', 1)
if mutated == text:
    raise SystemExit("мутация метода не применилась")
guard.write_text(mutated, encoding="utf-8")
classifier = root / "commit_command_classifier.py"
source = classifier.read_text(encoding="utf-8")
# Носитель `find` попадает в список команд-данных, и guard перестаёт сканировать
# его argv. Список пополняется только `which`, потому что он аргумент не
# исполняет; `find` исполняет его через `-exec`.
carrier = source.replace('    "file",\n    "grep",',
                         '    "file",\n    "find",\n    "grep",', 1)
if carrier == source:
    raise SystemExit("мутация списка команд-данных не применилась")
classifier.write_text(carrier, encoding="utf-8")
PYX
mut_guard_rc() {
  payload "$1" | "$RUNNER" "$GUARD_MUT_DIR/check-repository-mutation.py" >/dev/null 2>&1
  echo $?
}
if [ "$(mut_guard_rc "gh api -X PUT repos/o/r/contents/f -f branch=main -f content=y")" -eq 0 ]; then
  printf 'PASS мутация: снятие проверки метода у -X открывает fail-open (пойман)\n'; pass=$((pass+1))
else
  printf 'FAIL мутация метода не воспроизвела fail-open\n' >&2; fail=$((fail+1))
fi
if [ "$(mut_guard_rc "find . -exec gh pr merge 1 \\;")" -eq 0 ]; then
  printf 'PASS мутация: find в списке команд-данных выключает скан argv (пойман)\n'; pass=$((pass+1))
else
  printf 'FAIL мутация списка команд-данных не воспроизвела fail-open\n' >&2; fail=$((fail+1))
fi
rm -rf "$GUARD_MUT_DIR"

"$RUNNER" - "$SETTINGS" "$CODEX_HOOKS" <<'PY'
import json, sys
settings=json.load(open(sys.argv[1],encoding="utf-8"))
codex=json.load(open(sys.argv[2],encoding="utf-8"))
needle="check-repository-mutation.py"
claude=sum(needle in h.get("command","") for g in settings["hooks"]["PreToolUse"] for h in g["hooks"])
codex_count=sum(needle in h.get("command","") or needle in h.get("commandWindows","") for g in codex["hooks"]["PreToolUse"] for h in g["hooks"])
if claude != 1 or codex_count < 1:
    raise SystemExit(f"adapter mismatch: claude={claude}, codex={codex_count}")
PY
rc=$?
if [ "$rc" -eq 0 ]; then printf 'PASS adapters share one handler\n'; pass=$((pass+1))
else printf 'FAIL adapters do not share one handler\n' >&2; fail=$((fail+1)); fi

"$RUNNER" - "$SETTINGS" <<'PY'
import json, sys
deny="\n".join(json.load(open(sys.argv[1],encoding="utf-8"))["permissions"]["deny"])
required=("git push --force","git push origin main","git push origin HEAD:main","git push origin master","gh pr merge","gh api *merge*","git push * --delete")
missing=[x for x in required if x not in deny]
if missing:
    raise SystemExit("missing deny parity: "+", ".join(missing))
PY
rc=$?
if [ "$rc" -eq 0 ]; then printf 'PASS Claude deny parity\n'; pass=$((pass+1))
else printf 'FAIL Claude deny parity\n' >&2; fail=$((fail+1)); fi

printf 'repository mutation guard: %d pass, %d fail\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
