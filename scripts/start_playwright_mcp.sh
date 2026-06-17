#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/start_playwright_mcp.sh stdio-local
  scripts/start_playwright_mcp.sh stdio-jin10
  scripts/start_playwright_mcp.sh http-local
  scripts/start_playwright_mcp.sh http-jin10

Environment overrides:
  PLAYWRIGHT_MCP_BROWSER=chrome
  PLAYWRIGHT_MCP_VIEWPORT=1440x1000
  PLAYWRIGHT_MCP_PROFILE=/path/to/profile
  PLAYWRIGHT_MCP_OUTPUT_DIR=/path/to/output
  PLAYWRIGHT_MCP_PORT=8931
  JIN10_BROWSER_PROFILE=/home/zxx/.hermes/jin10_browser_profile
EOF
}

MODE="${1:-stdio-local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BROWSER="${PLAYWRIGHT_MCP_BROWSER:-chrome}"
VIEWPORT="${PLAYWRIGHT_MCP_VIEWPORT:-1440x1000}"
CONSOLE_LEVEL="${PLAYWRIGHT_MCP_CONSOLE_LEVEL:-warning}"
OUTPUT_ROOT="${PLAYWRIGHT_MCP_OUTPUT_DIR:-$REPO_ROOT/output/playwright-mcp}"
BLOCKED_ORIGINS="${PLAYWRIGHT_MCP_BLOCKED_ORIGINS:-http://169.254.169.254;http://metadata.google.internal}"

case "$MODE" in
  stdio-local|http-local)
    PROFILE="${PLAYWRIGHT_MCP_PROFILE:-$HOME/.hermes/playwright_mcp_profile/finance-agent}"
    OUTPUT_DIR="$OUTPUT_ROOT/local"
    ;;
  stdio-jin10|http-jin10)
    PROFILE="${PLAYWRIGHT_MCP_PROFILE:-${JIN10_BROWSER_PROFILE:-$HOME/.hermes/jin10_browser_profile}}"
    OUTPUT_DIR="$OUTPUT_ROOT/jin10"
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    usage
    exit 2
    ;;
esac

mkdir -p "$PROFILE" "$OUTPUT_DIR"

args=(
  --yes
  @playwright/mcp@latest
  --browser "$BROWSER"
  --user-data-dir "$PROFILE"
  --output-dir "$OUTPUT_DIR"
  --save-session
  --viewport-size "$VIEWPORT"
  --console-level "$CONSOLE_LEVEL"
  --blocked-origins "$BLOCKED_ORIGINS"
)

case "$MODE" in
  http-*)
    args+=(--host "${PLAYWRIGHT_MCP_HOST:-127.0.0.1}")
    args+=(--port "${PLAYWRIGHT_MCP_PORT:-8931}")
    args+=(--allowed-hosts "${PLAYWRIGHT_MCP_ALLOWED_HOSTS:-127.0.0.1,localhost}")
    ;;
esac

exec npx "${args[@]}"
