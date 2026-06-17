"""统一数据服务层 — OpenBB / Jin10 MCP 双源兜底。

用法：
    from apps.data_layer import MacroDataService, NewsDataService

    macro = MacroDataService(storage_root=Path("storage"))
    rates = macro.collect_fred_rates()
    prices = macro.collect_market_prices()

    news = NewsDataService(storage_root=Path("storage"))
    all_news = news.collect_all()
"""

from apps.data_layer.models import DualSourceResult
from apps.data_layer.service import MacroDataService, NewsDataService

__all__ = [
    "DualSourceResult",
    "MacroDataService",
    "NewsDataService",
]
