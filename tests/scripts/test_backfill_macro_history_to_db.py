from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.models.analysis import AnalysisSnapshot, ensure_analysis_tables
from scripts.backfill_macro_history_to_db import (
    infer_run_id,
    iter_macro_snapshot_paths,
    load_macro_snapshot_payload,
)


def _write_macro_snapshot(path: Path, *, as_of: str, dxy: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "as_of": as_of,
                "indicators": {
                    "DXY": {"value": dxy},
                    "REAL_10Y": {"value": 2.01},
                },
                "source_refs": [{"symbol": "DXY", "source": "fixture"}],
                "unavailable_symbols": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_iter_macro_snapshot_paths_filters_recent_dates(tmp_path: Path) -> None:
    macro_root = tmp_path / "storage" / "features" / "macro"
    _write_macro_snapshot(macro_root / "2026-05-01" / "macro_snapshot.json", as_of="2026-05-01", dxy=99.1)
    _write_macro_snapshot(macro_root / "2026-06-01" / "run-a" / "macro_snapshot.json", as_of="2026-06-01", dxy=98.9)

    result = iter_macro_snapshot_paths(macro_root, cutoff=__import__("datetime").date(2026, 5, 15))

    assert [p.as_posix() for p in result] == [
        (macro_root / "2026-06-01" / "run-a" / "macro_snapshot.json").as_posix()
    ]


def test_load_macro_snapshot_payload_builds_analysis_snapshot_shape(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "storage" / "features" / "macro" / "2026-06-01" / "run-a" / "macro_snapshot.json"
    _write_macro_snapshot(snapshot_path, as_of="2026-06-01", dxy=98.9)

    payload = load_macro_snapshot_payload(snapshot_path, asset="XAUUSD")

    assert payload["snapshot_id"] == "XAUUSD:2026-06-01:macro:run-a"
    assert payload["trade_date"] == "2026-06-01"
    assert payload["run_id"] == "run-a"
    assert payload["input_snapshot_ids"] == {"macro": "macro:2026-06-01:run-a"}
    assert payload["macro"]["indicators"]["DXY"]["value"] == 98.9
    assert payload["payload"]["timeframe"] == "1d"


def test_infer_run_id_handles_direct_and_nested_paths(tmp_path: Path) -> None:
    direct = tmp_path / "storage" / "features" / "macro" / "2026-06-01" / "macro_snapshot.json"
    nested = tmp_path / "storage" / "features" / "macro" / "2026-06-01" / "run-a" / "macro_snapshot.json"

    assert infer_run_id(direct) == "default"
    assert infer_run_id(nested) == "run-a"


def test_backfill_payload_can_be_upserted_idempotently(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "storage" / "features" / "macro" / "2026-06-01" / "run-a" / "macro_snapshot.json"
    _write_macro_snapshot(snapshot_path, as_of="2026-06-01", dxy=98.9)

    payload = load_macro_snapshot_payload(snapshot_path, asset="XAUUSD")

    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    from database.queries.analysis import upsert_analysis_snapshot

    artifact_path = "storage/features/macro/2026-06-01/run-a/macro_snapshot.json"
    first = upsert_analysis_snapshot(session, payload=payload, artifact_path=artifact_path)
    second = upsert_analysis_snapshot(session, payload=payload, artifact_path=artifact_path)
    session.commit()

    rows = session.scalars(select(AnalysisSnapshot)).all()
    assert first.id == second.id
    assert len(rows) == 1
    assert rows[0].snapshot_id == "XAUUSD:2026-06-01:macro:run-a"
