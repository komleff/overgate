#!/usr/bin/env bash
# Trusted main route: prepare/bootstrap/resolve и fresh CLI transaction publication.
# Queue — данные; publisher исполняет merged/trusted helper, не код PR.
# Usage: bash scripts/bd-apply-intents.sh [--prepare --base R --actor A --output Q] [queue.jsonl]
#        bash scripts/bd-apply-intents.sh --bootstrap <known preservation.json>
#        bash scripts/bd-apply-intents.sh --resolve <old queue hash> <new prepared queue>
set -euo pipefail
# Do not let caller Git configuration or repository-context variables redefine
# the trusted main, origin, hooks or object store during shell preflight.
for git_name in "${!GIT_@}"; do
  case "$git_name" in GIT_AUTHOR_NAME|GIT_AUTHOR_EMAIL|GIT_AUTHOR_DATE|GIT_COMMITTER_NAME|GIT_COMMITTER_EMAIL|GIT_COMMITTER_DATE) ;;
    *) unset "$git_name" ;;
  esac
done
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(git rev-parse --show-toplevel)"
repo_root="$(cd "$repo_root" && pwd -P)"
if [ "$SCRIPT_DIR" != "$repo_root/scripts" ] || [ -L "$SCRIPT_DIR/bd-apply-intents.sh" ] || [ -L "$SCRIPT_DIR/lib" ]; then
  echo "ERROR: trusted publisher helper path must be target main checkout scripts/ (fail-closed)." >&2
  exit 6
fi
cd "$repo_root"
for helper in scripts/bd-apply-intents.sh scripts/lib/bd-env.sh scripts/lib/bd-git-environment.mjs scripts/lib/bd-managed-*.mjs scripts/lib/bd-snapshot.mjs; do
  if [ ! -f "$helper" ] || [ -L "$helper" ] || ! git ls-files --error-unmatch -- "$helper" >/dev/null 2>&1; then
    echo "ERROR: tracked publisher tooling closure incomplete (fail-closed)." >&2
    exit 6
  fi
done
. "${SCRIPT_DIR}/lib/bd-env.sh"
bd_env_assert_main_checkout "bd-apply-intents.sh"

branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
head="$(git rev-parse HEAD)"
# Сетевой вызов с обычным входом пользователя (og-4py): файл переноса живёт только в этой
# command substitution и в exec-окружение не попадает.
trusted_line="$(bd_env_network_git "$repo_root" ls-remote --exit-code --heads origin refs/heads/main)" || trusted_line=""
trusted="$(printf '%s\n' "$trusted_line" | awk '{print $1}')"
if [ "$branch" != main ] || [ -z "$trusted" ] || [ "$head" != "$trusted" ]; then
  echo "ERROR: managed publisher требует exact trusted origin/main HEAD (fail-closed)." >&2
  exit 6
fi
if ! git diff --quiet -- scripts/bd-apply-intents.sh scripts/lib/bd-env.sh scripts/lib/bd-git-environment.mjs scripts/lib/bd-managed-*.mjs scripts/lib/bd-snapshot.mjs \
  || ! git diff --cached --quiet HEAD -- scripts/bd-apply-intents.sh scripts/lib/bd-env.sh scripts/lib/bd-git-environment.mjs scripts/lib/bd-managed-*.mjs scripts/lib/bd-snapshot.mjs; then
  echo "ERROR: managed publisher tooling изменён в worktree." >&2
  exit 6
fi
native_entry="$(bd_env_native_path "${SCRIPT_DIR}/lib/bd-managed-entry.mjs")" || {
  echo "ERROR: native Node module path unavailable (fail-closed)." >&2
  exit 6
}
bd_env_network_cleanup
exec node "$native_entry" "$@"
