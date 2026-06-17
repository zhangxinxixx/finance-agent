from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_cli_dry_run_accepts_message_argument():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/send_feishu_message.py",
            "--message",
            "hello",
            "--webhook-url",
            "https://example.com/webhook",
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert '"dry_run": true' in result.stdout
    assert '"msg_type": "text"' in result.stdout


def test_cli_reads_message_file_in_dry_run(tmp_path: Path):
    message_file = tmp_path / "message.md"
    message_file.write_text("report body", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/send_feishu_message.py",
            "--message-file",
            str(message_file),
            "--title",
            "Daily Report",
            "--message-type",
            "post",
            "--webhook-url",
            "https://example.com/webhook",
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Daily Report" in result.stdout
    assert "report body" in result.stdout
    assert '"msg_type": "post"' in result.stdout


def test_cli_requires_webhook_url_when_not_in_env(monkeypatch):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)

    result = subprocess.run(
        [sys.executable, "scripts/send_feishu_message.py", "--message", "hello", "--dry-run"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "FEISHU_WEBHOOK_URL" in result.stderr
