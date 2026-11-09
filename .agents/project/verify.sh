#!/usr/bin/env bash
# Reference verification. Installer creates a separate project-owned entrypoint.
# Этот entrypoint вызывает гейт коммита с пределом 570 с, поэтому здесь commit tier (og-cfx).
# Полный набор: bash scripts/verify-reference.sh (/verify и обязательный CI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$ROOT/scripts/verify-reference.sh" --commit-tier "$@"
