#!/usr/bin/env bash
set -euo pipefail

PG_ROOT="${HOME}/local/pg-extract"
PG_BIN="${PG_ROOT}/usr/lib/postgresql/16/bin"
PG_LIB="${PG_ROOT}/usr/lib/x86_64-linux-gnu"
PG_DATA="${HOME}/local/pgdata"
PG_PORT="${FINANCE_AGENT_PG_PORT:-55432}"

REDIS_CLI="${HOME}/local/bin/redis-cli"

export LD_LIBRARY_PATH="${PG_LIB}:${LD_LIBRARY_PATH:-}"

if [[ -x "${PG_BIN}/pg_ctl" ]] && "${PG_BIN}/pg_ctl" -D "${PG_DATA}" status >/dev/null 2>&1; then
  echo "Stopping finance-agent user-space PostgreSQL on port ${PG_PORT}..."
  "${PG_BIN}/pg_ctl" -D "${PG_DATA}" stop
else
  echo "finance-agent user-space PostgreSQL is not running."
fi

if [[ -x "${REDIS_CLI}" ]] && "${REDIS_CLI}" ping >/dev/null 2>&1; then
  echo "Stopping Redis..."
  "${REDIS_CLI}" shutdown || true
else
  echo "Redis is not running."
fi
