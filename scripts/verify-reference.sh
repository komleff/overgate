#!/usr/bin/env bash
# Единый fail-fast reference entrypoint. Не подменяет проверки установленного проекта.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
unset CLAUDE_PROJECT_DIR
PYTHON="$ROOT/.claude/tools/run-python.sh"
for required in git bash node jq; do
  command -v "$required" >/dev/null || { echo "NOT RUN: missing $required" >&2; exit 2; }
done
LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/overgate-verify.XXXXXX")"
echo "Reference evidence: $LOG_DIR"
run() {
  local label="$1"; shift
  local log="$LOG_DIR/$label.log"
  if "$@" >"$log" 2>&1; then
    printf 'PASS %s\n' "$label"
    tail -n 2 "$log"
  else
    local result=$?
    printf 'FAIL %s (exit %s)\n' "$label" "$result" >&2
    cat "$log" >&2
    exit "$result"
  fi
}
run structure "$PYTHON" scripts/check-reference.py
run structural-mutations "$PYTHON" scripts/tests/check-reference.test.py
run closure-mutations "$PYTHON" scripts/tests/reference-closure.test.py
run activation bash scripts/tests/activation-routing.test.sh
run mutation-guard bash scripts/tests/repository-mutation-guard.test.sh
run classifier bash scripts/tests/commit-command-classifier.test.sh
run commit-gate "$PYTHON" scripts/tests/commit-gate.test.py
run readiness "$PYTHON" .claude/hooks/test_check_merge_ready.py
run publisher "$PYTHON" scripts/tests/publish-pr-comment.test.py
for test_name in python-launcher with-timeout with-timeout-transparency merge-gate-script-run-parity merge-gate-parse-completeness merge-gate-parse-budget gate-arithmetic-expansion gate-heredoc-delimiter gate-line-continuation-parity shell-grammar-single-source module-resolution-closure finalize-triage-parse bd-read bd-wt; do
  run "$test_name" bash "scripts/tests/$test_name.test.sh"
done
for test_name in merge-gate-parse-complexity readiness-declaration-corpus readiness-policy-complexity; do
  run "$test_name" "$PYTHON" "scripts/tests/$test_name.test.py"
done
run finalizer-validator bash .claude/skills/finalize-pr/validators/test_validate_review_pass.sh
# regression_pr183.sh is historical U2 live-comment tooling, not a deterministic reference fixture.
run install-fresh-upgrade-rollback "$PYTHON" scripts/tests/install-distribution.test.py
run bd-sync bash scripts/test-bd-sync.sh
printf 'PASS verify-reference; full logs: %s\n' "$LOG_DIR"
