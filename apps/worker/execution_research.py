"""Refresh expired execution bars after research, before freezing the snapshot."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from apps.collectors.market.tradingview_chart import collect_tradingview_chart
from apps.features.research.tradingview_execution import (
    merge_tradingview_execution,
    stale_execution_timeframes,
)
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle


def refresh_execution_snapshot(snapshot, *, storage_root, collector=collect_tradingview_chart, db_session=None):
    result = deepcopy(snapshot)
    existing = result.get("daily_research", {}).get("execution_timeframes")
    requested = stale_execution_timeframes(
        existing, as_of=datetime.now(UTC).isoformat(), analysis_date=result["trade_date"],
    )
    if not requested:
        return result

    resolutions = {"15m": "15", "1h": "60", "4h": "240"}

    def collect(key):
        return collector(retrieved_date=result["trade_date"], storage_root=storage_root,
                         symbols=("OANDA:XAUUSD",), resolution=resolutions[key], bar_count=256)

    with ThreadPoolExecutor(max_workers=3) as executor:
        observations = list(executor.map(collect, requested))
    from apps.data_layer.research_market_ingestion import materialize_research_market
    observations = [materialize_research_market(db_session, item, run_id=result["run_id"],
                    storage_root=storage_root, kind="execution") for item in observations]
    now = datetime.now(UTC).isoformat()
    frames = merge_tradingview_execution(
        existing, [s for item in observations for s in item["series"]],
        as_of=now, analysis_date=result["trade_date"],
    )
    refs = [ref for item in observations for ref in item.get("source_refs", [])]
    feature = {"as_of": now, "requested_timeframes": requested, "execution_timeframes": frames,
               "source_refs": refs, "parsed_paths": [item["parsed_path"] for item in observations]}
    root = Path(storage_root)
    refresh_item = immutable_json_item("refresh.json", feature)
    digest = hashlib.sha256(refresh_item.content).hexdigest()
    path = root / "features" / "research_execution" / result["trade_date"] / result["run_id"] / f"refresh-{digest}.json"
    write_immutable_artifact_bundle([immutable_json_item(path, feature)], storage_root=root)
    result.setdefault("daily_research", {})["execution_timeframes"] = frames
    result.setdefault("input_snapshot_ids", {})["execution_refresh"] = str(path.relative_to(root))
    result.setdefault("source_refs", []).extend(refs)
    result["snapshot_time"] = now
    return result
