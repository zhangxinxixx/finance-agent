from __future__ import annotations

import json

from scripts import run_data_quality_monitor as script


def test_run_data_quality_monitor_prints_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        script,
        "run_data_quality_monitor",
        lambda **kwargs: {
            "trade_date": kwargs["trade_date"],
            "observed_at": "2026-07-08T03:00:00+00:00",
            "data_quality_report": {"overall_status": "partial"},
            "downstream_readiness": {
                "readiness": "partial",
                "can_run_full_analysis": False,
                "can_run_research_distillation": False,
            },
            "artifacts": {
                "source_health": "monitoring/2026-07-08/source_health.json",
                "data_quality_report": "monitoring/2026-07-08/data_quality_report.json",
                "downstream_readiness": "monitoring/2026-07-08/downstream_readiness.json",
            },
        },
    )

    rc = script.main(["--date", "2026-07-08", "--storage-root", "/tmp/storage", "--no-record-task"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trade_date"] == "2026-07-08"
    assert payload["readiness"] == "partial"
    assert payload["artifacts"]["source_health"].endswith("source_health.json")
