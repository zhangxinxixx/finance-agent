"""OpenBB 数据采集器。

基于 OpenBB SDK 的补充型数据采集，提供 FRED 宏观利率和 yfinance 市场价格代理。
不作为主数据源 — 用于 fallback、cross-check 和辅助输入。
"""

from __future__ import annotations

from apps.collectors.openbb.collector import (
    FRED_RATE_SYMBOLS,
    MARKET_PRICE_SYMBOLS,
    collect_fred_rates_via_openbb,
    collect_market_prices_via_openbb,
)

__all__ = [
    "FRED_RATE_SYMBOLS",
    "MARKET_PRICE_SYMBOLS",
    "collect_fred_rates_via_openbb",
    "collect_market_prices_via_openbb",
]
