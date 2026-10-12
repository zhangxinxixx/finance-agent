from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select

from apps.analysis.macro.regime import classify_macro_regime
from apps.api.services import _storage
from apps.api.services._storage import _iso, _latest_asset_date_run
from apps.api.services.report_index_service import list_reports_index
from apps.api.services.report_storage_service import (
    _research_created_at_for_run,
    _safe_model_rows,
    _safe_row_artifacts,
    _timestamp,
)
from apps.api.services.report_reading.common import (
    _generated_at_from_datetime,
    _generated_at_from_paths,
)
from apps.runtime.output_disposition import (
    FAIL_CLOSED_AGENT_NAMES,
    OUTPUT_CLEANUP_KEY,
    is_output_purged,
    purged_output_summary,
)
from database.models.analysis import AgentOutput, AnalysisSnapshot, FinalAnalysisResult
from database.models.report import ReportItem

logger = logging.getLogger(__name__)


def _strategy_purged_anchors(db, asset: str | None) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    report_query = lambda: db.execute(  # noqa: E731
        select(
            ReportItem.report_id,
            ReportItem.run_id,
            ReportItem.snapshot_id,
            ReportItem.trade_date,
            ReportItem.lifecycle_status,
            ReportItem.report_metadata.label("report_metadata"),
            ReportItem.created_at,
        ).where(
            or_(
                ReportItem.report_type == "strategy_card",
                ReportItem.family.in_(("strategy_card", "strategy_card_markdown")),
            ),
            *([or_(ReportItem.asset == asset, ReportItem.asset.is_(None))] if asset else []),
        )
    ).mappings().all()
    report_rows = _safe_model_rows(db, ReportItem, report_query)
    for row in report_rows:
        if not (
            is_output_purged(row)
            or str(row.lifecycle_status or "").lower() == "purged"
            or any(is_output_purged(artifact) for artifact in _safe_row_artifacts(db, row))
        ):
            continue
        marker = purged_output_summary(row) or {}
        anchors.append(
            {
                "report_id": str(row.report_id),
                "run_id": str(row.run_id) if row.run_id else marker.get("run_id"),
                "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                "trade_date": _iso(row.trade_date) if row.trade_date else None,
                "created_at": getattr(row, "created_at", None),
            }
        )

    final_query = lambda: db.execute(  # noqa: E731
        select(
            FinalAnalysisResult.id,
            FinalAnalysisResult.run_id,
            FinalAnalysisResult.snapshot_id,
            FinalAnalysisResult.trade_date,
            FinalAnalysisResult.created_at,
            FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
        ).where(*([FinalAnalysisResult.asset == asset] if asset else []))
    ).mappings().all()
    final_rows = _safe_model_rows(db, FinalAnalysisResult, final_query)
    for row in final_rows:
        if not is_output_purged(row):
            continue
        marker = purged_output_summary(row) or {}
        anchors.append(
            {
                "report_id": str(row.run_id),
                "run_id": str(row.run_id),
                "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                "trade_date": _iso(row.trade_date) if row.trade_date else None,
                "created_at": getattr(row, "created_at", None),
            }
        )

    failure_query = lambda: db.execute(  # noqa: E731
        select(
            AgentOutput.id,
            AgentOutput.snapshot_id,
            AgentOutput.asset,
            AgentOutput.trade_date,
            AgentOutput.run_id,
            AgentOutput.agent_name,
            AgentOutput.created_at,
            AgentOutput.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
        ).where(
            AgentOutput.asset == asset,
            AgentOutput.agent_name.in_(FAIL_CLOSED_AGENT_NAMES),
        )
    ).mappings().all()
    failure_rows = _safe_model_rows(db, AgentOutput, failure_query)
    for row in failure_rows:
        if not is_output_purged(row):
            continue
        marker = purged_output_summary(row) or {}
        anchors.append(
            {
                "report_id": str(row.run_id),
                "run_id": str(row.run_id),
                "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                "trade_date": _iso(row.trade_date) if row.trade_date else None,
                "created_at": getattr(row, "created_at", None),
            }
        )
    return anchors


def _strategy_anchor_matches(anchors: list[dict[str, Any]], *, run_id: str | None, snapshot_id: str | None = None) -> bool:
    identities = {str(value) for value in (run_id, snapshot_id) if value}
    for value in tuple(identities):
        for prefix in ("strategy_card:", "final_report:"):
            if value.startswith(prefix):
                identities.add(value[len(prefix) :])
    return any(
        identities.intersection(
            {
                str(anchor.get("run_id") or ""),
                str(anchor.get("report_id") or ""),
                str(anchor.get("snapshot_id") or ""),
            }
        )
        for anchor in anchors
    )


def _strategy_anchor_blocks_fs(
    anchors: list[dict[str, Any]],
    *,
    trade_date: str | None,
    run_id: str | None,
    path: Path | None = None,
    candidate_created_at: Any | None = None,
) -> bool:
    if not anchors:
        return False
    if trade_date is None or run_id is None:
        return True
    if _strategy_anchor_matches(anchors, run_id=run_id):
        return True
    candidate_time = _timestamp(candidate_created_at)
    for anchor in anchors:
        anchor_date = str(anchor.get("trade_date") or "")
        if anchor_date > str(trade_date):
            return True
        if anchor_date != str(trade_date):
            continue
        anchor_time = _timestamp(anchor.get("created_at"))
        # Filesystem mtime is mutable; same-date fallback needs trusted DB
        # research times or it must remain unavailable.
        if anchor_time is None or candidate_time is None or anchor_time >= candidate_time:
            return True
    return False


def _strategy_anchor_blocks_row(anchors: list[dict[str, Any]], row: Any) -> bool:
    row_date = _iso(row.trade_date) if getattr(row, "trade_date", None) else ""
    row_time = _timestamp(getattr(row, "created_at", None))
    for anchor in anchors:
        if str(anchor.get("run_id") or "") == str(getattr(row, "run_id", "")):
            return True
        anchor_date = str(anchor.get("trade_date") or "")
        if anchor_date > row_date:
            return True
        if anchor_date != row_date:
            continue
        anchor_time = _timestamp(anchor.get("created_at"))
        if anchor_time is None or row_time is None or anchor_time >= row_time:
            return True
    return False


def get_strategy_card_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "strategy_card"
    trade_date, run_id, run_dir = _latest_asset_date_run(base, asset)
    try:
        db = _storage._try_db_session()
    except Exception:
        return None
    if db is None:
        return None
    try:
        db.execute(select(1))
        # Query the authoritative identity, strategy body, paths, and cleanup
        # marker before reading a shared file.  The large persisted payload and
        # source arrays stay out of this current-latest query.
        row = db.execute(
            select(
                FinalAnalysisResult.id,
                FinalAnalysisResult.asset,
                FinalAnalysisResult.trade_date,
                FinalAnalysisResult.run_id,
                FinalAnalysisResult.snapshot_id,
                FinalAnalysisResult.strategy_card,
                FinalAnalysisResult.strategy_card_md_path,
                FinalAnalysisResult.strategy_card_json_path,
                FinalAnalysisResult.created_at,
                AnalysisSnapshot.macro.label("snapshot_macro"),
                FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
            )
            .outerjoin(AnalysisSnapshot, FinalAnalysisResult.analysis_snapshot_db_id == AnalysisSnapshot.id)
            .where(FinalAnalysisResult.asset == asset)
            .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
            .limit(1)
        ).mappings().first()
        purged_anchors = _strategy_purged_anchors(db, asset)
        candidate_created_at = None
        if run_id is not None:
            candidate_created_at = _research_created_at_for_run(
                db,
                asset,
                run_id,
                report_types=("strategy_card", "strategy_card_markdown"),
            )
        if (
            trade_date is not None
            and run_id is not None
            and run_dir is not None
            and not _strategy_anchor_blocks_fs(
                purged_anchors,
                trade_date=trade_date,
                run_id=run_id,
                path=run_dir / "strategy_card.json",
                candidate_created_at=candidate_created_at,
            )
        ):
            json_path = run_dir / "strategy_card.json"
            md_path = run_dir / "strategy_card.md"
            if json_path.exists():
                try:
                    json_data = json.loads(json_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    json_data = None
                if json_data is not None:
                    market_regime = _strategy_market_regime_from_json(json_path)
                    if market_regime is not None:
                        json_data = dict(json_data)
                        json_data.setdefault("market_regime", market_regime)
                    result: dict[str, Any] = {
                        "asset": asset,
                        "trade_date": trade_date,
                        "run_id": run_id,
                        "json": json_data,
                        "paths": {"json": str(json_path.relative_to(_storage._PROJECT_ROOT))},
                    }
                    if market_regime is not None:
                        result["market_regime"] = market_regime
                    if md_path.exists():
                        result["markdown"] = md_path.read_text(encoding="utf-8")
                        result["paths"]["markdown"] = str(md_path.relative_to(_storage._PROJECT_ROOT))
                    return result

        if row is not None and (
            is_output_purged(row)
            or _strategy_anchor_blocks_row(purged_anchors, row)
        ):
            return None
        if row is not None and row.strategy_card is not None:
            market_regime = _resolve_strategy_market_regime_from_row(row)
            json_payload = dict(row.strategy_card)
            if market_regime is not None:
                json_payload.setdefault("market_regime", market_regime)
            result = {
                "asset": asset,
                "trade_date": _iso(row.trade_date),
                "run_id": row.run_id,
                "json": json_payload,
                "paths": {},
            }
            if market_regime is not None:
                result["market_regime"] = market_regime
            if row.strategy_card_md_path:
                md_path = _storage._PROJECT_ROOT / row.strategy_card_md_path
                if md_path.exists():
                    result["markdown"] = md_path.read_text(encoding="utf-8")
                    result["paths"]["markdown"] = str(md_path.relative_to(_storage._PROJECT_ROOT))
            if row.strategy_card_json_path:
                result["paths"]["json"] = row.strategy_card_json_path
            return result
        return None
    except Exception:
        return None
    finally:
        db.close()


def get_strategy_card(date: str, run_id: str, asset: str = "XAUUSD") -> dict[str, Any] | None:
    db = _storage._try_db_session()
    purged_anchors: list[dict[str, Any]] = []
    candidate_created_at = None
    if db is not None:
        try:
            purged_anchors = _strategy_purged_anchors(db, asset)
            candidate_created_at = _research_created_at_for_run(
                db,
                asset,
                run_id,
                report_types=("strategy_card", "strategy_card_markdown"),
            )
            if _strategy_anchor_matches(purged_anchors, run_id=run_id, snapshot_id=run_id):
                return None
            from database.queries.analysis import get_final_analysis

            row = get_final_analysis(db, asset, date, run_id)
            if row is not None and is_output_purged(row):
                return None
            if row is not None and row.strategy_card is not None:
                market_regime = _resolve_strategy_market_regime_from_row(row)
                json_payload = dict(row.strategy_card)
                if market_regime is not None:
                    json_payload.setdefault("market_regime", market_regime)
                result: dict[str, Any] = {
                    "asset": asset,
                    "trade_date": date,
                    "run_id": run_id,
                    "json": json_payload,
                    "paths": {},
                }
                if market_regime is not None:
                    result["market_regime"] = market_regime
                if row.strategy_card_md_path:
                    md_path = _storage._PROJECT_ROOT / row.strategy_card_md_path
                    if md_path.exists():
                        result["markdown"] = md_path.read_text(encoding="utf-8")
                        result["paths"]["markdown"] = str(md_path.relative_to(_storage._PROJECT_ROOT))
                if row.strategy_card_json_path:
                    result["paths"]["json"] = row.strategy_card_json_path
                return result
        except Exception:
            pass
        finally:
            db.close()
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "strategy_card" / asset / date / run_id
    json_path = base / "strategy_card.json"
    md_path = base / "strategy_card.md"
    if not json_path.exists():
        return None
    if _strategy_anchor_blocks_fs(
        purged_anchors,
        trade_date=date,
        run_id=run_id,
        path=json_path,
        candidate_created_at=candidate_created_at,
    ):
        return None
    try:
        json_data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    market_regime = _strategy_market_regime_from_json(json_path)
    if market_regime is not None:
        json_data = dict(json_data)
        json_data.setdefault("market_regime", market_regime)
    result: dict[str, Any] = {
        "asset": asset,
        "trade_date": date,
        "run_id": run_id,
        "json": json_data,
        "paths": {"json": str(json_path.relative_to(_storage._PROJECT_ROOT))},
    }
    if market_regime is not None:
        result["market_regime"] = market_regime
    if md_path.exists():
        result["markdown"] = md_path.read_text(encoding="utf-8")
        result["paths"]["markdown"] = str(md_path.relative_to(_storage._PROJECT_ROOT))
    return result


def _build_strategy_card_summary(
    *,
    strategy_card_id: str,
    asset: str,
    trade_date: str,
    run_id: str,
    snapshot_id: str | None,
    sc_data: dict[str, Any],
    paths: dict[str, str],
    source_refs: list,
    artifact_refs: list[str],
    market_regime: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "strategy_card_id": strategy_card_id,
        "asset": asset,
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "status": _strategy_card_status(sc_data),
        "bias": sc_data.get("bias"),
        "confidence": sc_data.get("confidence"),
        "market_regime": market_regime if market_regime is not None else sc_data.get("market_regime"),
        "updated_at": updated_at or _strategy_card_payload_timestamp(sc_data),
        "paths": paths,
        "source_refs": source_refs or [],
        "artifact_refs": artifact_refs,
    }


def _build_strategy_card_detail(
    *,
    strategy_card_id: str,
    asset: str,
    trade_date: str,
    run_id: str,
    snapshot_id: str | None,
    sc_data: dict[str, Any],
    paths: dict[str, str],
    source_refs: list,
    artifact_refs: list[str],
    md_content: str | None = None,
    market_regime: str | None = None,
) -> dict[str, Any]:
    detail_source_refs = (
        source_refs or (sc_data.get("source_refs") if isinstance(sc_data.get("source_refs"), list) else []) or []
    )
    result: dict[str, Any] = {
        "strategy_card_id": strategy_card_id,
        "asset": asset,
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "status": _strategy_card_status(sc_data),
        "bias": sc_data.get("bias"),
        "confidence": sc_data.get("confidence"),
        "market_regime": market_regime if market_regime is not None else sc_data.get("market_regime"),
        "updated_at": sc_data.get("created_at"),
        "paths": paths,
        "source_refs": detail_source_refs,
        "artifact_refs": artifact_refs,
        "hero": _build_strategy_hero(
            sc_data,
            trade_date=trade_date,
            run_id=run_id,
            snapshot_id=snapshot_id,
            source_refs=detail_source_refs,
            market_regime=market_regime,
        ),
        "scenario": _build_strategy_scenario(sc_data),
        "module_signals": sc_data.get("module_signals") or [],
        "playbook_matches": sc_data.get("playbook_matches") or [],
        "has_data": bool(sc_data or md_content or paths),
        "daily_update": _build_strategy_daily_update(anchor_trade_date=trade_date),
        "weekend_context": _build_strategy_weekend_context(
            asset=asset,
            anchor_trade_date=trade_date,
            anchor_run_id=run_id,
            sc_data=sc_data,
        ),
        "json": sc_data,
    }
    if md_content is not None:
        result["markdown"] = md_content
    return result


def _build_strategy_daily_update(*, anchor_trade_date: str) -> dict[str, Any]:
    """Expose today's processing/update layer without rewriting the formal StrategyCard."""
    try:
        from apps.api.services.daily_analysis_followup_service import get_daily_analysis_followups_latest

        payload = get_daily_analysis_followups_latest(project_root=_storage._PROJECT_ROOT)
    except Exception:
        logger.exception("Failed to load daily strategy update context")
        payload = None

    if not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "date": None,
            "run_id": None,
            "anchor_trade_date": anchor_trade_date,
            "queue_count": 0,
            "high_priority_count": 0,
            "items": [],
            "message": "今日更新层未找到 daily_analysis_followups 产物。",
        }

    followups = [dict(item) for item in payload.get("followups") or [] if isinstance(item, dict)]
    items = [
        {
            "title": str(item.get("title") or item.get("source_title") or "未命名跟进项"),
            "priority": str(item.get("priority") or "medium"),
            "status": str(item.get("status") or "queued"),
            "gold_impact": item.get("gold_impact"),
            "summary": item.get("summary") or item.get("evidence_text"),
            "source_url": item.get("source_url"),
        }
        for item in followups[:5]
    ]
    queue_count = int(payload.get("queue_count") or len(followups))
    status = str(payload.get("status") or ("available" if queue_count else "empty"))
    message = (
        f"今日更新层发现 {queue_count} 条待加工跟进项。"
        if queue_count
        else "今日更新检查已完成，暂无需要追加到策略框架的跟进项。"
    )
    return {
        "status": status,
        "date": payload.get("date"),
        "run_id": payload.get("run_id"),
        "anchor_trade_date": anchor_trade_date,
        "queue_count": queue_count,
        "high_priority_count": int(payload.get("high_priority_count") or 0),
        "source_artifact": payload.get("source_artifact"),
        "artifact_path": payload.get("artifact_path"),
        "as_of": payload.get("as_of"),
        "items": items,
        "message": message,
    }


def _build_strategy_weekend_context(
    *,
    asset: str,
    anchor_trade_date: str,
    anchor_run_id: str,
    sc_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a weekend/opening outlook from existing reports without creating a new formal StrategyCard."""
    try:
        reports = list_reports_index(asset=asset).get("reports", [])
    except Exception:
        logger.exception("Failed to build strategy weekend context")
        return None
    if not isinstance(reports, list):
        return None

    latest_report_date = _latest_report_date(reports)
    weekly_report = _first_report(
        reports,
        _is_weekend_weekly_report,
    )
    weekly_key = _strategy_report_identity(weekly_report)
    recent_context = [
        _compact_strategy_report_ref(item)
        for item in reports
        if item.get("type") in {"macro_report", "jin10_daily_report", "jin10_weekly_report", "macro_event_followup"}
        and str(item.get("trade_date") or "") > anchor_trade_date
        and _strategy_report_identity(item) != weekly_key
    ][:4]

    should_show = bool(
        weekly_report or recent_context or (latest_report_date and latest_report_date > anchor_trade_date)
    )
    if not should_show:
        return None

    bias = str(sc_data.get("bias") or "unknown")
    confidence = sc_data.get("confidence")
    market_regime = str(sc_data.get("market_regime") or sc_data.get("macro_phase") or "unknown")
    quality_flags = _weekend_quality_flags(recent_context)
    prediction = _build_weekend_opening_outlook(
        bias=bias,
        confidence=confidence,
        market_regime=market_regime,
        weekly_report=weekly_report,
        recent_context=recent_context,
        quality_flags=quality_flags,
    )

    return {
        "status": "active",
        "mode": "weekend",
        "anchor_trade_date": anchor_trade_date,
        "anchor_run_id": anchor_run_id,
        "latest_report_date": latest_report_date,
        "weekly_report": _compact_strategy_report_ref(weekly_report) if weekly_report else None,
        "recent_context": recent_context,
        "monday_outlook": prediction,
        "quality_flags": quality_flags,
        "message": "周末模式：正式策略不改写，基于最后综合分析、周末报告和近两天宏观动态给出周一开盘预测框架。",
    }


def _first_report(reports: list[Any], predicate: Any) -> dict[str, Any] | None:
    for item in reports:
        if isinstance(item, dict) and predicate(item):
            return item
    return None


def _strategy_report_identity(item: dict[str, Any] | None) -> tuple[str | None, str | None, str | None] | None:
    if not isinstance(item, dict):
        return None
    return (item.get("type"), item.get("trade_date"), item.get("run_id") or item.get("report_id"))


def _latest_report_date(reports: list[Any]) -> str | None:
    dates = [str(item.get("trade_date") or "") for item in reports if isinstance(item, dict) and item.get("trade_date")]
    return max(dates) if dates else None


def _compact_strategy_report_ref(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    display_title = _strategy_report_display_title(item)
    return {
        "type": item.get("type"),
        "trade_date": item.get("trade_date"),
        "run_id": item.get("run_id"),
        "report_id": item.get("report_id"),
        "title": display_title,
        "status": item.get("status") or ("ready" if item.get("available") else "unavailable"),
        "summary": item.get("summary"),
        "anchor_trade_date": item.get("anchor_trade_date"),
    }


def _is_weekend_weekly_report(item: dict[str, Any]) -> bool:
    if item.get("type") == "jin10_weekly_report":
        return True
    text = " ".join(str(item.get(key) or "") for key in ("title", "source_title", "summary"))
    return "周" in text


def _strategy_report_display_title(item: dict[str, Any] | None) -> str | None:
    if not isinstance(item, dict):
        return None
    source_title = item.get("source_title")
    if source_title and "周" in str(source_title):
        return str(source_title)
    title = item.get("title")
    return str(title) if title else None


def _weekend_quality_flags(recent_context: list[dict[str, Any] | None]) -> list[str]:
    flags: list[str] = []
    if not recent_context:
        flags.append("missing_recent_context")
    if any(str(item.get("status") or "") == "degraded" for item in recent_context if item):
        flags.append("degraded_recent_report")
    return flags


def _build_weekend_opening_outlook(
    *,
    bias: str,
    confidence: Any,
    market_regime: str,
    weekly_report: dict[str, Any] | None,
    recent_context: list[dict[str, Any] | None],
    quality_flags: list[str],
) -> dict[str, Any]:
    direction = "等待确认"
    confidence_value = float(confidence) if isinstance(confidence, int | float) else None
    if bias == "bullish" and confidence_value is not None and confidence_value >= 0.2:
        direction = "偏多观察"
    elif bias == "bearish" and confidence_value is not None and confidence_value >= 0.2:
        direction = "偏空观察"
    elif bias in {"bullish", "bearish"}:
        direction = "方向存在但置信度不足"

    weekly_title = _strategy_report_display_title(weekly_report) or "无明确周报"
    context_titles = [str(item.get("title") or item.get("type") or "") for item in recent_context if item]
    summary_parts = [
        f"最后正式框架为 {bias}，宏观状态 {market_regime}。",
        f"周末输入包含 {weekly_title}。",
        f"近两天动态：{'；'.join(context_titles[:3]) if context_titles else '暂无可用新增动态'}。",
    ]
    if quality_flags:
        summary_parts.append(f"质量限制：{', '.join(quality_flags)}。")

    return {
        "direction": direction,
        "summary": "".join(summary_parts),
        "monday_open_bias": direction,
        "watch_points": [
            "周一开盘先验证跳空方向与亚洲盘延续性。",
            "若周末/近两天宏观动态仍为 degraded，不放大单一路径。",
            "优先等待实时点位、美元/美债收益率和黄金关键价位共振确认。",
        ],
        "invalidation": [
            "实时点位与最后正式框架方向背离。",
            "美元或美债收益率出现与黄金方向相反的快速重定价。",
            "新增宏观事件被确认但尚未进入正式 premarket 综合分析链路。",
        ],
    }


def _build_strategy_hero(
    sc_data: dict[str, Any],
    *,
    trade_date: str,
    run_id: str,
    snapshot_id: str | None,
    source_refs: list[Any],
    market_regime: str | None,
) -> dict[str, Any]:
    return {
        "status": _strategy_card_status(sc_data),
        "bias": sc_data.get("bias") or "",
        "direction": sc_data.get("direction") or "unknown",
        "confidence": sc_data.get("confidence"),
        "market_regime": market_regime
        if market_regime is not None
        else sc_data.get("market_regime") or sc_data.get("macro_phase"),
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "source_refs": source_refs,
    }


def _strategy_card_status(sc_data: dict[str, Any]) -> str:
    explicit_status = str(sc_data.get("status") or "").strip().lower()
    if explicit_status in {"available", "partial", "unavailable", "error"}:
        return explicit_status

    data_quality = {str(item).strip().lower() for item in sc_data.get("data_quality") or [] if str(item).strip()}
    scenario_summary = str(sc_data.get("scenario_summary") or "").lower()
    if data_quality.intersection({"observe_wait", "no_strong_conclusion"}) or "blocked" in scenario_summary:
        return "partial"
    return "available" if sc_data else "unavailable"


def _build_strategy_scenario(sc_data: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(sc_data, dict) or not sc_data:
        return None
    main_scenario = sc_data.get("main_scenario") or sc_data.get("scenario_summary") or ""
    has_scenario_fields = any(
        [
            bool(main_scenario),
            bool(sc_data.get("alternative_scenarios")),
            bool(sc_data.get("key_levels")),
            bool(sc_data.get("key_levels_from_options")),
            bool(sc_data.get("trigger_conditions") or sc_data.get("triggers")),
            bool(sc_data.get("invalidation_conditions") or sc_data.get("invalid_conditions")),
            bool(sc_data.get("confirmation_conditions")),
            bool(sc_data.get("risk_points")),
            bool(sc_data.get("watchlist")),
        ]
    )
    if not has_scenario_fields:
        return None
    key_levels = _build_strategy_key_levels(sc_data)
    return {
        "main_scenario": str(main_scenario),
        "alternative_scenarios": list(sc_data.get("alternative_scenarios") or []),
        "key_levels": key_levels,
        "trigger_conditions": list(sc_data.get("trigger_conditions") or sc_data.get("triggers") or []),
        "invalidation_conditions": list(
            sc_data.get("invalidation_conditions") or sc_data.get("invalid_conditions") or []
        ),
        "confirmation_conditions": list(sc_data.get("confirmation_conditions") or []),
        "risk_points": list(sc_data.get("risk_points") or []),
        "watchlist": list(sc_data.get("watchlist") or []),
    }


def _build_strategy_key_levels(sc_data: dict[str, Any]) -> dict[str, list[float]]:
    key_levels = sc_data.get("key_levels")
    if isinstance(key_levels, dict):
        return {
            "resistance": _coerce_numeric_list(key_levels.get("resistance")),
            "support": _coerce_numeric_list(key_levels.get("support")),
        }
    return {
        "resistance": _coerce_key_levels_from_options(sc_data.get("key_levels_from_options")),
        "support": [],
    }


def _coerce_numeric_list(raw: Any) -> list[float]:
    if not isinstance(raw, list):
        return []
    values: list[float] = []
    for item in raw:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if number.is_integer():
            values.append(int(number))
        else:
            values.append(number)
    return values


def _coerce_key_levels_from_options(raw: Any) -> list[float]:
    if not isinstance(raw, list):
        return []
    values: list[float] = []
    for item in raw:
        if isinstance(item, (int, float)):
            values.append(int(item) if float(item).is_integer() else float(item))
            continue
        if not isinstance(item, str):
            continue
        for match in re.findall(r"\d+(?:\.\d+)?", item):
            number = float(match)
            values.append(int(number) if number.is_integer() else number)
    return values


def _derive_strategy_card_id(row: FinalAnalysisResult, sc_data: dict[str, Any]) -> str:
    return (
        sc_data.get("strategy_card_id")
        or row.run_id
        or row.snapshot_id
        or f"{row.asset}:{_iso(row.trade_date)}:{row.run_id}"
    )


def _collect_fs_strategy_cards(
    base: Path,
    asset: str,
    limit: int,
    *,
    purged_anchors: list[dict[str, Any]] | None = None,
    created_at_by_run: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Scan filesystem for strategy card summaries when DB is unavailable."""
    items: list[dict[str, Any]] = []
    asset_dir = base / asset
    if not asset_dir.exists():
        return items
    for date_dir in sorted((d for d in asset_dir.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            json_path = run_dir / "strategy_card.json"
            if not json_path.exists():
                continue
            if _strategy_anchor_blocks_fs(
                purged_anchors or [],
                trade_date=date_dir.name,
                run_id=run_dir.name,
                path=json_path,
                candidate_created_at=(created_at_by_run or {}).get(run_dir.name),
            ):
                continue
            try:
                sc_data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            paths: dict[str, str] = {"json": str(json_path.relative_to(_storage._PROJECT_ROOT))}
            md_path = run_dir / "strategy_card.md"
            if md_path.exists():
                paths["markdown"] = str(md_path.relative_to(_storage._PROJECT_ROOT))
            strategy_card_id = sc_data.get("strategy_card_id") or run_dir.name
            market_regime = _strategy_market_regime_from_json(json_path)
            items.append(
                _build_strategy_card_summary(
                    strategy_card_id=strategy_card_id,
                    asset=asset,
                    trade_date=date_dir.name,
                    run_id=run_dir.name,
                    snapshot_id=None,
                    sc_data=sc_data,
                    paths=paths,
                    source_refs=[],
                    artifact_refs=[str(json_path.relative_to(_storage._PROJECT_ROOT))],
                    market_regime=market_regime,
                    updated_at=(
                        _strategy_card_payload_timestamp(sc_data) or _generated_at_from_paths(json_path, md_path)
                    ),
                )
            )
        if len(items) >= limit:
            break
    return sorted(items, key=_strategy_card_sort_key, reverse=True)[:limit]


def _strategy_card_payload_timestamp(sc_data: dict[str, Any]) -> str | None:
    for key in ("updated_at", "created_at", "generated_at"):
        value = sc_data.get(key)
        if isinstance(value, str) and _strategy_card_timestamp_value(value) > 0:
            return value
    return None


def _strategy_card_timestamp_value(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _strategy_card_sort_key(item: dict[str, Any]) -> tuple[str, float, str, str]:
    return (
        str(item.get("trade_date") or ""),
        _strategy_card_timestamp_value(item.get("updated_at")),
        str(item.get("run_id") or ""),
        str(item.get("strategy_card_id") or ""),
    )


def _merge_strategy_card_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in sorted(items, key=_strategy_card_sort_key, reverse=True):
        key = (
            str(item.get("strategy_card_id") or ""),
            str(item.get("trade_date") or ""),
            str(item.get("run_id") or ""),
        )
        if key in deduped:
            continue
        deduped[key] = item
    return sorted(deduped.values(), key=_strategy_card_sort_key, reverse=True)[:limit]


def _collect_fs_strategy_assets(
    base: Path, *, purged_anchors: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    if not base.exists():
        return []
    items: list[dict[str, Any]] = []
    for asset_dir in sorted((d for d in base.iterdir() if d.is_dir()), key=lambda path: path.name):
        sample_size = 0
        latest_trade_date: str | None = None
        latest_run_id: str | None = None
        latest_snapshot_id: str | None = None
        regime_counts: defaultdict[str, int] = defaultdict(int)
        for date_dir in sorted((d for d in asset_dir.iterdir() if d.is_dir()), reverse=True):
            for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
                json_path = run_dir / "strategy_card.json"
                if not json_path.exists():
                    continue
                if _strategy_anchor_matches(purged_anchors or [], run_id=run_dir.name):
                    continue
                sample_size += 1
                if latest_trade_date is None:
                    latest_trade_date = date_dir.name
                    latest_run_id = run_dir.name
                    try:
                        payload = json.loads(json_path.read_text(encoding="utf-8"))
                    except Exception:
                        payload = {}
                    if isinstance(payload, dict):
                        snapshot_id = payload.get("snapshot_id")
                        latest_snapshot_id = snapshot_id if isinstance(snapshot_id, str) else None
                regime = _strategy_market_regime_from_json(json_path)
                if regime is not None:
                    regime_counts[regime] += 1
        if sample_size > 0:
            items.append(
                {
                    "asset": asset_dir.name,
                    "sample_size": sample_size,
                    "latest_trade_date": latest_trade_date,
                    "latest_run_id": latest_run_id,
                    "latest_snapshot_id": latest_snapshot_id,
                    "regime_counts": _strategy_regime_counts_payload(regime_counts),
                }
            )
    return items


def _summarize_strategy_assets(rows: list[FinalAnalysisResult]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row.asset:
            continue
        item = grouped.setdefault(
            row.asset,
            {
                "asset": row.asset,
                "sample_size": 0,
                "latest_trade_date": None,
                "latest_run_id": None,
                "latest_snapshot_id": None,
                "_regime_counts": defaultdict(int),
            },
        )
        item["sample_size"] += 1
        regime = _resolve_strategy_market_regime_from_row(row)
        if regime is not None:
            item["_regime_counts"][regime] += 1
        if item["latest_trade_date"] is None:
            item["latest_trade_date"] = _iso(row.trade_date) if row.trade_date else None
            item["latest_run_id"] = row.run_id
            item["latest_snapshot_id"] = row.snapshot_id
    items: list[dict[str, Any]] = []
    for item in grouped.values():
        regime_counts = item.pop("_regime_counts", defaultdict(int))
        item["regime_counts"] = _strategy_regime_counts_payload(regime_counts)
        items.append(item)
    return items


def _strategy_market_regime_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("market_regime") or payload.get("macro_phase")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _strategy_market_regime_from_analysis_snapshot_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in ("market_regime", "market_phase"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    macro = payload.get("macro")
    if not isinstance(macro, dict):
        return None

    for key in ("market_regime", "market_phase"):
        value = macro.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if macro.get("status") != "available":
        return None

    data = macro.get("data")
    if not isinstance(data, dict):
        return None
    indicators = data.get("indicators")
    if not isinstance(indicators, dict):
        return None

    phase = classify_macro_regime(indicators).get("market_phase")
    if not isinstance(phase, str):
        return None
    phase = phase.strip()
    return phase or None


def _resolve_strategy_market_regime_from_row(row: FinalAnalysisResult) -> str | None:
    regime = _strategy_market_regime_from_payload(row.strategy_card)
    if regime is not None:
        return regime
    snapshot_macro = getattr(row, "snapshot_macro", None)
    if isinstance(snapshot_macro, dict):
        regime = _strategy_market_regime_from_analysis_snapshot_payload({"macro": snapshot_macro})
        if regime is not None:
            return regime
    snapshot = getattr(row, "analysis_snapshot", None)
    if snapshot is not None:
        if isinstance(snapshot.macro, dict):
            regime = _strategy_market_regime_from_analysis_snapshot_payload({"macro": snapshot.macro})
            if regime is not None:
                return regime
        if isinstance(snapshot.payload, dict):
            regime = _strategy_market_regime_from_analysis_snapshot_payload(snapshot.payload)
            if regime is not None:
                return regime
    return None


def _load_strategy_analysis_snapshot_payload(json_path: Path) -> dict[str, Any] | None:
    try:
        parts = json_path.resolve().parts
    except Exception:
        return None
    try:
        storage_idx = parts.index("storage")
    except ValueError:
        return None
    if len(parts) < storage_idx + 6:
        return None
    asset = parts[storage_idx + 3]
    trade_date = parts[storage_idx + 4]
    run_id = parts[storage_idx + 5]
    analysis_path = (
        _storage._PROJECT_ROOT / "storage" / "features" / "snapshots" / asset / trade_date / run_id / "premarket_snapshot.json"
    )
    if not analysis_path.exists():
        return None
    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _strategy_market_regime_from_json(json_path: Path) -> str | None:
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    regime = _strategy_market_regime_from_payload(payload)
    if regime is not None:
        return regime
    return _strategy_market_regime_from_analysis_snapshot_payload(_load_strategy_analysis_snapshot_payload(json_path))


def _strategy_regime_counts_payload(regime_counts: defaultdict[str, int]) -> list[dict[str, Any]]:
    return [
        {"market_regime": regime, "sample_size": sample_size}
        for regime, sample_size in sorted(regime_counts.items(), key=lambda item: (-item[1], item[0]))
        if sample_size > 0
    ]


def list_strategy_cards(asset: str = "XAUUSD", limit: int = 20) -> dict[str, Any]:
    """Return a list of strategy card summaries ordered by latest trade_date."""
    limit = min(max(limit, 1), 100)
    items: list[dict[str, Any]] = []
    purged_anchors: list[dict[str, Any]] = []
    created_at_by_run: dict[str, Any] = {}
    db = _storage._try_db_session()
    if db is not None:
        try:
            purged_anchors = _strategy_purged_anchors(db, asset)
            rows = db.execute(
                select(
                    FinalAnalysisResult.id,
                    FinalAnalysisResult.asset,
                    FinalAnalysisResult.trade_date,
                    FinalAnalysisResult.run_id,
                    FinalAnalysisResult.snapshot_id,
                    FinalAnalysisResult.source_refs,
                    FinalAnalysisResult.strategy_card,
                    FinalAnalysisResult.strategy_card_json_path,
                    FinalAnalysisResult.strategy_card_md_path,
                    FinalAnalysisResult.created_at,
                    FinalAnalysisResult.updated_at,
                    AnalysisSnapshot.macro.label("snapshot_macro"),
                    FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
                )
                .outerjoin(AnalysisSnapshot, FinalAnalysisResult.analysis_snapshot_db_id == AnalysisSnapshot.id)
                .where(
                    FinalAnalysisResult.asset == asset,
                    FinalAnalysisResult.strategy_card.isnot(None),
                )
                .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
                .limit(100)
            ).mappings().all()
            if rows:
                for row in rows:
                    if row.run_id and row.created_at is not None:
                        created_at_by_run[row.run_id] = row.created_at
                    if is_output_purged(row) or _strategy_anchor_matches(
                        purged_anchors, run_id=row.run_id, snapshot_id=row.snapshot_id
                    ):
                        continue
                    sc_data = row.strategy_card
                    if not isinstance(sc_data, dict):
                        continue
                    td = _iso(row.trade_date)
                    market_regime = _resolve_strategy_market_regime_from_row(row)
                    strategy_card_id = _derive_strategy_card_id(row, sc_data)
                    paths: dict[str, str] = {}
                    if row.strategy_card_json_path:
                        paths["json"] = row.strategy_card_json_path
                    if row.strategy_card_md_path:
                        paths["markdown"] = row.strategy_card_md_path
                    artifact_refs: list[str] = []
                    if row.strategy_card_json_path:
                        artifact_refs.append(row.strategy_card_json_path)
                    if row.strategy_card_md_path:
                        artifact_refs.append(row.strategy_card_md_path)
                    items.append(
                        _build_strategy_card_summary(
                            strategy_card_id=strategy_card_id,
                            asset=asset,
                            trade_date=td,
                            run_id=row.run_id,
                            snapshot_id=row.snapshot_id,
                            sc_data=sc_data,
                            paths=paths,
                            source_refs=row.source_refs if isinstance(row.source_refs, list) else [],
                            artifact_refs=artifact_refs,
                            market_regime=market_regime,
                            updated_at=(
                                _generated_at_from_datetime(getattr(row, "updated_at", None))
                                or _generated_at_from_datetime(getattr(row, "created_at", None))
                            ),
                        )
                    )
        except Exception:
            pass
        finally:
            db.close()

    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "strategy_card"
    items.extend(
        _collect_fs_strategy_cards(
            base,
            asset,
            100,
            purged_anchors=purged_anchors,
            created_at_by_run=created_at_by_run,
        )
    )
    merged_items = _merge_strategy_card_items(items, limit)
    return {"asset": asset, "count": len(merged_items), "items": merged_items}


def list_strategy_assets() -> dict[str, Any]:
    """Return discovered strategy assets with sample sizes and latest timestamps."""
    purged_anchors: list[dict[str, Any]] = []
    db = _storage._try_db_session()
    if db is not None:
        try:
            purged_anchors = _strategy_purged_anchors(db, None)
            rows = db.execute(
                select(
                    FinalAnalysisResult.id,
                    FinalAnalysisResult.asset,
                    FinalAnalysisResult.trade_date,
                    FinalAnalysisResult.run_id,
                    FinalAnalysisResult.snapshot_id,
                    FinalAnalysisResult.strategy_card,
                    AnalysisSnapshot.macro.label("snapshot_macro"),
                    FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
                )
                .outerjoin(AnalysisSnapshot, FinalAnalysisResult.analysis_snapshot_db_id == AnalysisSnapshot.id)
                .where(
                    FinalAnalysisResult.asset.isnot(None),
                    FinalAnalysisResult.strategy_card.isnot(None),
                )
                .order_by(
                    FinalAnalysisResult.asset.asc(),
                    FinalAnalysisResult.trade_date.desc(),
                    FinalAnalysisResult.id.desc(),
                )
            ).mappings().all()
            if rows:
                rows = [
                    row
                    for row in rows
                    if not is_output_purged(row)
                    and not _strategy_anchor_matches(purged_anchors, run_id=row.run_id, snapshot_id=row.snapshot_id)
                ]
                items = _summarize_strategy_assets(rows)
                return {"count": len(items), "items": items}
        except Exception:
            pass
        finally:
            db.close()

    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "strategy_card"
    items = _collect_fs_strategy_assets(base, purged_anchors=purged_anchors)
    return {"count": len(items), "items": items}


def get_strategy_card_by_id(
    strategy_card_id: str,
    asset: str = "XAUUSD",
    *,
    _allow_filesystem_fallback: bool = True,
    _db_session: Any | None = None,
) -> dict[str, Any] | None:
    """Find a strategy card by strategy_card_id, run_id, or snapshot_id."""
    supplied_db = _db_session is not None
    if supplied_db:
        db = _db_session
    else:
        try:
            db = _storage._try_db_session()
        except Exception:
            db = None
    purged_anchors: list[dict[str, Any]] = []
    candidate_created_at = None
    if db is not None:
        try:
            purged_anchors = _strategy_purged_anchors(db, asset)
            candidate_run_id = strategy_card_id
            for prefix in ("strategy_card:", "final_report:"):
                if candidate_run_id.startswith(prefix):
                    candidate_run_id = candidate_run_id[len(prefix) :]
                    break
            candidate_created_at = _research_created_at_for_run(
                db,
                asset,
                candidate_run_id,
                report_types=("strategy_card", "strategy_card_markdown"),
            )
            if _strategy_anchor_matches(purged_anchors, run_id=strategy_card_id, snapshot_id=strategy_card_id):
                return None
            rows = db.scalars(
                select(FinalAnalysisResult)
                .where(
                    FinalAnalysisResult.asset == asset,
                    FinalAnalysisResult.strategy_card.isnot(None),
                )
                .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
            ).all()
            for row in rows:
                if is_output_purged(row):
                    if strategy_card_id in {str(row.run_id), str(row.snapshot_id or "")}:
                        return None
                    continue
                sc_data = row.strategy_card
                if not isinstance(sc_data, dict):
                    continue
                row_sc_id = _derive_strategy_card_id(row, sc_data)
                if strategy_card_id in (row_sc_id, row.run_id, row.snapshot_id):
                    td = _iso(row.trade_date)
                    market_regime = _resolve_strategy_market_regime_from_row(row)
                    paths: dict[str, str] = {}
                    if row.strategy_card_json_path:
                        paths["json"] = row.strategy_card_json_path
                    if row.strategy_card_md_path:
                        paths["markdown"] = row.strategy_card_md_path
                    md_content: str | None = None
                    if row.strategy_card_md_path:
                        md_path = _storage._PROJECT_ROOT / row.strategy_card_md_path
                        if md_path.exists():
                            md_content = md_path.read_text(encoding="utf-8")
                    artifact_refs: list[str] = []
                    if row.strategy_card_json_path:
                        artifact_refs.append(row.strategy_card_json_path)
                    if row.strategy_card_md_path:
                        artifact_refs.append(row.strategy_card_md_path)
                    return _build_strategy_card_detail(
                        strategy_card_id=row_sc_id,
                        asset=asset,
                        trade_date=td,
                        run_id=row.run_id,
                        snapshot_id=row.snapshot_id,
                        sc_data=sc_data,
                        paths=paths,
                        source_refs=row.source_refs if isinstance(row.source_refs, list) else [],
                        artifact_refs=artifact_refs,
                        md_content=md_content,
                        market_regime=market_regime,
                    )
        except Exception:
            if supplied_db:
                return None
        finally:
            if not supplied_db:
                db.close()

    if not _allow_filesystem_fallback:
        return None

    if _strategy_anchor_matches(purged_anchors, run_id=strategy_card_id, snapshot_id=strategy_card_id):
        return None

    # Filesystem fallback
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "strategy_card" / asset
    if not base.exists():
        return None
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            json_path = run_dir / "strategy_card.json"
            if not json_path.exists():
                continue
            try:
                sc_data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            fs_id = sc_data.get("strategy_card_id") or run_dir.name
            if strategy_card_id not in (fs_id, run_dir.name):
                continue
            if _strategy_anchor_blocks_fs(
                purged_anchors,
                trade_date=date_dir.name,
                run_id=run_dir.name,
                path=json_path,
                candidate_created_at=candidate_created_at,
            ):
                return None
            paths = {"json": str(json_path.relative_to(_storage._PROJECT_ROOT))}
            md_path = run_dir / "strategy_card.md"
            md_content = None
            if md_path.exists():
                md_content = md_path.read_text(encoding="utf-8")
                paths["markdown"] = str(md_path.relative_to(_storage._PROJECT_ROOT))
            market_regime = _strategy_market_regime_from_json(json_path)
            return _build_strategy_card_detail(
                strategy_card_id=fs_id,
                asset=asset,
                trade_date=date_dir.name,
                run_id=run_dir.name,
                snapshot_id=None,
                sc_data=sc_data,
                paths=paths,
                source_refs=[],
                artifact_refs=list(paths.values()),
                md_content=md_content,
                market_regime=market_regime,
            )
    return None


def get_strategy_card_read_model_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    """Return the latest strategy card as a read model detail (reuses list + by_id)."""
    latest = get_strategy_card_latest(asset=asset)
    if latest is None:
        return None
    # This is a current read model.  Keep one healthy DB session for the
    # detail lookup so a second failed session cannot reopen a residual file.
    try:
        db = _storage._try_db_session()
    except Exception:
        return None
    if db is None:
        return None
    try:
        db.execute(select(1))
        return get_strategy_card_by_id(
            str(latest.get("run_id") or ""),
            asset=asset,
            _db_session=db,
        )
    except Exception:
        return None
    finally:
        db.close()
