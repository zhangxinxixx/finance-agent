"""Settlement ingestion within the existing task lifecycle; no probability inference."""

from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
from uuid import UUID

from apps.collectors.macro.cme_fed_funds import CMEFedFundsSettlementProvider
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle
from database.models.cme_settlement import ensure_cme_settlement_tables
from database.models.task import TaskRun, TaskStatus, TaskStep, StepStatus, ensure_task_tables
from database.queries.cme_settlement import (
    expected_trade_date,
    preferred_settlement,
    save_settlement,
    settlement_health,
    settlement_stability,
    utc,
)


def run_settlement_ingestion(session, *, storage_root, trade_date=None, now=None, provider=None):
    """One requested date, one immutable attempt. Caller may retry without overwrites."""
    clock = utc(now) if now else datetime.now(UTC)
    day = date.fromisoformat(trade_date) if isinstance(trade_date, str) else trade_date
    day = day or expected_trade_date(clock)
    root = Path(storage_root).resolve()
    ensure_task_tables(session)
    ensure_cme_settlement_tables(session)
    run = TaskRun(
        name="CME Fed Funds settlement ingestion",
        task_type="cme_settlement",
        status=TaskStatus.running,
        started_at=clock,
    )
    session.add(run)
    session.flush()
    step = TaskStep(
        task_run_id=run.id,
        name="cme_settlement_collect_normalize",
        stage="collect",
        status=StepStatus.running,
        started_at=clock,
        step_order=1,
    )
    session.add(step)
    session.commit()
    try:
        collector = provider or CMEFedFundsSettlementProvider()
        observation = collector.collect(trade_date=day, storage_root=root, now=clock if now else None)
        identity = observation["snapshot_id"]
        UUID(identity)
        # Verify actual archived bytes before creating a normalized observation.
        raw = (root / observation["raw_artifact_ref"]).resolve()
        raw.relative_to(root)
        if hashlib.sha256(raw.read_bytes()).hexdigest() != observation["content_hash"]:
            raise ValueError("raw_hash_mismatch")
        observation["collection_mode"] = "live" if provider is None and now is None else "replay"
        parsed_ref = Path("parsed/cme_settlement") / (identity + ".json")
        observation["parsed_artifact_ref"] = parsed_ref.as_posix()
        write_immutable_artifact_bundle([immutable_json_item(root / parsed_ref, observation)], storage_root=root)
        save_settlement(session, observation)
        from apps.data_layer.collection_ingestion import ingest_collection_records

        warehouse_ingestion = ingest_collection_records(
            session, "settlement", record_ids=[identity], storage_root=root, run_id=str(run.id),
            raw_sources=[{"raw_path": observation["raw_artifact_ref"], "source_key": "cme_settlement",
                          "collected_at": observation["observed_at"], "sha256": observation["content_hash"],
                          "expected_records": len(observation["rows"])}],
        )
        evaluated_at = clock if now else datetime.now(UTC)
        preferred = preferred_settlement(session, trade_date=day, as_of=evaluated_at)
        health = settlement_health(observation, as_of=evaluated_at)
        usable = observation["data_status"] == "available"
        expected_empty = health["status"] in {"no_trade_day", "outside_free_retention"}
        run.status = TaskStatus.success if usable or expected_empty else TaskStatus.degraded
        step.status = StepStatus.success if usable or expected_empty else StepStatus.failed
        run.snapshot_id = identity
        step.output_json = json.dumps(
            {
                "snapshot_id": identity,
                "source_health": health,
                "preferred_snapshot_id": preferred["snapshot_id"] if preferred else None,
                "warehouse": warehouse_ingestion,
            }
        )
        step.source_refs = json.dumps(observation["source_refs"])
        step.error = None if usable or expected_empty else observation.get("reason") or health["status"]
        run.error_summary = step.error
        step.finished_at = run.ended_at = evaluated_at
        session.commit()
        return {
            "snapshot_id": identity,
            "task_run_id": str(run.id),
            "source_health": health,
            "preferred_snapshot_id": preferred["snapshot_id"] if preferred else None,
            "contract_count": len(observation["rows"]),
            "warehouse": warehouse_ingestion,
            "raw_artifact_ref": observation["raw_artifact_ref"],
            "parsed_artifact_ref": parsed_ref.as_posix(),
            "stability": settlement_stability(session, as_of=evaluated_at),
        }
    except Exception as exc:
        session.rollback()
        run.status, step.status = TaskStatus.failed, StepStatus.failed
        run.error_summary = step.error = "settlement_worker_" + type(exc).__name__
        step.finished_at = run.ended_at = datetime.now(UTC)
        session.commit()
        raise
