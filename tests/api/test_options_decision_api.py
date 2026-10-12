from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import main as api_main
from apps.api.data_service import get_options_snapshot
from database.models.analysis import AnalysisBase
from database.models.cme import CmeOptionRow, CmeRawFile, CmeParseRun
from apps.data_layer.warehouse_sources import load_source_warehouse
from tests.helpers.warehouse import create_collection_schema
from database.models.task import Base, TaskRun, TaskStatus


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    create_collection_schema(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _snapshot() -> dict:
    return {
        "trade_date": "2026-07-15",
        "data_source": {"product": "OG", "status": "FINAL", "expiries": ["AUG26", "SEP26"]},
        "parameters": {"report_p0": 4140.0, "model_f": {"AUG26": 4141.0, "SEP26": 4148.0}},
        "gex": {
            "netgex_aggregate": {
                "net_gex": -1.0,
                "gamma_zero": {"price": 4144.7, "method": "interpolated"},
                "price_grid": [4100, 4125, 4150],
            }
        },
        "support_resistance": {
            "support": [{"strike": 4100, "wall_score": 8.0}],
            "resistance": [{"strike": 4200, "wall_score": 7.0}],
        },
        "source_trace": [{"source_ref": "cme://bulletin"}],
    }


def _seed_rows(session: Session) -> None:
    for date, values in {
        "2026-07-15": [
            ("AUG26", "CALL", 110000),
            ("AUG26", "PUT", 105236),
            ("SEP26", "CALL", 55000),
            ("SEP26", "PUT", 58263),
            ("OCT26", "CALL", 999999),
        ],
        "2026-07-14": [
            ("AUG26", "CALL", 110100),
            ("AUG26", "PUT", 105390),
            ("SEP26", "CALL", 54537),
            ("SEP26", "PUT", 57429),
            ("OCT26", "CALL", 888888),
        ],
        "2026-07-13": [("AUG26", "CALL", 110050), ("OCT26", "CALL", 999999)],
    }.items():
        raw = CmeRawFile(
            source="cme_daily_bulletin",
            source_url="https://www.cmegroup.com/bulletin.pdf",
            section="options",
            raw_path=f"{date}.pdf",
            sha256=hashlib.sha256(date.encode()).hexdigest(),
            report_date=date,
            bytes=1,
            retrieved_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
        session.add(raw)
        session.flush()
        session.add(CmeParseRun(raw_file_id=raw.id, status="FINAL", created_at=raw.retrieved_at))
        for index, (expiry, option_type, oi) in enumerate(values):
            session.add(
                CmeOptionRow(
                    raw_file_id=raw.id,
                    trade_date=date,
                    report_date=date,
                    version_type="FINAL",
                    product_code="OG",
                    expiry=expiry,
                    strike=4100 + index * 25,
                    option_type=option_type,
                    open_interest=oi,
                )
            )
    session.commit()
    assert load_source_warehouse(session, "cme-options", dry_run=False)["rejected"] == 0
    session.commit()


def _write_archived_rows(root: Path, trade_date: str, values: list[tuple[str, str, int]], *, flat: bool = False) -> None:
    filename = f"OG_ALL_detail_{trade_date.replace('-', '')}_FINAL.json" if flat else "parse-run/cme_parse_result.json"
    path = root / f"storage/parsed/cme/{trade_date}/{filename}"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "status": "FINAL",
                "trade_date": trade_date,
                "product": "OG",
                "detail_rows": [
                    {
                        "trade_date": trade_date,
                        "product": "OG",
                        "expiry": expiry,
                        "strike": 4100 + index * 25,
                        "option_type": option_type,
                        "open_interest": oi,
                    }
                    for index, (expiry, option_type, oi) in enumerate(values)
                ],
            }
        ),
        encoding="utf-8",
    )


def test_options_decision_route_reads_local_inputs_and_keeps_snapshot_route(tmp_path: Path) -> None:
    path = tmp_path / "storage/outputs/cme/2026-07-15/run-1/options_analysis.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    session = _session()
    _seed_rows(session)
    with (
        mock.patch("apps.api.data_service._PROJECT_ROOT", tmp_path),
        mock.patch(
            "apps.api.services.options_service.get_market_candles",
            return_value={
                "candles": [{"close": 4130.0, "time": datetime.now(timezone.utc).isoformat(), "source": "canonical"}],
                "coverage": {"degraded": False},
            },
        ),
    ):
        decision = api_main.api_options_decision(date="2026-07-15", lookback_days=5, db=session)
        snapshot = api_main.api_options_snapshot(date="2026-07-15", db=session)

    assert decision["schema_version"] == "cme_options_decision.v1"
    # The service exposes XAUUSD spot without a validated GC futures basis;
    # the API must preserve the GC structure while failing closed for live
    # regime and intraday execution fields.
    assert decision["gamma_summary"]["regime"] == "unavailable"
    assert decision["intraday_strategy"]["status"] == "unavailable"
    assert decision["intraday_strategy"]["long_setup"] is None
    assert decision["price_context"]["basis_status"] == "unvalidated"
    assert decision["oi_summary"]["total"]["current"] == 328499.0
    assert decision["roll_summary"]["items"][0]["far_put_delta"] == 834.0
    assert snapshot["trade_date"] == "2026-07-15"
    paths = {route.path for route in api_main.app.routes}
    assert "/api/options/decision" in paths


@pytest.mark.parametrize("archive_layout", ["run", "flat"])
def test_internal_options_processing_keeps_archive_replay_but_page_does_not(tmp_path: Path, archive_layout: str) -> None:
    for trade_date in ("2026-07-15", "2026-07-14"):
        snapshot = _snapshot()
        snapshot["trade_date"] = trade_date
        # Previous-day parsed rows remain valid comparison evidence even if
        # that day's derived options report was never rendered.
        if trade_date == "2026-07-15":
            path = tmp_path / f"storage/outputs/cme/{trade_date}/run-1/options_analysis.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(snapshot), encoding="utf-8")
    _write_archived_rows(
        tmp_path,
        "2026-07-15",
        [("AUG26", "CALL", 110000), ("AUG26", "PUT", 105236), ("SEP26", "CALL", 55000), ("SEP26", "PUT", 58263)],
        flat=archive_layout == "flat",
    )
    _write_archived_rows(
        tmp_path,
        "2026-07-14",
        [("AUG26", "CALL", 110100), ("AUG26", "PUT", 105390), ("SEP26", "CALL", 54537), ("SEP26", "PUT", 57429)],
        flat=archive_layout == "flat",
    )
    session = _session()

    with (
        mock.patch("apps.api.data_service._PROJECT_ROOT", tmp_path),
        mock.patch("apps.api.services.options_service.list_options_report_dates", side_effect=AssertionError("OI history must use row sources")),
        mock.patch(
            "apps.api.services.options_service.get_market_candles",
            return_value={
                "candles": [{"close": 4130.0, "time": datetime.now(timezone.utc).isoformat(), "source": "canonical"}],
                "coverage": {"degraded": False},
            },
        ),
    ):
        page = api_main.api_options_decision(date="2026-07-15", lookback_days=5, db=session)
        assert not any(ref.get("source_kind") == "archived_parse" for ref in page["source_refs"])
        assert page["oi_summary"]["total"]["previous"] is None
        from apps.api.services.options_service import get_options_decision

        decision = get_options_decision("2026-07-15", lookback_days=5, db=session, allow_archived_parse=True)

        from apps.api.services.gold_workspace_service import _read_options

        with mock.patch("apps.api.services._storage._try_db_session", return_value=session):
            workspace_options = _read_options()
        assert not any(ref.get("source_kind") == "archived_parse" for ref in workspace_options["source_refs"])
        assert workspace_options["oi_summary"]["total"]["previous"] is None

    assert decision["oi_summary"]["total"] == {
        "current": 328499.0,
        "previous": 327456.0,
        "delta": 1043.0,
        "pct_change": 1043.0 / 327456.0 * 100,
    }
    assert decision["meta"]["previous_trade_date"] == "2026-07-14"
    archive_refs = [ref for ref in decision["source_refs"] if ref.get("source_kind") == "archived_parse"]
    assert {ref["trade_date"] for ref in archive_refs} == {"2026-07-14", "2026-07-15"}
    assert all(ref["version_type"] == "FINAL" for ref in archive_refs)


def test_options_snapshot_selects_latest_verified_task_run_instead_of_uuid_order(tmp_path: Path) -> None:
    trade_date = "2026-07-15"
    older_uuid = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    newer_uuid = "11111111-1111-1111-1111-111111111111"
    older_path = tmp_path / f"storage/features/cme/{trade_date}/{older_uuid}/options_analysis.json"
    newer_path = tmp_path / f"storage/features/cme/{trade_date}/{newer_uuid}/options_analysis.json"
    older_path.parent.mkdir(parents=True)
    newer_path.parent.mkdir(parents=True)
    older_payload = _snapshot() | {
        "generated_at": "2026-07-15T23:00:00+00:00",
        "intent": {"type": "uuid-would-win"},
    }
    newer_payload = _snapshot() | {
        "generated_at": "2026-07-15T18:00:00+00:00",
        "intent": {"type": "verified-latest"},
    }
    older_path.write_text(json.dumps(older_payload), encoding="utf-8")
    newer_path.write_text(json.dumps(newer_payload), encoding="utf-8")

    session = _session()
    # SQLite's emulated PostgreSQL UUID type has an insertmanyvalues bug for
    # this model, so flush each registry row separately in the fixture.
    for run in (
        TaskRun(
            id=UUID(older_uuid),
            name="cme-options-old",
            task_type="premarket",
            status=TaskStatus.success,
            trade_date=trade_date,
            started_at=datetime(2026, 7, 15, 17, 55, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc),
        ),
        TaskRun(
            id=UUID(newer_uuid),
            name="cme-options-new",
            task_type="premarket",
            status=TaskStatus.success,
            trade_date=trade_date,
            started_at=datetime(2026, 7, 15, 18, 55, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc),
        ),
    ):
        session.add(run)
        session.flush()
    session.commit()

    with mock.patch("apps.api.data_service._PROJECT_ROOT", tmp_path):
        snapshot = get_options_snapshot(trade_date, db=session)

    assert snapshot is not None
    assert snapshot["run_id"] == newer_uuid
    assert snapshot["intent"]["type"] == "verified-latest"


@pytest.mark.parametrize(
    ("output_generated_at", "expected_run_id"),
    [
        ("2026-07-15T19:00:00+00:00", "features-run"),
        ("2026-07-15T19:00:01+00:00", "outputs-run"),
    ],
)
def test_options_snapshot_preserves_features_on_time_tie_but_selects_newer_outputs(
    tmp_path: Path, output_generated_at: str, expected_run_id: str
) -> None:
    trade_date = "2026-07-15"
    for layer, run_id, generated_at in (
        ("features", "features-run", "2026-07-15T19:00:00+00:00"),
        ("outputs", "outputs-run", output_generated_at),
    ):
        path = tmp_path / f"storage/{layer}/cme/{trade_date}/{run_id}/options_analysis.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(_snapshot() | {"generated_at": generated_at}), encoding="utf-8")

    with mock.patch("apps.api.data_service._PROJECT_ROOT", tmp_path):
        snapshot = get_options_snapshot(trade_date)

    assert snapshot is not None
    assert snapshot["run_id"] == expected_run_id


def test_latest_options_does_not_parse_old_research_when_current_bulletin_missing(tmp_path: Path) -> None:
    recent = tmp_path / "storage/features/snapshots/XAUUSD/2026-07-16/recent/premarket_snapshot.json"
    old = tmp_path / "storage/features/snapshots/XAUUSD/2026-06-01/old/premarket_snapshot.json"
    output = tmp_path / "storage/features/cme/2026-07-15/options-run/options_analysis.json"
    for path in (recent, old, output):
        path.parent.mkdir(parents=True)
    recent.write_text(json.dumps({"options": {"status": "available", "data": _snapshot()}}))
    old.write_text(json.dumps({"options": {"status": "unavailable"}}))
    output.write_text(json.dumps(_snapshot()))
    reads: list[Path] = []
    read_text = Path.read_text

    def track_read(path: Path, *args, **kwargs):
        reads.append(path)
        return read_text(path, *args, **kwargs)

    with (
        mock.patch("apps.api.data_service._PROJECT_ROOT", tmp_path),
        mock.patch("apps.api.services.options_service._get_t1_trade_date", return_value="2026-07-17"),
        mock.patch.object(Path, "read_text", track_read),
    ):
        snapshot = get_options_snapshot()

    assert snapshot is not None
    assert snapshot["trade_date"] == "2026-07-15"
    assert snapshot["run_id"] == "options-run"
    assert old not in reads
    assert reads.count(recent) == 1


def test_options_research_fallback_keeps_cross_date_data_and_rereads_next_request(tmp_path: Path) -> None:
    path = tmp_path / "storage/features/snapshots/XAUUSD/2026-07-16/research/premarket_snapshot.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"options": {"status": "available", "data": _snapshot()}}))
    with mock.patch("apps.api.data_service._PROJECT_ROOT", tmp_path):
        snapshot = get_options_snapshot("2026-07-15")
        assert snapshot is not None
        assert snapshot["trade_date"] == "2026-07-15"
        assert snapshot["run_id"] == "research"
        path.write_text(json.dumps({"options": {"status": "unavailable"}}))
        assert get_options_snapshot("2026-07-15") is None
