from __future__ import annotations

import json
import sys

from scripts import send_feishu_test_message


def test_send_feishu_test_message_dry_run_without_task_recording(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "send_feishu_test_message.py",
            "--dry-run",
            "--no-record-task",
            "--message",
            "hello",
            "--title",
            "Test",
        ],
    )

    exit_code = send_feishu_test_message.main()

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "dry_run"
    assert payload["payload_preview"]["title"] == "Test"
