from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from database.queries.analysis import (
    get_analysis_snapshot as _default_get_analysis_snapshot,
    upsert_agent_output as _default_upsert_agent_output,
    upsert_analysis_snapshot as _default_upsert_analysis_snapshot,
    upsert_final_analysis_result as _default_upsert_final_analysis_result,
)

logger = logging.getLogger(__name__)


def db_persist_analysis_snapshot(
    db: DBSession,
    snapshot: dict[str, Any],
    artifact_path: Path,
) -> str:
    """Persist analysis snapshot to DB via idempotent upsert."""
    payload = {
        "snapshot_id": snapshot["snapshot_id"],
        "asset": snapshot.get("asset", "XAUUSD"),
        "trade_date": snapshot["trade_date"],
        "run_id": snapshot["run_id"],
        "snapshot_time": snapshot.get("snapshot_time"),
        "status": snapshot.get("status", "success"),
        "input_snapshot_ids": snapshot.get("input_snapshot_ids", {}),
        "source_refs": snapshot.get("source_refs", []),
        "macro": snapshot.get("macro"),
        "options": snapshot.get("options"),
        "positioning": snapshot.get("positioning"),
        "news": snapshot.get("news"),
        "technical": snapshot.get("technical"),
        "payload": snapshot,
    }
    result = _runner_patchable("upsert_analysis_snapshot", _default_upsert_analysis_snapshot)(db, payload, str(artifact_path))
    db.commit()
    logger.info("DB: persisted analysis snapshot %s", result.snapshot_id)
    return result.id


def db_persist_agent_outputs(
    db: DBSession,
    snapshot: dict[str, Any],
    agents: dict[str, Any],
    run_id: str,
) -> str | None:
    """Persist all composite-analysis agent outputs to DB via idempotent upsert."""
    snapshot_id = snapshot.get("snapshot_id", "")
    trade_date = snapshot.get("trade_date", "")

    snap = _runner_patchable("get_analysis_snapshot", _default_get_analysis_snapshot)(db, "XAUUSD", trade_date, run_id)
    snapshot_db_id = snap.id if snap else None

    for agent_name, ao in agents.items():
        if ao is None:
            continue
        payload = {
            "snapshot_id": snapshot_id,
            "analysis_snapshot_db_id": snapshot_db_id,
            "asset": "XAUUSD",
            "trade_date": trade_date,
            "run_id": run_id,
            "agent_name": ao.agent_name,
            "module": ao.module,
            "version": ao.version,
            "status": ao.status.value,
            "bias": ao.bias.value,
            "confidence": float(ao.confidence),
            "input_snapshot_ids": dict(ao.input_snapshot_ids),
            "source_refs": list(ao.source_refs),
            "key_findings": list(ao.key_findings),
            "risk_points": list(ao.risk_points),
            "watchlist": list(ao.watchlist),
            "invalid_conditions": list(ao.invalid_conditions),
            "summary": ao.summary,
            "payload": ao.model_dump(mode="json"),
        }
        _runner_patchable("upsert_agent_output", _default_upsert_agent_output)(db, payload)
        logger.info("DB: persisted agent output %s/%s", agent_name, ao.module)

    db.commit()
    return snapshot_db_id


def db_persist_final_result(
    db: DBSession,
    snapshot: dict[str, Any],
    composite_outputs: dict[str, Any],
    snapshot_db_id: str | None,
) -> None:
    """Persist composite analysis final result via idempotent upsert."""
    card = composite_outputs["strategy_card"]
    report_result = composite_outputs["report_result"]
    card_result = composite_outputs["card_result"]
    agents = composite_outputs["agents"]
    gold_runtime_summary = composite_outputs.get("gold_runtime_summary")

    trade_date = snapshot.get("trade_date", "")
    run_id = snapshot["run_id"]
    snapshot_id = snapshot.get("snapshot_id", "")

    report_paths = report_result.get("paths", [])
    card_paths = card_result.get("paths", [])
    final_report_path = report_paths[0] if report_paths else None
    sc_json_path = card_paths[0] if len(card_paths) > 0 else None
    sc_md_path = card_paths[1] if len(card_paths) > 1 else None

    final_report_sha256 = _file_sha256(final_report_path)
    strategy_card_sha256 = _file_sha256(sc_json_path)

    source_agent_outputs: list[dict[str, Any]] = []
    for agent_name, ao in agents.items():
        if ao is not None:
            source_agent_outputs.append(
                {
                    "agent_name": ao.agent_name,
                    "module": ao.module,
                    "snapshot_id": ao.snapshot_id,
                    "bias": ao.bias.value,
                    "confidence": ao.confidence,
                }
            )

    payload = {
        "asset": "XAUUSD",
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "analysis_snapshot_db_id": snapshot_db_id,
        "final_bias": card.bias.value,
        "confidence": float(card.confidence),
        "market_state": "premarket",
        "scenario_summary": card.scenario_summary,
        "is_trade_instruction": False,
        "input_snapshot_ids": dict(card.input_snapshot_ids),
        "source_refs": list(card.source_refs),
        "source_agent_outputs": source_agent_outputs,
        "risk_points": list(card.risk_points),
        "watchlist": list(card.watchlist),
        "invalid_conditions": list(card.invalid_conditions),
        "strategy_card": card.model_dump(mode="json"),
        "run_summaries": {"gold_runtime_summary": gold_runtime_summary} if isinstance(gold_runtime_summary, dict) else {},
        "payload": card.model_dump(mode="json"),
    }

    paths = {
        "final_report_path": final_report_path,
        "strategy_card_json_path": sc_json_path,
        "strategy_card_md_path": sc_md_path,
        "run_summary_path": None,
        "final_report_sha256": final_report_sha256,
        "strategy_card_sha256": strategy_card_sha256,
    }

    _runner_patchable("upsert_final_analysis_result", _default_upsert_final_analysis_result)(db, payload, paths)
    db.commit()
    logger.info("DB: persisted final analysis result for run %s", run_id)

    ensure_review_items(
        db,
        run_id=run_id,
        trade_date=trade_date,
        card=card,
        agents=agents,
    )


def ensure_review_items(
    db: Any,
    *,
    run_id: str,
    trade_date: str,
    card: Any,
    agents: dict[str, Any],
) -> None:
    """Auto-create review items for low-confidence or data-gap premarket runs."""
    review_batch: list[dict[str, Any]] = []

    if card.confidence < 0.5:
        review_batch.append(
            {
                "review_id": f"{run_id}:low_confidence",
                "run_id": run_id,
                "source_module": "coordinator",
                "source_step_id": "strategy_card",
                "severity": "warning",
                "reason": f"策略卡置信度 {card.confidence:.0%}，低于 50% 阈值",
                "impact_modules": ["dashboard", "strategy"],
                "suggested_action": "人工复核策略结论与数据来源",
                "status": "pending",
            }
        )

    for agent_name, ao in agents.items():
        if ao is None:
            review_batch.append(
                {
                    "review_id": f"{run_id}:agent_missing:{agent_name}",
                    "run_id": run_id,
                    "source_module": agent_name,
                    "source_step_id": agent_name,
                    "severity": "error",
                    "reason": f"Agent {agent_name} 输出缺失",
                    "impact_modules": ["dashboard", "strategy"],
                    "suggested_action": "检查上游采集器与解析链路",
                    "status": "pending",
                }
            )
        elif ao.confidence is not None and ao.confidence < 0.3:
            review_batch.append(
                {
                    "review_id": f"{run_id}:agent_low_confidence:{agent_name}",
                    "run_id": run_id,
                    "source_module": agent_name,
                    "source_step_id": agent_name,
                    "severity": "warning",
                    "reason": f"Agent {agent_name} 置信度 {ao.confidence:.0%}，低于 30%",
                    "impact_modules": ["dashboard"],
                    "suggested_action": "确认输入数据质量",
                    "status": "pending",
                }
            )

    for risk_point in card.risk_points:
        if "unavailable" in str(risk_point).lower() or "missing" in str(risk_point).lower():
            risk_digest = hashlib.sha256(str(risk_point).encode("utf-8")).hexdigest()[:12]
            review_batch.append(
                {
                    "review_id": f"{run_id}:data_gap:{risk_digest}",
                    "run_id": run_id,
                    "source_module": "coordinator",
                    "source_step_id": "strategy_card",
                    "severity": "warning",
                    "reason": f"数据缺口: {str(risk_point)[:200]}",
                    "impact_modules": ["data_ingestion"],
                    "suggested_action": "检查对应数据源状态",
                    "status": "pending",
                }
            )

    for review_item in review_batch:
        try:
            from database.queries import review as review_queries

            _runner_patchable("upsert_review_item", review_queries.upsert_review_item)(db, review_item)
        except Exception:
            logger.exception("Failed to upsert review item %s", review_item.get("review_id"))
    if review_batch:
        db.commit()
        logger.info("Auto-created %d review items for run %s", len(review_batch), run_id)


def _file_sha256(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        return None


def _runner_patchable(name: str, default: Any) -> Any:
    from apps.worker import runner

    return getattr(runner, name, default)
