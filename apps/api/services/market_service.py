from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.agent_read_model import build_market_regime_agent_summary
from apps.api.services.macro_service import get_macro_latest
from apps.api.services.options_service import get_options_snapshot
from database.models.analysis import ensure_analysis_tables
from database.models.engine import DATABASE_URL
from database.queries.market import list_market_candles, list_market_candles_by_assets


logger = logging.getLogger(__name__)


def get_jin10_daily_report_latest() -> dict[str, Any] | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "jin10"
    if not base.exists():
        return None
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            result = _load_jin10_daily_report(date_dir.name, run_dir.name)
            if result is None:
                continue
            if _is_weekly_storage_report(result):
                continue
            result["report_type"] = "daily"
            return result
    return None


def get_jin10_daily_report(date: str, run_id: str) -> dict[str, Any] | None:
    result = _load_jin10_daily_report(date, run_id)
    if result is not None:
        if _is_weekly_storage_report(result):
            return None
        result["report_type"] = "daily"
    return result


def get_jin10_weekly_report_latest() -> dict[str, Any] | None:
    """查找最新周报：合并 storage/outputs/jin10 与 ~/jin10-reports 后按日期取最新。"""
    candidates: list[tuple[str, str, dict[str, Any]]] = []

    base = _PROJECT_ROOT / "storage" / "outputs" / "jin10"
    if base.exists():
        for date_dir in (d for d in base.iterdir() if d.is_dir()):
            for run_dir in (d for d in date_dir.iterdir() if d.is_dir()):
                result = _load_jin10_daily_report(date_dir.name, run_dir.name)
                if result is None:
                    continue
                if _is_weekly_storage_report(result):
                    report_meta = _load_jin10_report_meta(date_dir.name, run_dir.name)
                    weekly = _merge_report_meta(result, report_meta) if report_meta else result
                    candidates.append((str(weekly.get("date") or date_dir.name), str(weekly.get("article_id") or weekly.get("run_id") or run_dir.name), weekly))

    external = Path("~/jin10-reports").expanduser()
    if external.exists():
        for date_dir in (d for d in external.iterdir() if d.is_dir()):
            for sub_dir in (d for d in date_dir.iterdir() if d.is_dir()):
                for article_dir in (d for d in sub_dir.iterdir() if d.is_dir()):
                    meta = _load_jin10_report_meta(date_dir.name, article_dir.name)
                    if meta and _is_explicit_jin10_weekly(meta):
                        content = _read_jin10_report_content(date_dir.name, article_dir.name)
                        weekly = {
                            "article_id": meta.get("id"),
                            "date": meta.get("date"),
                            "title": meta.get("title"),
                            "report_type": "weekly",
                            "category": meta.get("category"),
                            "source_url": meta.get("source_url"),
                            "image_count": len(meta.get("images", [])),
                            "content": content,
                            "format": "markdown",
                        }
                        candidates.append((str(weekly.get("date") or date_dir.name), str(weekly.get("article_id") or article_dir.name), weekly))

    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0][2]


def _merge_report_meta(result: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """将 meta.json 的字段合并到 storage 结果中，并用 report.md 覆盖 content。"""
    result["report_type"] = "weekly"
    for key in ("date", "title", "category", "source_url"):
        if meta.get(key) and not result.get(key):
            result[key] = meta.get(key)
    result["image_count"] = len(meta.get("images", []))
    # 替换 content 为原始 markdown 报告
    report_date = meta.get("date") or result.get("date") or ""
    article_id = meta.get("id") or result.get("article_id") or ""
    raw_md = _read_jin10_report_content(report_date, article_id)
    if raw_md:
        result["content"] = raw_md
        result["format"] = "markdown"
    return result


def _read_jin10_report_content(date: str, article_id: str) -> str:
    """读取报告 markdown 内容。"""
    candidates = [
        Path(f"~/jin10-reports/{date}/daily/{article_id}/report.md").expanduser(),
        Path(f"~/jin10-reports/{date}/weekly/{article_id}/report.md").expanduser(),
        Path(f"~/jin10-reports/{date}/金银报告/{article_id}/report.md").expanduser(),
        Path(f"~/jin10-reports/{date}/报告/{article_id}/report.md").expanduser(),
        Path(f"~/jin10-reports/{date}/黄金周报/{article_id}/report.md").expanduser(),
    ]
    for path in candidates:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                return ""
    return ""


def get_jin10_weekly_report(date: str, run_id: str) -> dict[str, Any] | None:
    """按日期和 run_id 查找周报"""
    result = _load_jin10_daily_report(date, run_id)
    if result is not None:
        if _is_weekly_storage_report(result):
            report_meta = _load_jin10_report_meta(date, run_id)
            return _merge_report_meta(result, report_meta) if report_meta else result
        return None
    # 查 ~/jin10-reports
    meta = _load_jin10_report_meta(date, run_id)
    if meta and _is_explicit_jin10_weekly(meta):
        content = _read_jin10_report_content(date, run_id)
        return {
            "article_id": meta.get("id"),
            "date": meta.get("date"),
            "title": meta.get("title"),
            "report_type": "weekly",
            "category": meta.get("category"),
            "source_url": meta.get("source_url"),
            "image_count": len(meta.get("images", [])),
            "content": content,
            "format": "markdown",
        }
    return None


def _load_jin10_report_meta(date: str, article_id: str) -> dict[str, Any] | None:
    """从 ~/jin10-reports 或 storage 中加载报告 meta.json，自动推断 report_type。"""
    candidates = [
        Path(f"~/jin10-reports/{date}/daily/{article_id}/meta.json").expanduser(),
        Path(f"~/jin10-reports/{date}/weekly/{article_id}/meta.json").expanduser(),
        Path(f"~/jin10-reports/{date}/金银报告/{article_id}/meta.json").expanduser(),
        Path(f"~/jin10-reports/{date}/报告/{article_id}/meta.json").expanduser(),
        Path(f"~/jin10-reports/{date}/黄金周报/{article_id}/meta.json").expanduser(),
    ]
    for path in candidates:
        if path.exists():
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
            # 推断 report_type（兼容旧 meta.json 无此字段）
            if "report_type" not in meta:
                parent = path.parent.parent.name  # daily/weekly/金银报告/报告
                meta["report_type"] = "weekly" if parent in ("weekly", "黄金周报") and _is_explicit_jin10_weekly(meta) else "daily"
            return meta
    return None


def _load_jin10_daily_report(date: str, run_id: str) -> dict[str, Any] | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "jin10" / date / run_id
    json_path = base / "daily_analysis.json"
    html_path = base / "daily_analysis.html"
    if not json_path.exists() or not html_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    payload["content"] = html_path.read_text(encoding="utf-8")
    payload["format"] = "html"
    payload["path"] = str(html_path.relative_to(_PROJECT_ROOT))
    return payload


def _is_weekly_storage_report(payload: dict[str, Any]) -> bool:
    """Storage outputs are authoritative; legacy rows without report_type are daily."""
    return payload.get("report_type") == "weekly"


def _is_explicit_jin10_weekly(meta: dict[str, Any]) -> bool:
    category = str(meta.get("category") or "").strip()
    category_code = str(meta.get("category_code") or "").strip()
    title = str(meta.get("title") or "").strip()
    return category_code == "536" or "黄金周报" in category or "黄金周报" in title



def get_market_odds_snapshot(date_str: str | None = None, run_id: str | None = None) -> dict[str, Any] | None:
    base = _PROJECT_ROOT / "storage" / "features" / "snapshots" / "XAUUSD"
    if not base.exists():
        return None
    if date_str is None:
        dates = sorted((d.name for d in base.iterdir() if d.is_dir()), reverse=True)
        if not dates:
            return None
        date_str = dates[0]
    date_dir = base / date_str
    if not date_dir.exists():
        return None
    if run_id:
        run_dir = date_dir / run_id
        snap = _load_snapshot(run_dir) if run_dir.exists() else None
        return snap.get("market_odds") if snap else None
    for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
        snap = _load_snapshot(run_dir)
        if snap and snap.get("market_odds"):
            return snap.get("market_odds")
    return None


def _load_snapshot(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "premarket_snapshot.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_market_odds_report(date_str: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    mo = get_market_odds_snapshot(date_str=date_str, run_id=run_id)
    if mo is None:
        return {"status": "unavailable", "aggregate_signal": "unavailable", "aggregate_confidence": 0.0, "source_status": {}, "available_events": [], "unavailable_events": [], "source_refs": []}
    events = mo.get("events", []) if isinstance(mo, dict) else []
    available_events = [e for e in events if isinstance(e, dict) and e.get("status") == "available"]
    unavailable_events = [e for e in events if isinstance(e, dict) and e.get("status") == "unavailable"]
    source_status: dict[str, str] = {}
    for event in available_events:
        probs = event.get("probabilities", {})
        if isinstance(probs, dict):
            for source, data in probs.items():
                if isinstance(data, dict):
                    if data.get("probability") is not None:
                        source_status[source] = "available"
                    elif source_status.get(source) != "available":
                        source_status[source] = "unavailable"
    return {
        "status": mo.get("status", "unavailable") if isinstance(mo, dict) else "unavailable",
        "aggregate_signal": (mo.get("aggregate_signal") or "unavailable") if isinstance(mo, dict) else "unavailable",
        "aggregate_confidence": mo.get("aggregate_confidence") if isinstance(mo, dict) else 0.0,
        "source_status": source_status,
        "available_events": [{
            "event_id": e.get("event_id"), "event_name": e.get("event_name"), "event_type": e.get("event_type"), "target_value": e.get("target_value"),
            "signal_label": e.get("signal_label"), "final_probability": e.get("final_probability"), "confidence": e.get("confidence"),
            "reliability_score": e.get("reliability_score"), "divergence_score": e.get("divergence_score"), "interpretation": e.get("interpretation"),
        } for e in available_events],
        "unavailable_events": [{"event_id": e.get("event_id"), "event_name": e.get("event_name"), "reason": e.get("interpretation") or "Source data not yet available."} for e in unavailable_events],
        "source_refs": mo.get("source_refs", []) if isinstance(mo, dict) else [],
    }


_JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
_JIN10_MCP_KEY_ENV = "JIN10_MCP_KEY"


def _get_jin10_mcp_key() -> str:
    return os.environ.get(_JIN10_MCP_KEY_ENV) or str(dotenv_values(_PROJECT_ROOT / ".env").get(_JIN10_MCP_KEY_ENV) or "")


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def get_market_tickers() -> dict[str, Any]:
    tickers: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    mcp_key = _get_jin10_mcp_key()
    jin10_success = False

    if mcp_key:
        try:
            import httpx

            with httpx.Client(timeout=15.0, headers={"User-Agent": "finance-agent/0.1"}, trust_env=False) as client:
                init_r = client.post(
                    _JIN10_MCP_URL,
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "finance-agent", "version": "0.1"}}},
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {mcp_key}"},
                )
                init_r.raise_for_status()
                sid = init_r.headers.get("Mcp-Session-Id", "")
                if not sid:
                    logger.warning("Jin10 MCP initialize succeeded without session id; falling back to degraded market tickers", extra={"service": "jin10_mcp", "stage": "initialize", "degraded": True})
                else:
                    client.post(
                        _JIN10_MCP_URL,
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {mcp_key}", "Mcp-Session-Id": sid},
                    ).raise_for_status()
                    for symbol in ["XAUUSD", "XAGUSD"]:
                        try:
                            resp = client.post(
                                _JIN10_MCP_URL,
                                json={"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "get_quote", "arguments": {"code": symbol}}},
                                headers={"Content-Type": "application/json", "Authorization": f"Bearer {mcp_key}", "Mcp-Session-Id": sid},
                            )
                            resp.raise_for_status()
                            for line in resp.text.split("\n"):
                                if not line.startswith("data:"):
                                    continue
                                result = json.loads(line[5:]).get("result", {})
                                sc = result.get("structuredContent", {})
                                if isinstance(sc, dict) and sc.get("status") == 200:
                                    qdata = sc.get("data", {})
                                    tickers[symbol.lower()] = {
                                        "price": _coerce_float(qdata.get("price") or qdata.get("last") or qdata.get("close")),
                                        "open": _coerce_float(qdata.get("open")),
                                        "high": _coerce_float(qdata.get("high")),
                                        "low": _coerce_float(qdata.get("low")),
                                        "change": _coerce_float(qdata.get("ups_price") or qdata.get("change")),
                                        "change_pct": _coerce_float(qdata.get("ups_percent") or qdata.get("change_pct") or qdata.get("changePercent")),
                                        "bid": _coerce_float(qdata.get("bid") or qdata.get("bidPrice")),
                                        "ask": _coerce_float(qdata.get("ask") or qdata.get("askPrice")),
                                        "time": qdata.get("time"),
                                        "name": qdata.get("name"),
                                        "source": "jin10_mcp_realtime",
                                    }
                                    jin10_success = True
                                break
                        except Exception as exc:
                            logger.warning(
                                "Jin10 MCP quote fetch failed; continuing with degraded market tickers",
                                exc_info=exc,
                                extra={"service": "jin10_mcp", "stage": "quote", "symbol": symbol, "degraded": True},
                            )
        except Exception as exc:
            logger.warning(
                "Jin10 MCP request failed; continuing with degraded market tickers",
                exc_info=exc,
                extra={"service": "jin10_mcp", "stage": "initialize", "degraded": True},
            )
    else:
        logger.debug("Jin10 MCP key not configured; using degraded market tickers", extra={"service": "jin10_mcp", "stage": "config", "degraded": True})

    sources.append("jin10_mcp" if jin10_success else "jin10_mcp_error")

    if "xauusd" not in tickers:
        try:
            snap = get_options_snapshot()
            if snap:
                fwd = (snap.get("parameters") or {}).get("f_value")
                gz_price = (((snap.get("gex") or {}).get("netgex_aggregate") or {}).get("gamma_zero") or {}).get("price")
                price = fwd or gz_price
                if price:
                    tickers["xauusd"] = {"price": float(price), "change_pct": None, "bid": None, "ask": None, "source": "cme_gc_futures"}
        except Exception as exc:
            logger.debug("Options snapshot fallback failed for market tickers", exc_info=exc, extra={"service": "market_tickers", "stage": "options_fallback"})

    try:
        macro = get_macro_latest()
        if macro:
            indicators = macro.get("indicators", {})
            macro_map = {"dxy": ["DXY", "dxy"], "real_10y": ["REAL_10Y", "real_10y", "REAL10Y"], "t10yie": ["T10YIE", "t10yie"], "on_rrp": ["ON_RRP", "on_rrp"], "tga": ["TGA", "tga"]}
            for ticker_key, sym_keys in macro_map.items():
                for sym_key in sym_keys:
                    if sym_key in indicators:
                        val = indicators[sym_key]
                        tickers[ticker_key] = {"value": val.get("value") if isinstance(val, dict) else val, "unit": val.get("unit", "") if isinstance(val, dict) else "", "source": "macro_latest"}
                        break
        sources.append("macro_latest")
    except Exception as exc:
        logger.debug("Macro snapshot fallback failed for market tickers", exc_info=exc, extra={"service": "market_tickers", "stage": "macro"})
        sources.append("macro_latest")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "tickers": tickers,
        "market_regime": _compute_market_regime(tickers),
        "primary_driver": _compute_primary_driver(tickers),
    }


def get_market_monitor_overview() -> dict[str, Any]:
    tickers_payload = get_market_tickers()
    macro_payload = get_macro_latest() or {}
    indicators = macro_payload.get("indicators", {}) if isinstance(macro_payload, dict) else {}
    generated_at = tickers_payload.get("generated_at") or datetime.now(timezone.utc).isoformat()
    latest_date = macro_payload.get("as_of") if isinstance(macro_payload, dict) else None

    def metric_item(
        key: str,
        label: str,
        value: Any,
        unit: str,
        one_week_change: Any = None,
        one_month_change: Any = None,
        status: str = "unavailable",
        interpretation: str = "",
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "latest_date": latest_date or generated_at.split("T")[0],
            "latest_value": value,
            "unit": unit,
            "one_week_change": one_week_change,
            "one_month_change": one_month_change,
            "status": status,
            "interpretation": interpretation,
        }

    xau = (tickers_payload.get("tickers") or {}).get("xauusd", {})
    dxy = indicators.get("DXY", {}) or (tickers_payload.get("tickers") or {}).get("dxy", {})
    us10y = indicators.get("US10Y", {}) or indicators.get("DGS10", {})
    us02y = indicators.get("US02Y", {}) or indicators.get("DGS2", {})
    real10 = indicators.get("REAL_10Y", {})
    t10yie = indicators.get("T10YIE", {}) or indicators.get("BREAKEVEN_10Y", {})
    tga = indicators.get("TGA", {})
    rrp = indicators.get("ON_RRP_USAGE", {}) or indicators.get("RRP", {})
    sofr = indicators.get("SOFR", {})
    effr = indicators.get("EFFR", {})
    iorb = indicators.get("IORB", {})

    if xau.get("price") is None:
        latest_xau_candle = _latest_market_candle(asset="XAUUSD", timeframe="1d")
        if latest_xau_candle is not None:
            xau = {
                **xau,
                "price": latest_xau_candle["close"],
                "source": "market_candles_latest",
            }

    metrics = [
        metric_item("XAUUSD", "XAUUSD", xau.get("price"), "USD/oz", xau.get("change_pct"), None, "ok" if xau.get("price") is not None else "unavailable", xau.get("source", "")),
        metric_item("DXY", "DXY", dxy.get("value"), dxy.get("unit", "index"), dxy.get("weekly_change"), dxy.get("monthly_change"), "ok" if dxy.get("value") is not None else "unavailable", dxy.get("direction_note", "")),
        metric_item("US10Y", "US10Y", us10y.get("value"), us10y.get("unit", "%"), us10y.get("weekly_change"), us10y.get("monthly_change"), "ok" if us10y.get("value") is not None else "unavailable", us10y.get("direction_note", "")),
        metric_item("US02Y", "US02Y", us02y.get("value"), us02y.get("unit", "%"), us02y.get("weekly_change"), us02y.get("monthly_change"), "ok" if us02y.get("value") is not None else "unavailable", us02y.get("direction_note", "")),
        metric_item("REAL_10Y", "10Y Real Rate", real10.get("value"), real10.get("unit", "%"), real10.get("weekly_change"), real10.get("monthly_change"), "ok" if real10.get("value") is not None else "unavailable", real10.get("direction_note", "")),
        metric_item("T10YIE", "T10YIE", t10yie.get("value"), t10yie.get("unit", "%"), t10yie.get("weekly_change"), t10yie.get("monthly_change"), "ok" if t10yie.get("value") is not None else "unavailable", t10yie.get("direction_note", "")),
        metric_item("TGA", "TGA", tga.get("value"), tga.get("unit", "B"), tga.get("weekly_change"), tga.get("monthly_change"), "ok" if tga.get("value") is not None else "unavailable", tga.get("direction_note", "")),
        metric_item("RRP", "RRP", rrp.get("value"), rrp.get("unit", "B"), rrp.get("weekly_change"), rrp.get("monthly_change"), "ok" if rrp.get("value") is not None else "unavailable", rrp.get("direction_note", "")),
        metric_item("SOFR", "SOFR", sofr.get("value"), sofr.get("unit", "%"), sofr.get("weekly_change"), sofr.get("monthly_change"), "ok" if sofr.get("value") is not None else "unavailable", sofr.get("direction_note", "")),
        metric_item("EFFR", "EFFR", effr.get("value"), effr.get("unit", "%"), effr.get("weekly_change"), effr.get("monthly_change"), "ok" if effr.get("value") is not None else "unavailable", effr.get("direction_note", "")),
        metric_item("IORB", "IORB", iorb.get("value"), iorb.get("unit", "%"), iorb.get("weekly_change"), iorb.get("monthly_change"), "ok" if iorb.get("value") is not None else "unavailable", iorb.get("direction_note", "")),
    ]

    regime = tickers_payload.get("market_regime") or {}
    primary_driver = tickers_payload.get("primary_driver") or {}
    regime_key = regime.get("regime") if isinstance(regime, dict) else None

    def _regime_bucket(
        label: str,
        status: str = "unavailable",
        confidence: float = 0.0,
        description: str = "",
        interpretation: str = "",
        drivers: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "label": label,
            "status": status,
            "confidence": confidence,
            "description": description,
            "interpretation": interpretation,
            "drivers": drivers or [],
        }

    market_regimes = {
        "rate_pressure": _regime_bucket("Rate Pressure"),
        "transition_release": _regime_bucket("Transition Release"),
        "trend_tailwind": _regime_bucket("Trend Tailwind"),
    }

    if regime_key:
        mapped_key = (
            "rate_pressure"
            if regime_key == "hawkish_gold_pressure"
            else "trend_tailwind"
            if regime_key == "dovish_gold_friendly"
            else "transition_release"
        )
        confidence = float(regime.get("confidence") or 0.0) if isinstance(regime, dict) else 0.0
        drivers: list[str] = []
        if isinstance(primary_driver, dict):
            for key in ("driver", "secondary"):
                value = primary_driver.get(key)
                if isinstance(value, str) and value:
                    drivers.append(value)
        market_regimes[mapped_key] = _regime_bucket(
            market_regimes[mapped_key]["label"],
            status="ok" if confidence > 0 else "info",
            confidence=confidence,
            description=str(regime_key),
            interpretation=f"实时 regime: {regime_key}",
            drivers=drivers,
        )
    return {
        "generated_at": generated_at,
        "latest_date": latest_date or generated_at.split("T")[0],
        "has_data": any(item.get("latest_value") is not None for item in metrics),
        "source": "api",
        "metrics": metrics,
        "market_regime": regime,
        "agent_market_regime": build_market_regime_agent_summary(),
        "market_regimes": market_regimes,
        "primary_driver": primary_driver,
        "environment_filters": {
            "us10y": metrics[2],
            "dxy": metrics[1],
            "us02y": metrics[3],
            "xauusd_price_reaction": {
                "label": "XAUUSD Price Reaction",
                "status": metrics[0]["status"],
                "latest_value": metrics[0]["latest_value"],
                "one_week_change": metrics[0]["one_week_change"],
                "one_month_change": metrics[0]["one_month_change"],
                "interpretation": f"driver={primary_driver.get('driver', 'data_insufficient')}",
                "unit": metrics[0]["unit"],
            },
        },
        "source_trace": [
            {
                "name": "Market Tickers API",
                "trade_date": latest_date or generated_at.split("T")[0],
                "file": "api://market/tickers",
                "snapshot_id": None,
                "source_ref": "GET /api/market/tickers",
                "status": "ok",
            },
            {
                "name": "Macro Latest API",
                "trade_date": latest_date or generated_at.split("T")[0],
                "file": "api://macro/latest",
                "snapshot_id": None,
                "source_ref": "GET /api/macro/latest",
                "status": "ok" if indicators else "unavailable",
            },
        ],
    }


def get_market_monitor_history(limit: int = 30, timeframe: str = "1M") -> dict[str, Any]:
    normalized_timeframe = str(timeframe or "1M").upper()
    if normalized_timeframe in {"15M", "30M", "1H", "4H", "1D"}:
        return _get_market_monitor_intraday_history(limit=limit, timeframe=normalized_timeframe)
    return _get_market_monitor_daily_history(limit=limit, timeframe=normalized_timeframe)


def _get_market_monitor_intraday_history(limit: int = 30, timeframe: str = "1D") -> dict[str, Any]:
    session_factory = _market_session_factory()
    points: list[dict[str, Any]] = []
    timeframe_to_limit = {
        "15M": 32,
        "30M": 32,
        "1H": 32,
        "4H": 40,
        "1D": 30,
    }
    source_limit = timeframe_to_limit.get(timeframe, 30)
    source_timeframe = "1h"
    degraded_reason = ""
    with session_factory() as session:
        ensure_analysis_tables(session)
        if timeframe in {"15M", "30M", "1D"}:
            bucket_minutes = 15 if timeframe == "15M" else 30 if timeframe == "30M" else 60
            minute_limit = max(limit * bucket_minutes + bucket_minutes, source_limit * bucket_minutes)
            minute_rows = list_market_candles(session, asset="XAUUSD", timeframe="1m", limit=minute_limit)
            if minute_rows:
                xau_rows = _aggregate_intraday_rows(minute_rows, bucket_minutes=bucket_minutes)[-limit:]
                source_timeframe = "1m"
            else:
                xau_rows = list_market_candles(session, asset="XAUUSD", timeframe="1h", limit=max(limit, source_limit))
                xau_rows = _sample_intraday_rows(xau_rows, timeframe=timeframe)
                degraded_reason = f"{timeframe} requested but XAUUSD 1m candles are unavailable; fell back to 1h rows."
        else:
            xau_rows = list_market_candles(session, asset="XAUUSD", timeframe="1h", limit=max(limit, source_limit))
            xau_rows = _sample_intraday_rows(xau_rows, timeframe=timeframe)

    for row in xau_rows:
        key = _row_value(row, "open_time").isoformat()
        points.append(
            {
                "date": key,
                "XAUUSD": _row_value(row, "close"),
                "xauusd_ohlc": {
                    "open": _row_value(row, "open"),
                    "high": _row_value(row, "high"),
                    "low": _row_value(row, "low"),
                    "close": _row_value(row, "close"),
                },
                "DXY": None,
            }
        )

    degraded = len(points) < min(limit, 24 if timeframe == "1D" else 8) or bool(degraded_reason)
    message = degraded_reason or "小时间级别当前仅对 XAUUSD 提供真实价格曲线；DXY 保持日线，不伪造更细粒度走势。"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "source_timeframe": source_timeframe,
        "series": points,
        "available_points": len(points),
        "available_fields": ["XAUUSD", "DXY"],
        "degraded": degraded,
        "message": message,
    }


def _row_value(row: Any, field: str) -> Any:
    if isinstance(row, dict):
        value = row[field]
    else:
        value = getattr(row, field)
    if field == "open_time" and isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _aggregate_intraday_rows(rows: list[Any], *, bucket_minutes: int) -> list[dict[str, Any]]:
    buckets: dict[datetime, list[Any]] = {}
    for row in rows:
        open_time = _row_value(row, "open_time")
        bucket_time = _bucket_open_time(open_time, bucket_minutes=bucket_minutes)
        buckets.setdefault(bucket_time, []).append(row)

    aggregated: list[dict[str, Any]] = []
    for bucket_time in sorted(buckets):
        bucket_rows = sorted(buckets[bucket_time], key=lambda item: _row_value(item, "open_time"))
        first = bucket_rows[0]
        last = bucket_rows[-1]
        volumes = [_row_value(item, "volume") for item in bucket_rows if _row_value(item, "volume") is not None]
        aggregated.append(
            {
                "open_time": bucket_time,
                "open": float(_row_value(first, "open")),
                "high": max(float(_row_value(item, "high")) for item in bucket_rows),
                "low": min(float(_row_value(item, "low")) for item in bucket_rows),
                "close": float(_row_value(last, "close")),
                "volume": sum(float(volume) for volume in volumes) if volumes else None,
            }
        )
    return aggregated


def _bucket_open_time(open_time: datetime, *, bucket_minutes: int) -> datetime:
    minute = (open_time.minute // bucket_minutes) * bucket_minutes
    return open_time.replace(minute=minute, second=0, microsecond=0)


def _sample_intraday_rows(rows: list[Any], *, timeframe: str) -> list[Any]:
    if timeframe in {"1D", "1H"}:
        return rows[-30:]
    if timeframe == "4H":
        return rows[-40::4]
    if timeframe == "30M":
        return rows[-30:]
    if timeframe == "15M":
        return rows[-30:]
    return rows[-30:]


def _get_market_monitor_daily_history(limit: int = 30, timeframe: str = "1M") -> dict[str, Any]:
    macro_base = _PROJECT_ROOT / "storage" / "features" / "macro"
    macro_points_by_date: dict[str, dict[str, Any]] = {}
    if macro_base.exists():
        for date_dir in sorted((d for d in macro_base.iterdir() if d.is_dir()), reverse=True)[:limit]:
            path = date_dir / "macro_snapshot.json"
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            indicators = payload.get("indicators", {}) if isinstance(payload, dict) else {}
            macro_points_by_date[date_dir.name] = {
                "date": date_dir.name,
                "DXY": (indicators.get("DXY") or {}).get("value"),
                "US10Y": (indicators.get("US10Y") or indicators.get("DGS10") or {}).get("value"),
                "REAL_10Y": (indicators.get("REAL_10Y") or {}).get("value"),
                "T10YIE": (indicators.get("T10YIE") or indicators.get("BREAKEVEN_10Y") or {}).get("value"),
            }

    session_factory = _market_session_factory()
    with session_factory() as session:
        ensure_analysis_tables(session)
        price_rows = list_market_candles_by_assets(session, assets=["XAUUSD", "DXY"], timeframe="1d", limit=limit + 10)

    prices_by_date: dict[str, dict[str, float]] = {}
    for row in price_rows:
        day = row.open_time.date().isoformat()
        prices_by_date.setdefault(day, {})
        prices_by_date[day][row.asset] = row.close

    all_dates = sorted(set(macro_points_by_date.keys()) | set(prices_by_date.keys()))
    if limit > 0:
        all_dates = all_dates[-limit:]
    points: list[dict[str, Any]] = []
    for day in all_dates:
        point = dict(macro_points_by_date.get(day) or {"date": day})
        day_prices = prices_by_date.get(day, {})
        if "XAUUSD" in day_prices:
            point["XAUUSD"] = day_prices["XAUUSD"]
        if "DXY" in day_prices and point.get("DXY") is None:
            point["DXY"] = day_prices["DXY"]
        points.append(point)

    daily_xau_rows = [row for row in price_rows if row.asset == "XAUUSD"]
    daily_xau_by_date = {
        row.open_time.date().isoformat(): {
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
        }
        for row in daily_xau_rows
    }
    for point in points:
        if point["date"] in daily_xau_by_date:
            point["xauusd_ohlc"] = daily_xau_by_date[point["date"]]

    gap_dates = _find_missing_daily_dates(points, keys=["XAUUSD", "DXY"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "source_timeframe": "1d",
        "series": points,
        "available_points": len(points),
        "available_fields": ["XAUUSD", "DXY", "US10Y", "REAL_10Y", "T10YIE"],
        "degraded": len(points) < 5,
        "message": "历史序列当前基于本地 macro snapshots；若点数不足，则页面应显式提示历史深度不足。",
        "data_gaps": gap_dates,
        "coverage_note": _build_coverage_note(gap_dates),
    }


def _find_missing_daily_dates(points: list[dict[str, Any]], *, keys: list[str]) -> list[str]:
    if len(points) < 2:
        return []
    gaps: list[str] = []
    sorted_dates = [datetime.fromisoformat(str(point["date"])).date() for point in points if point.get("date")]
    for current, nxt in zip(sorted_dates, sorted_dates[1:]):
        delta_days = (nxt - current).days
        if delta_days <= 1:
            continue
        candidate = current
        for _ in range(delta_days - 1):
            candidate = candidate.fromordinal(candidate.toordinal() + 1)
            candidate_iso = candidate.isoformat()
            if candidate.weekday() < 5:
                gaps.append(candidate_iso)
    return gaps


def _build_coverage_note(gap_dates: list[str]) -> str | None:
    if not gap_dates:
        return None
    preview = ", ".join(gap_dates[:3])
    suffix = " ..." if len(gap_dates) > 3 else ""
    return f"daily source gap dates: {preview}{suffix}"


def _latest_market_candle(*, asset: str, timeframe: str) -> dict[str, Any] | None:
    try:
        session_factory = _market_session_factory()
        with session_factory() as session:
            ensure_analysis_tables(session)
            rows = list_market_candles(session, asset=asset, timeframe=timeframe, limit=1)
    except Exception as exc:
        logger.debug("Market candle fallback unavailable for %s %s: %s", asset, timeframe, exc)
        return None
    if not rows:
        return None
    row = rows[-1]
    return {
        "open_time": _row_value(row, "open_time"),
        "close": _row_value(row, "close"),
        "source": _row_value(row, "source") if hasattr(row, "source") or isinstance(row, dict) and "source" in row else None,
    }


def _market_session_factory():
    engine = create_engine(DATABASE_URL, echo=False)
    return sessionmaker(bind=engine)


def _compute_market_regime(tickers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """基于实际宏观数据推断市场状态，不硬编码。"""
    real_10y = tickers.get("real_10y", {})
    dxy = tickers.get("dxy", {})

    real_yield = real_10y.get("value")
    dxy_val = dxy.get("value")
    regime = "neutral"

    # 简易规则（仅基于可用数据）
    if real_yield is not None and dxy_val is not None:
        if isinstance(real_yield, (int, float)) and isinstance(dxy_val, (int, float)):
            if real_yield < 1.5 and dxy_val < 100:
                regime = "dovish_gold_friendly"
            elif real_yield > 2.5 and dxy_val > 105:
                regime = "hawkish_gold_pressure"
            elif real_yield < 2.0:
                regime = "neutral_soft"
            else:
                regime = "neutral_firm"

    return {
        "regime": regime,
        "confidence": 0.5 if real_yield is not None else 0.0,
        "available": real_yield is not None,
    }


def _compute_primary_driver(tickers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """基于可用数据判断当前主要驱动因子。"""
    xau = tickers.get("xauusd", {})
    dxy = tickers.get("dxy", {})
    change_pct = xau.get("change_pct")
    drivers: list[str] = []

    if change_pct is not None and isinstance(change_pct, (int, float)):
        if change_pct > 0:
            drivers.append("risk_sentiment" if dxy.get("value", 100) < 100 else "inflation_hedge")
        else:
            drivers.append("dollar_strength" if dxy.get("value", 100) > 100 else "rate_pressure")

    if not drivers:
        drivers.append("data_insufficient")

    return {
        "driver": drivers[0],
        "secondary": drivers[1] if len(drivers) > 1 else None,
        "confidence": 0.3 if drivers[0] != "data_insufficient" else 0.0,
    }
