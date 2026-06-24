#!/usr/bin/env bash
set -euo pipefail

ROOT="${FINANCE_AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="${ROOT}/logs/jin10"
mkdir -p "${LOG_DIR}"
UV_BIN="${HOME}/.local/bin/uv"

if [[ ! -x "${UV_BIN}" ]]; then
  echo "uv not found: ${UV_BIN}" >&2
  exit 127
fi

TARGET_DATE="${1:-$(date +%F)}"
if [[ $# -gt 0 ]]; then
  shift
fi

export no_proxy="${no_proxy:-127.0.0.1,localhost,::1}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

cd "${ROOT}"

LOG_FILE="${LOG_DIR}/daily-scheduler-${TARGET_DATE}.log"

echo "[$(date '+%F %T')] start Jin10 daily scheduler for ${TARGET_DATE}" | tee -a "${LOG_FILE}"
"${UV_BIN}" run python scripts/run_jin10_daily_scheduler.py --date "${TARGET_DATE}" --sleep-before-start "$@" 2>&1 | tee -a "${LOG_FILE}"
