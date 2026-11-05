#!/usr/bin/env bash
# После merge: единственный путь первичной активации managed publisher.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_PATH="$SCRIPT_DIR/bd-activate.py"
# Native Windows Python receives -I/-B before the script operand, so the
# generic launcher cannot normalize this later positional path itself.
if command -v cygpath >/dev/null 2>&1; then
  SCRIPT_PATH="$(cygpath -m "$SCRIPT_PATH")" || exit 127
  [ -n "$SCRIPT_PATH" ] || exit 127
fi
exec "$SCRIPT_DIR/../.claude/tools/run-python.sh" -I -B "$SCRIPT_PATH" "$@"
