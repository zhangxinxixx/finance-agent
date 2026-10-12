"""PRELIMINARY → FINAL reconciliation for CME option rows."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping


def _value(row: Mapping[str, Any] | object, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _as_key(row: Mapping[str, Any] | object) -> tuple[str, str, int, str]:
    try:
        strike = int(_value(row, "strike"))
    except (TypeError, ValueError):
        strike = -1
    return (
        str(_value(row, "product_code", _value(row, "product", "")) or "").upper(),
        str(_value(row, "expiry", "") or "").upper(),
        strike,
        str(_value(row, "option_type", "") or "").upper(),
    )


def _finite_equal(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    try:
        lf, rf = float(left), float(right)
    except (TypeError, ValueError):
        return left == right
    if not (math.isfinite(lf) and math.isfinite(rf)):
        return left == right
    return math.isclose(lf, rf, rel_tol=1e-10, abs_tol=1e-10)


def reconcile_cme_versions(
    prelim_rows: list[Mapping[str, Any] | object],
    final_rows: list[Mapping[str, Any] | object],
    *,
    report_date: str,
    product: str = "OG",
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Diff two same-report-date row sets without changing either input.

    The result is deliberately descriptive: the FINAL rows remain the current
    selection, while the PRELIM rows and all differences stay available for
    audit/replay.  A date mismatch raises so a caller cannot silently compare
    neighboring bulletins.
    """

    def check_date(row: Mapping[str, Any] | object) -> None:
        row_date = _value(row, "report_date", _value(row, "trade_date"))
        if row_date not in (None, "", report_date):
            raise ValueError(f"CME version row date {row_date!r} does not match report_date={report_date!r}")
        row_product = str(_value(row, "product_code", _value(row, "product", product)) or product).upper()
        if row_product != product.upper():
            raise ValueError(f"CME version row product {row_product!r} does not match product={product!r}")

    for row in [*prelim_rows, *final_rows]:
        check_date(row)

    prelim = {_as_key(row): row for row in prelim_rows}
    final = {_as_key(row): row for row in final_rows}
    if len(prelim) != len(prelim_rows) or len(final) != len(final_rows):
        raise ValueError("CME version rows contain duplicate option keys")

    comparable_fields = (
        "settlement", "delta", "open_interest", "oi_change", "total_volume",
        "block_volume", "pnt_volume", "globex_volume", "outcry_volume",
        "exercises", "pt_change",
    )
    added = sorted(set(final) - set(prelim))
    removed = sorted(set(prelim) - set(final))
    changed: list[dict[str, Any]] = []
    unchanged = 0
    field_changes: Counter[str] = Counter()
    for key in sorted(set(prelim) & set(final)):
        before, after = prelim[key], final[key]
        changes: dict[str, dict[str, Any]] = {}
        for field in comparable_fields:
            old, new = _value(before, field), _value(after, field)
            if not _finite_equal(old, new):
                changes[field] = {"prelim": old, "final": new}
                field_changes[field] += 1
        if changes:
            changed.append({
                "product_code": key[0], "expiry": key[1], "strike": key[2], "option_type": key[3],
                "changes": changes,
            })
        else:
            unchanged += 1

    if prelim_rows and final_rows:
        status = "final_reconciled"
    elif final_rows:
        status = "final_only"
    elif prelim_rows:
        status = "prelim_only"
    else:
        status = "no_data"

    def key_dict(key: tuple[str, str, int, str]) -> dict[str, Any]:
        return {"product_code": key[0], "expiry": key[1], "strike": key[2], "option_type": key[3]}

    comparable = bool(prelim_rows and final_rows)
    return {
        "schema_version": "cme_options_reconciliation.v1",
        "report_date": report_date,
        "product": product,
        "status": status,
        "current_selection": "FINAL" if final_rows else "PRELIMINARY" if prelim_rows else "UNAVAILABLE",
        "feature_version": "cme_options_analysis.v2",
        "feature_revision": "cme_options_analysis.v2:reconciliation_pending_source_revision",
        "prelim": {"row_count": len(prelim_rows)},
        "final": {"row_count": len(final_rows)},
        "delta": {
            "comparison_available": comparable,
            "added_in_final": len(added) if comparable else None,
            "removed_from_final": len(removed) if comparable else None,
            "changed": len(changed) if comparable else None,
            "unchanged": unchanged if comparable else None,
            "changed_fields": dict(sorted(field_changes.items())),
            "added_keys": [key_dict(key) for key in added[:100]] if comparable else [],
            "removed_keys": [key_dict(key) for key in removed[:100]] if comparable else [],
            "changed_rows": changed[:100],
        },
        "source_refs": [dict(item) for item in (source_refs or []) if isinstance(item, dict)],
        "limitations": [
            "Comparison is row-level for the supplied product and report_date.",
            "FINAL is preferred when available; PRELIMINARY remains retained for audit/replay.",
            "Rows beyond the first 100 added/removed/changed keys are counted but truncated in detail.",
        ],
    }


__all__ = ["reconcile_cme_versions"]
