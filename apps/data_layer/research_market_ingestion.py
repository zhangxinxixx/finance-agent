"""Audited research DWD materialization with per-file retention receipts."""
from hashlib import sha256

from sqlalchemy import select

from apps.data_layer.collection_ingestion import _empty_summary, _register_sources
from apps.data_layer.research_market_warehouse import materialize_research_market as _materialize
from database.models.warehouse import LoadBatch
from database.models.warehouse_research_market import ResearchMarketBatch


def materialize_research_market(session, observed, *, run_id, storage_root, kind):
    rebuilt = _materialize(session, observed, run_id=run_id, storage_root=storage_root, kind=kind)
    header = session.get(ResearchMarketBatch, session.info["research_market_batch_id"])
    sources = {}
    groups = [(rebuilt.get("observations", []), False)]
    groups.extend((rebuilt.get(key, []), True) for key in ("chart_series", "execution_chart_series", "series"))
    for rows, is_series in groups:
        for row in rows:
            # The typed series envelope itself is a record even when the
            # provider returned an explicit unavailable result with no bars.
            count = 1 + len(row.get("bars", [])) if is_series else 1
            for ref in {ref.get("raw_path"): ref for ref in row.get("source_refs", []) if ref.get("raw_path")}.values():
                path = ref["raw_path"]
                source = sources.setdefault(path, {"raw_path": path, "source_key": ref.get("source"),
                    "source_url": ref.get("source_url"), "collected_at": ref.get("retrieved_at"), "expected_records": 0})
                source["expected_records"] += count
    summary = _empty_summary("research-market")
    for path, source in sources.items():
        cursor = f"research-market:{header.id}:" + sha256(path.encode()).hexdigest()
        batch = session.scalar(select(LoadBatch).where(LoadBatch.dataset == "research-market", LoadBatch.source_cursor == cursor))
        if batch is None:
            batch = LoadBatch(dataset="research-market", source_cursor=cursor, source_artifact_path=path,
                as_of=header.retrieved_at, transform_version="research-market-v1", status="loaded",
                processed=source["expected_records"], inserted=source["expected_records"], skipped=0, rejected=0,
                audit_task_run_id=header.audit_task_run_id, audit_task_step_id=header.audit_task_step_id)
            session.add(batch)
            session.flush([batch])
        source["source_cursors"] = [cursor]
        summary["load_batch_ids"].append(batch.id)
    _register_sources(session, summary, sources.values(), storage_root=storage_root, run_id=run_id)
    session.info["research_market_ingestion"] = summary
    return rebuilt
