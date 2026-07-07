"""分析持久化仓库：Snapshot / AgentOutput / FinalAnalysisResult 的幂等 upsert 与查询。

所有函数使用便携 AnalysisBase 模型，在 SQLite 和 PostgreSQL 上均可运行。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.analysis import (
    AgentOutput,
    AnalysisSnapshot,
    FinalAnalysisResult,
    PromptVersion,
)


def _sha256_hex(data: dict) -> str:
    """确定性 SHA256（JSON keys 排序）。"""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_iso_date(v: str) -> date:
    return date.fromisoformat(v)


def _parse_iso_datetime(v: str | None) -> datetime | None:
    if v is None:
        return None
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _coerce_payload(payload: dict) -> dict:
    """Ensure payload is a plain dict (for SHA256 consistency)."""
    return dict(payload)


def _resolve_prompt_version_id(session: Session, payload: dict[str, Any]) -> str | None:
    explicit = payload.get("prompt_version_id")
    if explicit:
        return str(explicit)
    agent_name = payload.get("agent_name")
    if not agent_name:
        return None
    row = session.scalar(
        select(PromptVersion)
        .where(
            PromptVersion.agent_id == agent_name,
            PromptVersion.status == "active",
            PromptVersion.enabled.is_(True),
        )
        .order_by(PromptVersion.created_at.desc())
    )
    return row.id if row is not None else None


def _raise_lineage_conflict(message: str) -> None:
    raise ValueError(message)


def _resolve_snapshot_for_lineage(session: Session, payload: dict[str, Any]) -> AnalysisSnapshot | None:
    snapshot_db_id = payload.get("analysis_snapshot_db_id")
    snapshot_id = payload.get("snapshot_id")
    asset = payload.get("asset")
    run_id = payload.get("run_id")
    trade_date_raw = payload.get("trade_date")

    resolved: AnalysisSnapshot | None = None

    if snapshot_db_id:
        resolved = session.get(AnalysisSnapshot, str(snapshot_db_id))

    if snapshot_id:
        snapshot_row = session.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == str(snapshot_id)))
        if snapshot_row is not None:
            if resolved is not None and resolved.id != snapshot_row.id:
                _raise_lineage_conflict(
                    "analysis lineage conflict: "
                    f"analysis_snapshot_db_id={snapshot_db_id} conflicts with snapshot_id={snapshot_id}"
                )
            resolved = snapshot_row

    explicit_snapshot_ref = bool(snapshot_db_id or snapshot_id)
    if resolved is None and not explicit_snapshot_ref and asset and run_id and trade_date_raw:
        trade_date = _parse_iso_date(str(trade_date_raw))
        resolved = session.scalar(
            select(AnalysisSnapshot).where(
                AnalysisSnapshot.asset == str(asset),
                AnalysisSnapshot.trade_date == trade_date,
                AnalysisSnapshot.run_id == str(run_id),
            )
        )

    return resolved


def _validate_snapshot_lineage(session: Session, payload: dict[str, Any], *, entity: str) -> AnalysisSnapshot | None:
    snapshot = _resolve_snapshot_for_lineage(session, payload)
    if snapshot is None:
        return None

    snapshot_db_id = payload.get("analysis_snapshot_db_id")
    snapshot_id = payload.get("snapshot_id")
    run_id = payload.get("run_id")
    asset = payload.get("asset")
    trade_date_raw = payload.get("trade_date")

    if snapshot_db_id and snapshot.id != str(snapshot_db_id):
        _raise_lineage_conflict(
            f"{entity} lineage conflict: analysis_snapshot_db_id={snapshot_db_id} resolves to snapshot id={snapshot.id}"
        )
    if snapshot_id and snapshot.snapshot_id != str(snapshot_id):
        _raise_lineage_conflict(
            f"{entity} lineage conflict: snapshot_id={snapshot_id} resolves to AnalysisSnapshot("
            f"snapshot_id={snapshot.snapshot_id}, run_id={snapshot.run_id})"
        )
    if run_id and snapshot.run_id != str(run_id):
        _raise_lineage_conflict(
            f"{entity} lineage conflict: run_id={run_id} resolves to AnalysisSnapshot("
            f"snapshot_id={snapshot.snapshot_id}, run_id={snapshot.run_id})"
        )
    if asset and snapshot.asset != str(asset):
        _raise_lineage_conflict(
            f"{entity} lineage conflict: asset={asset} resolves to AnalysisSnapshot("
            f"snapshot_id={snapshot.snapshot_id}, asset={snapshot.asset})"
        )
    if trade_date_raw:
        trade_date = _parse_iso_date(str(trade_date_raw))
        if snapshot.trade_date != trade_date:
            _raise_lineage_conflict(
                f"{entity} lineage conflict: trade_date={trade_date_raw} resolves to AnalysisSnapshot("
                f"snapshot_id={snapshot.snapshot_id}, trade_date={snapshot.trade_date.isoformat()})"
            )

    return snapshot


# ═══════════════════════════════════════════════════════════════════
# AnalysisSnapshot
# ═══════════════════════════════════════════════════════════════════


def upsert_analysis_snapshot(
    session: Session,
    payload: dict[str, Any],
    artifact_path: str,
) -> AnalysisSnapshot:
    """幂等 upsert：按 snapshot_id 查找，存在则返回，不存在则创建。

    payload 键：
      snapshot_id, asset, trade_date, run_id, snapshot_time, status,
      input_snapshot_ids, source_refs, macro, options, positioning,
      news, technical, payload
    """
    snapshot_id = payload["snapshot_id"]
    existing = session.scalar(
        select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot_id)
    )
    if existing is not None:
        return existing

    core_payload = _coerce_payload(payload.get("payload", {}))

    snap = AnalysisSnapshot(
        snapshot_id=snapshot_id,
        asset=payload["asset"],
        trade_date=_parse_iso_date(payload["trade_date"]),
        run_id=payload["run_id"],
        snapshot_time=_parse_iso_datetime(payload.get("snapshot_time")),
        status=payload.get("status", "success"),
        input_snapshot_ids=payload.get("input_snapshot_ids", {}),
        source_refs=payload.get("source_refs", []),
        macro=payload.get("macro"),
        options=payload.get("options"),
        positioning=payload.get("positioning"),
        news=payload.get("news"),
        technical=payload.get("technical"),
        payload=core_payload,
        payload_sha256=_sha256_hex(core_payload),
        artifact_path=artifact_path,
    )
    session.add(snap)
    session.flush()
    return snap


def get_analysis_snapshot_latest(
    session: Session,
    asset: str = "XAUUSD",
) -> AnalysisSnapshot | None:
    """返回最新 trade_date 的 snapshots；同日期内按 snapshot_time 降序。"""
    return session.scalar(
        select(AnalysisSnapshot)
        .where(AnalysisSnapshot.asset == asset)
        .order_by(
            AnalysisSnapshot.trade_date.desc(),
            AnalysisSnapshot.snapshot_time.desc().nullslast(),
            AnalysisSnapshot.id.desc(),
        )
        .limit(1)
    )


def get_analysis_snapshot(
    session: Session,
    asset: str,
    trade_date: str,
    run_id: str,
) -> AnalysisSnapshot | None:
    """按 (asset, trade_date, run_id) 精确查询。"""
    return session.scalar(
        select(AnalysisSnapshot).where(
            AnalysisSnapshot.asset == asset,
            AnalysisSnapshot.trade_date == _parse_iso_date(trade_date),
            AnalysisSnapshot.run_id == run_id,
        )
    )


# ═══════════════════════════════════════════════════════════════════
# AgentOutput
# ═══════════════════════════════════════════════════════════════════


def upsert_agent_output(
    session: Session,
    payload: dict[str, Any],
) -> AgentOutput:
    """幂等 upsert：按 (snapshot_id, agent_name, module, version) 查找；
    存在则更新字段，不存在则创建。

    payload 键：
      snapshot_id, analysis_snapshot_db_id, asset, trade_date, run_id,
      agent_name, module, version, status, bias, confidence,
      input_snapshot_ids, source_refs, key_findings, risk_points,
      watchlist, invalid_conditions, summary, payload
    """
    _validate_snapshot_lineage(session, payload, entity="agent output")

    snapshot_id = payload["snapshot_id"]
    agent_name = payload["agent_name"]
    module = payload["module"]
    version = payload.get("version", "1.0")

    existing = session.scalar(
        select(AgentOutput).where(
            AgentOutput.snapshot_id == snapshot_id,
            AgentOutput.agent_name == agent_name,
            AgentOutput.module == module,
            AgentOutput.version == version,
        )
    )

    core_payload = _coerce_payload(payload.get("payload", {}))
    prompt_version_id = _resolve_prompt_version_id(session, payload)

    if existing is not None:
        # Update mutable fields
        existing.analysis_snapshot_db_id = payload.get("analysis_snapshot_db_id")
        existing.asset = payload["asset"]
        existing.trade_date = _parse_iso_date(payload["trade_date"])
        existing.run_id = payload["run_id"]
        existing.status = payload["status"]
        existing.bias = payload["bias"]
        existing.confidence = float(payload["confidence"])
        existing.input_snapshot_ids = payload.get("input_snapshot_ids", {})
        existing.source_refs = payload.get("source_refs", [])
        existing.key_findings = payload.get("key_findings", [])
        existing.risk_points = payload.get("risk_points", [])
        existing.watchlist = payload.get("watchlist", [])
        existing.invalid_conditions = payload.get("invalid_conditions", [])
        existing.summary = payload.get("summary", "")
        existing.token_usage = payload.get("token_usage")
        existing.llm_model = payload.get("llm_model")
        existing.llm_elapsed_seconds = payload.get("llm_elapsed_seconds")
        existing.prompt_version_id = prompt_version_id
        existing.payload = core_payload
        existing.payload_sha256 = _sha256_hex(core_payload)
        session.flush()
        return existing

    ao = AgentOutput(
        snapshot_id=snapshot_id,
        analysis_snapshot_db_id=payload.get("analysis_snapshot_db_id"),
        asset=payload["asset"],
        trade_date=_parse_iso_date(payload["trade_date"]),
        run_id=payload["run_id"],
        agent_name=agent_name,
        module=module,
        version=version,
        status=payload["status"],
        bias=payload["bias"],
        confidence=float(payload["confidence"]),
        input_snapshot_ids=payload.get("input_snapshot_ids", {}),
        source_refs=payload.get("source_refs", []),
        key_findings=payload.get("key_findings", []),
        risk_points=payload.get("risk_points", []),
        watchlist=payload.get("watchlist", []),
        invalid_conditions=payload.get("invalid_conditions", []),
        summary=payload.get("summary", ""),
        token_usage=payload.get("token_usage"),
        llm_model=payload.get("llm_model"),
        llm_elapsed_seconds=payload.get("llm_elapsed_seconds"),
        prompt_version_id=prompt_version_id,
        payload=core_payload,
        payload_sha256=_sha256_hex(core_payload),
    )
    session.add(ao)
    session.flush()
    return ao


def list_agent_outputs(
    session: Session,
    snapshot_id: str,
) -> list[AgentOutput]:
    """返回某个 snapshot_id 的所有 Agent Output。"""
    return list(
        session.scalars(
            select(AgentOutput)
            .where(AgentOutput.snapshot_id == snapshot_id)
            .order_by(AgentOutput.agent_name)
        )
    )


def get_agent_output(
    session: Session,
    snapshot_id: str,
    agent_name: str,
) -> AgentOutput | None:
    """按 (snapshot_id, agent_name) 精确查询。"""
    return session.scalar(
        select(AgentOutput).where(
            AgentOutput.snapshot_id == snapshot_id,
            AgentOutput.agent_name == agent_name,
        )
    )


# ═══════════════════════════════════════════════════════════════════
# FinalAnalysisResult
# ═══════════════════════════════════════════════════════════════════


def upsert_final_analysis_result(
    session: Session,
    payload: dict[str, Any],
    paths: dict[str, str],
) -> FinalAnalysisResult:
    """幂等 upsert：按 (asset, trade_date, run_id) 查找；
    存在则更新，不存在则创建。

    payload 键：
      asset, trade_date, run_id, snapshot_id, analysis_snapshot_db_id,
      final_bias, confidence, market_state, scenario_summary,
      is_trade_instruction, input_snapshot_ids, source_refs,
      source_agent_outputs, risk_points, watchlist,
      invalid_conditions, strategy_card, run_summaries, payload

    paths 键：
      final_report_path, strategy_card_json_path, strategy_card_md_path,
      run_summary_path, final_report_sha256, strategy_card_sha256
    """
    _validate_snapshot_lineage(session, payload, entity="final analysis")

    asset = payload["asset"]
    trade_date_val = _parse_iso_date(payload["trade_date"])
    run_id = payload["run_id"]

    existing = session.scalar(
        select(FinalAnalysisResult).where(
            FinalAnalysisResult.asset == asset,
            FinalAnalysisResult.trade_date == trade_date_val,
            FinalAnalysisResult.run_id == run_id,
        )
    )

    core_payload = _coerce_payload(payload.get("payload", {}))
    sha256_val = _sha256_hex(core_payload)

    if existing is not None:
        # Update all mutable fields
        existing.snapshot_id = payload.get("snapshot_id")
        existing.analysis_snapshot_db_id = payload.get("analysis_snapshot_db_id")
        existing.final_bias = payload.get("final_bias")
        existing.confidence = float(payload["confidence"]) if payload.get("confidence") is not None else None
        existing.market_state = payload.get("market_state")
        existing.scenario_summary = payload.get("scenario_summary")
        existing.is_trade_instruction = payload.get("is_trade_instruction", False)
        existing.input_snapshot_ids = payload.get("input_snapshot_ids", {})
        existing.source_refs = payload.get("source_refs", [])
        existing.source_agent_outputs = payload.get("source_agent_outputs", [])
        existing.risk_points = payload.get("risk_points", [])
        existing.watchlist = payload.get("watchlist", [])
        existing.invalid_conditions = payload.get("invalid_conditions", [])
        existing.strategy_card = payload.get("strategy_card")
        existing.run_summaries = payload.get("run_summaries")
        existing.payload = core_payload
        existing.payload_sha256 = sha256_val
        existing.final_report_path = paths.get("final_report_path")
        existing.strategy_card_json_path = paths.get("strategy_card_json_path")
        existing.strategy_card_md_path = paths.get("strategy_card_md_path")
        existing.run_summary_path = paths.get("run_summary_path")
        existing.final_report_sha256 = paths.get("final_report_sha256")
        existing.strategy_card_sha256 = paths.get("strategy_card_sha256")
        session.flush()
        return existing

    far = FinalAnalysisResult(
        asset=asset,
        trade_date=trade_date_val,
        run_id=run_id,
        snapshot_id=payload.get("snapshot_id"),
        analysis_snapshot_db_id=payload.get("analysis_snapshot_db_id"),
        final_bias=payload.get("final_bias"),
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        market_state=payload.get("market_state"),
        scenario_summary=payload.get("scenario_summary"),
        is_trade_instruction=payload.get("is_trade_instruction", False),
        input_snapshot_ids=payload.get("input_snapshot_ids", {}),
        source_refs=payload.get("source_refs", []),
        source_agent_outputs=payload.get("source_agent_outputs", []),
        risk_points=payload.get("risk_points", []),
        watchlist=payload.get("watchlist", []),
        invalid_conditions=payload.get("invalid_conditions", []),
        strategy_card=payload.get("strategy_card"),
        run_summaries=payload.get("run_summaries"),
        payload=core_payload,
        payload_sha256=sha256_val,
        final_report_path=paths.get("final_report_path"),
        strategy_card_json_path=paths.get("strategy_card_json_path"),
        strategy_card_md_path=paths.get("strategy_card_md_path"),
        run_summary_path=paths.get("run_summary_path"),
        final_report_sha256=paths.get("final_report_sha256"),
        strategy_card_sha256=paths.get("strategy_card_sha256"),
    )
    session.add(far)
    session.flush()
    return far


def get_final_analysis_latest(
    session: Session,
    asset: str = "XAUUSD",
) -> FinalAnalysisResult | None:
    """返回最新 trade_date 的 FinalAnalysisResult。"""
    return session.scalar(
        select(FinalAnalysisResult)
        .where(FinalAnalysisResult.asset == asset)
        .order_by(
            FinalAnalysisResult.trade_date.desc(),
            FinalAnalysisResult.id.desc(),
        )
        .limit(1)
    )


def get_final_analysis(
    session: Session,
    asset: str,
    trade_date: str,
    run_id: str,
) -> FinalAnalysisResult | None:
    """按 (asset, trade_date, run_id) 精确查询。"""
    return session.scalar(
        select(FinalAnalysisResult).where(
            FinalAnalysisResult.asset == asset,
            FinalAnalysisResult.trade_date == _parse_iso_date(trade_date),
            FinalAnalysisResult.run_id == run_id,
        )
    )
