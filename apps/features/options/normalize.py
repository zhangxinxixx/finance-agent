"""CME option data normalization for analysis input.

Accepts rows from CmeOptionRow (ORM) or parser dataclass dicts and produces
NormalizedOptionRow records suitable for downstream Black-76 / wall analysis.

Important: this is for analysis input normalization only. DB ingest must
still reject parser duplicate bugs via its UniqueConstraint.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

@runtime_checkable
class _CmeOptionRowLike(Protocol):
    """Structural typing: anything that exposes the CmeOptionRow fields."""

    trade_date: str
    report_date: str
    product_code: str
    expiry: str
    strike: int
    option_type: str
    settlement: float | None
    delta: float | None
    open_interest: int | None
    oi_change: int | None
    total_volume: int | None
    block_volume: int | None
    pnt_volume: int | None
    globex_volume: int | None
    outcry_volume: int | None
    exercises: int | None
    pt_change: float | None


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NormalizedOptionRow:
    """Single normalized option row for analysis consumption."""

    trade_date: str               # YYYY-MM-DD
    report_date: str              # YYYY-MM-DD
    expiry: str                   # "JUN26"
    strike: int
    option_type: str              # "CALL" / "PUT"
    settlement: float | None
    delta: float | None           # Call positive; Put negative for DEX
    delta_raw: float | None       # Original delta (Put positive)
    open_interest: int
    oi_change: int
    total_volume: int
    block_volume: int
    pnt_volume: int
    globex_volume: int
    outcry_volume: int
    exercises: int
    pt_change: float | None
    source: str                   # "PRELIM" / "FINAL" / "UNKNOWN"
    data_quality: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizationReport:
    """Statistics produced alongside the normalized rows."""

    total_input_rows: int
    duplicates_merged: int        # rows eliminated by aggregation
    rows_missing_settlement: int
    rows_missing_delta: int
    rows_missing_oi: int
    rows_filtered_by_strike: int  # rows outside strike range
    warnings: list[str] = field(default_factory=list)
    data_quality_counts: dict[str, int] = field(default_factory=dict)
    """Per-category counts from per-row data_quality tags (zero_oi, low_oi,
    missing_settlement, missing_delta, prelim_data, etc.)."""


@dataclass(frozen=True)
class GroupedViews:
    """Call/put rows grouped by expiry and strike for quick lookup."""

    by_expiry: dict[str, list[NormalizedOptionRow]]
    call_by_expiry: dict[str, list[NormalizedOptionRow]]
    put_by_expiry: dict[str, list[NormalizedOptionRow]]
    by_expiry_strike: dict[str, dict[int, list[NormalizedOptionRow]]]


# ---------------------------------------------------------------------------
# Internal: extract scalar from ORM attr or dict key
# ---------------------------------------------------------------------------

def _get(row: Any, attr: str, default: Any = None) -> Any:
    """Read *attr* from an ORM object or dict."""
    if isinstance(row, dict):
        return row.get(attr, default)
    return getattr(row, attr, default)


# ---------------------------------------------------------------------------
# Duplicate aggregation key
# ---------------------------------------------------------------------------

def _agg_key(row: Any) -> tuple:
    return (
        _get(row, "trade_date"),
        _get(row, "expiry"),
        _get(row, "strike"),
        _get(row, "option_type"),
    )


def _safe_int(v: Any) -> int:
    if v is None:
        return 0
    return int(v)


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)


# ---------------------------------------------------------------------------
# OI-weighted mean helper
# ---------------------------------------------------------------------------

def _oi_weighted_mean(values: list[tuple[float, int]]) -> float | None:
    """Compute OI-weighted mean. Returns None if no valid data."""
    total_oi = 0
    weighted_sum = 0.0
    for val, oi in values:
        if val is None:
            continue
        total_oi += oi
        weighted_sum += val * oi
    if total_oi == 0:
        # fall back to simple mean of non-None values
        valid = [v for v, _ in values if v is not None]
        if not valid:
            return None
        return sum(valid) / len(valid)
    return weighted_sum / total_oi


# ---------------------------------------------------------------------------
# Core normalization
# ---------------------------------------------------------------------------

def normalize_option_rows(
    rows: list[Any],
    *,
    source: str = "UNKNOWN",
    strike_min: int = 3800,
    strike_max: int = 5000,
    filter_strikes: bool = True,
    aggregate_duplicates: bool = True,
) -> tuple[list[NormalizedOptionRow], NormalizationReport]:
    """Normalize a list of CmeOptionRow-like objects for analysis.

    Parameters
    ----------
    rows:
        CmeOptionRow ORM instances or dicts from parser dataclasses.
    source:
        "PRELIM" / "FINAL" — propagated to each normalized row.
    strike_min, strike_max:
        Inclusive strike filter bounds. Default 3800–5000 per rules doc.
    filter_strikes:
        If False, skip strike filtering entirely.
    aggregate_duplicates:
        If True, merge rows with identical (trade_date, expiry, strike,
        option_type) using sum for volumes/OI and OI-weighted mean for
        settlement/delta. This is for *analysis* aggregation only — DB
        ingest should still reject duplicates.

    Returns
    -------
    (normalized_rows, report)
    """
    total_input = len(rows)
    warnings: list[str] = []
    rows_filtered_by_strike = 0
    rows_missing_settlement = 0
    rows_missing_delta = 0
    rows_missing_oi = 0

    # -- Step 1: optionally filter by strike range --
    working = rows
    if filter_strikes:
        filtered = []
        for r in rows:
            strike = _get(r, "strike")
            if strike is not None and strike_min <= strike <= strike_max:
                filtered.append(r)
            else:
                rows_filtered_by_strike += 1
        working = filtered

    # -- Step 2: aggregate duplicates if requested --
    duplicates_merged = 0
    if aggregate_duplicates:
        groups: dict[tuple, list[Any]] = defaultdict(list)
        for r in working:
            groups[_agg_key(r)].append(r)

        merged: list[dict[str, Any]] = []
        for key, group in groups.items():
            if len(group) == 1:
                merged.append(_row_to_dict(group[0], source))
                continue

            # Multiple rows with same key — merge
            duplicates_merged += len(group) - 1

            total_oi = sum(_safe_int(_get(r, "open_interest")) for r in group)
            total_oi_change = sum(_safe_int(_get(r, "oi_change")) for r in group)
            total_vol = sum(_safe_int(_get(r, "total_volume")) for r in group)
            total_block = sum(_safe_int(_get(r, "block_volume")) for r in group)
            total_pnt = sum(_safe_int(_get(r, "pnt_volume")) for r in group)
            total_globex = sum(_safe_int(_get(r, "globex_volume")) for r in group)
            total_outcry = sum(_safe_int(_get(r, "outcry_volume")) for r in group)
            total_exercises = sum(_safe_int(_get(r, "exercises")) for r in group)

            # OI-weighted means for settlement and delta
            settlement_vals = [(_safe_float(_get(r, "settlement")), _safe_int(_get(r, "open_interest"))) for r in group]
            delta_vals = [(_safe_float(_get(r, "delta")), _safe_int(_get(r, "open_interest"))) for r in group]
            pt_vals = [(_safe_float(_get(r, "pt_change")), 1) for r in group if _get(r, "pt_change") is not None]

            merged_row = {
                "trade_date": key[0],
                "report_date": _get(group[0], "report_date"),
                "expiry": key[1],
                "strike": key[2],
                "option_type": key[3],
                "settlement": _oi_weighted_mean(settlement_vals),
                "delta": _oi_weighted_mean(delta_vals),
                "open_interest": total_oi,
                "oi_change": total_oi_change,
                "total_volume": total_vol,
                "block_volume": total_block,
                "pnt_volume": total_pnt,
                "globex_volume": total_globex,
                "outcry_volume": total_outcry,
                "exercises": total_exercises,
                "pt_change": _oi_weighted_mean(pt_vals) if pt_vals else None,
                "source": source,
                "_aggregated": len(group),
            }
            merged.append(merged_row)

        working_dicts = merged
    else:
        working_dicts = [_row_to_dict(r, source) for r in working]

    # -- Step 3: build NormalizedOptionRow with delta sign & quality flags --
    normalized: list[NormalizedOptionRow] = []
    for d in working_dicts:
        quality: list[str] = []

        raw_delta = _safe_float(d.get("delta"))
        settlement = _safe_float(d.get("settlement"))
        oi = _safe_int(d.get("open_interest"))

        if settlement is None:
            quality.append("missing_settlement")
            rows_missing_settlement += 1

        if raw_delta is None:
            quality.append("missing_delta")
            rows_missing_delta += 1

        if oi == 0:
            quality.append("zero_oi")
            rows_missing_oi += 1
        elif oi < 10:
            quality.append("low_oi")

        if source and source.upper().startswith("PRELIM"):
            quality.append("prelim_data")

        # Put delta: flip positive to negative for DEX
        option_type = d.get("option_type", "").upper()
        delta_for_dex = raw_delta
        if option_type == "PUT" and raw_delta is not None and raw_delta > 0:
            delta_for_dex = -raw_delta

        normalized.append(
            NormalizedOptionRow(
                trade_date=d.get("trade_date", ""),
                report_date=d.get("report_date", ""),
                expiry=d.get("expiry", ""),
                strike=d.get("strike", 0),
                option_type=option_type,
                settlement=settlement,
                delta=delta_for_dex,
                delta_raw=raw_delta,
                open_interest=oi,
                oi_change=_safe_int(d.get("oi_change")),
                total_volume=_safe_int(d.get("total_volume")),
                block_volume=_safe_int(d.get("block_volume")),
                pnt_volume=_safe_int(d.get("pnt_volume")),
                globex_volume=_safe_int(d.get("globex_volume")),
                outcry_volume=_safe_int(d.get("outcry_volume")),
                exercises=_safe_int(d.get("exercises")),
                pt_change=_safe_float(d.get("pt_change")),
                source=d.get("source", source),
                data_quality=quality,
            )
        )

    report = NormalizationReport(
        total_input_rows=total_input,
        duplicates_merged=duplicates_merged,
        rows_missing_settlement=rows_missing_settlement,
        rows_missing_delta=rows_missing_delta,
        rows_missing_oi=rows_missing_oi,
        rows_filtered_by_strike=rows_filtered_by_strike,
        warnings=warnings,
        data_quality_counts=_build_dq_counts(normalized),
    )

    return normalized, report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_dq_counts(normalized: list[NormalizedOptionRow]) -> dict[str, int]:
    """Aggregate per-row data_quality tags into category counts."""
    counts: dict[str, int] = {}
    for row in normalized:
        for tag in row.data_quality:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def _row_to_dict(row: Any, source: str) -> dict[str, Any]:
    """Convert an ORM object or dict to a plain dict for internal use."""
    if isinstance(row, dict):
        d = dict(row)
        if "source" not in d:
            d["source"] = source
        return d
    return {
        "trade_date": row.trade_date,
        "report_date": row.report_date,
        "expiry": row.expiry,
        "strike": row.strike,
        "option_type": row.option_type,
        "settlement": row.settlement,
        "delta": row.delta,
        "open_interest": row.open_interest,
        "oi_change": row.oi_change,
        "total_volume": row.total_volume,
        "block_volume": row.block_volume,
        "pnt_volume": row.pnt_volume,
        "globex_volume": row.globex_volume,
        "outcry_volume": row.outcry_volume,
        "exercises": row.exercises,
        "pt_change": row.pt_change,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Grouped views
# ---------------------------------------------------------------------------

def build_grouped_views(
    rows: list[NormalizedOptionRow],
) -> GroupedViews:
    """Group normalized rows by expiry, option_type, and strike.

    Returns a GroupedViews with convenience lookups.
    """
    by_expiry: dict[str, list[NormalizedOptionRow]] = defaultdict(list)
    call_by_expiry: dict[str, list[NormalizedOptionRow]] = defaultdict(list)
    put_by_expiry: dict[str, list[NormalizedOptionRow]] = defaultdict(list)
    by_expiry_strike: dict[str, dict[int, list[NormalizedOptionRow]]] = defaultdict(lambda: defaultdict(list))

    for r in rows:
        by_expiry[r.expiry].append(r)
        by_expiry_strike[r.expiry][r.strike].append(r)
        if r.option_type == "CALL":
            call_by_expiry[r.expiry].append(r)
        elif r.option_type == "PUT":
            put_by_expiry[r.expiry].append(r)

    return GroupedViews(
        by_expiry=dict(by_expiry),
        call_by_expiry=dict(call_by_expiry),
        put_by_expiry=dict(put_by_expiry),
        by_expiry_strike={k: dict(v) for k, v in by_expiry_strike.items()},
    )
