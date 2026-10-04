#!/usr/bin/env bash
# Reference verification. Installer creates a separate project-owned entrypoint.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$ROOT/scripts/verify-reference.sh"
