from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from sqlalchemy import JSON, LargeBinary, PickleType, create_engine, event, func, select
from sqlalchemy.orm import Session

from apps.data_layer.research_market_warehouse import (
    ResearchMarketWarehouseError,
    materialize_research_market,
    read_research_market,
)
from apps.features.research.cross_asset import build_cross_asset_features
from apps.features.research.tradingview_execution import merge_tradingview_execution
from apps.parsers.market.tradingview import CORE_INSTRUMENTS, parse_tradingview
from apps.parsers.market.tradingview_chart import parse_tradingview_chart
from database.models.task import Base, TaskRun, TaskStep
from database.models.warehouse_research_market import (
    RESEARCH_MARKET_TABLES,
    ResearchMarketBar,
    ResearchMarketBatch,
    ResearchMarketChartSeries,
    ResearchMarketScannerQuote,
)

FIXTURES = Path("tests/fixtures/research")
AS_OF = "2026-09-17T11:26:15+00:00"


def _wire(messages):
    payloads = [json.dumps(message, separators=(",", ":")) for message in messages]
    return ["".join(f"~m~{len(payload.encode('utf-8'))}~m~{payload}" for payload in payloads)]


def _source_ref(source, ticker=None, raw_path="raw/research.json", retrieved_at=AS_OF):
    result = {
        "source": source,
        "source_url": "https://example.invalid/research",
        "raw_path": raw_path,
        "retrieved_at": retrieved_at,
        "source_tier": "secondary",
        "evidence_scope": "provider_observation",
    }
    if ticker:
        result["ticker"] = ticker
    return result


def _scanner():
    payload = json.loads((FIXTURES / "tradingview_cross_asset.json").read_text(encoding="utf-8"))
    ref = _source_ref("tradingview_cross_asset", raw_path="raw/scanner.json")
    return parse_tradingview(payload, retrieved_at=AS_OF, source_ref=ref, instruments=CORE_INSTRUMENTS)


def _chart(fixture_name="tradingview_chart_protocol.json"):
    fixture = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    ticker, resolution = fixture["ticker"], fixture["resolution"]
    retrieved_at = fixture.get("retrieved_at", AS_OF)
    ref = _source_ref(
        "tradingview_chart", ticker=ticker, raw_path=f"raw/{ticker.replace(':', '_')}.json", retrieved_at=retrieved_at
    )
    return parse_tradingview_chart(
        {**fixture, "frames": _wire(fixture["messages"])},
        ticker=ticker,
        resolution=resolution,
        retrieved_at=retrieved_at,
        source_ref=ref,
    )


def _observed():
    scanner = _scanner()
    chart = _chart()
    gold = _chart("tradingview_gold_4h.json")
    return {
        **scanner,
        "parsed_path": "parsed/scanner.json",
        "chart_parsed_path": "parsed/chart.json",
        "chart_series": [chart],
        "execution_chart_series": [gold],
        "source_refs": [*scanner["source_refs"], *chart["source_refs"], *gold["source_refs"]],
    }


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research-market.db'}")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["task_runs"], Base.metadata.tables["task_steps"]])
    for table in RESEARCH_MARKET_TABLES:
        table.create(engine)
    with Session(engine) as db:
        yield db


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_materializes_real_parsed_fixtures_and_rebuilds_financial_features(session, tmp_path):
    observed = _observed()
    before_cross = build_cross_asset_features(observed, as_of=AS_OF)
    gold_as_of = observed["execution_chart_series"][0]["retrieved_at"]
    before_execution = merge_tradingview_execution(
        None,
        observed["execution_chart_series"],
        as_of=gold_as_of,
        analysis_date="2026-09-28",
    )

    rebuilt = materialize_research_market(
        session, observed, run_id="research-fixture-run", storage_root=tmp_path, kind="cross_asset"
    )

    assert build_cross_asset_features(rebuilt, as_of=AS_OF) == before_cross
    assert (
        merge_tradingview_execution(
            None,
            rebuilt["execution_chart_series"],
            as_of=gold_as_of,
            analysis_date="2026-09-28",
        )
        == before_execution
    )
    assert rebuilt["chart_series"][0]["metadata"] == observed["chart_series"][0]["metadata"]
    assert rebuilt["execution_chart_series"][0]["bars"] == observed["execution_chart_series"][0]["bars"]
    assert rebuilt["source_refs"] == observed["source_refs"]
    assert _count(session, ResearchMarketBatch) == 1
    assert _count(session, ResearchMarketScannerQuote) == len(observed["observations"])
    assert _count(session, ResearchMarketChartSeries) == 2
    assert _count(session, ResearchMarketBar) == sum(
        len(row["bars"]) for key in ("chart_series", "execution_chart_series") for row in observed[key]
    )
    assert _count(session, TaskRun) == _count(session, TaskStep) == 1


def test_collection_receipts_allow_expiry_without_losing_research_facts(session, tmp_path):
    import os
    from datetime import UTC, datetime, timedelta
    from sqlalchemy.orm import sessionmaker
    from apps.data_layer.research_market_ingestion import materialize_research_market as ingest
    from apps.data_layer.raw_retention import apply_raw_retention, preview_raw_retention
    from tests.helpers.warehouse import create_collection_schema

    create_collection_schema(session.get_bind())
    observed = _observed()
    paths = {tmp_path / ref['raw_path'] for ref in observed['source_refs']}
    now = datetime(2026, 11, 10, tzinfo=UTC)
    old = (now - timedelta(days=40)).timestamp()
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('archived provider response')
        os.utime(path, (old, old))
    rebuilt = ingest(session, observed, run_id='retention-research', storage_root=tmp_path, kind='cross_asset')
    batch_id = session.info['research_market_batch_id']
    assert session.info['research_market_ingestion']['raw_ready'] == len(paths)
    session.commit()
    preview = preview_raw_retention(session, storage_root=tmp_path, now=now)
    assert preview['candidate_count'] == len(paths)
    session.rollback()
    result = apply_raw_retention(sessionmaker(session.get_bind()), storage_root=tmp_path, now=now)
    assert result['deleted_count'] == len(paths)
    assert not any(path.exists() for path in paths)
    assert read_research_market(session, batch_id=batch_id) == rebuilt
    assert build_cross_asset_features(rebuilt, as_of=AS_OF) == build_cross_asset_features(observed, as_of=AS_OF)


def test_same_run_kind_and_content_is_zero_new_dwd_rows_but_audited(session, tmp_path):
    observed = _observed()
    first = materialize_research_market(
        session, observed, run_id="idempotent-run", storage_root=tmp_path, kind="adaptive"
    )
    counts = tuple(
        _count(session, model)
        for model in (ResearchMarketBatch, ResearchMarketScannerQuote, ResearchMarketChartSeries, ResearchMarketBar)
    )
    second = materialize_research_market(
        session, deepcopy(observed), run_id="idempotent-run", storage_root=tmp_path, kind="adaptive"
    )

    assert second == first
    assert (
        tuple(
            _count(session, model)
            for model in (ResearchMarketBatch, ResearchMarketScannerQuote, ResearchMarketChartSeries, ResearchMarketBar)
        )
        == counts
    )
    assert _count(session, TaskRun) == _count(session, TaskStep) == 2
    assert read_research_market(session, run_id="idempotent-run", kind="adaptive") == first

    materialize_research_market(
        session, deepcopy(observed), run_id="another-run", storage_root=tmp_path, kind="cross_asset"
    )
    hashes = set(session.scalars(select(ResearchMarketBatch.content_sha256)))
    assert len(hashes) == 1  # Content identity is independent of run and consumer kind.


def test_execution_collector_shape_round_trips_from_series_key(session, tmp_path):
    gold = _chart("tradingview_gold_4h.json")
    observed = {
        "schema_version": "tradingview_chart_series.v1",
        "retrieved_at": gold["retrieved_at"],
        "series": [gold],
        "source_refs": gold["source_refs"],
        "parsed_path": "parsed/gold.json",
    }
    rebuilt = materialize_research_market(
        session, observed, run_id="execution-run", storage_root=tmp_path, kind="execution"
    )
    assert set(rebuilt) == set(observed)
    assert rebuilt == observed


@pytest.mark.parametrize(
    "mutate,error",
    [
        (lambda data: data["observations"][0].update(quote_time_verified=1), "RESEARCH_MARKET_BOOLEAN_INVALID"),
        (
            lambda data: data["observations"][0].update(retrieved_at="2026-09-17T11:26:15"),
            "RESEARCH_MARKET_TIME_INVALID",
        ),
        (
            lambda data: data["observations"][0]["source_refs"][0].update(source="jin10"),
            "RESEARCH_MARKET_SOURCE_REJECTED",
        ),
        (lambda data: data["observations"][0].update(symbol="BRENT"), "RESEARCH_MARKET_IDENTITY_INVALID"),
    ],
)
def test_rejects_bad_boolean_pit_source_and_identity(session, tmp_path, mutate, error):
    observed = _observed()
    mutate(observed)
    with pytest.raises(ResearchMarketWarehouseError, match=error):
        materialize_research_market(session, observed, run_id="rejected-run", storage_root=tmp_path, kind="cross_asset")
    assert _count(session, ResearchMarketBatch) == _count(session, TaskRun) == 0


def test_missing_and_failed_inputs_remain_unavailable_and_unknown(session, tmp_path):
    observed = _observed()
    missing = observed["observations"][0]
    missing.update(
        status="missing",
        reason="symbol_not_returned",
        value=None,
        scanner_close=None,
        delay_seconds=None,
        provider_bar_time=None,
        minute_bar_time=None,
        update_mode=None,
    )
    failed = observed["chart_series"][0]
    failed.update(status="unavailable", delay_seconds=None, bars=[], error="TimeoutError")
    failed.pop("metadata")

    rebuilt = materialize_research_market(
        session, observed, run_id="degraded-run", storage_root=tmp_path, kind="adaptive"
    )

    assert rebuilt["observations"][0]["status"] == "missing"
    assert rebuilt["observations"][0]["value"] is None
    assert rebuilt["observations"][0]["delay_seconds"] is None
    assert rebuilt["chart_series"][0]["status"] == "unavailable"
    assert rebuilt["chart_series"][0]["delay_seconds"] is None
    assert rebuilt["chart_series"][0]["bars"] == []
    assert "metadata" not in rebuilt["chart_series"][0]


def test_database_failure_rolls_back_batch_children_and_audit(session, tmp_path):
    def fail_insert(*_args, **_kwargs):
        raise RuntimeError("injected database failure")

    event.listen(ResearchMarketBar, "before_insert", fail_insert)
    try:
        with pytest.raises(ResearchMarketWarehouseError, match="RESEARCH_MARKET_TRANSACTION_FAILED"):
            materialize_research_market(
                session, _observed(), run_id="rollback-run", storage_root=tmp_path, kind="cross_asset"
            )
    finally:
        event.remove(ResearchMarketBar, "before_insert", fail_insert)

    for model in (
        ResearchMarketBatch,
        ResearchMarketScannerQuote,
        ResearchMarketChartSeries,
        ResearchMarketBar,
        TaskRun,
        TaskStep,
    ):
        assert _count(session, model) == 0


def test_caller_owns_outer_transaction_and_tables_have_no_serialized_bags(session, tmp_path):
    materialize_research_market(
        session, _observed(), run_id="caller-transaction", storage_root=tmp_path, kind="cross_asset"
    )
    assert _count(session, ResearchMarketBatch) == 1
    for table in RESEARCH_MARKET_TABLES:
        assert all(not isinstance(column.type, (JSON, LargeBinary, PickleType)) for column in table.columns)

    session.rollback()
    with Session(session.bind) as independent:
        assert _count(independent, ResearchMarketBatch) == 0
        assert _count(independent, TaskRun) == 0


def test_required_session_and_schema_fail_explicitly(tmp_path):
    with pytest.raises(ResearchMarketWarehouseError, match="RESEARCH_MARKET_SESSION_REQUIRED"):
        materialize_research_market(
            None, _observed(), run_id="missing-session", storage_root=tmp_path, kind="cross_asset"
        )
    engine = create_engine(f"sqlite:///{tmp_path / 'missing-schema.db'}")
    with Session(engine) as empty:
        with pytest.raises(ResearchMarketWarehouseError, match="RESEARCH_MARKET_SCHEMA_MISSING"):
            materialize_research_market(
                empty, _observed(), run_id="missing-schema", storage_root=tmp_path, kind="cross_asset"
            )
