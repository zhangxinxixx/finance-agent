#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
TASK_FILE="${2:-}"

SESSION="${FINANCE_TMUX_SESSION:-finance-dev}"
WINDOW="${FINANCE_TMUX_WINDOW:-dev-board}"

usage() {
  cat <<'EOF'
Usage:
  scripts/send-to-codex-pane.sh <frontend|backend> <task-file>

This sends the task content into an existing interactive Codex pane.
It refuses to send if the target pane is not currently running Codex.
EOF
}

if [[ -z "$ROLE" || -z "$TASK_FILE" ]]; then
  usage >&2
  exit 1
fi

case "$ROLE" in
  frontend)
    TARGET_PATH="/home/zxx/workspace/worktrees/finance-agent/frontend"
    FALLBACK_TITLE="1-frontend-tui"
    ;;
  backend)
    TARGET_PATH="/home/zxx/workspace/worktrees/finance-agent/backend"
    FALLBACK_TITLE="2-backend-tui"
    ;;
  *)
    echo "ERROR: unsupported role for pane dispatch: $ROLE" >&2
    usage >&2
    exit 1
    ;;
esac

if [[ ! -f "$TASK_FILE" ]]; then
  echo "ERROR: task file not found: $TASK_FILE" >&2
  exit 1
fi

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "ERROR: tmux session $SESSION not found." >&2
  exit 1
fi

pane_id="$(tmux list-panes -t "$SESSION:$WINDOW" -F '#{pane_id}|#{pane_title}|#{pane_current_command}|#{pane_current_path}' | awk -F '|' -v path="$TARGET_PATH" '$4 == path { print $1; exit }')"
pane_cmd="$(tmux list-panes -t "$SESSION:$WINDOW" -F '#{pane_id}|#{pane_title}|#{pane_current_command}|#{pane_current_path}' | awk -F '|' -v path="$TARGET_PATH" '$4 == path { print $3; exit }')"

if [[ -z "$pane_id" ]]; then
  pane_id="$(tmux list-panes -t "$SESSION:$WINDOW" -F '#{pane_id}|#{pane_title}|#{pane_current_command}|#{pane_current_path}' | awk -F '|' -v title="$FALLBACK_TITLE" '$2 == title { print $1; exit }')"
  pane_cmd="$(tmux list-panes -t "$SESSION:$WINDOW" -F '#{pane_id}|#{pane_title}|#{pane_current_command}|#{pane_current_path}' | awk -F '|' -v title="$FALLBACK_TITLE" '$2 == title { print $3; exit }')"
fi

if [[ -z "$pane_id" ]]; then
  echo "ERROR: target pane not found for role=$ROLE path=$TARGET_PATH title=$FALLBACK_TITLE" >&2
  exit 1
fi

if [[ "$pane_cmd" != "node" && "$pane_cmd" != "codex" ]]; then
  echo "ERROR: target pane is not running Codex." >&2
  echo "pane=$pane_id path=$TARGET_PATH current_command=$pane_cmd" >&2
  exit 1
fi

# Clear any existing draft in the interactive input box before pasting a new task.
tmux send-keys -t "$pane_id" C-u
tmux load-buffer "$TASK_FILE"
tmux paste-buffer -t "$pane_id"
tmux send-keys -t "$pane_id" Enter
sleep 0.2
tmux send-keys -t "$pane_id" Enter

printf 'sent to %s pane (%s)\n' "$ROLE" "$pane_id"
