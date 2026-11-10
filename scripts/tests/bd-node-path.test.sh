#!/usr/bin/env bash
# Public Bash routes pass native module operands to Windows Node without losing complex paths.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT
PROJECT="$TEMP/Проект's (QA) space/primary"
REMOTE="$TEMP/remote.git"
mkdir -p "$PROJECT/scripts/lib" "$TEMP/bin"
# D-6: путь проекта с апострофом MSYS не преобразует в argv нативного git.exe
# (`git -C '/d/…/Проект's …'` — «cannot change to»). Подготовка фикстуры поэтому идёт
# из самого каталога: рабочий каталог bash передаёт git.exe в нативной форме.
project_git() { ( cd "$PROJECT" && git "$@" ); }
git init -q --bare "$REMOTE"
project_git init -q -b main
# Фикстура проверяет пути модулей Node, а не концы строк: глобальный core.autocrlf=true
# runner Windows делал проверку «tooling не изменён» зависимой от гонки stat (exit 6).
project_git config core.autocrlf false
project_git config user.name fixture
project_git config user.email fixture@example.invalid
project_git remote add origin "$REMOTE"
cp "$ROOT/scripts/bd-apply-intents.sh" "$ROOT/scripts/bd-read.sh" "$PROJECT/scripts/"
cp "$ROOT/scripts/lib/bd-env.sh" "$ROOT/scripts/lib/bd-git-environment.mjs" \
  "$ROOT/scripts/lib/bd-snapshot.mjs" "$ROOT"/scripts/lib/bd-managed-*.mjs "$PROJECT/scripts/lib/"
project_git add scripts
project_git commit -qm 'trusted route fixture'
project_git push -q origin main
git -C "$REMOTE" symbolic-ref HEAD refs/heads/main
project_git switch -q -c beads-backup
mkdir -p "$PROJECT/.beads"
: > "$PROJECT/.beads/issues.jsonl"
project_git add .beads/issues.jsonl
project_git commit -qm 'empty task snapshot'
project_git push -q origin beads-backup
project_git switch -q main

cat > "$TEMP/bin/cygpath" <<'SH'
#!/usr/bin/env bash
[ "$1" = -m ] || exit 64
case "$2" in
  */bd-managed-entry.mjs) printf '%s\n' "D:/CodexArtifacts/Проект's (QA) space/primary/scripts/lib/bd-managed-entry.mjs" ;;
  */bd-managed-read-check.mjs) printf '%s\n' "D:/CodexArtifacts/Проект's (QA) space/primary/scripts/lib/bd-managed-read-check.mjs" ;;
  */bd-read-engine.mjs) printf '%s\n' "D:/CodexArtifacts/Проект's (QA) space/primary/scripts/lib/bd-read-engine.mjs" ;;
  */overgate-bd-read.*) printf '%s\n' 'D:/Temp/overgate-bd-read.fixture' ;;
  *) exit 64 ;;
esac
SH
cat > "$TEMP/bin/node" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$1" >> "$OG_NODE_PATH_LOG"
[ "$1" != "D:/CodexArtifacts/Проект's (QA) space/primary/scripts/lib/bd-managed-read-check.mjs" ] || printf '%s\n' "$3" > "$OG_NODE_SNAPSHOT_ARG"
SH
chmod +x "$TEMP/bin/cygpath" "$TEMP/bin/node"
export PATH="$TEMP/bin:$PATH" OG_NODE_PATH_LOG="$TEMP/node-paths.txt" OG_NODE_SNAPSHOT_ARG="$TEMP/snapshot-arg.txt"
( cd "$PROJECT" && bash scripts/bd-apply-intents.sh --read-state )
( cd "$PROJECT" && bash scripts/bd-read.sh ready --json )
[ "$(wc -l < "$OG_NODE_PATH_LOG" | tr -d ' ')" -eq 3 ] || { echo 'FAIL: expected three native Node entrypoints' >&2; exit 1; }
[ "$(sed -n '1p' "$OG_NODE_PATH_LOG")" = "D:/CodexArtifacts/Проект's (QA) space/primary/scripts/lib/bd-managed-entry.mjs" ] || { echo 'FAIL: managed apply Node operand is not native' >&2; exit 1; }
[ "$(sed -n '2p' "$OG_NODE_PATH_LOG")" = "D:/CodexArtifacts/Проект's (QA) space/primary/scripts/lib/bd-managed-read-check.mjs" ] || { echo 'FAIL: managed reader check Node operand is not native' >&2; exit 1; }
[ "$(sed -n '3p' "$OG_NODE_PATH_LOG")" = "D:/CodexArtifacts/Проект's (QA) space/primary/scripts/lib/bd-read-engine.mjs" ] || { echo 'FAIL: reader engine Node operand is not native' >&2; exit 1; }
[ "$(cat "$OG_NODE_SNAPSHOT_ARG")" = 'D:/Temp/overgate-bd-read.fixture' ] || { echo 'FAIL: reader snapshot argument is not native' >&2; exit 1; }
cat > "$TEMP/bin/cygpath" <<'SH'
#!/usr/bin/env bash
exit 64
SH
: > "$OG_NODE_PATH_LOG"
if ( cd "$PROJECT" && bash scripts/bd-apply-intents.sh --read-state ) >"$TEMP/apply.out" 2>"$TEMP/apply.err"; then
  echo 'FAIL: apply accepted failed native path conversion' >&2; exit 1
fi
if ( cd "$PROJECT" && bash scripts/bd-read.sh ready --json ) >"$TEMP/read.out" 2>"$TEMP/read.err"; then
  echo 'FAIL: reader accepted failed native path conversion' >&2; exit 1
fi
[ ! -s "$OG_NODE_PATH_LOG" ] || { echo 'FAIL: Node ran after failed path conversion' >&2; exit 1; }
grep -q 'native Node module path unavailable' "$TEMP/apply.err"
grep -q 'native Node reader module path unavailable' "$TEMP/read.err"
printf '%s\n' 'PASS bd-node-path native module operands 3/3'
