from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from apps.analysis.agents.weekly_context_revision import (
    apply_weekly_context_revision_llm,
    invoke_weekly_context_revision_llm,
    mark_weekly_context_revision_llm_failure,
)
from apps.output.weekly_context_revision import write_weekly_context_revision
from apps.renderer.markdown.weekly_context_revision import (
    build_weekly_context_revision_payload,
    render_weekly_context_revision_analysis_markdown,
    render_weekly_context_revision_source_markdown,
)


def build_weekly_context_revision_input_snapshot(
    *,
    article_id: str,
    baseline_date: str,
    trade_date: str,
    asset: str = "XAUUSD",
    storage_root: Path = Path("./storage"),
) -> dict[str, Any]:
    date.fromisoformat(baseline_date)
    date.fromisoformat(trade_date)
    baseline_path = storage_root / "outputs" / "jin10" / baseline_date / article_id / "agent_analysis_report.json"
    baseline = _read_json(baseline_path)
    if baseline is None:
        return _blocked_snapshot(
            article_id=article_id,
            baseline_date=baseline_date,
            trade_date=trade_date,
            asset=asset,
            reason="missing_weekly_baseline",
        )

    context = _latest_premarket_snapshot(
        storage_root=storage_root,
        asset=asset,
        start_date=baseline_date,
        end_date=trade_date,
    )
    if context is None:
        return _blocked_snapshot(
            article_id=article_id,
            baseline_date=baseline_date,
            trade_date=trade_date,
            asset=asset,
            reason="missing_premarket_context",
            baseline=baseline,
            baseline_path=baseline_path,
        )

    context_date, context_run_id, context_path, premarket = context
    news_brief_path = storage_root / "features" / "news" / context_date / context_run_id / "daily_market_brief.json"
    overview_path = storage_root / "analysis" / "gold_mainlines" / context_date / context_run_id / "gold_macro_overview.json"
    oil_path = storage_root / "analysis" / "gold_mainlines" / context_date / context_run_id / "oil_context.json"
    news_brief_bundle = _read_json(news_brief_path) or {}
    news_brief = _dict(news_brief_bundle.get("daily_market_brief"))
    overview = _read_json(overview_path) or {}
    oil_context = _read_json(oil_path) or {}

    technical = _available_payload(premarket.get("technical"))
    macro = _available_payload(premarket.get("macro"))
    options = _available_payload(premarket.get("options"))
    positioning = _available_payload(premarket.get("positioning"))
    indicators = _dict(macro.get("indicators"))
    snapshot_time = str(premarket.get("snapshot_time") or premarket.get("trade_date") or context_date)
    price = _number(technical.get("price"))
    us10y = _indicator_value(indicators, "US10Y")
    real_10y = _indicator_value(indicators, "REAL_10Y")
    breakeven_10y = _indicator_value(indicators, "BREAKEVEN_10Y")
    dxy = _indicator_value(indicators, "DXY")
    rates_as_of = _latest_indicator_date(indicators, ("US10Y", "REAL_10Y", "BREAKEVEN_10Y", "DXY"))
    options_trade_date = str(options.get("trade_date") or "")
    positioning_as_of = str(positioning.get("as_of") or "")
    oil_as_of = str(oil_context.get("as_of") or oil_context.get("trade_date") or "")
    news_as_of = str(news_brief.get("as_of") or "")

    price_confirmation = {
        "status": "observed" if price is not None else "pending",
        "basis": "point_quote" if price is not None else "missing",
        "current_price": price,
        "as_of": snapshot_time,
        "note": "点报价只能用于观察，不能代替 4H 或日线收盘确认。",
    }
    rates_confirmation = {
        "status": "confirmed" if us10y is not None and real_10y is not None else "pending",
        "us10y": us10y,
        "real_10y": real_10y,
        "breakeven_10y": breakeven_10y,
        "dxy": dxy,
        "as_of": rates_as_of,
    }
    options_confirmation = _options_confirmation(options)
    macro_confirmation = {
        "status": "confirmed" if macro else "pending",
        "as_of": str(macro.get("as_of") or context_date),
    }
    geopolitical_confirmation = {
        "status": "observed" if news_brief else "pending",
        "as_of": news_as_of,
        "risk_level": _dict(news_brief.get("market_mainline")).get("risk_level"),
        "summary": _dict(news_brief.get("market_mainline")).get("summary"),
        "oil_price_confirmation": "confirmed" if oil_context else "pending",
    }
    positioning_check = {
        "status": "confirmed" if positioning else "pending",
        "as_of": positioning_as_of,
        "noncomm_net": _number(positioning.get("noncomm_net")),
        "noncomm_net_prev": _number(positioning.get("noncomm_net_prev")),
        "commercial_net": _number(positioning.get("commercial_net")),
        "commercial_net_prev": _number(positioning.get("commercial_net_prev")),
        "extreme_reading": positioning.get("extreme_reading"),
    }

    baseline_quality = _baseline_quality(baseline)
    quality_flags: list[str] = []
    warnings: list[str] = []
    if baseline_quality != "accepted":
        quality_flags.append("baseline_needs_review")
        warnings.append("Weekly baseline is not accepted; revision must remain observe-only.")
    for key, item in (
        ("price", price_confirmation),
        ("rates", rates_confirmation),
        ("options", options_confirmation),
    ):
        if str(item.get("status")) == "pending":
            quality_flags.append(f"missing_{key}_confirmation")
            warnings.append(f"{key} confirmation is unavailable for {trade_date}.")
    high_geopolitical_risk = str(geopolitical_confirmation.get("risk_level") or "").lower() == "high"
    if high_geopolitical_risk and not oil_context:
        quality_flags.append("missing_oil_confirmation")
        warnings.append("High geopolitical risk is present but deterministic Brent/WTI context is unavailable.")

    baseline_claims = _baseline_claims(baseline)
    chain = _dict(overview.get("war_oil_rate_chain"))
    if not chain:
        chain = {
            "status": "pending",
            "label": "地缘风险 -> 油价 -> 通胀预期 -> 实际利率 -> 黄金",
            "dominant_driver": None,
        }
    else:
        chain = {
            "status": "confirmed" if oil_context else "observed",
            **{
                key: value
                for key, value in chain.items()
                if key
                in {
                    "label",
                    "dominant_driver",
                    "net_effect",
                    "path_id",
                    "conclusion_code",
                    "conclusion_label",
                    "summary",
                }
            },
        }

    input_snapshot_ids = {
        "weekly_baseline": _relative(storage_root, baseline_path),
        "premarket_snapshot": _relative(storage_root, context_path),
    }
    for key, path in (
        ("daily_market_brief", news_brief_path),
        ("gold_macro_overview", overview_path),
        ("oil_context", oil_path),
    ):
        if path.exists():
            input_snapshot_ids[key] = _relative(storage_root, path)

    source_refs = _dedupe_refs(
        [
            *_source_refs(baseline)[:20],
            *_source_refs(technical),
            *_selected_macro_source_refs(macro),
            *_source_refs(options),
            *_source_refs(positioning)[:5],
            *_selected_news_source_refs(news_brief),
            *_source_refs(_dict(overview.get("war_oil_rate_chain")))[:10],
            *_source_refs(oil_context),
        ]
    )
    new_evidence = [
        {"evidence_id": "price", "category": "price", "status": price_confirmation["status"], "value": price},
        {"evidence_id": "rates", "category": "rates", "status": rates_confirmation["status"], "value": real_10y},
        {
            "evidence_id": "options",
            "category": "options",
            "status": options_confirmation["status"],
            "value": options_confirmation.get("primary_wall"),
        },
        {
            "evidence_id": "positioning",
            "category": "positioning",
            "status": positioning_check["status"],
            "value": positioning_check.get("noncomm_net"),
        },
        {
            "evidence_id": "oil",
            "category": "oil",
            "status": "available" if oil_context else "pending",
            "value": _number(oil_context.get("brent_price")),
        },
        {
            "evidence_id": "news",
            "category": "news",
            "status": "available" if news_brief else "pending",
            "value": geopolitical_confirmation.get("summary"),
        },
    ]
    scenario_updates = [
        {
            "path": str(item.get("path") or f"scenario_{index + 1}"),
            "summary": str(item.get("summary") or "等待触发条件。"),
            "trigger": item.get("trigger"),
            "status": "pending",
        }
        for index, item in enumerate(baseline.get("scenario_paths") or [])
        if isinstance(item, Mapping)
    ]
    watch_items = _watch_items(
        price=price,
        options_confirmation=options_confirmation,
        rates_confirmation=rates_confirmation,
        oil_context=oil_context,
    )

    return {
        "status": "degraded" if quality_flags else "ready",
        "asset": asset,
        "trade_date": trade_date,
        "context_as_of": snapshot_time,
        "anchor": {
            "article_id": article_id,
            "report_date": baseline_date,
            "run_id": str(baseline.get("run_id") or article_id),
            "title": str(baseline.get("title") or "Jin10 weekly report"),
            "baseline_quality_status": baseline_quality,
            "baseline_artifact_refs": [
                {
                    "artifact_type": "jin10_weekly_analysis",
                    "path": _relative(storage_root, baseline_path),
                }
            ],
        },
        "input_snapshot_ids": input_snapshot_ids,
        "freshness": {
            "baseline": {"status": "available", "as_of": baseline_date},
            "price": {"status": price_confirmation["status"], "as_of": snapshot_time},
            "rates": {"status": rates_confirmation["status"], "as_of": rates_as_of},
            "options": {"status": options_confirmation["status"], "as_of": options_trade_date},
            "positioning": {"status": positioning_check["status"], "as_of": positioning_as_of},
            "oil": {"status": "available" if oil_context else "pending", "as_of": oil_as_of},
            "news": {"status": "available" if news_brief else "pending", "as_of": news_as_of},
        },
        "baseline_claims": baseline_claims,
        "new_evidence": new_evidence,
        "confirmation_matrix": {
            "price": price_confirmation,
            "rates": rates_confirmation,
            "options": options_confirmation,
            "macro": macro_confirmation,
            "geopolitical": geopolitical_confirmation,
        },
        "positioning_check": positioning_check,
        "dominant_transmission_chain": chain,
        "scenario_updates": scenario_updates,
        "watch_items": watch_items,
        "revision_risk": {
            "level": "needs_review" if quality_flags else "monitor",
            "reason": warnings[0] if warnings else "价格仍需收盘级确认，最大痛点和期权墙不视为必达目标。",
            "quality_flags": quality_flags,
        },
        "source_refs": source_refs,
        "quality_flags": quality_flags,
        "warnings": warnings,
    }


def generate_weekly_context_revision(
    *,
    article_id: str,
    baseline_date: str,
    trade_date: str,
    run_id: str,
    asset: str = "XAUUSD",
    storage_root: Path = Path("./storage"),
) -> dict[str, Any]:
    snapshot = build_weekly_context_revision_input_snapshot(
        article_id=article_id,
        baseline_date=baseline_date,
        trade_date=trade_date,
        asset=asset,
        storage_root=storage_root,
    )
    if snapshot.get("status") == "blocked":
        return snapshot
    structured = build_weekly_context_revision_payload(snapshot, run_id=run_id)
    try:
        llm_result = invoke_weekly_context_revision_llm(structured)
        structured = apply_weekly_context_revision_llm(structured, llm_result)
    except Exception as exc:
        structured = mark_weekly_context_revision_llm_failure(structured, exc)
    result = write_weekly_context_revision(
        storage_root=storage_root,
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
        source_markdown=render_weekly_context_revision_source_markdown(snapshot),
        analysis_markdown=render_weekly_context_revision_analysis_markdown(structured.model_dump(mode="json")),
        structured_payload=structured.model_dump(mode="json"),
    )
    return {**snapshot, **result, "structured_payload": structured.model_dump(mode="json")}


def _blocked_snapshot(
    *,
    article_id: str,
    baseline_date: str,
    trade_date: str,
    asset: str,
    reason: str,
    baseline: Mapping[str, Any] | None = None,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    refs = []
    if baseline_path is not None:
        refs.append({"artifact_type": "jin10_weekly_analysis", "path": str(baseline_path)})
    return {
        "status": "blocked",
        "asset": asset,
        "trade_date": trade_date,
        "context_as_of": trade_date,
        "anchor": {
            "article_id": article_id,
            "report_date": baseline_date,
            "run_id": str((baseline or {}).get("run_id") or article_id),
            "title": str((baseline or {}).get("title") or "Jin10 weekly report"),
            "baseline_quality_status": _baseline_quality(baseline or {}),
            "baseline_artifact_refs": refs,
        },
        "input_snapshot_ids": {},
        "freshness": {},
        "baseline_claims": [],
        "new_evidence": [],
        "confirmation_matrix": {},
        "positioning_check": {"status": "pending"},
        "dominant_transmission_chain": {"status": "pending"},
        "scenario_updates": [],
        "watch_items": [],
        "revision_risk": {"level": "blocked", "reason": reason, "quality_flags": [reason]},
        "source_refs": _source_refs(baseline or {}),
        "quality_flags": [reason],
        "warnings": [reason],
        "blocking_reason": reason,
    }


def _latest_premarket_snapshot(
    *,
    storage_root: Path,
    asset: str,
    start_date: str,
    end_date: str,
) -> tuple[str, str, Path, dict[str, Any]] | None:
    base = storage_root / "features" / "snapshots" / asset
    candidates: list[tuple[str, str, Path]] = []
    if not base.exists():
        return None
    for date_dir in base.iterdir():
        if not date_dir.is_dir() or not (start_date <= date_dir.name <= end_date):
            continue
        for run_dir in date_dir.iterdir():
            path = run_dir / "premarket_snapshot.json"
            if run_dir.is_dir() and path.is_file():
                candidates.append((date_dir.name, run_dir.name, path))
    for context_date, run_id, path in sorted(candidates, reverse=True):
        payload = _read_json(path)
        if payload is not None:
            return context_date, run_id, path, payload
    return None


def _baseline_quality(baseline: Mapping[str, Any]) -> str:
    for value in (
        _dict(baseline.get("quality_audit")).get("status"),
        _dict(baseline.get("output_quality_audit")).get("status"),
        baseline.get("quality_status"),
    ):
        if value:
            return str(value)
    return "needs_review"


def _baseline_claims(baseline: Mapping[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for claim_id, category, source_path, value in (
        ("overall_thesis", "overall_thesis", "one_line_conclusion", baseline.get("one_line_conclusion")),
        ("market_stage", "market_stage", "market_stage.label", _dict(baseline.get("market_stage")).get("label")),
        ("gold_analysis", "gold_analysis", "gold_analysis", baseline.get("gold_analysis")),
    ):
        if str(value or "").strip():
            claims.append(
                {
                    "claim_id": claim_id,
                    "category": category,
                    "claim": str(value).strip(),
                    "source_path": source_path,
                }
            )
    for index, scenario in enumerate(baseline.get("scenario_paths") or []):
        if not isinstance(scenario, Mapping):
            continue
        summary = str(scenario.get("summary") or "").strip()
        if summary:
            claims.append(
                {
                    "claim_id": f"scenario_{index + 1}",
                    "category": "scenario",
                    "claim": summary,
                    "source_path": f"scenario_paths[{index}].summary",
                }
            )
    if not claims:
        claims.append(
            {
                "claim_id": "baseline_unresolved",
                "category": "unknown",
                "claim": "周报未稳定提取出可修正主张。",
                "source_path": "unresolved",
            }
        )
    return claims


def _options_confirmation(options: Mapping[str, Any]) -> dict[str, Any]:
    walls = [dict(item) for item in options.get("wall_scores") or [] if isinstance(item, Mapping)]
    ranked = sorted(walls, key=lambda item: (_number(item.get("rank")) or 10_000, -(_number(item.get("oi")) or 0)))
    primary_wall = _number(ranked[0].get("strike")) if ranked else None
    gamma_zero = _number(
        _dict(_dict(options.get("gex")).get("netgex_aggregate")).get("gamma_zero", {}).get("price")
        if isinstance(_dict(_dict(options.get("gex")).get("netgex_aggregate")).get("gamma_zero"), Mapping)
        else None
    )
    data_source = _dict(options.get("data_source"))
    return {
        "status": "confirmed" if options and primary_wall is not None else "pending",
        "report_status": str(data_source.get("status") or "unknown"),
        "trade_date": str(options.get("trade_date") or ""),
        "report_p0": _number(_dict(options.get("parameters")).get("report_p0")),
        "primary_wall": primary_wall,
        "gamma_zero": gamma_zero,
        "support": [dict(item) for item in _dict(options.get("support_resistance")).get("support") or [] if isinstance(item, Mapping)][:5],
        "resistance": [dict(item) for item in _dict(options.get("support_resistance")).get("resistance") or [] if isinstance(item, Mapping)][:5],
        "note": "期权墙与 Gamma Zero 是结构证据，不是必达价格目标。",
    }


def _watch_items(
    *,
    price: float | None,
    options_confirmation: Mapping[str, Any],
    rates_confirmation: Mapping[str, Any],
    oil_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    wall = _number(options_confirmation.get("primary_wall"))
    gamma_zero = _number(options_confirmation.get("gamma_zero"))
    if wall is not None:
        items.append({"label": f"{wall:g} 期权墙能否形成有效承接", "status": "active", "current_value": price})
    if gamma_zero is not None:
        items.append({"label": f"价格能否收复 Gamma Zero {gamma_zero:g}", "status": "pending", "current_value": price})
    if _number(rates_confirmation.get("us10y")) is not None:
        items.append({"label": "10年期收益率能否持续回落", "status": "active", "current_value": rates_confirmation.get("us10y")})
    if oil_context:
        items.append({"label": "Brent/WTI 是否继续强化能源通胀链", "status": "active", "current_value": oil_context.get("brent_price")})
    return items


def _available_payload(value: Any) -> dict[str, Any]:
    item = _dict(value)
    if str(item.get("status") or "") not in {"available", "ready"}:
        return {}
    return _dict(item.get("data"))


def _indicator_value(indicators: Mapping[str, Any], key: str) -> float | None:
    return _number(_dict(indicators.get(key)).get("value"))


def _latest_indicator_date(indicators: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    values = [str(_dict(indicators.get(key)).get("date") or "") for key in keys]
    return max((value for value in values if value), default="")


def _source_refs(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs = value.get("source_refs")
    if isinstance(refs, list):
        return [dict(item) for item in refs if isinstance(item, Mapping)]
    if isinstance(refs, Mapping):
        return [dict(item) for item in refs.values() if isinstance(item, Mapping)]
    return []


def _selected_macro_source_refs(macro: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs = macro.get("source_refs")
    if not isinstance(refs, Mapping):
        return _source_refs(macro)[:8]
    selected: list[dict[str, Any]] = []
    for key, ref in refs.items():
        normalized = str(key).upper()
        if not any(symbol in normalized for symbol in ("US10Y", "DGS10", "REAL_10Y", "DFII10", "BREAKEVEN_10Y", "T10YIE", "DXY")):
            continue
        if isinstance(ref, Mapping):
            selected.append(dict(ref))
    return selected[:12]


def _selected_news_source_refs(news_brief: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    primary_event_id = str(_dict(news_brief.get("market_mainline")).get("primary_event_id") or "")
    for collection in (news_brief.get("confirmed_events"), news_brief.get("candidate_events")):
        for event in collection or []:
            if not isinstance(event, Mapping):
                continue
            if primary_event_id and str(event.get("event_id") or "") != primary_event_id:
                continue
            selected.extend(_source_refs(event))
            if selected:
                return selected[:10]
    return _source_refs(news_brief)[:10]


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in refs:
        key = (
            str(ref.get("source") or ""),
            str(ref.get("source_ref") or ""),
            str(ref.get("path") or ref.get("raw_path") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(_compact_ref(ref))
    return output


def _compact_ref(ref: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "source",
        "source_ref",
        "source_type",
        "title",
        "published_at",
        "raw_path",
        "parsed_path",
        "path",
        "source_url",
        "url",
        "article_id",
        "sha256",
    )
    return {key: ref.get(key) for key in allowed if ref.get(key) is not None}


def _relative(storage_root: Path, path: Path) -> str:
    return path.relative_to(storage_root).as_posix()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
