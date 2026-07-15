from __future__ import annotations

import json

from scripts import run_data_quality_monitor as script


def test_run_data_quality_monitor_prints_summary(monkeypatch, capsys) -> None:
    calls = []

    def fake_run_data_quality_monitor(**kwargs):
        calls.append(kwargs)
        return {
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
        }

    monkeypatch.setattr(
        script,
        "run_data_quality_monitor",
        fake_run_data_quality_monitor,
    )

    rc = script.main(
        [
            "--date",
            "2026-07-08",
            "--storage-root",
            "/tmp/storage",
            "--run-source-probes",
            "--run-consistency-checks",
            "--probe-limit",
            "3",
            "--no-record-task",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trade_date"] == "2026-07-08"
    assert payload["readiness"] == "partial"
    assert payload["artifacts"]["source_health"].endswith("source_health.json")
    assert calls[0]["run_source_probes"] is True
    assert calls[0]["probe_limit"] == 3
    assert calls[0]["run_consistency_checks"] is True
