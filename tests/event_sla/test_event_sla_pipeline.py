from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apps.event_sla import sla_orchestrator
from apps.event_sla.sla_orchestrator import run_event_sla_pipeline


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

    trace = json.loads((storage_root / artifacts["sla_trace"]).read_text(encoding="utf-8"))
    assert trace["task_type"] == "event_sla_analysis"
    assert trace["sla_minutes"] == 30
    assert trace["status"] == "success"
    assert [step["name"] for step in trace["steps"]][-1] == "record_sla_result"

    strategy = json.loads((storage_root / artifacts["trading_strategy_json"]).read_text(encoding="utf-8"))
    assert strategy["evidence_level"] == "full"
    assert strategy["strategy_mode"] == "wait_breakout"
    assert strategy["entry_conditions"]
    assert strategy["invalidation_conditions"]

    notification = json.loads((storage_root / artifacts["notification_request"]).read_text(encoding="utf-8"))
    assert notification["kind"] == "event_sla_completed"
    assert notification["facts"]["event_id"] == event["event_id"]
    assert notification["facts"]["status"] == "success"


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
    assert "actionable strategy is blocked" in strategy["risk_notes"][0]
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
    trace = json.loads((storage_root / event["artifacts"]["sla_trace"]).read_text(encoding="utf-8"))
    assert next(step for step in trace["steps"] if step["name"] == "parse_content")["status"] == "blocked"


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
