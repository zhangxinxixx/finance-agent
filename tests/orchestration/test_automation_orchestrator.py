from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from apps.orchestration import automation_orchestrator
from apps.orchestration.automation_orchestrator import run_automation_orchestrator


OBSERVED_AT = datetime(2026, 7, 8, 10, 30, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _seed_upstream_artifacts(storage_root: Path) -> None:
    _write_json(
        storage_root / "data_control" / "2026-07-08" / "collection_plan_10.json",
        {"trade_date": "2026-07-08", "hour": "10", "status": "degraded", "actions": [{"source_key": "jin10_mcp_flash", "action": "refresh", "state": "stale"}]},
    )
    _write_json(
        storage_root / "data_control" / "2026-07-08" / "processing_plan_10.json",
        {"trade_date": "2026-07-08", "hour": "10", "status": "blocked", "blocked_steps": [{"reason_code": "downstream_quality_gate_blocked"}]},
    )
    _write_json(
        storage_root / "data_control" / "2026-07-08" / "dispatch_plan_10.json",
        {
            "trade_date": "2026-07-08",
            "hour": "10",
            "status": "ready",
            "execution_owner": "automation_orchestrator",
            "auto_execute": False,
            "requests": [
                {
                    "request_id": "data-control:2026-07-08:10:jin10_mcp_flash:jin10_flash_refresh",
                    "source_key": "jin10_mcp_flash",
                    "task_key": "jin10_flash_refresh",
                    "status": "ready",
                }
            ],
        },
    )
    _write_json(
        storage_root / "data_control" / "2026-07-08" / "hourly_collection_processing_report_10.json",
        {
            "trade_date": "2026-07-08",
            "hour": "10",
            "status": "blocked",
            "notification_request": {
                "kind": "hourly_report",
                "title": "Data control hourly report",
                "summary": "status=blocked",
                "severity": "critical",
                "facts": {"status": "blocked"},
                "source_refs": [],
                "dry_run": False,
                "trade_date": "2026-07-08",
                "sections": [],
            },
        },
    )
    _write_json(
        storage_root / "monitoring" / "2026-07-08" / "downstream_readiness.json",
        {
            "trade_date": "2026-07-08",
            "readiness": "blocked",
            "can_run_full_analysis": False,
            "can_run_research_distillation": False,
            "allowed_outputs": ["market snapshot"],
            "blocked_outputs": ["full analysis", "knowledge distillation"],
            "blocking_issues": [{"source_key": "jin10_mcp_market", "reason_code": "freshness_stale"}],
        },
    )
    event_dir = storage_root / "event_sla" / "2026-07-08" / "jin10_report_223556_hash"
    _write_json(event_dir / "sla_trace.json", {"event_id": "jin10_report_223556_hash", "source_key": "jin10_report", "status": "partial_success"})
    _write_json(
        event_dir / "notification_request.json",
        {
            "kind": "event_sla_partial",
            "title": "Event SLA completed",
            "summary": "status=partial_success",
            "severity": "warning",
            "facts": {"event_id": "jin10_report_223556_hash", "status": "partial_success"},
            "source_refs": [],
            "dry_run": False,
            "trade_date": "2026-07-08",
            "sections": [],
        },
    )


def test_automation_orchestrator_writes_plans_from_existing_agent_outputs(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=False,
        send_notifications=False,
    )

    artifacts = result["artifacts"]
    assert (storage_root / artifacts["orchestration_plan"]).is_file()
    assert (storage_root / artifacts["notification_plan"]).is_file()
    assert (storage_root / artifacts["automation_summary"]).is_file()
    assert (storage_root / artifacts["workflow_runs"]).is_file()

    plan = json.loads((storage_root / artifacts["orchestration_plan"]).read_text(encoding="utf-8"))
    assert plan["trigger"]["type"] == "hourly"
    assert [step["agent_name"] for step in plan["steps"]] == ["data_control_agent", "data_quality_monitor", "feishu_notification_agent"]
    assert plan["inputs"]["collection_plan"].endswith("collection_plan_10.json")
    assert plan["inputs"]["dispatch_plan"].endswith("dispatch_plan_10.json")
    assert plan["inputs"]["downstream_readiness"].endswith("downstream_readiness.json")

    notification_plan = json.loads((storage_root / artifacts["notification_plan"]).read_text(encoding="utf-8"))
    assert len(notification_plan["requests"]) == 2
    assert {item["kind"] for item in notification_plan["requests"]} == {"hourly_report", "incident"}
    assert notification_plan["requests"][1]["facts"]["blocked_outputs"] == ["full analysis", "knowledge distillation"]

    summary = json.loads((storage_root / artifacts["automation_summary"]).read_text(encoding="utf-8"))
    assert summary["status"] == "blocked"
    assert summary["send_notifications"] is False
    assert summary["notification_dispatch_status"] == "skipped"
    workflow_runs = json.loads((storage_root / artifacts["workflow_runs"]).read_text(encoding="utf-8"))
    assert workflow_runs["workflow_runs"][0]["trigger"] == "hourly"
    assert workflow_runs["workflow_runs"][0]["manual_review_required"] is True
    assert workflow_runs["workflow_runs"][0]["retry_policy"]["max_attempts"] == 3


def test_same_day_runs_write_isolated_artifacts_and_update_latest_pointer(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)

    first = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        run_id="hourly-run-1",
        record_task_run=False,
        send_notifications=False,
    )
    second = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="incident",
        hour="10",
        run_id="incident-run-2",
        record_task_run=False,
        send_notifications=False,
    )

    assert first["run_id"] == "hourly-run-1"
    assert second["run_id"] == "incident-run-2"
    assert first["artifacts"]["automation_summary"] == (
        "orchestration/2026-07-08/hourly-run-1/automation_summary.json"
    )
    assert second["artifacts"]["automation_summary"] == (
        "orchestration/2026-07-08/incident-run-2/automation_summary.json"
    )
    assert (storage_root / first["artifacts"]["automation_summary"]).is_file()
    assert (storage_root / second["artifacts"]["automation_summary"]).is_file()

    latest_path = storage_root / "orchestration" / "2026-07-08" / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["run_id"] == "incident-run-2"
    assert latest["trigger"] == "incident"
    assert latest["artifacts"]["automation_summary"] == second["artifacts"]["automation_summary"]


def test_automation_orchestrator_pre_analysis_trigger_builds_readiness_notification(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="pre_analysis",
        hour="10",
        record_task_run=False,
        send_notifications=False,
    )

    plan = json.loads((storage_root / result["artifacts"]["orchestration_plan"]).read_text(encoding="utf-8"))
    assert [step["agent_name"] for step in plan["steps"]] == ["data_quality_monitor", "feishu_notification_agent"]
    notification_plan = json.loads((storage_root / result["artifacts"]["notification_plan"]).read_text(encoding="utf-8"))
    assert [item["kind"] for item in notification_plan["requests"]] == ["pre_analysis_readiness", "incident"]
    assert notification_plan["requests"][0]["facts"]["blocked_outputs"] == ["full analysis", "knowledge distillation"]


def test_automation_orchestrator_pre_analysis_trigger_writes_gate_from_downstream_readiness(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="pre_analysis",
        hour="10",
        record_task_run=False,
        send_notifications=False,
    )

    artifacts = result["artifacts"]
    assert artifacts["pre_analysis_gate"] == (
        f"orchestration/2026-07-08/{result['run_id']}/pre_analysis_gate.json"
    )
    gate = json.loads((storage_root / artifacts["pre_analysis_gate"]).read_text(encoding="utf-8"))
    assert gate["decision"] == "block"
    assert gate["status"] == "blocked"
    assert gate["can_run_full_analysis"] is False
    assert gate["can_run_research_distillation"] is False
    assert gate["allowed_outputs"] == ["market snapshot"]
    assert gate["blocked_outputs"] == ["full analysis", "knowledge distillation"]
    assert gate["source_ref"] == "monitoring/2026-07-08/downstream_readiness.json"
    assert gate["issues"] == [{"source_key": "jin10_mcp_market", "reason_code": "freshness_stale"}]

    summary = json.loads((storage_root / artifacts["automation_summary"]).read_text(encoding="utf-8"))
    assert summary["pre_analysis_gate"]["decision"] == "block"
    workflow_runs = json.loads((storage_root / artifacts["workflow_runs"]).read_text(encoding="utf-8"))
    workflow_run = workflow_runs["workflow_runs"][0]
    assert workflow_run["pre_analysis_gate"]["decision"] == "block"
    assert workflow_run["output_refs"] == [
        {"artifact_type": "pre_analysis_gate", "path": artifacts["pre_analysis_gate"]}
    ]


def test_pre_analysis_gate_prefers_capability_states_over_legacy_booleans(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    _write_json(
        storage_root / "monitoring" / "2026-07-08" / "downstream_readiness.json",
        {
            "trade_date": "2026-07-08",
            "readiness": "partial",
            "capabilities": {
                "daily_market_snapshot": "allowed",
                "full_daily_analysis": "degraded",
                "research_report_interpretation": "blocked",
                "knowledge_distillation": "blocked",
                "technical_trigger_confirmation": "allowed",
                "options_structure_analysis": "allowed",
            },
            "can_run_full_analysis": False,
            "can_run_research_distillation": False,
            "allowed_outputs": ["market snapshot", "limited daily analysis"],
            "blocked_outputs": ["knowledge distillation"],
            "blocking_issues": [{"source_key": "jin10_svip_reports"}],
        },
    )

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="pre_analysis",
        hour="10",
        record_task_run=False,
        send_notifications=False,
    )

    gate = json.loads((storage_root / result["artifacts"]["pre_analysis_gate"]).read_text(encoding="utf-8"))
    assert gate["decision"] == "limited"
    assert gate["can_run_full_analysis"] is True
    assert gate["can_run_research_distillation"] is False
    assert gate["capabilities"]["full_daily_analysis"] == "degraded"


def test_pre_analysis_gate_ignores_unrelated_blocked_capability(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    _write_json(
        storage_root / "monitoring" / "2026-07-08" / "downstream_readiness.json",
        {
            "trade_date": "2026-07-08",
            "readiness": "partial",
            "capabilities": {
                "daily_market_snapshot": "allowed",
                "full_daily_analysis": "allowed",
                "research_report_interpretation": "allowed",
                "knowledge_distillation": "allowed",
                "technical_trigger_confirmation": "allowed",
                "options_structure_analysis": "blocked",
            },
            "can_run_full_analysis": True,
            "can_run_research_distillation": True,
            "allowed_outputs": ["market snapshot", "full daily analysis", "knowledge distillation"],
            "blocked_outputs": [],
            "blocking_issues": [{"source_key": "cme_options"}],
        },
    )

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="pre_analysis",
        hour="10",
        record_task_run=False,
        send_notifications=False,
    )

    gate = json.loads((storage_root / result["artifacts"]["pre_analysis_gate"]).read_text(encoding="utf-8"))
    assert gate["decision"] == "allow"


def test_automation_orchestrator_event_sla_trigger_includes_sla_notification(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="event_sla",
        hour="10",
        record_task_run=False,
        send_notifications=False,
    )

    notification_plan = json.loads((storage_root / result["artifacts"]["notification_plan"]).read_text(encoding="utf-8"))
    assert any(item["kind"] == "event_sla_partial" for item in notification_plan["requests"])
    plan = json.loads((storage_root / result["artifacts"]["orchestration_plan"]).read_text(encoding="utf-8"))
    assert any(step["agent_name"] == "event_sla_pipeline" for step in plan["steps"])


def test_automation_orchestrator_can_call_notification_agent_with_plan(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    sent: list[dict] = []

    class Sender:
        def send(self, request):
            sent.append({"kind": request.kind, "title": request.title, "dry_run": request.dry_run})
            return type("Result", (), {"to_dict": lambda self: {"ok": True, "status": "dry_run", "kind": request.kind}})()

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=False,
        send_notifications=True,
        notification_agent=Sender(),
    )

    assert [item["kind"] for item in sent] == ["hourly_report", "incident"]
    assert result["notification_results"][0]["status"] == "dry_run"


def test_automation_orchestrator_skips_notification_inside_cooldown(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    _write_json(
        storage_root / "orchestration" / "2026-07-08" / "notification_delivery_log.json",
        {
            "deliveries": [
                {
                    "dedupe_key": "hourly_report:2026-07-08:10",
                    "sent_at": "2026-07-08T10:10:00+00:00",
                    "status": "sent",
                }
            ]
        },
    )
    sent: list[dict] = []

    class Sender:
        def send(self, request):
            sent.append({"kind": request.kind})
            return type("Result", (), {"to_dict": lambda self: {"ok": True, "status": "sent", "kind": request.kind}})()

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=False,
        send_notifications=True,
        notification_agent=Sender(),
    )

    notification_plan = json.loads((storage_root / result["artifacts"]["notification_plan"]).read_text(encoding="utf-8"))
    hourly = next(item for item in notification_plan["requests"] if item["kind"] == "hourly_report")
    assert hourly["dedupe_key"] == "hourly_report:2026-07-08:10"
    assert hourly["eligible_to_send"] is False
    assert hourly["skipped_reason"] == "cooldown_active"
    assert [item["kind"] for item in sent] == ["incident"]


def test_automation_orchestrator_retries_failed_notification(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    attempts: list[str] = []

    class Sender:
        def send(self, request):
            attempts.append(request.kind)
            if len(attempts) == 1:
                return type("Result", (), {"to_dict": lambda self: {"ok": False, "status": "failed", "kind": request.kind, "error": "temporary"}})()
            return type("Result", (), {"to_dict": lambda self: {"ok": True, "status": "sent", "kind": request.kind}})()

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=False,
        send_notifications=True,
        notification_agent=Sender(),
    )

    assert result["notification_results"][0]["attempts"] == 2
    assert result["notification_results"][0]["status"] == "sent"


def test_automation_orchestrator_records_retry_queue_for_failed_notification(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)

    class Sender:
        def send(self, request):
            return type("Result", (), {"to_dict": lambda self: {"ok": False, "status": "failed", "kind": request.kind, "error": "temporary"}})()

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=False,
        send_notifications=True,
        notification_agent=Sender(),
    )

    assert result["notification_results"][0]["status"] == "failed"
    assert result["notification_dispatch_status"] == "partial_success"
    assert result["notification_results"][0]["next_retry_at"] == "2026-07-08T10:34:00+00:00"
    summary = json.loads((storage_root / result["artifacts"]["automation_summary"]).read_text(encoding="utf-8"))
    retry_item = summary["retry_queue"][0]
    assert retry_item["kind"] == "hourly_report"
    assert retry_item["dedupe_key"] == "hourly_report:2026-07-08:10"
    assert retry_item["attempt_count"] == 3
    assert retry_item["attempts"] == 3
    assert retry_item["next_retry_at"] == "2026-07-08T10:34:00+00:00"
    assert retry_item["last_error"] == "temporary"
    assert retry_item["request"]["title"] == "Data control hourly report"
    assert retry_item["request"]["facts"] == {"status": "blocked"}
    outbox_path = storage_root / "orchestration" / "outbox" / f"{retry_item['notification_id']}.json"
    outbox = json.loads(outbox_path.read_text(encoding="utf-8"))
    assert outbox["status"] == "pending_retry"
    assert outbox["request"] == retry_item["request"]
    workflow_runs = json.loads((storage_root / result["artifacts"]["workflow_runs"]).read_text(encoding="utf-8"))
    workflow_run = workflow_runs["workflow_runs"][0]
    assert workflow_run["retry_policy"]["backoff"] == "exponential"
    assert workflow_run["retry_queue"] == summary["retry_queue"]
    assert result["artifacts"]["retry_queue"] == (
        f"orchestration/2026-07-08/{result['run_id']}/retry_queue.json"
    )
    retry_queue = json.loads((storage_root / result["artifacts"]["retry_queue"]).read_text(encoding="utf-8"))
    assert retry_queue["trade_date"] == "2026-07-08"
    assert retry_queue["items"] == summary["retry_queue"]
    assert retry_queue["count"] == 2


def test_automation_orchestrator_persists_delivery_log_for_cooldown(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    sent: list[str] = []

    class Sender:
        def send(self, request):
            sent.append(request.kind)
            return type("Result", (), {"to_dict": lambda self: {"ok": True, "status": "sent", "kind": request.kind}})()

    first = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=False,
        send_notifications=True,
        notification_agent=Sender(),
    )

    delivery_log_path = storage_root / "orchestration" / "2026-07-08" / "notification_delivery_log.json"
    assert delivery_log_path.is_file()
    delivery_log = json.loads(delivery_log_path.read_text(encoding="utf-8"))
    assert [item["kind"] for item in delivery_log["deliveries"]] == ["hourly_report", "incident"]
    assert delivery_log["deliveries"][0]["dedupe_key"] == "hourly_report:2026-07-08:10"
    assert delivery_log["deliveries"][0]["attempts"] == 1
    assert first["notification_results"][0]["status"] == "sent"

    run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=False,
        send_notifications=True,
        notification_agent=Sender(),
    )

    assert sent == ["hourly_report", "incident"]


def test_notification_delivery_log_append_is_atomic_under_concurrency(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    barrier = threading.Barrier(2)
    original_read_json = automation_orchestrator._read_json

    def synchronized_read(path):
        payload = original_read_json(path)
        barrier.wait(timeout=2)
        return payload

    monkeypatch.setattr(automation_orchestrator, "_read_json", synchronized_read)

    def append(kind: str) -> None:
        automation_orchestrator._append_delivery_log(
            storage_root=storage_root,
            trade_date="2026-07-08",
            observed_at=OBSERVED_AT.isoformat(),
            results=[{"kind": kind, "status": "sent", "ok": True, "attempts": 1}],
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(append, ["hourly_report", "incident"]))

    delivery_log = json.loads(
        (storage_root / "orchestration" / "2026-07-08" / "notification_delivery_log.json").read_text(encoding="utf-8")
    )
    assert {item["kind"] for item in delivery_log["deliveries"]} == {"hourly_report", "incident"}


def test_automation_orchestrator_records_task_run_when_enabled(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    calls: list[dict] = []

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def step(self, step_name: str, **kwargs):
            calls.append({"step_name": step_name, **kwargs})

        def run_id(self):
            return "auto-run-1"

    def fake_record_task(**kwargs):
        calls.append({"record_task": kwargs})
        return Recorder()

    monkeypatch.setattr(automation_orchestrator, "record_task", fake_record_task)

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=True,
        send_notifications=False,
    )

    assert result["task_run_id"] == "auto-run-1"
    assert calls[0]["record_task"]["task_type"] == "automation_orchestrator"
    assert calls[1]["step_name"] == "load_agent_registry"
    dispatch = next(call for call in calls if call.get("step_name") == "dispatch_feishu_notification")
    assert dispatch["status"] == "skipped"
    assert dispatch["output_refs"][0]["notification_dispatch_status"] == "skipped"


def test_automation_orchestrator_records_retryable_delivery_failure_as_blocked_step(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    calls: list[dict] = []

    class Sender:
        def send(self, request):
            return type(
                "Result",
                (),
                {"to_dict": lambda self: {"ok": False, "status": "failed", "kind": request.kind, "error": "temporary"}},
            )()

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def step(self, step_name: str, **kwargs):
            calls.append({"step_name": step_name, **kwargs})

        def run_id(self):
            return "auto-run-failed-delivery"

    monkeypatch.setattr(automation_orchestrator, "record_task", lambda **_kwargs: Recorder())

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=True,
        send_notifications=True,
        notification_agent=Sender(),
    )

    dispatch = next(call for call in calls if call.get("step_name") == "dispatch_feishu_notification")
    assert result["notification_dispatch_status"] == "partial_success"
    assert dispatch["status"] == "blocked"
    assert dispatch["output_refs"][0]["notification_dispatch_status"] == "partial_success"


def test_automation_orchestrator_records_outbox_persistence_failure_as_failed_step(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_upstream_artifacts(storage_root)
    calls: list[dict] = []
    original_write_json_atomic = automation_orchestrator._write_json_atomic

    def fail_outbox_write(path, payload):
        if path.parent.name == "outbox":
            raise OSError("outbox unavailable")
        return original_write_json_atomic(path, payload)

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def step(self, step_name: str, **kwargs):
            calls.append({"step_name": step_name, **kwargs})

        def run_id(self):
            return "auto-run-outbox-failure"

    monkeypatch.setattr(automation_orchestrator, "_write_json_atomic", fail_outbox_write)
    monkeypatch.setattr(automation_orchestrator, "record_task", lambda **_kwargs: Recorder())

    result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        trigger="hourly",
        hour="10",
        record_task_run=True,
        send_notifications=True,
    )

    dispatch = next(call for call in calls if call.get("step_name") == "dispatch_feishu_notification")
    assert result["status"] == "failed"
    assert result["notification_dispatch_status"] == "failed"
    assert dispatch["status"] == "failed"
