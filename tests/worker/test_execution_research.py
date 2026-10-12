import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest

from apps.features.research.tradingview_execution import merge_tradingview_execution


ANALYSIS_DATE = "2026-09-28"
BASE_TIME = "2026-09-28T10:31:30+00:00"
FIRST_REFRESH_TIME = "2026-09-28T10:56:30+00:00"
SECOND_REFRESH_TIME = "2026-09-28T11:12:30+00:00"


@pytest.fixture
def warehouse_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from tests.helpers.warehouse import create_collection_schema
    engine = create_engine('sqlite://')
    create_collection_schema(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _series(*, seconds: int, retrieved_at: str, final_open: str, raw_path: str) -> dict:
    end = datetime.fromisoformat(final_open)
    bars = []
    for index in range(12):
        opened = end - timedelta(seconds=seconds * (11 - index))
        bars.append(
            {
                "time": opened.isoformat(),
                "open": 100 + index,
                "high": 102 + index,
                "low": 99 + index,
                "close": 101 + index,
            }
        )
    return {
        "ticker": "OANDA:XAUUSD",
        "status": "available",
        "resolution_seconds": seconds,
        "delay_seconds": 0,
        "retrieved_at": retrieved_at,
        "bars": bars,
        "continuous_contract": False,
        "metadata": {"exchange": "OANDA", "instrument_type": "commodity", "currency": "USD",
                     "series_completed": True, "provider_delay_seconds": 0},
        "source_refs": [
            {
                "source": "tradingview_chart",
                "ticker": "OANDA:XAUUSD",
                "raw_path": raw_path,
                "retrieved_at": retrieved_at,
            }
        ],
    }


def _initial_execution() -> dict:
    rows = [
        _series(
            seconds=900,
            retrieved_at=BASE_TIME,
            final_open="2026-09-28T10:30:00+00:00",
            raw_path="raw/initial-15m.json",
        ),
        _series(
            seconds=3600,
            retrieved_at=BASE_TIME,
            final_open="2026-09-28T10:15:00+00:00",
            raw_path="raw/initial-1h.json",
        ),
        _series(
            seconds=14400,
            retrieved_at=BASE_TIME,
            final_open="2026-09-28T09:00:00+00:00",
            raw_path="raw/initial-4h.json",
        ),
    ]
    return merge_tradingview_execution(
        {}, rows, as_of=BASE_TIME, analysis_date=ANALYSIS_DATE
    )


def _snapshot() -> dict:
    return {
        "run_id": "refresh-regression",
        "trade_date": ANALYSIS_DATE,
        "snapshot_time": BASE_TIME,
        "daily_research": {"execution_timeframes": _initial_execution()},
        "input_snapshot_ids": {},
        "source_refs": [
            {
                "source": "tradingview_chart",
                "ticker": "OANDA:XAUUSD",
                "raw_path": "raw/prior-observation.json",
                "retrieved_at": BASE_TIME,
            }
        ],
    }


class _Clock:
    current = FIRST_REFRESH_TIME

    @classmethod
    def now(cls, tz: object) -> datetime:
        return datetime.fromisoformat(cls.current)


def _collector_for(clock: type[_Clock], *, tag: str):
    def collector(**kwargs):
        assert kwargs["resolution"] == "15"
        row = _series(
            seconds=900,
            retrieved_at=clock.current,
            final_open=(
                "2026-09-28T10:45:00+00:00"
                if tag == "first"
                else "2026-09-28T11:00:00+00:00"
            ),
            raw_path=f"raw/refresh-{tag}.json",
        )
        return {
            "series": [row],
            "source_refs": row["source_refs"],
            "parsed_path": f"parsed/refresh-{tag}.json",
        }

    return collector


def _artifact_path(storage: Path, result: dict) -> Path:
    return storage / result["input_snapshot_ids"]["execution_refresh"]


def test_refresh_versions_distinct_observations_and_preserves_lineage(monkeypatch, tmp_path, warehouse_db):
    import apps.worker.execution_research as module

    monkeypatch.setattr(module, "datetime", _Clock)
    snapshot = _snapshot()

    _Clock.current = FIRST_REFRESH_TIME
    first = module.refresh_execution_snapshot(
        snapshot,
        storage_root=tmp_path,
        collector=_collector_for(_Clock, tag="first"),
        db_session=warehouse_db,
    )
    first_path = _artifact_path(tmp_path, first)
    first_bytes = first_path.read_bytes()

    _Clock.current = SECOND_REFRESH_TIME
    second = module.refresh_execution_snapshot(
        first,
        storage_root=tmp_path,
        collector=_collector_for(_Clock, tag="second"),
        db_session=warehouse_db,
    )
    second_path = _artifact_path(tmp_path, second)

    assert first_path != second_path
    assert first_path.name == f"refresh-{hashlib.sha256(first_bytes).hexdigest()}.json"
    assert second_path.name == f"refresh-{hashlib.sha256(second_path.read_bytes()).hexdigest()}.json"
    assert first_path.is_file()
    assert second_path.is_file()
    assert first_path.read_bytes() == first_bytes
    second_payload = json.loads(second_path.read_text())
    assert second_payload["execution_timeframes"] == second["daily_research"]["execution_timeframes"]

    refs = second["source_refs"]
    assert any(ref["raw_path"] == "raw/prior-observation.json" for ref in refs)
    assert any(ref["raw_path"] == "raw/refresh-first.json" for ref in refs)
    assert any(ref["raw_path"] == "raw/refresh-second.json" for ref in refs)
    assert second["input_snapshot_ids"]["execution_refresh"] == second_path.relative_to(tmp_path).as_posix()
    assert second_payload["source_refs"][0]["raw_path"] == "raw/refresh-second.json"


def test_refresh_identical_write_is_idempotent_and_legacy_artifact_is_untouched(
    monkeypatch, tmp_path, warehouse_db
):
    import apps.worker.execution_research as module

    monkeypatch.setattr(module, "datetime", _Clock)
    snapshot = _snapshot()
    legacy_path = (
        tmp_path
        / "features"
        / "research_execution"
        / ANALYSIS_DATE
        / snapshot["run_id"]
        / "refresh.json"
    )
    legacy_path.parent.mkdir(parents=True)
    legacy_bytes = b'{"legacy": true}\n'
    legacy_path.write_bytes(legacy_bytes)

    _Clock.current = FIRST_REFRESH_TIME
    collector = _collector_for(_Clock, tag="first")
    first = module.refresh_execution_snapshot(snapshot, storage_root=tmp_path, collector=collector, db_session=warehouse_db)
    repeated = module.refresh_execution_snapshot(snapshot, storage_root=tmp_path, collector=collector, db_session=warehouse_db)

    artifact = _artifact_path(tmp_path, first)
    repeated_artifact = _artifact_path(tmp_path, repeated)
    artifact_bytes = artifact.read_bytes()
    assert artifact == repeated_artifact
    assert repeated_artifact.read_bytes() == artifact_bytes
    assert list(artifact.parent.glob("refresh-*.json")) == [artifact]
    assert legacy_path.read_bytes() == legacy_bytes
