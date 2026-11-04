#!/usr/bin/env bash
# Trusted main route: prepare/bootstrap/resolve и fresh CLI transaction publication.
# Queue — данные; publisher исполняет merged/trusted helper, не код PR.
# Usage: bash scripts/bd-apply-intents.sh [--prepare --base R --actor A --output Q] [queue.jsonl]
#        bash scripts/bd-apply-intents.sh --bootstrap <known preservation.json>
#        bash scripts/bd-apply-intents.sh --resolve <old queue hash> <new prepared queue>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/lib/bd-env.sh"
bd_env_assert_main_checkout "bd-apply-intents.sh"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
head="$(git rev-parse HEAD)"
trusted="$(git ls-remote --exit-code --heads origin refs/heads/main 2>/dev/null | awk '{print $1}')"
if [ "$branch" != main ] || [ -z "$trusted" ] || [ "$head" != "$trusted" ]; then
  echo "ERROR: managed publisher требует exact trusted origin/main HEAD (fail-closed)." >&2
  exit 6
fi
if ! git diff --quiet -- scripts/bd-apply-intents.sh scripts/lib/bd-managed-*.mjs scripts/lib/bd-snapshot.mjs; then
  echo "ERROR: managed publisher tooling изменён в worktree." >&2
  exit 6
fi
exec node "${SCRIPT_DIR}/lib/bd-managed-entry.mjs" "$@"
