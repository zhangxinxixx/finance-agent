from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apps.monitoring import data_quality_agent
from apps.monitoring.data_quality_agent import run_data_quality_monitor


OBSERVED_AT = datetime(2026, 7, 8, 3, 0, tzinfo=timezone.utc)


def _health_snapshot() -> dict:
    items = []
    for source_key in (
        "jin10_mcp_market",
        "jin10_mcp_flash",
        "jin10_xnews_public",
        "jin10_svip_reports",
        "jin10_datacenter_reports",
    ):
        items.append(
            {
                "source_key": source_key,
                "data_status": "live",
                "freshness_status": "fresh",
                "freshness_reason": "within_sla",
                "health_state": "healthy",
                "readiness_state": "ready",
                "latest_health_at": "2026-07-08T03:00:00+00:00",
            }
        )
    return {
        "snapshot_date": "2026-07-08",
        "as_of": "2026-07-08T03:00:00+00:00",
        "overall_status": "LIVE",
        "counts": {"total": 5, "live": 5, "partial": 0, "unavailable": 0, "stale": 0},
        "items": items,
    }


def _write_text(path: Path, text: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _set_source_health(snapshot: dict, source_key: str, **updates) -> None:
    item = next(item for item in snapshot["items"] if item["source_key"] == source_key)
    item.update(updates)


def _seed_storage(storage_root: Path, *, content_scope: str = "full", body_complete: bool = True, vip_locked: bool = False) -> None:
    _write_text(storage_root / "outputs" / "jin10" / "quotes_cache.json")
    _write_text(storage_root / "outputs" / "jin10" / "flash_cache.json")
    _write_text(storage_root / "features" / "news" / "2026-07-08" / "run-1" / "jin10_article_briefs.json")
    _write_text(storage_root / "raw" / "jin10_datacenter" / "2026-07-08" / "dc_etf_gold.json")
    _write_text(storage_root / "raw" / "jin10" / "2026-07-08" / "index.json")
    _write_text(storage_root / "parsed" / "jin10" / "2026-07-08" / "index.json")
    _write_text(storage_root / "outputs" / "jin10" / "2026-07-08" / "analysis.json")
    agent_payload = {
        "article_id": "223556",
        "trade_date": "2026-07-08",
        "content_access": {
            "report_type": "research",
            "series": "master_review",
            "content_scope": content_scope,
            "body_complete": body_complete,
            "vip_locked": vip_locked,
        },
        "quality_audit": {"status": "accepted"},
    }
    _write_text(
        storage_root / "outputs" / "jin10" / "2026-07-08" / "223556" / "agent_analysis_report.json",
        json.dumps(agent_payload, ensure_ascii=False),
    )


def test_data_quality_monitor_writes_three_artifacts_for_full_content(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)
    monkeypatch.setattr(data_quality_agent, "get_data_source_health_latest", lambda date=None: _health_snapshot())

    result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=False,
    )

    artifacts = result["artifacts"]
    assert (storage_root / artifacts["source_health"]).is_file()
    assert (storage_root / artifacts["data_quality_report"]).is_file()
    assert (storage_root / artifacts["downstream_readiness"]).is_file()
    readiness = json.loads((storage_root / artifacts["downstream_readiness"]).read_text(encoding="utf-8"))
    assert readiness["can_run_full_analysis"] is True
    assert readiness["can_run_research_distillation"] is True
    assert "knowledge distillation" in readiness["allowed_outputs"]


def test_data_quality_monitor_blocks_distillation_for_preview_content(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root, content_scope="preview", body_complete=False, vip_locked=True)
    monkeypatch.setattr(data_quality_agent, "get_data_source_health_latest", lambda date=None: _health_snapshot())

    result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=False,
    )

    readiness = result["downstream_readiness"]
    quality = result["data_quality_report"]
    assert readiness["capabilities"]["full_daily_analysis"] == "allowed"
    assert readiness["capabilities"]["research_report_interpretation"] == "blocked"
    assert readiness["capabilities"]["knowledge_distillation"] == "blocked"
    assert readiness["can_run_research_distillation"] is False
    assert "knowledge distillation" in readiness["blocked_outputs"]
    assert any(issue["reason_code"] == "jin10_report_preview_or_incomplete" for issue in readiness["blocking_issues"])
    assert quality["summary"]["permission_problem_count"] == 1


def test_data_quality_monitor_marks_stale_market_as_full_analysis_blocker(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)
    snapshot = _health_snapshot()
    for item in snapshot["items"]:
        if item["source_key"] == "jin10_mcp_market":
            item["freshness_status"] = "stale"
            item["freshness_reason"] = "ttl_exceeded"
            item["latest_health_at"] = "2026-07-08T02:00:00+00:00"
    monkeypatch.setattr(data_quality_agent, "get_data_source_health_latest", lambda date=None: snapshot)

    result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=False,
    )

    readiness = result["downstream_readiness"]
    assert readiness["capabilities"]["daily_market_snapshot"] == "blocked"
    assert readiness["capabilities"]["full_daily_analysis"] == "blocked"
    assert readiness["capabilities"]["technical_trigger_confirmation"] == "blocked"
    assert readiness["capabilities"]["options_structure_analysis"] == "allowed"
    assert readiness["can_run_full_analysis"] is False
    assert "full analysis" in readiness["blocked_outputs"]
    assert any(issue["source_key"] == "jin10_mcp_market" and issue["reason_code"] == "freshness_stale" for issue in readiness["blocking_issues"])


def test_non_core_flash_staleness_degrades_without_blocking_daily_analysis(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)
    snapshot = _health_snapshot()
    _set_source_health(
        snapshot,
        "jin10_mcp_flash",
        freshness_status="stale",
        freshness_reason="ttl_exceeded",
        latest_health_at="2026-07-08T02:00:00+00:00",
    )
    monkeypatch.setattr(data_quality_agent, "get_data_source_health_latest", lambda date=None: snapshot)

    result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=False,
    )
    readiness = result["downstream_readiness"]

    assert readiness["capabilities"]["full_daily_analysis"] == "degraded"
    assert readiness["can_run_full_analysis"] is True
    assert readiness["readiness"] == "partial"
    assert not any(issue["source_key"] == "jin10_mcp_flash" for issue in readiness["blocking_issues"])
    assert any(issue["source_key"] == "jin10_mcp_flash" for issue in readiness["degraded_issues"])
    assert not any(issue["source_key"] == "jin10_mcp_flash" for issue in result["data_quality_report"]["blocking_issues"])


def test_low_frequency_datacenter_staleness_is_degraded_not_blocked(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)
    snapshot = _health_snapshot()
    _set_source_health(
        snapshot,
        "jin10_datacenter_reports",
        freshness_status="stale",
        freshness_reason="stale_allowed",
        latest_health_at="2026-07-06T03:00:00+00:00",
    )
    monkeypatch.setattr(data_quality_agent, "get_data_source_health_latest", lambda date=None: snapshot)

    readiness = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=False,
    )["downstream_readiness"]

    assert readiness["capabilities"]["full_daily_analysis"] == "degraded"
    assert readiness["can_run_full_analysis"] is True
    assert readiness["capabilities"]["knowledge_distillation"] == "allowed"


def test_waiting_research_source_degrades_instead_of_blocking(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)
    snapshot = _health_snapshot()
    _set_source_health(
        snapshot,
        "jin10_svip_reports",
        data_status="waiting",
        freshness_status="waiting",
        freshness_reason="not_published_yet",
        latest_health_at=None,
    )
    monkeypatch.setattr(data_quality_agent, "get_data_source_health_latest", lambda date=None: snapshot)

    result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=False,
    )
    readiness = result["downstream_readiness"]
    freshness_check = next(
        check
        for check in result["data_quality_report"]["checks"]
        if check["source_key"] == "jin10_svip_reports" and check["check_type"] == "freshness"
    )

    assert freshness_check["status"] == "waiting"
    assert freshness_check["blocked_capabilities"] == []
    assert set(freshness_check["degraded_capabilities"]) == {
        "full_daily_analysis",
        "research_report_interpretation",
        "knowledge_distillation",
    }
    assert result["source_health"]["overall_status"] == "partial"
    assert readiness["capabilities"]["research_report_interpretation"] == "degraded"
    assert readiness["capabilities"]["knowledge_distillation"] == "degraded"
    assert readiness["can_run_research_distillation"] is True
    assert not any(issue["source_key"] == "jin10_svip_reports" for issue in readiness["blocking_issues"])


def test_data_quality_monitor_records_task_run_when_enabled(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    _seed_storage(storage_root)
    calls: list[dict] = []

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def step(self, step_name: str, **kwargs):
            calls.append({"step_name": step_name, **kwargs})

        def run_id(self):
            return "dq-run-1"

    def fake_record_task(**kwargs):
        calls.append({"record_task": kwargs})
        return Recorder()

    monkeypatch.setattr(data_quality_agent, "get_data_source_health_latest", lambda date=None: _health_snapshot())
    monkeypatch.setattr(data_quality_agent, "record_task", fake_record_task)

    result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        record_task_run=True,
    )

    assert result["task_run_id"] == "dq-run-1"
    assert calls[0]["record_task"]["task_type"] == "data_quality_monitor"
    assert calls[1]["step_name"] == "write_monitoring_artifacts"
    assert calls[1]["output_refs"][0]["artifact_type"] == "source_health"
    assert calls[1]["source_refs"] == [
        {
            "source": "data_source_health_read_model",
            "source_ref": "data-source-health:2026-07-08",
            "data_date": "2026-07-08",
        }
    ]
