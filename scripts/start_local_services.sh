#!/usr/bin/env bash
set -euo pipefail

# Local user-space services for finance-agent.
# System PostgreSQL may occupy 5432, so the preserved user-space PGDATA runs on 55432.

PG_ROOT="${HOME}/local/pg-extract"
PG_BIN="${PG_ROOT}/usr/lib/postgresql/16/bin"
PG_LIB="${PG_ROOT}/usr/lib/x86_64-linux-gnu"
PG_DATA="${HOME}/local/pgdata"
PG_SOCKET_DIR="/tmp/pg-sockets"
PG_PORT="${FINANCE_AGENT_PG_PORT:-55432}"
PG_LOG="/tmp/finance-agent-pg-${PG_PORT}.log"

REDIS_BIN="${HOME}/local/bin/redis-server"
REDIS_CLI="${HOME}/local/bin/redis-cli"
REDIS_LOG="/tmp/finance-agent-redis.log"

export LD_LIBRARY_PATH="${PG_LIB}:${LD_LIBRARY_PATH:-}"

require_exec() {
  local path="$1"
  if [[ ! -x "$path" ]]; then
    echo "Missing executable: $path" >&2
    exit 1
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "$path" ]]; then
    echo "Missing directory: $path" >&2
    exit 1
  fi
}

require_exec "${PG_BIN}/postgres"
require_exec "${PG_BIN}/pg_ctl"
require_exec "${PG_BIN}/pg_isready"
require_exec "${PG_BIN}/psql"
require_dir "${PG_DATA}"
require_exec "${REDIS_BIN}"
require_exec "${REDIS_CLI}"

mkdir -p "${PG_SOCKET_DIR}"

if "${PG_BIN}/pg_isready" -h 127.0.0.1 -p "${PG_PORT}" >/dev/null 2>&1; then
  echo "PostgreSQL already running on 127.0.0.1:${PG_PORT}."
else
  if "${PG_BIN}/pg_ctl" -D "${PG_DATA}" status >/dev/null 2>&1; then
    echo "PostgreSQL PGDATA is already running, but not reachable on ${PG_PORT}." >&2
    "${PG_BIN}/pg_ctl" -D "${PG_DATA}" status >&2 || true
    exit 1
  fi
  echo "Starting PostgreSQL on 127.0.0.1:${PG_PORT}..."
  "${PG_BIN}/pg_ctl" \
    -D "${PG_DATA}" \
    -l "${PG_LOG}" \
    -o "-p ${PG_PORT} -k ${PG_SOCKET_DIR}" \
    start
fi

if "${REDIS_CLI}" ping >/dev/null 2>&1; then
  echo "Redis already running."
else
  echo "Starting Redis..."
  "${REDIS_BIN}" --daemonize yes --dir /tmp --logfile "${REDIS_LOG}"
fi

"${PG_BIN}/pg_isready" -h 127.0.0.1 -p "${PG_PORT}"
"${PG_BIN}/psql" -h 127.0.0.1 -p "${PG_PORT}" -U finance_agent -d finance_agent -Atqc "select current_user || '@' || current_database();"
"${REDIS_CLI}" ping

echo ""
echo "Use this for finance-agent:"
echo "export DATABASE_URL=postgresql://finance_agent:finance_agent@127.0.0.1:${PG_PORT}/finance_agent"
