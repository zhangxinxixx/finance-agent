"""Scanner plus bounded chart history, consumed by the existing research TaskStep."""

from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor

from apps.collectors.market.tradingview import collect_tradingview
from apps.collectors.market.tradingview_chart import collect_tradingview_chart
from apps.parsers.market.tradingview import CORE_INSTRUMENTS


def collect_tradingview_research(*, retrieved_date, storage_root, symbols=None, resolution="15",
                                scanner_collector=collect_tradingview, chart_collector=collect_tradingview_chart):
    requested = tuple(CORE_INSTRUMENTS) if symbols is None else tuple(dict.fromkeys(symbols))
    if not requested or len(requested) > 8:
        raise ValueError("TradingView research requires 1 to 8 symbols")
    if resolution not in {"1", "15", "60"}:
        raise ValueError("unsupported research resolution")
    # Include a gold anchor for targeted supplementary research, within the same request budget.
    chart_symbols = tuple(dict.fromkeys(("OANDA:XAUUSD", *requested)))
    if len(chart_symbols) > 8:
        raise ValueError("chart symbol budget exceeded including gold anchor")
    scanner = scanner_collector(retrieved_date=retrieved_date, storage_root=storage_root, symbols=requested)
    chart = chart_collector(retrieved_date=retrieved_date, storage_root=storage_root,
                            symbols=chart_symbols, resolution=resolution,
                            bar_count=256)
    # Baseline PA uses provider-native bars, not scanner quotes or resampled
    # intraday prices. Targeted adaptive requests keep their existing budget.
    execution_charts = [chart]
    if symbols is None:
        def collect_frame(period):
            return chart_collector(retrieved_date=retrieved_date, storage_root=storage_root,
                                   symbols=("OANDA:XAUUSD",), resolution=period, bar_count=256)
        with ThreadPoolExecutor(max_workers=2) as executor:
            execution_charts.extend(executor.map(collect_frame, ("60", "240")))
    return {**scanner, "retrieved_at": datetime.now(UTC).isoformat(),
            "chart_series": chart["series"], "chart_parsed_path": chart["parsed_path"],
            "execution_chart_series": [s for c in execution_charts for s in c["series"]
                                       if s.get("ticker") == "OANDA:XAUUSD"],
            "source_refs": [*scanner.get("source_refs", []),
                            *(ref for c in execution_charts for ref in c.get("source_refs", []))]}
