from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.event_sla import sla_orchestrator
from apps.event_sla.sla_orchestrator import run_event_sla_pipeline
from apps.runtime import task_recorder as task_recorder_module
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import ensure_task_tables


OBSERVED_AT = datetime(2026, 7, 8, 10, 20, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_jin10_event(storage_root: Path, *, content_scope: str = "full", body_complete: bool = True) -> None:
    _write_json(
        storage_root / "outputs" / "jin10" / "2026-07-08" / "223556" / "agent_analysis_report.json",
        {
            "article_id": "223556",
            "title": "非农仅增5.7万，美联储为何不能轻易转鸽？｜大师复盘",
            "published_at": "2026-07-08T09:55:00+00:00",
            "content_access": {
                "report_type": "research",
                "series": "master_review",
                "content_scope": content_scope,
                "body_complete": body_complete,
                "vip_locked": content_scope != "full",
            },
            "one_line_conclusion": "就业放缓但通胀约束仍在，黄金短线进入事件风险观察。",
            "key_variables": [{"name": "非农就业", "meaning": "影响美联储路径"}],
            "key_levels": [{"level": 4300, "type": "resistance", "meaning": "站稳后修复升级"}],
        },
    )
    _write_text(storage_root / "outputs" / "jin10" / "2026-07-08" / "223556" / "agent_analysis_report.md", "# Jin10 analysis\n")
    _write_json(storage_root / "raw" / "jin10" / "2026-07-08" / "index.json", {"items": ["223556"]})
    _write_json(storage_root / "parsed" / "jin10" / "2026-07-08" / "index.json", {"items": ["223556"]})
    _write_json(
        storage_root / "monitoring" / "2026-07-08" / "downstream_readiness.json",
        {
            "readiness": "ready",
            "can_run_full_analysis": True,
            "can_run_research_distillation": True,
            "allowed_outputs": ["full daily analysis", "knowledge distillation"],
            "blocked_outputs": [],
            "blocking_issues": [],
        },
    )


def _seed_cme_event(storage_root: Path) -> None:
    pdf_path = storage_root / "raw" / "cme" / "daily_bulletin" / "2026-07-08" / "Section64_Metals_Option_Products_2026-07-08.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF cme gold options bulletin")
    _write_json(
        storage_root / "parsed" / "cme" / "2026-07-08" / "run-1" / "cme_parse_result.json",
        {
            "product": "OG COMEX Gold options",
            "excluded_products": ["OMG Micro Gold", "OG1 weekly"],
            "key_levels": [4000, 4100, 4200],
            "summary": "Main OG open interest remains concentrated near 4000 put and 4200 call.",
        },
    )


def _seed_cme_unparsed_event(storage_root: Path) -> None:
    pdf_path = storage_root / "raw" / "cme" / "daily_bulletin" / "2026-07-08" / "Section64_Metals_Option_Products_2026-07-08.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF cme gold options bulletin")


def test_event_sla_pipeline_writes_jin10_analysis_strategy_trace_and_notification(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root)

    result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("jin10",),
        record_task_run=False,
    )

    assert result["created_count"] == 1
    event = result["events"][0]
    artifacts = event["artifacts"]
    assert event["source_key"] == "jin10_research_master_review"
    assert event["status"] == "success"
    assert (storage_root / artifacts["event_snapshot"]).is_file()
    assert (storage_root / artifacts["analysis_report"]).is_file()
    assert (storage_root / artifacts["trading_strategy"]).is_file()
    assert (storage_root / artifacts["sla_trace"]).is_file()
    assert (storage_root / artifacts["notification_request"]).is_file()
    assert (storage_root / artifacts["live_strategy_recompute_request"]).is_file()

    snapshot = json.loads((storage_root / artifacts["event_snapshot"]).read_text(encoding="utf-8"))
    assert snapshot["observation_hash"] == event["observation_hash"]
    request = json.loads(
        (storage_root / artifacts["live_strategy_recompute_request"]).read_text(encoding="utf-8")
    )
    assert request["schema_name"] == "live_strategy_recompute_request"
    assert request["schema_version"] == "live_strategy_recompute_request.v1"
    assert request["requested_action"] == "recompute_live_strategy"
    assert request["event_id"] == event["event_id"]
    assert request["observation_hash"] == event["observation_hash"]
    assert request["dispatch_status"] == "pending"
    assert request["reason_codes"] == []
    assert request["source_refs"] == []

    trace = json.loads((storage_root / artifacts["sla_trace"]).read_text(encoding="utf-8"))
    assert trace["task_type"] == "event_sla_analysis"
    assert event["event_id"] == "jin10_research_master_review_223556"
    assert trace["sla_minutes"] == 30
    assert trace["status"] == "success"
    assert trace["published_at"] == "2026-07-08T09:55:00+00:00"
    assert trace["first_seen_at"] == OBSERVED_AT.isoformat()
    assert trace["detected_at"] == OBSERVED_AT.isoformat()
    assert trace["analysis_started_at"] == OBSERVED_AT.isoformat()
    assert trace["completed_at"] >= trace["analysis_started_at"]
    assert trace["detection_lag_minutes"] == 25.0
    assert trace["processing_duration_minutes"] >= 0.0
    assert trace["end_to_end_sla_minutes"] >= 25.0
    assert trace["elapsed_minutes"] == trace["end_to_end_sla_minutes"]
    assert [step["name"] for step in trace["steps"]][-1] == "record_sla_result"
    assert next(step for step in trace["steps"] if step["name"] == "detect_update") == {
        "name": "detect_update",
        "status": "success",
        "execution_mode": "executed",
    }
    assert next(step for step in trace["steps"] if step["name"] == "collect_raw") == {
        "name": "collect_raw",
        "status": "skipped",
        "execution_mode": "reused_existing_artifact",
    }
    assert next(step for step in trace["steps"] if step["name"] == "parse_content") == {
        "name": "parse_content",
        "status": "skipped",
        "execution_mode": "reused_existing_artifact",
    }
    recompute_step = next(
        step for step in trace["steps"] if step["name"] == "write_live_strategy_recompute_request"
    )
    assert recompute_step["output_refs"][0]["path"] == artifacts["live_strategy_recompute_request"]

    strategy = json.loads((storage_root / artifacts["trading_strategy_json"]).read_text(encoding="utf-8"))
    assert strategy["authority"] == "none"
    assert strategy["output_mode"] == "observation_only"
    assert strategy["evidence_level"] == "full"
    assert strategy["strategy_mode"] == "wait_breakout"
    assert strategy["entry_conditions"]
    assert strategy["invalidation_conditions"]

    notification = json.loads((storage_root / artifacts["notification_request"]).read_text(encoding="utf-8"))
    assert notification["kind"] == "event_sla_completed"
    assert notification["facts"]["event_id"] == event["event_id"]
    assert notification["facts"]["status"] == "success"


def test_event_sla_pipeline_does_not_claim_missing_jin10_indexes_were_reused(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root)
    (storage_root / "raw" / "jin10" / "2026-07-08" / "index.json").unlink()
    (storage_root / "parsed" / "jin10" / "2026-07-08" / "index.json").unlink()

    result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("jin10",),
        record_task_run=False,
    )

    event = result["events"][0]
    snapshot = json.loads(
        (storage_root / event["artifacts"]["event_snapshot"]).read_text(encoding="utf-8")
    )
    trace = json.loads((storage_root / event["artifacts"]["sla_trace"]).read_text(encoding="utf-8"))
    collect_raw = next(step for step in trace["steps"] if step["name"] == "collect_raw")
    parse_content = next(step for step in trace["steps"] if step["name"] == "parse_content")

    assert snapshot["raw_refs"] == []
    assert snapshot["parsed_refs"] == []
    request = json.loads(
        (storage_root / event["artifacts"]["live_strategy_recompute_request"]).read_text(encoding="utf-8")
    )
    assert request["raw_refs"] == []
    assert request["parsed_refs"] == []
    assert request["source_refs"] == []
    assert request["dispatch_status"] == "blocked"
    assert request["reason_codes"] == ["missing_parsed_refs"]
    assert collect_raw == {
        "name": "collect_raw",
        "status": "skipped",
        "execution_mode": "not_required",
    }
    assert parse_content == {
        "name": "parse_content",
        "status": "blocked",
        "execution_mode": "blocked_by_missing_input",
    }


def test_event_sla_pipeline_degrades_preview_jin10_to_observation_only(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root, content_scope="preview", body_complete=False)

    result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("jin10",),
        record_task_run=False,
    )

    event = result["events"][0]
    strategy = json.loads((storage_root / event["artifacts"]["trading_strategy_json"]).read_text(encoding="utf-8"))
    notification = json.loads((storage_root / event["artifacts"]["notification_request"]).read_text(encoding="utf-8"))
    assert event["status"] == "partial_success"
    assert notification["kind"] == "event_sla_partial"
    assert strategy["evidence_level"] == "preview"
    assert strategy["strategy_mode"] == "observe"
    assert not strategy["entry_conditions"]
    assert "legacy observation output is blocked" in strategy["risk_notes"][0]
    request = json.loads(
        (storage_root / event["artifacts"]["live_strategy_recompute_request"]).read_text(encoding="utf-8")
    )
    assert request["dispatch_status"] == "blocked"
    assert request["reason_codes"] == ["evidence_preview", "event_status_partial_success"]
    trace = json.loads((storage_root / event["artifacts"]["sla_trace"]).read_text(encoding="utf-8"))
    assert next(step for step in trace["steps"] if step["name"] == "build_trading_strategy")["status"] == "blocked"


def test_event_sla_pipeline_supports_cme_bulletin_event(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_cme_event(storage_root)

    result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("cme",),
        record_task_run=False,
    )

    assert result["created_count"] == 1
    event = result["events"][0]
    strategy = json.loads((storage_root / event["artifacts"]["trading_strategy_json"]).read_text(encoding="utf-8"))
    assert event["source_key"] == "cme_gold_options_bulletin"
    assert event["status"] == "success"
    assert any(level["type"] == "option_wall" for level in strategy["key_levels"])


def test_event_sla_pipeline_marks_unparsed_cme_notification_as_blocked(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_cme_unparsed_event(storage_root)

    result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("cme",),
        record_task_run=False,
    )

    event = result["events"][0]
    notification = json.loads((storage_root / event["artifacts"]["notification_request"]).read_text(encoding="utf-8"))
    assert event["status"] == "blocked"
    assert notification["kind"] == "event_sla_blocked"
    assert notification["severity"] == "critical"
    request = json.loads(
        (storage_root / event["artifacts"]["live_strategy_recompute_request"]).read_text(encoding="utf-8")
    )
    assert request["dispatch_status"] == "blocked"
    assert request["reason_codes"] == [
        "evidence_partial",
        "missing_parsed_refs",
        "event_status_blocked",
    ]
    trace = json.loads((storage_root / event["artifacts"]["sla_trace"]).read_text(encoding="utf-8"))
    assert next(step for step in trace["steps"] if step["name"] == "parse_content")["status"] == "blocked"


def test_event_sla_pipeline_blocks_recompute_request_when_quality_gate_is_blocked(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_cme_event(storage_root)
    _write_json(
        storage_root / "monitoring" / "2026-07-08" / "downstream_readiness.json",
        {"readiness": "blocked", "can_run_full_analysis": False},
    )

    result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("cme",),
        record_task_run=False,
    )

    event = result["events"][0]
    request = json.loads(
        (storage_root / event["artifacts"]["live_strategy_recompute_request"]).read_text(encoding="utf-8")
    )
    assert event["status"] == "blocked"
    assert request["quality_status"] == "blocked"
    assert request["dispatch_status"] == "blocked"
    assert request["reason_codes"] == ["quality_gate_blocked", "event_status_blocked"]


def test_event_sla_pipeline_records_task_run_when_enabled(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root)
    calls: list[dict] = []

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def step(self, step_name: str, **kwargs):
            calls.append({"step_name": step_name, **kwargs})

        def run_id(self):
            return "sla-run-1"

    def fake_record_task(**kwargs):
        calls.append({"record_task": kwargs})
        return Recorder()

    monkeypatch.setattr(sla_orchestrator, "record_task", fake_record_task)

    result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("jin10",),
        record_task_run=True,
    )

    assert result["events"][0]["task_run_id"] == "sla-run-1"
    assert calls[0]["record_task"]["task_type"] == "event_sla_analysis"
    assert calls[1]["step_name"] == "detect_update"
    assert calls[1]["source_refs"][0]["source_ref"].startswith("event:")
    collect_raw = next(call for call in calls if call.get("step_name") == "collect_raw")
    parse_content = next(call for call in calls if call.get("step_name") == "parse_content")
    recompute_request = next(
        call for call in calls if call.get("step_name") == "write_live_strategy_recompute_request"
    )
    assert collect_raw["status"] == "skipped"
    assert collect_raw["output_refs"][0]["execution_mode"] == "reused_existing_artifact"
    assert parse_content["status"] == "skipped"
    assert parse_content["output_refs"][0]["execution_mode"] == "reused_existing_artifact"
    assert recompute_request["output_refs"][0]["path"] == result["events"][0]["artifacts"]["live_strategy_recompute_request"]


def test_event_sla_pipeline_reuses_identical_event_without_rewriting_outputs(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root)

    first = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("jin10",),
        record_task_run=False,
    )
    first_event = first["events"][0]
    trace_path = storage_root / first_event["artifacts"]["sla_trace"]
    request_path = storage_root / first_event["artifacts"]["live_strategy_recompute_request"]
    original_trace = trace_path.read_text(encoding="utf-8")
    original_request = request_path.read_text(encoding="utf-8")

    second = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 25, tzinfo=timezone.utc),
        source_types=("jin10",),
        record_task_run=False,
    )

    assert first["created_count"] == 1
    assert first["reused_count"] == 0
    assert second["created_count"] == 0
    assert second["reused_count"] == 1
    assert second["events"][0]["execution_mode"] == "reused"
    assert second["events"][0]["task_run_id"] is None
    assert trace_path.read_text(encoding="utf-8") == original_trace
    assert request_path.read_text(encoding="utf-8") == original_request
    assert json.loads(request_path.read_text(encoding="utf-8"))["request_id"] == json.loads(
        original_request
    )["request_id"]
    ledger = json.loads(
        (storage_root / "event_sla" / "2026-07-08" / "event_execution_ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["events"][first_event["event_id"]]["event_hash"] == first_event["event_hash"]


def test_event_sla_pipeline_migrates_legacy_hash_suffixed_ledger_key_on_reuse(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root)
    first = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("jin10",),
        record_task_run=False,
    )
    stable_event_id = first["events"][0]["event_id"]
    ledger_path = storage_root / "event_sla" / "2026-07-08" / "event_execution_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    legacy_event_id = f"{stable_event_id}_deadbeef00"
    ledger["events"][legacy_event_id] = ledger["events"].pop(stable_event_id)
    ledger["events"][legacy_event_id]["event_id"] = legacy_event_id
    _write_json(ledger_path, ledger)

    second = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 25, tzinfo=timezone.utc),
        source_types=("jin10",),
        record_task_run=False,
    )

    migrated = json.loads(ledger_path.read_text(encoding="utf-8"))["events"]
    assert second["reused_count"] == 1
    assert stable_event_id in migrated
    assert legacy_event_id not in migrated
    assert migrated[stable_event_id]["event_id"] == stable_event_id


def test_event_sla_pipeline_tracks_changed_report_as_new_observation_of_same_event(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root)
    first = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("jin10",),
        record_task_run=False,
    )
    report_path = storage_root / "outputs" / "jin10" / "2026-07-08" / "223556" / "agent_analysis_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["one_line_conclusion"] = "Updated conclusion after the source artifact changed."
    _write_json(report_path, payload)

    second = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 25, tzinfo=timezone.utc),
        source_types=("jin10",),
        record_task_run=False,
    )

    assert second["created_count"] == 1
    assert second["reused_count"] == 0
    assert second["events"][0]["event_id"] == first["events"][0]["event_id"]
    assert second["events"][0]["observation_hash"] != first["events"][0]["observation_hash"]
    assert second["events"][0]["artifacts"]["sla_trace"] != first["events"][0]["artifacts"]["sla_trace"]
    ledger = json.loads(
        (storage_root / "event_sla" / "2026-07-08" / "event_execution_ledger.json").read_text(encoding="utf-8")
    )
    entry = ledger["events"][first["events"][0]["event_id"]]
    assert entry["execution_count"] == 2
    assert entry["first_seen_at"] == OBSERVED_AT.isoformat()
    assert entry["history"][0]["observation_hash"] == first["events"][0]["observation_hash"]
    assert entry["history"][0]["artifacts"] == first["events"][0]["artifacts"]


def test_event_sla_pipeline_reexecutes_when_parsed_input_arrives(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    _seed_cme_unparsed_event(storage_root)
    first = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("cme",),
        record_task_run=False,
    )
    _write_json(
        storage_root / "parsed" / "cme" / "2026-07-08" / "run-1" / "cme_parse_result.json",
        {
            "product": "OG COMEX Gold options",
            "key_levels": [4000, 4100, 4200],
            "summary": "Parsed after the PDF observation was first recorded.",
        },
    )

    second = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 10, 25, tzinfo=timezone.utc),
        source_types=("cme",),
        record_task_run=False,
    )

    assert first["events"][0]["status"] == "blocked"
    assert second["created_count"] == 1
    assert second["reused_count"] == 0
    assert second["events"][0]["status"] == "success"
    ledger = json.loads(
        (storage_root / "event_sla" / "2026-07-08" / "event_execution_ledger.json").read_text(encoding="utf-8")
    )
    entry = ledger["events"][second["events"][0]["event_id"]]
    assert entry["execution_count"] == 2
    assert entry["history"][0]["status"] == "blocked"


def test_event_sla_pipeline_serializes_concurrent_duplicate_observations(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root)
    original_run_event = sla_orchestrator.EventSlaOrchestrator._run_event

    def slow_run_event(self, **kwargs):
        time.sleep(0.1)
        return original_run_event(self, **kwargs)

    monkeypatch.setattr(sla_orchestrator.EventSlaOrchestrator, "_run_event", slow_run_event)

    def run_once():
        return run_event_sla_pipeline(
            storage_root=storage_root,
            trade_date="2026-07-08",
            observed_at=OBSERVED_AT,
            source_types=("jin10",),
            record_task_run=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: run_once(), range(2)))

    assert sorted(result["created_count"] for result in results) == [0, 1]
    assert sorted(result["reused_count"] for result in results) == [0, 1]


def test_preview_and_reused_event_artifacts_are_registered_with_usage_metadata(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_jin10_event(storage_root, content_scope="preview", body_complete=False)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(task_recorder_module, "SessionLocal", factory)

    result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        source_types=("jin10",),
        record_task_run=True,
    )

    with factory() as session:
        artifacts = session.query(RunArtifact).all()

    artifact_paths = [artifact.file_path for artifact in artifacts]
    assert len(artifact_paths) == len(set(artifact_paths))
    strategy_json = next(
        artifact
        for artifact in artifacts
        if artifact.file_path == result["events"][0]["artifacts"]["trading_strategy_json"]
    )
    recompute_request = next(
        artifact
        for artifact in artifacts
        if artifact.file_path == result["events"][0]["artifacts"]["live_strategy_recompute_request"]
    )
    parsed = next(artifact for artifact in artifacts if artifact.artifact_metadata.get("execution_mode") == "reused_existing_artifact" and "parsed" in artifact.file_path)
    assert strategy_json.artifact_metadata["quality_status"] == "observation_only"
    assert strategy_json.artifact_metadata["usable_for"] == ["observation"]
    assert strategy_json.artifact_metadata["blocked_for"] == ["recompute_authority", "direct_execution"]
    assert recompute_request.artifact_metadata["quality_status"] == "request_only"
    assert recompute_request.artifact_metadata["usable_for"] == ["recompute_resolution"]
    assert recompute_request.artifact_metadata["blocked_for"] == ["direct_execution", "strategy_freeze"]
    assert parsed.artifact_metadata["quality_status"] == "reused"
    assert parsed.artifact_metadata["usable_for"] == ["source_evidence"]
