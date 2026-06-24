"""
P1-07c: Module Signals 后端聚合服务。

为 Strategy Center 提供只读模块信号汇聚，每个模块按固定契约返回:
  - module: str ("market" | "cme" | "event" | "knowledge")
  - label: str (中文展示名)
  - status: str ("available" | "partial" | "unavailable")
  - summary: str | None
  - source_refs: list[dict]

规则:
  - 不计算 bias/regime/GEX/WallScore/Playbook 匹配。
  - 缺失数据显式返回 "unavailable"，不伪装。
  - 所有 source_refs 可追溯到真实数据源。
"""

from __future__ import annotations

import logging
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT

logger = logging.getLogger(__name__)


def build_module_signals() -> list[dict[str, Any]]:
    """聚合四个模块的当前信号状态，返回适合 API 序列化的列表。"""
    return [
        _build_market_signal(),
        _build_cme_signal(),
        _build_event_signal(),
        _build_knowledge_signal(),
    ]


# ── market ──

def _build_market_signal() -> dict[str, Any]:
    """宏观 & 市场行情模块信号。"""
    signal: dict[str, Any] = {
        "module": "market",
        "label": "宏观 & 行情",
        "status": "unavailable",
        "summary": None,
        "source_refs": [],
    }

    try:
        from apps.api.data_service import get_macro_latest, get_market_tickers  # noqa: PLC0415

        macro = get_macro_latest()
        tickers = get_market_tickers()
    except Exception:
        logger.warning("module_signals: macro/tickers load failed", exc_info=True)
        return signal

    refs: list[dict[str, Any]] = []
    parts: list[str] = []
    has_any = False

    # ── 行情 ──
    if isinstance(tickers, dict) and isinstance(tickers.get("tickers"), dict):
        t = tickers["tickers"]
        has_any = True
        xau = t.get("xauusd", {})
        if xau.get("price") is not None:
            parts.append(f"XAUUSD {xau['price']}")
        dxy = t.get("dxy", {})
        if dxy.get("value") is not None:
            parts.append(f"DXY {dxy['value']}")
        refs.append({
            "source_ref": "market.tickers",
            "label": "实时行情 (Jin10 MCP + 宏观快照)",
            "status": "ok",
        })

    # ── 宏观 ──
    if isinstance(macro, dict) and macro.get("indicators"):
        has_any = True
        indicators = macro["indicators"]
        real_10y = indicators.get("REAL_10Y", {})
        us10y = indicators.get("US10Y", {})
        tga = indicators.get("TGA", {})
        if isinstance(real_10y, dict) and real_10y.get("value") is not None:
            parts.append(f"实际利率 {real_10y['value']}%")
        if isinstance(us10y, dict) and us10y.get("value") is not None:
            parts.append(f"US10Y {us10y['value']}%")
        if isinstance(tga, dict) and tga.get("value") is not None:
            parts.append(f"TGA {tga['value']}B")
        refs.append({
            "source_ref": "macro.latest",
            "label": "宏观快照 (FRED/Fed/Treasury)",
            "status": "ok",
            "as_of": macro.get("as_of"),
        })

    # ── 缺失指标 ──
    missing = macro.get("unavailable_symbols", []) if isinstance(macro, dict) else []
    if missing:
        parts.append(f"{len(missing)} 项指标不可用")

    if has_any:
        signal["status"] = "partial" if missing else "available"
        signal["summary"] = "；".join(parts) if parts else "宏观数据可用"
    else:
        signal["summary"] = "宏观与行情数据不可用"

    signal["source_refs"] = refs
    return signal


# ── cme_options ──

def _build_cme_signal() -> dict[str, Any]:
    """CME 期权结构模块信号。"""
    signal: dict[str, Any] = {
        "module": "cme",
        "label": "CME 期权结构",
        "status": "unavailable",
        "summary": None,
        "source_refs": [],
    }

    try:
        from apps.api.data_service import get_options_snapshot, list_options_report_dates  # noqa: PLC0415

        dates = list_options_report_dates()
    except Exception:
        logger.warning("module_signals: cme dates load failed", exc_info=True)
        return signal

    if not dates:
        signal["summary"] = "暂无 CME 期权分析数据"
        return signal

    latest_date = dates[0]
    refs: list[dict[str, Any]] = [
        {
            "source_ref": "cme.options.latest",
            "label": "CME 期权分析",
            "trade_date": latest_date,
            "status": "ok",
        }
    ]

    try:
        snap = get_options_snapshot()
    except Exception:
        snap = None

    if snap:
        product = snap.get("data_source", {}).get("product", "GC")
        gamma_zero = snap.get("parameters", {}).get("f_value")
        n_expiries = len(snap.get("data_source", {}).get("expiries", []))
        parts = [f"{product} ({n_expiries} 个到期日)"]
        if gamma_zero is not None:
            parts.append(f"Gamma 零点 ≈ {gamma_zero:.0f}")
        signal["status"] = "available"
        signal["summary"] = "；".join(parts)
    else:
        signal["status"] = "partial"
        signal["summary"] = f"期权日期 {latest_date} 可用，但快照未加载"

    signal["source_refs"] = refs
    return signal


# ── event_flow ──

def _build_event_signal() -> dict[str, Any]:
    """事件流模块信号（当前解析 Jin10 财经日历/快讯可用性）。"""
    signal: dict[str, Any] = {
        "module": "event",
        "label": "事件流 & 定价",
        "status": "unavailable",
        "summary": None,
        "source_refs": [],
    }

    # Jin10 快讯 & 财经日历可用性探测
    try:
        import json

        snap_dir = _PROJECT_ROOT / "storage" / "features" / "snapshots" / "XAUUSD"
        jin10_section = None
        if snap_dir.exists():
            for date_dir in sorted((d for d in snap_dir.iterdir() if d.is_dir()), reverse=True):
                for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
                    snap_path = run_dir / "premarket_snapshot.json"
                    if not snap_path.exists():
                        continue
                    try:
                        snap = json.loads(snap_path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    jin10_section = snap.get("jin10")
                    if jin10_section:
                        break
                if jin10_section:
                    break
    except Exception:
        jin10_section = None

    has_news = False
    parts: list[str] = []
    refs: list[dict[str, Any]] = []

    if isinstance(jin10_section, dict):
        flash_count = jin10_section.get("flash_count")
        calendar_count = jin10_section.get("calendar_count")
        if flash_count is not None and flash_count > 0:
            has_news = True
            parts.append(f"快讯 {flash_count} 条")
        if calendar_count is not None and calendar_count > 0:
            has_news = True
            parts.append(f"财经日历 {calendar_count} 项")
        if has_news:
            refs.append({
                "source_ref": "jin10.news",
                "label": "Jin10 快讯 & 财经日历",
                "status": "ok",
            })

    if has_news:
        signal["status"] = "available"
        signal["summary"] = "；".join(parts)
    else:
        signal["status"] = "unavailable"
        signal["summary"] = "事件流真实数据不可用"

    signal["source_refs"] = refs
    return signal


# ── knowledge ──

def _build_knowledge_signal() -> dict[str, Any]:
    """知识库模块信号。"""
    return {
        "module": "knowledge",
        "label": "知识库",
        "status": "unavailable",
        "summary": "知识库真实索引不可用",
        "source_refs": [],
    }
