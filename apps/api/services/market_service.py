from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.agent_read_model import build_market_regime_agent_summary
from apps.api.services.macro_service import get_market_macro_latest as get_macro_latest
from apps.features.market_data import is_xauusd_compatible_row
from database.models.analysis import ensure_analysis_tables
from database.models.engine import DATABASE_URL
from database.queries.warehouse_read import (
    list_warehouse_candles as list_market_candles,
    list_warehouse_candles_by_assets as list_market_candles_by_assets,
)


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
            if not _is_daily_storage_report(result):
                continue
            result["report_type"] = "daily"
            return result
    return None


def get_jin10_daily_report(date: str, run_id: str) -> dict[str, Any] | None:
    result = _load_jin10_daily_report(date, run_id)
    if result is not None:
        if not _is_daily_storage_report(result):
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
                        weekly = {
                            "article_id": meta.get("id"),
                            "run_id": article_dir.name,
                            "date": meta.get("date"),
                            "title": meta.get("title"),
                            "report_type": "weekly",
                            "category": meta.get("category"),
                            "source_url": meta.get("source_url"),
                            "image_count": _jin10_weekly_image_count(meta, date_dir.name, article_dir.name),
                            "content": "",
                            "format": "markdown",
                        }
                        _attach_jin10_weekly_markdown(weekly, date_dir.name, article_dir.name)
                        candidates.append((str(weekly.get("date") or date_dir.name), str(weekly.get("article_id") or article_dir.name), weekly))

    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0][2]


def _merge_report_meta(result: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """将 meta.json 的字段合并到 storage 结果中，并用完整原稿覆盖 content。"""
    result["report_type"] = "weekly"
    for key in ("date", "title", "category", "source_url"):
        if meta.get(key) and not result.get(key):
            result[key] = meta.get(key)
    report_date = meta.get("date") or result.get("date") or ""
    article_id = meta.get("id") or result.get("article_id") or ""
    result["image_count"] = _jin10_weekly_image_count(meta, str(report_date), str(article_id))
    # 替换 content 为原始 markdown 报告，优先使用 storage 解析后的完整原稿和本地图。
    _attach_jin10_weekly_markdown(result, str(report_date), str(article_id))
    return result


def _jin10_weekly_storage_base(date: str, article_id: str) -> Path:
    return _PROJECT_ROOT / "storage" / "outputs" / "jin10" / date / article_id


def _read_jin10_storage_raw_markdown(date: str, article_id: str) -> str:
    path = _jin10_weekly_storage_base(date, article_id) / "raw_article_report.md"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _jin10_storage_figure_count(date: str, article_id: str) -> int:
    figures = _jin10_weekly_storage_base(date, article_id) / "figures"
    if not figures.exists():
        return 0
    return len([path for path in figures.glob("*.png") if path.is_file()])


def _jin10_weekly_image_count(meta: dict[str, Any], date: str, article_id: str) -> int:
    storage_count = _jin10_storage_figure_count(date, article_id)
    if storage_count:
        return storage_count
    images = meta.get("images")
    return len(images) if isinstance(images, list) else 0


def _attach_jin10_weekly_markdown(payload: dict[str, Any], date: str, article_id: str) -> None:
    storage_md = _read_jin10_storage_raw_markdown(date, article_id)
    if storage_md:
        payload["content"] = storage_md
        payload["format"] = "markdown"
        payload["path"] = str((_jin10_weekly_storage_base(date, article_id) / "raw_article_report.md").relative_to(_PROJECT_ROOT))
        payload["asset_base_url"] = f"/api/jin10/report-bundle/{date}/{article_id}/asset/"
        return

    raw_md = _read_jin10_report_content(date, article_id)
    if raw_md:
        payload["content"] = raw_md
        payload["format"] = "markdown"


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
        weekly = {
            "article_id": meta.get("id"),
            "run_id": run_id,
            "date": meta.get("date"),
            "title": meta.get("title"),
            "report_type": "weekly",
            "category": meta.get("category"),
            "source_url": meta.get("source_url"),
            "image_count": _jin10_weekly_image_count(meta, date, run_id),
            "content": "",
            "format": "markdown",
        }
        _attach_jin10_weekly_markdown(weekly, date, run_id)
        return weekly
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
    raw_payload = _read_optional_jin10_json(base / "raw_article_report.json")
    report_meta = _load_jin10_report_meta(date, run_id)
    source_title = _jin10_source_title(raw_payload, report_meta)
    if source_title:
        payload["source_title"] = source_title
    payload["content"] = html_path.read_text(encoding="utf-8")
    payload["format"] = "html"
    payload["path"] = str(html_path.relative_to(_PROJECT_ROOT))
    return payload


def _is_weekly_storage_report(payload: dict[str, Any]) -> bool:
    """Storage outputs are authoritative; legacy rows without report_type are daily."""
    return payload.get("report_type") == "weekly" or payload.get("family") == "jin10_weekly_visual"


def _is_daily_storage_report(payload: dict[str, Any]) -> bool:
    report_type = str(payload.get("report_type") or "").strip().lower()
    family = str(payload.get("family") or "").strip()
    if report_type and report_type != "daily":
        return False
    if family and family != "jin10_daily_visual":
        return False
    if _has_jin10_non_daily_title_marker(payload.get("title"), payload.get("source_title")):
        return False
    return True


_JIN10_NON_DAILY_TITLE_MARKERS = ("黄金头条", "投行金评", "财料", "一周热榜精选")


def _has_jin10_non_daily_title_marker(*values: Any) -> bool:
    for value in values:
        text = str(value or "")
        if text and any(marker in text for marker in _JIN10_NON_DAILY_TITLE_MARKERS):
            return True
    return False


def _read_optional_jin10_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _jin10_source_title(raw_payload: dict[str, Any] | None, report_meta: dict[str, Any] | None = None) -> str | None:
    title = (raw_payload or {}).get("title") or (report_meta or {}).get("title")
    if title:
        return str(title)
    markdown = str((raw_payload or {}).get("article_markdown") or "")
    for line in markdown.splitlines():
        text = line.strip()
        if text.startswith("#"):
            return text.lstrip("#").strip() or None
    return None


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


def get_market_tickers() -> dict[str, Any]:
    tickers: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    sources.append("jin10_news_only")

    if "xauusd" not in tickers:
        try:
            candles = [
                candle for timeframe in ("5m", "1h", "1d")
                if (candle := _latest_market_candle(asset="XAUUSD", timeframe=timeframe)) is not None
            ]
            if candles:
                candle = max(candles, key=lambda item: item["open_time"])
                tickers["xauusd"] = {
                    "price": candle["close"], "change_pct": None, "bid": None, "ask": None,
                    "source": candle["source"], "time": candle["open_time"].isoformat(),
                }
                sources.append("market_candles")
        except Exception as exc:
            logger.debug("Spot candle fallback failed for market tickers", exc_info=exc, extra={"service": "market_tickers", "stage": "spot_fallback"})

    try:
        macro = get_macro_latest()
        if macro:
            indicators = macro.get("indicators", {})
            macro_map = {
                "dxy": ["DXY", "dxy"],
                "real_10y": ["REAL_10Y", "real_10y", "REAL10Y"],
                "t10yie": ["T10YIE", "t10yie"],
                "yield_spread_2y_3m": ["YIELD_SPREAD_2Y_3M", "yield_spread_2y_3m"],
                "on_rrp": ["ON_RRP", "on_rrp"],
                "tga": ["TGA", "tga"],
            }
            for ticker_key, sym_keys in macro_map.items():
                for sym_key in sym_keys:
                    if sym_key in indicators:
                        val = indicators[sym_key]
                        tickers[ticker_key] = {"value": val.get("value") if isinstance(val, dict) else val, "unit": val.get("unit", "") if isinstance(val, dict) else "", "date": val.get("date") if isinstance(val, dict) else None, "source": "macro_latest"}
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


def _indicator_with_aliases(indicators: Any, *keys: str) -> dict[str, Any]:
    """Select the first usable indicator while retaining the canonical fallback metadata."""

    if not isinstance(indicators, dict):
        return {}
    fallback: dict[str, Any] = {}
    for key in keys:
        candidate = indicators.get(key)
        if not isinstance(candidate, dict):
            continue
        if not fallback:
            fallback = candidate
        if candidate.get("value") is not None:
            return candidate
    return fallback


def get_market_monitor_overview() -> dict[str, Any]:
    tickers_payload = get_market_tickers()
    macro_payload = get_macro_latest() or {}
    indicators = macro_payload.get("indicators", {}) if isinstance(macro_payload, dict) else {}
    generated_at = tickers_payload.get("generated_at") or datetime.now(timezone.utc).isoformat()

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
            "latest_date": None,
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
    spread_2y_3m = indicators.get("YIELD_SPREAD_2Y_3M", {})
    real10 = _indicator_with_aliases(indicators, "REAL_10Y", "REAL10Y")
    real10_value = _finite_history_value(real10.get("value"))
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
                "source": latest_xau_candle["source"],
                "time": latest_xau_candle["open_time"].isoformat(),
            }

    metrics = [
        metric_item("XAUUSD", "XAUUSD", xau.get("price"), "USD/oz", xau.get("change_pct"), None, "ok" if xau.get("price") is not None else "unavailable", xau.get("source", "")),
        metric_item("DXY", "DXY", dxy.get("value"), dxy.get("unit", "index"), dxy.get("weekly_change"), dxy.get("monthly_change"), "ok" if dxy.get("value") is not None else "unavailable", dxy.get("direction_note", "")),
        metric_item("US10Y", "US10Y", us10y.get("value"), us10y.get("unit", "%"), us10y.get("weekly_change"), us10y.get("monthly_change"), "ok" if us10y.get("value") is not None else "unavailable", us10y.get("direction_note", "")),
        metric_item("US02Y", "US02Y", us02y.get("value"), us02y.get("unit", "%"), us02y.get("weekly_change"), us02y.get("monthly_change"), "ok" if us02y.get("value") is not None else "unavailable", us02y.get("direction_note", "")),
        metric_item("YIELD_SPREAD_2Y_3M", "2Y-3M Spread", spread_2y_3m.get("value"), spread_2y_3m.get("unit", "%"), spread_2y_3m.get("weekly_change"), spread_2y_3m.get("monthly_change"), "ok" if spread_2y_3m.get("value") is not None else "unavailable", spread_2y_3m.get("direction_note", "")),
        metric_item("REAL_10Y", "10Y Real Rate", real10_value, real10.get("unit", "%"), real10.get("weekly_change"), real10.get("monthly_change"), "ok" if real10_value is not None else "unavailable", real10.get("direction_note", "")),
        metric_item("T10YIE", "T10YIE", t10yie.get("value"), t10yie.get("unit", "%"), t10yie.get("weekly_change"), t10yie.get("monthly_change"), "ok" if t10yie.get("value") is not None else "unavailable", t10yie.get("direction_note", "")),
        metric_item("TGA", "TGA", tga.get("value"), tga.get("unit", "B"), tga.get("weekly_change"), tga.get("monthly_change"), "ok" if tga.get("value") is not None else "unavailable", tga.get("direction_note", "")),
        metric_item("RRP", "RRP", rrp.get("value"), rrp.get("unit", "B"), rrp.get("weekly_change"), rrp.get("monthly_change"), "ok" if rrp.get("value") is not None else "unavailable", rrp.get("direction_note", "")),
        metric_item("SOFR", "SOFR", sofr.get("value"), sofr.get("unit", "%"), sofr.get("weekly_change"), sofr.get("monthly_change"), "ok" if sofr.get("value") is not None else "unavailable", sofr.get("direction_note", "")),
        metric_item("EFFR", "EFFR", effr.get("value"), effr.get("unit", "%"), effr.get("weekly_change"), effr.get("monthly_change"), "ok" if effr.get("value") is not None else "unavailable", effr.get("direction_note", "")),
        metric_item("IORB", "IORB", iorb.get("value"), iorb.get("unit", "%"), iorb.get("weekly_change"), iorb.get("monthly_change"), "ok" if iorb.get("value") is not None else "unavailable", iorb.get("direction_note", "")),
    ]

    observations = [xau, dxy, us10y, us02y, spread_2y_3m, real10, t10yie, tga, rrp, sofr, effr, iorb]
    for metric, observation in zip(metrics, observations):
        observed_at = observation.get("date") or observation.get("time")
        metric["latest_date"] = str(observed_at)[:10] if observed_at else None

    # Project collected facts to the keys consumed by the cross-asset table.
    # Preserve the existing RRP metric and distinguish broad dollar from DXY.
    for key, label, source_symbol, default_unit in [
        ("REPO", "逆回购", "ON_RRP_USAGE", "B"),
        ("FED_BS", "美联储资产负债表", "WALCL", "B"),
        ("USDX_N", "名义广义美元指数", "BROAD_DOLLAR", "index"),
        ("VIX", "VIX 波动率指数", "VIX", "index"),
    ]:
        if key == "REPO" and not indicators.get(source_symbol):
            source_symbol = "RRP"
        observation = indicators.get(source_symbol) or {}
        value = observation.get("value")
        available = isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
        item = metric_item(
            key, label, value if available else None, observation.get("unit", default_unit),
            observation.get("weekly_change"), observation.get("monthly_change"),
            "ok" if available else "unavailable", observation.get("direction_note", ""),
        )
        item["latest_date"] = observation.get("date") or None
        item["snapshot_id"] = macro_payload.get("snapshot_id")
        item["source_symbol"] = source_symbol
        item["source_refs"] = [f"GET /api/macro/latest#{source_symbol}"] if observation else []
        metrics.append(item)

    cot = (macro_payload.get("cot_reports") or {}).get("futures_only") or {}
    managed_money = cot.get("managed_money") or {}
    cot_net = (managed_money.get("latest") or {}).get("net")
    etf = macro_payload.get("official_etf") or {}
    holdings = etf.get("gold_holdings_tonnes")
    for metric, observed_at, refs in [
        (
            metric_item("COT_GOLD_NET", "CFTC 黄金管理基金净多", cot_net, "contracts",
                        (managed_money.get("delta") or {}).get("net"),
                        status="ok" if cot_net is not None and cot.get("freshness_status") == "fresh" else "warn" if cot_net is not None else "unavailable",
                        interpretation="CFTC futures-only 管理基金净持仓；周频报告"),
            cot.get("report_date"), cot.get("source_refs") or [],
        ),
        (
            metric_item("GLD_HOLDINGS", "SPDR GLD 黄金持有量", holdings, "tonnes",
                        etf.get("gold_holdings_tonnes_weekly_delta"),
                        status="info" if holdings is not None else "unavailable",
                        interpretation="最近可用官方披露；单基金持有量，以观测日为准"),
            etf.get("gold_holdings_tonnes_reported_on") or etf.get("as_of"), etf.get("source_refs") or [],
        ),
    ]:
        metric["latest_date"] = observed_at
        metric["snapshot_id"] = macro_payload.get("snapshot_id")
        metric["source_refs"] = list(dict.fromkeys(
            str(ref.get("reference") or ref.get("source_url"))
            for ref in refs if ref.get("reference") or ref.get("source_url")
        ))
        metrics.append(metric)

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
    observed_dates = []
    for item in metrics:
        if item.get("latest_value") is None or not item.get("latest_date"):
            continue
        try:
            observed_dates.append(datetime.fromisoformat(str(item["latest_date"])[:10]).date().isoformat())
        except ValueError:
            continue
    latest_date = max(observed_dates, default=None)
    return {
        "generated_at": generated_at,
        "latest_date": latest_date,
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
                "trade_date": metrics[0]["latest_date"],
                "file": "api://market/tickers",
                "snapshot_id": None,
                "source_ref": "GET /api/market/tickers",
                "status": metrics[0]["status"],
            },
            {
                "name": "采集宏观快照",
                "trade_date": latest_date,
                "file": macro_payload.get("artifact_path") or "api://market/monitor",
                "snapshot_id": macro_payload.get("snapshot_id"),
                "source_ref": macro_payload.get("snapshot_id") or "GET /api/market/monitor",
                "status": "ok" if indicators else "unavailable",
            },
        ],
    }


def get_market_monitor_history(limit: int = 30, timeframe: str = "1M") -> dict[str, Any]:
    normalized_timeframe = str(timeframe or "1M").upper()
    if normalized_timeframe in {"5M", "15M", "30M", "1H", "4H"}:
        return _get_market_monitor_intraday_history(limit=limit, timeframe=normalized_timeframe)
    return _get_market_monitor_daily_history(limit=limit, timeframe=normalized_timeframe)


def _get_market_monitor_intraday_history(limit: int = 30, timeframe: str = "15M") -> dict[str, Any]:
    from apps.api.services.market_candle_service import get_market_candles

    session_factory = _market_session_factory()
    points: list[dict[str, Any]] = []
    service_timeframe = {
        "5M": "5m",
        "15M": "15m",
        "30M": "30m",
        "1H": "1h",
        "4H": "4h",
    }[timeframe]
    with session_factory() as session:
        ensure_analysis_tables(session)
        candle_payload = get_market_candles(
            asset="XAUUSD",
            timeframe=service_timeframe,
            limit=limit,
            session=session,
        )

    for candle in candle_payload["candles"]:
        key = str(candle["time"])
        points.append(
            {
                "date": key,
                "XAUUSD": candle["close"],
                "xauusd_ohlc": {
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                },
                "DXY": None,
            }
        )

    coverage = candle_payload["coverage"]
    degraded = bool(coverage.get("degraded"))
    message = coverage.get("reason") or "分钟和小时周期仅提供 canonical XAUUSD；DXY 保持日线。"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "source_timeframe": candle_payload["source_timeframe"],
        "provider": candle_payload["provider"],
        "series": points,
        "available_points": len(points),
        "available_fields": ["XAUUSD", "DXY"],
        "degraded": degraded,
        "message": message,
        "source_trace": candle_payload["source_trace"],
    }


def _row_value(row: Any, field: str) -> Any:
    if isinstance(row, dict):
        value = row[field]
    else:
        value = getattr(row, field)
    if field == "open_time" and isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _finite_history_value(value: Any) -> Any:
    """Return ``None`` for numeric values that cannot be represented in JSON."""

    try:
        return value if isfinite(value) else None
    except (TypeError, ValueError):
        return value


def _get_market_monitor_daily_history(limit: int = 30, timeframe: str = "1M") -> dict[str, Any]:
    macro_base = _PROJECT_ROOT / "storage" / "features" / "macro"
    macro_points_by_date: dict[str, dict[str, Any]] = {}
    invalid_numeric_fields: set[tuple[str, str]] = set()

    def finite_value(value: Any, *, day: str, field: str) -> Any:
        sanitized = _finite_history_value(value)
        if value is not None and sanitized is None:
            invalid_numeric_fields.add((day, field))
        return sanitized

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
            def indicator_value(*symbols: str) -> Any:
                item = next((indicators.get(symbol) for symbol in symbols if indicators.get(symbol)), {})
                return (item or {}).get("value")

            macro_points_by_date[date_dir.name] = {
                "date": date_dir.name,
                "DXY": finite_value(indicator_value("DXY"), day=date_dir.name, field="DXY"),
                "US10Y": finite_value(
                    indicator_value("US10Y", "DGS10"), day=date_dir.name, field="US10Y"
                ),
                "REAL_10Y": finite_value(
                    _indicator_with_aliases(indicators, "REAL_10Y", "REAL10Y").get("value"),
                    day=date_dir.name,
                    field="REAL_10Y",
                ),
                "T10YIE": finite_value(
                    indicator_value("T10YIE", "BREAKEVEN_10Y"), day=date_dir.name, field="T10YIE"
                ),
                "YIELD_SPREAD_2Y_3M": finite_value(
                    indicator_value("YIELD_SPREAD_2Y_3M"),
                    day=date_dir.name,
                    field="YIELD_SPREAD_2Y_3M",
                ),
            }

    session_factory = _market_session_factory()
    with session_factory() as session:
        ensure_analysis_tables(session)
        price_rows = list_market_candles_by_assets(session, assets=["XAUUSD", "DXY"], timeframe="1d", limit=limit + 10)

    prices_by_date: dict[str, dict[str, float]] = {}
    for row in price_rows:
        if row.asset == "XAUUSD" and not is_xauusd_compatible_row(row):
            continue
        day = row.open_time.date().isoformat()
        prices_by_date.setdefault(day, {})
        prices_by_date[day][row.asset] = finite_value(row.close, day=day, field=row.asset)

    all_dates = sorted(set(macro_points_by_date.keys()) | set(prices_by_date.keys()))
    if limit > 0:
        all_dates = all_dates[-limit:]
    points: list[dict[str, Any]] = []
    for day in all_dates:
        point = dict(macro_points_by_date.get(day) or {"date": day})
        day_prices = prices_by_date.get(day, {})
        if "XAUUSD" in day_prices:
            point["XAUUSD"] = day_prices["XAUUSD"]
        else:
            point.setdefault("XAUUSD", None)
        if "DXY" in day_prices and point.get("DXY") is None:
            point["DXY"] = day_prices["DXY"]
        point.setdefault("xauusd_ohlc", None)
        points.append(point)

    daily_xau_rows = [row for row in price_rows if row.asset == "XAUUSD" and is_xauusd_compatible_row(row)]
    daily_xau_by_date: dict[str, dict[str, Any] | None] = {}
    for row in daily_xau_rows:
        day = row.open_time.date().isoformat()
        ohlc = {
            field: finite_value(getattr(row, field), day=day, field=f"xauusd_ohlc.{field}")
            for field in ("open", "high", "low", "close")
        }
        daily_xau_by_date[day] = ohlc if all(value is not None for value in ohlc.values()) else None
    for point in points:
        if point["date"] in daily_xau_by_date:
            point["xauusd_ohlc"] = daily_xau_by_date[point["date"]]

    gap_dates = _find_missing_daily_dates(points, keys=["XAUUSD", "DXY"])

    message = "历史序列当前基于本地 macro snapshots；若点数不足，则页面应显式提示历史深度不足。"
    if invalid_numeric_fields:
        message += f" {len(invalid_numeric_fields)} 个非有限数值已按缺失处理。"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "source_timeframe": "1d",
        "series": points,
        "available_points": len(points),
        "available_fields": ["XAUUSD", "DXY", "US10Y", "REAL_10Y", "T10YIE", "YIELD_SPREAD_2Y_3M"],
        "degraded": len(points) < 5 or bool(invalid_numeric_fields),
        "message": message,
        "invalid_numeric_fields": [
            {"date": day, "field": field, "reason": "non_finite"}
            for day, field in sorted(invalid_numeric_fields)
        ],
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
            rows = list_market_candles(session, asset=asset, timeframe=timeframe, limit=20)
    except Exception as exc:
        logger.debug("Market candle fallback unavailable for %s %s: %s", asset, timeframe, exc)
        return None
    if asset == "XAUUSD":
        rows = [row for row in rows if is_xauusd_compatible_row(row)]
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
