"""Compatibility entry point for the BLS Employment collector."""

from apps.collectors.bls.employment import (
    BLS_API_BASE_URL,
    BLS_CACHE_MAX_AGE_DAYS,
    BLS_DEFAULT_REQUEST_TIMEOUT_SECONDS,
    BLS_EMPLOYMENT_SERIES,
    BLS_INDUSTRY_SERIES,
    BLS_FRED_MIRROR_SYMBOLS,
    BLS_SERIES,
    BLS_SOURCE,
    FRED_GRAPH_CSV_URL,
    FRED_API_MIRROR_KIND,
    FRED_MIRROR_KIND,
    FRED_MIRROR_SOURCE,
    bls_batch_url,
    bls_series_url,
    collect_bls_employment,
    collect_bls_series_from_payload,
)

__all__ = [
    "BLS_API_BASE_URL",
    "BLS_CACHE_MAX_AGE_DAYS",
    "BLS_DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "BLS_EMPLOYMENT_SERIES",
    "BLS_INDUSTRY_SERIES",
    "BLS_FRED_MIRROR_SYMBOLS",
    "BLS_SERIES",
    "BLS_SOURCE",
    "FRED_GRAPH_CSV_URL",
    "FRED_API_MIRROR_KIND",
    "FRED_MIRROR_KIND",
    "FRED_MIRROR_SOURCE",
    "bls_batch_url",
    "bls_series_url",
    "collect_bls_employment",
    "collect_bls_series_from_payload",
]
