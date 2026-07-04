from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.task import StepStatus, TaskRun, TaskStep, TaskStatus, ensure_task_tables

from scripts.backfill_artifact_registry import main


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_run_context(session_factory, *, trade_date: str, task_name: str = "daily_report_pipeline") -> str:
    with session_factory() as session:
        run = TaskRun(
            name=task_name,
            task_type=task_name,
            status=TaskStatus.success,
            trade_date=trade_date,
        )
        session.add(run)
        session.flush()
        session.add(
            TaskStep(
                task_run_id=run.id,
                name="render",
                status=StepStatus.success,
            )
        )
        session.commit()
        return str(run.id)


def _build_storage_fixture(tmp_path: Path, *, final_run: str, strategy_run: str, macro_run: str) -> Path:
    project_root = tmp_path / "repo"
    storage_root = project_root / "storage"

    _write_text(
        storage_root / "outputs" / "final_report" / "XAUUSD" / "2026-06-26" / final_run / "final_report.md",
        "# Final report\n",
    )
    _write_json(
        storage_root / "outputs" / "final_report" / "XAUUSD" / "2026-06-26" / final_run / "run_summary.json",
        {"run_id": final_run, "family": "final_report"},
    )
    _write_text(
        storage_root / "outputs" / "strategy_card" / "XAUUSD" / "2026-06-26" / strategy_run / "strategy_card.md",
        "# Strategy card\n",
    )
    _write_json(
        storage_root / "outputs" / "strategy_card" / "XAUUSD" / "2026-06-26" / strategy_run / "strategy_card.json",
        {"run_id": strategy_run, "bias": "bullish"},
    )
    _write_text(
        storage_root / "outputs" / "macro" / "2026-06-26" / macro_run / "macro_report.md",
        "# Macro report\n",
    )
    _write_json(
        storage_root / "features" / "snapshots" / "2026-06-26" / "snap-001" / "analysis_snapshot.json",
        {"snapshot_id": "snap-001"},
    )
    _write_json(
        storage_root / "features" / "news" / "2026-06-26" / "run-news-001" / "news_digest.json",
        {"headline": "noop"},
    )
    _write_text(storage_root / "outputs" / "unknown" / "2026-06-26" / "ignored.txt", "ignored\n")
    return project_root


def _build_jin10_fixture(tmp_path: Path, *, run_id: str = "222894") -> Path:
    project_root = tmp_path / "repo"
    storage_root = project_root / "storage"
    run_dir = storage_root / "outputs" / "jin10" / "2026-06-26" / run_id
    _write_json(run_dir / "daily_analysis.json", {"run_id": run_id, "family": "jin10_daily_visual"})
    _write_text(run_dir / "daily_analysis.html", "<html>daily</html>\n")
    _write_text(storage_root / "outputs" / "unknown" / "2026-06-26" / "ignored.txt", "ignored\n")
    return project_root


def test_backfill_dry_run_is_default_and_does_not_persist(tmp_path: Path, capsys) -> None:
    session_factory = _make_session_factory()
    final_run = _seed_run_context(session_factory, trade_date="2026-06-26")
    strategy_run = _seed_run_context(session_factory, trade_date="2026-06-26")
    macro_run = _seed_run_context(session_factory, trade_date="2026-06-26", task_name="macro_pipeline")
    project_root = _build_storage_fixture(tmp_path, final_run=final_run, strategy_run=strategy_run, macro_run=macro_run)

    rc = main(
        [
            "--storage-root",
            str(project_root / "storage"),
            "--database-url",
            "sqlite://",
        ],
        session_factory=session_factory,
        project_root=project_root,
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["scanned"] >= 1
    assert output["planned"] >= 1
    assert output["written"] == 0

    with session_factory() as session:
        assert session.query(RunArtifact).count() == 0
        assert session.query(ReportItem).count() == 0
        assert session.query(ReportArtifact).count() == 0


def test_backfill_dry_run_does_not_create_or_migrate_tables(tmp_path: Path, capsys) -> None:
    session_factory = _make_session_factory()
    final_run = _seed_run_context(session_factory, trade_date="2026-06-26")
    project_root = _build_storage_fixture(
        tmp_path,
        final_run=final_run,
        strategy_run="unbound-strategy-run",
        macro_run="unbound-macro-run",
    )

    with (
        patch("scripts.backfill_artifact_registry.ensure_task_tables", side_effect=AssertionError("dry-run must not migrate task tables")),
        patch("scripts.backfill_artifact_registry.ensure_execution_tables", side_effect=AssertionError("dry-run must not migrate execution tables")),
        patch("scripts.backfill_artifact_registry.ensure_analysis_tables", side_effect=AssertionError("dry-run must not migrate analysis tables")),
        patch("scripts.backfill_artifact_registry.ensure_report_tables", side_effect=AssertionError("dry-run must not migrate report tables")),
    ):
        rc = main(
            [
                "--storage-root",
                str(project_root / "storage"),
                "--family",
                "final_report",
            ],
            session_factory=session_factory,
            project_root=project_root,
        )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["written"] == 0


def test_backfill_commit_writes_reports_and_is_idempotent(tmp_path: Path, capsys) -> None:
    session_factory = _make_session_factory()
    final_run = _seed_run_context(session_factory, trade_date="2026-06-26")
    strategy_run = _seed_run_context(session_factory, trade_date="2026-06-26")
    project_root = _build_storage_fixture(tmp_path, final_run=final_run, strategy_run=strategy_run, macro_run="unbound-macro-run")

    final_path = (
        project_root / "storage" / "outputs" / "final_report" / "XAUUSD" / "2026-06-26" / final_run / "final_report.md"
    )
    strategy_path = (
        project_root
        / "storage"
        / "outputs"
        / "strategy_card"
        / "XAUUSD"
        / "2026-06-26"
        / strategy_run
        / "strategy_card.json"
    )

    args = [
        "--storage-root",
        str(project_root / "storage"),
        "--commit",
    ]

    rc1 = main(args, session_factory=session_factory, project_root=project_root)
    out1 = json.loads(capsys.readouterr().out)
    rc2 = main(args, session_factory=session_factory, project_root=project_root)
    out2 = json.loads(capsys.readouterr().out)

    assert rc1 == 0
    assert rc2 == 0
    assert out1["dry_run"] is False
    assert out1["written"] >= 4
    assert out2["written"] == 0

    with session_factory() as session:
        report_items = session.scalars(select(ReportItem).order_by(ReportItem.report_id.asc())).all()
        report_artifacts = session.scalars(select(ReportArtifact).order_by(ReportArtifact.artifact_id.asc())).all()
        run_artifacts = session.scalars(select(RunArtifact).order_by(RunArtifact.file_path.asc())).all()

        report_ids = {row.report_id for row in report_items}
        assert {f"final_report:{final_run}", f"strategy_card:{strategy_run}"}.issubset(report_ids)
        assert all(row.file_path.startswith("storage/") for row in report_artifacts)
        assert any(
            row.file_path
            == f"storage/outputs/final_report/XAUUSD/2026-06-26/{final_run}/final_report.md"
            for row in run_artifacts
        )
        assert any(
            row.file_path
            == f"storage/outputs/strategy_card/XAUUSD/2026-06-26/{strategy_run}/strategy_card.json"
            for row in run_artifacts
        )

        final_artifact = next(
            row
            for row in report_artifacts
            if row.file_path == f"storage/outputs/final_report/XAUUSD/2026-06-26/{final_run}/final_report.md"
        )
        assert final_artifact.sha256 == _sha256_text("# Final report\n")
        assert final_artifact.byte_size == final_path.stat().st_size
        assert final_artifact.artifact_metadata["backfill_family"] == "final_report"
        assert (
            final_artifact.artifact_metadata["relative_path"]
            == f"storage/outputs/final_report/XAUUSD/2026-06-26/{final_run}/final_report.md"
        )
        assert final_artifact.artifact_metadata["storage_backend"] == "local_fs"

        strategy_artifact = next(
            row
            for row in report_artifacts
            if row.file_path == f"storage/outputs/strategy_card/XAUUSD/2026-06-26/{strategy_run}/strategy_card.json"
        )
        assert strategy_artifact.sha256 == hashlib.sha256(strategy_path.read_bytes()).hexdigest()
        assert strategy_artifact.byte_size == strategy_path.stat().st_size


def test_backfill_commit_writes_report_registry_without_task_run_parent(tmp_path: Path, capsys) -> None:
    session_factory = _make_session_factory()
    project_root = _build_storage_fixture(
        tmp_path,
        final_run="manual-final-run",
        strategy_run="manual-strategy-run",
        macro_run="manual-macro-run",
    )

    rc = main(
        [
            "--storage-root",
            str(project_root / "storage"),
            "--family",
            "final_report",
            "--commit",
        ],
        session_factory=session_factory,
        project_root=project_root,
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["written"] >= 2

    with session_factory() as session:
        report_item = session.get(ReportItem, "final_report:manual-final-run")
        assert report_item is not None
        report_artifacts = session.scalars(
            select(ReportArtifact).where(ReportArtifact.report_id == "final_report:manual-final-run")
        ).all()
        assert {artifact.artifact_type for artifact in report_artifacts} == {"analysis_md", "structured_json"}
        assert session.query(RunArtifact).count() == 0


def test_backfill_family_alias_jin10_daily_report_scans_jin10_outputs(tmp_path: Path, capsys) -> None:
    session_factory = _make_session_factory()
    project_root = _build_jin10_fixture(tmp_path)

    rc = main(
        [
            "--storage-root",
            str(project_root / "storage"),
            "--family",
            "jin10_daily_report",
            "--date",
            "2026-06-26",
            "--commit",
        ],
        session_factory=session_factory,
        project_root=project_root,
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["families"] == ["jin10"]
    assert output["written"] >= 3

    with session_factory() as session:
        report_item = session.get(ReportItem, "222894")
        assert report_item is not None
        assert report_item.report_type == "jin10_daily_report"
        artifacts = session.scalars(select(ReportArtifact).where(ReportArtifact.report_id == "222894")).all()
        assert {artifact.file_path for artifact in artifacts} == {
            "storage/outputs/jin10/2026-06-26/222894/daily_analysis.html",
            "storage/outputs/jin10/2026-06-26/222894/daily_analysis.json",
        }


def test_backfill_filters_by_date_family_and_limit(tmp_path: Path, capsys) -> None:
    session_factory = _make_session_factory()
    final_run = _seed_run_context(session_factory, trade_date="2026-06-26")
    strategy_run = _seed_run_context(session_factory, trade_date="2026-06-26")
    macro_run = _seed_run_context(session_factory, trade_date="2026-06-26", task_name="macro_pipeline")
    project_root = _build_storage_fixture(tmp_path, final_run=final_run, strategy_run=strategy_run, macro_run=macro_run)

    rc = main(
        [
            "--storage-root",
            str(project_root / "storage"),
            "--family",
            "strategy_card",
            "--date",
            "2026-06-26",
            "--limit",
            "1",
        ],
        session_factory=session_factory,
        project_root=project_root,
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["planned"] == 1
    assert output["scanned"] == 1
    assert output["skipped"] == 0


def test_backfill_ignores_unknown_paths_and_does_not_modify_source_files(tmp_path: Path, capsys) -> None:
    session_factory = _make_session_factory()
    final_run = _seed_run_context(session_factory, trade_date="2026-06-26")
    project_root = _build_storage_fixture(
        tmp_path,
        final_run=final_run,
        strategy_run="unbound-strategy-run",
        macro_run="unbound-macro-run",
    )

    target = (
        project_root / "storage" / "outputs" / "final_report" / "XAUUSD" / "2026-06-26" / final_run / "final_report.md"
    )
    before_content = target.read_text(encoding="utf-8")
    before_mtime = target.stat().st_mtime_ns

    rc = main(
        [
            "--storage-root",
            str(project_root / "storage"),
            "--family",
            "final_report",
        ],
        session_factory=session_factory,
        project_root=project_root,
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["scanned"] == 2
    assert target.read_text(encoding="utf-8") == before_content
    assert target.stat().st_mtime_ns == before_mtime
    assert not any("unknown" in item for item in output.get("families", []))
