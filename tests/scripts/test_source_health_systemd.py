from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_source_health_systemd_units_are_daily_user_timer() -> None:
    service = PROJECT_ROOT / "deploy/systemd/source-health-snapshot.service"
    timer = PROJECT_ROOT / "deploy/systemd/source-health-snapshot.timer"

    service_text = service.read_text(encoding="utf-8")
    timer_text = timer.read_text(encoding="utf-8")

    assert "WorkingDirectory=%h/workspace/finance-agent" in service_text
    assert "Environment=no_proxy=127.0.0.1,localhost,::1" in service_text
    assert "Environment=UV_CACHE_DIR=/tmp/uv-cache" in service_text
    assert "ExecStart=/usr/bin/env uv run python scripts/record_data_source_health_snapshot.py" in service_text
    assert "WorkingDirectory=/home/" not in service_text
    assert "ExecStart=/home/" not in service_text

    assert "OnCalendar=*-*-* 10:05:00" in timer_text
    assert "Persistent=true" in timer_text
    assert "Unit=source-health-snapshot.service" in timer_text


def test_source_health_systemd_installer_dry_run_does_not_write(tmp_path: Path) -> None:
    user_dir = tmp_path / "systemd-user"

    result = subprocess.run(
        [
            "bash",
            "scripts/install_source_health_snapshot_systemd.sh",
            "--dry-run",
            "--root",
            str(PROJECT_ROOT),
            "--user-dir",
            str(user_dir),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "[dry-run]" in result.stdout
    assert "source-health-snapshot.service" in result.stdout
    assert "systemctl --user enable --now source-health-snapshot.timer" in result.stdout
    assert not user_dir.exists()
