from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import main as api_main
from database.models.analysis import AnalysisBase
from database.models.cme import CmeOptionRow, CmeRawFile
from database.models.task import Base


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
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
            source="test",
            section="options",
            raw_path=f"{date}.pdf",
            sha256=f"sha-{date}",
            report_date=date,
            bytes=1,
            retrieved_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
        session.add(raw)
        session.flush()
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


def _write_archived_rows(root: Path, trade_date: str, values: list[tuple[str, str, int]]) -> None:
    path = root / f"storage/parsed/cme/{trade_date}/parse-run/cme_parse_result.json"
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
            return_value={"candles": [{"close": 4130.0, "time": "2026-07-15T12:00:00Z", "source": "canonical"}]},
        ),
    ):
        decision = api_main.api_options_decision(date="2026-07-15", lookback_days=5, db=session)
        snapshot = api_main.api_options_snapshot(date="2026-07-15", db=session)

    assert decision["schema_version"] == "cme_options_decision.v1"
    assert decision["gamma_summary"]["regime"] == "negative_gamma"
    assert decision["oi_summary"]["total"]["current"] == 328499.0
    assert decision["roll_summary"]["items"][0]["far_put_delta"] == 834.0
    assert snapshot["trade_date"] == "2026-07-15"
    paths = {route.path for route in api_main.app.routes}
    assert "/api/options/decision" in paths


def test_options_decision_falls_back_to_archived_parse_rows_when_database_has_gap(tmp_path: Path) -> None:
    for trade_date in ("2026-07-15", "2026-07-14"):
        snapshot = _snapshot()
        snapshot["trade_date"] = trade_date
        path = tmp_path / f"storage/outputs/cme/{trade_date}/run-1/options_analysis.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(snapshot), encoding="utf-8")
    _write_archived_rows(
        tmp_path,
        "2026-07-15",
        [("AUG26", "CALL", 110000), ("AUG26", "PUT", 105236), ("SEP26", "CALL", 55000), ("SEP26", "PUT", 58263)],
    )
    _write_archived_rows(
        tmp_path,
        "2026-07-14",
        [("AUG26", "CALL", 110100), ("AUG26", "PUT", 105390), ("SEP26", "CALL", 54537), ("SEP26", "PUT", 57429)],
    )
    session = _session()

    with (
        mock.patch("apps.api.data_service._PROJECT_ROOT", tmp_path),
        mock.patch(
            "apps.api.services.options_service.get_market_candles",
            return_value={"candles": [{"close": 4130.0, "time": "2026-07-15T12:00:00Z", "source": "canonical"}]},
        ),
    ):
        decision = api_main.api_options_decision(date="2026-07-15", lookback_days=5, db=session)

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
