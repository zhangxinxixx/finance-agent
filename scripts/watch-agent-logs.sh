#!/usr/bin/env bash
set -euo pipefail

WORKBENCH="/home/zxx/workspace/finance-agent-workbench"
LOG_ROOT="$WORKBENCH/logs/agents"

mkdir -p "$LOG_ROOT"
cd "$WORKBENCH"

echo "Watching agent logs under $LOG_ROOT"
echo "Press Ctrl+C to stop."

TAIL_PID=""
LAST_FILES=""

cleanup() {
  if [[ -n "$TAIL_PID" ]]; then
    kill "$TAIL_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

while true; do
  mapfile -t files < <(find "$LOG_ROOT" -type f \( -name 'all.log' -o -name 'events.jsonl' \) | sort)
  current="$(printf '%s\n' "${files[@]-}")"

  if [[ "$current" != "$LAST_FILES" ]]; then
    if [[ -n "$TAIL_PID" ]]; then
      kill "$TAIL_PID" 2>/dev/null || true
      wait "$TAIL_PID" 2>/dev/null || true
      TAIL_PID=""
    fi

    clear
    echo "Watching agent logs under $LOG_ROOT"
    echo "Press Ctrl+C to stop."
    echo

    if [[ ${#files[@]} -eq 0 ]]; then
      echo "(no log files yet)"
    else
      printf '%s\n' "${files[@]}"
      echo
      tail -n 20 -F "${files[@]}" &
      TAIL_PID=$!
    fi

    LAST_FILES="$current"
  fi

  sleep 2
done
