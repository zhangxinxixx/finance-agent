"""Tests for macro worker pipeline.

Covers:
- MacroPipelineState creation and field defaults
- run_macro_step dispatches to correct step functions
- Individual step logic with mocked collectors
- Full pipeline chain: collect → feature → render
- Error handling: step failure propagation
- run_premarket integration with macro steps (SQLite, no real network)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.data_layer.models import DualSourceResult
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.worker.pipelines.macro import (
    MACRO_STEPS,
    MacroPipelineState,
    run_macro_step,
)
from database.models.analysis import DataSourceStatus, FeatureSnapshot, MacroObservation, ensure_analysis_tables
from database.models.execution import ExecutionEvent, RunArtifact, ensure_execution_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_db_session(tmp_path: Path):
    """Create a SQLite session with task and analysis tables."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    ensure_analysis_tables(engine)
    ensure_execution_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _make_fred_result() -> CollectorResult:
    """Realistic FRED collector result with some data and some unavailable."""
    points = [
        MacroPoint(
            symbol="DGS10", date="2026-05-06", value=4.30,
            source="fred", source_url="https://api.stlouisfed.org/fred/series/observations?series_id=DGS10",
            retrieved_at="2026-05-06T12:00:00+00:00", raw_path="storage/raw/macro/fred/2026-05-06/DGS10.json",
        ),
        MacroPoint(
            symbol="DGS10", date="2026-04-29", value=4.20,
            source="fred", source_url="https://api.stlouisfed.org/fred/series/observations?series_id=DGS10",
            retrieved_at="2026-05-06T12:00:00+00:00", raw_path="storage/raw/macro/fred/2026-05-06/DGS10.json",
        ),
        MacroPoint(
            symbol="DGS2", date="2026-05-06", value=4.00,
            source="fred", source_url="https://api.stlouisfed.org/fred/series/observations?series_id=DGS2",
            retrieved_at="2026-05-06T12:00:00+00:00", raw_path="storage/raw/macro/fred/2026-05-06/DGS2.json",
        ),
        MacroPoint(
            symbol="SOFR", date="2026-05-06", value=4.40,
            source="fred", source_url="https://api.stlouisfed.org/fred/series/observations?series_id=SOFR",
            retrieved_at="2026-05-06T12:00:00+00:00", raw_path="storage/raw/macro/fred/2026-05-06/SOFR.json",
        ),
    ]
    return CollectorResult(
        points=points,
        unavailable_symbols=["RRPONTSYD"],  # FRED API key not set
        source_refs=[
            {"symbol": "DGS10", "source": "fred", "source_url": "https://api.stlouisfed.org/"},
            {"symbol": "DGS2", "source": "fred", "source_url": "https://api.stlouisfed.org/"},
            {"symbol": "SOFR", "source": "fred", "source_url": "https://api.stlouisfed.org/"},
            {"symbol": "RRPONTSYD", "source": "fred", "source_url": "https://api.stlouisfed.org/", "reason": "FRED_API_KEY not set"},
        ],
    )


def _make_fed_result() -> CollectorResult:
    """Fed collector: offline MVP, all unavailable."""
    return CollectorResult(
        points=[],
        unavailable_symbols=["RRP", "RESERVES", "IORB"],
        source_refs=[
            {"symbol": "RRP", "source": "fed", "reason": "offline MVP"},
            {"symbol": "RESERVES", "source": "fed", "reason": "offline MVP"},
            {"symbol": "IORB", "source": "fed", "reason": "offline MVP"},
        ],
    )


def _make_treasury_result() -> CollectorResult:
    """Treasury collector: offline MVP, TGA unavailable."""
    return CollectorResult(
        points=[],
        unavailable_symbols=["TGA"],
        source_refs=[{"symbol": "TGA", "source": "treasury", "reason": "offline MVP"}],
    )


def _make_dxy_empty_result() -> CollectorResult:
    """DXY collector: mocked empty for unit tests (no real network)."""
    return CollectorResult(
        points=[],
        unavailable_symbols=["DXY"],
        source_refs=[{"symbol": "DXY", "source": "tradingview", "source_url": "https://scanner.tradingview.com/america/scan", "reason": "mocked offline"}],
    )


def _make_empty_result() -> CollectorResult:
    """Generic empty collector result for technical/positioning/news mocks."""
    return CollectorResult(points=[], unavailable_symbols=[], source_refs=[])


@pytest.fixture(autouse=True)
def _mock_jin10_mcp_collectors():
    """Keep macro pipeline unit tests isolated from live Jin10 MCP collectors."""
    with (
        patch("apps.collectors.jin10.quotes.collect_quotes", return_value=_make_empty_result()),
        patch("apps.collectors.jin10.kline.collect_kline", return_value=_make_empty_result()),
        patch("apps.collectors.jin10.articles.collect_articles", return_value=_make_empty_result()),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_source_status_index():
    """Keep worker integration tests deterministic unless a test opts into source gating explicitly."""
    with patch("apps.api.services.source_service.get_data_source_status_index", return_value={}):
        yield


def _make_news_result() -> CollectorResult:
    return CollectorResult(
        points=[
            MacroPoint(
                symbol="NEWS_EVENT:美国CPI",
                date="2026-05-06T12:00:00+00:00",
                value=5.0,
                source="jin10_mcp",
                source_url="storage/raw/jin10_mcp/2026-05-06/calendar.json",
                retrieved_at="2026-05-06T12:00:00+00:00",
                raw_path="storage/raw/jin10_mcp/2026-05-06/calendar.json",
            )
        ],
        unavailable_symbols=[],
        source_refs=[{"source": "jin10_mcp", "method": "list_calendar"}],
    )


def _make_data_layer_fred_result(
    *,
    points: list[MacroPoint] | None = None,
    unavailable_symbols: list[str] | None = None,
    source_refs: list[dict[str, str]] | None = None,
    source_used: str = "openbb",
    warnings: list[str] | None = None,
) -> DualSourceResult:
    return DualSourceResult(
        points=points or [],
        source_used=source_used,
        unavailable_symbols=unavailable_symbols or [],
        source_refs=source_refs or [],
        warnings=warnings or [],
    )


def _make_data_layer_market_result(
    *,
    points: list[MacroPoint] | None = None,
    unavailable_symbols: list[str] | None = None,
    source_refs: list[dict[str, str]] | None = None,
    source_used: str = "openbb",
    warnings: list[str] | None = None,
) -> DualSourceResult:
    return DualSourceResult(
        points=points or [],
        source_used=source_used,
        unavailable_symbols=unavailable_symbols or [],
        source_refs=source_refs or [],
        warnings=warnings or [],
    )


# ---------------------------------------------------------------------------
# Unit tests — MacroPipelineState
# ---------------------------------------------------------------------------


class TestMacroPipelineState:
    def test_defaults(self):
        state = MacroPipelineState()
        assert state.all_points == []
        assert state.all_unavailable == []
        assert state.all_source_refs == []
        assert state.as_of == ""
        assert state.snapshot_dict is None
        assert state.conclusion_dict is None
        assert state.report_md is None
        assert state.full_report_md is None
        assert state.step_summaries == {}


# ---------------------------------------------------------------------------
# Unit tests — run_macro_step dispatch
# ---------------------------------------------------------------------------


class TestRunMacroStepDispatch:
    def test_unknown_step_raises(self):
        state = MacroPipelineState()
        with pytest.raises(ValueError, match="Unknown macro step"):
            run_macro_step("nonexistent_step", state)

    def test_macro_steps_are_well_defined(self):
        assert MACRO_STEPS == {"macro_collect", "macro_feature", "report_render"}


# ---------------------------------------------------------------------------
# Unit tests — individual step logic (mocked)
# ---------------------------------------------------------------------------


class TestStepCollect:
    def test_collect_aggregates_all_sources(self, tmp_path):
        """Verify that macro_collect calls all 3 collectors and merges results."""
        state = MacroPipelineState()

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", return_value=_make_fred_result()),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_fed_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_treasury_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=_make_dxy_empty_result()),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_news_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", return_value=_make_data_layer_fred_result()),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=_make_data_layer_market_result()),
        ):
            summary = run_macro_step("macro_collect", state, storage_root=tmp_path)

        assert summary["step"] == "macro_collect"
        assert summary["status"] == "success"
        assert summary["total_points"] == 5  # FRED: 4 points + News: 1 point
        assert summary["total_unavailable"] > 0
        assert state.as_of != ""

        # Verify merged state
        assert len(state.all_points) == 5
        assert any(point.symbol.startswith("NEWS_EVENT:") for point in state.all_points)
        assert "RRP" in state.all_unavailable  # Fed
        assert "TGA" in state.all_unavailable  # Treasury
        assert "DXY" in state.all_unavailable  # DXY mock
        assert len(state.all_source_refs) > 0

        # Verify collector statuses
        collector_names = [c["collector"] for c in summary["collectors"]]
        assert "fred" in collector_names
        assert "fed" in collector_names
        assert "treasury" in collector_names
        assert "dxy" in collector_names
        assert "technical" in collector_names
        assert "positioning" in collector_names
        assert "news" in collector_names

    def test_collect_upserts_data_source_status_rows(self, tmp_path):
        """macro_collect persists real collector status when a DB session is provided."""
        state = MacroPipelineState()
        db = _make_db_session(tmp_path)

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", return_value=_make_fred_result()),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_fed_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_treasury_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=_make_dxy_empty_result()),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_news_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", return_value=_make_data_layer_fred_result()),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=_make_data_layer_market_result()),
        ):
            summary = run_macro_step("macro_collect", state, storage_root=tmp_path, run_id="run-status-001", db_session=db)

        assert summary["data_source_status_upserts"] == 8
        assert summary["macro_observation_upserts"] == 5
        assert summary["raw_artifact_registry_upserts"] == 0

        rows = {row.source_key: row for row in db.query(DataSourceStatus).all()}
        assert {"fred", "fed", "treasury", "dxy", "technical_yahoo", "positioning_cot", "openbb_macro", "jin10_news"}.issubset(rows)

        assert rows["fred"].status == "partial"
        assert rows["fred"].configured is True
        assert rows["fred"].raw_ingested is True
        assert rows["fred"].parsed is True
        assert rows["fred"].analysis_ready is True
        assert rows["fred"].row_count == 4
        assert rows["fred"].last_run_id == "run-status-001"

        assert rows["openbb_macro"].source_metadata["provider_role"] == "fallback"
        assert rows["openbb_macro"].status == "partial"
        assert rows["openbb_macro"].raw_ingested is False
        assert rows["openbb_macro"].parsed is False
        assert rows["openbb_macro"].last_run_id == "run-status-001"

        assert rows["jin10_news"].source_metadata["provider_role"] == "supplemental"
        assert rows["jin10_news"].status == "ok"
        assert rows["jin10_news"].analysis_ready is True

        assert rows["technical_yahoo"].source_metadata["frontend_label"] == "Jin10 黄金实时/技术补充源"
        assert rows["technical_yahoo"].status == "ok"
        assert rows["technical_yahoo"].raw_ingested is False
        assert rows["positioning_cot"].status == "ok"
        assert rows["positioning_cot"].raw_ingested is False

        observations = db.query(MacroObservation).order_by(MacroObservation.source_key.asc(), MacroObservation.symbol.asc()).all()
        assert len(observations) == 5
        dgs10 = [
            row
            for row in observations
            if row.source_key == "fred" and row.symbol == "DGS10" and row.observation_date.isoformat() == "2026-05-06"
        ][0]
        assert dgs10.value == 4.30
        assert dgs10.run_id == "run-status-001"
        assert dgs10.source_refs == [
            {"symbol": "DGS10", "source": "fred", "source_url": "https://api.stlouisfed.org/"}
        ]
        assert dgs10.observation_metadata["collector_source"] == "fred"

        news_event = [row for row in observations if row.symbol.startswith("NEWS_EVENT:")][0]
        assert news_event.source_key == "jin10_mcp"
        assert news_event.observation_date.isoformat() == "2026-05-06"
        assert news_event.source_refs == [{"source": "jin10_mcp", "method": "list_calendar"}]

    def test_collect_links_macro_observations_to_registered_raw_artifacts(self, tmp_path):
        state = MacroPipelineState()
        db = _make_db_session(tmp_path)
        run = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(run)
        db.flush()
        dgs10_raw_path = "raw/macro/fred/2026-05-06/DGS10.json"
        dgs2_raw_path = "raw/macro/fred/2026-05-06/DGS2.json"
        for raw_path in (dgs10_raw_path, dgs2_raw_path):
            target = tmp_path / raw_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"observations":[]}\n', encoding="utf-8")
        fred_result = CollectorResult(
            points=[
                MacroPoint(
                    symbol="DGS10",
                    date="2026-05-06",
                    value=4.30,
                    source="fred",
                    source_url="https://api.stlouisfed.org/",
                    retrieved_at="2026-05-06T12:00:00+00:00",
                    raw_path=dgs10_raw_path,
                ),
                MacroPoint(
                    symbol="DGS10",
                    date="2026-04-29",
                    value=4.20,
                    source="fred",
                    source_url="https://api.stlouisfed.org/",
                    retrieved_at="2026-05-06T12:00:00+00:00",
                    raw_path=dgs10_raw_path,
                ),
                MacroPoint(
                    symbol="DGS2",
                    date="2026-05-06",
                    value=4.00,
                    source="fred",
                    source_url="https://api.stlouisfed.org/",
                    retrieved_at="2026-05-06T12:00:00+00:00",
                    raw_path=dgs2_raw_path,
                ),
            ],
            unavailable_symbols=[],
            source_refs=[
                {"symbol": "DGS10", "source": "fred", "source_url": "https://api.stlouisfed.org/", "raw_path": dgs10_raw_path},
                {"symbol": "DGS2", "source": "fred"},
            ],
        )

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", return_value=fred_result),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_empty_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_empty_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=_make_empty_result()),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_empty_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", return_value=_make_data_layer_fred_result()),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=_make_data_layer_market_result()),
        ):
            summary = run_macro_step("macro_collect", state, storage_root=tmp_path, run_id=str(run.id), db_session=db)
        db.commit()

        assert summary["macro_observation_upserts"] == 3
        assert summary["raw_artifact_registry_upserts"] == 2

        artifacts = db.query(RunArtifact).order_by(RunArtifact.file_path.asc()).all()
        assert [artifact.file_path for artifact in artifacts] == [dgs10_raw_path, dgs2_raw_path]
        assert all(artifact.artifact_type == "raw_file" for artifact in artifacts)
        assert all(artifact.artifact_metadata["canonical_path"] is False for artifact in artifacts)
        assert all(artifact.artifact_metadata["collector_stage"] == "macro_collect" for artifact in artifacts)
        dgs2_artifact = next(artifact for artifact in artifacts if artifact.file_path == dgs2_raw_path)
        assert dgs2_artifact.source_refs_data == [
            {
                "symbol": "DGS2",
                "source": "fred",
                "source_url": "https://api.stlouisfed.org/",
                "raw_path": dgs2_raw_path,
            }
        ]

        observations = {
            (row.symbol, row.observation_date.isoformat()): row
            for row in db.query(MacroObservation).all()
        }
        assert observations[("DGS10", "2026-05-06")].raw_artifact_id == str(
            next(artifact.artifact_id for artifact in artifacts if artifact.file_path == dgs10_raw_path)
        )
        assert observations[("DGS10", "2026-04-29")].raw_artifact_id == observations[("DGS10", "2026-05-06")].raw_artifact_id
        assert observations[("DGS2", "2026-05-06")].raw_artifact_id == str(
            next(artifact.artifact_id for artifact in artifacts if artifact.file_path == dgs2_raw_path)
        )

    def test_collect_official_source_keeps_existing_symbols_without_data_layer_duplicates(self, tmp_path):
        state = MacroPipelineState()
        db = _make_db_session(tmp_path)
        data_layer_fred = _make_data_layer_fred_result(
            points=[
                MacroPoint(
                    symbol="DGS10",
                    date="2026-05-06",
                    value=4.35,
                    source="openbb_fred",
                    source_url="https://fred.stlouisfed.org/series/DGS10",
                    retrieved_at="2026-05-06T13:00:00+00:00",
                    raw_path="storage/raw/macro/openbb_fred/2026-05-06/DGS10.json",
                )
            ],
            unavailable_symbols=["DGS30"],
            source_refs=[
                {"symbol": "DGS10", "source": "openbb_fred", "raw_path": "storage/raw/macro/openbb_fred/2026-05-06/DGS10.json"},
                {"symbol": "DGS30", "source": "openbb_fred", "reason": "missing"},
            ],
            warnings=["OpenBB returned a partial subset"],
        )
        data_layer_market = _make_data_layer_market_result(
            source_refs=[{"symbol": "DX-Y.NYB", "source": "openbb_yfinance"}],
            warnings=["market prices skipped because official DXY exists"],
        )

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", return_value=_make_fred_result()),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_fed_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_treasury_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=CollectorResult(
                points=[
                    MacroPoint(
                        symbol="DXY",
                        date="2026-05-06",
                        value=101.2,
                        source="tradingview",
                        source_url="https://scanner.tradingview.com/america/scan",
                        retrieved_at="2026-05-06T12:00:00+00:00",
                        raw_path="storage/raw/macro/tradingview/2026-05-06/DXY.json",
                    )
                ],
                unavailable_symbols=[],
                source_refs=[{"symbol": "DXY", "source": "tradingview"}],
            )),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_empty_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", return_value=data_layer_fred),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=data_layer_market),
        ):
            summary = run_macro_step("macro_collect", state, storage_root=tmp_path, run_id="run-dedupe-001", db_session=db)

        dgs10_points = [point for point in state.all_points if point.symbol == "DGS10"]
        assert len(dgs10_points) == 2  # official FRED keeps the original 2 observations
        assert all(point.source == "fred" for point in dgs10_points)
        assert "DGS30" in state.all_unavailable
        assert any(ref.get("source") == "openbb_fred" for ref in state.all_source_refs)

        collectors = {item["collector"]: item for item in summary["collectors"]}
        assert collectors["data_layer_fred_rates"]["status"] == "partial"
        assert collectors["data_layer_fred_rates"]["added_points"] == 0
        assert collectors["data_layer_fred_rates"]["source_used"] == "openbb"
        assert collectors["data_layer_market_prices"]["status"] == "skipped"
        assert collectors["data_layer_market_prices"]["warnings"]

        openbb_status = db.query(DataSourceStatus).filter_by(source_key="openbb_macro").one()
        assert openbb_status.status == "partial"
        assert openbb_status.configured is True
        assert openbb_status.raw_ingested is False
        assert openbb_status.parsed is False
        assert openbb_status.analysis_ready is False
        assert openbb_status.row_count == 0

    def test_collect_continues_when_one_collector_fails(self, tmp_path):
        """Collector failure is non-fatal — other collectors still run."""
        state = MacroPipelineState()

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", side_effect=RuntimeError("Network down")),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_fed_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_treasury_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=_make_dxy_empty_result()),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_empty_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", return_value=_make_data_layer_fred_result()),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=_make_data_layer_market_result()),
        ):
            summary = run_macro_step("macro_collect", state, storage_root=tmp_path)

        assert summary["status"] == "success"
        fred_status = [c for c in summary["collectors"] if c["collector"] == "fred"][0]
        assert fred_status["status"] == "failed"
        assert "Network down" in fred_status["error"]

        # FRED failed, DXY mocked empty — other collectors have no points either
        assert len(state.all_points) == 0
        assert "TGA" in state.all_unavailable

    def test_collect_uses_data_layer_when_official_source_missing(self, tmp_path):
        state = MacroPipelineState()
        fallback_fred = _make_data_layer_fred_result(
            points=[
                MacroPoint(
                    symbol="DGS10",
                    date="2026-05-06",
                    value=4.31,
                    source="openbb_fred",
                    source_url="https://fred.stlouisfed.org/series/DGS10",
                    retrieved_at="2026-05-06T13:00:00+00:00",
                    raw_path="storage/raw/macro/openbb_fred/2026-05-06/DGS10.json",
                )
            ],
            unavailable_symbols=["DGS2"],
            source_refs=[{"symbol": "DGS10", "source": "openbb_fred"}],
            warnings=["official fred unavailable, using OpenBB"],
        )
        fallback_market = _make_data_layer_market_result(
            points=[
                MacroPoint(
                    symbol="DX-Y.NYB",
                    date="2026-05-06",
                    value=100.1,
                    source="openbb_yfinance",
                    source_url="https://finance.yahoo.com/quote/DX-Y.NYB",
                    retrieved_at="2026-05-06T13:00:00+00:00",
                    raw_path="storage/raw/macro/openbb_yfinance/2026-05-06/DX-Y.NYB.json",
                )
            ],
            unavailable_symbols=["^VIX"],
            source_refs=[{"symbol": "DX-Y.NYB", "source": "openbb_yfinance"}],
            warnings=["official dxy unavailable, using market proxy"],
        )

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", side_effect=RuntimeError("FRED down")),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_fed_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_treasury_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=_make_dxy_empty_result()),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_empty_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", return_value=fallback_fred),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=fallback_market),
        ):
            summary = run_macro_step("macro_collect", state, storage_root=tmp_path)

        assert summary["status"] == "success"
        assert any(point.symbol == "DGS10" and point.source == "openbb_fred" for point in state.all_points)
        assert any(point.symbol == "DXY" and point.source == "openbb_yfinance" for point in state.all_points)
        assert "DGS2" in state.all_unavailable
        assert "^VIX" in state.all_unavailable

        collectors = {item["collector"]: item for item in summary["collectors"]}
        assert collectors["fred"]["status"] == "failed"
        assert collectors["data_layer_fred_rates"]["status"] == "partial"
        assert collectors["data_layer_fred_rates"]["added_points"] == 1
        assert collectors["data_layer_market_prices"]["status"] == "partial"
        assert collectors["data_layer_market_prices"]["added_points"] == 1

    def test_collect_merges_data_layer_source_refs_and_unavailable(self, tmp_path):
        state = MacroPipelineState()
        fallback_fred = _make_data_layer_fred_result(
            unavailable_symbols=["DGS30"],
            source_refs=[{"symbol": "DGS30", "source": "openbb_fred", "reason": "fallback missing"}],
            warnings=["FRED fallback unavailable"],
        )
        fallback_market = _make_data_layer_market_result(
            source_refs=[{"symbol": "DX-Y.NYB", "source": "openbb_yfinance", "reason": "proxy checked"}],
            warnings=["market proxy evaluated"],
        )

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", return_value=_make_fred_result()),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_fed_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_treasury_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=_make_dxy_empty_result()),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_empty_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", return_value=fallback_fred),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=fallback_market),
        ):
            run_macro_step("macro_collect", state, storage_root=tmp_path)

        assert "DGS30" in state.all_unavailable
        assert state.all_unavailable.count("DGS30") == 1
        assert any(ref.get("source") == "openbb_fred" and ref.get("symbol") == "DGS30" for ref in state.all_source_refs)
        assert any(ref.get("source") == "openbb_yfinance" and ref.get("symbol") == "DX-Y.NYB" for ref in state.all_source_refs)

    def test_collect_data_layer_failure_is_non_fatal_and_records_status(self, tmp_path):
        state = MacroPipelineState()

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", return_value=_make_fred_result()),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_fed_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_treasury_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=_make_dxy_empty_result()),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_empty_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", side_effect=RuntimeError("OpenBB service down")),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=_make_data_layer_market_result()),
        ):
            summary = run_macro_step("macro_collect", state, storage_root=tmp_path)

        assert summary["status"] == "success"
        collectors = {item["collector"]: item for item in summary["collectors"]}
        assert collectors["data_layer_fred_rates"]["status"] == "failed"
        assert "OpenBB service down" in collectors["data_layer_fred_rates"]["error"]
        assert collectors["data_layer_market_prices"]["status"] == "skipped"


class TestStepFeature:
    def test_feature_builds_snapshot(self, tmp_path):
        """Feature step builds snapshot from collected points."""
        state = MacroPipelineState()
        state.as_of = "2026-05-06"
        state.all_points = _make_fred_result().points
        state.all_unavailable = ["TGA", "DXY"]
        state.all_source_refs = [
            {"symbol": "TGA", "source": "treasury", "reason": "offline"},
        ]

        summary = run_macro_step("macro_feature", state, storage_root=tmp_path)

        assert summary["step"] == "macro_feature"
        assert summary["status"] == "success"
        assert summary["indicator_count"] > 0
        assert state.snapshot_dict is not None
        assert state.snapshot_dict["as_of"] == "2026-05-06"
        assert "TGA" in state.snapshot_dict["unavailable_symbols"]

    def test_feature_requires_collect(self, tmp_path):
        """Feature step raises if collect hasn't set as_of."""
        state = MacroPipelineState()
        with pytest.raises(RuntimeError, match="macro_collect"):
            run_macro_step("macro_feature", state, storage_root=tmp_path)


class TestStepRender:
    def test_render_writes_json_and_md(self, tmp_path):
        """Render step writes macro_snapshot.json and macro_snapshot.md."""
        state = MacroPipelineState()
        state.as_of = "2026-05-06"
        state.all_points = _make_fred_result().points
        state.all_unavailable = ["TGA", "DXY"]
        state.all_source_refs = []

        # Run feature first to populate snapshot_dict
        run_macro_step("macro_feature", state, storage_root=tmp_path)

        summary = run_macro_step("report_render", state, storage_root=tmp_path, run_id="run-a")

        assert summary["step"] == "report_render"
        assert summary["status"] == "success"
        assert summary["feature_snapshot_upserts"] == 0

        json_path = tmp_path / "features" / "macro" / "2026-05-06" / "run-a" / "macro_snapshot.json"
        conclusion_path = tmp_path / "features" / "macro" / "2026-05-06" / "run-a" / "macro_conclusion.json"
        md_path = tmp_path / "outputs" / "macro" / "2026-05-06" / "run-a" / "macro_snapshot.md"
        full_md_path = tmp_path / "outputs" / "macro" / "2026-05-06" / "run-a" / "macro_full_report.md"

        assert json_path.exists()
        assert conclusion_path.exists()
        assert md_path.exists()
        assert full_md_path.exists()

        json_content = json.loads(json_path.read_text())
        assert json_content["as_of"] == "2026-05-06"
        assert "indicators" in json_content
        assert "unavailable_symbols" in json_content
        assert "source_refs" in json_content

        md_content = md_path.read_text()
        assert "XAUUSD 宏观数据报告" in md_content
        assert "数据刷新时间: 2026-05-06" in md_content
        assert "指标 | 最新日期" in md_content

        conclusion_content = json.loads(conclusion_path.read_text())
        assert "bias" in conclusion_content
        full_md_content = full_md_path.read_text()
        assert "XAUUSD 宏观 / 流动性更新" in full_md_content

    def test_render_upserts_feature_snapshots_when_db_session_is_provided(self, tmp_path):
        state = MacroPipelineState()
        state.as_of = "2026-05-06"
        state.all_points = _make_fred_result().points
        state.all_unavailable = ["TGA", "DXY"]
        state.all_source_refs = [{"symbol": "DGS10", "source": "fred", "source_url": "https://api.stlouisfed.org/"}]
        db = _make_db_session(tmp_path)

        run_macro_step("macro_feature", state, storage_root=tmp_path)
        summary = run_macro_step(
            "report_render",
            state,
            storage_root=tmp_path,
            run_id="run-feature-001",
            db_session=db,
        )
        db.commit()

        assert summary["feature_snapshot_upserts"] == 2
        assert summary["render_artifact_registry_upserts"] == 0
        assert summary["report_registry_upserts"] == 5
        rows = {
            row.snapshot_kind: row
            for row in db.query(FeatureSnapshot).order_by(FeatureSnapshot.snapshot_kind.asc()).all()
        }
        assert set(rows) == {"macro_snapshot", "macro_conclusion"}

        snapshot = rows["macro_snapshot"]
        conclusion = rows["macro_conclusion"]
        assert snapshot.snapshot_id == "feature:macro:macro_snapshot:2026-05-06:run-feature-001"
        assert snapshot.domain == "macro"
        assert snapshot.asset == "XAUUSD"
        assert snapshot.trade_date.isoformat() == "2026-05-06"
        assert snapshot.run_id == "run-feature-001"
        assert snapshot.status == "partial"
        assert snapshot.payload["as_of"] == "2026-05-06"
        assert len(snapshot.payload_sha256) == 64
        assert snapshot.artifact_path == summary["json_path"]
        assert snapshot.source_refs == [
            {"symbol": "DGS10", "source": "fred", "source_url": "https://api.stlouisfed.org/"}
        ]
        assert snapshot.feature_metadata["artifact_name"] == "macro_snapshot.json"

        assert conclusion.snapshot_id == "feature:macro:macro_conclusion:2026-05-06:run-feature-001"
        assert conclusion.payload["bias"]
        assert conclusion.artifact_path == summary["conclusion_path"]
        assert conclusion.input_snapshot_ids == {"macro_snapshot": snapshot.snapshot_id}
        assert conclusion.feature_metadata["artifact_name"] == "macro_conclusion.json"

        report_item = db.query(ReportItem).filter_by(report_id="macro_report:run-feature-001").one()
        assert report_item.family == "macro_report"
        assert report_item.report_type == "macro_report"
        assert report_item.title == "XAUUSD 宏观分析报告（2026-05-06）"
        assert report_item.run_id == "run-feature-001"
        assert report_item.snapshot_id == snapshot.snapshot_id
        assert report_item.report_metadata["input_snapshot_ids"]["macro_conclusion"] == conclusion.snapshot_id

        report_artifacts = db.query(ReportArtifact).filter_by(report_id=report_item.report_id).all()
        assert len(report_artifacts) == 4
        assert {artifact.artifact_type for artifact in report_artifacts} == {"analysis_md", "structured_json"}
        primary_artifacts = [artifact for artifact in report_artifacts if artifact.is_primary]
        assert len(primary_artifacts) == 1
        assert primary_artifacts[0].file_path == summary["full_md_path"]
        assert primary_artifacts[0].content_type == "text/markdown"
        assert all(artifact.sha256 for artifact in report_artifacts)
        assert all(artifact.byte_size and artifact.byte_size > 0 for artifact in report_artifacts)
        assert all(artifact.source_refs == state.all_source_refs for artifact in report_artifacts)

    def test_render_registers_output_artifacts_for_real_task_run(self, tmp_path):
        state = MacroPipelineState()
        state.as_of = "2026-05-06"
        state.all_points = _make_fred_result().points
        state.all_unavailable = ["TGA", "DXY"]
        state.all_source_refs = [{"symbol": "DGS10", "source": "fred", "source_url": "https://api.stlouisfed.org/"}]
        db = _make_db_session(tmp_path)
        run = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(run)
        db.flush()

        run_macro_step("macro_feature", state, storage_root=tmp_path)
        summary = run_macro_step(
            "report_render",
            state,
            storage_root=tmp_path,
            run_id=str(run.id),
            db_session=db,
        )
        db.commit()

        assert summary["feature_snapshot_upserts"] == 2
        assert summary["render_artifact_registry_upserts"] == 4
        assert summary["report_registry_upserts"] == 5

        artifacts = db.query(RunArtifact).order_by(RunArtifact.file_path.asc()).all()
        assert [artifact.file_path for artifact in artifacts] == [
            f"features/macro/2026-05-06/{run.id}/macro_conclusion.json",
            f"features/macro/2026-05-06/{run.id}/macro_snapshot.json",
            f"outputs/macro/2026-05-06/{run.id}/macro_full_report.md",
            f"outputs/macro/2026-05-06/{run.id}/macro_snapshot.md",
        ]
        assert {artifact.artifact_type for artifact in artifacts} == {"feature_json", "analysis_md"}
        assert all(artifact.run_id == run.id for artifact in artifacts)
        assert all(artifact.task_id is None for artifact in artifacts)
        assert all(artifact.sha256 for artifact in artifacts)
        assert all(artifact.byte_size and artifact.byte_size > 0 for artifact in artifacts)
        assert all(artifact.source_refs_data == state.all_source_refs for artifact in artifacts)
        assert all(artifact.artifact_metadata["canonical_path"] is True for artifact in artifacts)
        assert all(artifact.artifact_metadata["source_key"] == "macro" for artifact in artifacts)
        assert all(artifact.artifact_metadata["pipeline_step"] == "report_render" for artifact in artifacts)

    def test_render_requires_feature(self, tmp_path):
        """Render step raises if feature hasn't run."""
        state = MacroPipelineState()
        with pytest.raises(RuntimeError, match="macro_feature"):
            run_macro_step("report_render", state, storage_root=tmp_path)


# ---------------------------------------------------------------------------
# Integration test — full macro pipeline chain
# ---------------------------------------------------------------------------


class TestFullMacroPipelineChain:
    def test_collect_feature_render_chain(self, tmp_path):
        """Full chain: collect → feature → render produces all artifacts."""
        state = MacroPipelineState()

        with (
            patch("apps.collectors.fred.collector.collect_fred_series", return_value=_make_fred_result()),
            patch("apps.collectors.fed.collector.collect_fed_series", return_value=_make_fed_result()),
            patch("apps.collectors.treasury.collector.collect_treasury_series", return_value=_make_treasury_result()),
            patch("apps.collectors.dxy.collector.collect_dxy_series", return_value=_make_dxy_empty_result()),
            patch("apps.collectors.technical.collector.collect_technical", return_value=_make_empty_result()),
            patch("apps.collectors.positioning.collector.collect_positioning_cot", return_value=_make_empty_result()),
            patch("apps.collectors.news.collector.collect_news", return_value=_make_empty_result()),
            patch("apps.data_layer.service.MacroDataService.collect_fred_rates", return_value=_make_data_layer_fred_result()),
            patch("apps.data_layer.service.MacroDataService.collect_market_prices", return_value=_make_data_layer_market_result()),
        ):
            s1 = run_macro_step("macro_collect", state, storage_root=tmp_path)
        assert s1["status"] == "success"
        assert len(state.all_points) == 4  # FRED: 4 pts; DXY/tech/positioning/news mocked empty

        s2 = run_macro_step("macro_feature", state, storage_root=tmp_path)
        assert s2["status"] == "success"
        assert state.snapshot_dict is not None

        s3 = run_macro_step("report_render", state, storage_root=tmp_path, run_id="run-chain-a")
        assert s3["status"] == "success"
        assert state.report_md is not None

        # Verify all output artifacts
        feature_dir = tmp_path / "features" / "macro" / state.as_of / "run-chain-a"
        out_dir = tmp_path / "outputs" / "macro" / state.as_of / "run-chain-a"
        assert (feature_dir / "macro_snapshot.json").exists()
        assert (out_dir / "macro_snapshot.md").exists()

        # Verify snapshot content
        snap = json.loads((feature_dir / "macro_snapshot.json").read_text())
        assert snap["as_of"] == state.as_of
        assert "indicators" in snap

        # Verify step_summaries
        assert len(state.step_summaries) == 3
        assert set(state.step_summaries.keys()) == MACRO_STEPS

    def test_same_day_runs_keep_history(self, tmp_path):
        """Repeated same-day renders land in distinct run directories."""
        state_a = MacroPipelineState()
        state_a.as_of = "2026-05-06"
        state_a.all_points = _make_fred_result().points
        state_a.all_unavailable = []
        state_a.all_source_refs = []
        run_macro_step("macro_feature", state_a, storage_root=tmp_path)
        summary_a = run_macro_step("report_render", state_a, storage_root=tmp_path, run_id="run-a")

        state_b = MacroPipelineState()
        state_b.as_of = "2026-05-06"
        state_b.all_points = _make_fred_result().points
        state_b.all_unavailable = []
        state_b.all_source_refs = []
        run_macro_step("macro_feature", state_b, storage_root=tmp_path)
        summary_b = run_macro_step("report_render", state_b, storage_root=tmp_path, run_id="run-b")

        json_a = Path(summary_a["json_path"])
        md_a = Path(summary_a["md_path"])
        json_b = Path(summary_b["json_path"])
        md_b = Path(summary_b["md_path"])

        assert json_a.exists()
        assert md_a.exists()
        assert json_b.exists()
        assert md_b.exists()
        assert json_a != json_b
        assert md_a != md_b
        assert json_a.read_text(encoding="utf-8") == json_b.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Integration test — run_premarket with macro steps
# ---------------------------------------------------------------------------


class TestRunPremarketWithMacro:
    def test_macro_steps_succeed(self, tmp_path):
        """run_premarket marks macro steps as success with mocked pipeline."""
        db = _make_db_session(tmp_path)

        task = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(task)
        db.flush()

        for name in ["macro_collect", "macro_feature", "cme_download", "cme_parse", "cme_ingest", "option_wall", "report_render"]:
            step = TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending)
            db.add(step)

        db.commit()

        # Mock CME pipeline
        cme_mock_results = {
            "cme_download": {"step": "cme_download", "status": "success"},
            "cme_parse": {"step": "cme_parse", "status": "success"},
            "cme_ingest": {"step": "cme_ingest", "status": "success"},
            "option_wall": {"step": "option_wall", "status": "success"},
        }

        def mock_cme_step(step_name, state, **kwargs):
            return cme_mock_results[step_name]

        # Mock macro pipeline
        macro_mock_results = {
            "macro_collect": {"step": "macro_collect", "status": "success"},
            "macro_feature": {"step": "macro_feature", "status": "success"},
            "report_render": {"step": "report_render", "status": "success"},
        }

        def mock_macro_step(step_name, state, **kwargs):
            return macro_mock_results[step_name]

        with (
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        ):
            from apps.worker.runner import run_premarket
            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.success

        db.refresh(task)
        assert task.status == TaskStatus.success
        for step in task.steps:
            assert step.status == StepStatus.success

        events = (
            db.query(ExecutionEvent)
            .filter(ExecutionEvent.run_id == task.id)
            .order_by(ExecutionEvent.created_at.asc(), ExecutionEvent.event_type.asc())
            .all()
        )
        event_types = [event.event_type for event in events]
        assert "RUN_STARTED" in event_types
        assert "RUN_FINISHED" in event_types
        assert event_types.count("TASK_STARTED") == len(task.steps)
        assert event_types.count("TASK_FINISHED") == len(task.steps)
        assert {event.task_id for event in events if event.event_type == "TASK_FINISHED"} == {
            step.id for step in task.steps
        }

    def test_macro_failure_produces_partial_success(self, tmp_path):
        """A macro step failure produces partial_success when other steps succeed."""
        db = _make_db_session(tmp_path)

        task = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(task)
        db.flush()

        for name in ["macro_collect", "macro_feature", "cme_download", "cme_parse", "cme_ingest", "option_wall", "report_render"]:
            step = TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending)
            db.add(step)

        db.commit()

        def mock_cme_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        def mock_macro_step(step_name, state, **kwargs):
            if step_name == "macro_collect":
                raise RuntimeError("FRED API timeout")
            return {"step": step_name, "status": "success"}

        with (
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        ):
            from apps.worker.runner import run_premarket
            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.partial_success

        db.refresh(task)
        steps_by_name = {s.name: s for s in task.steps}
        assert steps_by_name["macro_collect"].status == StepStatus.failed
        assert steps_by_name["macro_collect"].error == "FRED API timeout"
        # T1.4: same-pipeline upstream failure blocks downstream steps
        assert steps_by_name["macro_feature"].status == StepStatus.blocked
        assert steps_by_name["macro_feature"].blocked_reason is not None
        # CME pipeline is independent — not blocked by macro failure
        assert steps_by_name["cme_download"].status == StepStatus.success

    def test_cme_and_macro_steps_independent(self, tmp_path):
        """CME and macro pipelines are independent — one failing doesn't block the other."""
        db = _make_db_session(tmp_path)

        task = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(task)
        db.flush()

        for name in ["macro_collect", "macro_feature", "cme_download", "cme_parse", "cme_ingest", "option_wall", "report_render"]:
            step = TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending)
            db.add(step)

        db.commit()

        def mock_cme_step(step_name, state, **kwargs):
            if step_name == "cme_download":
                raise RuntimeError("CME server down")
            return {"step": step_name, "status": "success"}

        def mock_macro_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        with (
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        ):
            from apps.worker.runner import run_premarket
            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.partial_success

        db.refresh(task)
        steps_by_name = {s.name: s for s in task.steps}
        assert steps_by_name["cme_download"].status == StepStatus.failed
        assert steps_by_name["macro_collect"].status == StepStatus.success
        assert steps_by_name["macro_feature"].status == StepStatus.success
        assert steps_by_name["report_render"].status == StepStatus.success

    def test_source_readiness_blocks_macro_pipeline_before_execution(self, tmp_path):
        """Blocked source readiness should stop the macro pipeline before macro execution starts."""
        db = _make_db_session(tmp_path)

        task = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(task)
        db.flush()

        for name in ["macro_collect", "macro_feature", "report_render", "cme_download"]:
            db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))

        db.commit()

        macro_calls: list[str] = []

        def mock_cme_step(step_name, state, **kwargs):
            return {"step": step_name, "status": "success"}

        def mock_macro_step(step_name, state, **kwargs):
            macro_calls.append(step_name)
            return {"step": step_name, "status": "success"}

        source_status_index = {
            "fred": {"readiness_state": "blocked", "error_message": "upstream blocked"},
            "fed": {"readiness_state": "ready", "raw_ingested": True},
            "treasury": {"readiness_state": "ready", "raw_ingested": True},
            "dxy": {"readiness_state": "ready", "raw_ingested": True},
            "cme_daily_bulletin": {"readiness_state": "ready", "raw_ingested": True},
        }

        with (
            patch("apps.api.services.source_service.get_data_source_status_index", return_value=source_status_index),
            patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        ):
            from apps.worker.runner import run_premarket

            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.partial_success
        assert macro_calls == []

        db.refresh(task)
        steps_by_name = {s.name: s for s in task.steps}
        assert steps_by_name["macro_collect"].status == StepStatus.blocked
        assert "source readiness blocked: fred" in (steps_by_name["macro_collect"].blocked_reason or "")
        assert steps_by_name["macro_feature"].status == StepStatus.blocked
        assert steps_by_name["report_render"].status == StepStatus.blocked
        assert steps_by_name["cme_download"].status == StepStatus.success
        events = (
            db.query(ExecutionEvent)
            .filter(ExecutionEvent.run_id == task.id)
            .order_by(ExecutionEvent.created_at.asc(), ExecutionEvent.event_type.asc())
            .all()
        )
        event_types = [event.event_type for event in events]
        assert "SOURCE_READINESS_EVALUATED" in event_types
        assert "SOURCE_BLOCKED_TASK" in event_types

    def test_source_readiness_blocks_macro_pipeline_when_required_source_not_configured(self, tmp_path):
        """not_configured required sources should still trip the worker gate even without runtime signals."""
        db = _make_db_session(tmp_path)

        task = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(task)
        db.flush()

        for name in ["macro_collect", "macro_feature", "report_render"]:
            db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))

        db.commit()

        macro_calls: list[str] = []

        def mock_macro_step(step_name, state, **kwargs):
            macro_calls.append(step_name)
            return {"step": step_name, "status": "success"}

        source_status_index = {
            "fred": {"readiness_state": "not_configured"},
            "fed": {"readiness_state": "ready", "raw_ingested": True},
            "treasury": {"readiness_state": "ready", "raw_ingested": True},
            "dxy": {"readiness_state": "ready", "raw_ingested": True},
        }

        with (
            patch("apps.api.services.source_service.get_data_source_status_index", return_value=source_status_index),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        ):
            from apps.worker.runner import run_premarket

            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.blocked
        assert macro_calls == []

        db.refresh(task)
        assert task.status == TaskStatus.blocked
        steps_by_name = {s.name: s for s in task.steps}
        assert steps_by_name["macro_collect"].status == StepStatus.blocked
        assert "required_source_not_configured" in (steps_by_name["macro_collect"].blocked_reason or "")
        assert steps_by_name["macro_feature"].status == StepStatus.blocked
        assert steps_by_name["report_render"].status == StepStatus.blocked

    def test_source_readiness_degraded_allowed_marks_run_degraded(self, tmp_path):
        """Degraded-but-allowed source readiness should keep execution running and roll up to degraded."""
        db = _make_db_session(tmp_path)

        task = TaskRun(name="premarket", status=TaskStatus.pending)
        db.add(task)
        db.flush()

        for name in ["macro_collect", "macro_feature", "report_render"]:
            db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))

        db.commit()

        def mock_macro_step(step_name, state, **kwargs):
            if step_name == "report_render":
                state.snapshot_dict = {
                    "as_of": "2026-05-06",
                    "indicators": {
                        "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    },
                    "source_refs": [{"symbol": "DXY", "source": "tradingview"}],
                }
            return {"step": step_name, "status": "success"}

        source_status_index = {
            "fred": {"readiness_state": "degraded", "raw_ingested": True},
            "fed": {"readiness_state": "ready", "raw_ingested": True},
            "treasury": {"readiness_state": "ready", "raw_ingested": True},
            "dxy": {"readiness_state": "ready", "raw_ingested": True},
        }

        with (
            patch("apps.api.services.source_service.get_data_source_status_index", return_value=source_status_index),
            patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        ):
            from apps.worker.runner import run_premarket

            result = run_premarket(db, task.id, storage_root=tmp_path)

        assert result == TaskStatus.degraded

        db.refresh(task)
        assert task.status == TaskStatus.degraded
        assert all(step.status == StepStatus.success for step in task.steps)
        events = (
            db.query(ExecutionEvent)
            .filter(ExecutionEvent.run_id == task.id)
            .order_by(ExecutionEvent.created_at.asc(), ExecutionEvent.event_type.asc())
            .all()
        )
        event_types = [event.event_type for event in events]
        assert "SOURCE_READINESS_EVALUATED" in event_types
        assert "SOURCE_FALLBACK_USED" in event_types
