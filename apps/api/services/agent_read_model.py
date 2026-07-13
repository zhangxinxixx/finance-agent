from __future__ import annotations

import logging
from typing import Any, Iterable

from sqlalchemy import desc

from apps.api.services.agent_output_service import build_agent_output_summary
from database.models.analysis import AgentOutput
from database.models.engine import SessionLocal


logger = logging.getLogger(__name__)


def _latest_agent_summaries(agent_names: Iterable[str]) -> dict[str, dict[str, Any]]:
    names = list(dict.fromkeys(agent_names))
    if not names:
        return {}

    try:
        with SessionLocal() as db:
            rows = (
                db.query(AgentOutput)
                .filter(AgentOutput.agent_name.in_(names))
                .order_by(desc(AgentOutput.trade_date), desc(AgentOutput.created_at))
                .all()
            )
            result: dict[str, dict[str, Any]] = {}
            for row in rows:
                if row.agent_name in result:
                    continue
                result[row.agent_name] = build_agent_output_summary(row)
            return result
    except Exception as exc:
        logger.debug(
            "Agent read model lookup failed; returning empty summary",
            exc_info=exc,
            extra={"service": "agent_read_model", "agent_names": names, "degraded": True},
        )
        return {}


def _summary_text(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    return str(item.get("summary_zh") or item.get("summary") or "")


def _compact_agent(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "agent_output_id": item.get("agent_output_id"),
        "agent_name": item.get("agent_name"),
        "registry_id": item.get("registry_id"),
        "run_id": item.get("run_id"),
        "snapshot_id": item.get("snapshot_id"),
        "status": item.get("status"),
        "bias": item.get("bias"),
        "confidence": item.get("confidence"),
        "summary": _summary_text(item),
        "summary_raw": item.get("summary"),
        "key_findings": item.get("key_findings") or [],
        "risk_points": item.get("risk_points") or [],
        "watchlist": item.get("watchlist") or [],
        "invalid_conditions": item.get("invalid_conditions") or [],
        "market_phase": item.get("market_phase"),
        "regime_drivers": item.get("regime_drivers") or {},
        "narrative_md": item.get("narrative_md") or "",
        "source_refs": item.get("source_refs") or [],
        "fact_review_status": item.get("fact_review_status"),
        "claim_count": item.get("claim_count") or 0,
        "llm_model": item.get("llm_model"),
        "llm_elapsed_seconds": item.get("llm_elapsed_seconds"),
        "created_at": item.get("created_at"),
    }


def build_dashboard_agent_summary() -> dict[str, Any]:
    summaries = _latest_agent_summaries(["synthesis_agent", "coordinator_agent", "coordinator"])
    coordinator = summaries.get("coordinator_agent") or summaries.get("coordinator")
    synthesis = summaries.get("synthesis_agent")
    return {
        "coordinator": _compact_agent(coordinator),
        "synthesis": _compact_agent(synthesis),
    }


def build_market_regime_agent_summary() -> dict[str, Any] | None:
    item = _compact_agent(_latest_agent_summaries(["market_regime"]).get("market_regime"))
    if not item:
        return None
    regime_drivers = item.get("regime_drivers") or {}
    key_drivers = regime_drivers.get("key_drivers") or regime_drivers.get("drivers") or item.get("key_findings") or []
    return {
        **item,
        "regime": item.get("market_phase") or item.get("bias") or "unknown",
        "regime_label": item.get("summary") or "市场阶段待生成",
        "key_drivers": key_drivers,
    }


def build_event_impact_agent_summary() -> dict[str, Any] | None:
    item = _compact_agent(_latest_agent_summaries(["event_impact"]).get("event_impact"))
    if not item:
        return None
    return {
        **item,
        "events": [],
        "sentiment": {},
        "risk_radar": {},
    }
