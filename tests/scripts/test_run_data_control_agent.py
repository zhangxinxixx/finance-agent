from __future__ import annotations

import json

from scripts import run_data_control_agent as script


def test_run_data_control_agent_prints_hourly_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        script,
        "run_data_control_agent",
        lambda **kwargs: {
            "trade_date": kwargs["trade_date"],
            "observed_at": "2026-07-08T10:15:00+00:00",
            "hour": "10",
            "status": "blocked",
            "main_analysis_readiness": "blocked",
            "knowledge_distillation_readiness": "blocked",
            "artifacts": {
                "data_availability_snapshot": "data_control/2026-07-08/data_availability_snapshot.json",
                "collection_plan": "data_control/2026-07-08/collection_plan_10.json",
                "processing_plan": "data_control/2026-07-08/processing_plan_10.json",
                "hourly_report_json": "data_control/2026-07-08/hourly_collection_processing_report_10.json",
                "hourly_report_md": "data_control/2026-07-08/hourly_collection_processing_report_10.md",
            },
            "notification_request": {"kind": "hourly_report", "severity": "critical"},
            "task_run_id": None,
        },
    )

    rc = script.main(["--date", "2026-07-08", "--storage-root", "/tmp/storage", "--no-record-task"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trade_date"] == "2026-07-08"
    assert payload["status"] == "blocked"
    assert payload["notification_request"]["kind"] == "hourly_report"
