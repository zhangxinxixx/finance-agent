"""Unified Jin10 MCP client for all collectors.

Provides a shared HTTP session with MCP handshake and tool-call helpers
so every collector (quotes, kline, articles, news) reuses the same
transport layer. MCP key is read from ``JIN10_MCP_KEY`` env var.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from apps.runtime.secret_resolver import resolve_runtime_secret

logger = logging.getLogger(__name__)

JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
JIN10_MCP_KEY_ENV = "JIN10_MCP_KEY"


class Jin10MCPClient:
    """Shared Jin10 MCP HTTP client.

    Reuses the same session and MCP session ID across tool calls.
    Thread-safe for sequential use; not designed for concurrent use.
    """

    def __init__(self, mcp_key: str | None = None, timeout: float = 30.0):
        self._mcp_key = mcp_key or resolve_runtime_secret(JIN10_MCP_KEY_ENV)
        if not self._mcp_key:
            raise RuntimeError(
                f"Jin10 MCP key not set. Provide ``mcp_key`` or set ${JIN10_MCP_KEY_ENV}"
            )

        import httpx
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "finance-agent/0.2"},
        )
        self._session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ── Session lifecycle ──────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """Build request headers with MCP session."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._mcp_key}",
            "Mcp-Session-Id": self._session_id or "",
        }

    def connect(self) -> bool:
        """Perform MCP initialize handshake. Returns True on success."""
        if self._session_id:
            return True
        try:
            init_r = self._client.post(
                JIN10_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "finance-agent", "version": "0.2"},
                    },
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._mcp_key}",
                },
            )
            sid = init_r.headers.get("Mcp-Session-Id", "")
            if not sid:
                logger.warning("Jin10 MCP handshake: no session ID returned")
                return False
            self._session_id = sid
            # Send initialized notification
            self._client.post(
                JIN10_MCP_URL,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._mcp_key}",
                    "Mcp-Session-Id": sid,
                },
            )
            logger.info("Jin10 MCP connected, session=%s", self._session_id[:12])
            return True
        except Exception as exc:
            logger.exception("Jin10 MCP handshake failed: %s", exc)
            return False

    def close(self):
        """Close the HTTP session."""
        self._client.close()
        self._session_id = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    # ── Tool calls ─────────────────────────────────────────────────

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        retries: int = 3,
    ) -> dict[str, Any]:
        """Call an MCP tool and return structuredContent.

        Args:
            tool_name: MCP tool name (e.g. 'get_quote', 'get_kline')
            arguments: Tool arguments dict
            retries: Number of retry attempts

        Returns:
            StructuredContent dict (empty dict on failure)
        """
        if not self._session_id:
            if not self.connect():
                return {}

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self._client.post(
                    JIN10_MCP_URL,
                    json={
                        "jsonrpc": "2.0",
                        "id": 99,
                        "method": "tools/call",
                        "params": {
                            "name": tool_name,
                            "arguments": arguments or {},
                        },
                    },
                    headers=self._headers(),
                )
                result = _parse_sse_result(resp.text)
                if result is None:
                    raise RuntimeError(f"Failed to parse SSE for {tool_name}")
                sc = result.get("structuredContent", {})
                if isinstance(sc, dict):
                    status = sc.get("status")
                    if status and status != 200:
                        raise RuntimeError(
                            f"{tool_name} returned status={status}: {sc.get('message', '')}"
                        )
                    return sc
                return {}
            except Exception as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(0.5 * (attempt + 1))
        if last_exc is not None:
            logger.warning("Jin10 tool %s failed after %d retries: %s", tool_name, retries, last_exc)
        return {}

    def call_tool_raw(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        retries: int = 2,
    ) -> dict[str, Any] | None:
        """Call a tool and return the full result dict (not just structuredContent)."""
        if not self._session_id:
            if not self.connect():
                return None

        for attempt in range(retries):
            try:
                resp = self._client.post(
                    JIN10_MCP_URL,
                    json={
                        "jsonrpc": "2.0",
                        "id": 99,
                        "method": "tools/call",
                        "params": {
                            "name": tool_name,
                            "arguments": arguments or {},
                        },
                    },
                    headers=self._headers(),
                )
                return _parse_sse_result(resp.text)
            except Exception as exc:
                if attempt >= retries - 1:
                    logger.warning("Jin10 raw %s failed: %s", tool_name, exc)
        return None

    # ── High-level convenience methods ──────────────────────────────

    def get_quote(self, code: str) -> dict[str, Any]:
        """Get real-time quote for a symbol code (e.g. 'XAUUSD')."""
        return self.call_tool("get_quote", {"code": code})

    def get_kline(
        self,
        code: str,
        time_stamp: int | None = None,
        count: int = 50,
    ) -> dict[str, Any]:
        """Get minute-level K-line data.

        Args:
            code: Symbol code (e.g. 'XAUUSD')
            time_stamp: Unix timestamp to start from (default: now)
            count: Number of candles (1-100)
        """
        args: dict[str, Any] = {"code": code, "count": min(count, 100)}
        if time_stamp is not None:
            args["time"] = time_stamp
        return self.call_tool("get_kline", args)

    def list_calendar(self) -> dict[str, Any]:
        """Get weekly economic calendar."""
        return self.call_tool("list_calendar", {})

    def list_flash(self, cursor: str | None = None) -> dict[str, Any]:
        """Get flash news by cursor."""
        args: dict[str, Any] = {}
        if cursor:
            args["cursor"] = cursor
        return self.call_tool("list_flash", args)

    def search_flash(self, keyword: str) -> dict[str, Any]:
        """Search flash news by keyword."""
        return self.call_tool("search_flash", {"keyword": keyword})

    def list_news(self, cursor: str | None = None) -> dict[str, Any]:
        """Get article list by cursor."""
        args: dict[str, Any] = {}
        if cursor:
            args["cursor"] = cursor
        return self.call_tool("list_news", args)

    def search_news(self, keyword: str, cursor: str | None = None) -> dict[str, Any]:
        """Search articles by keyword."""
        args: dict[str, Any] = {"keyword": keyword}
        if cursor:
            args["cursor"] = cursor
        return self.call_tool("search_news", args)

    def get_news(self, article_id: str) -> dict[str, Any]:
        """Get full article by ID."""
        return self.call_tool("get_news", {"id": article_id})


# ── SSE parsing (copied from news collector) ────────────────────────────


def _parse_sse_result(response_text: str) -> dict[str, Any] | None:
    """Parse MCP SSE response, extracting the final JSON result."""
    lines = response_text.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        # SSE data: prefix
        if line.startswith("data: "):
            payload = line[len("data: "):]
            try:
                data = json.loads(payload)
                if isinstance(data, dict) and "result" in data:
                    return data["result"]
            except (json.JSONDecodeError, TypeError):
                continue
    # Fallback: try raw JSON
    try:
        data = json.loads(response_text)
        if isinstance(data, dict):
            return data.get("result", data)
    except (json.JSONDecodeError, TypeError):
        pass
    return None
