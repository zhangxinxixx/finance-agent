from __future__ import annotations

import json

from scripts import run_automation_orchestrator as script


def test_run_automation_orchestrator_prints_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        script,
        "run_automation_orchestrator",
        lambda **kwargs: {
            "trade_date": kwargs["trade_date"],
            "observed_at": "2026-07-08T10:30:00+00:00",
            "trigger": kwargs["trigger"],
            "status": "blocked",
            "artifacts": {
                "orchestration_plan": "orchestration/2026-07-08/orchestration_plan.json",
                "notification_plan": "orchestration/2026-07-08/notification_plan.json",
                "automation_summary": "orchestration/2026-07-08/automation_summary.json",
                "workflow_runs": "orchestration/2026-07-08/workflow_runs.json",
            },
            "notification_results": [],
            "task_run_id": None,
        },
    )

    rc = script.main(["--date", "2026-07-08", "--trigger", "pre_analysis", "--hour", "10", "--storage-root", "/tmp/storage", "--no-record-task"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trigger"] == "pre_analysis"
    assert payload["status"] == "blocked"
    assert payload["artifacts"]["notification_plan"].endswith("notification_plan.json")
    assert payload["artifacts"]["workflow_runs"].endswith("workflow_runs.json")
