"""Deterministic CME option expiry-window selection.

The Daily Bulletin contains more expiries than the compact options report can
sensibly model.  This module selects a documented, reproducible window while
retaining coverage metadata.  It intentionally does not know anything about
the current calendar month (and therefore never hard-codes OCT/NOV/etc.).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Mapping

from apps.features.options.black76 import calc_time_to_expiry, expiry_sort_key


def _value(row: Mapping[str, Any] | object, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _as_float(value: Any) -> float:
    try:
        number = float(str(value).replace(",", "")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class ExpirySelectionResult:
    """Selected expiry window and its measurable chain coverage."""

    selected_expiries: list[str]
    all_expiries: list[str]
    eligible_expiries: list[str]
    excluded_expiries: dict[str, str]
    total_open_interest: dict[str, float]
    selected_open_interest: float
    eligible_open_interest: float
    total_row_count: int
    selected_row_count: int
    selection_policy: dict[str, Any] = field(default_factory=dict)

    @property
    def open_interest_coverage(self) -> float | None:
        if self.eligible_open_interest <= 0:
            return None
        return round(self.selected_open_interest / self.eligible_open_interest, 6)

    @property
    def row_coverage(self) -> float | None:
        if self.total_row_count <= 0:
            return None
        return round(self.selected_row_count / self.total_row_count, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_expiries": list(self.selected_expiries),
            "selected_expiry_window": list(self.selected_expiries),
            "all_expiries": list(self.all_expiries),
            "eligible_expiries": list(self.eligible_expiries),
            "excluded_expiries": dict(self.excluded_expiries),
            "total_open_interest": {
                expiry: round(value, 4) for expiry, value in self.total_open_interest.items()
            },
            "selected_open_interest": round(self.selected_open_interest, 4),
            "eligible_open_interest": round(self.eligible_open_interest, 4),
            "open_interest_coverage": self.open_interest_coverage,
            "total_row_count": self.total_row_count,
            "selected_row_count": self.selected_row_count,
            "row_coverage": self.row_coverage,
            "coverage": {
                "open_interest": self.open_interest_coverage,
                "rows": self.row_coverage,
                "selected_expiries": len(self.selected_expiries),
                "eligible_expiries": len(self.eligible_expiries),
                "all_expiries": len(self.all_expiries),
            },
            "selection_policy": dict(self.selection_policy),
        }


def select_expiry_window(
    rows: list[Mapping[str, Any] | object],
    *,
    trade_date: str | None,
    max_expiries: int = 2,
    top_n_oi: int | None = None,
    front_active_future_expiry: str | None = None,
) -> ExpirySelectionResult:
    """Select the nearest eligible expiry plus the largest-OI eligible expiries.

    The nearest expiry is always retained when it can be parsed.  Remaining
    slots are filled by total positive OI (ties resolve chronologically), and
    the final list is returned chronologically for downstream roll analysis.
    Expiry dates supplied on rows are preferred; otherwise the existing CME
    delivery-month estimate is used and recorded as such.
    """

    if max_expiries < 1:
        raise ValueError("max_expiries must be at least 1")
    top_n_oi = max_expiries if top_n_oi is None else max(1, int(top_n_oi))

    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        expiry_raw = _value(row, "expiry")
        expiry = str(expiry_raw or "").strip().upper()
        if not expiry:
            continue
        item = normalized.setdefault(
            expiry,
            {"oi": 0.0, "rows": 0, "expiry_dates": set(), "unparseable_date": False},
        )
        item["oi"] += _as_float(_value(row, "open_interest", 0))
        item["rows"] += 1
        supplied_date = _parse_date(
            _value(row, "expiry_date")
            or _value(row, "expiration_date")
            or _value(row, "option_expiry_date")
        )
        if supplied_date is not None:
            item["expiry_dates"].add(supplied_date)
        elif any(_value(row, key) is not None for key in ("expiry_date", "expiration_date", "option_expiry_date")):
            item["unparseable_date"] = True

    all_expiries = sorted(normalized, key=expiry_sort_key)
    # Do not inspect option-row fields for a futures expiry.  A Daily Bulletin
    # option row describes an option expiry, not the currently active GC
    # futures contract.  The optional argument is accepted only for a caller
    # that has independently collected and identified the front future.
    excluded: dict[str, str] = {}
    eligible: list[str] = []
    dates: dict[str, dt.date] = {}
    trade = _parse_date(trade_date)
    for expiry in all_expiries:
        item = normalized[expiry]
        expiry_dates = item["expiry_dates"]
        if len(expiry_dates) > 1:
            excluded[expiry] = "conflicting_expiry_dates"
            continue
        if expiry_dates:
            expiry_date = next(iter(expiry_dates))
        else:
            if item["unparseable_date"]:
                excluded[expiry] = "expiry_date_unparseable"
                continue
            if trade is None:
                # Keep a parseable month in the eligible universe when the
                # caller has no trade date; expiry ordering remains valid but
                # date eligibility cannot be verified.
                expiry_date = None
            else:
                try:
                    _T, expiry_date, _warnings = calc_time_to_expiry(trade.isoformat(), expiry=expiry)
                except (ValueError, KeyError, IndexError):
                    excluded[expiry] = "expiry_code_unparseable"
                    continue
        if expiry_date is not None and trade is not None and expiry_date < trade:
            excluded[expiry] = "expired_before_trade_date"
            continue
        dates[expiry] = expiry_date
        eligible.append(expiry)

    oi_by_expiry = {expiry: float(normalized[expiry]["oi"]) for expiry in all_expiries}
    eligible_oi = sum(oi_by_expiry.get(expiry, 0.0) for expiry in eligible)
    selected: list[str] = []
    front_future_status = "unavailable_from_option_rows"
    front_future = (
        str(front_active_future_expiry).strip().upper()
        if front_active_future_expiry
        else None
    )
    if front_future and front_future not in eligible:
        front_future_status = "not_in_eligible_expiries"
        front_future = None
    elif front_future:
        front_future_status = "included"

    nearest: str | None = None
    top_oi_candidates: list[str] = []
    if eligible:
        # Front active expiry is a hard inclusion.  A supplied expiry date is
        # preserved in the policy so consumers can tell estimated dates apart.
        nearest = min(eligible, key=lambda expiry: (dates.get(expiry) or dt.date.max, expiry_sort_key(expiry)))
        selected.append(nearest)
        if front_future and front_future != nearest and len(selected) < max_expiries:
            selected.append(front_future)
        oi_ranked = sorted(
            eligible,
            key=lambda expiry: (-oi_by_expiry.get(expiry, 0.0), expiry_sort_key(expiry)),
        )
        top_oi_candidates = oi_ranked[:top_n_oi]
        for expiry in top_oi_candidates:
            if expiry not in selected:
                selected.append(expiry)

    # If a caller explicitly supplies a smaller cap, preserve the nearest
    # expiry and the highest-OI candidates before applying chronological
    # display ordering.  The production CME pipeline uses a cap of three for
    # the nearest + Top-2 union, so no candidate is silently lost there.
    selected_before_cap = sorted(set(selected), key=expiry_sort_key)
    if len(selected) > max_expiries:
        prioritized: list[str] = []
        if nearest is not None:
            prioritized.append(nearest)
        if front_future and front_future != nearest:
            prioritized.append(front_future)
        prioritized.extend(top_oi_candidates)
        selected = []
        for expiry in prioritized:
            if expiry in eligible and expiry not in selected:
                selected.append(expiry)
            if len(selected) >= max_expiries:
                break
    selected = sorted(set(selected), key=expiry_sort_key)[:max_expiries]

    selected_oi = sum(oi_by_expiry.get(expiry, 0.0) for expiry in selected)
    selected_rows = sum(int(normalized[expiry]["rows"]) for expiry in selected)
    truncated_expiries = selected_before_cap[max_expiries:]
    selection_policy = {
        "version": "expiry_window.v2",
        "name": "nearest_eligible_plus_top_open_interest",
        "max_expiries": max_expiries,
        "top_n_oi": top_n_oi,
        "top_n_oi_included": [expiry for expiry in top_oi_candidates if expiry in selected],
        "top_n_oi_candidates": top_n_oi,
        "required_nearest_eligible": True,
        "ranking": "total_positive_open_interest_desc_then_chronological",
        # Legacy field retained, explicitly scoped to options so it cannot be
        # read as the front active GC futures contract.
        "front_active_expiry": selected[0] if selected else None,
        "front_active_expiry_instrument": "option" if selected else None,
        "front_active_option_expiry": selected[0] if selected else None,
        "front_active_future_expiry": front_future,
        "front_active_future_status": front_future_status,
        # Option rows describe option expiries only.  Do not expose them as
        # futures expiries when no independent futures source was supplied.
        "available_option_expiries": list(eligible),
        "available_front_future_expiries": [front_future] if front_future else [],
        "front_active_future_source": (
            "independent_caller_source" if front_active_future_expiry else "unavailable"
        ),
        "front_active_future_inference": False,
        "front_active_future_limitation": (
            "No independent GC futures expiry source was supplied; option months are not used as futures expiry."
            if not front_active_future_expiry
            else "Caller supplied an independently identified front GC futures expiry."
        ),
        "union_selection": {
            "nearest_eligible": nearest,
            "top_oi_candidates": top_oi_candidates,
            "selected_before_cap": selected_before_cap,
            "truncated_expiries": truncated_expiries,
            "is_truncated": bool(truncated_expiries),
        },
        "expiry_date_source": {
            expiry: (
                "row_expiry_date"
                if normalized[expiry]["expiry_dates"]
                else "estimated_from_delivery_month"
                if trade is not None
                else "not_verified_without_trade_date"
            )
            for expiry in eligible
        },
        "date_eligibility_verified": trade is not None,
        "derived_expiry_restrictions": [
            "expired_before_trade_date excluded",
            "unparseable or conflicting expiry dates excluded",
            "rows outside selected window retained in source chain but excluded from main analysis",
        ],
        "selected_is_full_chain": len(selected) == len(eligible) == len(all_expiries),
    }
    return ExpirySelectionResult(
        selected_expiries=selected,
        all_expiries=all_expiries,
        eligible_expiries=eligible,
        excluded_expiries=excluded,
        total_open_interest=oi_by_expiry,
        selected_open_interest=selected_oi,
        eligible_open_interest=eligible_oi,
        total_row_count=len(rows),
        selected_row_count=selected_rows,
        selection_policy=selection_policy,
    )


__all__ = ["ExpirySelectionResult", "select_expiry_window"]
