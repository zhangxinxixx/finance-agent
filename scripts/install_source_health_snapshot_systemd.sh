#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DST_DIR="${HOME}/.config/systemd/user"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/install_source_health_snapshot_systemd.sh [--dry-run] [--root PATH] [--user-dir PATH]

Installs the Finance Agent source-health snapshot user systemd timer.

Options:
  --dry-run        Print planned writes and systemctl commands without executing them.
  --root PATH     Project root containing deploy/systemd. Defaults to this script's repo.
  --user-dir PATH Destination user systemd directory. Defaults to ~/.config/systemd/user.
  -h, --help      Show this help.
EOF
}

log_cmd() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    printf '%s\n' "$*"
  fi
}

run_cmd() {
  log_cmd "$*"
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    "$@"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --root)
      if [[ $# -lt 2 ]]; then
        printf 'error: --root requires a path\n' >&2
        exit 2
      fi
      ROOT="$2"
      shift 2
      ;;
    --user-dir)
      if [[ $# -lt 2 ]]; then
        printf 'error: --user-dir requires a path\n' >&2
        exit 2
      fi
      DST_DIR="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf 'error: unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd "${ROOT}" && pwd)"
SRC_DIR="${ROOT}/deploy/systemd"
SERVICE_SRC="${SRC_DIR}/source-health-snapshot.service"
TIMER_SRC="${SRC_DIR}/source-health-snapshot.timer"
SERVICE_DST="${DST_DIR}/source-health-snapshot.service"
TIMER_DST="${DST_DIR}/source-health-snapshot.timer"

if [[ ! -f "${SERVICE_SRC}" || ! -f "${TIMER_SRC}" ]]; then
  printf 'error: expected source health systemd units under %s\n' "${SRC_DIR}" >&2
  exit 1
fi

run_cmd mkdir -p "${DST_DIR}"
run_cmd install -m 0644 "${SERVICE_SRC}" "${SERVICE_DST}"
run_cmd install -m 0644 "${TIMER_SRC}" "${TIMER_DST}"
run_cmd systemctl --user daemon-reload
run_cmd systemctl --user enable --now source-health-snapshot.timer
run_cmd systemctl --user list-timers source-health-snapshot.timer --all
