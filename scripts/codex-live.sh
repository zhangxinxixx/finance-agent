#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
TASK_FILE="${2:-}"

MAIN="/home/zxx/workspace/finance-agent"
WT_ROOT="/home/zxx/workspace/worktrees/finance-agent"
WORKBENCH="/home/zxx/workspace/finance-agent-workbench"
LOG_ROOT="$WORKBENCH/logs/agents"

usage() {
  cat <<'EOF'
Usage:
  scripts/codex-live.sh <frontend|backend|review> <task-file>
EOF
}

if [[ -z "$ROLE" || -z "$TASK_FILE" ]]; then
  usage >&2
  exit 1
fi

case "$ROLE" in
  frontend)
    WORKDIR="$WT_ROOT/frontend"
    PROFILE="frontend"
    SANDBOX="danger-full-access"
    ;;
  backend)
    WORKDIR="$WT_ROOT/backend"
    PROFILE="backend"
    SANDBOX="danger-full-access"
    ;;
  review)
    WORKDIR="$WT_ROOT/integration"
    PROFILE="review"
    SANDBOX="danger-full-access"
    ;;
  *)
    echo "ERROR: unknown role: $ROLE" >&2
    usage >&2
    exit 1
    ;;
esac

if [[ ! -d "$WORKDIR" ]]; then
  WORKDIR="$MAIN"
fi

if [[ ! -f "$TASK_FILE" ]]; then
  echo "ERROR: task file not found: $TASK_FILE" >&2
  exit 1
fi

mkdir -p "$LOG_ROOT"

TS="$(date +%F-%H%M%S)"
JOB_ID="${ROLE}-${TS}"
JOB_DIR="$LOG_ROOT/$JOB_ID"
TASK_COPY="$JOB_DIR/task.md"
ALL_LOG="$JOB_DIR/all.log"
JSON_LOG="$JOB_DIR/events.jsonl"

mkdir -p "$JOB_DIR"
cp "$TASK_FILE" "$TASK_COPY"

export no_proxy="${no_proxy:-127.0.0.1,localhost,::1}"

{
  echo "============================================================"
  echo " Codex Live Job"
  echo "============================================================"
  echo "role      : $ROLE"
  echo "profile   : $PROFILE"
  echo "sandbox   : $SANDBOX"
  echo "workdir   : $WORKDIR"
  echo "task      : $TASK_FILE"
  echo "task_copy : $TASK_COPY"
  echo "job_dir   : $JOB_DIR"
  echo "started_at: $(date -Is)"
  echo "============================================================"
  echo
  echo "----- TASK CONTENT -----"
  cat "$TASK_FILE"
  echo
  echo "----- CODEX LIVE OUTPUT -----"
} | tee -a "$ALL_LOG"

set +e
codex exec \
  --json \
  --profile "$PROFILE" \
  --cd "$WORKDIR" \
  --sandbox "$SANDBOX" \
  - < "$TASK_FILE" \
  2>&1 | tee -a "$ALL_LOG" | tee -a "$JSON_LOG"
STATUS=${PIPESTATUS[0]}
set -e

{
  echo
  echo "============================================================"
  echo "finished_at: $(date -Is)"
  echo "exit_status: $STATUS"
  echo "job_dir    : $JOB_DIR"
  echo "============================================================"
} | tee -a "$ALL_LOG"

exit "$STATUS"
