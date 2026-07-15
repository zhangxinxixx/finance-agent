"""统一数据服务层 — 复用已有 collector，提供双源兜底。

MacroDataService：FRED 利率 + 市场价格代理
  - 主源 OpenBB，备用源 Jin10 MCP
  - 每个 category 内部 double-fallback：先主源，失败再备用

NewsDataService：经济日历 + 快讯
  - 主源 Jin10 MCP，备用源 OpenBB（新闻部分）

均不新增 CollectorResult 契约，输出统一 DualSourceResult。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from apps.runtime.secret_resolver import resolve_runtime_secret
from apps.data_layer.models import DualSourceResult
from apps.parsers.macro.models import CollectorResult, MacroPoint


class MacroDataService:
    """宏观数据服务 — FRED 利率 + 市场价格代理，OpenBB/Jin10 双兜底。"""

    def __init__(self, storage_root: Path, env_file: Path | None = None):
        self.storage_root = Path(storage_root)
        self.env_file = env_file

    def collect_fred_rates(
        self,
        *,
        retrieved_date: str | None = None,
        symbols: tuple[str, ...] | None = None,
    ) -> DualSourceResult:
        """采集 FRED 宏观利率。

        优先 OpenBB FRED（需 FRED_API_KEY），失败则尝试 Jin10 行情兜底。
        """
        retrieved_date = retrieved_date or date.today().isoformat()
        symbols = symbols or DEFAULT_FRED_RATE_SYMBOLS

        from apps.collectors.openbb.collector import collect_fred_rates_via_openbb

        # 1. 主源：OpenBB FRED
        result = collect_fred_rates_via_openbb(
            retrieved_date=retrieved_date,
            storage_root=self.storage_root,
            symbols=tuple(symbols),
            env_file=self.env_file,
        )

        if result.points:
            return DualSourceResult(
                points=result.points,
                source_used="openbb",
                unavailable_symbols=result.unavailable_symbols,
                source_refs=result.source_refs,
            )

        # 2. 备用源：Jin10 行情
        jin10 = self._try_jin10_rates(symbols, retrieved_date, result.source_refs)
        if jin10 is not None:
            return jin10

        # 3. 双源都失败
        return DualSourceResult(
            points=[],
            source_used=None,
            unavailable_symbols=list(symbols),
            source_refs=result.source_refs,
            warnings=["FRED 利率：OpenBB 和 Jin10 均不可用"],
        )

    def collect_market_prices(
        self,
        *,
        retrieved_date: str | None = None,
        symbols: dict[str, str] | None = None,
        lookback_days: int = 180,
    ) -> DualSourceResult:
        """采集市场价格代理。

        优先 OpenBB/yfinance，失败则尝试 Jin10 行情兜底。
        """
        retrieved_date = retrieved_date or date.today().isoformat()
        symbols = symbols or _DEFAULT_PRICE_SYMBOLS

        from apps.collectors.openbb.collector import collect_market_prices_via_openbb

        # 1. 主源：OpenBB yfinance
        result = collect_market_prices_via_openbb(
            retrieved_date=retrieved_date,
            storage_root=self.storage_root,
            symbols=dict(symbols),
            env_file=self.env_file,
            lookback_days=lookback_days,
        )

        if result.points:
            return DualSourceResult(
                points=result.points,
                source_used="openbb",
                unavailable_symbols=result.unavailable_symbols,
                source_refs=result.source_refs,
            )

        # 2. 备用源：Jin10 行情
        jin10 = self._try_jin10_prices(
            list(symbols.keys()), retrieved_date, result.source_refs
        )
        if jin10 is not None:
            return jin10

        return DualSourceResult(
            points=[],
            source_used=None,
            unavailable_symbols=list(symbols.keys()),
            source_refs=result.source_refs,
            warnings=["市场价格：OpenBB 和 Jin10 均不可用"],
        )

    # ── Jin10 fallback helpers ──────────────────────────────────────────

    def _try_jin10_rates(
        self,
        symbols: tuple[str, ...],
        retrieved_date: str,
        openbb_refs: list[dict[str, str]],
    ) -> DualSourceResult | None:
        """尝试通过 Jin10 获取利率 proxy。"""
        jin10_symbols = _fred_to_jin10_map(symbols)
        if not jin10_symbols:
            return None

        jin10_result = self._jin10_quote_collect(
            jin10_symbols, retrieved_date, "rates"
        )
        if jin10_result is None or not jin10_result.points:
            return None

        return DualSourceResult(
            points=jin10_result.points,
            source_used="jin10",
            unavailable_symbols=jin10_result.unavailable_symbols,
            source_refs=[*openbb_refs, *jin10_result.source_refs],
            warnings=["FRED 利率：OpenBB 不可用，使用 Jin10 行情兜底"],
        )

    def _try_jin10_prices(
        self,
        symbols: list[str],
        retrieved_date: str,
        openbb_refs: list[dict[str, str]],
    ) -> DualSourceResult | None:
        """尝试通过 Jin10 获取价格兜底。"""
        jin10_symbols = _price_to_jin10_map(symbols)
        if not jin10_symbols:
            return None

        jin10_result = self._jin10_quote_collect(
            jin10_symbols, retrieved_date, "prices"
        )
        if jin10_result is None or not jin10_result.points:
            return None

        return DualSourceResult(
            points=jin10_result.points,
            source_used="jin10",
            unavailable_symbols=jin10_result.unavailable_symbols,
            source_refs=[*openbb_refs, *jin10_result.source_refs],
            warnings=["市场价格：OpenBB/yfinance 不可用，使用 Jin10 行情兜底"],
        )

    def _jin10_quote_collect(
        self,
        codes: list[str],
        retrieved_date: str,
        label: str,
    ) -> CollectorResult | None:
        """通过 Jin10 MCP HTTP 接口获取行情 → CollectorResult。"""
        import httpx

        mcp_key = resolve_runtime_secret("JIN10_MCP_KEY")
        if not mcp_key:
            return None

        from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

        points: list[MacroPoint] = []
        unavailable: list[str] = []
        refs: list[dict[str, str]] = []

        try:
            with httpx.Client(timeout=30.0) as client:
                sid = self._mcp_handshake(client, mcp_key)
                if not sid:
                    return None

                for code in codes:
                    try:
                        payload = self._mcp_tool_call(
                            client, mcp_key, sid, "get_quote", {"code": code}
                        )
                    except Exception:
                        unavailable.append(code)
                        continue

                    raw_path = archive_raw_payload(
                        storage_root=self.storage_root,
                        source="jin10_mcp",
                        retrieved_date=retrieved_date,
                        symbol=code,
                        payload=payload,
                    )
                    refs.append({"symbol": code, "source": "jin10_mcp", "raw_path": raw_path, "type": label})

                    try:
                        data = _extract_quote_value(payload)
                        if data is None:
                            unavailable.append(code)
                            continue
                        points.append(
                            MacroPoint(
                                symbol=code,
                                date=retrieved_date,
                                value=data["price"],
                                source="jin10_mcp",
                                source_url=f"jin10://quote/{code}",
                                retrieved_at=utc_now_iso(),
                                raw_path=raw_path,
                            )
                        )
                    except Exception:
                        unavailable.append(code)
        except Exception:
            return None

        return CollectorResult(
            points=points,
            unavailable_symbols=unavailable,
            source_refs=refs,
        )

    @staticmethod
    def _mcp_handshake(client, mcp_key: str) -> str | None:
        """Jin10 MCP 握手，返回 session_id。"""
        import uuid

        try:
            init_resp = client.post(
                "https://mcp.jin10.com/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "finance-agent", "version": "0.1"},
                    },
                    "id": str(uuid.uuid4()),
                },
                headers={
                    "Authorization": f"Bearer {mcp_key}",
                    "Content-Type": "application/json",
                },
            )
            init_resp.raise_for_status()
            init_data = init_resp.json()
            sid = None
            if "result" in init_data:
                sid = init_data["result"].get("sessionId")
            # Send initialized notification
            client.post(
                "https://mcp.jin10.com/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Authorization": f"Bearer {mcp_key}"},
            )
            return sid
        except Exception:
            return None

    @staticmethod
    def _mcp_tool_call(client, mcp_key: str, sid: str, tool: str, args: dict) -> dict:
        """调用 Jin10 MCP 工具。"""
        import json
        import uuid

        resp = client.post(
            "https://mcp.jin10.com/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool, "arguments": args},
                "id": str(uuid.uuid4()),
            },
            headers={
                "Authorization": f"Bearer {mcp_key}",
                "Content-Type": "application/json",
                "Mcp-Session-Id": sid,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        content = result.get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return json.loads(item["text"])
        return result


class NewsDataService:
    """新闻数据服务 — 经济日历 + 快讯，Jin10 MCP 为主，OpenBB 为辅。"""

    def __init__(self, storage_root: Path, env_file: Path | None = None):
        self.storage_root = Path(storage_root)
        self.env_file = env_file

    def collect_all(
        self,
        *,
        retrieved_date: str | None = None,
    ) -> DualSourceResult:
        """采集新闻 + 日历 — Jin10 主源，失败则尝试 OpenBB。"""
        retrieved_date = retrieved_date or date.today().isoformat()

        # 1. 主源：Jin10 MCP
        from apps.collectors.news.collector import collect_news

        try:
            result = collect_news(
                retrieved_date=retrieved_date,
                storage_root=self.storage_root,
            )
        except Exception:
            result = CollectorResult(points=[], unavailable_symbols=["JIN10_MCP"], source_refs=[])

        if result.points:
            return DualSourceResult(
                points=result.points,
                source_used="jin10",
                unavailable_symbols=result.unavailable_symbols,
                source_refs=result.source_refs,
            )

        # 2. 备用：OpenBB 新闻
        obb = self._try_openbb_news(retrieved_date, result.source_refs)
        if obb is not None:
            return obb

        return DualSourceResult(
            points=[],
            source_used=None,
            unavailable_symbols=["NEWS_ALL"],
            source_refs=result.source_refs,
            warnings=["新闻：Jin10 和 OpenBB 均不可用"],
        )

    def collect_flash(self, *, keyword: str | None = None) -> DualSourceResult:
        """采集快讯 — Jin10 专用。"""
        # 快讯只有 Jin10 MCP 支持，不设兜底
        from apps.collectors.news.collector import collect_news

        try:
            result = collect_news(
                retrieved_date=date.today().isoformat(),
                storage_root=self.storage_root,
            )
        except Exception:
            return DualSourceResult(
                unavailable_symbols=["FLASH"],
                source_refs=[],
                warnings=["快讯采集失败：Jin10 MCP 不可用"],
            )

        return DualSourceResult(
            points=result.points,
            source_used="jin10",
            unavailable_symbols=result.unavailable_symbols,
            source_refs=result.source_refs,
        )

    def _try_openbb_news(
        self, retrieved_date: str, jin10_refs: list[dict[str, str]]
    ) -> DualSourceResult | None:
        """尝试 OpenBB yfinance 获取 GLD 相关新闻兜底。"""
        from apps.collectors.openbb.collector import _load_env
        _load_env(self.env_file)
        from openbb import obb
        from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

        points: list[MacroPoint] = []
        refs: list[dict[str, str]] = [*jin10_refs]

        try:
            result = obb.news.company(
                symbol="GLD",
                provider="yfinance",
                limit=5,
            )
            df = result.to_df()
        except Exception:
            return None

        if df is None or df.empty:
            return None

        raw_path = archive_raw_payload(
            storage_root=self.storage_root,
            source="openbb_news",
            retrieved_date=retrieved_date,
            symbol="GLD",
            payload={"columns": list(df.columns), "row_count": len(df), "latest": df.head(5).to_dict("records")},
        )
        refs.append({"source": "openbb_news", "symbol": "GLD", "raw_path": raw_path})

        try:
            for _, row in df.iterrows():
                title = str(row.get("title", "") or row.iloc[1] or "")[:200]
                points.append(
                    MacroPoint(
                        symbol=f"NEWS_OB:{title}",
                        date=retrieved_date,
                        value=0.0,
                        source="openbb_news",
                        source_url="https://finance.yahoo.com/quote/GLD",
                        retrieved_at=utc_now_iso(),
                        raw_path=raw_path,
                    )
                )
        except Exception:
            return None

        if points:
            return DualSourceResult(
                points=points,
                source_used="openbb",
                unavailable_symbols=[],
                source_refs=refs,
                warnings=["新闻：Jin10 不可用，使用 OpenBB/yfinance 兜底"],
            )
        return None


# ── Default symbols ────────────────────────────────────────────────────

DEFAULT_FRED_RATE_SYMBOLS: tuple[str, ...] = (
    "DGS10", "DGS2", "DGS3MO", "DGS30", "DFII10", "DFII5",
    "FEDFUNDS", "SOFR", "T10Y2Y", "T10YIE",
)

_DEFAULT_PRICE_SYMBOLS: dict[str, str] = {
    "DX-Y.NYB": "index",
    "SPY": "equity",
    "TLT": "equity",
    "GDX": "equity",
    "SLV": "equity",
    "^VIX": "index",
}

# ── Symbol mapping: FRED → Jin10 codes ─────────────────────────────────

def _fred_to_jin10_map(symbols: tuple[str, ...]) -> list[str]:
    """FRED symbol → Jin10 quote code 映射。"""
    mapping = {
        "DGS10": "US10YR",   # 10Y Treasury yield
        "DGS2": "US02YR",    # 2Y Treasury yield
        "DXY": "USDOLLAR",   # Dollar index
    }
    return [mapping[s] for s in symbols if s in mapping]


def _price_to_jin10_map(symbols: list[str]) -> list[str]:
    """市场价格 symbol → Jin10 quote code 映射。"""
    mapping = {
        "DX-Y.NYB": "USDOLLAR",
        "SPY": "SPX500",
        "^VIX": "VIX",
    }
    return [mapping[s] for s in symbols if s in mapping]


def _extract_quote_value(payload: dict) -> dict | None:
    """从 Jin10 get_quote 响应中提取价格。"""
    data = payload.get("data") or payload
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None
    price = data.get("price") or data.get("close") or data.get("last")
    if price is None:
        return None
    return {"price": float(price)}
