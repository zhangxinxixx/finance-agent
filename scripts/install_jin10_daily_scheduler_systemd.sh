#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${ROOT}/deploy/systemd"
DST_DIR="${HOME}/.config/systemd/user"

mkdir -p "${DST_DIR}"
install -m 0644 "${SRC_DIR}/jin10-daily-scheduler.service" "${DST_DIR}/jin10-daily-scheduler.service"
install -m 0644 "${SRC_DIR}/jin10-daily-scheduler.timer" "${DST_DIR}/jin10-daily-scheduler.timer"

systemctl --user daemon-reload
systemctl --user enable --now jin10-daily-scheduler.timer
systemctl --user list-timers jin10-daily-scheduler.timer --all
