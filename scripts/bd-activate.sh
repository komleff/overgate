#!/usr/bin/env bash
# После merge: единственный путь первичной активации managed publisher.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
exec "$SCRIPT_DIR/../.claude/tools/run-python.sh" -I -B "$SCRIPT_DIR/bd-activate.py" "$@"
