"""TDD: Report Detail API for Phase 4 report artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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


def test_report_detail_macro_report_adapter_reads_macro_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    _make_tree(
        tmp_path,
        {
            "storage/outputs/macro/2026-06-21/run-macro/macro_snapshot.md": "# XAUUSD 宏观数据报告\n\n## 核心宏观指标",
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    factory = _make_session_factory()

    with factory() as db:
        detail = api_main.api_report_detail("macro_report:run-macro", db=db).model_dump(mode="json")
        analysis_payload = api_main.api_report_analysis("macro_report:run-macro", db=db)

    assert detail["family"] == "macro_report"
    assert detail["title"] == "XAUUSD 宏观数据报告（2026-06-21）"
    assert detail["run_id"] == "run-macro"
    assert detail["data_status"] == "live"
    assert analysis_payload["content"].startswith("# XAUUSD 宏观数据报告")


def test_report_detail_legacy_jin10_weekly_bundle_maps_weekly_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    _make_tree(
        tmp_path,
        {
            "storage/outputs/jin10/2026-05-31/220787/raw_article_report.md": "# Weekly Source\n\nBody",
            "storage/outputs/jin10/2026-05-31/220787/agent_analysis_report.md": "# Weekly Analysis\n\nView",
            "storage/outputs/jin10/2026-05-31/220787/daily_analysis.html": "<html><body>weekly</body></html>",
            "storage/outputs/jin10/2026-05-31/220787/raw_article_report.json": json.dumps({"article_id": "220787"}),
            "storage/outputs/jin10/2026-05-31/220787/daily_analysis.json": json.dumps(
                {
                    "family": "jin10_weekly_visual",
                    "report_type": "weekly",
                    "trade_date": "2026-05-31",
                    "run_id": "220787",
                }
            ),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    factory = _make_session_factory()

    with factory() as db:
        payload = api_main.api_report_detail("220787", db=db).model_dump(mode="json")

    assert payload["family"] == "jin10_weekly_visual"
    assert payload["title"] == "Jin10 weekly report"
