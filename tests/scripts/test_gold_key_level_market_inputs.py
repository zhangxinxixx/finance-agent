from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_store import (
    persist_gold_daily_close_run,
    verify_gold_daily_close_bundle,
)
from database.models.analysis import MarketCandle, ensure_analysis_tables
from database.models.report import ensure_report_tables
from scripts import gold_key_level_market_inputs as market_inputs
from scripts import run_gold_daily_report as report
from tests.analysis.test_gold_daily_close_store import _bootstrap_pair
from tests.analysis.test_gold_key_level_market_producer import _state
from tests.analysis.test_gold_key_level_policy import _direct_state, _spec
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


CUTOFF = datetime(2026, 7, 30, 1, tzinfo=UTC)
WINDOW_END = CUTOFF - timedelta(hours=1)


def _head(*states):
    return SimpleNamespace(strategy_policy_input=SimpleNamespace(key_levels=tuple(states)))


def _session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'market.db'}")
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory()


def _archive_row(
    root: Path,
    *,
    close_time: datetime,
    close: float = 4490.0,
    retrieved_at: str | None = None,
    quality_status: str = "accepted",
) -> tuple[MarketCandle, Path]:
    open_time = close_time - timedelta(days=1)
    source = "fixture_xauusd_primary_1d"
    raw_path = Path("raw/market/fixture_primary") / f"{open_time.date()}.json"
    archive_path = root / raw_path
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive = {
        "asset": "XAUUSD",
        "timeframe": "1d",
        "source": source,
        "open_time": open_time.isoformat(),
        "close_time": close_time.isoformat(),
        "open": close,
        "high": close + 5,
        "low": close - 5,
        "close": close,
    }
    raw_bytes = json.dumps(archive, sort_keys=True).encode()
    archive_path.write_bytes(raw_bytes)
    source_ref = {
        "provider_symbol": "XAUUSD",
        "instrument_type": "otc_spot_quote_proxy",
        "source_role": "market_primary",
        "quality_status": quality_status,
        "freshness_status": "fresh",
        "alignment_status": "aligned",
        "reference": f"fixture://{open_time.date()}",
        "raw_path": raw_path.as_posix(),
        "retrieved_at": retrieved_at or close_time.isoformat(),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }
    return (
        MarketCandle(
            asset="XAUUSD",
            timeframe="1d",
            open_time=open_time,
            open=close,
            high=close + 5,
            low=close - 5,
            close=close,
            source=source,
            source_ref=source_ref,
            raw_path=raw_path.as_posix(),
        ),
        archive_path,
    )


def _committed_window(tmp_path: Path):
    engine, session = _session(tmp_path)
    older, _ = _archive_row(tmp_path, close_time=WINDOW_END - timedelta(days=1))
    newer, _ = _archive_row(tmp_path, close_time=WINDOW_END)
    session.add_all((older, newer))
    session.commit()
    return engine, session


def _replace_archive(session, root: Path, row: MarketCandle, payload: object) -> None:
    raw_bytes = json.dumps(payload, sort_keys=True).encode()
    (root / row.raw_path).write_bytes(raw_bytes)
    row.source_ref = {**row.source_ref, "sha256": hashlib.sha256(raw_bytes).hexdigest()}
    session.commit()


def test_verified_sqlite_window_produces_break_without_sql_writes(tmp_path: Path) -> None:
    engine, session = _committed_window(tmp_path)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    result = market_inputs.load_gold_key_level_market_inputs(
        head=_head(_state()),
        db=session,
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )

    assert result.summary.status == "ready"
    assert result.summary.queried_row_count == result.summary.verified_row_count == 2
    assert result.summary.produced_event_count == 1
    assert result.summary.reason_codes == ("KEY_LEVEL_BREAK_EVENTS_PRODUCED",)
    assert result.controls_input is not None
    assert result.controls_input.previous_states == (_state(),)
    assert result.controls_input.ordered_events[0].evidence.window_end == WINDOW_END
    assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert len(session.scalars(select(MarketCandle)).all()) == 2


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("tampered", "D1_MARKET_RAW_ARCHIVE_HASH_MISMATCH"),
        ("unsupported", "D1_MARKET_RAW_ARCHIVE_SHAPE_UNSUPPORTED"),
        ("row_mismatch", "D1_MARKET_RAW_ARCHIVE_ROW_MISMATCH"),
        ("identity_mismatch", "D1_MARKET_RAW_ARCHIVE_ROW_MISMATCH"),
        ("quality", "D1_MARKET_QUALITY_NOT_ACCEPTED"),
        ("missing_retrieved", "D1_MARKET_RETRIEVAL_TIME_MISSING"),
        ("naive_retrieved", "D1_MARKET_RETRIEVAL_TIME_MISSING"),
        ("bad_close_time", "D1_MARKET_WINDOW_TIME_INVALID"),
    ],
)
def test_invalid_archive_row_quality_or_time_fails_closed(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    _, session = _committed_window(tmp_path)
    rows = session.scalars(select(MarketCandle).order_by(MarketCandle.open_time)).all()
    target = rows[-1]
    if mutation == "tampered":
        (tmp_path / target.raw_path).write_bytes(b'{"tampered": true}')
    elif mutation == "unsupported":
        path = tmp_path / target.raw_path
        raw = json.dumps({"asset": "XAUUSD", "payload": "not a bar"}).encode()
        path.write_bytes(raw)
        target.source_ref = {**target.source_ref, "sha256": hashlib.sha256(raw).hexdigest()}
        session.commit()
    elif mutation in {"row_mismatch", "identity_mismatch"}:
        path = tmp_path / target.raw_path
        payload = json.loads(path.read_bytes())
        if mutation == "row_mismatch":
            payload["close"] += 1
        else:
            payload["asset"] = "GC"
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        target.source_ref = {**target.source_ref, "sha256": hashlib.sha256(raw).hexdigest()}
        session.commit()
    elif mutation == "quality":
        target.source_ref = {**target.source_ref, "quality_status": "observe"}
        session.commit()
    elif mutation == "missing_retrieved":
        source_ref = dict(target.source_ref)
        source_ref.pop("retrieved_at")
        target.source_ref = source_ref
        session.commit()
    elif mutation == "naive_retrieved":
        target.source_ref = {**target.source_ref, "retrieved_at": "2026-07-30T00:00:00"}
        session.commit()
    else:
        target.source_ref = {**target.source_ref, "close_time": "2026-07-30T00:00:00"}
        session.commit()

    result = market_inputs.load_gold_key_level_market_inputs(
        head=_head(_state()),
        db=session,
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )

    assert result.summary.status == "missing"
    assert reason in result.summary.reason_codes
    assert result.controls_input is not None
    assert result.controls_input.previous_states == (_state(),)
    assert result.controls_input.ordered_events == ()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_d1_evidence",
        "record_timeframe_conflict",
        "wrapper_timeframe_conflict",
        "record_symbol_conflict",
        "nested_instrument_conflict",
        "nested_quality_degraded",
        "wrapper_freshness_degraded",
        "wrapper_alignment_degraded",
    ],
)
def test_raw_archive_declarations_must_all_support_canonical_d1_spot(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, session = _committed_window(tmp_path)
    target = session.scalars(select(MarketCandle).order_by(MarketCandle.open_time)).all()[-1]
    path = tmp_path / target.raw_path
    bar = json.loads(path.read_bytes())

    if mutation == "missing_d1_evidence":
        bar.pop("timeframe")
        bar.pop("close_time")
        payload = bar
    elif mutation == "record_timeframe_conflict":
        payload = {**bar, "interval": "5m"}
    elif mutation == "wrapper_timeframe_conflict":
        payload = {"provider_timeframe": "5m", "bars": [bar]}
    elif mutation == "record_symbol_conflict":
        payload = {**bar, "symbol": "GC=F"}
    elif mutation == "nested_instrument_conflict":
        payload = {**bar, "source_ref": {"instrument_type": "futures_continuous_proxy"}}
    elif mutation == "nested_quality_degraded":
        payload = {**bar, "source_ref": {"quality_status": "observe"}}
    elif mutation == "wrapper_freshness_degraded":
        payload = {"source_ref": {"freshness_status": "stale"}, "bars": [bar]}
    else:
        payload = {"alignment_status": "misaligned", "bars": [bar]}
    _replace_archive(session, tmp_path, target, payload)

    result = market_inputs.load_gold_key_level_market_inputs(
        head=_head(_state()),
        db=session,
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )

    assert result.summary.status == "missing"
    assert result.summary.reason_codes == ("D1_MARKET_RAW_ARCHIVE_ROW_MISMATCH",)
    assert result.controls_input is not None
    assert result.controls_input.previous_states == (_state(),)
    assert result.controls_input.ordered_events == ()


@pytest.mark.parametrize("daily_evidence", ["wrapper_timeframe", "actual_close_time"])
def test_raw_archive_accepts_explicit_daily_wrapper_or_exact_close_time(
    tmp_path: Path,
    daily_evidence: str,
) -> None:
    _, session = _committed_window(tmp_path)
    rows = session.scalars(select(MarketCandle).order_by(MarketCandle.open_time)).all()
    for row in rows:
        bar = json.loads((tmp_path / row.raw_path).read_bytes())
        bar.pop("timeframe")
        if daily_evidence == "wrapper_timeframe":
            bar.pop("close_time")
            payload = {"timeframe": "daily", "bars": [bar]}
        else:
            payload = bar
        _replace_archive(session, tmp_path, row, payload)

    result = market_inputs.load_gold_key_level_market_inputs(
        head=_head(_state()),
        db=session,
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )

    assert result.summary.status == "ready"
    assert result.summary.reason_codes == ("KEY_LEVEL_BREAK_EVENTS_PRODUCED",)
    assert result.controls_input is not None
    assert result.controls_input.ordered_events[0].evidence.window_end == WINDOW_END


@pytest.mark.parametrize("case", ["outside", "symlink"])
def test_outside_or_linked_raw_archive_is_rejected(tmp_path: Path, case: str) -> None:
    _, session = _committed_window(tmp_path)
    target = session.scalars(select(MarketCandle).order_by(MarketCandle.open_time)).all()[-1]
    original = tmp_path / target.raw_path
    if case == "outside":
        outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
        outside.write_bytes(original.read_bytes())
        target.raw_path = str(outside)
        target.source_ref = {**target.source_ref, "raw_path": str(outside)}
        expected = "D1_MARKET_RAW_ARCHIVE_OUTSIDE_STORAGE"
    else:
        referent = tmp_path / "raw/market/fixture_primary/referent.json"
        original.rename(referent)
        original.symlink_to(referent)
        expected = "D1_MARKET_RAW_ARCHIVE_SYMLINK"
    session.commit()

    result = market_inputs.load_gold_key_level_market_inputs(
        head=_head(_state()),
        db=session,
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )

    assert result.summary.reason_codes == (expected,)
    assert result.controls_input is not None
    assert result.controls_input.ordered_events == ()


def test_pending_market_candle_blocks_before_sql_or_flush(tmp_path: Path) -> None:
    engine, session = _committed_window(tmp_path)
    pending, _ = _archive_row(tmp_path, close_time=WINDOW_END + timedelta(days=1))
    session.add(pending)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    result = market_inputs.load_gold_key_level_market_inputs(
        head=_head(_state()),
        db=session,
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )

    assert result.summary.reason_codes == ("D1_MARKET_UNCOMMITTED_DATA",)
    assert result.controls_input is not None
    assert result.controls_input.previous_states == (_state(),)
    assert result.controls_input.ordered_events == ()
    assert statements == []
    assert pending in session.new


def test_no_head_or_no_levels_never_touches_dummy_database(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        market_inputs,
        "list_completed_market_candles",
        lambda *args, **kwargs: pytest.fail("no-level input must not query"),
    )

    no_head = market_inputs.load_gold_key_level_market_inputs(
        head=None,
        db=object(),
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )
    no_levels = market_inputs.load_gold_key_level_market_inputs(
        head=_head(),
        db=object(),
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )

    assert no_head.controls_input is no_levels.controls_input is None
    assert no_head.summary.status == no_levels.summary.status == "not_applicable"
    assert no_head.summary.reason_codes == no_levels.summary.reason_codes == ("NO_PREVIOUS_KEY_LEVEL_STATES",)


def test_missing_database_preserves_verified_predecessor_levels(tmp_path: Path) -> None:
    state = _state()

    result = market_inputs.load_gold_key_level_market_inputs(
        head=_head(state),
        db=None,
        storage_root=tmp_path,
        decision_as_of=CUTOFF,
    )

    assert result.summary.reason_codes == ("D1_MARKET_DATABASE_UNAVAILABLE",)
    assert result.controls_input is not None
    assert result.controls_input.previous_states == (state,)
    assert result.controls_input.ordered_events == ()


def test_cli_actual_sql_reaches_invalidated_verified_bundle_and_idempotent_reread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base_bootstrap_input, _ = _bootstrap_pair()
    state = _direct_state(
        "holding",
        spec=_spec(
            reference_price="4500",
            effective_from=base_bootstrap_input.decision_as_of - timedelta(days=30),
            expires_at=base_bootstrap_input.decision_as_of + timedelta(days=30),
            origin_key="cli-sql-predecessor-support",
        ),
        as_of=base_bootstrap_input.decision_as_of - timedelta(days=2),
    )
    predecessor_input = base_bootstrap_input.model_copy(update={"key_levels": (state,)})
    persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="verified-predecessor",
        loop_input=predecessor_input,
        result=evaluate_gold_daily_close_loop(predecessor_input),
    )

    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    current_support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, predecessor_input.current_feature),
    )
    snapshot_path = (
        tmp_path / "features/snapshots/XAUUSD" / current.as_of.date().isoformat() / "premarket/premarket_snapshot.json"
    )
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "trade_date": current.as_of.date().isoformat(),
                "snapshot_time": current_support.decision_as_of.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    engine, session = _session(tmp_path)
    older, _ = _archive_row(
        tmp_path,
        close_time=current.as_of - timedelta(days=1),
    )
    newer, _ = _archive_row(tmp_path, close_time=current.as_of)
    session.add_all((older, newer))
    session.commit()
    monkeypatch.setattr(report, "prepare_gold_policy_current_feature", lambda **kwargs: current)

    before_bytes = {
        str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    preview = report.run_gold_daily_report(
        trade_date=current.as_of.date().isoformat(),
        storage_root=tmp_path,
        run_id="cli-d1-break",
        dry_run=True,
        db=session,
    )
    after_bytes = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    assert preview["status"] == "dry_run"
    assert preview["formal_key_levels"]["produced_event_count"] == 1, preview
    assert preview["formal_key_level_reasons"] == ["KEY_LEVEL_BREAK_EVENTS_PRODUCED"]
    assert "LEVEL_BREAK_CONFIRMED" in preview["control_reason_codes"]
    assert after_bytes == before_bytes
    assert not session.new and not session.dirty and not session.deleted

    from apps.runtime.premarket_snapshot_authority import PremarketSnapshotAuthority

    monkeypatch.setattr(
        report,
        "resolve_gold_daily_report_premarket_snapshot",
        lambda *args, **kwargs: PremarketSnapshotAuthority(
            status="found",
            reason_code="test_authority",
            snapshot_path=snapshot_path,
            run_id="verified-premarket",
            snapshot_id=current.snapshot_id,
            file_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        ),
    )
    first = report.run_gold_daily_report(
        trade_date=current.as_of.date().isoformat(),
        storage_root=tmp_path,
        run_id="cli-d1-break",
        db=session,
    )
    session.commit()
    bundle = Path(first["report_paths"][0]).parent
    verification = verify_gold_daily_close_bundle(storage_root=tmp_path, bundle_path=bundle)
    second = report.run_gold_daily_report(
        trade_date=current.as_of.date().isoformat(),
        storage_root=tmp_path,
        run_id="cli-d1-break",
        db=session,
    )

    assert first["status"] == "completed", first
    transition = json.loads((bundle / "state_transition_policy_decision.v1.json").read_text())
    assert transition["action"] == "invalidate"
    assert transition["evidence"]["delta_kind"] == "hard_invalidation"
    assert transition["evidence"]["rule_code"] == "CONFIRMED_SUPPORT_BREAK"
    assert verification.status == "valid"
    assert second == first
    engine.dispose()
