#!/usr/bin/env bash
# Regression prove для VC-5: проверяет, что новый stripper + grep
# не даёт ложных результатов на реальной истории comments PR #183.
#
# Ожидание:
#   - все финальные APPROVED review-pass (internal + external) проходят
#     (grep на CHANGES_REQUESTED после strip НЕ матчится, grep на APPROVED матчится);
#   - исторические CHANGES_REQUESTED review-pass (в plain text вердикт CR)
#     блокируются (grep на CHANGES_REQUESTED после strip ДОЛЖЕН матчиться).
#
# Запуск:
#   # предполагается что /tmp/pr183_comments/c*.txt уже извлечены:
#   # for i in $(seq 0 24); do gh pr view 183 --json comments -q ".comments[$i].body" > /tmp/pr183_comments/c$i.txt; done
#   bash .claude/skills/finalize-pr/validators/regression_pr183.sh

set -u

# shopt -s nullglob: пустой glob раскрывается в пустой список, а не литерал
# `/path/c*.txt`. Без этого пустой COMMENTS_DIR приводил к loop с `c*.txt` как
# единственным элементом → grep падал с «No such file», но счётчики оставались
# 0/0, скрипт рапортовал REGRESSION OK exit 0 (false success). Copilot C-1.
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRIPPER="$SCRIPT_DIR/strip_code_spans.sh"

COMMENTS_DIR="${COMMENTS_DIR:-/tmp/pr183_comments}"

if [ ! -d "$COMMENTS_DIR" ]; then
  echo "Нет каталога $COMMENTS_DIR — сначала извлеки comments PR #183:" >&2
  echo "  mkdir -p $COMMENTS_DIR && for i in \$(seq 0 24); do gh pr view 183 --json comments -q \".comments[\$i].body\" > $COMMENTS_DIR/c\$i.txt; done" >&2
  exit 2
fi

# Явная проверка непустого списка файлов: fail-fast вместо silent success.
files=( "$COMMENTS_DIR"/c*.txt )
if [ ${#files[@]} -eq 0 ]; then
  echo "ERROR: в $COMMENTS_DIR не найдено файлов c*.txt — нечего валидировать." >&2
  echo "Извлеки comments PR #183 через gh pr view --json comments." >&2
  exit 2
fi

APPROVED_PASS=0
APPROVED_FAIL=0
CR_PASS=0
CR_FAIL=0

echo "=== Regression PR #183 (VC-5) ==="

for f in "${files[@]}"; do
  # Отбираем только review-pass (internal или external), исключаем triage/scope rollback/landing.
  if ! grep -qiE "Внутреннее ревью|Внешнее ревью|review-pass" "$f"; then
    continue
  fi

  idx=$(basename "$f" .txt)
  body=$(cat "$f")

  # Находим заявленный вердикт в plain text (ищем строку с «**Вердикт:**» или «Вердикт:»
  # которая НЕ в code span — для этого используем stripped body).
  stripped=$(printf '%s' "$body" | bash "$STRIPPER")

  # Определяем «ожидание»: какой вердикт заявлен в plain text.
  # Ищем первое явное вхождение CHANGES_REQUESTED или APPROVED в stripped body
  # (т.е. в plain text вне code spans). Приоритет CHANGES_REQUESTED, так как реальные вердикты CR
  # обычно содержат и APPROVED (например, "APPROVED ранее — но теперь CHANGES_REQUESTED").
  has_cr_plain=false
  has_approved_plain=false
  if printf '%s\n' "$stripped" | grep -qE '(^|[^A-Z_])CHANGES_REQUESTED([^A-Z_]|$)'; then
    has_cr_plain=true
  fi
  if printf '%s\n' "$stripped" | grep -qE '(^|[^A-Z_])APPROVED([^A-Z_]|$)'; then
    has_approved_plain=true
  fi

  # Классификация по первой строке «Вердикт:» в stripped body.
  first_verdict_line=$(printf '%s\n' "$stripped" | grep -iE '^\*{0,2}#{0,3} *Вердикт[:*]' | head -1)
  if [ -z "$first_verdict_line" ]; then
    # fallback — любая строка с «Вердикт:»
    first_verdict_line=$(printf '%s\n' "$stripped" | grep -iE 'Вердикт[:*]' | head -1)
  fi

  declared="UNKNOWN"
  if printf '%s' "$first_verdict_line" | grep -qE 'CHANGES_REQUESTED'; then
    declared="CHANGES_REQUESTED"
  elif printf '%s' "$first_verdict_line" | grep -qE 'APPROVED'; then
    declared="APPROVED"
  fi

  # validator принимает review-pass как APPROVED если:
  #   - CHANGES_REQUESTED НЕ найден после strip, И
  #   - APPROVED найден после strip.
  validator_verdict="BLOCK"
  if ! $has_cr_plain && $has_approved_plain; then
    validator_verdict="APPROVED"
  elif $has_cr_plain; then
    validator_verdict="BLOCK"
  else
    validator_verdict="NO_APPROVED"
  fi

  # Сверяем
  case "$declared" in
    APPROVED)
      if [ "$validator_verdict" = "APPROVED" ]; then
        echo "PASS  [$idx] declared=APPROVED → validator=APPROVED"
        APPROVED_PASS=$((APPROVED_PASS + 1))
      else
        echo "FAIL  [$idx] declared=APPROVED → validator=$validator_verdict (ложная блокировка!)"
        APPROVED_FAIL=$((APPROVED_FAIL + 1))
      fi
      ;;
    CHANGES_REQUESTED)
      if [ "$validator_verdict" = "BLOCK" ]; then
        echo "PASS  [$idx] declared=CHANGES_REQUESTED → validator=BLOCK (корректно блокирует)"
        CR_PASS=$((CR_PASS + 1))
      else
        echo "FAIL  [$idx] declared=CHANGES_REQUESTED → validator=$validator_verdict (CR должен был блокироваться!)"
        CR_FAIL=$((CR_FAIL + 1))
      fi
      ;;
    *)
      echo "SKIP  [$idx] не удалось определить declared verdict"
      ;;
  esac
done

echo ""
echo "=== Summary ==="
echo "APPROVED review-pass: $APPROVED_PASS passed / $((APPROVED_PASS + APPROVED_FAIL)) total"
echo "CR review-pass:       $CR_PASS correctly blocked / $((CR_PASS + CR_FAIL)) total"

# Если каталог содержал c*.txt, но ни один файл не оказался review-pass
# (все пропущены через `continue` в grep на маркеры ревью), скрипт ничего не
# провалидировал. Без этой проверки — false success. Copilot C-1 extension.
total_processed=$((APPROVED_PASS + APPROVED_FAIL + CR_PASS + CR_FAIL))
if [ "$total_processed" -eq 0 ]; then
  echo "ERROR: ни один review-pass не обработан — ${#files[@]} файл(ов) в $COMMENTS_DIR не содержит маркеров (\"Внутреннее ревью\" | \"Внешнее ревью\" | \"review-pass\")." >&2
  exit 2
fi

if [ "$APPROVED_FAIL" -gt 0 ] || [ "$CR_FAIL" -gt 0 ]; then
  echo "REGRESSION FAILED"
  exit 1
fi
echo "REGRESSION OK"
exit 0
