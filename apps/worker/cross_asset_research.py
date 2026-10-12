"""TV research enrichment inside the existing merge TaskStep."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from apps.collectors.market.tradingview_research import collect_tradingview_research
from apps.features.research.cross_asset import build_cross_asset_features
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle


def enrich_cross_asset_snapshot(snapshot, *, storage_root, collector=collect_tradingview_research, db_session=None):
    result = deepcopy(snapshot)
    observed = collector(retrieved_date=snapshot["trade_date"], storage_root=storage_root)
    from apps.data_layer.research_market_ingestion import materialize_research_market
    observed = materialize_research_market(db_session, observed, run_id=snapshot["run_id"], storage_root=storage_root, kind="cross_asset")
    from apps.features.research.multi_horizon import snapshot_window_anchors
    observed = {**observed, 'window_anchors': snapshot_window_anchors(snapshot)}
    now = datetime.now(UTC).isoformat()
    feature = build_cross_asset_features(observed, as_of=now)
    feature["parsed_path"] = observed["parsed_path"]
    if observed.get("chart_parsed_path"):
        feature["chart_parsed_path"] = observed["chart_parsed_path"]
    path = Path(storage_root) / "features" / "research_cross_asset" / snapshot["trade_date"] / snapshot["run_id"] / "tradingview.json"
    write_immutable_artifact_bundle([immutable_json_item(path, feature)], storage_root=storage_root)
    result["tradingview_cross_asset"] = feature
    result["input_snapshot_ids"]["tradingview_cross_asset"] = str(path.relative_to(Path(storage_root)))
    result["source_refs"].extend(feature["source_refs"])
    result["snapshot_time"] = now
    from apps.features.research.tradingview_execution import merge_tradingview_execution
    research = result.setdefault("daily_research", {})
    research["execution_timeframes"] = merge_tradingview_execution(
        research.get("execution_timeframes"), observed.get("execution_chart_series", []),
        as_of=now, analysis_date=snapshot["trade_date"],
    )
    return result
