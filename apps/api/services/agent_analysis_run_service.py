"""Manual dispatch helpers for agent-analysis routes."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_market_regime_async(target_date: str) -> None:
    def _run() -> None:
        try:
            from apps.analysis.agents.market_regime import run_market_regime_agent

            result = run_market_regime_agent(
                load_macro_snapshot(target_date), load_options_intent(target_date),
                snapshot_id=f"manual-{target_date}", run_id=f"manual-{target_date}",
            )
            save_agent_output(result)
        except Exception:
            logger.exception("Market Regime Agent failed")

    threading.Thread(target=_run, daemon=True).start()


def run_event_impact_async(target_date: str) -> None:
    def _run() -> None:
        try:
            from apps.analysis.agents.event_impact import run_event_impact_agent

            result = run_event_impact_agent(
                load_flash_news(), load_macro_snapshot(target_date), load_options_intent(target_date),
                current_price=load_current_price(), snapshot_id=f"manual-{target_date}", run_id=f"manual-{target_date}",
            )
            save_agent_output(result)
        except Exception:
            logger.exception("Event Impact Agent failed")

    threading.Thread(target=_run, daemon=True).start()


def load_macro_snapshot(target_date: str) -> dict[str, Any]:
    features_dir = Path("storage/features/macro") / target_date
    if not features_dir.exists():
        features_dir = Path("storage/features/macro")
        dates = sorted((item.name for item in features_dir.iterdir() if item.is_dir() and item.name.startswith("2026")), reverse=True) if features_dir.exists() else []
        if not dates:
            return {"indicators": {}}
        features_dir = features_dir / dates[0]
    for run_dir in features_dir.iterdir():
        snapshot_file = run_dir / "macro_snapshot.json"
        if snapshot_file.exists():
            return json.loads(snapshot_file.read_text())
    return {"indicators": {}}


def load_options_intent(target_date: str) -> dict[str, Any] | None:
    del target_date
    features_dir = Path("storage/features/cme")
    if not features_dir.exists():
        return None
    dates = sorted((item.name for item in features_dir.iterdir() if item.is_dir() and item.name.startswith("2026")), reverse=True)
    for date_dir in dates:
        for run_dir in (features_dir / date_dir).iterdir():
            analysis_file = run_dir / "options_analysis.json"
            if analysis_file.exists():
                data = json.loads(analysis_file.read_text())
                intent = data.get("intent", {})
                gex = data.get("gex", {}).get("netgex_aggregate", {})
                return {
                    "type": intent.get("type", intent.get("primary_intent", {}).get("intent_type", "N/A")),
                    "score": intent.get("score", intent.get("confidence", 0)),
                    "gamma_zero": gex.get("gamma_zero", {}).get("price"),
                    "forward_price": data.get("parameters", {}).get("p0"),
                }
    return None


def load_flash_news() -> list[dict[str, Any]]:
    try:
        from apps.collectors.jin10.mcp_client import fetch_flash_news

        return fetch_flash_news(limit=30)
    except Exception:
        return []


def load_current_price() -> float | None:
    cache_file = Path("storage/outputs/jin10/quotes_cache.json")
    if not cache_file.exists():
        return None
    return json.loads(cache_file.read_text()).get("quotes", {}).get("XAUUSD", {}).get("price")


def save_agent_output(result) -> None:
    from database.models.analysis import AgentOutput
    from database.models.engine import SessionLocal

    payload = {
        "market_phase": result.market_phase,
        "regime_drivers": result.regime_drivers,
        "generated_by": (result.regime_drivers or {}).get("generated_by", "rule"),
        "data_category": result.data_category.value if result.data_category else None,
        "evidence_refs": result.evidence_refs,
        "prompt_messages": result.prompt_messages,
        "input_payload": result.input_payload,
        "llm_raw_output": result.llm_raw_output,
    }
    with SessionLocal() as db:
        row = db.query(AgentOutput).filter(
            AgentOutput.snapshot_id == result.snapshot_id,
            AgentOutput.agent_name == result.agent_name,
            AgentOutput.module == result.module,
            AgentOutput.version == result.version,
        ).one_or_none()
        values = {
            "status": result.status.value, "bias": result.bias.value, "confidence": result.confidence,
            "input_snapshot_ids": result.input_snapshot_ids, "source_refs": result.source_refs,
            "key_findings": result.key_findings, "risk_points": result.risk_points,
            "watchlist": result.watchlist, "invalid_conditions": result.invalid_conditions,
            "summary": result.summary, "payload": payload, "payload_sha256": "manual",
            "token_usage": result.llm_usage, "llm_model": result.llm_model,
            "llm_elapsed_seconds": result.llm_latency_ms / 1000.0 if result.llm_latency_ms else None,
        }
        if row is None:
            row = AgentOutput(
                id=str(uuid.uuid4()), snapshot_id=result.snapshot_id, asset="XAUUSD",
                trade_date=result.created_at.date(), run_id=result.snapshot_id,
                agent_name=result.agent_name, module=result.module, version=result.version, **values,
            )
            db.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        db.commit()
