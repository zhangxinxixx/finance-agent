#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$ROOT/deploy/systemd"
DST_DIR="$HOME/.config/systemd/user"

mkdir -p "$DST_DIR"
install -m 0644 "$SRC_DIR/report-window-scanner.service" "$DST_DIR/report-window-scanner.service"
install -m 0644 "$SRC_DIR/report-window-scanner.timer" "$DST_DIR/report-window-scanner.timer"

systemctl --user daemon-reload
systemctl --user disable --now jin10-daily-scheduler.timer
systemctl --user enable --now report-window-scanner.timer
systemctl --user list-timers report-window-scanner.timer --all
