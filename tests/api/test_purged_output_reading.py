"""Reader fences for cleaned derived output tombstones.

These tests use isolated SQLite and temporary storage only.  They cover the
legacy filesystem fallbacks because a cleanup operation deliberately may leave
the physical file until shared-path reference protection has finished.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.services import report_index_service, report_storage_service, report_strategy_service
from apps.api.services.agent_analysis_service import _agent_inspection_item
from apps.api.services.agent_output_service import build_agent_output_summary
from apps.api.services.artifact_service import get_artifact_detail_response
from apps.api.services.report_reading import detail as report_detail_service
from apps.api.services.report_reading.detail import (
    _build_agent_fallback_inputs,
    get_report_artifacts,
    get_report_detail,
    get_report_evidence,
    get_report_source,
)
from apps.runtime.output_disposition import is_output_purged
from database.models.analysis import AgentOutput, ensure_analysis_tables
from database.models.report import ensure_report_tables
from database.queries.analysis import upsert_final_analysis_result
from database.queries.report import upsert_report_artifact, upsert_report_item


_PROJECT_ROOT_PATCH = "apps.api.services._storage._PROJECT_ROOT"
_DB_SESSION_PATCH = "apps.api.services._storage._try_db_session"


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _session_without_agent_output():
    session = _session()
    engine = session.get_bind()
    AgentOutput.__table__.drop(engine, checkfirst=True)
    session.close()
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _marker(*, run_id: str, snapshot_id: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "status": "purged",
        "reason_codes": ["quality_gate_failed"],
        "purged_at": "2026-10-12T12:00:00+00:00",
        "original_payload_sha256": "a" * 64,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
    }


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _upsert_final(session, *, trade_date: str, run_id: str, payload: dict):
    return upsert_final_analysis_result(
        session,
        payload={
            "asset": "XAUUSD",
            "trade_date": trade_date,
            "run_id": run_id,
            "snapshot_id": None,
            "analysis_snapshot_db_id": None,
            "final_bias": "bullish",
            "confidence": 0.8,
            "market_state": "risk-on",
            "scenario_summary": "old body must never be projected after purge",
            "is_trade_instruction": False,
            "input_snapshot_ids": {},
            "source_refs": [],
            "source_agent_outputs": [],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": [],
            "strategy_card": {"bias": "bullish", "confidence": 0.8},
            "run_summaries": {},
            "payload": payload,
        },
        paths={
            "final_report_path": f"storage/outputs/final_report/XAUUSD/{trade_date}/{run_id}/final_report.md",
            "strategy_card_json_path": f"storage/outputs/strategy_card/XAUUSD/{trade_date}/{run_id}/strategy_card.json",
            "strategy_card_md_path": f"storage/outputs/strategy_card/XAUUSD/{trade_date}/{run_id}/strategy_card.md",
        },
    )


def test_output_cleanup_requires_schema_version_one_and_handles_scalar_values() -> None:
    marker = _marker(run_id="run-purged")
    assert is_output_purged({"output_cleanup": marker})
    assert is_output_purged(json.dumps({"output_cleanup": marker}))
    assert not is_output_purged({"output_cleanup": {"status": "purged"}})
    assert not is_output_purged({"output_cleanup": {"schema_version": 2, "status": "purged"}})
    assert not is_output_purged({"status": "purged"})
    assert is_output_purged(SimpleNamespace(status="purged"))
    assert not is_output_purged(None)
    assert not is_output_purged("ordinary text")


def test_current_latest_fails_closed_without_db_even_when_old_files_remain(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "storage/outputs/final_report/XAUUSD/2026-10-11/old-good/final_report.md",
        "OLD GOOD",
    )
    _write(
        tmp_path,
        "storage/outputs/strategy_card/XAUUSD/2026-10-11/old-good/strategy_card.json",
        json.dumps({"bias": "bullish", "confidence": 0.8}),
    )

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: None),
    ):
        assert report_storage_service.get_final_report_latest() is None
        assert report_strategy_service.get_strategy_card_latest() is None
        assert report_strategy_service.get_strategy_card_read_model_latest() is None


def test_current_latest_fails_closed_when_db_query_raises(tmp_path: Path) -> None:
    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("database connection lost")

        def close(self):
            return None

    _write(
        tmp_path,
        "storage/outputs/final_report/XAUUSD/2026-10-11/old-good/final_report.md",
        "OLD GOOD",
    )
    _write(
        tmp_path,
        "storage/outputs/strategy_card/XAUUSD/2026-10-11/old-good/strategy_card.json",
        json.dumps({"bias": "bullish", "confidence": 0.8}),
    )

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, BrokenSession),
    ):
        assert report_storage_service.get_final_report_latest() is None
        assert report_strategy_service.get_strategy_card_latest() is None
        assert report_strategy_service.get_strategy_card_read_model_latest() is None


def test_final_latest_does_not_fall_back_to_old_file_after_new_purge(tmp_path: Path) -> None:
    session = _session()
    _upsert_final(session, trade_date="2026-10-11", run_id="new-purged", payload={"output_cleanup": _marker(run_id="new-purged")})
    session.commit()
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-10/old-good/final_report.md", "OLD GOOD")
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-11/new-purged/final_report.md", "PURGED BODY")

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        assert report_storage_service.get_final_report_latest() is None


def test_final_latest_keeps_valid_newer_history_when_purge_is_older(tmp_path: Path) -> None:
    session = _session()
    _upsert_final(session, trade_date="2026-10-10", run_id="old-purged", payload={"output_cleanup": _marker(run_id="old-purged")})
    session.commit()
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-11/new-good/final_report.md", "NEW GOOD")

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        result = report_storage_service.get_final_report_latest()

    assert result is not None
    assert result["run_id"] == "new-good"
    assert result["content"] == "NEW GOOD"


def test_same_date_valid_db_creation_beats_cleanup_updated_at(tmp_path: Path) -> None:
    session = _session()
    purged = _upsert_final(
        session,
        trade_date="2026-10-11",
        run_id="old-purged",
        payload={"output_cleanup": _marker(run_id="old-purged")},
    )
    valid = _upsert_final(session, trade_date="2026-10-11", run_id="new-good", payload={})
    purged.created_at = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
    purged.updated_at = datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
    valid.created_at = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
    valid.updated_at = datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc)
    session.commit()
    path = _write(
        tmp_path,
        "storage/outputs/final_report/XAUUSD/2026-10-11/new-good/final_report.md",
        "NEW GOOD",
    )
    path.touch()

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        result = report_storage_service.get_final_report_latest()

    assert result is not None
    assert result["run_id"] == "new-good"


def test_same_date_valid_report_item_creation_beats_cleanup_updated_at(tmp_path: Path) -> None:
    session = _session()
    purged = upsert_report_item(
        session,
        {
            "report_id": "final_report:old-purged",
            "family": "final_report_markdown",
            "report_type": "final_report",
            "title": "old purged",
            "asset": "XAUUSD",
            "trade_date": "2026-10-11",
            "run_id": "old-purged",
            "data_status": "live",
            "lifecycle_status": "purged",
            "source_refs": [],
            "metadata": {"output_cleanup": _marker(run_id="old-purged")},
        },
    )
    valid = upsert_report_item(
        session,
        {
            "report_id": "final_report:new-good",
            "family": "final_report_markdown",
            "report_type": "final_report",
            "title": "new good",
            "asset": "XAUUSD",
            "trade_date": "2026-10-11",
            "run_id": "new-good",
            "data_status": "live",
            "lifecycle_status": "generated",
            "source_refs": [],
            "metadata": {},
        },
    )
    purged.created_at = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
    purged.updated_at = datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
    valid.created_at = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
    valid.updated_at = datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc)
    session.commit()
    _write(
        tmp_path,
        "storage/outputs/final_report/XAUUSD/2026-10-11/new-good/final_report.md",
        "NEW GOOD",
    )

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        result = report_storage_service.get_final_report_latest()

    assert result is not None
    assert result["run_id"] == "new-good"


def test_strategy_latest_uses_original_creation_time_for_same_date_row() -> None:
    session = _session()
    purged = _upsert_final(
        session,
        trade_date="2026-10-11",
        run_id="newer-purged",
        payload={"output_cleanup": _marker(run_id="newer-purged")},
    )
    valid = _upsert_final(session, trade_date="2026-10-11", run_id="older-good", payload={})
    purged.created_at = datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc)
    purged.updated_at = datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
    valid.created_at = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
    valid.updated_at = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    session.commit()

    with mock.patch(_DB_SESSION_PATCH, lambda: session):
        assert report_strategy_service.get_strategy_card_latest() is None


def test_same_date_filesystem_without_db_time_stays_blocked_after_touch(tmp_path: Path) -> None:
    session = _session()
    purged = _upsert_final(
        session,
        trade_date="2026-10-11",
        run_id="purged-run",
        payload={"output_cleanup": _marker(run_id="purged-run")},
    )
    purged.created_at = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
    purged.updated_at = datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
    session.commit()
    path = _write(
        tmp_path,
        "storage/outputs/final_report/XAUUSD/2026-10-11/old-good/final_report.md",
        "OLD GOOD",
    )
    path.touch()

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        assert report_storage_service.get_final_report_latest() is None


def test_known_final_anchor_survives_missing_agent_output_table(tmp_path: Path) -> None:
    session = _session_without_agent_output()
    purged = _upsert_final(
        session,
        trade_date="2026-10-11",
        run_id="purged-run",
        payload={"output_cleanup": _marker(run_id="purged-run")},
    )
    purged.created_at = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
    session.commit()
    _write(
        tmp_path,
        "storage/outputs/final_report/XAUUSD/2026-10-11/old-good/final_report.md",
        "OLD GOOD",
    )
    _write(
        tmp_path,
        "storage/outputs/strategy_card/XAUUSD/2026-10-11/old-good/strategy_card.json",
        json.dumps({"bias": "bullish", "confidence": 0.8}),
    )

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        assert report_storage_service.get_final_report_latest() is None
        assert report_strategy_service.get_strategy_card_latest() is None


def test_blocked_coordinator_without_report_row_still_fences_old_latest(tmp_path: Path) -> None:
    session = _session()
    session.add(
        AgentOutput(
            snapshot_id="snap-coordinator-purged",
            asset="XAUUSD",
            trade_date=date(2026, 10, 11),
            run_id="coordinator-purged",
            agent_name="coordinator_agent",
            module="coordinator",
            version="1.0",
            status="unavailable",
            bias="unavailable",
            confidence=0.0,
            input_snapshot_ids={},
            source_refs=[],
            key_findings=[],
            risk_points=[],
            watchlist=[],
            invalid_conditions=[],
            summary="",
            payload={"output_cleanup": _marker(run_id="coordinator-purged", snapshot_id="snap-coordinator-purged")},
            payload_sha256="b" * 64,
        )
    )
    session.commit()
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-10/old-good/final_report.md", "OLD GOOD")

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        assert report_storage_service.get_final_report_latest() is None


def test_input_validation_failure_without_coordinator_still_fences_old_latest(tmp_path: Path) -> None:
    session = _session()
    session.add(
        AgentOutput(
            snapshot_id="snap-input-validation-purged",
            asset="XAUUSD",
            trade_date=date(2026, 10, 11),
            run_id="input-validation-purged",
            agent_name="research_input_validation",
            module="input_validation",
            version="1.0",
            status="unavailable",
            bias="unavailable",
            confidence=0.0,
            input_snapshot_ids={},
            source_refs=[],
            key_findings=[],
            risk_points=[],
            watchlist=[],
            invalid_conditions=[],
            summary="",
            payload={
                "output_cleanup": _marker(
                    run_id="input-validation-purged",
                    snapshot_id="snap-input-validation-purged",
                )
            },
            payload_sha256="c" * 64,
        )
    )
    session.commit()
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-10/old-good/final_report.md", "OLD GOOD")

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        assert report_storage_service.get_final_report_latest() is None


def test_input_validation_failure_also_fences_old_strategy_latest(tmp_path: Path) -> None:
    session = _session()
    session.add(
        AgentOutput(
            snapshot_id="snap-input-validation-strategy-purged",
            asset="XAUUSD",
            trade_date=date(2026, 10, 11),
            run_id="input-validation-strategy-purged",
            agent_name="research_input_validation",
            module="input_validation",
            version="1.0",
            status="unavailable",
            bias="unavailable",
            confidence=0.0,
            input_snapshot_ids={},
            source_refs=[],
            key_findings=[],
            risk_points=[],
            watchlist=[],
            invalid_conditions=[],
            summary="",
            payload={"output_cleanup": _marker(run_id="input-validation-strategy-purged")},
            payload_sha256="e" * 64,
        )
    )
    session.commit()
    _write(
        tmp_path,
        "storage/outputs/strategy_card/XAUUSD/2026-10-10/old-good/strategy_card.json",
        json.dumps({"bias": "bullish", "confidence": 0.8}),
    )

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        assert report_strategy_service.get_strategy_card_latest() is None


def test_index_hides_failure_anchor_run_but_keeps_other_history(tmp_path: Path) -> None:
    session = _session()
    for agent_name, run_id, snapshot_id in (
        ("coordinator_agent", "coordinator-purged", "snap-coordinator-purged"),
        ("research_input_validation", "input-validation-purged", "snap-input-validation-purged"),
    ):
        session.add(
            AgentOutput(
                snapshot_id=snapshot_id,
                asset="XAUUSD",
                trade_date=date(2026, 10, 11),
                run_id=run_id,
                agent_name=agent_name,
                module=agent_name,
                version="1.0",
                status="unavailable",
                bias="unavailable",
                confidence=0.0,
                input_snapshot_ids={},
                source_refs=[],
                key_findings=[],
                risk_points=[],
                watchlist=[],
                invalid_conditions=[],
                summary="",
                payload={"output_cleanup": _marker(run_id=run_id, snapshot_id=snapshot_id)},
                payload_sha256="d" * 64,
            )
        )
    session.commit()
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-09/history-good/final_report.md", "HISTORY GOOD")
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-11/coordinator-purged/final_report.md", "PURGED")
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-11/input-validation-purged/final_report.md", "PURGED")

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        result = report_index_service.list_reports_index()

    report_runs = {
        item["run_id"]
        for item in result["reports"]
        if item.get("type") == "final_report"
    }
    assert "history-good" in report_runs
    assert "coordinator-purged" not in report_runs
    assert "input-validation-purged" not in report_runs


def test_report_detail_and_artifact_detail_do_not_revive_tombstoned_rows(tmp_path: Path) -> None:
    session = _session()
    marker = _marker(run_id="run-purged", snapshot_id="snap-purged")
    report_item = upsert_report_item(
        session,
        {
            "report_id": "final_report:run-purged",
            "family": "final_report_markdown",
            "report_type": "final_report",
            "title": "purged",
            "asset": "XAUUSD",
            "trade_date": "2026-10-11",
            "run_id": "run-purged",
            "snapshot_id": "snap-purged",
            "data_status": "live",
            "lifecycle_status": "generated",
            "source_refs": [],
            "metadata": {},
        },
    )
    report_artifact = upsert_report_artifact(
        session,
        {
            "artifact_id": "run-purged:final",
            "report_id": "final_report:run-purged",
            "artifact_type": "analysis_md",
            "file_path": "storage/outputs/final_report/XAUUSD/2026-10-11/run-purged/final_report.md",
            "status": "generated",
            "metadata": {},
        },
    )
    # Insert the rows as ordinary output, then apply the persisted tombstone
    # shape.  The normal upsert path correctly refuses to re-register a
    # purged parent, while this test exercises readers after cleanup.
    report_item.data_status = "live"
    report_item.lifecycle_status = "purged"
    report_item.report_metadata = {"output_cleanup": marker}
    report_artifact.status = "purged"
    report_artifact.artifact_metadata = {"output_cleanup": marker}
    report_artifact.metadata_text = json.dumps({"output_cleanup": marker})
    session.commit()
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-11/run-purged/final_report.md", "PURGED BODY")

    assert get_report_detail(session, "final_report:run-purged") is None
    assert get_report_artifacts(session, "final_report:run-purged") is None
    assert get_report_source(session, "final_report:run-purged") is None
    assert get_report_evidence(session, "final_report:run-purged") is None
    assert get_artifact_detail_response(session, "run-purged:final") is None

    # The row-level lifecycle contract remains authoritative even if an older
    # cleanup record lacks the JSON marker.
    report_item.report_metadata = {}
    report_artifact.status = "generated"
    report_artifact.artifact_metadata = {}
    report_artifact.metadata_text = None
    session.commit()
    assert get_report_detail(session, "final_report:run-purged") is None
    assert get_artifact_detail_response(session, "run-purged:final") is None


def test_purged_artifact_path_alias_does_not_revive_legacy_final(tmp_path: Path) -> None:
    session = _session()
    _upsert_final(session, trade_date="2026-10-11", run_id="legacy-run", payload={})
    report_item = upsert_report_item(
        session,
        {
            "report_id": "registered-parent",
            "family": "final_report_markdown",
            "report_type": "final_report",
            "title": "registered parent",
            "asset": "XAUUSD",
            "trade_date": "2026-10-11",
            "source_refs": [],
            "metadata": {},
        },
    )
    report_artifact = upsert_report_artifact(
        session,
        {
            "artifact_id": "registered-parent:final",
            "report_id": report_item.report_id,
            "artifact_type": "analysis_md",
            "file_path": "storage/outputs/final_report/XAUUSD/2026-10-11/legacy-run/final_report.md",
            "status": "generated",
            "metadata": {},
        },
    )
    report_artifact.status = "purged"
    report_artifact.artifact_metadata = {"output_cleanup": _marker(run_id="legacy-run")}
    session.commit()
    _write(tmp_path, "storage/outputs/final_report/XAUUSD/2026-10-11/legacy-run/final_report.md", "PURGED BODY")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        assert get_report_detail(session, "legacy-run") is None


def test_legacy_basename_alias_rechecked_after_purged_paths_cleared(tmp_path: Path) -> None:
    """A cleared registration path cannot revive a shared residual file by alias."""
    session = _session()
    final = _upsert_final(session, trade_date="2026-10-11", run_id="legacy-run", payload={})
    final.final_report_path = None
    final.strategy_card_json_path = None
    final.strategy_card_md_path = None
    final.run_summary_path = None
    report_item = upsert_report_item(
        session,
        {
            "report_id": "registered-parent",
            "family": "final_report_markdown",
            "report_type": "final_report",
            "title": "registered parent",
            "asset": "XAUUSD",
            "trade_date": "2026-10-11",
            "run_id": "legacy-run",
            "snapshot_id": "legacy-snapshot",
            "source_refs": [],
            "metadata": {},
        },
    )
    report_artifact = upsert_report_artifact(
        session,
        {
            "artifact_id": "registered-parent:final",
            "report_id": report_item.report_id,
            "artifact_type": "analysis_md",
            "file_path": "purged://cleanup-token",
            "status": "purged",
            "metadata": {"output_cleanup": _marker(run_id="legacy-run", snapshot_id="legacy-snapshot")},
        },
    )
    report_artifact.artifact_metadata = {
        "output_cleanup": _marker(run_id="legacy-run", snapshot_id="legacy-snapshot")
    }
    session.commit()
    _write(
        tmp_path,
        "storage/outputs/final_report/XAUUSD/2026-10-11/legacy-run/final_report.md",
        "PURGED SHARED BODY",
    )

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resolved_legacy_detail = report_detail_service._legacy_final_report_detail_from_filesystem("legacy-run")

    assert resolved_legacy_detail is not None
    # The basename alias is intentionally resolved by the legacy adapter in
    # this fixture; the reader must then recheck the resolved run identity.
    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch.object(report_detail_service, "_build_legacy_report_detail", return_value=resolved_legacy_detail),
    ):
        assert get_report_detail(session, "final_report.md") is None


def test_strategy_latest_and_alias_detail_do_not_revive_tombstone(tmp_path: Path) -> None:
    session = _session()
    _upsert_final(
        session,
        trade_date="2026-10-11",
        run_id="strategy-purged",
        payload={"output_cleanup": _marker(run_id="strategy-purged")},
    )
    upsert_report_item(
        session,
        {
            "report_id": "strategy_card:strategy-purged",
            "family": "strategy_card",
            "report_type": "strategy_card",
            "title": "purged strategy",
            "asset": "XAUUSD",
            "trade_date": "2026-10-11",
            "run_id": "strategy-purged",
            "snapshot_id": "snapshot-strategy-purged",
            "data_status": "unavailable",
            "lifecycle_status": "purged",
            "source_refs": [],
            "metadata": {"output_cleanup": _marker(run_id="strategy-purged")},
        },
    )
    session.commit()
    _write(
        tmp_path,
        "storage/outputs/strategy_card/XAUUSD/2026-10-10/old-good/strategy_card.json",
        json.dumps({"bias": "bullish", "confidence": 0.8}),
    )
    _write(
        tmp_path,
        "storage/outputs/strategy_card/XAUUSD/2026-10-11/strategy-purged/strategy_card.json",
        json.dumps({"bias": "bearish", "confidence": 0.9}),
    )

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_DB_SESSION_PATCH, lambda: session),
    ):
        assert report_strategy_service.get_strategy_card_latest() is None
        assert report_strategy_service.get_strategy_card("2026-10-11", "strategy-purged") is None
        assert report_strategy_service.get_strategy_card_by_id("strategy_card:strategy-purged") is None


def test_agent_tombstone_summary_keeps_identity_without_old_body() -> None:
    marker = _marker(run_id="agent-purged", snapshot_id="snap-agent")
    row = SimpleNamespace(
        id="agent-output-1",
        agent_name="coordinator_agent",
        module="coordinator",
        version="1.0",
        run_id="agent-purged",
        snapshot_id="snap-agent",
        status="failed",
        bias="bullish",
        confidence=0.99,
        summary="OLD DIRECTIONAL JUDGEMENT",
        payload={
            "output_cleanup": marker,
            "claims": [{"text": "OLD CLAIM"}],
            "prompt_messages": [{"role": "user", "content": "OLD PROMPT"}],
            "input_payload": {"secret": "OLD INPUT"},
            "llm_raw_output": "OLD RAW",
        },
        key_findings=["OLD FINDING"],
        risk_points=["OLD RISK"],
        watchlist=["OLD WATCH"],
        invalid_conditions=[],
        input_snapshot_ids={"macro": "old"},
        source_refs=[{"source": "old"}],
        llm_model="old-model",
        token_usage={"total": 10},
        llm_elapsed_seconds=1.0,
        prompt_version_id=None,
        prompt_version=None,
        created_at=datetime.now(timezone.utc),
    )

    summary = build_agent_output_summary(row)

    assert summary["agent_output_id"] == "agent-output-1"
    assert summary["status"] == "failed"
    assert summary["purged"] is True
    assert summary["output_cleanup"]["status"] == "purged"
    assert summary["bias"] == "unavailable"
    assert summary["confidence"] == 0.0
    assert "OLD" not in summary["summary"]
    assert summary["key_findings"] == []
    assert summary["artifact_refs"] == []

    inspection = _agent_inspection_item(row, None)
    assert inspection["bias"] == "unavailable"
    assert inspection["prompt"]["messages"] == []
    assert inspection["input"]["payload"] == {"output_cleanup": marker}
    assert inspection["output"]["payload"] == {"output_cleanup": marker}
    assert inspection["output"]["llm_raw_output"] is None
    assert "OLD" not in repr(inspection)
    assert _build_agent_fallback_inputs([row]) == []
