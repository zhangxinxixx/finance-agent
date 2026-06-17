"""News collector via Jin10 MCP — economic calendar + flash headlines.

Connects to the Jin10 MCP server for:
- ``list_calendar``  → recent economic events with star ratings
- ``list_flash``     → latest 20 breaking news headlines
- ``search_flash``   → gold-related and Fed-related flash headlines

Produces ``CollectorResult`` with ``MacroPoint`` entries keyed by symbol
prefixes ``NEWS_EVENT:`` and ``NEWS_FLASH`` for downstream processing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from apps.runtime.secret_resolver import resolve_runtime_secret
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
JIN10_MCP_KEY_ENV = "JIN10_MCP_KEY"
JIN10_MCP_CALENDAR_SOURCE_KEY = "jin10_mcp_calendar"
JIN10_MCP_FLASH_SOURCE_KEY = "jin10_mcp_flash"


def collect_news(
    *,
    retrieved_date: str,
    storage_root: Path,
    mcp_key: str | None = None,
) -> CollectorResult:
    """Collect economic calendar and flash headlines via Jin10 MCP.

    Returns a ``CollectorResult`` with:
    - Calendar events as ``MacroPoint`` entries (symbol="NEWS_EVENT:<title>", value=star)
    - Flash headlines as ``MacroPoint`` entries (symbol="NEWS_FLASH", value=0.0)
    """
    mcp_key = mcp_key or resolve_runtime_secret(JIN10_MCP_KEY_ENV)
    if not mcp_key:
        raise RuntimeError(
            f"Jin10 MCP key not set. Provide ``mcp_key`` or set ${JIN10_MCP_KEY_ENV}"
        )

    import httpx

    points: list[MacroPoint] = []
    unavailable: list[str] = []
    refs: list[dict[str, str]] = []

    with httpx.Client(timeout=30.0, headers={"User-Agent": "finance-agent/0.1"}) as client:
        # ── MCP session handshake ──────────────────────────────────────
        sid = _mcp_handshake(client, mcp_key)
        if not sid:
            return CollectorResult(
                points=[], unavailable_symbols=["JIN10_MCP_HANDSHAKE"], source_refs=[]
            )

        # ── list_calendar ──────────────────────────────────────────────
        try:
            cal_payload = _mcp_tool_call(client, mcp_key, sid, "list_calendar", {})
            cal_raw_path = archive_raw_payload(
                storage_root=storage_root,
                source="jin10_mcp",
                retrieved_date=retrieved_date,
                symbol="calendar",
                payload=cal_payload,
            )
            cal_ref = _make_ref(
                "jin10_mcp",
                "list_calendar",
                cal_raw_path,
                source_key=JIN10_MCP_CALENDAR_SOURCE_KEY,
            )
            refs.append(cal_ref)

            events = _extract_calendar_events(cal_payload)
            retrieved_at = utc_now_iso()
            for event in events:
                points.append(MacroPoint(
                    symbol=f"NEWS_EVENT:{event['title']}",
                    date=event["pub_time"],
                    value=float(event["star"]),
                    source="jin10_mcp",
                    source_url=cal_ref["raw_path"],
                    retrieved_at=retrieved_at,
                    raw_path=cal_raw_path,
                ))
        except Exception as exc:
            unavailable.append("NEWS_CALENDAR")
            refs.append({
                "source": "jin10_mcp",
                "source_key": JIN10_MCP_CALENDAR_SOURCE_KEY,
                "method": "list_calendar",
                "reason": f"{type(exc).__name__}: {exc}",
            })

        # ── list_flash (latest 20 headlines) ───────────────────────────
        try:
            flash_payload = _mcp_tool_call(
                client, mcp_key, sid, "list_flash", {}
            )
            flash_raw_path = archive_raw_payload(
                storage_root=storage_root,
                source="jin10_mcp",
                retrieved_date=retrieved_date,
                symbol="flash_latest",
                payload=flash_payload,
            )
            flash_ref = _make_ref(
                "jin10_mcp",
                "list_flash",
                flash_raw_path,
                source_key=JIN10_MCP_FLASH_SOURCE_KEY,
            )
            refs.append(flash_ref)

            _add_flash_points(points, flash_payload, flash_raw_path)
        except Exception as exc:
            refs.append({
                "source": "jin10_mcp",
                "source_key": JIN10_MCP_FLASH_SOURCE_KEY,
                "method": "list_flash",
                "reason": f"{type(exc).__name__}: {exc}",
            })

        # ── search_flash for gold-related ──────────────────────────────
        try:
            gold_payload = _mcp_tool_call(
                client, mcp_key, sid, "search_flash", {"keyword": "黄金"}
            )
            gold_raw_path = archive_raw_payload(
                storage_root=storage_root,
                source="jin10_mcp",
                retrieved_date=retrieved_date,
                symbol="flash_gold",
                payload=gold_payload,
            )
            gold_ref = _make_ref(
                "jin10_mcp",
                "search_flash:黄金",
                gold_raw_path,
                source_key=JIN10_MCP_FLASH_SOURCE_KEY,
            )
            refs.append(gold_ref)

            _add_flash_points(points, gold_payload, gold_raw_path)
        except Exception as exc:
            refs.append({
                "source": "jin10_mcp",
                "source_key": JIN10_MCP_FLASH_SOURCE_KEY,
                "method": "search_flash:黄金",
                "reason": f"{type(exc).__name__}: {exc}",
            })

        # ── search_flash for Fed-related ───────────────────────────────
        try:
            fed_payload = _mcp_tool_call(
                client, mcp_key, sid, "search_flash", {"keyword": "美联储"}
            )
            fed_raw_path = archive_raw_payload(
                storage_root=storage_root,
                source="jin10_mcp",
                retrieved_date=retrieved_date,
                symbol="flash_fed",
                payload=fed_payload,
            )
            fed_ref = _make_ref(
                "jin10_mcp",
                "search_flash:美联储",
                fed_raw_path,
                source_key=JIN10_MCP_FLASH_SOURCE_KEY,
            )
            refs.append(fed_ref)

            _add_flash_points(points, fed_payload, fed_raw_path)
        except Exception as exc:
            refs.append({
                "source": "jin10_mcp",
                "source_key": JIN10_MCP_FLASH_SOURCE_KEY,
                "method": "search_flash:美联储",
                "reason": f"{type(exc).__name__}: {exc}",
            })

    if not any(p.symbol == "NEWS_FLASH" for p in points):
        unavailable.append("NEWS_FLASH")

    return CollectorResult(points=points, unavailable_symbols=unavailable, source_refs=refs)


# ── MCP protocol helpers ──────────────────────────────────────────────────────


def _mcp_handshake(client, mcp_key: str) -> str:
    """Perform MCP initialize handshake, return session ID."""
    init_r = client.post(
        JIN10_MCP_URL,
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
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {mcp_key}"},
    )
    sid = init_r.headers.get("Mcp-Session-Id", "")
    if not sid:
        return ""
    # Send initialized notification
    client.post(
        JIN10_MCP_URL,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {mcp_key}",
            "Mcp-Session-Id": sid,
        },
    )
    return sid


def _mcp_tool_call(
    client, mcp_key: str, sid: str, tool_name: str, arguments: dict[str, Any]
):
    """Call an MCP tool and return the structuredContent."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = client.post(
                JIN10_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {mcp_key}",
                    "Mcp-Session-Id": sid,
                },
            )
            result = _parse_sse_result(resp.text)
            if result is None:
                raise RuntimeError(f"Failed to parse SSE for {tool_name}")
            sc = result.get("structuredContent", {})
            if isinstance(sc, dict):
                status = sc.get("status")
                if status and status != 200:
                    raise RuntimeError(f"{tool_name} returned status={status}: {sc.get('message','')}")
                return sc
            return {}
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{tool_name} failed without exception")


def _parse_sse_result(text: str) -> dict[str, Any] | None:
    """Parse SSE-streamed MCP response."""
    for line in text.split("\n"):
        if line.startswith("data:"):
            data = json.loads(line[5:])
            return data.get("result")
    return None


# ── Data extraction helpers ───────────────────────────────────────────────────


def _extract_calendar_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract calendar events from list_calendar response."""
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    events: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        star = item.get("star")
        if star is None or int(star) < 2:
            continue  # skip low-importance events
        events.append({
            "title": str(item.get("title", "")),
            "pub_time": str(item.get("pub_time", "")),
            "star": int(star),
            "actual": str(item.get("actual", "")),
            "consensus": str(item.get("consensus", "")),
            "previous": str(item.get("previous", "")),
            "affect_txt": str(item.get("affect_txt", "")),
        })
    return events


def _add_flash_points(
    points: list[MacroPoint],
    payload: dict[str, Any],
    raw_path: str,
) -> None:
    """Extract flash headlines from a flash payload and append MacroPoints."""
    items = payload.get("data", {}).get("items", [])
    if not isinstance(items, list):
        return
    retrieved_at = utc_now_iso()
    for item in items:
        if not isinstance(item, dict):
            continue
        time_str = str(item.get("time", ""))
        points.append(MacroPoint(
            symbol="NEWS_FLASH",
            date=time_str,
            value=0.0,
            source="jin10_mcp",
            source_url=str(item.get("url", "")),
            retrieved_at=retrieved_at,
            raw_path=raw_path,
        ))


def _make_ref(source: str, method: str, raw_path: str, *, source_key: str | None = None) -> dict[str, str]:
    ref = {"source": source, "method": method, "raw_path": raw_path}
    if source_key:
        ref["source_key"] = source_key
    return ref
