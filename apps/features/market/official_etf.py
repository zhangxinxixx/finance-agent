"""Pure feature contract for official single-fund GLD evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable


@dataclass(frozen=True)
class OfficialGldEtfSnapshot:
    """Typed GLD level/change context for Core integration.

    Shares outstanding and trust gold holdings are separate official facts.
    ``total_net_assets_usd`` is deliberately a level; this contract does not
    expose an AUM flow field.
    """

    status: str
    source_key: str
    source_kind: str
    fund_name: str
    ticker: str
    fund_scope: str
    region: str
    as_of: str | None
    shares_outstanding: float | None
    shares_delta: float | None
    shares_reported_on: str | None
    shares_previous_value: float | None
    shares_previous_reported_on: str | None
    shares_weekly_anchor_value: float | None
    shares_weekly_anchor_date: str | None
    shares_weekly_delta: float | None
    gold_holdings_tonnes: float | None
    gold_holdings_tonnes_delta: float | None
    gold_holdings_tonnes_reported_on: str | None
    gold_holdings_tonnes_previous_value: float | None
    gold_holdings_tonnes_previous_reported_on: str | None
    gold_holdings_tonnes_weekly_anchor_value: float | None
    gold_holdings_tonnes_weekly_anchor_date: str | None
    gold_holdings_tonnes_weekly_delta: float | None
    gold_holdings_ounces: float | None
    gold_holdings_ounces_delta: float | None
    gold_holdings_ounces_previous_value: float | None
    gold_holdings_ounces_previous_reported_on: str | None
    nav_per_share: float | None
    nav_reported_on: str | None
    total_net_assets_usd: float | None
    total_net_assets_reported_on: str | None
    total_net_asset_value_usd: float | None
    total_net_asset_value_reported_on: str | None
    date_alignment: str
    single_fund_holdings_change_tonnes: float | None
    single_fund_holdings_change_kind: str
    global_etf_flow: None = None
    north_america_etf_flow: None = None
    asia_etf_flow: None = None
    provider_role: str = "official_primary"
    verification_status: str = "official_primary"
    source_tier: str = "official"
    missing_data: tuple[str, ...] = ()
    source_refs: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_official_gld_snapshot(
    *,
    points: Iterable[dict[str, Any]],
    source_refs: Iterable[dict[str, Any]] | None = None,
) -> OfficialGldEtfSnapshot:
    """Build a pure GLD feature from ``CollectorResult.points``.

    The collector emits latest and previous rows for shares and tonnes.  This
    function selects each metric by its own published date and recomputes the
    delta from the actual previous point.  It accepts dictionaries so Core can
    pass ``[point.to_dict() for point in result.points]`` without adaptation.
    """

    rows = tuple(row for row in points if isinstance(row, dict))
    shares_weekly_anchor = _latest_metric(rows, "GLD_shares_outstanding_weekly_anchor")
    holdings_weekly_anchor = _latest_metric(rows, "GLD_gold_holdings_tonnes_weekly_anchor")
    shares = _latest_metric(rows, "GLD_shares_outstanding")
    holdings = _latest_metric(rows, "GLD_gold_holdings_tonnes")
    ounces = _latest_metric(rows, "GLD_gold_holdings_ounces")
    nav = _latest_metric(rows, "GLD_nav_per_share")
    total_assets = _latest_metric(rows, "GLD_total_net_assets_usd")
    total_value = _latest_metric(rows, "GLD_total_net_asset_value_usd")

    shares_previous = _metric_point(rows, "GLD_shares_outstanding_prev")
    holdings_previous = _metric_point(rows, "GLD_gold_holdings_tonnes_prev")
    ounces_previous = _metric_point(rows, "GLD_gold_holdings_ounces_prev")
    missing: list[str] = []
    if shares is None:
        missing.append("shares_outstanding")
    if holdings is None:
        missing.append("gold_holdings_tonnes")
    if shares is not None and shares_weekly_anchor is None:
        missing.append("shares_weekly_anchor")
    if holdings is not None and holdings_weekly_anchor is None:
        missing.append("gold_holdings_tonnes_weekly_anchor")

    dates = [item["date"] for item in (shares, holdings, nav) if item is not None]
    as_of = max(dates) if dates else None
    evidence_dates = {item["date"] for item in (shares, holdings) if item is not None}
    if shares is None or holdings is None:
        date_alignment = "missing"
    else:
        date_alignment = "same_date" if len(evidence_dates) == 1 else "different_source_dates"
    refs = _dedupe_refs(source_refs or ())
    if shares is not None and not _has_lineage(refs, source="ssga_gld"):
        missing.append("shares_source_lineage")
    if holdings is not None and not _has_lineage(refs, source="spdr_gld"):
        missing.append("holdings_source_lineage")
    if date_alignment == "different_source_dates":
        # The facts remain useful as separately dated levels, but the
        # composite cannot support a same-day direction claim downstream.
        missing.append("shares_holdings_date_alignment")
    has_required_fact = shares is not None or holdings is not None
    status = "available" if not missing else "partial" if has_required_fact and refs else "unavailable"
    holdings_delta = _delta(holdings, holdings_previous)
    ounces_delta = _delta(ounces, ounces_previous)
    shares_delta = _delta(shares, shares_previous)

    return OfficialGldEtfSnapshot(
        status=status,
        source_key="official_spdr_gld",
        source_kind="official_etf_holdings",
        fund_name="SPDR Gold Shares",
        ticker="GLD",
        fund_scope="single_fund",
        region="north_america",
        as_of=as_of,
        shares_outstanding=_number(shares, "value"),
        shares_delta=shares_delta,
        shares_reported_on=shares.get("date") if shares else None,
        shares_previous_value=_number(shares_previous, "value"),
        shares_previous_reported_on=shares_previous.get("date") if shares_previous else None,
        shares_weekly_anchor_value=_number(shares_weekly_anchor, "value"),
        shares_weekly_anchor_date=shares_weekly_anchor.get("date") if shares_weekly_anchor else None,
        shares_weekly_delta=_delta(shares, shares_weekly_anchor),
        gold_holdings_tonnes=_number(holdings, "value"),
        gold_holdings_tonnes_delta=holdings_delta,
        gold_holdings_tonnes_reported_on=holdings.get("date") if holdings else None,
        gold_holdings_tonnes_previous_value=_number(holdings_previous, "value"),
        gold_holdings_tonnes_previous_reported_on=holdings_previous.get("date") if holdings_previous else None,
        gold_holdings_tonnes_weekly_anchor_value=_number(holdings_weekly_anchor, "value"),
        gold_holdings_tonnes_weekly_anchor_date=holdings_weekly_anchor.get("date") if holdings_weekly_anchor else None,
        gold_holdings_tonnes_weekly_delta=_delta(holdings, holdings_weekly_anchor),
        gold_holdings_ounces=_number(ounces, "value"),
        gold_holdings_ounces_delta=ounces_delta,
        gold_holdings_ounces_previous_value=_number(ounces_previous, "value"),
        gold_holdings_ounces_previous_reported_on=ounces_previous.get("date") if ounces_previous else None,
        nav_per_share=_number(nav, "value"),
        nav_reported_on=nav.get("date") if nav else None,
        total_net_assets_usd=_number(total_assets, "value"),
        total_net_assets_reported_on=total_assets.get("date") if total_assets else None,
        total_net_asset_value_usd=_number(total_value, "value"),
        total_net_asset_value_reported_on=total_value.get("date") if total_value else None,
        date_alignment=date_alignment,
        single_fund_holdings_change_tonnes=holdings_delta,
        single_fund_holdings_change_kind="trust_holdings_change",
        missing_data=tuple(missing),
        source_refs=refs,
    )


def build_official_gld_context(
    *,
    points: Iterable[dict[str, Any]],
    source_refs: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the JSON-ready official GLD feature context."""

    return build_official_gld_snapshot(points=points, source_refs=source_refs).to_dict()


def build_official_gld_context_from_result(result: Any) -> dict[str, Any]:
    """Convenience adapter for a project ``CollectorResult`` instance."""

    return build_official_gld_context(
        points=[point.to_dict() for point in getattr(result, "points", ())],
        source_refs=getattr(result, "source_refs", ()),
    )


def _latest_metric(rows: tuple[dict[str, Any], ...], symbol: str) -> dict[str, Any] | None:
    candidates = [_point for _point in rows if _point.get("symbol") == symbol and _valid_point(_point)]
    return max(candidates, key=lambda row: row["date"], default=None)


def _metric_point(rows: tuple[dict[str, Any], ...], symbol: str) -> dict[str, Any] | None:
    candidates = [_point for _point in rows if _point.get("symbol") == symbol and _valid_point(_point)]
    return max(candidates, key=lambda row: row["date"], default=None)


def _valid_point(row: dict[str, Any]) -> bool:
    if not row.get("date"):
        return False
    try:
        date.fromisoformat(str(row["date"])[:10])
        value = float(row.get("value"))
    except (TypeError, ValueError):
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def _number(row: dict[str, Any] | None, key: str) -> float | None:
    if row is None:
        return None
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _delta(latest: dict[str, Any] | None, previous: dict[str, Any] | None) -> float | None:
    if latest is not None and previous is not None:
        try:
            if date.fromisoformat(str(previous["date"])[:10]) >= date.fromisoformat(str(latest["date"])[:10]):
                return None
        except (KeyError, TypeError, ValueError):
            return None
    latest_value = _number(latest, "value")
    previous_value = _number(previous, "value")
    if latest_value is None or previous_value is None:
        return None
    return round(latest_value - previous_value, 6)


def _has_lineage(refs: tuple[dict[str, Any], ...], *, source: str) -> bool:
    return any(
        ref.get("source") == source
        and ref.get("source_tier") == "official"
        and ref.get("raw_path")
        and ref.get("source_url")
        for ref in refs
    )


def _dedupe_refs(refs: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = tuple(sorted((str(key), str(value)) for key, value in ref.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(ref))
    return tuple(result)
