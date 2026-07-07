from __future__ import annotations

import json

from scripts import run_event_sla_pipeline as script


def test_run_event_sla_pipeline_prints_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        script,
        "run_event_sla_pipeline",
        lambda **kwargs: {
            "trade_date": kwargs["trade_date"],
            "observed_at": "2026-07-08T10:20:00+00:00",
            "created_count": 1,
            "events": [
                {
                    "event_id": "jin10_research_master_review_223556_abcd1234",
                    "source_key": "jin10_research_master_review",
                    "status": "success",
                    "artifacts": {"sla_trace": "event_sla/2026-07-08/event/sla_trace.json"},
                }
            ],
        },
    )

    rc = script.main(["--date", "2026-07-08", "--storage-root", "/tmp/storage", "--source-type", "jin10", "--no-record-task"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created_count"] == 1
    assert payload["events"][0]["source_key"] == "jin10_research_master_review"
