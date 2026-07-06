"""Jin10 实时行情定时刷新（APScheduler 任务）。

每 15 分钟拉取 Jin10 MCP 实时报价，写入轻量 JSON 缓存。
供 /api/jin10/quotes/latest 消费（当 premarket_snapshot 不可用时回退）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from sqlalchemy import func

from apps.analysis.agents.jin10_flash_semantic_filter import (
    AGENT_ID as JIN10_FLASH_SEMANTIC_FILTER_AGENT_ID,
    build_jin10_flash_semantic_filter_prompt_template,
    render_jin10_flash_semantic_filter_messages,
)
from apps.collectors.jin10.mcp_client import Jin10MCPClient
from apps.llm.gateway import chat_sync
from apps.runtime.secret_resolver import resolve_runtime_secret
from database.models.analysis import MarketCandle, ensure_analysis_tables
from database.models.engine import SessionLocal
from database.queries.market import upsert_market_candle

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("./storage/outputs/jin10/quotes_cache.json")
_CALENDAR_CACHE_PATH = Path("./storage/outputs/jin10/calendar_cache.json")
_JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
_JIN10_MCP_KEY_ENV = "JIN10_MCP_KEY"
_JIN10_CALENDAR_PAST_WINDOW_DAYS = 7
_JIN10_CALENDAR_FUTURE_WINDOW_DAYS = 14

QUOTE_SYMBOLS = [
    "XAUUSD",
    "XAGUSD",
    "USDCNH",
    "EURUSD",
    "USDJPY",
    "GBPUSD",
    "USOIL",
    "SPX",
    "DJI",
]

KLINE_SYMBOLS = ["XAUUSD"]
DAILY_MARKET_CANDLE_ASSETS = ("XAUUSD", "DXY")
_JIN10_MCP_MARKET_SOURCE_KEY = "jin10_mcp_market"


def _get_mcp_key() -> str:
    project_root = Path(__file__).resolve().parent.parent.parent
    env_path = project_root / ".env"
    env = {}
    if env_path.exists():
        env = dotenv_values(str(env_path))
    return resolve_runtime_secret(_JIN10_MCP_KEY_ENV) or env.get(_JIN10_MCP_KEY_ENV, "")


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_jin10_calendar_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip().replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)

    candidates = [normalized]
    if len(normalized) == 16:
        candidates.append(f"{normalized}:00")

    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _jin10_calendar_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    start = datetime.combine(anchor - timedelta(days=_JIN10_CALENDAR_PAST_WINDOW_DAYS), datetime.min.time(), timezone.utc)
    end = datetime.combine(anchor + timedelta(days=_JIN10_CALENDAR_FUTURE_WINDOW_DAYS), datetime.max.time(), timezone.utc)
    return start, end


def _is_jin10_calendar_event_in_window(event: dict[str, Any], *, window_start: datetime, window_end: datetime) -> bool:
    parsed_time = _parse_jin10_calendar_time(event.get("pub_time"))
    return parsed_time is not None and window_start <= parsed_time <= window_end


def refresh_jin10_quotes_cache() -> None:
    """拉取 Jin10 MCP 实时报价并写入 JSON 缓存文件。"""
    mcp_key = _get_mcp_key()
    if not mcp_key:
        logger.debug("Jin10 MCP key not configured; skipping quotes cache refresh")
        return

    try:
        import httpx
    except ImportError:
        logger.exception("httpx not available")
        return

    quotes: dict[str, dict[str, Any]] = {}
    try:
        with httpx.Client(timeout=15.0, trust_env=False) as client:
            init_r = client.post(
                _JIN10_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "finance-agent", "version": "0.1"},
                    },
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                },
            )
            init_r.raise_for_status()
            sid = init_r.headers.get("Mcp-Session-Id", "")
            if not sid:
                logger.warning("Jin10 MCP session id missing during refresh")
                return

            client.post(
                _JIN10_MCP_URL,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                    "Mcp-Session-Id": sid,
                },
            ).raise_for_status()

            for symbol in QUOTE_SYMBOLS:
                try:
                    resp = client.post(
                        _JIN10_MCP_URL,
                        json={
                            "jsonrpc": "2.0",
                            "id": 99,
                            "method": "tools/call",
                            "params": {"name": "get_quote", "arguments": {"code": symbol}},
                        },
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {mcp_key}",
                            "Mcp-Session-Id": sid,
                        },
                    )
                    resp.raise_for_status()
                    for line in resp.text.split("\n"):
                        if not line.startswith("data:"):
                            continue
                        result = json.loads(line[5:]).get("result", {})
                        sc = result.get("structuredContent", {})
                        if isinstance(sc, dict) and sc.get("status") == 200:
                            qdata = sc.get("data", {})
                            quotes[symbol] = {
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
                            }
                        break
                except Exception as exc:
                    logger.warning("Quote %s refresh failed: %s", symbol, exc)
    except Exception as exc:
        logger.warning("Jin10 MCP quotes refresh failed: %s", exc)
        return

    if quotes:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "quotes": quotes,
        }
        _CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("Jin10 quotes cache refreshed: %d symbols", len(quotes))


def refresh_jin10_kline_cache(*, count: int = 100) -> None:
    """拉取 Jin10 近端 1m K 线并增量写入 market_candles。"""
    mcp_key = _get_mcp_key()
    if not mcp_key:
        logger.debug("Jin10 MCP key not configured; skipping kline refresh")
        return

    try:
        with Jin10MCPClient(mcp_key=mcp_key) as client, SessionLocal() as session:
            ensure_analysis_tables(session)
            imported = 0
            for symbol in KLINE_SYMBOLS:
                latest_open_time = session.query(func.max(MarketCandle.open_time)).filter(
                    MarketCandle.asset == symbol,
                    MarketCandle.timeframe == "1m",
                ).scalar()
                latest_open_time = _normalize_existing_open_time(latest_open_time)
                payload = client.get_kline(symbol, count=min(max(count, 1), 100))
                rows = _extract_kline_rows(payload)
                for row in rows:
                    candle = _normalize_kline_row(row)
                    if candle is None:
                        continue
                    if latest_open_time is not None and candle["open_time"] <= latest_open_time:
                        continue
                    upsert_market_candle(
                        session,
                        asset=symbol,
                        timeframe="1m",
                        open_time=candle["open_time"],
                        open=candle["open"],
                        high=candle["high"],
                        low=candle["low"],
                        close=candle["close"],
                        volume=candle["volume"],
                        source="jin10_mcp_kline_1m",
                        source_ref={
                            "symbol": symbol,
                            "source": "jin10_mcp",
                            "source_key": _JIN10_MCP_MARKET_SOURCE_KEY,
                            "provider_timeframe": "1m",
                        },
                    )
                    imported += 1
            session.commit()
            logger.debug("Jin10 kline cache refreshed: imported=%d", imported)
    except Exception as exc:
        logger.warning("Jin10 MCP kline refresh failed: %s", exc)


def refresh_market_candle_daily_cache(*, range_: str = "10d") -> None:
    """Refresh recent daily market candles for local coverage and gap repair."""
    try:
        storage_root = Path("./storage").resolve()
        with SessionLocal() as session:
            ensure_analysis_tables(session)
            imported = 0
            scanned = 0
            for asset in DAILY_MARKET_CANDLE_ASSETS:
                candles, raw_path, source, source_ref = _collect_daily_market_candles(
                    storage_root=storage_root,
                    asset=asset,
                    range_=range_,
                )
                for candle in candles:
                    scanned += 1
                    upsert_market_candle(
                        session,
                        asset=asset,
                        timeframe="1d",
                        open_time=candle["open_time"],
                        open=candle["open"],
                        high=candle["high"],
                        low=candle["low"],
                        close=candle["close"],
                        volume=candle["volume"],
                        source=source,
                        source_ref={
                            **source_ref,
                            "refresh_role": "scheduled_daily_gap_repair",
                        },
                        raw_path=raw_path,
                    )
                    imported += 1
            session.commit()
            logger.debug("Daily market candle refresh completed: scanned=%d upserted=%d", scanned, imported)
    except Exception as exc:
        logger.warning("Daily market candle refresh failed: %s", exc)


def _collect_daily_market_candles(
    *,
    storage_root: Path,
    asset: str,
    range_: str,
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any]]:
    from scripts.backfill_market_candles import collect_daily_candles

    return collect_daily_candles(
        storage_root=storage_root,
        asset=asset,
        range_=range_,
    )


def _extract_kline_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    rows = data.get("klines") or data.get("list") or data.get("data") or []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _normalize_kline_row(row: dict[str, Any]) -> dict[str, Any] | None:
    ts = row.get("time")
    open_ = row.get("open")
    high = row.get("high")
    low = row.get("low")
    close = row.get("close")
    if None in (ts, open_, high, low, close):
        return None
    try:
        open_time = datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(second=0, microsecond=0)
        return {
            "open_time": open_time,
            "open": float(open_),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(row["volume"]) if row.get("volume") is not None else None,
        }
    except (TypeError, ValueError):
        return None


def _normalize_existing_open_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def refresh_jin10_calendar_cache() -> None:
    """拉取 Jin10 MCP 经济日历并写入 JSON 缓存文件。"""
    mcp_key = _get_mcp_key()
    if not mcp_key:
        logger.debug("Jin10 MCP key not configured; skipping calendar cache refresh")
        return

    try:
        import httpx
    except ImportError:
        logger.exception("httpx not available")
        return

    try:
        with httpx.Client(timeout=15.0, trust_env=False) as client:
            init_r = client.post(
                _JIN10_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "finance-agent", "version": "0.1"},
                    },
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                },
            )
            init_r.raise_for_status()
            sid = init_r.headers.get("Mcp-Session-Id", "")
            if not sid:
                logger.warning("Jin10 MCP session id missing during calendar refresh")
                return

            client.post(
                _JIN10_MCP_URL,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                    "Mcp-Session-Id": sid,
                },
            ).raise_for_status()

            resp = client.post(
                _JIN10_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "tools/call",
                    "params": {"name": "list_calendar", "arguments": {}},
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                    "Mcp-Session-Id": sid,
                },
            )
            resp.raise_for_status()
            for line in resp.text.split("\n"):
                if not line.startswith("data:"):
                    continue
                result = json.loads(line[5:]).get("result", {})
                sc = result.get("structuredContent", {})
                if isinstance(sc, dict) and sc.get("status") == 200:
                    events = sc.get("data", [])
                    window_start, window_end = _jin10_calendar_window()
                    filtered = [
                        e for e in events
                        if isinstance(e, dict)
                        and _is_jin10_calendar_event_in_window(e, window_start=window_start, window_end=window_end)
                    ]
                    _CALENDAR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    payload = {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "events": filtered,
                    }
                    _CALENDAR_CACHE_PATH.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    logger.debug("Jin10 calendar cache refreshed: %d events", len(filtered))
                break
    except Exception as exc:
        logger.warning("Jin10 MCP calendar refresh failed: %s", exc)


_FLASH_CACHE_PATH = Path("./storage/outputs/jin10/flash_cache.json")
_FLASH_CLASSIFICATION_VERSION = "jin10-flash-semantic-llm-v2"
_FLASH_CLASSIFIER_PROVIDER = "mimo"
_FLASH_CLASSIFIER_MODEL_ENV = "LLM_MIMO_FLASH_MODEL"
_FLASH_CLASSIFIER_DEFAULT_MODEL = "mimo-v2.5"
_FLASH_SOURCE_KEY = "jin10_flash"
_FLASH_SOURCE_NAME = "Jin10 Flash"
_FLASH_LANE_SOURCE_KEY = "jin10_mcp_flash"
_JIN10_MCP_SETTINGS_KEY = "source.jin10_mcp.enabled"

_MARKET_FLASH_KEYWORDS = (
    "美联储",
    "央行",
    "降息",
    "加息",
    "利率",
    "通胀",
    "CPI",
    "PCE",
    "非农",
    "GDP",
    "美元",
    "黄金",
    "白银",
    "原油",
    "油价",
    "美债",
    "收益率",
    "股指",
    "纳斯达克",
    "标普",
    "避险",
)
_STRATEGIC_CHANNEL_KEYWORDS = (
    "霍尔木兹",
    "油轮",
    "海峡",
    "阿曼",
    "英国海上贸易行动办公室",
    "红海",
    "曼德海峡",
)
_GEO_ACTOR_KEYWORDS = ("伊朗", "美伊", "以色列", "黎巴嫩", "真主党", "胡塞")
_ESCALATION_KEYWORDS = (
    "导弹",
    "无人机",
    "袭击",
    "击落",
    "防空",
    "警报",
    "爆炸",
    "封锁",
    "开火",
    "制裁",
    "核",
    "停火",
    "协议",
    "谅解备忘录",
)
_STRONG_EVENT_KEYWORDS = ("击中", "袭击", "不明投射物", "安全事件", "霍尔木兹", "封锁", "导弹", "无人机", "击落")
_LOW_SIGNAL_PATTERNS = ("船员安全", "未报告造成环境影响", "前往下一个停靠港口", "暂无人员伤亡", "未造成其受伤", "遇害")


def _extract_flash_items(payload: Any) -> list[dict[str, Any]]:
    """Normalize Jin10 flash payload into a list of item dicts.

    Jin10 MCP `list_flash` currently returns `structuredContent.data.items`.
    Keep a list fallback so older cache shapes do not explode the refresher.
    """
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _is_jin10_mcp_source_enabled() -> bool:
    """Respect Settings source toggle; default open if settings DB is unavailable."""
    try:
        from database.queries.app_settings import get_app_setting

        with SessionLocal() as session:
            record = get_app_setting(session, _JIN10_MCP_SETTINGS_KEY)
            if record is None:
                return True
            value = record.value_json if isinstance(record.value_json, dict) else {}
            return value.get("enabled") is not False
    except Exception as exc:
        logger.debug("Jin10 MCP settings preflight unavailable; defaulting enabled: %s", exc)
        return True


def _parse_flash_item_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _latest_flash_item_time(items: list[dict[str, Any]]) -> datetime | None:
    times = [
        parsed
        for parsed in (_parse_flash_item_time(item.get("time")) for item in items)
        if parsed is not None
    ]
    return max(times) if times else None


def _latest_flash_item_url(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        url = item.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _flash_cache_artifact_path() -> str:
    try:
        return _FLASH_CACHE_PATH.relative_to(Path(".")).as_posix()
    except ValueError:
        return _FLASH_CACHE_PATH.as_posix()


def _upsert_jin10_flash_source_status(
    *,
    status: str,
    configured: bool,
    raw_ingested: bool = False,
    parsed: bool = False,
    analysis_ready: bool = False,
    items: list[dict[str, Any]] | None = None,
    error_message: str | None = None,
    generated_at: str | None = None,
    classification_provider: str | None = None,
    classification_model: str | None = None,
) -> None:
    """Write realtime flash refresh state into Data Ingestion observability."""
    items = items or []
    latest_raw_time = _latest_flash_item_time(items)
    latest_url = _latest_flash_item_url(items)
    try:
        from database.queries.data_source_status import upsert_data_source_status

        with SessionLocal() as session:
            ensure_analysis_tables(session)
            upsert_data_source_status(
                session,
                {
                    "source_key": _FLASH_SOURCE_KEY,
                    "source_name": _FLASH_SOURCE_NAME,
                    "source_group": "news",
                    "source_type": "api",
                    "access_method": "jin10_mcp_list_flash",
                    "configured": configured,
                    "raw_ingested": raw_ingested,
                    "parsed": parsed,
                    "analysis_ready": analysis_ready,
                    "latest_raw_time": latest_raw_time,
                    "latest_parsed_time": datetime.now(timezone.utc) if parsed else None,
                    "latest_snapshot_id": None,
                    "row_count": len(items),
                    "status": status,
                    "error_message": error_message,
                    "last_run_id": "jin10_flash_refresh",
                    "next_run_time": None,
                    "source_metadata": {
                        "latest_raw_url": latest_url,
                        "latest_raw_ref": {
                            "url": latest_url,
                            "published_at": latest_raw_time.isoformat() if latest_raw_time else None,
                            "content": str(items[0].get("content") or "")[:240] if items else "",
                        },
                        "collector_raw_artifact_path": _flash_cache_artifact_path(),
                        "cache_artifact_path": _flash_cache_artifact_path(),
                        "generated_at": generated_at,
                        "item_count": len(items),
                        "key_item_count": sum(1 for item in items if item.get("is_key_event") is True),
                        "classification_version": _FLASH_CLASSIFICATION_VERSION,
                        "classification_provider": classification_provider,
                        "classification_model": classification_model,
                        "lane_source_key": _FLASH_LANE_SOURCE_KEY,
                        "settings_gate": "jin10_mcp",
                    },
                },
            )
            session.commit()
    except Exception as exc:
        logger.debug("Failed to upsert Jin10 flash data source status: %s", exc)


def _matched_keywords(content: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in content]


def classify_jin10_flash_item_fallback(item: dict[str, Any]) -> dict[str, Any]:
    """Fallback classifier used only when MiMo semantic tagging is unavailable."""
    content = str(item.get("content") or item.get("title") or "").strip()
    if not content:
        return {
            "is_key_event": False,
            "importance": "normal",
            "signal_tags": [],
            "summary_zh": "",
            "filter_reason": "empty_content",
            "classification_provider": "fallback_rule",
            "classification_model": "",
            "classification_confidence": 0.0,
        }

    market_hits = _matched_keywords(content, _MARKET_FLASH_KEYWORDS)
    channel_hits = _matched_keywords(content, _STRATEGIC_CHANNEL_KEYWORDS)
    actor_hits = _matched_keywords(content, _GEO_ACTOR_KEYWORDS)
    escalation_hits = _matched_keywords(content, _ESCALATION_KEYWORDS)
    strong_hits = _matched_keywords(content, _STRONG_EVENT_KEYWORDS)
    low_hits = _matched_keywords(content, _LOW_SIGNAL_PATTERNS)

    signal_tags: list[str] = []
    if market_hits:
        signal_tags.append("market_sensitive")
    if channel_hits:
        signal_tags.append("strategic_channel")
    if actor_hits and escalation_hits:
        signal_tags.append("geopolitical_escalation")
    if low_hits:
        signal_tags.append("low_signal_followup")

    if low_hits and not market_hits and not strong_hits:
        return {
            "is_key_event": False,
            "importance": "normal",
            "signal_tags": signal_tags,
            "summary_zh": "",
            "filter_reason": "low_signal_followup",
            "classification_provider": "fallback_rule",
            "classification_model": "",
            "classification_confidence": 0.45,
        }

    is_key_event = bool(market_hits or channel_hits or (actor_hits and escalation_hits))
    importance = "high" if market_hits or channel_hits or len(signal_tags) >= 2 else "medium" if is_key_event else "normal"
    return {
        "is_key_event": is_key_event,
        "importance": importance,
        "signal_tags": signal_tags,
        "summary_zh": "",
        "filter_reason": "key_event" if is_key_event else "no_market_signal",
        "classification_provider": "fallback_rule",
        "classification_model": "",
        "classification_confidence": 0.55 if is_key_event else 0.35,
    }


def _get_flash_classifier_prompt_template() -> dict[str, Any]:
    """Resolve active settings prompt, falling back to registry default."""
    try:
        from apps.analysis.agents.registry import get_active_prompt_version_from_db, get_agent_registry

        active = get_active_prompt_version_from_db(JIN10_FLASH_SEMANTIC_FILTER_AGENT_ID)
        if active and isinstance(active.get("prompt_template"), dict):
            return active["prompt_template"]

        agent = get_agent_registry(JIN10_FLASH_SEMANTIC_FILTER_AGENT_ID)
        template = (agent or {}).get("prompt", {}).get("template")
        if isinstance(template, dict):
            return template
    except Exception as exc:
        logger.debug("Failed to resolve flash classifier prompt template: %s", exc)
    return build_jin10_flash_semantic_filter_prompt_template()


def _coerce_flash_importance(value: Any, *, is_key_event: bool) -> str:
    importance = str(value or "").strip().lower()
    if importance in {"high", "medium", "normal"}:
        return importance
    return "medium" if is_key_event else "normal"


def _coerce_flash_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "是"}:
            return True
        if normalized in {"false", "no", "0", "否"}:
            return False
    return False


def _coerce_flash_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for tag in value[:6]:
        text = str(tag).strip()
        if text and text not in tags:
            tags.append(text[:48])
    return tags


def _coerce_flash_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(confidence, 1.0))


def _coerce_flash_summary(value: Any) -> str:
    return str(value or "").strip()[:80]


_FLASH_CONTENT_TYPES = {"flash", "article", "report", "calendar"}


def _coerce_flash_content_type(value: Any) -> str:
    """标准化 content_type 值。"""
    ct = str(value).strip().lower() if value else "flash"
    if ct in _FLASH_CONTENT_TYPES:
        return ct
    # 模糊匹配
    if ct in ("news", "market_flash", "headline", "快讯"):
        return "flash"
    if ct in ("article", "news_article", "新闻", "报道", "文章"):
        return "article"
    if ct in ("report", "special_report", "depth", "报告", "深度", "长文"):
        return "report"
    if ct in ("calendar", "event_list", "schedule", "日历", "日程"):
        return "calendar"
    return "flash"  # 默认


def _parse_flash_classifier_response(content: str, item_count: int) -> dict[int, dict[str, Any]]:
    normalized_content = content.strip()
    if normalized_content.startswith("```"):
        normalized_content = normalized_content.removeprefix("```json").removeprefix("```").strip()
        normalized_content = normalized_content.removesuffix("```").strip()
    parsed = json.loads(normalized_content)
    raw_items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(raw_items, list):
        raise ValueError("LLM response missing items list")

    results: dict[int, dict[str, Any]] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= item_count:
            continue
        is_key_event = _coerce_flash_bool(raw.get("is_key_event"))
        results[idx] = {
            "is_key_event": is_key_event,
            "importance": _coerce_flash_importance(raw.get("importance"), is_key_event=is_key_event),
            "signal_tags": _coerce_flash_tags(raw.get("signal_tags")),
            "summary_zh": _coerce_flash_summary(raw.get("summary_zh")),
            "filter_reason": str(raw.get("filter_reason") or ("key_event" if is_key_event else "no_market_signal"))[:200],
            "classification_confidence": _coerce_flash_confidence(raw.get("confidence")),
            "content_type": _coerce_flash_content_type(raw.get("content_type")),
        }
    return results


def classify_jin10_flash_items_with_llm(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify flash items with MiMo semantic tagging, falling back per item if needed."""
    if not items:
        return []

    fallback_items = [{**item, **classify_jin10_flash_item_fallback(item)} for item in items]
    model = (os.getenv(_FLASH_CLASSIFIER_MODEL_ENV) or "").strip() or _FLASH_CLASSIFIER_DEFAULT_MODEL

    try:
        response = chat_sync(
            messages=render_jin10_flash_semantic_filter_messages(
                _get_flash_classifier_prompt_template(),
                items,
            ),
            provider=_FLASH_CLASSIFIER_PROVIDER,
            model=model,
            temperature=0.0,
            max_tokens=1800,
            json_mode=True,
            max_retries=1,
        )
        labels = _parse_flash_classifier_response(response.content, len(items))
    except Exception as exc:
        logger.warning("Jin10 flash MiMo semantic classification failed; using fallback: %s", exc)
        return fallback_items

    annotated: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        label = labels.get(idx)
        if label is None:
            annotated.append(fallback_items[idx])
            continue
        annotated.append(
            {
                **item,
                **label,
                "classification_provider": response.provider,
                "classification_model": response.model,
            }
        )
    return annotated


def refresh_jin10_flash_cache() -> None:
    """拉取 Jin10 MCP 快讯并写入 JSON 缓存文件。"""
    if not _is_jin10_mcp_source_enabled():
        logger.debug("Jin10 MCP source disabled in Settings; skipping flash cache refresh")
        _upsert_jin10_flash_source_status(
            status="disabled",
            configured=False,
            error_message="disabled_by_settings: source.jin10_mcp.enabled=false",
        )
        return

    mcp_key = _get_mcp_key()
    if not mcp_key:
        logger.debug("Jin10 MCP key not configured; skipping flash cache refresh")
        _upsert_jin10_flash_source_status(
            status="not_connected",
            configured=False,
            error_message="missing JIN10_MCP_KEY",
        )
        return

    try:
        import httpx
    except ImportError:
        logger.exception("httpx not available")
        _upsert_jin10_flash_source_status(
            status="error",
            configured=True,
            error_message="httpx not available",
        )
        return

    try:
        with httpx.Client(timeout=15.0, trust_env=False) as client:
            init_r = client.post(
                _JIN10_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "finance-agent", "version": "0.1"},
                    },
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                },
            )
            init_r.raise_for_status()
            sid = init_r.headers.get("Mcp-Session-Id", "")
            if not sid:
                logger.warning("Jin10 MCP session id missing during flash refresh")
                _upsert_jin10_flash_source_status(
                    status="error",
                    configured=True,
                    error_message="Jin10 MCP session id missing during flash refresh",
                )
                return

            client.post(
                _JIN10_MCP_URL,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                    "Mcp-Session-Id": sid,
                },
            ).raise_for_status()

            resp = client.post(
                _JIN10_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "tools/call",
                    "params": {"name": "list_flash", "arguments": {}},
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                    "Mcp-Session-Id": sid,
                },
            )
            resp.raise_for_status()
            for line in resp.text.split("\n"):
                if not line.startswith("data:"):
                    continue
                result = json.loads(line[5:]).get("result", {})
                sc = result.get("structuredContent", {})
                if isinstance(sc, dict) and sc.get("status") == 200:
                    items = _extract_flash_items(sc)
                    annotated_items = classify_jin10_flash_items_with_llm(items[:50])
                    _FLASH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    generated_at = datetime.now(timezone.utc).isoformat()
                    payload = {
                        "generated_at": generated_at,
                        "items": annotated_items,
                        "key_item_count": sum(1 for item in annotated_items if item.get("is_key_event") is True),
                        "classification_version": _FLASH_CLASSIFICATION_VERSION,
                        "classification_provider": _summarize_flash_classification_provider(annotated_items),
                    }
                    _FLASH_CACHE_PATH.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                    )

                    # 持久化到 DB + 增量光标 + 触发分析任务
                    _persist_flash_to_db(annotated_items)

                    _upsert_jin10_flash_source_status(
                        status="ok",
                        configured=True,
                        raw_ingested=bool(annotated_items),
                        parsed=bool(annotated_items),
                        analysis_ready=bool(annotated_items),
                        items=annotated_items,
                        generated_at=generated_at,
                        classification_provider=payload["classification_provider"],
                        classification_model=_summarize_flash_classification_model(annotated_items),
                    )
                    logger.debug("Jin10 flash cache refreshed: %d items", len(items[:50]))
                break
    except Exception as exc:
        logger.warning("Jin10 MCP flash refresh failed: %s", exc)
        _upsert_jin10_flash_source_status(
            status="error",
            configured=True,
            error_message=str(exc),
        )


def _summarize_flash_classification_provider(items: list[dict[str, Any]]) -> str:
    providers = {str(item.get("classification_provider") or "unavailable") for item in items}
    if not providers:
        return "unavailable"
    if len(providers) == 1:
        return next(iter(providers))
    return "mixed"


def _summarize_flash_classification_model(items: list[dict[str, Any]]) -> str | None:
    models = {str(item.get("classification_model") or "") for item in items}
    models.discard("")
    if not models:
        return None
    if len(models) == 1:
        return next(iter(models))
    return "mixed"


def _persist_flash_to_db(annotated_items: list[dict[str, Any]]) -> None:
    """将分类后的 Jin10 快讯持久化到 DB，触发分析任务。"""
    try:
        from apps.scheduler.flash_persistence import persist_flash_items, dispatch_pending_flash_analysis
        from database.models.engine import SessionLocal

        with SessionLocal() as session:
            result = persist_flash_items(session, annotated_items)
            if result["key_events"] > 0:
                dispatch_pending_flash_analysis(session)
            logger.info(
                "Flash persisted: new=%d skipped=%d key_events=%d",
                result["new"], result["skipped"], result["key_events"],
            )
    except Exception as exc:
        logger.warning("Failed to persist flash messages: %s", exc)
