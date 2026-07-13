from __future__ import annotations

import json
from pathlib import Path

from apps.api.services.orchestration_service import (
    create_manual_review_action,
    get_orchestration_latest,
    get_orchestration_manual_review,
    get_orchestration_notification_plan,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _seed_orchestration(storage_root: Path) -> None:
    base = storage_root / "orchestration" / "2026-07-08"
    _write_json(
        base / "pre_analysis_gate.json",
        {
            "trade_date": "2026-07-08",
            "decision": "block",
            "status": "blocked",
            "source_ref": "monitoring/2026-07-08/downstream_readiness.json",
        },
    )
    _write_json(
        base / "automation_summary.json",
        {
            "trade_date": "2026-07-08",
            "trigger": "hourly",
            "status": "blocked",
            "notification_request_count": 2,
            "workflow_run_count": 1,
        },
    )
    _write_json(
        base / "retry_queue.json",
        {
            "trade_date": "2026-07-08",
            "count": 1,
            "items": [
                {
                    "kind": "incident",
                    "dedupe_key": "incident:2026-07-08:blocked",
                    "attempts": 3,
                    "next_retry_at": "2026-07-08T10:34:00+00:00",
                }
            ],
        },
    )
    _write_json(
        base / "notification_plan.json",
        {
            "trade_date": "2026-07-08",
            "trigger": "hourly",
            "requests": [
                {"kind": "hourly_report", "severity": "critical", "dedupe_key": "hourly_report:2026-07-08:04"},
                {"kind": "incident", "severity": "critical", "dedupe_key": "incident:2026-07-08:blocked"},
            ],
            "request_count": 2,
        },
    )
    _write_json(
        base / "workflow_runs.json",
        {
            "trade_date": "2026-07-08",
            "workflow_runs": [
                {
                    "workflow_id": "hourly:2026-07-08:04",
                    "trigger": "hourly",
                    "status": "blocked",
                    "manual_review_required": True,
                    "manual_review": [
                        {
                            "kind": "incident",
                            "dedupe_key": "incident:2026-07-08:blocked",
                            "reason": "downstream readiness blocked",
                            "facts": {"blocked_outputs": ["full analysis"]},
                        }
                    ],
                    "retry_policy": {"max_attempts": 3},
                }
            ],
        },
    )
    _write_json(
        base / "notification_delivery_log.json",
        {
            "trade_date": "2026-07-08",
            "deliveries": [
                {
                    "kind": "incident",
                    "dedupe_key": "incident:2026-07-08:blocked",
                    "status": "disabled",
                    "attempts": 1,
                }
            ],
        },
    )
    _write_json(
        base / "notification_retry_results.json",
        {
            "trade_date": "2026-07-08",
            "results": [
                {
                    "kind": "hourly_report",
                    "dedupe_key": "hourly_report:2026-07-08:04",
                    "status": "sent",
                    "attempted_at": "2026-07-08T10:05:00+00:00",
                }
            ],
        },
    )


def test_orchestration_latest_reads_summary_workflow_and_delivery_log(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_orchestration(storage_root)

    payload = get_orchestration_latest(storage_root=storage_root, date="2026-07-08")

    assert payload["trade_date"] == "2026-07-08"
    assert payload["summary"]["status"] == "blocked"
    assert payload["workflow_runs"][0]["workflow_id"] == "hourly:2026-07-08:04"
    assert payload["notification_plan"]["request_count"] == 2
    assert payload["delivery_log"]["deliveries"][0]["status"] == "disabled"
    assert payload["manual_review_count"] == 1
    assert payload["artifacts"]["pre_analysis_gate"] == "orchestration/2026-07-08/pre_analysis_gate.json"
    assert payload["artifacts"]["retry_queue"] == "orchestration/2026-07-08/retry_queue.json"
    assert (
        payload["artifacts"]["notification_retry_results"]
        == "orchestration/2026-07-08/notification_retry_results.json"
    )
    assert payload["pre_analysis_gate"]["decision"] == "block"
    assert payload["pre_analysis_gate"]["source_ref"] == "monitoring/2026-07-08/downstream_readiness.json"
    assert payload["retry_queue"]["items"][0]["dedupe_key"] == "incident:2026-07-08:blocked"
    assert payload["notification_retry_results"]["results"][0]["status"] == "sent"
    assert payload["notification_retry_results"]["results"][0]["dedupe_key"] == "hourly_report:2026-07-08:04"


def test_orchestration_manual_review_extracts_review_items(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_orchestration(storage_root)

    payload = get_orchestration_manual_review(storage_root=storage_root, date="2026-07-08")

    assert payload["count"] == 1
    assert payload["items"][0]["workflow_id"] == "hourly:2026-07-08:04"
    assert payload["items"][0]["dedupe_key"] == "incident:2026-07-08:blocked"
    assert payload["items"][0]["facts"]["blocked_outputs"] == ["full analysis"]
    assert payload["items"][0]["action_status"] == "open"


def test_orchestration_manual_review_action_is_recorded_and_merged(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_orchestration(storage_root)

    action = create_manual_review_action(
        storage_root=storage_root,
        date="2026-07-08",
        dedupe_key="incident:2026-07-08:blocked",
        action="acknowledged",
        actor="codex",
        note="checked blocked readiness",
    )

    assert action["status"] == "recorded"
    actions_path = storage_root / "orchestration" / "2026-07-08" / "manual_review_actions.json"
    assert actions_path.is_file()
    actions = json.loads(actions_path.read_text(encoding="utf-8"))
    assert actions["actions"][0]["action"] == "acknowledged"
    assert actions["actions"][0]["actor"] == "codex"

    payload = get_orchestration_manual_review(storage_root=storage_root, date="2026-07-08")
    assert payload["items"][0]["action_status"] == "acknowledged"
    assert payload["items"][0]["action_note"] == "checked blocked readiness"


def test_orchestration_notification_plan_missing_storage_returns_empty(tmp_path) -> None:
    payload = get_orchestration_notification_plan(storage_root=tmp_path / "storage", date="2026-07-08")

    assert payload["trade_date"] == "2026-07-08"
    assert payload["requests"] == []
    assert payload["request_count"] == 0


def test_orchestration_latest_follows_run_scoped_latest_pointer(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    date_root = storage_root / "orchestration" / "2026-07-08"
    run_root = date_root / "hourly-run-1"
    artifacts = {
        "run_id": "hourly-run-1",
        "automation_summary": "orchestration/2026-07-08/hourly-run-1/automation_summary.json",
        "notification_plan": "orchestration/2026-07-08/hourly-run-1/notification_plan.json",
        "workflow_runs": "orchestration/2026-07-08/hourly-run-1/workflow_runs.json",
        "retry_queue": "orchestration/2026-07-08/hourly-run-1/retry_queue.json",
        "pre_analysis_gate": "orchestration/2026-07-08/hourly-run-1/pre_analysis_gate.json",
    }
    _write_json(
        date_root / "latest.json",
        {
            "trade_date": "2026-07-08",
            "run_id": "hourly-run-1",
            "trigger": "hourly",
            "artifacts": artifacts,
        },
    )
    _write_json(run_root / "automation_summary.json", {"run_id": "hourly-run-1", "status": "partial"})
    _write_json(run_root / "notification_plan.json", {"trade_date": "2026-07-08", "request_count": 0, "requests": []})
    _write_json(run_root / "workflow_runs.json", {"workflow_runs": []})
    _write_json(run_root / "retry_queue.json", {"trade_date": "2026-07-08", "count": 0, "items": []})
    _write_json(run_root / "pre_analysis_gate.json", {"decision": "limited"})
    (storage_root / "orchestration" / "outbox").mkdir(parents=True)

    payload = get_orchestration_latest(storage_root=storage_root)

    assert payload["run_id"] == "hourly-run-1"
    assert payload["summary"]["run_id"] == "hourly-run-1"
    assert payload["pre_analysis_gate"]["decision"] == "limited"
    assert payload["artifacts"]["automation_summary"] == artifacts["automation_summary"]
