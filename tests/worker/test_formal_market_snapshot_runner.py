from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from apps.features.market_data.formal_snapshot_loader import FormalSnapshotBundle
from apps.features.market_data.formal_snapshots import (
    build_market_context_snapshot,
    build_market_price_snapshot,
    build_oil_snapshot,
)
from apps.worker.runner import _persist_analysis_snapshot


def _bar(*, asset: str, timeframe: str, source: str, source_ref: dict, open_time: datetime) -> dict:
    duration = timedelta(minutes=5) if timeframe == "5m" else timedelta(days=1)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "source": source,
        "source_ref": source_ref,
        "open_time": open_time,
        "close_time": open_time + duration,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "retrieved_at": (open_time + duration).isoformat(),
        "raw_path": f"raw/{asset}/{source}.json",
    }


def _ready_bundle(as_of: datetime) -> FormalSnapshotBundle:
    market_prices = build_market_price_snapshot(
        candidates=[
            _bar(
                asset="XAUUSD",
                timeframe="5m",
                source="jin10_mcp_derived_5m",
                source_ref={
                    "provider_symbol": "XAUUSD",
                    "instrument_type": "otc_spot_quote_proxy",
                    "source_role": "market_primary",
                    "reference": "fixture://xau",
                },
                open_time=as_of - timedelta(minutes=10),
            ),
            _bar(
                asset="GC",
                timeframe="1d",
                source="yahoo_finance_gc_f",
                source_ref={
                    "provider_symbol": "GC=F",
                    "instrument_type": "futures_continuous_proxy",
                    "source_role": "futures_continuous_proxy",
                    "reference": "fixture://gc",
                },
                open_time=as_of - timedelta(days=2),
            ),
        ],
        as_of=as_of,
    )
    oil = build_oil_snapshot(
        candidates=[
            _bar(
                asset=asset,
                timeframe="1d",
                source="ice_settlement",
                source_ref={
                    "provider_symbol": asset,
                    "instrument_type": "futures_settlement",
                    "source_role": "oil_primary",
                    "reference": f"fixture://{asset.lower()}",
                },
                open_time=as_of - timedelta(days=2),
            )
            for asset in ("WTI", "BRENT")
        ],
        as_of=as_of,
    )
    market_context = build_market_context_snapshot(
        candidates=[
            _bar(
                asset=asset,
                timeframe="1d",
                source=source,
                source_ref={
                    "provider_symbol": symbol,
                    "instrument_type": instrument_type,
                    "source_role": role,
                    "reference": f"fixture://{asset.lower()}",
                },
                open_time=as_of - timedelta(days=2),
            )
            for asset, source, symbol, instrument_type, role in (
                ("DXY", "yahoo_finance_dx_y_nyb", "DX-Y.NYB", "index", "market_primary"),
                ("VIX", "yahoo_finance_vix", "^VIX", "volatility_index", "market_primary"),
            )
        ],
        as_of=as_of,
    )
    return FormalSnapshotBundle(
        market_prices=market_prices,
        oil=oil,
        as_of=as_of,
        market_context=market_context,
    )


def _states() -> tuple[SimpleNamespace, SimpleNamespace]:
    return (
        SimpleNamespace(
            snapshot_dict={"as_of": "2026-07-20", "indicators": {"US10Y": {"value": 4.2}}},
            all_source_refs=[],
            all_points=[],
            step_summaries={},
        ),
        SimpleNamespace(snapshot_dict={"trade_date": "2026-07-20"}),
    )


def test_persist_snapshot_passes_loaded_formal_models_and_one_run_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import apps.worker.runner as runner

    macro_state, cme_state = _states()
    run_time = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    as_of = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    session = object()
    captured = {}
    bundle = _ready_bundle(as_of)

    monkeypatch.setattr(runner, "resolve_formal_snapshot_as_of", lambda **kwargs: as_of)
    monkeypatch.setattr(
        runner,
        "load_formal_market_snapshots",
        lambda received_session, *, as_of: captured.update(session=received_session, as_of=as_of) or bundle,
    )

    path, snapshot = _persist_analysis_snapshot(
        tmp_path,
        "formal-success",
        macro_state,
        cme_state,
        analysis_context_date="2026-07-20",
        db_session=session,
        run_time=run_time,
    )

    assert path.exists()
    assert captured == {"session": session, "as_of": as_of}
    assert snapshot["snapshot_time"] == run_time.isoformat()
    assert snapshot["market_prices"]["data"]["readiness"] == "ready"
    assert snapshot["market_context"]["data"]["readiness"] == "observe"
    assert snapshot["oil"]["data"]["readiness"] == "ready"
    assert macro_state.step_summaries["formal_market_snapshots"] == {
        "step": "formal_market_snapshots",
        "status": "success",
        "as_of": as_of.isoformat(),
        "market_prices_readiness": "ready",
        "market_context_readiness": "observe",
        "oil_readiness": "ready",
        "error": None,
    }


def test_persist_snapshot_loader_failure_writes_blocked_formal_sections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import apps.worker.runner as runner

    macro_state, cme_state = _states()
    run_time = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(runner, "resolve_formal_snapshot_as_of", lambda **_kwargs: run_time)
    monkeypatch.setattr(
        runner,
        "load_formal_market_snapshots",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database password=secret")),
    )

    path, snapshot = _persist_analysis_snapshot(
        tmp_path,
        "formal-failure",
        macro_state,
        cme_state,
        analysis_context_date="2026-07-20",
        db_session=object(),
        run_time=run_time,
    )

    assert path.exists()
    assert snapshot["market_prices"]["data"]["readiness"] == "blocked"
    assert snapshot["oil"]["data"]["readiness"] == "blocked"
    summary = macro_state.step_summaries["formal_market_snapshots"]
    assert summary["status"] == "degraded"
    assert summary["error"] == "RuntimeError: formal market snapshot load failed"
    assert "secret" not in summary["error"]


def test_persist_snapshot_future_trade_date_degrades_without_stopping_write(tmp_path: Path) -> None:
    macro_state, cme_state = _states()
    run_time = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

    path, snapshot = _persist_analysis_snapshot(
        tmp_path,
        "formal-future-date",
        macro_state,
        cme_state,
        analysis_context_date="2026-07-21",
        db_session=object(),
        run_time=run_time,
    )

    assert path.exists()
    assert snapshot["trade_date"] == "2026-07-21"
    assert snapshot["market_prices"]["data"]["readiness"] == "blocked"
    assert macro_state.step_summaries["formal_market_snapshots"]["status"] == "degraded"
    assert macro_state.step_summaries["formal_market_snapshots"]["error"].startswith("ValueError:")


def test_persist_snapshot_materializes_formal_cot_from_macro_points(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import apps.worker.runner as runner

    macro_state, cme_state = _states()
    run_time = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    macro_state.all_points = [
        SimpleNamespace(
            to_dict=lambda: {
                "symbol": "COT_GOLD_noncomm_net",
                "date": "2026-07-14",
                "value": 116_161.0,
                "source": "cftc",
                "source_url": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip",
                "retrieved_at": "2026-07-17T20:00:00Z",
                "raw_path": "raw/positioning/2026-07-17/cot_gold.json",
            }
        )
    ]
    bundle = _ready_bundle(run_time)
    monkeypatch.setattr(runner, "resolve_formal_snapshot_as_of", lambda **_kwargs: run_time)
    monkeypatch.setattr(runner, "load_formal_market_snapshots", lambda *_args, **_kwargs: bundle)

    _, snapshot = _persist_analysis_snapshot(
        tmp_path,
        "formal-cot-runtime",
        macro_state,
        cme_state,
        analysis_context_date="2026-07-20",
        db_session=object(),
        run_time=run_time,
    )

    assert snapshot["cot"]["data"]["readiness"] == "ready"
    assert snapshot["cot"]["data"]["managed_money_net"]["value"] == 116_161.0
    assert snapshot["input_snapshot_ids"]["cot"].startswith("cot_snapshot.v1:")
