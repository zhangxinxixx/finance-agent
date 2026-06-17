#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/dev-dispatch.sh <frontend|backend|review> <task-file>

Default behavior:
  Try to send to an existing interactive Codex pane for frontend/backend.
  If that is unavailable, fall back to scripts/dispatch-visible.sh.

Set DEV_DISPATCH_FORCE_JOB=1 to skip pane dispatch and always open a job window.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 1
fi

ROLE="$1"
TASK_FILE="$2"
ROOT="/home/zxx/workspace/finance-agent/scripts"

if [[ "${DEV_DISPATCH_FORCE_JOB:-}" != "1" && ( "$ROLE" == "frontend" || "$ROLE" == "backend" ) ]]; then
  if "$ROOT/send-to-codex-pane.sh" "$ROLE" "$TASK_FILE"; then
    exit 0
  fi
fi

exec "$ROOT/dispatch-visible.sh" "$ROLE" "$TASK_FILE"
