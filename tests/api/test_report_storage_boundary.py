"""Final-report reads stay inside the trusted outputs artifact boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.services import report_storage_service as service
from database.models.analysis import ensure_analysis_tables


DATE = "2026-05-14"
RUN_ID = "run-001"
REPORT_RELATIVE = f"storage/outputs/final_report/XAUUSD/{DATE}/{RUN_ID}/final_report.md"


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def _write_report(root: Path, relative_path: str = REPORT_RELATIVE, content: str = "# Final report") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _seed_final(session: Session, final_report_path: str) -> None:
    from database.queries.analysis import upsert_final_analysis_result

    upsert_final_analysis_result(
        session,
        payload={
            "asset": "XAUUSD",
            "trade_date": DATE,
            "run_id": RUN_ID,
            "snapshot_id": None,
            "analysis_snapshot_db_id": None,
            "final_bias": "bullish",
            "confidence": 0.72,
            "market_state": "risk-on",
            "scenario_summary": "Gold bullish",
            "is_trade_instruction": False,
            "input_snapshot_ids": {},
            "source_refs": [],
            "source_agent_outputs": [],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": [],
            "strategy_card": None,
            "run_summaries": {},
            "payload": {"final": "report"},
        },
        paths={
            "final_report_path": final_report_path,
            "strategy_card_json_path": None,
            "strategy_card_md_path": None,
            "run_summary_path": None,
            "final_report_sha256": None,
            "strategy_card_sha256": None,
        },
    )
    session.commit()


def _bind_service(monkeypatch: pytest.MonkeyPatch, root: Path, db_session: Session | None = None) -> None:
    monkeypatch.setattr(service._storage, "_PROJECT_ROOT", root)
    monkeypatch.setattr(service._storage, "_try_db_session", lambda: db_session)


def test_exact_db_report_preserves_existing_response_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    content = "# Exact via DB"
    report_path = _write_report(tmp_path, content=content)
    (report_path.parent / "structured_report.json").write_text('{"summary": "db"}', encoding="utf-8")
    _seed_final(db_session, REPORT_RELATIVE)
    _bind_service(monkeypatch, tmp_path, db_session)

    result = service.get_final_report(DATE, RUN_ID)

    assert result == {
        "asset": "XAUUSD",
        "trade_date": DATE,
        "run_id": RUN_ID,
        "content": content,
        "format": "markdown",
        "path": REPORT_RELATIVE,
        "structured_sections": {"summary": "db"},
    }


@pytest.mark.parametrize("path_kind", ["raw", "parsed", "absolute", "traversal"])
def test_exact_db_report_rejects_paths_outside_canonical_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    path_kind: str,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    if path_kind == "raw":
        row_path = "storage/raw/XAUUSD/2026-05-14/source/final_report.md"
        _write_report(tmp_path, row_path, "raw content")
    elif path_kind == "parsed":
        row_path = "storage/parsed/XAUUSD/2026-05-14/source/final_report.md"
        _write_report(tmp_path, row_path, "parsed content")
    elif path_kind == "absolute":
        absolute_path = outside / "final_report.md"
        absolute_path.write_text("outside content", encoding="utf-8")
        row_path = str(absolute_path)
    elif path_kind == "traversal":
        row_path = "storage/outputs/final_report/XAUUSD/2026-05-14/../other/final_report.md"
    _seed_final(db_session, row_path)
    _bind_service(monkeypatch, tmp_path, db_session)

    assert service.get_final_report(DATE, RUN_ID) is None


def test_exact_db_report_accepts_registered_output_path_without_canonical_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    row_path = "storage/outputs/archive/2026-05-14/run-001/final_report.md"
    content = "# Registered historical report"
    _write_report(tmp_path, row_path, content)
    _seed_final(db_session, row_path)
    _bind_service(monkeypatch, tmp_path, db_session)

    result = service.get_final_report(DATE, RUN_ID)

    assert result is not None
    assert result["content"] == content
    assert result["path"] == row_path


def test_exact_db_report_accepts_configured_legacy_storage_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    runtime_storage = tmp_path / "runtime-storage"
    runtime_storage.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "storage").symlink_to(runtime_storage, target_is_directory=True)
    alias_root = tmp_path / "legacy-storage"
    row_path = alias_root / "outputs/archive/2026-05-14/run-001/final_report.md"
    relative_runtime_path = "storage/outputs/archive/2026-05-14/run-001/final_report.md"
    _write_report(project_root, relative_runtime_path, "# Legacy alias report")
    _seed_final(db_session, str(row_path))
    monkeypatch.setenv("FINANCE_AGENT_STORAGE_ROOT", str(runtime_storage))
    monkeypatch.setenv("FINANCE_AGENT_LEGACY_STORAGE_ROOTS", str(alias_root))
    _bind_service(monkeypatch, project_root, db_session)

    result = service.get_final_report(DATE, RUN_ID)

    assert result is not None
    assert result["content"] == "# Legacy alias report"
    assert result["path"] == relative_runtime_path


@pytest.mark.parametrize("escape_kind", ["file", "directory"])
def test_latest_report_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, escape_kind: str, db_session: Session
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_report = outside / "final_report.md"
    outside_report.write_text("outside content", encoding="utf-8")
    date_dir = tmp_path / "storage/outputs/final_report/XAUUSD/2026-05-14"
    date_dir.mkdir(parents=True)
    if escape_kind == "file":
        run_dir = date_dir / RUN_ID
        run_dir.mkdir()
        (run_dir / "final_report.md").symlink_to(outside_report)
    else:
        (date_dir / RUN_ID).symlink_to(outside, target_is_directory=True)
    _bind_service(monkeypatch, tmp_path, db_session)

    assert service.get_final_report_latest() is None


def test_latest_report_reads_structured_json_only_inside_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    report_path = _write_report(tmp_path, content="# Filesystem report")
    outside_json = tmp_path / "outside" / "structured_report.json"
    outside_json.parent.mkdir()
    outside_json.write_text('{"secret": true}', encoding="utf-8")
    structured_path = report_path.parent / "structured_report.json"
    structured_path.symlink_to(outside_json)
    _bind_service(monkeypatch, tmp_path, db_session)

    escaped = service.get_final_report_latest()
    assert escaped is not None
    assert escaped["content"] == "# Filesystem report"
    assert escaped["structured_sections"] is None

    structured_path.unlink()
    structured_path.write_text('{"summary": "inside"}', encoding="utf-8")
    safe = service.get_final_report_latest()
    assert safe is not None
    assert safe["structured_sections"] == {"summary": "inside"}


def test_legal_runtime_storage_symlink_remains_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    runtime_storage = tmp_path / "runtime-storage"
    runtime_storage.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "storage").symlink_to(runtime_storage, target_is_directory=True)
    _write_report(project_root, content="# Runtime report")
    monkeypatch.setenv("FINANCE_AGENT_STORAGE_ROOT", str(runtime_storage))
    _bind_service(monkeypatch, project_root, db_session)

    result = service.get_final_report_latest()

    assert result is not None
    assert result["content"] == "# Runtime report"
    assert result["path"] == REPORT_RELATIVE


@pytest.mark.parametrize("bad_date", ["../2026-05-14", "/tmp/2026-05-14"])
def test_exact_report_rejects_path_components_before_db_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_date: str
) -> None:
    _write_report(tmp_path)
    _bind_service(monkeypatch, tmp_path)

    assert service.get_final_report(bad_date, RUN_ID) is None


@pytest.mark.parametrize("layout", ["outputs", "final_report"])
def test_outputs_boundary_rejects_external_symlink_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str, db_session: Session
) -> None:
    outside = tmp_path / "outside"
    _write_report(outside, content="# Escaped report")
    project_root = tmp_path / "project"
    (project_root / "storage").mkdir(parents=True)
    if layout == "outputs":
        (project_root / "storage" / "outputs").symlink_to(
            outside / "storage" / "outputs", target_is_directory=True
        )
    else:
        outputs = project_root / "storage" / "outputs"
        outputs.mkdir()
        (outputs / "final_report").symlink_to(
            outside / "storage" / "outputs" / "final_report", target_is_directory=True
        )
    _bind_service(monkeypatch, project_root, db_session)

    assert service.get_final_report_latest() is None


@pytest.mark.parametrize("link_kind", ["final_report", "asset"])
def test_latest_report_rejects_external_regular_file_directory_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link_kind: str, db_session: Session
) -> None:
    outside_file = tmp_path / "outside-report-file"
    outside_file.write_text("not a directory", encoding="utf-8")
    outputs = tmp_path / "storage/outputs"
    outputs.mkdir(parents=True)
    if link_kind == "final_report":
        (outputs / "final_report").symlink_to(outside_file)
    else:
        final_report = outputs / "final_report"
        final_report.mkdir()
        (final_report / "XAUUSD").symlink_to(outside_file)
    _bind_service(monkeypatch, tmp_path, db_session)

    assert service.get_final_report_latest() is None
