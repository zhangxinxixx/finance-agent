from __future__ import annotations

from pathlib import Path

from apps.parsers.macro.models import CollectorResult

DISPLAY_SYMBOL = "XAUUSD"


def collect_technical(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    """Return unavailable for the retired Jin10 numeric source."""
    return _collect_from_jin10_quote(retrieved_date=retrieved_date, storage_root=storage_root)


def _collect_from_jin10_quote(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    # No credentials, network calls or new numeric archives.
    return CollectorResult(points=[], unavailable_symbols=[DISPLAY_SYMBOL], source_refs=[{
        "symbol": DISPLAY_SYMBOL, "source": "jin10_quote", "status": "unavailable",
        "reason_code": "jin10_numeric_source_forbidden",
        "reason": "Jin10 is news/historical reading only; use a qualified numeric source",
    }])
