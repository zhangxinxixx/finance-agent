#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
TASK_FILE="${2:-}"

SESSION="${FINANCE_TMUX_SESSION:-finance-dev}"
MAIN="/home/zxx/workspace/finance-agent"

usage() {
  cat <<'EOF'
Usage:
  scripts/dispatch-visible.sh <frontend|backend|review> <task-file>
EOF
}

if [[ -z "$ROLE" || -z "$TASK_FILE" ]]; then
  usage >&2
  exit 1
fi

case "$ROLE" in
  frontend|backend|review)
    ;;
  *)
    echo "ERROR: unknown role: $ROLE" >&2
    usage >&2
    exit 1
    ;;
esac

if [[ ! -f "$TASK_FILE" ]]; then
  echo "ERROR: task file not found: $TASK_FILE" >&2
  exit 1
fi

TASK_FILE="$(cd "$(dirname "$TASK_FILE")" && pwd)/$(basename "$TASK_FILE")"
TS="$(date +%H%M%S)"
WIN="job-${ROLE}-${TS}"
CMD="cd '$MAIN' && ./scripts/codex-live.sh '$ROLE' '$TASK_FILE'; STATUS=\$?; echo; echo \"Job finished with exit status \$STATUS. Press Ctrl-b d to detach or close this window manually.\"; bash"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux new-window -t "$SESSION" -n "$WIN" "$CMD"
  tmux select-window -t "$SESSION:$WIN"
else
  echo "tmux session $SESSION not found, running directly..."
  bash -lc "$CMD"
fi
