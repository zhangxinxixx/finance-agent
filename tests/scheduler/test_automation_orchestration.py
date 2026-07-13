from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def test_hourly_orchestration_scheduler_wrapper_calls_orchestrator(monkeypatch, tmp_path) -> None:
    from apps.scheduler import automation_orchestration

    calls: list[dict] = []

    def fake_run_data_control_agent(**kwargs):
        calls.append({"data_control": kwargs})
        return {"status": "partial", "artifacts": {"hourly_report_json": "data_control/2026-07-08/hourly.json"}}

    def fake_run_data_quality_monitor(**kwargs):
        calls.append({"data_quality": kwargs})
        return {"downstream_readiness": {"readiness": "blocked"}}

    def fake_run_automation_orchestrator(**kwargs):
        calls.append({"orchestrator": kwargs})
        return {"status": "blocked", "trigger": kwargs["trigger"]}

    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(automation_orchestration, "run_data_control_agent", fake_run_data_control_agent)
    monkeypatch.setattr(automation_orchestration, "run_data_quality_monitor", fake_run_data_quality_monitor)
    monkeypatch.setattr(automation_orchestration, "run_automation_orchestrator", fake_run_automation_orchestrator)

    result = automation_orchestration.run_hourly_orchestration(
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc),
        storage_root=tmp_path / "storage",
        send_notifications=True,
    )

    assert result["trigger"] == "hourly"
    assert result["data_control"]["status"] == "partial"
    assert result["data_quality"]["downstream_readiness"]["readiness"] == "blocked"
    assert list(calls[0]) == ["data_control"]
    assert list(calls[1]) == ["data_quality"]
    assert list(calls[2]) == ["orchestrator"]
    assert calls[0]["data_control"]["trade_date"] == "2026-07-08"
    assert calls[0]["data_control"]["observed_at"] == datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)
    assert calls[0]["data_control"]["record_task_run"] is True
    assert calls[1]["data_quality"]["trade_date"] == "2026-07-08"
    assert calls[1]["data_quality"]["record_task_run"] is True
    assert calls[2]["orchestrator"]["trigger"] == "hourly"
    assert calls[2]["orchestrator"]["trade_date"] == "2026-07-08"
    assert calls[2]["orchestrator"]["hour"] == "10"
    assert calls[2]["orchestrator"]["storage_root"] == tmp_path / "storage"
    assert calls[2]["orchestrator"]["send_notifications"] is True
    assert calls[2]["orchestrator"]["record_task_run"] is True
    assert automation_orchestration.os.environ["no_proxy"] == "127.0.0.1,localhost,::1"


def test_pre_analysis_orchestration_scheduler_wrapper_calls_orchestrator(monkeypatch) -> None:
    from apps.scheduler import automation_orchestration

    calls: list[dict] = []

    def fake_run_data_quality_monitor(**kwargs):
        calls.append({"data_quality": kwargs})
        return {"downstream_readiness": {"readiness": "ready"}}

    def fake_run_automation_orchestrator(**kwargs):
        calls.append({"orchestrator": kwargs})
        return {"status": "normal"}

    monkeypatch.setattr(automation_orchestration, "run_data_quality_monitor", fake_run_data_quality_monitor)
    monkeypatch.setattr(automation_orchestration, "run_automation_orchestrator", fake_run_automation_orchestrator)

    result = automation_orchestration.run_pre_analysis_orchestration(
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 20, 0, tzinfo=timezone.utc),
        send_notifications=False,
    )

    assert result["status"] == "normal"
    assert result["data_quality"]["downstream_readiness"]["readiness"] == "ready"
    assert list(calls[0]) == ["data_quality"]
    assert list(calls[1]) == ["orchestrator"]
    assert calls[0]["data_quality"]["trade_date"] == "2026-07-08"
    assert calls[0]["data_quality"]["record_task_run"] is True
    assert calls[1]["orchestrator"]["trigger"] == "pre_analysis"
    assert calls[1]["orchestrator"]["hour"] == "20"
    assert calls[1]["orchestrator"]["send_notifications"] is False
    assert calls[1]["orchestrator"]["storage_root"] == Path("./storage")


def test_event_sla_orchestration_scheduler_wrapper_runs_pipeline_then_orchestrator(monkeypatch, tmp_path) -> None:
    from apps.scheduler import automation_orchestration

    calls: list[dict] = []

    def fake_run_event_sla_pipeline(**kwargs):
        calls.append({"pipeline": kwargs})
        return {"created_count": 1, "events": [{"event_id": "jin10-1"}]}

    def fake_run_automation_orchestrator(**kwargs):
        calls.append({"orchestrator": kwargs})
        return {"status": "normal", "trigger": kwargs["trigger"]}

    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(automation_orchestration, "run_event_sla_pipeline", fake_run_event_sla_pipeline)
    monkeypatch.setattr(automation_orchestration, "run_automation_orchestrator", fake_run_automation_orchestrator)

    result = automation_orchestration.run_event_sla_orchestration(
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 35, tzinfo=timezone.utc),
        storage_root=tmp_path / "storage",
        send_notifications=True,
        record_task_run=True,
    )

    assert result["trigger"] == "event_sla"
    assert result["event_sla"]["created_count"] == 1
    assert calls[0]["pipeline"]["trade_date"] == "2026-07-08"
    assert calls[0]["pipeline"]["source_types"] == ("jin10", "cme")
    assert calls[0]["pipeline"]["record_task_run"] is True
    assert calls[1]["orchestrator"]["trigger"] == "event_sla"
    assert calls[1]["orchestrator"]["hour"] == "10"
    assert calls[1]["orchestrator"]["send_notifications"] is True
    assert calls[1]["orchestrator"]["storage_root"] == tmp_path / "storage"
    assert automation_orchestration.os.environ["no_proxy"] == "127.0.0.1,localhost,::1"


def test_incident_orchestration_scheduler_wrapper_refreshes_quality_then_orchestrates(monkeypatch, tmp_path) -> None:
    from apps.scheduler import automation_orchestration

    calls: list[dict] = []

    def fake_run_data_quality_monitor(**kwargs):
        calls.append({"data_quality": kwargs})
        return {"downstream_readiness": {"readiness": "blocked"}}

    def fake_run_automation_orchestrator(**kwargs):
        calls.append({"orchestrator": kwargs})
        return {"status": "blocked", "trigger": kwargs["trigger"]}

    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(automation_orchestration, "run_data_quality_monitor", fake_run_data_quality_monitor)
    monkeypatch.setattr(automation_orchestration, "run_automation_orchestrator", fake_run_automation_orchestrator)

    result = automation_orchestration.run_incident_orchestration(
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 45, tzinfo=timezone.utc),
        storage_root=tmp_path / "storage",
        send_notifications=True,
        record_task_run=True,
    )

    assert result["trigger"] == "incident"
    assert result["data_quality"]["downstream_readiness"]["readiness"] == "blocked"
    assert list(calls[0]) == ["data_quality"]
    assert list(calls[1]) == ["orchestrator"]
    assert calls[0]["data_quality"]["trade_date"] == "2026-07-08"
    assert calls[1]["orchestrator"]["trigger"] == "incident"
    assert calls[1]["orchestrator"]["hour"] == "10"
    assert calls[1]["orchestrator"]["send_notifications"] is True
    assert calls[1]["orchestrator"]["storage_root"] == tmp_path / "storage"
    assert automation_orchestration.os.environ["no_proxy"] == "127.0.0.1,localhost,::1"


def test_notification_retry_queue_sends_due_items_and_updates_artifacts(tmp_path) -> None:
    from apps.scheduler import automation_orchestration

    storage_root = tmp_path / "storage"
    base = storage_root / "orchestration" / "2026-07-08"
    base.mkdir(parents=True, exist_ok=True)
    (base / "notification_plan.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-07-08",
                "requests": [
                    {
                        "kind": "hourly_report",
                        "title": "Hourly blocked",
                        "summary": "status=blocked",
                        "severity": "critical",
                        "facts": {"status": "blocked"},
                        "source_refs": [],
                        "dry_run": False,
                        "trade_date": "2026-07-08",
                        "dedupe_key": "hourly_report:2026-07-08:10",
                    },
                    {
                        "kind": "incident",
                        "title": "Incident blocked",
                        "summary": "blocked",
                        "severity": "critical",
                        "facts": {"status": "blocked"},
                        "source_refs": [],
                        "dry_run": False,
                        "trade_date": "2026-07-08",
                        "dedupe_key": "incident:2026-07-08:blocked",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (base / "retry_queue.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-07-08",
                "count": 2,
                "items": [
                    {
                        "kind": "hourly_report",
                        "dedupe_key": "hourly_report:2026-07-08:10",
                        "attempts": 3,
                        "max_attempts": 3,
                        "next_retry_at": "2026-07-08T10:29:00+00:00",
                        "backoff_seconds": 240,
                        "error": "temporary",
                    },
                    {
                        "kind": "incident",
                        "dedupe_key": "incident:2026-07-08:blocked",
                        "attempts": 3,
                        "max_attempts": 3,
                        "next_retry_at": "2026-07-08T10:45:00+00:00",
                        "backoff_seconds": 240,
                        "error": "temporary",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sent: list[str] = []

    class Sender:
        def send(self, request):
            sent.append(request.kind)
            return type("Result", (), {"to_dict": lambda self: {"ok": True, "status": "sent", "kind": request.kind, "title": request.title}})()

    result = automation_orchestration.run_notification_retry_queue(
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 30, tzinfo=timezone.utc),
        storage_root=storage_root,
        notification_agent=Sender(),
    )

    assert sent == ["hourly_report"]
    assert result["processed_count"] == 1
    assert result["remaining_count"] == 1
    retry_queue = json.loads((base / "retry_queue.json").read_text(encoding="utf-8"))
    assert retry_queue["items"][0]["dedupe_key"] == "incident:2026-07-08:blocked"
    retry_results = json.loads((base / "notification_retry_results.json").read_text(encoding="utf-8"))
    assert retry_results["results"][0]["dedupe_key"] == "hourly_report:2026-07-08:10"
    assert retry_results["results"][0]["status"] == "sent"
    delivery_log = json.loads((base / "notification_delivery_log.json").read_text(encoding="utf-8"))
    assert delivery_log["deliveries"][0]["dedupe_key"] == "hourly_report:2026-07-08:10"
    assert delivery_log["deliveries"][0]["status"] == "sent"
    assert delivery_log["deliveries"][0]["sent_at"] == "2026-07-08T10:30:00+00:00"


def test_notification_retry_recovers_from_outbox_without_run_notification_plan(tmp_path) -> None:
    from apps.scheduler import automation_orchestration

    storage_root = tmp_path / "storage"
    outbox_path = storage_root / "orchestration" / "outbox" / "notification-1.json"
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    outbox_path.write_text(
        json.dumps(
            {
                "notification_id": "notification-1",
                "source_run_id": "hourly-run-1",
                "trade_date": "2026-07-08",
                "status": "pending_retry",
                "dedupe_key": "hourly_report:2026-07-08:10",
                "request": {
                    "kind": "hourly_report",
                    "title": "Hourly blocked",
                    "summary": "status=blocked",
                    "severity": "critical",
                    "facts": {"status": "blocked"},
                    "sections": [],
                    "source_refs": [],
                    "dry_run": False,
                    "trade_date": "2026-07-08",
                },
                "attempt_count": 3,
                "next_retry_at": "2026-07-08T10:29:00+00:00",
                "last_error": "temporary",
                "attempts": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sent: list[str] = []

    class Sender:
        def send(self, request):
            sent.append(request.title)
            return type(
                "Result",
                (),
                {"to_dict": lambda self: {"ok": True, "status": "sent", "kind": request.kind, "title": request.title}},
            )()

    result = automation_orchestration.run_notification_retry_queue(
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 30, tzinfo=timezone.utc),
        storage_root=storage_root,
        notification_agent=Sender(),
    )

    assert sent == ["Hourly blocked"]
    assert result["processed_count"] == 1
    updated = json.loads(outbox_path.read_text(encoding="utf-8"))
    assert updated["status"] == "sent"
    assert updated["attempt_count"] == 4
    assert updated["last_error"] is None
