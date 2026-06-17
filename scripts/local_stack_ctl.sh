#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/apps/frontend-web"
STATE_DIR="${FINANCE_AGENT_STATE_DIR:-/tmp/finance-agent-stack}"
API_PORT="${FINANCE_AGENT_API_PORT:-8000}"
API_PID_FILE="$STATE_DIR/api.pid"
API_LOG="$STATE_DIR/api.log"
FRONTEND_BUILD_LOG="$STATE_DIR/frontend-build.log"
BACKEND_URL="http://127.0.0.1:${API_PORT}"
DASHBOARD_URL="${BACKEND_URL}/dashboard"
HEALTH_URL="${BACKEND_URL}/health"
DATABASE_URL_DEFAULT="postgresql://finance_agent:finance_agent@127.0.0.1:55432/finance_agent"

mkdir -p "$STATE_DIR"

usage() {
  cat <<'EOF'
Usage: scripts/local_stack_ctl.sh <start|stop|restart|status|logs> [--with-deps]

Commands:
  start       Start local PostgreSQL/Redis if needed, build frontend if stale, and launch API in background.
  stop        Stop API. Pass --with-deps to also stop local PostgreSQL/Redis.
  restart     Restart API. Pass --with-deps to also restart local PostgreSQL/Redis.
  status      Show PID, health, and entry URLs.
  logs        Tail API log and latest frontend build log.
EOF
}

pid_from_file() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  local pid
  pid="$(tr -d '[:space:]' <"$file")"
  [[ -n "$pid" ]] || return 1
  printf '%s\n' "$pid"
}

pid_running() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

cleanup_pid_file() {
  local file="$1"
  if pid="$(pid_from_file "$file" 2>/dev/null)"; then
    if ! pid_running "$pid"; then
      rm -f "$file"
    fi
  fi
}

listening_pid_for_port() {
  ss -ltnp 2>/dev/null | sed -nE "s/.*:${API_PORT} .*pid=([0-9]+).*/\\1/p" | head -n 1
}

adopt_existing_api() {
  cleanup_pid_file "$API_PID_FILE"
  if [[ -f "$API_PID_FILE" ]]; then
    return 0
  fi
  local pid
  pid="$(listening_pid_for_port || true)"
  if [[ -n "$pid" ]] && pid_running "$pid" && wait_for_http "$HEALTH_URL" 1 1; then
    printf '%s\n' "$pid" >"$API_PID_FILE"
  fi
}

wait_for_http() {
  local url="$1"
  local attempts="${2:-30}"
  local sleep_seconds="${3:-1}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl --noproxy '*' -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_seconds"
  done
  return 1
}

frontend_build_needed() {
  local index="$FRONTEND_DIR/dist/index.html"
  if [[ ! -f "$index" ]]; then
    return 0
  fi
  if [[ "$FRONTEND_DIR/package.json" -nt "$index" || "$FRONTEND_DIR/vite.config.ts" -nt "$index" || "$FRONTEND_DIR/index.html" -nt "$index" ]]; then
    return 0
  fi
  if find "$FRONTEND_DIR/src" "$FRONTEND_DIR/public" -type f -newer "$index" -print -quit 2>/dev/null | grep -q .; then
    return 0
  fi
  return 1
}

build_frontend() {
  echo "Building apps/frontend-web..."
  if ! (
    cd "$FRONTEND_DIR"
    npm run build >"$FRONTEND_BUILD_LOG" 2>&1
  ); then
    echo "Frontend build failed. Log: $FRONTEND_BUILD_LOG" >&2
    tail -n 80 "$FRONTEND_BUILD_LOG" >&2 || true
    exit 1
  fi
  echo "Frontend build ready."
}

ensure_local_services() {
  echo "Checking PostgreSQL/Redis..."
  "$PROJECT_ROOT/scripts/start_local_services.sh"
}

start_api() {
  adopt_existing_api

  if existing_pid="$(pid_from_file "$API_PID_FILE" 2>/dev/null)"; then
    if pid_running "$existing_pid" && wait_for_http "$HEALTH_URL" 2 1; then
      echo "API already running (pid=$existing_pid)."
      return 0
    fi
    rm -f "$API_PID_FILE"
  fi

  echo "Starting API on ${BACKEND_URL}..."
  (
    cd "$PROJECT_ROOT"
    export no_proxy=127.0.0.1,localhost,::1
    export DATABASE_URL="${DATABASE_URL:-$DATABASE_URL_DEFAULT}"
    export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
    export FINANCE_AGENT_FRONTEND_DIST_DIR="$FRONTEND_DIR/dist"
    setsid .venv/bin/python -m uvicorn apps.api.main:app --host 0.0.0.0 --port "$API_PORT" >"$API_LOG" 2>&1 < /dev/null &
    echo $! >"$API_PID_FILE"
  )

  if ! wait_for_http "$HEALTH_URL" 45 1; then
    echo "API failed to become healthy. Log: $API_LOG" >&2
    tail -n 120 "$API_LOG" >&2 || true
    exit 1
  fi
}

stop_api() {
  cleanup_pid_file "$API_PID_FILE"
  if ! pid="$(pid_from_file "$API_PID_FILE" 2>/dev/null)"; then
    echo "API is not running."
    return 0
  fi

  echo "Stopping API (pid=$pid)..."
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! pid_running "$pid"; then
      rm -f "$API_PID_FILE"
      echo "API stopped."
      return 0
    fi
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$API_PID_FILE"
  echo "API force stopped."
}

show_status() {
  adopt_existing_api
  local api_status="stopped"
  local api_pid=""
  if api_pid="$(pid_from_file "$API_PID_FILE" 2>/dev/null)"; then
    if pid_running "$api_pid"; then
      api_status="running"
    else
      api_pid=""
    fi
  fi

  echo "finance-agent local stack"
  echo "  API status:        $api_status${api_pid:+ (pid=$api_pid)}"
  if wait_for_http "$HEALTH_URL" 1 1; then
    echo "  Health:            ok ($HEALTH_URL)"
  else
    echo "  Health:            unavailable ($HEALTH_URL)"
  fi
  echo "  Dashboard:         $DASHBOARD_URL"
  echo "  API log:           $API_LOG"
  echo "  Build log:         $FRONTEND_BUILD_LOG"
}

tail_logs() {
  echo "== API log =="
  tail -n 80 "$API_LOG" 2>/dev/null || echo "(missing)"
  echo ""
  echo "== Frontend build log =="
  tail -n 80 "$FRONTEND_BUILD_LOG" 2>/dev/null || echo "(missing)"
}

command="${1:-start}"
with_deps="0"
if [[ "${2:-}" == "--with-deps" ]]; then
  with_deps="1"
fi

case "$command" in
  start)
    ensure_local_services
    if frontend_build_needed; then
      build_frontend
    else
      echo "Frontend build is up to date."
    fi
    start_api
    show_status
    ;;
  stop)
    stop_api
    if [[ "$with_deps" == "1" ]]; then
      "$PROJECT_ROOT/scripts/stop_local_services.sh"
    fi
    ;;
  restart)
    stop_api
    if [[ "$with_deps" == "1" ]]; then
      "$PROJECT_ROOT/scripts/stop_local_services.sh"
    fi
    ensure_local_services
    build_frontend
    start_api
    show_status
    ;;
  status)
    show_status
    ;;
  logs)
    tail_logs
    ;;
  *)
    usage
    exit 1
    ;;
esac
