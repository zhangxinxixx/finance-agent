from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from apps.analysis.agents.cme_options import analyze_cme_options
from apps.analysis.options.llm_conclusion import build_conclusion_prompt, parse_llm_response

_SYSTEM_PROMPT = "你是一位专业 CME / COMEX 黄金期权结构分析师。只输出 Markdown 正文。"
_PROMPT_VERSION = "cme_options_agent_v1"


def build_options_agent_output_payload(
    snapshot: dict[str, Any],
    *,
    artifact_dir: Path | str,
    run_id: str | None = None,
    llm_markdown: str | None = None,
    llm_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_dir_path = Path(artifact_dir)
    trade_date = str(snapshot.get("trade_date") or "")
    resolved_run_id = _resolve_run_id(snapshot, run_id)
    snapshot_id = str(snapshot.get("snapshot_id") or f"options:{trade_date}:{resolved_run_id}")
    source_refs = _build_source_refs(snapshot)
    input_snapshot_ids = _build_input_snapshot_ids(snapshot, snapshot_id)
    wrapped_snapshot = {
        "snapshot_id": snapshot_id,
        "input_snapshot_ids": input_snapshot_ids,
        "source_refs": source_refs,
        "options": {
            "status": "available" if snapshot else "unavailable",
            "data": snapshot,
        },
    }
    deterministic_output = analyze_cme_options(wrapped_snapshot)
    prompt = build_conclusion_prompt(snapshot)

    enhanced_markdown = parse_llm_response(llm_markdown) if llm_markdown else None
    deterministic_markdown = _read_optional_text(artifact_dir_path / "options_analysis.md")
    narrative_md = enhanced_markdown or deterministic_markdown or ""
    artifact_refs = _artifact_refs(artifact_dir_path)
    claims = _build_claims(snapshot, deterministic_output, artifact_refs, source_refs, enhanced_markdown)
    llm_meta = dict(llm_result or {})

    summary = deterministic_output.summary
    if enhanced_markdown:
        summary = _extract_one_line_conclusion(enhanced_markdown) or summary

    data_category = "external_opinion" if enhanced_markdown else "system_inference"
    generated_by = "hybrid" if enhanced_markdown else "rule"

    return {
        "snapshot_id": snapshot_id,
        "analysis_snapshot_db_id": None,
        "asset": "XAUUSD",
        "trade_date": trade_date,
        "run_id": resolved_run_id,
        "agent_name": deterministic_output.agent_name,
        "module": deterministic_output.module,
        "version": deterministic_output.version,
        "status": deterministic_output.status.value,
        "bias": deterministic_output.bias.value,
        "confidence": float(deterministic_output.confidence),
        "input_snapshot_ids": input_snapshot_ids,
        "source_refs": source_refs,
        "key_findings": list(deterministic_output.key_findings),
        "risk_points": list(deterministic_output.risk_points),
        "watchlist": list(deterministic_output.watchlist),
        "invalid_conditions": list(deterministic_output.invalid_conditions),
        "summary": summary,
        "payload": {
            "generated_by": generated_by,
            "prompt_version": _PROMPT_VERSION,
            "prompt_messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "input_payload": {"options_snapshot": snapshot},
            "llm_raw_output": enhanced_markdown,
            "narrative_md": narrative_md,
            "report_json": snapshot,
            "artifact_refs": artifact_refs,
            "claims": claims,
            "data_category": data_category,
            "deterministic_output": deterministic_output.model_dump(mode="json"),
        },
        "token_usage": llm_meta.get("tokens") or llm_meta.get("usage"),
        "llm_model": llm_meta.get("model"),
        "llm_elapsed_seconds": _latency_seconds(llm_meta.get("latency_ms")),
    }


def persist_options_agent_output(
    snapshot: dict[str, Any],
    *,
    artifact_dir: Path | str,
    run_id: str | None = None,
    llm_markdown: str | None = None,
    llm_result: dict[str, Any] | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    from apps.analysis.agents.fact_review import persist_fact_review_agent_output
    from apps.analysis.agents.synthesis import persist_synthesis_agent_output
    from database.queries.analysis import upsert_agent_output

    own_session = session is None
    if own_session:
        from database.models.engine import SessionLocal

        session = SessionLocal()

    assert session is not None
    try:
        payload = build_options_agent_output_payload(
            snapshot,
            artifact_dir=artifact_dir,
            run_id=run_id,
            llm_markdown=llm_markdown,
            llm_result=llm_result,
        )
        row = upsert_agent_output(session, payload)
        fact_review = persist_fact_review_agent_output(session, snapshot_id=row.snapshot_id)
        synthesis = persist_synthesis_agent_output(session, snapshot_id=row.snapshot_id)
        if own_session:
            session.commit()
        return {
            "agent_output_id": row.id,
            "agent_name": row.agent_name,
            "snapshot_id": row.snapshot_id,
            "run_id": row.run_id,
            "trade_date": payload["trade_date"],
            "fact_review_agent_output_id": fact_review["agent_output_id"],
            "fact_review_status": fact_review["fact_review_status"],
            "synthesis_agent_output_id": synthesis["agent_output_id"],
            "synthesis_status": synthesis["synthesis_status"],
        }
    finally:
        if own_session:
            session.close()


def _resolve_run_id(snapshot: dict[str, Any], run_id: str | None) -> str:
    if run_id:
        return str(run_id)
    data_source = snapshot.get("data_source") or {}
    input_snapshot_ids = data_source.get("input_snapshot_ids") or {}
    raw_file_sha256 = input_snapshot_ids.get("raw_file_sha256")
    if raw_file_sha256:
        return str(raw_file_sha256)[:16]
    trade_date = str(snapshot.get("trade_date") or "unknown-date")
    product = str(snapshot.get("data_source", {}).get("product") or snapshot.get("product") or "options")
    return f"{product.lower()}-{trade_date}"


def _build_input_snapshot_ids(snapshot: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    data_source = snapshot.get("data_source") or {}
    input_snapshot_ids = dict(data_source.get("input_snapshot_ids") or {})
    input_snapshot_ids.setdefault("options_analysis_snapshot", snapshot_id)
    return input_snapshot_ids


def _build_source_refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    data_source = snapshot.get("data_source") or {}
    source_url = data_source.get("source_url")
    if source_url:
        refs.append(
            {
                "source": "cme_daily_bulletin",
                "source_url": source_url,
                "report_date": snapshot.get("trade_date"),
                "product": data_source.get("product") or snapshot.get("product"),
                "status": data_source.get("status"),
                "input_snapshot_ids": data_source.get("input_snapshot_ids") or {},
            }
        )
    calibration = snapshot.get("calibration") or {}
    for item in calibration.get("source_refs") or []:
        if isinstance(item, dict):
            refs.append(dict(item))
    return refs


def _artifact_refs(artifact_dir: Path) -> list[str]:
    refs: list[str] = []
    for filename in (
        "options_analysis.json",
        "options_analysis.md",
        "options_visual_report.json",
        "options_visual_report.html",
        "options_analysis_agent_report.md",
    ):
        path = artifact_dir / filename
        if path.exists():
            refs.append(str(path))
    return refs


def _build_claims(
    snapshot: dict[str, Any],
    deterministic_output: Any,
    artifact_refs: list[str],
    source_refs: list[dict[str, Any]],
    enhanced_markdown: str | None,
) -> list[dict[str, Any]]:
    trade_date = str(snapshot.get("trade_date") or "unknown-date")
    run_id = _resolve_run_id(snapshot, None)
    evidence_refs = [*source_refs, *[{"artifact_path": path} for path in artifact_refs]]
    claims: list[dict[str, Any]] = []

    def _append_claim(claim_id: str, text: str, claim_type: str, confidence: float = 0.72) -> None:
        if not text.strip():
            return
        claims.append(
            {
                "claim_id": f"{trade_date}:{run_id}:{claim_id}",
                "text": text.strip(),
                "claim_type": claim_type,
                "source_refs": source_refs,
                "evidence_refs": evidence_refs,
                "confidence": confidence,
            }
        )

    _append_claim(
        "summary",
        _extract_one_line_conclusion(enhanced_markdown) or deterministic_output.summary,
        "market_view",
        confidence=float(deterministic_output.confidence),
    )

    gamma_zero = (
        (((snapshot.get("gex") or {}).get("netgex_aggregate") or {}).get("gamma_zero") or {}).get("price")
    )
    if gamma_zero is not None:
        _append_claim("gamma_zero", f"Gamma Zero: {gamma_zero}", "strategy_condition")

    wall_scores = snapshot.get("wall_scores") or []
    if wall_scores and isinstance(wall_scores[0], dict):
        top_wall = wall_scores[0]
        wall_type = str(top_wall.get("wall_type") or top_wall.get("side") or "wall")
        strike = top_wall.get("strike") or top_wall.get("price") or top_wall.get("level")
        score = top_wall.get("wall_score")
        _append_claim(
            "top_wall",
            f"Top wall: {wall_type} @ {strike}, score {score}",
            "strategy_condition",
        )

    intent = snapshot.get("intent") or {}
    intent_type = str(intent.get("type") or "")
    intent_score = intent.get("score")
    if intent_type:
        _append_claim("intent", f"机构意图 {intent_type}，score {intent_score}", "causal_inference")

    support_resistance = snapshot.get("support_resistance") or {}
    support = ((support_resistance.get("support") or [{}])[0] if isinstance(support_resistance.get("support"), list) else {})
    resistance = ((support_resistance.get("resistance") or [{}])[0] if isinstance(support_resistance.get("resistance"), list) else {})
    if isinstance(support, dict) and any(key in support for key in ("strike", "price", "level")):
        _append_claim("support", f"Nearest support: {support.get('strike') or support.get('price') or support.get('level')}", "strategy_condition")
    if isinstance(resistance, dict) and any(key in resistance for key in ("strike", "price", "level")):
        _append_claim("resistance", f"Nearest resistance: {resistance.get('strike') or resistance.get('price') or resistance.get('level')}", "strategy_condition")

    for index, risk in enumerate(deterministic_output.risk_points[:4], start=1):
        _append_claim(f"risk_{index}", str(risk), "risk_warning", confidence=0.65)

    return claims


def _extract_one_line_conclusion(markdown: str | None) -> str | None:
    if not markdown:
        return None
    match = re.search(r"##\s*一句话结论\s*\n(.+?)(?=\n##|\Z)", markdown, re.DOTALL)
    if match:
        return match.group(1).strip()
    for line in markdown.splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            return text
    return None


def _latency_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value) / 1000.0, 3)
    except (TypeError, ValueError):
        return None


def _read_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")
