"""Collectors for official ETF data sources."""

from apps.collectors.etf.official_gld import (
    GLD_HISTORICAL_ARCHIVE_URL,
    GLD_NAV_HISTORY_URL,
    collect_official_gld,
)

__all__ = ["GLD_HISTORICAL_ARCHIVE_URL", "GLD_NAV_HISTORY_URL", "collect_official_gld"]
