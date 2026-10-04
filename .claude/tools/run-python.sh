#!/bin/sh
# Единый переносимый запуск Python 3 для macOS, Linux и Windows Git Bash.

probe='import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)'

if command -v py >/dev/null 2>&1 && py -3 -c "$probe" >/dev/null 2>&1; then
  exec py -3 "$@"
fi

if command -v python3 >/dev/null 2>&1 && \
    python3 -c "$probe" >/dev/null 2>&1; then
  exec python3 "$@"
fi

if command -v python >/dev/null 2>&1 && \
    python -c "$probe" >/dev/null 2>&1; then
  exec python "$@"
fi

echo "ОШИБКА: не найден исправный Python 3 (проверены: py -3, python3, python)." >&2
exit 127
