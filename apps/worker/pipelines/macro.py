"""Macro worker pipeline — collect → feature → render.

Chains the existing macro collector, feature, and analysis modules into
the premarket worker flow.  Each step is dispatched by name via
``run_macro_step``.

Produces durable artifacts under run-partitioned paths:
- ``storage/features/macro/<date>/<run_id>/macro_snapshot.json`` — structured MacroSnapshot dict
- ``storage/outputs/macro/<date>/<run_id>/macro_snapshot.md``   — human-readable Markdown table

Never fabricates data; missing sources flow through as
``unavailable_symbols`` in the output.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.analysis.macro.conclusion import build_macro_conclusion
from apps.analysis.macro.full_report import render_macro_full_report_markdown
from apps.analysis.macro.summary import render_macro_snapshot_markdown
from apps.data_layer.models import DualSourceResult
from apps.data_layer.service import DEFAULT_FRED_RATE_SYMBOLS, MacroDataService
from apps.features.macro.snapshot import MacroIndicator, MacroSnapshot, build_macro_snapshot
from apps.output.artifacts import artifact_run_dir
from apps.parsers.macro.models import MacroPoint
from apps.runtime.artifact_registry import register_artifact
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from database.queries.data_source_status import upsert_data_source_status
from database.queries.feature_snapshots import upsert_feature_snapshots as upsert_feature_snapshot_rows
from database.queries.macro_observations import upsert_macro_observations as upsert_macro_observation_rows
from database.queries.report import upsert_report_artifact, upsert_report_item

# ---------------------------------------------------------------------------
# Step names that belong to the macro pipeline
# ---------------------------------------------------------------------------

MACRO_STEPS = {"macro_collect", "macro_feature", "report_render"}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline state — threaded through each step
# ---------------------------------------------------------------------------


@dataclass
class MacroPipelineState:
    """Holds intermediate results for the macro pipeline."""

    all_points: list[MacroPoint] = field(default_factory=list)
    all_unavailable: list[str] = field(default_factory=list)
    all_source_refs: list[dict[str, str]] = field(default_factory=list)
    as_of: str = ""
    snapshot_dict: dict[str, Any] | None = None
    conclusion_dict: dict[str, Any] | None = None
    macro_output: Any | None = None
    report_md: str | None = None
    full_report_md: str | None = None
    step_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def run_macro_step(
    step_name: str,
    state: MacroPipelineState,
    *,
    storage_root: Path = Path("./storage"),
    run_id: str | None = None,
    db_session: Session | None = None,
) -> dict[str, Any]:
    """Execute a single macro pipeline step and update *state*.

    Returns a summary dict for the step (suitable for task logging).

    Raises on failure; the caller is responsible for marking the task step
    as failed.
    """
    dispatch = {
        "macro_collect": _step_collect,
        "macro_feature": _step_feature,
        "report_render": _step_render,
    }

    fn = dispatch.get(step_name)
    if fn is None:
        raise ValueError(f"Unknown macro step: {step_name!r}")

    summary = fn(state, storage_root=storage_root, run_id=run_id, db_session=db_session)
    state.step_summaries[step_name] = summary
    return summary


# ---------------------------------------------------------------------------
# Individual step implementations
# ---------------------------------------------------------------------------


def _step_collect(
    state: MacroPipelineState,
    *,
    storage_root: Path,
    run_id: str | None,
    db_session: Session | None,
) -> dict[str, Any]:
    """Step 1: Collect macro data from FRED, Fed, and Treasury sources.

    Merges all CollectorResults into the shared state.  Individual collector
    failures are non-fatal — the symbol is added to unavailable and the
    remaining collectors continue.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    state.as_of = today

    all_points: list[MacroPoint] = []
    all_unavailable: list[str] = []
    all_refs: list[dict[str, str]] = []
    collector_statuses: list[dict[str, Any]] = []
    fred_fallback_symbols: tuple[str, ...] = DEFAULT_FRED_RATE_SYMBOLS

    # --- FRED ---
    try:
        from apps.collectors.fred.collector import collect_fred_series

        fred_result = collect_fred_series(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(fred_result.points)
        all_unavailable.extend(fred_result.unavailable_symbols)
        all_refs.extend(fred_result.source_refs)
        fred_fallback_symbols = tuple(
            symbol
            for symbol in DEFAULT_FRED_RATE_SYMBOLS
            if symbol in set(fred_result.unavailable_symbols)
        )
        collector_statuses.append({
            "collector": "fred",
            "status": "success",
            "points": len(fred_result.points),
            "unavailable": len(fred_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "fred",
            "status": "failed",
            "error": str(exc),
        })

    # --- Fed ---
    try:
        from apps.collectors.fed.collector import collect_fed_series

        fed_result = collect_fed_series(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(fed_result.points)
        all_unavailable.extend(fed_result.unavailable_symbols)
        all_refs.extend(fed_result.source_refs)
        collector_statuses.append({
            "collector": "fed",
            "status": "success",
            "points": len(fed_result.points),
            "unavailable": len(fed_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "fed",
            "status": "failed",
            "error": str(exc),
        })

    # --- Treasury ---
    try:
        from apps.collectors.treasury.collector import collect_treasury_series

        treasury_result = collect_treasury_series(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(treasury_result.points)
        all_unavailable.extend(treasury_result.unavailable_symbols)
        all_refs.extend(treasury_result.source_refs)
        collector_statuses.append({
            "collector": "treasury",
            "status": "success",
            "points": len(treasury_result.points),
            "unavailable": len(treasury_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "treasury",
            "status": "failed",
            "error": str(exc),
        })

    # --- DXY / TradingView ---
    try:
        from apps.collectors.dxy.collector import collect_dxy_series

        dxy_result = collect_dxy_series(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(dxy_result.points)
        all_unavailable.extend(dxy_result.unavailable_symbols)
        all_refs.extend(dxy_result.source_refs)
        collector_statuses.append({
            "collector": "dxy",
            "status": "success",
            "points": len(dxy_result.points),
            "unavailable": len(dxy_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "dxy",
            "status": "failed",
            "error": str(exc),
        })

    # --- Technical / XAUUSD price ---
    try:
        from apps.collectors.technical.collector import collect_technical

        tech_result = collect_technical(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(tech_result.points)
        all_unavailable.extend(tech_result.unavailable_symbols)
        all_refs.extend(tech_result.source_refs)
        collector_statuses.append({
            "collector": "technical",
            "status": "success",
            "points": len(tech_result.points),
            "unavailable": len(tech_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "technical",
            "status": "failed",
            "error": str(exc),
        })

    # --- Positioning / CFTC COT ---
    try:
        from apps.collectors.positioning.collector import collect_positioning_cot

        pos_result = collect_positioning_cot(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(pos_result.points)
        all_unavailable.extend(pos_result.unavailable_symbols)
        all_refs.extend(pos_result.source_refs)
        collector_statuses.append({
            "collector": "positioning",
            "status": "success",
            "points": len(pos_result.points),
            "unavailable": len(pos_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "positioning",
            "status": "failed",
            "error": str(exc),
        })

    # --- News / Jin10 MCP ---
    try:
        from apps.collectors.news.collector import collect_news

        news_result = collect_news(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(news_result.points)
        all_unavailable.extend(news_result.unavailable_symbols)
        all_refs.extend(news_result.source_refs)
        collector_statuses.append({
            "collector": "news",
            "status": "success",
            "points": len(news_result.points),
            "unavailable": len(news_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "news",
            "status": "failed",
            "error": str(exc),
        })

    # --- Jin10 Quotes / MCP (real-time prices) ---
    try:
        from apps.collectors.jin10.quotes import collect_quotes

        quotes_result = collect_quotes(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(quotes_result.points)
        all_unavailable.extend(quotes_result.unavailable_symbols)
        all_refs.extend(quotes_result.source_refs)
        collector_statuses.append({
            "collector": "jin10_quotes",
            "status": "success",
            "points": len(quotes_result.points),
            "unavailable": len(quotes_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "jin10_quotes",
            "status": "failed",
            "error": str(exc),
        })

    # --- Jin10 K-line / MCP ---
    try:
        from apps.collectors.jin10.kline import collect_kline

        kline_result = collect_kline(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(kline_result.points)
        all_unavailable.extend(kline_result.unavailable_symbols)
        all_refs.extend(kline_result.source_refs)
        dxy_kline_fallback = None
        if not any(point.symbol == "DXY" for point in all_points):
            dxy_kline_fallback = _promote_latest_kline_close(
                kline_result.points,
                code="DXY",
            )
            if dxy_kline_fallback is not None:
                all_points.append(dxy_kline_fallback)
                all_unavailable = [symbol for symbol in all_unavailable if symbol != "DXY"]
        collector_statuses.append({
            "collector": "jin10_kline",
            "status": "success",
            "points": len(kline_result.points) + int(dxy_kline_fallback is not None),
            "unavailable": len(kline_result.unavailable_symbols),
            "dxy_fallback_promoted": dxy_kline_fallback is not None,
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "jin10_kline",
            "status": "failed",
            "error": str(exc),
        })

    # --- Jin10 Articles / MCP ---
    try:
        from apps.collectors.jin10.articles import collect_articles

        articles_result = collect_articles(
            retrieved_date=today,
            storage_root=storage_root,
        )
        all_points.extend(articles_result.points)
        all_unavailable.extend(articles_result.unavailable_symbols)
        all_refs.extend(articles_result.source_refs)
        collector_statuses.append({
            "collector": "jin10_articles",
            "status": "success",
            "points": len(articles_result.points),
            "unavailable": len(articles_result.unavailable_symbols),
        })
    except Exception as exc:
        collector_statuses.append({
            "collector": "jin10_articles",
            "status": "failed",
            "error": str(exc),
        })

    if not fred_fallback_symbols:
        collector_statuses.append({
            "collector": "data_layer_fred_rates",
            "status": "skipped",
            "reason": "official_fred_coverage_complete",
            "requested_symbols": [],
        })
    else:
        data_service = MacroDataService(storage_root=storage_root)
        try:
            fred_fallback = _collect_fred_fallback_with_timeout(
                data_service,
                retrieved_date=today,
                symbols=fred_fallback_symbols,
            )
            fallback_status = _merge_data_layer_result(
                result=fred_fallback,
                collector_name="data_layer_fred_rates",
                all_points=all_points,
                all_unavailable=all_unavailable,
                all_refs=all_refs,
            )
            fallback_status["requested_symbols"] = list(fred_fallback_symbols)
            collector_statuses.append(fallback_status)
        except Exception as exc:
            collector_statuses.append({
                "collector": "data_layer_fred_rates",
                "status": "failed",
                "error": str(exc),
                "requested_symbols": list(fred_fallback_symbols),
            })

    collector_statuses.append({
        "collector": "data_layer_market_prices",
        "status": "skipped",
        "reason": "yahoo_market_collection_disabled",
        "warnings": ["Yahoo market proxy collection is disabled"],
    })

    state.all_points = all_points
    state.all_unavailable = list(dict.fromkeys(all_unavailable))
    state.all_source_refs = all_refs

    data_source_status_upserts = 0
    macro_observation_upserts = 0
    raw_artifact_registry_upserts = 0
    if db_session is not None:
        data_source_status_upserts = _upsert_macro_data_source_statuses(
            db_session,
            collector_statuses=collector_statuses,
            as_of=today,
            run_id=run_id,
        )
        macro_observation_upserts, raw_artifact_registry_upserts = _upsert_macro_point_observations(
            db_session,
            storage_root=storage_root,
            all_points=all_points,
            all_refs=all_refs,
            run_id=run_id,
        )

    return {
        "step": "macro_collect",
        "status": "success",
        "as_of": today,
        "total_points": len(all_points),
        "total_unavailable": len(state.all_unavailable),
        "collectors": collector_statuses,
        "data_source_status_upserts": data_source_status_upserts,
        "macro_observation_upserts": macro_observation_upserts,
        "raw_artifact_registry_upserts": raw_artifact_registry_upserts,
    }


def _collect_fred_fallback_with_timeout(
    data_service: MacroDataService,
    *,
    retrieved_date: str,
    symbols: tuple[str, ...],
) -> DualSourceResult:
    """Run the optional OpenBB fallback without letting it stall a task run.

    OpenBB performs its own provider calls synchronously and does not expose a
    stable request timeout at this boundary.  A daemon worker keeps a stalled
    fallback from blocking the canonical official-data pipeline.  The provider
    call still owns its normal internal cleanup and cannot mutate database state.
    """
    raw_timeout = os.getenv("FINANCE_AGENT_OPENBB_FALLBACK_TIMEOUT_SECONDS", "30")
    try:
        timeout_seconds = max(0.1, min(float(raw_timeout), 120.0))
    except ValueError:
        timeout_seconds = 30.0

    result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

    def _run() -> None:
        try:
            result_queue.put((
                "result",
                data_service.collect_fred_rates(
                    retrieved_date=retrieved_date,
                    symbols=symbols,
                ),
            ))
        except BaseException as exc:  # propagated on the caller thread
            result_queue.put(("error", exc))

    worker = threading.Thread(
        target=_run,
        name="openbb-fred-fallback",
        daemon=True,
    )
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise TimeoutError(
            f"OpenBB FRED fallback exceeded {timeout_seconds:g}s for "
            f"{','.join(symbols)}"
        )

    kind, payload = result_queue.get_nowait()
    if kind == "error":
        assert isinstance(payload, BaseException)
        raise payload
    assert isinstance(payload, DualSourceResult)
    return payload


_MACRO_STATUS_CONTRACTS: dict[str, dict[str, Any]] = {
    "fred": {
        "source_name": "FRED",
        "source_group": "macro",
        "source_type": "api",
        "access_method": "fred_api",
        "metadata": {
            "provider_role": "official_primary",
            "fallback_for": [],
            "fallback_sources": ["openbb_macro", "jin10_news"],
            "frontend_label": "FRED 官方宏观主源",
            "notes": "官方宏观时间序列主源；异常时由 OpenBB 补充，并由 Jin10 提供事件/快讯上下文。",
        },
    },
    "fed": {
        "source_name": "Federal Reserve",
        "source_group": "macro",
        "source_type": "api",
        "access_method": "fed_prates_json",
        "metadata": {
            "provider_role": "official_primary",
            "fallback_for": [],
            "fallback_sources": ["openbb_macro", "jin10_news"],
            "frontend_label": "Federal Reserve 官方源",
        },
    },
    "treasury": {
        "source_name": "US Treasury",
        "source_group": "macro",
        "source_type": "api",
        "access_method": "treasury_fiscaldata",
        "metadata": {
            "provider_role": "official_primary",
            "fallback_for": [],
            "fallback_sources": ["openbb_macro", "jin10_news"],
            "frontend_label": "US Treasury 官方源",
        },
    },
    "dxy": {
        "source_name": "DXY Index",
        "source_group": "macro",
        "source_type": "api",
        "access_method": "tradingview_or_cnbc",
        "metadata": {
            "provider_role": "official_primary",
            "fallback_for": [],
            "fallback_sources": ["openbb_macro", "jin10_news"],
            "frontend_label": "DXY 主行情源",
        },
    },
    "openbb_macro": {
        "source_name": "OpenBB Macro/Market",
        "source_group": "macro",
        "source_type": "api",
        "access_method": "openbb_data_layer",
        "metadata": {
            "provider_role": "fallback",
            "fallback_for": ["fred", "fed", "treasury", "dxy"],
            "fallback_sources": [],
            "frontend_label": "OpenBB 宏观/市场补充源",
            "notes": "补充或回退宏观/市场数据；未写入原始/解析工件时不得视为已入库。",
        },
    },
    "technical_yahoo": {
        "source_name": "Jin10 XAUUSD Technical",
        "source_group": "technical",
        "source_type": "api",
        "access_method": "jin10_mcp",
        "metadata": {
            "provider_role": "supplemental",
            "fallback_for": ["openbb_macro"],
            "fallback_sources": ["jin10_news"],
            "frontend_label": "Jin10 黄金实时/技术补充源",
            "notes": "黄金现货价格与日内 OHLC 使用 Jin10 XAUUSD；历史技术指标不足时显式降级。",
        },
    },
    "positioning_cot": {
        "source_name": "COT Positioning",
        "source_group": "positioning",
        "source_type": "api",
        "access_method": "cftc_api",
        "metadata": {
            "provider_role": "official_primary",
            "fallback_for": [],
            "fallback_sources": [],
            "frontend_label": "COT 官方持仓源",
        },
    },
    "jin10_news": {
        "source_name": "Jin10 News",
        "source_group": "news",
        "source_type": "scraper",
        "access_method": "jin10_mcp",
        "metadata": {
            "provider_role": "supplemental",
            "fallback_for": ["fred", "fed", "treasury", "dxy", "openbb_macro"],
            "fallback_sources": [],
            "frontend_label": "Jin10 新闻/日历补充源",
            "notes": "提供快讯、日历、事件上下文；不应被前端当作官方宏观时间序列主源。",
        },
    },
}

_COLLECTOR_TO_SOURCE_KEY = {
    "fred": "fred",
    "fed": "fed",
    "treasury": "treasury",
    "dxy": "dxy",
    "technical": "technical_yahoo",
    "positioning": "positioning_cot",
    "news": "jin10_news",
}


def _upsert_macro_data_source_statuses(
    db_session: Session,
    *,
    collector_statuses: list[dict[str, Any]],
    as_of: str,
    run_id: str | None,
) -> int:
    """Persist macro collector status rows for the Data Ingestion page."""
    now = datetime.now(timezone.utc)
    by_collector = {item.get("collector"): item for item in collector_statuses}
    upserted = 0

    for collector_name, source_key in _COLLECTOR_TO_SOURCE_KEY.items():
        status = by_collector.get(collector_name, {"collector": collector_name, "status": "not_connected"})
        upsert_data_source_status(
            db_session,
            _build_source_status_payload(
                source_key,
                status,
                now=now,
                as_of=as_of,
                run_id=run_id,
            ),
        )
        upserted += 1

    openbb_statuses = [
        by_collector.get("data_layer_fred_rates", {"collector": "data_layer_fred_rates", "status": "not_connected"}),
        by_collector.get("data_layer_market_prices", {"collector": "data_layer_market_prices", "status": "not_connected"}),
    ]
    upsert_data_source_status(
        db_session,
        _build_openbb_source_status_payload(
            openbb_statuses,
            now=now,
            as_of=as_of,
            run_id=run_id,
        ),
    )
    upserted += 1
    return upserted


def _upsert_macro_point_observations(
    db_session: Session,
    *,
    storage_root: Path,
    all_points: list[MacroPoint],
    all_refs: list[dict[str, str]],
    run_id: str | None,
) -> tuple[int, int]:
    raw_artifact_ids = _register_macro_raw_artifacts(
        db_session,
        storage_root=storage_root,
        all_points=all_points,
        all_refs=all_refs,
        run_id=run_id,
    )
    rows = upsert_macro_observation_rows(
        db_session,
        [
            {
                "source_key": point.source,
                "symbol": point.symbol,
                "observation_date": point.date,
                "value": point.value,
                "source_url": point.source_url,
                "raw_path": point.raw_path,
                "raw_artifact_id": raw_artifact_ids.get(_macro_point_raw_artifact_key(point)),
                "retrieved_at": point.retrieved_at,
                "run_id": run_id,
                "source_refs": _source_refs_for_macro_point(point, all_refs),
                "metadata": {
                    "collector_source": point.source,
                    "point_date": point.date,
                    "raw_path": point.raw_path,
                },
            }
            for point in all_points
        ],
    )
    return len(rows), len(set(raw_artifact_ids.values()))


def persist_macro_points(
    db_session: Session,
    *,
    storage_root: Path,
    all_points: list[MacroPoint],
    all_refs: list[dict[str, str]],
    run_id: str | None,
) -> tuple[int, int]:
    """Persist normalized macro points and their raw-file lineage.

    This narrow public seam is shared by the worker pipeline and the legacy
    backfill script.  It stores observations and artifact references only;
    collector response bodies remain in the file-backed raw layer.
    """
    return _upsert_macro_point_observations(
        db_session,
        storage_root=storage_root,
        all_points=all_points,
        all_refs=all_refs,
        run_id=run_id,
    )


def _register_macro_raw_artifacts(
    db_session: Session,
    *,
    storage_root: Path,
    all_points: list[MacroPoint],
    all_refs: list[dict[str, str]],
    run_id: str | None,
) -> dict[tuple[str, str, str, str], str]:
    # RunArtifact lineage is keyed to a persisted TaskRun UUID. Backfill
    # scripts may use human-readable run labels; observations can still keep
    # those labels, but artifact registration must quietly remain disabled.
    if not _is_uuid_string(run_id):
        return {}

    storage = LocalFileSystemArtifactStorage(root=storage_root)
    registered_by_raw_path: dict[str, str] = {}
    artifact_ids: dict[tuple[str, str, str, str], str] = {}

    for point in all_points:
        raw_path = str(point.raw_path or "").strip()
        if not raw_path:
            continue
        if raw_path not in registered_by_raw_path:
            try:
                row = register_artifact(
                    db_session,
                    run_id=run_id,
                    artifact_type="raw_file",
                    file_path=raw_path,
                    sha256=None,
                    source_refs=_artifact_source_refs_for_macro_point(point, all_refs),
                    metadata={
                        "source_key": point.source,
                        "symbol": point.symbol,
                        "observation_date": point.date,
                        "collector_stage": "macro_collect",
                    },
                    require_canonical_path=False,
                    storage=storage,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to register macro raw artifact: run_id=%s raw_path=%s error=%s",
                    run_id,
                    raw_path,
                    exc,
                )
                continue
            if row is None:
                continue
            registered_by_raw_path[raw_path] = str(row.artifact_id)
        artifact_ids[_macro_point_raw_artifact_key(point)] = registered_by_raw_path[raw_path]

    return artifact_ids


def _macro_point_raw_artifact_key(point: MacroPoint) -> tuple[str, str, str, str]:
    return (point.source, point.symbol, point.date, point.raw_path)


def _source_refs_for_macro_point(point: MacroPoint, refs: list[dict[str, str]]) -> list[dict[str, str]]:
    matched: list[dict[str, str]] = []
    for ref in refs:
        ref_symbol = ref.get("symbol")
        ref_source = ref.get("source")
        ref_raw_path = ref.get("raw_path")
        if ref_symbol and ref_symbol != point.symbol:
            continue
        if ref_source and ref_source != point.source:
            continue
        if ref_raw_path and ref_raw_path != point.raw_path:
            continue
        if ref_symbol or ref_source or ref_raw_path:
            matched.append(dict(ref))

    if matched:
        return matched

    return [
        {
            "symbol": point.symbol,
            "source": point.source,
            "source_url": point.source_url,
            "raw_path": point.raw_path,
        }
    ]


def _artifact_source_refs_for_macro_point(point: MacroPoint, refs: list[dict[str, str]]) -> list[dict[str, str]]:
    artifact_refs: list[dict[str, str]] = []
    for ref in _source_refs_for_macro_point(point, refs):
        enriched = dict(ref)
        enriched.setdefault("symbol", point.symbol)
        enriched.setdefault("source", point.source)
        enriched.setdefault("source_url", point.source_url)
        enriched.setdefault("raw_path", point.raw_path)
        artifact_refs.append(enriched)
    return artifact_refs


def _build_source_status_payload(
    source_key: str,
    collector_status: dict[str, Any],
    *,
    now: datetime,
    as_of: str,
    run_id: str | None,
) -> dict[str, Any]:
    contract = _MACRO_STATUS_CONTRACTS[source_key]
    status = _collector_status_to_source_status(collector_status)
    points = int(collector_status.get("points") or 0)
    unavailable = int(collector_status.get("unavailable") or 0)
    error = collector_status.get("error")
    has_raw = points > 0
    is_failed = status == "failed"
    metadata = {
        **contract["metadata"],
        "collector": collector_status.get("collector"),
        "collector_status": collector_status.get("status"),
        "collector_points": points,
        "collector_unavailable": unavailable,
        "as_of": as_of,
    }
    return {
        "source_key": source_key,
        "source_name": contract["source_name"],
        "source_group": contract["source_group"],
        "source_type": contract["source_type"],
        "access_method": contract["access_method"],
        "configured": True,
        "raw_ingested": has_raw,
        "parsed": has_raw,
        "analysis_ready": has_raw and not is_failed,
        "latest_raw_time": now if has_raw else None,
        "latest_parsed_time": now if has_raw else None,
        "latest_snapshot_id": run_id,
        "row_count": points,
        "status": status,
        "error_message": str(error) if error else None,
        "last_run_id": run_id,
        "next_run_time": None,
        "source_metadata": metadata,
    }


def _build_openbb_source_status_payload(
    statuses: list[dict[str, Any]],
    *,
    now: datetime,
    as_of: str,
    run_id: str | None,
) -> dict[str, Any]:
    contract = _MACRO_STATUS_CONTRACTS["openbb_macro"]
    points = sum(int(item.get("added_points") or 0) for item in statuses)
    unavailable = sum(int(item.get("unavailable") or 0) for item in statuses)
    failed = [item for item in statuses if item.get("status") == "failed"]
    attempted = any(item.get("status") not in {None, "not_connected"} for item in statuses)
    usable_attempt = any(item.get("status") in {"success", "partial", "skipped"} for item in statuses)
    has_raw = points > 0
    if failed and len(failed) == len(statuses):
        status = "failed"
    elif has_raw and unavailable:
        status = "partial"
    elif has_raw:
        status = "ok"
    elif attempted:
        status = "partial"
    else:
        status = "not_connected"
    metadata = {
        **contract["metadata"],
        "collector_statuses": statuses,
        "collector_points": points,
        "collector_unavailable": unavailable,
        "as_of": as_of,
    }
    return {
        "source_key": "openbb_macro",
        "source_name": contract["source_name"],
        "source_group": contract["source_group"],
        "source_type": contract["source_type"],
        "access_method": contract["access_method"],
        "configured": has_raw or usable_attempt,
        "raw_ingested": has_raw,
        "parsed": has_raw,
        "analysis_ready": has_raw,
        "latest_raw_time": now if has_raw else None,
        "latest_parsed_time": now if has_raw else None,
        "latest_snapshot_id": run_id,
        "row_count": points,
        "status": status,
        "error_message": "; ".join(str(item.get("error")) for item in failed if item.get("error")) or None,
        "last_run_id": run_id,
        "next_run_time": None,
        "source_metadata": metadata,
    }


def _collector_status_to_source_status(collector_status: dict[str, Any]) -> str:
    status = collector_status.get("status")
    if status == "failed":
        return "failed"
    points = int(collector_status.get("points") or 0)
    unavailable = int(collector_status.get("unavailable") or 0)
    if points and unavailable:
        return "partial"
    if points:
        return "ok"
    if unavailable:
        return "partial"
    if status in {"success", "skipped"}:
        return "ok"
    return "not_connected"


def _merge_data_layer_result(
    *,
    result: DualSourceResult,
    collector_name: str,
    all_points: list[MacroPoint],
    all_unavailable: list[str],
    all_refs: list[dict[str, str]],
    symbol_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    symbol_aliases = symbol_aliases or {}
    existing_symbols = {point.symbol for point in all_points}
    transformed_points = [
        _canonicalize_macro_point(point, symbol_aliases=symbol_aliases)
        for point in result.points
    ]

    points_to_add: list[MacroPoint] = []
    duplicate_points = 0
    for point in transformed_points:
        if point.symbol in existing_symbols:
            duplicate_points += 1
            continue
        points_to_add.append(point)
        existing_symbols.add(point.symbol)

    if points_to_add:
        all_points.extend(points_to_add)
        resolved_symbols = {point.symbol for point in points_to_add}
        all_unavailable[:] = [symbol for symbol in all_unavailable if symbol not in resolved_symbols]

    for symbol in result.unavailable_symbols:
        canonical_symbol = symbol_aliases.get(symbol, symbol)
        if canonical_symbol not in existing_symbols:
            all_unavailable.append(canonical_symbol)

    all_refs.extend(result.source_refs)

    status = "success"
    if points_to_add and result.unavailable_symbols:
        status = "partial"
    elif result.unavailable_symbols:
        status = "partial"
    elif not points_to_add:
        status = "skipped"

    return {
        "collector": collector_name,
        "status": status,
        "source_used": result.source_used,
        "points": len(result.points),
        "added_points": len(points_to_add),
        "duplicate_points": duplicate_points,
        "unavailable": len(result.unavailable_symbols),
        "warnings": list(result.warnings),
    }


def _canonicalize_macro_point(
    point: MacroPoint,
    *,
    symbol_aliases: dict[str, str],
) -> MacroPoint:
    canonical_symbol = symbol_aliases.get(point.symbol)
    if canonical_symbol is None:
        return point
    return MacroPoint(
        symbol=canonical_symbol,
        date=point.date,
        value=point.value,
        source=point.source,
        source_url=point.source_url,
        retrieved_at=point.retrieved_at,
        raw_path=point.raw_path,
    )


def _promote_latest_kline_close(
    points: list[MacroPoint],
    *,
    code: str,
) -> MacroPoint | None:
    """Promote a collected intraday close into a canonical macro fallback."""

    prefix = f"KLINE:{code}:"
    candidates = [point for point in points if point.symbol.startswith(prefix)]
    if not candidates:
        return None

    def candle_timestamp(point: MacroPoint) -> int:
        try:
            return int(point.symbol.rsplit(":", 1)[-1])
        except ValueError:
            return -1

    latest = max(candidates, key=candle_timestamp)
    return MacroPoint(
        symbol=code,
        date=latest.date,
        value=latest.value,
        source=latest.source,
        source_url=latest.source_url,
        retrieved_at=latest.retrieved_at,
        raw_path=latest.raw_path,
    )


def _step_feature(
    state: MacroPipelineState,
    *,
    storage_root: Path,
    run_id: str | None,
    db_session: Session | None,
) -> dict[str, Any]:
    """Step 2: Build macro snapshot from collected data points.

    Calls ``build_macro_snapshot`` which computes indicators, spreads, and
    direction notes.  Markers ``unavailable_symbols`` and ``source_refs``
    are preserved from the collect step.
    """
    if not state.as_of:
        raise RuntimeError("macro_feature requires macro_collect to have completed first")

    snapshot = build_macro_snapshot(
        [p.to_dict() for p in state.all_points],
        as_of=state.as_of,
        unavailable_symbols=state.all_unavailable,
        source_refs=state.all_source_refs,
    )

    state.snapshot_dict = snapshot.to_dict()
    return {
        "step": "macro_feature",
        "status": "success",
        "as_of": state.as_of,
        "indicator_count": len(snapshot.indicators),
        "unavailable_count": len(snapshot.unavailable_symbols),
    }


def _step_render(
    state: MacroPipelineState,
    *,
    storage_root: Path,
    run_id: str | None,
    db_session: Session | None,
) -> dict[str, Any]:
    """Step 3: Render macro snapshot to JSON and Markdown artifacts.

    Writes ``storage/features/macro/<date>/<run_id>/macro_snapshot.json`` and
    ``storage/outputs/macro/<date>/<run_id>/macro_snapshot.md``.
    """
    if state.snapshot_dict is None:
        raise RuntimeError("report_render requires macro_feature to have completed first")

    # Reconstruct MacroSnapshot from dict for the Markdown renderer
    snapshot = _snapshot_from_dict(state.snapshot_dict)
    conclusion = build_macro_conclusion(snapshot)
    report_md = render_macro_snapshot_markdown(snapshot)
    full_report_md = render_macro_full_report_markdown(snapshot, conclusion, macro_output=state.macro_output)
    state.conclusion_dict = conclusion.to_dict()
    state.report_md = report_md
    state.full_report_md = full_report_md

    features_dir = artifact_run_dir(
        storage_root,
        layer="features",
        domain="macro",
        date=state.as_of,
        run_id=run_id,
    )
    outputs_dir = artifact_run_dir(
        storage_root,
        layer="outputs",
        domain="macro",
        date=state.as_of,
        run_id=run_id,
    )
    features_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    json_path = features_dir / "macro_snapshot.json"
    json_path.write_text(
        json.dumps(state.snapshot_dict, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    md_path = outputs_dir / "macro_snapshot.md"
    md_path.write_text(report_md, encoding="utf-8")

    conclusion_path = features_dir / "macro_conclusion.json"
    conclusion_path.write_text(
        json.dumps(state.conclusion_dict, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    full_md_path = outputs_dir / "macro_full_report.md"
    full_md_path.write_text(full_report_md, encoding="utf-8")

    feature_snapshot_upserts = 0
    render_artifact_registry_upserts = 0
    report_registry_upserts = 0
    if db_session is not None:
        feature_snapshot_upserts = _upsert_macro_feature_snapshots(
            db_session,
            snapshot_payload=state.snapshot_dict,
            conclusion_payload=state.conclusion_dict,
            snapshot_artifact_path=json_path,
            conclusion_artifact_path=conclusion_path,
            trade_date=state.as_of,
            run_id=run_id,
            source_refs=state.all_source_refs,
            unavailable_symbols=state.all_unavailable,
        )
        render_artifact_registry_upserts = _register_macro_render_artifacts(
            db_session,
            storage_root=storage_root,
            run_id=run_id,
            trade_date=state.as_of,
            snapshot_path=json_path,
            conclusion_path=conclusion_path,
            report_path=md_path,
            full_report_path=full_md_path,
            source_refs=state.all_source_refs,
        )
        report_registry_upserts = _register_macro_report_registry_entries(
            db_session,
            run_id=run_id,
            trade_date=state.as_of,
            snapshot_path=json_path,
            conclusion_path=conclusion_path,
            report_path=md_path,
            full_report_path=full_md_path,
            source_refs=state.all_source_refs,
        )

    return {
        "step": "report_render",
        "status": "success",
        "as_of": state.as_of,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "conclusion_path": str(conclusion_path),
        "full_md_path": str(full_md_path),
        "source_refs_count": len(state.all_source_refs),
        "unavailable_count": len(state.all_unavailable),
        "feature_snapshot_upserts": feature_snapshot_upserts,
        "render_artifact_registry_upserts": render_artifact_registry_upserts,
        "report_registry_upserts": report_registry_upserts,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _upsert_macro_feature_snapshots(
    db_session: Session,
    *,
    snapshot_payload: dict[str, Any],
    conclusion_payload: dict[str, Any],
    snapshot_artifact_path: Path,
    conclusion_artifact_path: Path,
    trade_date: str,
    run_id: str | None,
    source_refs: list[dict[str, Any]],
    unavailable_symbols: list[str],
) -> int:
    if not run_id:
        return 0

    snapshot_id = _feature_snapshot_id("macro", "macro_snapshot", trade_date, run_id)
    conclusion_snapshot_id = _feature_snapshot_id("macro", "macro_conclusion", trade_date, run_id)
    snapshot_source_refs = _feature_snapshot_source_refs(snapshot_payload, source_refs)
    status = "partial" if unavailable_symbols else "success"

    rows = upsert_feature_snapshot_rows(
        db_session,
        [
            {
                "snapshot_id": snapshot_id,
                "domain": "macro",
                "snapshot_kind": "macro_snapshot",
                "asset": "XAUUSD",
                "trade_date": trade_date,
                "run_id": run_id,
                "status": status,
                "payload": snapshot_payload,
                "artifact_path": str(snapshot_artifact_path),
                "source_refs": snapshot_source_refs,
                "input_snapshot_ids": {},
                "metadata": {
                    "pipeline_step": "report_render",
                    "artifact_name": "macro_snapshot.json",
                    "unavailable_count": len(unavailable_symbols),
                    "source_refs_count": len(snapshot_source_refs),
                },
            },
            {
                "snapshot_id": conclusion_snapshot_id,
                "domain": "macro",
                "snapshot_kind": "macro_conclusion",
                "asset": "XAUUSD",
                "trade_date": trade_date,
                "run_id": run_id,
                "status": status,
                "payload": conclusion_payload,
                "artifact_path": str(conclusion_artifact_path),
                "source_refs": snapshot_source_refs,
                "input_snapshot_ids": {"macro_snapshot": snapshot_id},
                "metadata": {
                    "pipeline_step": "report_render",
                    "artifact_name": "macro_conclusion.json",
                    "unavailable_count": len(unavailable_symbols),
                    "source_refs_count": len(snapshot_source_refs),
                },
            },
        ],
    )
    return len(rows)


def persist_macro_feature_snapshots(
    db_session: Session,
    *,
    snapshot_payload: dict[str, Any],
    conclusion_payload: dict[str, Any],
    snapshot_artifact_path: Path,
    conclusion_artifact_path: Path,
    trade_date: str,
    run_id: str | None,
    source_refs: list[dict[str, Any]],
    unavailable_symbols: list[str],
) -> int:
    """Persist the computed macro snapshot and conclusion payloads."""
    return _upsert_macro_feature_snapshots(
        db_session,
        snapshot_payload=snapshot_payload,
        conclusion_payload=conclusion_payload,
        snapshot_artifact_path=snapshot_artifact_path,
        conclusion_artifact_path=conclusion_artifact_path,
        trade_date=trade_date,
        run_id=run_id,
        source_refs=source_refs,
        unavailable_symbols=unavailable_symbols,
    )


def _register_macro_render_artifacts(
    db_session: Session,
    *,
    storage_root: Path,
    run_id: str | None,
    trade_date: str,
    snapshot_path: Path,
    conclusion_path: Path,
    report_path: Path,
    full_report_path: Path,
    source_refs: list[dict[str, Any]],
) -> int:
    if not _is_uuid_string(run_id):
        return 0

    snapshot_id = _feature_snapshot_id("macro", "macro_snapshot", trade_date, str(run_id))
    conclusion_snapshot_id = _feature_snapshot_id("macro", "macro_conclusion", trade_date, str(run_id))
    registry_storage = _macro_registry_storage(storage_root)
    artifact_specs = [
        ("macro_snapshot", "feature_json", snapshot_path, snapshot_id, {}),
        ("macro_conclusion", "feature_json", conclusion_path, conclusion_snapshot_id, {"macro_snapshot": snapshot_id}),
        ("macro_snapshot_report", "analysis_md", report_path, snapshot_id, {"macro_snapshot": snapshot_id}),
        ("macro_full_report", "analysis_md", full_report_path, conclusion_snapshot_id, {"macro_snapshot": snapshot_id}),
    ]

    upserted = 0
    for artifact_name, artifact_type, artifact_path, feature_snapshot_id, input_snapshot_ids in artifact_specs:
        try:
            row = register_artifact(
                db_session,
                run_id=str(run_id),
                artifact_type=artifact_type,
                file_path=_macro_registry_file_path(artifact_path, storage_root=storage_root),
                source_refs=source_refs,
                input_snapshot_ids=input_snapshot_ids,
                metadata={
                    "source_key": "macro",
                    "pipeline_step": "report_render",
                    "artifact_name": artifact_path.name,
                    "macro_artifact_name": artifact_name,
                    "feature_snapshot_id": feature_snapshot_id,
                },
                storage=registry_storage,
            )
        except Exception as exc:
            logger.warning(
                "Failed to register macro render artifact: run_id=%s artifact_path=%s error=%s",
                run_id,
                artifact_path,
                exc,
            )
            continue
        if row is not None:
            upserted += 1
    return upserted


def _register_macro_report_registry_entries(
    db_session: Session,
    *,
    run_id: str | None,
    trade_date: str,
    snapshot_path: Path,
    conclusion_path: Path,
    report_path: Path,
    full_report_path: Path,
    source_refs: list[dict[str, Any]],
) -> int:
    if not run_id:
        return 0

    report_id = f"macro_report:{run_id}"
    input_snapshot_ids = {
        "macro_snapshot": _feature_snapshot_id("macro", "macro_snapshot", trade_date, run_id),
        "macro_conclusion": _feature_snapshot_id("macro", "macro_conclusion", trade_date, run_id),
    }
    artifact_specs = [
        ("macro_snapshot_report", "analysis_md", report_path, False, "text/markdown"),
        ("macro_full_report", "analysis_md", full_report_path, True, "text/markdown"),
        ("macro_snapshot", "structured_json", snapshot_path, False, "application/json"),
        ("macro_conclusion", "structured_json", conclusion_path, False, "application/json"),
    ]

    try:
        with db_session.begin_nested():
            upsert_report_item(
                db_session,
                {
                    "report_id": report_id,
                    "family": "macro_report",
                    "report_type": "macro_report",
                    "title": f"XAUUSD 宏观分析报告（{trade_date}）",
                    "asset": "XAUUSD",
                    "trade_date": trade_date,
                    "run_id": run_id,
                    "snapshot_id": input_snapshot_ids["macro_snapshot"],
                    "data_status": "live",
                    "lifecycle_status": "generated",
                    "source_refs": source_refs,
                    "metadata": {
                        "input_snapshot_ids": input_snapshot_ids,
                        "writer": "macro.report_render",
                    },
                },
            )
            artifact_count = 0
            for artifact_name, artifact_type, artifact_path, is_primary, content_type in artifact_specs:
                upsert_report_artifact(
                    db_session,
                    _macro_report_artifact_payload(
                        report_id=report_id,
                        artifact_name=artifact_name,
                        artifact_type=artifact_type,
                        artifact_path=artifact_path,
                        content_type=content_type,
                        is_primary=is_primary,
                        source_refs=source_refs,
                        input_snapshot_ids=input_snapshot_ids,
                    ),
                )
                artifact_count += 1
            db_session.flush()
            return 1 + artifact_count
    except Exception as exc:
        logger.warning(
            "Failed to register macro report registry entries: run_id=%s trade_date=%s error=%s",
            run_id,
            trade_date,
            exc,
        )
        return 0


def _macro_report_artifact_payload(
    *,
    report_id: str,
    artifact_name: str,
    artifact_type: str,
    artifact_path: Path,
    content_type: str,
    is_primary: bool,
    source_refs: list[dict[str, Any]],
    input_snapshot_ids: dict[str, str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": f"{report_id}:{artifact_name}",
        "report_id": report_id,
        "artifact_type": artifact_type,
        "file_path": str(artifact_path),
        "storage_backend": "local_fs",
        "status": "generated",
        "content_type": content_type,
        "is_primary": is_primary,
        "source_refs": source_refs,
        "metadata": {
            "input_snapshot_ids": input_snapshot_ids,
            "macro_artifact_name": artifact_name,
            "pipeline_step": "report_render",
        },
    }
    try:
        stat_result = artifact_path.stat()
    except OSError:
        return payload

    payload["byte_size"] = stat_result.st_size
    payload["generated_at"] = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat()
    payload["sha256"] = LocalFileSystemArtifactStorage().compute_sha256(str(artifact_path))
    return payload


def _macro_registry_storage(storage_root: Path) -> LocalFileSystemArtifactStorage:
    root = storage_root.resolve()
    if root.name == "storage":
        return LocalFileSystemArtifactStorage(root=root.parent)
    return LocalFileSystemArtifactStorage(root=root)


def _macro_registry_file_path(path: Path, *, storage_root: Path) -> str:
    root = storage_root.resolve()
    relative_path = path.resolve().relative_to(root)
    if root.name == "storage":
        return (Path(root.name) / relative_path).as_posix()
    return relative_path.as_posix()


def _is_uuid_string(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _feature_snapshot_id(domain: str, snapshot_kind: str, trade_date: str, run_id: str) -> str:
    return f"feature:{domain}:{snapshot_kind}:{trade_date}:{run_id}"


def _feature_snapshot_source_refs(
    snapshot_payload: dict[str, Any],
    source_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if source_refs:
        return [dict(ref) for ref in source_refs]

    raw_refs = snapshot_payload.get("source_refs") or {}
    if isinstance(raw_refs, dict):
        normalized: list[dict[str, Any]] = []
        for symbol, ref in raw_refs.items():
            if not isinstance(ref, dict):
                continue
            item = dict(ref)
            item.setdefault("symbol", symbol)
            normalized.append(item)
        return normalized

    if isinstance(raw_refs, list):
        return [dict(ref) for ref in raw_refs if isinstance(ref, dict)]

    return []


def _snapshot_from_dict(data: dict[str, Any]) -> MacroSnapshot:
    """Reconstruct a MacroSnapshot from its dict representation."""

    indicators: dict[str, MacroIndicator] = {}
    for symbol, ind_dict in data.get("indicators", {}).items():
        indicators[symbol] = MacroIndicator(
            symbol=ind_dict["symbol"],
            date=ind_dict["date"],
            value=ind_dict["value"],
            daily_change=ind_dict.get("daily_change"),
            weekly_change=ind_dict.get("weekly_change"),
            monthly_change=ind_dict.get("monthly_change"),
            label=ind_dict.get("label", ""),
            unit=ind_dict.get("unit", ""),
            direction_note=ind_dict.get("direction_note", ""),
        )

    return MacroSnapshot(
        as_of=data["as_of"],
        indicators=indicators,
        unavailable_symbols=data.get("unavailable_symbols", []),
        source_refs=data.get("source_refs", {}),
    )
