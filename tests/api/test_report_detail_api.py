"""TDD: Report Detail API for Phase 4 report artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.worker.pipelines.macro_event_followup import generate_macro_event_followup
from database.models.analysis import ensure_analysis_tables
from database.models.task import ensure_task_tables


def _make_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    ensure_task_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _make_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _seed_report(session: Session) -> None:
    from database.models.report import ensure_report_tables
    from database.queries.report import upsert_report_artifact, upsert_report_item

    ensure_report_tables(session)
    upsert_report_item(
        session,
        {
            "report_id": "report-std-001",
            "family": "macro",
            "report_type": "daily_macro",
            "title": "Macro Daily Report",
            "asset": "XAUUSD",
            "trade_date": "2026-05-26",
            "run_id": "run-std-001",
            "snapshot_id": "snap-std-001",
            "data_status": "live",
            "lifecycle_status": "generated",
            "source_refs": [
                {
                    "source_id": "src-001",
                    "source_name": "Macro Feed",
                    "source_type": "api",
                    "status": "available",
                }
            ],
            "metadata": {"template_version": "v1"},
        },
    )
    artifact_specs = [
        ("source", "source_md", "source.md", "text/markdown", True),
        ("analysis", "analysis_md", "analysis.md", "text/markdown", False),
        ("visual", "visual_html", "visual.html", "text/html", False),
        ("structured", "structured_json", "report_structured.json", "application/json", False),
    ]
    for suffix, artifact_type, name, content_type, is_primary in artifact_specs:
        upsert_report_artifact(
            session,
            {
                "artifact_id": f"report-std-001:{suffix}",
                "report_id": "report-std-001",
                "artifact_type": artifact_type,
                "file_path": f"storage/outputs/reports/2026-05-26/report-std-001/{name}",
                "version": "1",
                "status": "generated",
                "content_type": content_type,
                "is_primary": is_primary,
            },
        )
    session.commit()


def _seed_legacy_final(session: Session) -> None:
    from database.queries.analysis import upsert_final_analysis_result

    payload = {
        "asset": "XAUUSD",
        "trade_date": "2026-05-26",
        "run_id": "run-legacy-001",
        "snapshot_id": "snap-legacy-001",
        "analysis_snapshot_db_id": None,
        "final_bias": "bullish",
        "confidence": 0.82,
        "market_state": "trend_up",
        "scenario_summary": "Legacy report",
        "is_trade_instruction": False,
        "input_snapshot_ids": {"analysis": "snap-legacy-001"},
        "source_refs": [
            {
                "source_id": "src-legacy-001",
                "source_name": "Coordinator",
                "source_type": "agent_output",
                "status": "generated",
            }
        ],
        "source_agent_outputs": ["macro", "options"],
        "risk_points": [],
        "watchlist": [],
        "invalid_conditions": [],
        "strategy_card": None,
        "run_summaries": {},
        "payload": {"final": "report"},
    }
    paths = {
        "final_report_path": "storage/outputs/final_report/XAUUSD/2026-05-26/run-legacy-001/final_report.md",
        "strategy_card_json_path": None,
        "strategy_card_md_path": None,
        "run_summary_path": "storage/outputs/run/2026-05-26/run-legacy-001/step_summaries.json",
        "final_report_sha256": "legacysha",
        "strategy_card_sha256": None,
    }
    upsert_final_analysis_result(session, payload=payload, paths=paths)
    session.commit()


def _seed_snapshot(session: Session, *, snapshot_id: str = "snap-std-001", run_id: str = "run-std-001") -> None:
    from database.queries.analysis import upsert_analysis_snapshot

    upsert_analysis_snapshot(
        session,
        payload={
            "snapshot_id": snapshot_id,
            "asset": "XAUUSD",
            "trade_date": "2026-05-26",
            "run_id": run_id,
            "status": "success",
            "input_snapshot_ids": {"macro": "macro-raw-001"},
            "source_refs": [{"source_id": "src-snapshot", "source_name": "Snapshot Feed", "source_type": "api", "status": "available"}],
            "macro": {"regime": "tightening"},
            "payload": {"snapshot_id": snapshot_id},
        },
        artifact_path=f"storage/features/2026-05-26/{snapshot_id}/analysis_snapshot.json",
    )


def test_report_detail_returns_standard_four_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_report(session)

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source\n\nBody",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis\n\nView",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html><body>visual</body></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_detail("report-std-001", db=db).model_dump(mode="json")

    assert payload["report_id"] == "report-std-001"
    assert payload["data_status"] == "live"
    assert {item["artifact_type"] for item in payload["artifacts"]} == {
        "source_md",
        "analysis_md",
        "visual_html",
        "structured_json",
    }


def test_report_detail_includes_gold_macro_overview_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_report(session)

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source\n\nBody",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis\n\nView",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html><body>visual</body></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        report_service,
        "get_gold_mainlines_latest",
        lambda *, project_root=None: {
            "status": "partial",
            "gold_macro_overview": {
                "asset": "XAUUSD",
                "as_of": "2026-06-30T00:00:00Z",
                "dominant_mainline": "real_rates_usd",
                "theme_rankings": [{"rank": 1, "mainline_id": "real_rates_usd", "score": 72}],
                "verification_matrix": [{"label": "多源确认", "status": "pending"}],
            },
        },
    )

    with factory() as db:
        payload = api_main.api_report_detail("report-std-001", db=db).model_dump(mode="json")

    assert payload["gold_macro_overview"]["asset"] == "XAUUSD"
    assert payload["gold_macro_overview"]["dominant_mainline"] == "real_rates_usd"
    assert payload["gold_macro_overview"]["theme_rankings"][0]["mainline_id"] == "real_rates_usd"


def test_report_subroutes_read_standard_source_and_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_report(session)

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source\n\nPrimary text",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis\n\nInterpretation",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html><body>visual</body></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": [{"id": "s1"}]}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        source_payload = api_main.api_report_source("report-std-001", db=db)
        analysis_payload = api_main.api_report_analysis("report-std-001", db=db)
        evidence_payload = api_main.api_report_evidence("report-std-001", db=db)

    assert source_payload["content"].startswith("# Source")
    assert analysis_payload["content"].startswith("# Analysis")
    assert evidence_payload["content"]["sections"][0]["id"] == "s1"


def test_artifact_detail_supports_standard_report_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import artifact_service
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_report(session)

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source\n\nBody",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis\n\nView",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html><body>visual</body></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(artifact_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_artifact_detail("report-std-001:source", db=db).model_dump(mode="json")

    assert payload["run_id"] == "run-std-001"
    assert payload["snapshot_id"] == "snap-std-001"
    assert payload["task_name"] == "report_artifact"
    assert payload["stage"] == "report"
    assert payload["artifact"]["artifact_id"] == "report-std-001:source"
    assert payload["artifact"]["artifact_type"] == "source_md"
    assert payload["artifact"]["file_path"] == "storage/outputs/reports/2026-05-26/report-std-001/source.md"
    assert {item["artifact_id"] for item in payload["artifact_refs"]} == {
        "report-std-001:source",
        "report-std-001:analysis",
        "report-std-001:visual",
        "report-std-001:structured",
    }
    assert {item["source_id"] for item in payload["source_refs"]} == {"src-001"}
    assert payload["metadata"]["report_id"] == "report-std-001"
    assert payload["metadata"]["family"] == "macro"
    assert payload["warnings"] == []


def test_artifact_detail_warns_when_standard_report_lineage_drifted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service
    from database.models.report import ReportItem

    factory = _make_session_factory()
    with factory() as session:
        _seed_report(session)
        _seed_snapshot(session)
        report_item = session.get(ReportItem, "report-std-001")
        report_item.snapshot_id = "snap-declared-999"
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source\n\nBody",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis\n\nView",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html><body>visual</body></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_artifact_detail("report-std-001:source", db=db).model_dump(mode="json")

    warning_codes = {item["code"] for item in payload["warnings"]}
    assert "report-lineage-snapshot-mismatch" in warning_codes
    assert payload["snapshot_id"] == "snap-std-001"


def test_report_detail_warns_when_declared_snapshot_drifted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service
    from database.models.report import ReportItem

    factory = _make_session_factory()
    with factory() as session:
        _seed_report(session)
        _seed_snapshot(session)
        report_item = session.get(ReportItem, "report-std-001")
        report_item.snapshot_id = "snap-declared-999"
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source\n\nBody",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis\n\nView",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html><body>visual</body></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_detail("report-std-001", db=db).model_dump(mode="json")

    warning_codes = {item["code"] for item in payload["warnings"]}
    assert "report-lineage-snapshot-mismatch" in warning_codes
    assert payload["snapshot_id"] == "snap-std-001"


def test_report_detail_marks_missing_visual_partial_and_visual_route_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_report(session)

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source\n\nBody",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis\n\nView",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        detail = api_main.api_report_detail("report-std-001", db=db).model_dump(mode="json")
    assert detail["data_status"] == "partial"
    missing_warnings = [warning for warning in detail["warnings"] if warning["code"] == "report-artifact-missing-file"]
    assert missing_warnings
    assert missing_warnings[0]["field"] == "storage/outputs/reports/2026-05-26/report-std-001/visual.html"

    with factory() as db:
        with pytest.raises(HTTPException) as exc:
            api_main.api_report_visual("report-std-001", db=db)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Report artifact not found"


def test_report_detail_legacy_final_report_adapter_reads_markdown_and_structured_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_legacy_final(session)

    _make_tree(
        tmp_path,
        {
            "storage/outputs/final_report/XAUUSD/2026-05-26/run-legacy-001/final_report.md": "# Legacy Final\n\nContent",
            "storage/outputs/final_report/XAUUSD/2026-05-26/run-legacy-001/structured_report.json": json.dumps(
                {"summary": "legacy"}
            ),
            "storage/outputs/run/2026-05-26/run-legacy-001/step_summaries.json": json.dumps({"renderer": "done"}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        detail = api_main.api_report_detail("run-legacy-001", db=db).model_dump(mode="json")
        analysis_payload = api_main.api_report_analysis("run-legacy-001", db=db)
        evidence_payload = api_main.api_report_evidence("run-legacy-001", db=db)

    artifact_paths = {item["file_path"] for item in detail["artifacts"]}
    assert detail["report_id"] == "run-legacy-001"
    assert detail["data_status"] == "partial"
    assert "storage/outputs/final_report/XAUUSD/2026-05-26/run-legacy-001/final_report.md" in artifact_paths
    assert "storage/outputs/final_report/XAUUSD/2026-05-26/run-legacy-001/structured_report.json" in artifact_paths
    assert analysis_payload["content"].startswith("# Legacy Final")
    assert evidence_payload["content"]["summary"] == "legacy"


def test_report_detail_filesystem_final_report_adapter_reads_markdown_without_db_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    _make_tree(
        tmp_path,
        {
            "storage/outputs/final_report/XAUUSD/2026-06-21/run-related/final_report.md": "# XAUUSD 相关报告\n\n## 综合报告",
            "storage/outputs/final_report/XAUUSD/2026-06-21/run-related/structured_report.json": json.dumps(
                {"sections": ["综合报告"]}
            ),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    factory = _make_session_factory()

    with factory() as db:
        detail = api_main.api_report_detail("run-related", db=db).model_dump(mode="json")
        analysis_payload = api_main.api_report_analysis("run-related", db=db)

    assert detail["family"] == "final_report_markdown"
    assert detail["title"] == "XAUUSD 综合报告"
    assert detail["data_status"] == "live"
    assert analysis_payload["content"].startswith("# XAUUSD 相关报告")


def test_report_detail_macro_report_adapter_prefers_macro_full_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    _make_tree(
        tmp_path,
        {
            "storage/outputs/macro/2026-06-21/run-macro/macro_full_report.md": "# XAUUSD 宏观 / 流动性更新\n\n## 一句话结论",
            "storage/outputs/macro/2026-06-21/run-macro/macro_snapshot.md": "# XAUUSD 宏观数据报告\n\n## 核心宏观指标",
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    factory = _make_session_factory()

    with factory() as db:
        detail = api_main.api_report_detail("macro_report:run-macro", db=db).model_dump(mode="json")
        analysis_payload = api_main.api_report_analysis("macro_report:run-macro", db=db)

    assert detail["family"] == "macro_report"
    assert detail["title"] == "XAUUSD 宏观分析报告（2026-06-21）"
    assert detail["run_id"] == "run-macro"
    assert detail["data_status"] == "live"
    assert analysis_payload["content"].startswith("# XAUUSD 宏观 / 流动性更新")


def test_report_detail_macro_event_followup_adapter_uses_trade_date_scoped_report_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    _make_tree(
        tmp_path,
        {
            "storage/outputs/macro_event_followup/XAUUSD/2026-05-17/run-shared/source.md": "# Source\n\n2026-05-17",
            "storage/outputs/macro_event_followup/XAUUSD/2026-05-17/run-shared/analysis.md": "# Analysis\n\nLatest day",
            "storage/outputs/macro_event_followup/XAUUSD/2026-05-17/run-shared/report_structured.json": json.dumps(
                {
                    "report_type": "macro_event_followup",
                    "trade_date": "2026-05-17",
                    "anchor_trade_date": "2026-05-16",
                    "anchor_report_refs": [{"report_id": "final_report:run-2026-05-16"}],
                    "new_macro_events": [{"headline": "Latest weekend event"}],
                    "impact_assessment": {"stance": "reinforce", "summary": "Latest summary"},
                    "watch_items": [{"item": "Watch Monday open"}],
                    "revision_risk": {"status": "monitor"},
                    "source_refs": [{"source_type": "report", "ref": "final_report:run-2026-05-16"}],
                }
            ),
            "storage/outputs/macro_event_followup/XAUUSD/2026-05-16/run-shared/source.md": "# Source\n\n2026-05-16",
            "storage/outputs/macro_event_followup/XAUUSD/2026-05-16/run-shared/analysis.md": "# Analysis\n\nOlder day",
            "storage/outputs/macro_event_followup/XAUUSD/2026-05-16/run-shared/report_structured.json": json.dumps(
                {
                    "report_type": "macro_event_followup",
                    "trade_date": "2026-05-16",
                    "anchor_trade_date": "2026-05-15",
                    "anchor_report_refs": [{"report_id": "final_report:run-2026-05-15"}],
                    "new_macro_events": [{"headline": "Older weekend event"}],
                    "impact_assessment": {"stance": "monitor", "summary": "Older summary"},
                    "watch_items": [{"item": "Watch prior open"}],
                    "revision_risk": {"status": "low"},
                    "source_refs": [{"source_type": "report", "ref": "final_report:run-2026-05-15"}],
                }
            ),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    factory = _make_session_factory()

    with factory() as db:
        detail = api_main.api_report_detail("macro_event_followup:2026-05-16:run-shared", db=db).model_dump(mode="json")

    assert detail["report_id"] == "macro_event_followup:2026-05-16:run-shared"
    assert detail["trade_date"] == "2026-05-16"
    assert detail["run_id"] == "run-shared"
    assert detail["structured_payload"]["trade_date"] == "2026-05-16"
    assert detail["structured_payload"]["impact_assessment"]["summary"] == "Older summary"


def test_report_detail_reads_generated_macro_event_followup_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    _make_tree(
        tmp_path,
        {
            "storage/outputs/final_report/XAUUSD/2026-06-20/run-anchor/final_report.md": "# Final Report\n",
            "storage/outputs/strategy_card/XAUUSD/2026-06-20/run-anchor/strategy_card.json": "{}",
            "storage/features/news/2026-06-21/run-news/daily_market_brief.json": json.dumps(
                {
                    "daily_market_brief": {
                        "market_mainline": {"status": "available", "summary": "Weekend macro updates keep gold sensitive to Fed repricing."},
                        "confirmed_events": [
                            {
                                "event_type": "fed_hawkish",
                                "what_happened": "Fed speaker stayed hawkish.",
                                "source_refs": [{"source": "jin10", "source_ref": "evt:1"}],
                            }
                        ],
                        "candidate_events": [],
                        "unconfirmed_risks": [],
                        "source_refs": [{"source": "jin10", "source_ref": "brief:1"}],
                    }
                }
            ),
            "storage/features/news/2026-06-21/run-news/daily_analysis_triggers.json": json.dumps(
                {
                    "as_of": "2026-06-21T10:00:00+00:00",
                    "trigger_count": 1,
                    "triggers": [
                        {
                            "trigger_id": "trigger-1",
                            "priority": "high",
                            "source_title": "Weekend Fed repricing",
                            "source_url": "https://xnews.jin10.com/details/trigger-1",
                            "event_type": "fed_hawkish",
                            "suggested_actions": ["run_jin10_daily_analysis"],
                            "source_refs": [{"source": "jin10", "source_ref": "trigger:1"}],
                        }
                    ],
                    "data_quality": {},
                }
            ),
            "storage/features/news/2026-06-21/run-news/jin10_article_briefs.json": json.dumps(
                {
                    "as_of": "2026-06-21T10:05:00+00:00",
                    "brief_count": 1,
                    "briefs": [
                        {
                            "brief_id": "brief-1",
                            "article_class": "gold_macro_market_reference",
                            "headline": "Gold weekend brief",
                            "source_url": "https://xnews.jin10.com/details/brief-1",
                            "access_status": "readable",
                            "analysis_summary": "Weekend macro headlines reinforce the prior gold thesis.",
                            "original_excerpt": "Weekend macro headlines reinforce the prior gold thesis.",
                            "key_points": ["Fed path still restrictive"],
                            "suggested_actions": ["queue_daily_analysis"],
                            "source_refs": [{"source": "jin10", "source_ref": "brief:generated"}],
                        }
                    ],
                    "data_quality": {},
                }
            ),
        },
    )
    generate_macro_event_followup(
        trade_date="2026-06-21",
        asset="XAUUSD",
        storage_root=tmp_path / "storage",
        run_id="run-generated",
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    factory = _make_session_factory()

    with factory() as db:
        detail = api_main.api_report_detail("macro_event_followup:2026-06-21:run-generated", db=db).model_dump(mode="json")

    assert detail["report_id"] == "macro_event_followup:2026-06-21:run-generated"
    assert detail["trade_date"] == "2026-06-21"
    assert detail["run_id"] == "run-generated"
    assert detail["structured_payload"]["anchor_trade_date"] == "2026-06-20"
    assert detail["structured_payload"]["impact_assessment"]["summary"] == (
        "Fed speaker stayed hawkish. | Weekend Fed repricing | Weekend macro headlines reinforce the prior gold thesis."
    )


def test_report_detail_legacy_jin10_weekly_bundle_maps_weekly_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-05-31/220787/raw_article_report.md": "# Weekly Source\n\nBody\n\n![图表 1](figures/fig_p1_001.png)",
            "storage/outputs/jin10/2026-05-31/220787/agent_analysis_report.md": "# Weekly Analysis\n\nView",
            "storage/outputs/jin10/2026-05-31/220787/daily_analysis.html": "<html><body>weekly</body></html>",
            "external-jin10/2026-05-31/weekly/220787/report.md": "# Original Weekly Draft\n\nExternal raw source.",
            "external-jin10/2026-05-31/weekly/220787/meta.json": json.dumps(
                {
                    "date": "2026-05-31",
                    "id": "220787",
                    "title": "External Weekly",
                    "category": "黄金周报",
                    "report_type": "weekly",
                }
            ),
            "storage/outputs/jin10/2026-05-31/220787/raw_article_report.json": json.dumps(
                {
                    "article_id": "220787",
                    "charts": [
                        {
                            "figure_id": "fig_p1_001",
                            "image_path": "figures/fig_p1_001.png",
                            "title": "图表 1",
                            "recognized_text": "这是一段过长的正文混入图表识别文本，需要触发语义复核。" * 12,
                        }
                    ],
                    "generated_from": {
                        "source": "jin10_external",
                        "content_stage": "parsed_markdown",
                        "parser_trace": {
                            "status": {
                                "parser_version": "jin10-vlm-parser-v0.2",
                                "parser_run_id": "test-run",
                                "recognition_mode": "vlm",
                                "vision_provider": "mimo",
                                "vision_model": "mimo-v2.5",
                                "vision_markdown_status": "success",
                                "vision_layout_status": "success",
                            },
                        },
                    },
                    "quality_audit": {"status": "accepted", "checked_at": "2026-05-31T00:00:00Z"},
                    "source_refs": [
                        {
                            "source": "jin10_external",
                            "source_url": "https://svip.jin10.com/news/220787",
                            "path": "/tmp/report.md",
                        }
                    ],
                }
            ),
            "storage/outputs/jin10/2026-05-31/220787/agent_analysis_report.json": json.dumps(
                {
                    "generated_from": {
                        "provider": "codex",
                        "model": "gpt-5-codex",
                        "generated_at": "2026-05-31T01:00:00Z",
                    },
                    "scenario_paths": [{"path": "路径A", "summary": "4100企稳"}],
                    "trading_implications": [{"stance": "短线", "trigger": "站稳4120"}],
                    "source_refs": [
                        {
                            "source": "jin10_agent_analysis",
                            "source_url": "https://svip.jin10.com/news/220787",
                            "path": "/tmp/agent.json",
                        }
                    ],
                }
            ),
            "storage/outputs/jin10/2026-05-31/220787/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_weekly_visual",
                    "report_type": "weekly",
                    "report_identity": {
                        "classification_label": "黄金投资者周报",
                        "report_theme": "黄金日线底部确认",
                        "verification_status": "confirmed",
                    },
                    "trade_date": "2026-05-31",
                    "run_id": "220787",
                }
            ),
            "storage/parsed/jin10/2026-05-31/220787/figures/fig_p1_001.png": "png",
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(report_service, "_JIN10_EXTERNAL_ROOT", tmp_path / "external-jin10")
    factory = _make_session_factory()

    with factory() as db:
        payload = api_main.api_report_detail("220787", db=db).model_dump(mode="json")
        source_payload = api_main.get_report_source(db, "220787")

    assert payload["family"] == "jin10_weekly_visual"
    assert payload["title"] == "External Weekly"
    assert payload["report_identity"]["classification_label"] == "黄金投资者周报"
    assert payload["report_identity"]["report_theme"] == "黄金日线底部确认"
    assert source_payload is not None
    assert source_payload["path"] == "storage/outputs/jin10/2026-05-31/220787/raw_article_report.md"
    assert "# Weekly Source" in source_payload["content"]
    assert "# Original Weekly Draft" not in source_payload["content"]
    assert payload["data_status"] == "partial"
    assert payload["lifecycle_status"] == "needs_review"
    assert any(item["code"] == "jin10-chart-text-needs-review" for item in payload["warnings"])
    assert len(payload["source_refs"]) == 2
    trace = payload["structured_payload"]["_generation_trace"]
    assert trace["llm"]["model"] == "gpt-5-codex"
    assert trace["vlm"]["status"] == "tracked"
    assert trace["vlm"]["provider"] == "mimo"
    assert trace["vlm"]["model"] == "mimo-v2.5"
    assert trace["vlm"]["parser_run_id"] == "test-run"
    assert trace["vlm"]["vision_layout_status"] == "success"
    assert trace["vlm"]["reason"] is None
    assert trace["asset_audit"]["status"] == "pass"
    assert trace["source_counts"]["original_images"] == 0
    assert trace["quality_audit"]["semantic_review_status"] == "needs_review"
    assert trace["quality_audit"]["chart_text_issues"][0]["figure_id"] == "fig_p1_001"
    assert trace["strategy_handoff"]["scenario_paths"][0]["title"] == "路径A"


def test_report_detail_jin10_chart_asset_mismatch_requires_agent_loop_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-07-05/223608/raw_article_report.md": (
                "# Weekly Source\n\n"
                "![图表 1](figures/fig_p1_001.png)\n\n"
                "![图表 2](figures/fig_p2_001.png)\n"
            ),
            "storage/outputs/jin10/2026-07-05/223608/agent_analysis_report.md": "# Weekly Analysis\n\nView",
            "storage/outputs/jin10/2026-07-05/223608/daily_analysis.html": "<html><body>weekly</body></html>",
            "storage/outputs/jin10/2026-07-05/223608/raw_article_report.json": json.dumps(
                {
                    "article_id": "223608",
                    "charts": [
                        {"figure_id": "fig_p1_001", "image_path": "figures/fig_p1_001.png", "title": "图表 1"},
                        {"figure_id": "fig_p2_001", "image_path": "figures/fig_p2_001.png", "title": "图表 2"},
                    ],
                    "generated_from": {
                        "source": "jin10_external",
                        "parser_trace": {
                            "status": "success",
                            "figures_total": 1,
                            "vision_layout_status": "partial",
                        },
                    },
                    "quality_audit": {"status": "accepted", "checked_at": "2026-07-05T00:00:00Z"},
                }
            ),
            "storage/outputs/jin10/2026-07-05/223608/agent_analysis_report.json": json.dumps(
                {
                    "generated_from": {"provider": "codex", "model": "gpt-5-codex"},
                    "source_refs": [],
                }
            ),
            "storage/outputs/jin10/2026-07-05/223608/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_weekly_visual",
                    "report_type": "weekly",
                    "trade_date": "2026-07-05",
                    "run_id": "223608",
                }
            ),
            "storage/parsed/jin10/2026-07-05/223608/figures/fig_p1_001.png": "png",
            "storage/parsed/jin10/2026-07-05/223608/figures/fig_p2_001.png": "png",
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(report_service, "_JIN10_EXTERNAL_ROOT", tmp_path / "external-jin10")
    factory = _make_session_factory()

    with factory() as db:
        payload = api_main.api_report_detail("223608", db=db).model_dump(mode="json")

    trace = payload["structured_payload"]["_generation_trace"]
    assert payload["data_status"] == "partial"
    assert payload["lifecycle_status"] == "needs_review"
    assert any(item["code"] == "jin10-chart-assets-needs-review" for item in payload["warnings"])
    assert trace["asset_audit"]["status"] == "needs_review"
    assert trace["asset_audit"]["markdown_image_refs"] == 2
    assert trace["asset_audit"]["raw_chart_count"] == 2
    assert trace["asset_audit"]["figure_files"] == 2
    assert trace["asset_audit"]["parser_figures_total"] == 1
    assert trace["asset_audit"]["count_issues"][0]["code"] == "parser_figure_count_mismatch"


def test_jin10_asset_audit_normalizes_equivalent_image_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.services import report_service

    run_dir = tmp_path / "storage" / "outputs" / "jin10" / "2026-07-05" / "223609-benchmark"
    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-07-05/223609-benchmark/raw_article_report.md": (
                "# Source\n\n"
                "![图表 1](./figures/fig_p1_001.png)\n\n"
                "![图表 2](/api/reports/223609/asset/fig_p2_001.png?raw=1)\n"
            ),
            "storage/parsed/jin10/2026-07-05/223609/figures/fig_p1_001.png": "png",
            "storage/parsed/jin10/2026-07-05/223609/figures/fig_p2_001.png": "png",
            "storage/parsed/jin10/2026-07-05/223609/figures/fig_p3_unreferenced.png": "png",
        },
    )
    raw_payload = {
        "article_id": "223609",
        "charts": [
            {"figure_id": "fig_p1_001", "image_path": "figures/fig_p1_001.png?raw=1"},
            {"figure_id": "fig_p2_001", "image_path": "figures/fig_p2_001.png"},
        ],
        "generated_from": {"parser_trace": {"figures_total": 2}},
    }

    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    audit = report_service._build_jin10_asset_audit(run_dir=run_dir, raw_payload=raw_payload)

    assert audit["status"] == "pass"
    assert audit["missing_refs"] == []
    assert audit["extra_files"] == []
    assert audit["count_issues"] == []
    assert audit["figure_files"] == 2
    assert audit["canonical_figure_files"] == 3


def test_jin10_chart_text_audit_uses_compound_noise_signals() -> None:
    from apps.api.services.report_service import _jin10_chart_text_issues

    dense_table_text = "A" * 121
    article_like_text = "黄金价格继续震荡。" * 24

    assert _jin10_chart_text_issues([{"figure_id": "table", "recognized_text": dense_table_text}]) == []
    issues = _jin10_chart_text_issues([{"figure_id": "article", "recognized_text": article_like_text}])
    assert issues[0]["figure_id"] == "article"
