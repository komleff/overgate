#!/usr/bin/env bash
# Единый fail-fast reference entrypoint. Не подменяет проверки установленного проекта.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Уровень: full (по умолчанию: /verify, CI) или commit — ядро пути коммита для гейта
# коммита (og-cfx, состав — ADR §3.38). Неизвестный аргумент — NOT RUN, никакой PASS.
TIER=full
case "${1-}" in
  '') ;;
  --commit-tier) TIER=commit; shift ;;
  *) echo "NOT RUN: unknown argument: $1 (supported: --commit-tier)" >&2; exit 2 ;;
esac
if [ "$#" -gt 0 ]; then echo "NOT RUN: unexpected extra arguments" >&2; exit 2; fi
cd "$ROOT"
unset CLAUDE_PROJECT_DIR
PYTHON="$ROOT/.claude/tools/run-python.sh"
for required in git bash node jq; do
  command -v "$required" >/dev/null || { echo "NOT RUN: missing $required" >&2; exit 2; }
done
LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/overgate-verify.XXXXXX")"
echo "Reference evidence: $LOG_DIR"
# Сумма времени шагов: по ней сверяется бюджет commit tier (ADR §3.38, AC-06).
STEPS_SECONDS=0
run() {
  local label="$1"; shift
  local log="$LOG_DIR/$label.log"
  local started=$SECONDS
  if "$@" >"$log" 2>&1; then
    local elapsed=$((SECONDS - started))
    STEPS_SECONDS=$((STEPS_SECONDS + elapsed))
    printf 'PASS %s (%s s)\n' "$label" "$elapsed"
    tail -n 2 "$log"
  else
    local result=$?
    printf 'FAIL %s (exit %s, %s s)\n' "$label" "$result" "$((SECONDS - started))" >&2
    cat "$log" >&2
    exit "$result"
  fi
}
# Commit tier — ядро пути коммита: структура reference, диспетчер, guard, classifier,
# гейт коммита, хук готовности PR, launcher Python, граница уровней (ADR §3.38).
run structure "$PYTHON" scripts/check-reference.py
run structural-mutations "$PYTHON" scripts/tests/check-reference.test.py
run closure-mutations "$PYTHON" scripts/tests/reference-closure.test.py
run pre-bash-dispatch "$PYTHON" scripts/tests/pre-bash-dispatch.test.py
run portability-names "$PYTHON" scripts/tests/portability-names.test.py
run activation bash scripts/tests/activation-routing.test.sh
run mutation-guard bash scripts/tests/repository-mutation-guard.test.sh
run classifier bash scripts/tests/commit-command-classifier.test.sh
run commit-gate "$PYTHON" scripts/tests/commit-gate.test.py
run readiness "$PYTHON" .claude/hooks/test_check_merge_ready.py
run python-launcher bash scripts/tests/python-launcher.test.sh
run verify-tiers "$PYTHON" scripts/tests/verify-tiers.test.py
# Граница commit tier: остальное идёт только в full (/verify и обязательный CI
# verify-reference; на Windows — джоба windows-commit-tier); гейт коммита укладывается в предел.
if [ "$TIER" = commit ]; then
  printf 'commit tier steps total: %s s\n' "$STEPS_SECONDS"
  printf 'PASS verify-reference commit tier; publisher/gate/finalize/Beads/installer NOT RUN here (full: bash scripts/verify-reference.sh, required CI); logs: %s\n' "$LOG_DIR"
  exit 0
fi
run publisher "$PYTHON" scripts/tests/publish-pr-comment.test.py
for test_name in with-timeout with-timeout-transparency merge-gate-script-run-parity merge-gate-parse-completeness merge-gate-parse-budget gate-arithmetic-expansion gate-heredoc-delimiter gate-line-continuation-parity shell-grammar-single-source module-resolution-closure finalize-triage-parse finalize-gate-script bd-node-path bd-read bd-wt; do
  run "$test_name" bash "scripts/tests/$test_name.test.sh"
done
for test_name in merge-gate-parse-complexity readiness-declaration-corpus readiness-policy-complexity shell-nonascii-expansion; do
  run "$test_name" "$PYTHON" "scripts/tests/$test_name.test.py"
done
run finalizer-validator bash .claude/skills/finalize-pr/validators/test_validate_review_pass.sh
run finalize-no-beads "$PYTHON" scripts/tests/finalize-no-beads.test.py
# regression_pr183.sh is historical U2 live-comment tooling, not a deterministic reference fixture.
run install-fresh-upgrade-rollback "$PYTHON" scripts/tests/install-distribution.test.py
run install-helpers "$PYTHON" scripts/tests/install-helpers.test.py
run bd-bootstrap-native "$PYTHON" scripts/tests/bd-bootstrap-native.test.py
run bd-upgrade-preserve "$PYTHON" scripts/tests/bd-upgrade-preserve.test.py
run bd-legacy-fence "$PYTHON" scripts/tests/bd-legacy-fence.test.py
run bd-sync bash scripts/test-bd-sync.sh
run bd-managed-prefix node scripts/tests/bd-managed-prefix.test.mjs
run bd-managed-snapshot node scripts/tests/bd-managed-snapshot.test.mjs
run bd-managed-two-clone node scripts/tests/bd-managed-two-clone.test.mjs
run bd-publisher-guard node scripts/tests/bd-publisher-guard.test.mjs
run bd-publisher-setup node scripts/tests/bd-publisher-setup.test.mjs
run bd-managed-routes node scripts/tests/bd-managed-routes.test.mjs
printf 'full steps total: %s s\n' "$STEPS_SECONDS"
printf 'PASS verify-reference; full logs: %s\n' "$LOG_DIR"
