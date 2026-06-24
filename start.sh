#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

exec "$PROJECT_ROOT/scripts/local_stack_ctl.sh" "$@"
