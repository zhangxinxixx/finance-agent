#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/apps/frontend-web"
STATE_DIR="${FINANCE_AGENT_STATE_DIR:-/tmp/finance-agent-stack}"
API_PORT="${FINANCE_AGENT_API_PORT:-8000}"
FRONTEND_PORT="${FINANCE_AGENT_FRONTEND_PORT:-8080}"
FRONTEND_MODE_DEFAULT="${FINANCE_AGENT_FRONTEND_MODE:-dev}"
EVENT_FLOW_TRANSLATION_PROVIDER_DEFAULT="${FINANCE_AGENT_EVENT_FLOW_TRANSLATION_PROVIDER:-${EVENT_FLOW_TRANSLATION_PROVIDER:-}}"
EVENT_FLOW_TRANSLATION_MODEL_DEFAULT="${FINANCE_AGENT_EVENT_FLOW_TRANSLATION_MODEL:-${EVENT_FLOW_TRANSLATION_MODEL:-}}"
API_PID_FILE="$STATE_DIR/api.pid"
API_LOG="$STATE_DIR/api.log"
FRONTEND_PID_FILE="$STATE_DIR/frontend.pid"
FRONTEND_LOG="$STATE_DIR/frontend.log"
FRONTEND_BUILD_LOG="$STATE_DIR/frontend-build.log"
BACKEND_URL="http://127.0.0.1:${API_PORT}"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"
DASHBOARD_API_URL="${BACKEND_URL}/dashboard"
DASHBOARD_FRONTEND_URL="${FRONTEND_URL}/dashboard"
HEALTH_URL="${BACKEND_URL}/health"
DATABASE_URL_DEFAULT="postgresql://finance_agent:finance_agent@127.0.0.1:55432/finance_agent"

mkdir -p "$STATE_DIR"

usage() {
  cat <<'EOF'
Usage: scripts/local_stack_ctl.sh <start|stop|restart|status|logs> [--with-deps] [--frontend=dev|build|none] [--dry-run]

Commands:
  start       Start local PostgreSQL/Redis if needed, launch API, and optionally launch frontend.
  stop        Stop API and managed frontend dev server. Pass --with-deps to also stop local PostgreSQL/Redis.
  restart     Restart API and managed frontend. Pass --with-deps to also restart local PostgreSQL/Redis.
  status      Show PID, health, and entry URLs.
  logs        Tail API / frontend / build logs.

Frontend modes:
  dev         Start Vite dev server on FINANCE_AGENT_FRONTEND_PORT (default 8080).
  build       Build apps/frontend-web/dist and let FastAPI serve /dashboard.
  none        Do not manage frontend.

Event Flow translation:
  Set FINANCE_AGENT_EVENT_FLOW_TRANSLATION_PROVIDER=mimo to enable the Event Flow translation hub.
  Optionally set FINANCE_AGENT_EVENT_FLOW_TRANSLATION_MODEL=mimo-v2.5 to override the model.
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

run_or_echo() {
  if [[ "$dry_run" == "1" ]]; then
    printf '[dry-run] '
    printf '%q ' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

listening_pid_for_port() {
  local port="$1"
  ss -ltnp 2>/dev/null | sed -nE "s/.*:${port} .*pid=([0-9]+).*/\\1/p" | head -n 1
}

adopt_existing_api() {
  cleanup_pid_file "$API_PID_FILE"
  if [[ -f "$API_PID_FILE" ]]; then
    return 0
  fi
  local pid
  pid="$(listening_pid_for_port "$API_PORT" || true)"
  if [[ -n "$pid" ]] && pid_running "$pid" && wait_for_http "$HEALTH_URL" 1 1; then
    printf '%s\n' "$pid" >"$API_PID_FILE"
  fi
}

adopt_existing_frontend() {
  cleanup_pid_file "$FRONTEND_PID_FILE"
  if [[ -f "$FRONTEND_PID_FILE" ]]; then
    return 0
  fi
  local pid
  pid="$(listening_pid_for_port "$FRONTEND_PORT" || true)"
  if [[ -n "$pid" ]] && pid_running "$pid" && wait_for_http "$DASHBOARD_FRONTEND_URL" 1 1; then
    printf '%s\n' "$pid" >"$FRONTEND_PID_FILE"
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
  if [[ "$dry_run" == "1" ]]; then
    echo "[dry-run] (cd \"$FRONTEND_DIR\" && npm run build >\"$FRONTEND_BUILD_LOG\" 2>&1)"
    return 0
  fi
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
  if [[ "$dry_run" == "1" ]]; then
    echo "[dry-run] $PROJECT_ROOT/scripts/start_local_services.sh"
    return 0
  fi
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
  if [[ "$dry_run" == "1" ]]; then
    echo "[dry-run] start uvicorn -> $API_LOG"
    return 0
  fi
  (
    cd "$PROJECT_ROOT"
    export no_proxy=127.0.0.1,localhost,::1
    export DATABASE_URL="${DATABASE_URL:-$DATABASE_URL_DEFAULT}"
    export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
    export FINANCE_AGENT_FRONTEND_DIST_DIR="$FRONTEND_DIR/dist"
    export FRONTEND_WEB_URL="${FRONTEND_WEB_URL:-$FRONTEND_URL}"
    local -a api_env
    api_env=()
    if [[ -n "${EVENT_FLOW_TRANSLATION_PROVIDER_DEFAULT}" ]]; then
      api_env+=("EVENT_FLOW_TRANSLATION_PROVIDER=${EVENT_FLOW_TRANSLATION_PROVIDER_DEFAULT}")
    fi
    if [[ -n "${EVENT_FLOW_TRANSLATION_MODEL_DEFAULT}" ]]; then
      api_env+=("EVENT_FLOW_TRANSLATION_MODEL=${EVENT_FLOW_TRANSLATION_MODEL_DEFAULT}")
    fi
    setsid env "${api_env[@]}" .venv/bin/python -m uvicorn apps.api.main:app --host 0.0.0.0 --port "$API_PORT" >"$API_LOG" 2>&1 < /dev/null &
    echo $! >"$API_PID_FILE"
  )

  if ! wait_for_http "$HEALTH_URL" 45 1; then
    echo "API failed to become healthy. Log: $API_LOG" >&2
    tail -n 120 "$API_LOG" >&2 || true
    exit 1
  fi
}

start_frontend_dev() {
  adopt_existing_frontend

  if existing_pid="$(pid_from_file "$FRONTEND_PID_FILE" 2>/dev/null)"; then
    if pid_running "$existing_pid" && wait_for_http "$DASHBOARD_FRONTEND_URL" 2 1; then
      echo "Frontend dev server already running (pid=$existing_pid)."
      return 0
    fi
    rm -f "$FRONTEND_PID_FILE"
  fi

  echo "Starting frontend dev server on ${FRONTEND_URL}..."
  if [[ "$dry_run" == "1" ]]; then
    echo "[dry-run] start vite dev server -> $FRONTEND_LOG"
    return 0
  fi
  (
    cd "$FRONTEND_DIR"
    export no_proxy=127.0.0.1,localhost,::1
    export VITE_PROXY_TARGET="${VITE_PROXY_TARGET:-$BACKEND_URL}"
    setsid npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" >"$FRONTEND_LOG" 2>&1 < /dev/null &
    echo $! >"$FRONTEND_PID_FILE"
  )

  if ! wait_for_http "$DASHBOARD_FRONTEND_URL" 45 1; then
    echo "Frontend dev server failed to become ready. Log: $FRONTEND_LOG" >&2
    tail -n 120 "$FRONTEND_LOG" >&2 || true
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

stop_frontend() {
  cleanup_pid_file "$FRONTEND_PID_FILE"
  if ! pid="$(pid_from_file "$FRONTEND_PID_FILE" 2>/dev/null)"; then
    echo "Frontend dev server is not running."
    return 0
  fi

  echo "Stopping frontend dev server (pid=$pid)..."
  if [[ "$dry_run" == "1" ]]; then
    echo "[dry-run] kill $pid"
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! pid_running "$pid"; then
      rm -f "$FRONTEND_PID_FILE"
      echo "Frontend dev server stopped."
      return 0
    fi
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$FRONTEND_PID_FILE"
  echo "Frontend dev server force stopped."
}

show_status() {
  adopt_existing_api
  adopt_existing_frontend
  local api_status="stopped"
  local api_pid=""
  local frontend_status="stopped"
  local frontend_pid=""
  if api_pid="$(pid_from_file "$API_PID_FILE" 2>/dev/null)"; then
    if pid_running "$api_pid"; then
      api_status="running"
    else
      api_pid=""
    fi
  fi
  if frontend_pid="$(pid_from_file "$FRONTEND_PID_FILE" 2>/dev/null)"; then
    if pid_running "$frontend_pid"; then
      frontend_status="running"
    else
      frontend_pid=""
    fi
  fi

  echo "finance-agent local stack"
  echo "  API status:        $api_status${api_pid:+ (pid=$api_pid)}"
  echo "  Frontend status:   $frontend_status${frontend_pid:+ (pid=$frontend_pid)}"
  if wait_for_http "$HEALTH_URL" 1 1; then
    echo "  Health:            ok ($HEALTH_URL)"
  else
    echo "  Health:            unavailable ($HEALTH_URL)"
  fi
  if wait_for_http "$DASHBOARD_FRONTEND_URL" 1 1; then
    echo "  Frontend URL:      $FRONTEND_URL"
    echo "  Dashboard:         $DASHBOARD_FRONTEND_URL"
  else
    echo "  Dashboard:         $DASHBOARD_API_URL"
  fi
  echo "  API log:           $API_LOG"
  echo "  Frontend log:      $FRONTEND_LOG"
  echo "  Build log:         $FRONTEND_BUILD_LOG"
  echo "  Event Flow翻译:    ${EVENT_FLOW_TRANSLATION_PROVIDER_DEFAULT:-disabled}${EVENT_FLOW_TRANSLATION_MODEL_DEFAULT:+ (${EVENT_FLOW_TRANSLATION_MODEL_DEFAULT})}"
}

tail_logs() {
  echo "== API log =="
  tail -n 80 "$API_LOG" 2>/dev/null || echo "(missing)"
  echo ""
  echo "== Frontend log =="
  tail -n 80 "$FRONTEND_LOG" 2>/dev/null || echo "(missing)"
  echo ""
  echo "== Frontend build log =="
  tail -n 80 "$FRONTEND_BUILD_LOG" 2>/dev/null || echo "(missing)"
}

command="${1:-start}"
shift || true
with_deps="0"
frontend_mode="$FRONTEND_MODE_DEFAULT"
dry_run="0"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-deps)
      with_deps="1"
      ;;
    --frontend=*)
      frontend_mode="${1#--frontend=}"
      ;;
    --dry-run)
      dry_run="1"
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "$frontend_mode" != "dev" && "$frontend_mode" != "build" && "$frontend_mode" != "none" ]]; then
  echo "Invalid frontend mode: $frontend_mode" >&2
  usage >&2
  exit 1
fi

case "$command" in
  start)
    ensure_local_services
    start_api
    case "$frontend_mode" in
      dev)
        start_frontend_dev
        ;;
      build)
        stop_frontend
        if frontend_build_needed; then
          build_frontend
        else
          echo "Frontend build is up to date."
        fi
        ;;
      none)
        stop_frontend
        echo "Frontend management skipped."
        ;;
    esac
    show_status
    ;;
  stop)
    stop_frontend
    stop_api
    if [[ "$with_deps" == "1" ]]; then
      if [[ "$dry_run" == "1" ]]; then
        echo "[dry-run] $PROJECT_ROOT/scripts/stop_local_services.sh"
      else
        "$PROJECT_ROOT/scripts/stop_local_services.sh"
      fi
    fi
    ;;
  restart)
    stop_frontend
    stop_api
    if [[ "$with_deps" == "1" ]]; then
      if [[ "$dry_run" == "1" ]]; then
        echo "[dry-run] $PROJECT_ROOT/scripts/stop_local_services.sh"
      else
        "$PROJECT_ROOT/scripts/stop_local_services.sh"
      fi
    fi
    ensure_local_services
    start_api
    case "$frontend_mode" in
      dev)
        start_frontend_dev
        ;;
      build)
        stop_frontend
        build_frontend
        ;;
      none)
        stop_frontend
        echo "Frontend management skipped."
        ;;
    esac
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
