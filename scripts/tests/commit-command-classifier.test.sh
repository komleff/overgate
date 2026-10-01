#!/usr/bin/env bash
# Табличный контракт единственного семантического классификатора commit-команд.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLASSIFIER="$ROOT/.claude/hooks/commit_command_classifier.py"
PYTHON_RUNNER="$ROOT/.claude/tools/run-python.sh"
PASS=0
FAIL=0

ok() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
no() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

classify() {
  printf '%s' "$1" | "$PYTHON_RUNNER" "$CLASSIFIER" classify
}

expect_class() {
  local expected="$1"
  local command="$2"
  local actual
  actual="$(classify "$command" 2>/dev/null)"
  local rc=$?
  if [ "$rc" -eq 0 ] && [ "$actual" = "$expected" ]; then
    ok "$expected: $command"
  else
    no "$command — ожидался класс '$expected', получен '$actual' (код $rc)"
  fi
}

echo "== commit-command-classifier.test.sh =="

# Обычные команды и строковые данные со словами `git commit` не являются операцией commit.
expect_class ordinary "ls -la"
expect_class ordinary "git status"
expect_class ordinary "git.exe status"
expect_class ordinary "git diff --stat"
expect_class ordinary "git add README.md"
expect_class ordinary "git push"
expect_class ordinary "git pull --rebase"
expect_class ordinary "git rebase origin/main"
expect_class ordinary "git merge --ff-only origin/main"
expect_class ordinary "echo commit"
expect_class ordinary "printf '%s' 'git commit -m data-only'"
expect_class ordinary 'rg "$PATTERN" .'
expect_class ordinary 'grep "$PATTERN" README.md'
expect_class ordinary 'jq "$FILTER" package.json'
expect_class ordinary 'dotnet test "$PROJECT"'
expect_class ordinary 'python3 script.py "$ARG"'
expect_class ordinary 'gh pr view "$PR" --json state'
expect_class ordinary 'sed -n "$RANGE" README.md'
expect_class ordinary "awk '{print \$1}' README.md"
expect_class ordinary "awk -F: '{print \$1}' /etc/passwd"
expect_class ordinary "awk -v prefix=x '{print prefix, \$1}' README.md"
expect_class ordinary 'openssl rand -hex "$N"'
expect_class ordinary 'nice ls -la'
expect_class ordinary 'nice git status'
expect_class ordinary 'future-exec-wrapper --payload '\''echo "$DATA"'\'''
expect_class ordinary 'nice "$TOOL" status'
expect_class ordinary 'printf "%s\n" data | xargs echo'
expect_class ordinary "sh ./scripts/read-only-check.sh"
expect_class ordinary $'cat <<\'EOF\'\ngit commit -m quoted-heredoc-data\nEOF'
expect_class ordinary $'cat <<EOF\ngit commit -m unquoted-heredoc-data\nEOF'

# Доказанные commit-команды: путь определяется по basename, wrapper'ы разбираются
# по своей семантике, global options Git пропускаются до подкоманды.
expect_class commit "git commit -m direct"
expect_class commit "git.exe commit -m windows-direct"
expect_class commit "/mingw64/bin/GIT.EXE commit -m windows-path"
expect_class commit "GIT commit -m windows-extensionless"
expect_class commit "/usr/bin/git commit -m absolute"
expect_class commit "./tools/git -c user.name=U2 -C /tmp commit -m options"
expect_class commit "git -c alias.ci=commit ci -m inline-alias"
expect_class commit "git -c alias.ci='!git commit' ci -m shell-alias"
expect_class commit "command -- git --no-pager commit -m command-wrapper"
expect_class commit "/usr/bin/env -i HOME=/tmp /opt/tools/git -c user.email=u2@example.invalid commit"
expect_class commit "command env FOO=bar git commit -m nested-wrappers"
expect_class commit "builtin command git commit -m builtin-command"
expect_class commit "builtin exec git commit -m builtin-exec"
expect_class commit "builtin eval 'git commit -m builtin-eval'"

# Любая неизвестная оболочка исполнения вокруг доказанной commit-команды должна
# быть gated: точную семантику wrapper'а мы не доказываем, поэтому fail-closed
# класс `ambiguous` достаточен. Набор включает shell keyword, POSIX-утилиты,
# privilege/session wrappers и произвольное имя — защита должна быть классом,
# а не перечнем известных программ.
expect_class ambiguous "nice git commit -m nice-wrapper"
expect_class ambiguous "nohup git commit -m nohup-wrapper"
expect_class ambiguous "time git commit -m time-wrapper"
expect_class ambiguous "sudo git commit -m sudo-wrapper"
expect_class ambiguous "xargs git commit -m xargs-wrapper"
expect_class ambiguous "setsid git commit -m setsid-wrapper"
expect_class ambiguous "future-exec-wrapper --opaque /usr/bin/git commit -m unknown-wrapper"
expect_class ambiguous "future-exec-wrapper --payload 'git commit -m literal-payload'"
expect_class ambiguous 'printf "%s\n" commit -m bypass | xargs git'
expect_class ambiguous 'future-exec-wrapper --payload=git\ commit\ -m\ option-payload'
expect_class ambiguous 'future-exec-wrapper "$X" git commit -m dynamic-prefix'
expect_class ambiguous 'future-exec-wrapper --payload '\''git "$SUBCOMMAND"'\'''
expect_class ambiguous 'nice "$GIT" -C /tmp commit -m dynamic-git-options'
expect_class ambiguous 'future-exec-wrapper "$GIT" -c user.name=U2 commit -m dynamic-git-options'
expect_class ambiguous 'printf "%s\n" commit -m bypass | xargs "$GIT"'
expect_class ambiguous 'nice "$GIT" "$SUBCOMMAND" -m dynamic-subcommand'
expect_class ambiguous 'future-exec-wrapper "$GIT" "$SUBCOMMAND" -m dynamic-subcommand'
expect_class ambiguous 'nice -n 5 "$GIT" "$SUBCOMMAND" -m option-prefix-dynamic'
expect_class ambiguous 'future-exec-wrapper --opaque "$GIT" "$SUBCOMMAND" -m option-prefix-dynamic'
expect_class ambiguous 'nice "$GIT" -p "$SUBCOMMAND" -m dynamic-subcommand-option'
expect_class ambiguous 'nice "$GIT" --no-lazy-fetch commit -m unknown-valid-git-option'
expect_class ambiguous 'printf "%s\n" commit | xargs -I X git X -m replace-subcommand'
expect_class ambiguous 'printf "%s\n" commit | xargs -J X git X -m bsd-replace-subcommand'
expect_class ambiguous 'printf "%s\n" commit | xargs -iX git X -m gnu-replace-subcommand'
expect_class ambiguous 'printf "%s\n" commit | xargs -i git {} -m gnu-default-replace-subcommand'
expect_class ambiguous $'bash <<\'EOF\'\ngit commit -m bash-heredoc\nEOF'
expect_class ambiguous $'sh <<\'EOF\'\ngit commit -m sh-heredoc\nEOF'
expect_class ambiguous $'zsh <<\'EOF\'\ngit commit -m zsh-heredoc\nEOF'
expect_class ambiguous "bash < <(printf '%s\\n' 'git commit -m process-input')"
expect_class ambiguous "printf '%s\\n' 'git commit -m pipeline-input' | bash"
expect_class ambiguous "printf '%s\\n' 'git commit -m pipeline-input' | sh -s"
expect_class ambiguous "printf '%s\\n' 'git commit -m pipeline-input' | bash --"
expect_class ambiguous 'MODE=-c; bash "$MODE" "git commit -m dynamic-shell-option"'
expect_class ambiguous 'python3 -c '\''import os; os.system("git commit -m python-system")'\'''
expect_class ambiguous "awk 'BEGIN{system(\"git commit -m awk-system\")}' /dev/null"
expect_class ambiguous "awk '{print \$1 | \"git commit -m awk-pipe\"}' README.md"
expect_class ambiguous "awk '\"git commit -m awk-getline\" | getline x' README.md"
expect_class ambiguous "awk -f script.awk README.md"
expect_class ambiguous 'awk "{print \\$1}" README.md'
expect_class ambiguous 'python3 -c '\''import subprocess; subprocess.run(["git","commit","-m","python-subprocess"])'\'''
expect_class ambiguous 'node -e '\''require("child_process").execSync("git commit -m node-exec")'\'''
expect_class ambiguous 'ruby -e '\''system("git", "commit", "-m", "ruby-system")'\'''
expect_class ordinary 'python3 -c '\''print("git status")'\'''

# Shell grammar: составные команды, группы, активные подстановки и carriers.
expect_class commit "git status && git commit -m compound"
expect_class commit "git status; (git commit -m group)"
expect_class commit 'echo "$(git commit -m substitution)"'
expect_class commit "eval 'git commit -m eval-carrier'"
expect_class commit "/bin/sh -c 'git commit -m sh-carrier'"
expect_class commit "/usr/local/bin/bash -lc 'git status && git commit -m bash-carrier'"
expect_class commit "/bin/bash --rcfile /dev/null -c 'git commit -m rcfile-carrier'"
expect_class commit "/bin/bash --init-file /dev/null -lc 'git commit -m init-file-carrier'"
expect_class commit "bash -c -- 'git commit -m bash-double-dash'"
expect_class commit "sh -c -- 'git commit -m sh-double-dash'"
expect_class commit "zsh -c -- 'git commit -m zsh-double-dash'"
expect_class commit $'cat <<EOF\n$(git commit -m expanded-heredoc)\nEOF'
expect_class commit $'cat <<\'EOF\'\ndata only\nEOF\ngit commit -m after-heredoc'

# Запись `$((` начинается с тех же символов, что `$(`. Когда её содержимое не
# является арифметическим выражением, shell исполняет запись как подстановку
# команды, поэтому тело классифицируется fail-closed — как у обычной подстановки.
# Вложенные $()/backtick внутри тела разбираются дополнительно.
expect_class commit 'echo "$((git commit --allow-empty -m direct-body) )"'
expect_class commit 'echo "$((cd /tmp) && git commit -m tail-after-group)"'
expect_class commit $'cat <<EOF\n$((git commit -m direct-body-heredoc) )\nEOF'
expect_class commit $'cat <<EOF\n$((cd /tmp) && git commit -m tail-heredoc)\nEOF'
expect_class commit 'echo "$(( $(git commit -m nested-subst) ))"'
expect_class commit $'cat <<EOF\n$(( $(git commit -m nested-heredoc) ))\nEOF'
expect_class commit 'echo "$(( `git commit -m nested-backtick` ))"'
# Настоящая арифметика без команды в теле вердикт не меняет.
expect_class ordinary 'value=$((1 + 2))'
expect_class ordinary 'echo "$(( COUNT + 1 ))"'
expect_class ordinary 'i=$((i+1))'
expect_class ordinary 'echo "$(( n % 3 ))"'

# Shell убирает пару «обратная косая черта + перевод строки» до разбора, поэтому
# такая запись — одна команда. Классификатор нормализует её первым шагом, иначе
# связка распадалась бы на две команды и commit терялся. Перенос поддержан и
# внутри имени исполняемого файла, и при другом виде перевода строки.
expect_class commit $'git \\\n  commit -m continuation'
expect_class commit $'gi\\\nt commit -m continuation-in-name'
expect_class commit $'git \\\r\n  commit -m continuation-crlf'
expect_class commit $'git commit \\\n  -m continuation-in-options'
expect_class commit $'/usr/bin/git \\\n  commit -m continuation-abs-path'
# Экранированная обратная косая черта переносом не является: строки не склеиваются.
expect_class ordinary $'printf \'a\\\\\'\ngit status'

# Метка heredoc внутри комментария shell инертна: последующие строки остаются
# командами, а не данными. Комментарии распознаются до меток heredoc — иначе
# похожий на метку токен маскировал бы реальные команды.
expect_class commit $'echo ok # <<:\ngit commit -m marker-in-comment\n:'
expect_class commit $'echo ok # <<\'X\'\ngit commit -m quoted-marker-in-comment\nX'
expect_class commit $'echo ok # <<-EOF\ngit commit -m dash-marker-in-comment\nEOF'
# Настоящий heredoc по-прежнему считается данными, а не командами.
expect_class ordinary $'cat <<EOF\ngit commit -m real-heredoc-data\nEOF'
expect_class ordinary 'echo ok # обычный комментарий без метки'

# Запасной вердикт: умолчание смещено с «не доказано, что это commit —
# пропускаем» на «не доказано, что инертно — проверяем». Доказанно инертны
# только строка в одинарных кавычках, комментарий и тело heredoc; текст в
# двойных кавычках инертным не доказан, поэтому связка git+commit в нём
# отправляет команду на прогон тестов.
expect_class ambiguous 'echo "git commit -m not-proven-inert"'
expect_class ambiguous 'printf "%s" "git commit -m not-proven-inert"'
# Доказанно инертные области вердикт не меняют.
expect_class ordinary "printf '%s' 'git commit -m proven-inert-single-quotes'"
expect_class ordinary 'echo ok # git commit -m proven-inert-comment'
expect_class ordinary $'cat <<\'EOF\'\ngit commit -m proven-inert-heredoc\nEOF'
# Связка сужена до подкоманды commit: обычный текст со словом git не срабатывает.
expect_class ordinary 'echo "Git Bash на Windows — fallback на scp"'
expect_class ordinary 'echo "git status показывает изменения"'

# Динамическая позиция executable/subcommand/payload может скрыть commit и потому
# обязана идти в fail-closed ветку, но динамический аргумент обычной команды — нет.
expect_class ambiguous '"$GIT" commit -m dynamic-executable'
expect_class ambiguous 'git "$SUBCOMMAND" -m dynamic-subcommand'
expect_class ambiguous 'env "$GIT" commit -m dynamic-wrapper-target'
expect_class ambiguous 'sh -c "$COMMAND"'
expect_class ambiguous 'eval "$COMMAND"'
expect_class ambiguous '$(command -v git) commit -m substitution-head'
expect_class ambiguous 'git --future-global-option value commit -m unknown-option'
expect_class ambiguous 'git --config-env=alias.ci=ALIAS_VALUE ci -m config-env-alias'
expect_class ambiguous 'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.ci GIT_CONFIG_VALUE_0=commit git ci -m bypass'
expect_class ambiguous 'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.scalar GIT_CONFIG_VALUE_0=commit git scalar -m optional-command-alias'
expect_class ambiguous 'git ci -m ambient-or-external-alias'
expect_class ambiguous "/bin/bash --future-option value -c 'git commit -m opaque-shell-option'"
expect_class ordinary 'echo "$DYNAMIC_ARGUMENT"'

# Комментарий shell инертен на ЛЮБОЙ позиции, где shell его признаёт, а не
# только в хвосте обычной команды. Раньше границы комментария вычислялись в двух
# местах, а основной путь разбора не использовал ни одно: решётка доходила до
# токенизации отдельным словом, становилась неизвестным носителем команды, и
# безобидная заметка со словами `git commit` гоняла тесты. Теперь границы даёт
# единственный сканер, и весь класс позиций обязан давать ordinary.
expect_class ordinary '# git commit -m standalone-comment'
expect_class ordinary '   # git commit -m indented-comment'
expect_class ordinary $'# git commit -m comment-then-command\ngit status'
expect_class ordinary $'git status\n# git commit -m comment-after-newline'
expect_class ordinary 'git status; # git commit -m comment-after-semicolon'
expect_class ordinary 'git status && # git commit -m comment-after-and'
expect_class ordinary 'false || # git commit -m comment-after-or'
expect_class ordinary 'echo a | # git commit -m comment-after-pipe'
expect_class ordinary $'( # git commit -m comment-after-paren\n)'
expect_class ordinary 'echo a > /dev/null # git commit -m comment-after-redirect'
expect_class ordinary 'echo hi # git commit -m trailing-comment'
expect_class ordinary 'git status &&# git commit -m comment-glued-to-metachar'
# Раскрытия внутри комментария shell не выполняет: подстановка там мертва.
expect_class ordinary '# $(git commit -m substitution-in-comment)'
expect_class ordinary '# `git commit -m backtick-in-comment`'

# Обратная сторона того же класса и главный инвариант: признать комментарием то,
# что shell ИСПОЛНЯЕТ, нельзя — гейт ослепнет. Решётка открывает комментарий
# только в начале слова и только вне кавычек, поэтому в записях ниже связка
# git+commit обязана остаться видимой разбору. Ожидания сверены с живым shell.
expect_class ordinary 'foo#bar'
expect_class ambiguous 'git#commit'
expect_class commit 'X=#value git commit -m hash-after-equals'
expect_class commit 'echo ${#var} && git commit -m hash-in-parameter-length'
expect_class ambiguous '\# git commit -m escaped-hash-is-command'
expect_class ambiguous 'echo "# git commit -m double-quoted-hash"'
expect_class ordinary "echo '# git commit -m single-quoted-hash'"
expect_class commit "echo 'a # b' && git commit -m hash-inside-single-quotes"
expect_class commit 'echo "a # b" && git commit -m hash-inside-double-quotes'
# Решётка в теле heredoc — данные команды, а не комментарий: комментарии
# затираются ПОСЛЕ маскирования тел heredoc. В раскрываемом теле подстановка
# после решётки жива, и это обязано доходить до разбора.
expect_class ordinary $'cat <<\'EOF\'\n# git commit -m quoted-heredoc-hash-is-data\nEOF'
expect_class ordinary $'cat <<EOF\n# git commit -m unquoted-heredoc-hash-is-data\nEOF'
expect_class commit $'cat <<EOF\n# $(git commit -m hash-in-heredoc-body-is-data)\nEOF'
expect_class commit $'cat <<\'EOF\'\n# data\nEOF\ngit commit -m after-heredoc-with-hash'
# Порядок «сначала heredoc, потом комментарии» проверяется телом с нечётной
# кавычкой: на сыром тексте состояние кавычек уехало бы и настоящий комментарий
# после heredoc остался бы нераспознанным — и на основном пути, и в запасном
# вердикте. Оба вида кавычек в теле, потому что запасной вердикт затирает
# одинарные и не затирает двойные.
expect_class ordinary $'cat <<\'EOF\'\nit\'s data\nEOF\necho \'a\' # git commit -m masked-body-keeps-quotes-balanced'
expect_class ordinary $'cat <<\'EOF\'\nsay "hi\nEOF\necho x # git commit -m masked-body-keeps-double-quotes-balanced'
expect_class ordinary $'cat <<\'EOF\'\nsay "hi\nEOF\n# git commit -m standalone-comment-after-heredoc'
# Экранированная кавычка строку не открывает, поэтому следующая за ней решётка
# остаётся комментарием. Проверено на живом shell: команда не выполняется.
expect_class ordinary "echo \\' # git commit -m escaped-quote-does-not-open-string"
# Комментарий кончается на переводе строки, и сам перевод остаётся разделителем
# команд. Обратная косая черта в конце комментария его НЕ продлевает — проверено
# на живом shell: следующая строка исполняется.
expect_class commit $'# note\ngit commit -m comment-ends-at-newline'
expect_class commit $'# note \\\ngit commit -m backslash-does-not-extend-comment'

# Роль обратной косой черты зависит от контекста кавычек, и склейка переносов
# обязана повторять его ровно. Внутри ОДИНАРНЫХ кавычек обратная косая
# буквальна: строку закрывает первая же одинарная кавычка. Пока пара «обратная
# косая + символ» проглатывалась и там, запись `'a\'` оставляла кавычку
# открытой, комментарий за ней переставал распознаваться, склейка выполнялась
# внутри комментария — и комментарий поглощал следующую строку с настоящей
# командой. Ожидания сверены с живым shell: команда исполняется.
expect_class commit $'echo \'a\\\'\n# note \\\ngit commit -m x'
expect_class commit $'echo \'a\\\' # note \\\ngit commit -m x'
expect_class commit $'echo \'a\\\'; # note \\\ngit commit -m x'
expect_class commit $'echo \'a\'\\\'\'b\\\' # note \\\ngit commit -m x'
# Обратная сторона того же исправления: закрытая одинарная кавычка возвращает
# разбору способность видеть комментарий, и он остаётся инертным.
expect_class ordinary $'echo \'a\\\' # git commit -m comment-still-inert'
expect_class ordinary $'echo \'a\\\'\ngit status'

# Тело heredoc — данные команды, а не shell-текст: кавычка в нём состояние
# разбора не меняет. Пока склейка переносов разбирала тело как обычный текст,
# нечётная кавычка в данных уводила состояние, комментарий за телом переставал
# распознаваться, и склейка внутри него так же поглощала следующую строку с
# настоящей командой. Ожидания сверены с живым shell.
expect_class commit $'cat <<\'EOF\'\nsay "hi\nEOF\necho x # note \\\ngit commit -m x'
expect_class commit $'cat <<\'EOF\'\nit\'s data\nEOF\n# note \\\ngit commit -m x'
expect_class commit $'cat <<\'EOF\'\ndata\nEOF\necho \'a\\\' # note \\\ngit commit -m x'
# Контроль: сами данные heredoc командами не становятся.
expect_class ordinary $'cat <<\'EOF\'\ngit commit -m data-only\nEOF'

# --- F2: безопасные стабильные builtin-подкоманды git не гоняют тесты ----------
# Их alias затенить не может, коммит на ветке они не создают и произвольную
# вложенную команду НЕ исполняют — ordinary.
for _git_sub in apply blame describe gc reflog restore stash switch; do
  expect_class ordinary "git $_git_sub"
done
expect_class ordinary "git switch main"
expect_class ordinary "git switch -c newbranch"
expect_class ordinary "git restore file.py"
expect_class ordinary "git stash pop"
expect_class ordinary "git apply patch.diff"
# Регресс-контроль: коммитящие подкоманды остаются под гейтом.
expect_class commit "git commit -m z"
# cherry-pick/revert создают коммит на ветке — консервативно под гейтом.
expect_class ambiguous "git cherry-pick abc123"
expect_class ambiguous "git revert HEAD"
# submodule/bisect — НОСИТЕЛИ произвольных вложенных команд (foreach/run):
# из allowlist убраны, остаются консервативными (fail-open иначе).
expect_class ambiguous "git submodule foreach 'git commit -m x'"
expect_class ambiguous "git bisect run sh -c 'git commit -m x'"
# git grep — НОСИТЕЛЬ через -O<cmd> / --open-files-in-pager=<cmd> (исполняет
# команду через shell, может создать коммит на ТЕКУЩЕЙ ветке). Из allowlist убран.
expect_class ambiguous "git grep -O'git commit --allow-empty -m x #' needle"
expect_class ambiguous "git grep --open-files-in-pager='git commit' needle"
# Обычный git grep без -O теперь тоже консервативен — безопасная сторона.
expect_class ambiguous "git grep foo"
# Обычный grep (не подкоманда git) носителем НЕ является — остаётся ordinary.
expect_class ordinary "grep foo file"
expect_class ordinary "grep -rn pattern src/"

# --- F3: awk/sed — НОСИТЕЛИ произвольных команд (system()/print|/e), не данные --
# Скрытый git через awk/sed обязан ловиться: они остаются консервативными.
expect_class ambiguous "awk 'BEGIN{system(\"git commit -m x\")}'"
expect_class ambiguous "awk 'BEGIN{print | \"git commit\"}'"
expect_class ambiguous "sed -e 'e git commit' file"
# Литеральная awk-программа в ОДИНАРНЫХ кавычках без примитивов внешнего исполнения
# доказуемо инертна: текст программы виден целиком и не может отрастить команду в
# рантайме. Такая форма — ordinary, тяжёлый набор для неё не запускается (план §5 C1).
# Консервативными остаются формы, где внешнее исполнение возможно: `system()`,
# pipe/coprocess, `getline`, `@load`, `-f script.awk` (текст программы не виден),
# двойные кавычки (программу раскрывает shell) и динамически собранная программа.
expect_class ordinary "awk '{print \$1}' file"
# Регресс-контроль: реальные носители bash остаются консервативными.
expect_class ambiguous "docker run img bash deploy.sh"
expect_class ambiguous "timeout 60 bash script.sh"

# --- C-2 (a): узкое доказательство read-only sed --------------------------------
# Чтение диапазона строк — обычная работа, а не носитель. Раньше операнд с
# расширением скрипта делал такую команду ambiguous, и после введения безусловного
# блока ambiguous чтение любого `.sh` через sed перестало исполняться.
# Доказательство построено как whitelist грамматики программы: адрес плюс одна из
# команд `p`/`d`/`q`/`=`. Перечислять «запрещённые буквы» у sed нельзя — синтаксис
# контекстно зависим, и любой перечень обходится сменой разделителя у `s`.
expect_class ordinary "sed -n '1,5p' x.test.sh"
expect_class ordinary "sed -n 5p a.sh"
expect_class ordinary "sed -n '45,85p' scripts/tests/finalize-triage-parse.test.sh"
expect_class ordinary "sed -n '330,350p' file.sh"
expect_class ordinary "sed -n '1p;5p' a.sh"
expect_class ordinary "sed -e '1,5p' -n a.sh"
expect_class ordinary "sed -n '45,85p' README.md"
# Fail-closed: каждый примитив записи или запуска отменяет доказательство целиком.
# Операнд со скриптовым расширением взят намеренно — на нём видно именно решение
# доказательства, а не общий путь.
expect_class ambiguous "sed 'e git commit' file.sh"
expect_class ambiguous "sed -e 'e gh pr merge 1' file.sh"
expect_class ambiguous "sed -n 's/a/b/e' file.sh"
expect_class ambiguous "sed -n 's/a/b/w out.txt' file.sh"
expect_class ambiguous "sed -n '1w out.txt' file.sh"
expect_class ambiguous "sed -n '1W out.txt' file.sh"
expect_class ambiguous "sed -n '1r other.txt' file.sh"
expect_class ambiguous "sed -n '1R other.txt' file.sh"
expect_class ambiguous "sed -f script.sed file.sh"
expect_class ambiguous "sed --file=script.sed file.sh"
expect_class ambiguous "sed -i 's/a/b/' file.sh"
expect_class ambiguous "sed --in-place 's/a/b/' file.sh"
expect_class ambiguous "sed -s -n '1,5p' a.sh b.sh"
expect_class ambiguous 'sed -n "1,5p" a.sh'
expect_class ambiguous 'sed -n "$RANGE" a.sh'
expect_class ambiguous "sed -n '{1,5p}' a.sh"
expect_class ambiguous "sed -n '1,5!p' a.sh"
expect_class ambiguous "sed -n '1,5p' -i a.sh"
# Доказательство не имеет права перебить более сильный вердикт соседней команды.
expect_class commit "sed -n '1,5p' a.sh; git commit -m x"
expect_class commit "sed -n '1,5p' a.sh && git commit -m x"
expect_class commit 'sed -n '\''1,5p'\'' "$(git commit -m x)"'

# --- C-2 (b): формы секвенсора, которые коммит не создают -----------------------
# `--abort`/`--quit` и `bisect reset` выходят из уже начатой операции: они не
# создают коммит и не исполняют переданную команду. До правки единственная штатная
# команда выхода из конфликта cherry-pick/am/revert была заблокирована.
expect_class ordinary "git cherry-pick --abort"
expect_class ordinary "git cherry-pick --quit"
expect_class ordinary "git revert --abort"
expect_class ordinary "git revert --quit"
expect_class ordinary "git am --abort"
expect_class ordinary "git am --quit"
expect_class ordinary "git bisect reset"
# `--continue`/`--skip` продолжают операцию и коммит создать могут — остаются как были.
# Позиционность доказательства: ровно один аргумент нужной формы и ничего больше.
expect_class ambiguous "git cherry-pick --continue"
expect_class ambiguous "git cherry-pick --skip"
expect_class ambiguous "git revert --continue"
expect_class ambiguous "git am --continue"
expect_class ambiguous "git am --skip"
expect_class ambiguous "git bisect run ./script.sh"
expect_class ambiguous "git bisect start"
expect_class ambiguous "git cherry-pick abc123"
expect_class ambiguous "git revert HEAD"
expect_class ambiguous "git cherry-pick --abort extra"
expect_class ambiguous "git bisect reset HEAD"
expect_class ambiguous 'git cherry-pick "$ARG"'
# `git commit-tree` создаёт объект коммита и в этом проходе намеренно не трогался.
expect_class ambiguous "git commit-tree abc -p def -F /tmp/m.txt"

# --- F1: арифметика в присваивании — ordinary; подоболочка с commit — блок -----
expect_class ordinary "result=\$((a*b))"
expect_class ordinary "area=\$((w*h))"
expect_class ordinary "n=\$((2**8))"
expect_class ordinary "echo \$((x<<2))"
expect_class ordinary "make -j\$((n*2))"
expect_class commit 'echo "$((git commit --allow-empty -m direct-body) )"'

# --- U2-e5d9a: формы только для чтения не должны гонять набор ------------------
# K-1: `--version`, терминальный `-h` и подкоманда `version` git завершают
# команду выводом и подкоманду не запускают. `--help` в список НЕ входит: с ним
# git открывает просмотрщик справки из конфигурации (U2-i3woa).
expect_class ordinary "git --version"
expect_class ordinary "git -h"
expect_class ordinary "git -c core.pager=less -h"
expect_class ordinary "git version"
expect_class ordinary "git version --build-options"
# `git --version <подкоманда>` печатает версию и подкоманду игнорирует.
expect_class ordinary "git --version check-ignore -v f.md"
expect_class ambiguous "git help commit"
expect_class ambiguous "git --help"
expect_class ambiguous "git -c help.format=man -c man.viewer=foo -c man.foo.cmd='git commit -m x' help commit"
# `-h` с остатком — это `git help <подкоманда>`: git запускает просмотрщик
# справки из конфигурации, поэтому форма остаётся ambiguous, как на базе.
expect_class ambiguous "git -h check-ignore -v f.md"
expect_class ambiguous "git -h version"
expect_class ambiguous "git -h commit"
expect_class ambiguous "git -c man.viewer=p -c man.p.cmd='git commit -m x' -h check-ignore f"

# K-2: подкоманды только для чтения. Критерий — не создают коммит и не исполняют
# внешнюю команду ни одной своей опцией.
expect_class ordinary "git check-ignore -v f.md"
expect_class ordinary "git check-attr -a f.md"
expect_class ordinary "git check-mailmap 'A U Thor <author@example.com>'"
expect_class ordinary "git count-objects -v"
expect_class ordinary "git merge-base main HEAD"
expect_class ordinary "git name-rev HEAD"
expect_class ordinary "git patch-id --stable"
expect_class ordinary "git stripspace -s"
expect_class ordinary "git var GIT_AUTHOR_IDENT"
expect_class ordinary "git show-branch --current"
# Носители произвольных команд критерию не отвечают и в список не попадают.
expect_class ambiguous "git grep -O'git commit -m x' y"
expect_class ambiguous "git submodule foreach 'git commit -m x'"
expect_class ambiguous "git bisect run ./x"

# Разрешённое ослабление (план §3.1, владелец U2-i3woa): исполняемый ключ
# конфигурации рядом с новой формой чтения. Класс существует на main для всех
# подкоманд списка; PR добавляет в него членов, но не создаёт его. Защищённую
# мутацию в таком значении по-прежнему держит guard — см. фикстуру guard'а.
expect_class ordinary "git --paginate -c core.pager='git commit -m x' version"
expect_class ordinary "git -c pager.version='git commit -m x' version"
expect_class ordinary "git --paginate -c core.pager='git commit -m x' check-ignore -v f.md"
expect_class ordinary "git --version -c core.pager='git commit -m x'"

# K-3 (б): `which` печатает путь и аргумент не исполняет, поэтому слово `git` в
# его argv не является вложенной командой.
expect_class ordinary "which git"
expect_class ordinary "which git gh"
expect_class ordinary "which gh"
expect_class ordinary "which 'gh pr merge 1'"
expect_class ordinary "which 'git commit'"
# Остальные носители в список данных не попадают: `cp` аргумент копирует, но
# guard продолжает сканировать его argv — см. фикстуру guard'а.
expect_class ordinary "cp 'gh pr merge 1' d/"
expect_class ordinary "cp which d/"

# Слово-опция, оканчивающееся на `sh`, у неизвестной команды даёт ambiguous с
# ложным диагнозом «может скрывать git commit». Это ИЗВЕСТНЫЙ ЛОЖНЫЙ БЛОК, и он
# остаётся: владелец — `U2-xv0u1`. Исключение для таких слов пробовали ввести в
# этом PR и сняли: у неизвестной команды нельзя доказать, что слово на `-` не
# будет исполнено — после литерального `--` оно операнд (`nice -- -sh …`), у
# обёртки, которая перестаёт разбирать опции на первом операнде, тоже
# (`timeout 5 -sh …`), и внутри закавыченного payload (`foo '-sh -c …'`).
# Кейсы ниже фиксируют текущее поведение, чтобы правка по `U2-xv0u1` была
# видимой.
expect_class ambiguous "foo --squash"
expect_class ambiguous "foo --wash"
expect_class ambiguous "foo --bash"
expect_class ambiguous "foo -sh"
expect_class ambiguous "gh pr merge 1 --squash"
expect_class ambiguous "gh pr merge 999999 --squash"
expect_class ordinary "gh pr merge 1"
# Носитель оболочки: любое слово на `sh` в позиции команды, включая слово с `-`
# в начале и путь к такому файлу. Формы ниже — регрессия на это поведение, они
# и есть причина, по которой узкого исключения не существует.
expect_class ambiguous 'mysh -c "$CMD"'
expect_class ambiguous 'nice mysh -c "$CMD"'
expect_class commit "mysh -c 'git commit -m x'"
expect_class ordinary "mysh script.sh"
expect_class commit "-sh -c 'git commit -m x'"
expect_class ambiguous '-sh -c "$CMD"'
expect_class ambiguous '-bash -c "$CMD"'
expect_class ambiguous '-zsh -c "$CMD"'
expect_class ambiguous './-sh -c "$CMD"'
expect_class ambiguous '/usr/local/bin/-sh -c "$CMD"'
expect_class ambiguous 'nice ./-sh -c "$CMD"'
expect_class ambiguous 'foo ./-sh -c "$CMD"'
# Находки Code Review и QA: слово на `-` доходит до исполнения тремя путями.
expect_class ambiguous 'nice -- -sh -c "$CMD"'
expect_class ambiguous 'timeout 5 -sh -c "$CMD"'
expect_class ambiguous 'foo '\''-sh -c "$CMD"'\'''
# Имена файлов-скриптов в аргументах правкой не затронуты (U2-z34lp).
expect_class ambiguous "cp b.sh d/"
expect_class ambiguous "./x.sh"
expect_class ordinary "bash x.sh"

# Формы чтения gh api: вердикт гейта у них и сегодня ordinary, кейсы закрепляют
# отсутствие регрессии при правке guard'а.
expect_class ordinary "gh api repos/o/r/pulls/1 --jq .state"
expect_class ordinary "gh api -X GET repos/o/r/pulls/1"
expect_class ordinary 'gh api -H "Accept: application/json" repos/o/r'

# --- Мутация: снятие защиты awk / возврат носителей в allowlist открывает fail-open -
# Если снять проверку execution surface у awk ИЛИ вернуть submodule в allowlist,
# скрытый git commit снова пройдёт как ordinary — эта проверка обязана краснеть.
#
# Точка защиты awk сменилась вместе с fast-path: раньше awk удерживался тем, что
# ОТСУТСТВОВАЛ в `_NON_CARRIER_COMMANDS`, теперь литеральную программу разбирает
# `_classify_proven_inert_awk`, и удерживает её именно отказ по `system()`/pipe/
# `getline`/`@load`. Мутация нацелена на новую точку: без неё она проверяла бы
# структурно недостижимый исход и зеленела бы впустую.
MUT_DIR="$(mktemp -d)"
cp "$ROOT"/.claude/hooks/*.py "$MUT_DIR/"
"$PYTHON_RUNNER" - "$MUT_DIR/commit_command_classifier.py" <<'PYX'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
# снять отказ awk-проба по system(): программа с внешним запуском станет «инертной»
a = t.replace('    if re.search(r"(?<![A-Za-z0-9_])system\\s*\\(", program):\n'
              '        return CommandClass.AMBIGUOUS\n',
              '', 1)
# submodule обратно в allowlist
b = a.replace('    "stash",\n    "status",\n    "switch",',
              '    "stash",\n    "status",\n    "submodule",\n    "switch",', 1)
# grep обратно в allowlist стабильных git-подкоманд
c = b.replace('    "for-each-ref",\n    "gc",\n    "hash-object",',
              '    "for-each-ref",\n    "gc",\n    "grep",\n    "hash-object",', 1)
# C-2 (a): грамматика программы sed принимает что угодно — доказательство перестаёт
# быть доказательством, и программа с записью файла объявляется инертной.
d = c.replace('r"\\s*(?:(?:\\d+|\\$)(?:,(?:\\d+|\\$))?)?\\s*[pdq=]\\s*", part',
              'r".*", part', 1)
# C-2 (b): `--continue` попадает в перечень не создающих коммит форм, хотя операцию
# он продолжает и коммит создать может.
e = d.replace('        return argument in {"--abort", "--quit"}',
              '        return argument in {"--abort", "--quit", "--continue"}', 1)
if c == t or d == c or e == d:
    raise SystemExit("мутация не применилась")
p.write_text(e, encoding="utf-8")
PYX
mut_class() { printf '%s' "$1" | "$PYTHON_RUNNER" "$MUT_DIR/commit_command_classifier.py" classify 2>/dev/null; }
if [ "$(mut_class "awk 'BEGIN{system(\"git commit\")}'")" = "ordinary" ]; then
  ok "мутация: снятие проверки system() у awk открывает fail-open (пойман)"
else
  no "мутация awk не воспроизвела fail-open"
fi
if [ "$(mut_class "git submodule foreach 'git commit'")" = "ordinary" ]; then
  ok "мутация: submodule обратно в allowlist открывает fail-open (пойман)"
else
  no "мутация submodule не воспроизвела fail-open"
fi
if [ "$(mut_class "git grep -O'git commit --allow-empty -m x #' n")" = "ordinary" ]; then
  ok "мутация: grep обратно в allowlist открывает fail-open (пойман)"
else
  no "мутация grep не воспроизвела fail-open"
fi
if [ "$(mut_class "sed -n '1w out.txt' file.sh")" = "ordinary" ]; then
  ok "мутация: грамматика sed принимает что угодно — запись файла объявлена инертной (пойман)"
else
  no "мутация грамматики sed не воспроизвела fail-open"
fi
if [ "$(mut_class "git cherry-pick --continue")" = "ordinary" ]; then
  ok "мутация: --continue в перечне не-коммитных форм открывает fail-open (пойман)"
else
  no "мутация --continue не воспроизвела fail-open"
fi
rm -rf "$MUT_DIR"

echo "ИТОГО commit-command-classifier.test.sh: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
