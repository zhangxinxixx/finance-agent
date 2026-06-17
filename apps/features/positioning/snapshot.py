from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PositioningSnapshot:
    """Read-only COT positioning snapshot for a single asset (COT_GOLD).

    Computed from CFTC Commitment of Traders disaggregated data.
    All net figures are in contracts (long - short).
    """

    status: str  # "available", "unavailable"
    as_of: str  # Report_Date of latest row
    commercial_net: float  # latest week Prod_Merc long - short
    noncomm_net: float  # latest week Managed Money long - short
    commercial_net_prev: float | None  # previous week for direction
    noncomm_net_prev: float | None
    commercial_direction: str  # "increasing_short", "increasing_long", "flat"
    noncomm_direction: str
    extreme_reading: bool  # True if commercial_net in top/bottom 20% of last 52 weeks
    total_oi: float  # open interest
    source_refs: list[dict[str, str]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_positioning_snapshot(
    points: list[dict[str, object]],
    *,
    unavailable_symbols: list[str] | None = None,
    source_refs: list[dict[str, str]] | None = None,
) -> PositioningSnapshot:
    """Build a PositioningSnapshot from collected MacroPoints.

    Points must include ``COT_GOLD_commercial_net``, ``COT_GOLD_noncomm_net``,
    and optionally the ``_prev`` variants.
    """
    by_symbol: dict[str, dict[str, object]] = {}
    for point in points:
        symbol = str(point["symbol"])
        by_symbol[symbol] = point

    refs: list[dict[str, str]] = []
    refs.extend(source_refs or [])
    for point in points:
        refs.append({
            "source": str(point["source"]),
            "source_url": str(point["source_url"]),
            "raw_path": str(point["raw_path"]),
        })

    def _get(suffix: str) -> float | None:
        key = f"COT_GOLD_{suffix}"
        point = by_symbol.get(key)
        if point is None:
            return None
        try:
            return float(point["value"])
        except (TypeError, ValueError, KeyError):
            return None

    commercial_net = _get("commercial_net")
    noncomm_net = _get("noncomm_net")
    total_oi = _get("open_interest")
    commercial_net_prev = _get("commercial_net_prev")
    noncomm_net_prev = _get("noncomm_net_prev")

    if commercial_net is None or noncomm_net is None:
        return PositioningSnapshot(
            status="unavailable",
            as_of="",
            commercial_net=0.0,
            noncomm_net=0.0,
            commercial_net_prev=None,
            noncomm_net_prev=None,
            commercial_direction="flat",
            noncomm_direction="flat",
            extreme_reading=False,
            total_oi=0.0,
            source_refs=refs,
        )

    # Compute direction
    if commercial_net_prev is not None:
        if commercial_net < commercial_net_prev:
            commercial_direction = "increasing_short"
        elif commercial_net > commercial_net_prev:
            commercial_direction = "increasing_long"
        else:
            commercial_direction = "flat"
    else:
        commercial_direction = "flat"

    if noncomm_net_prev is not None:
        if noncomm_net < noncomm_net_prev:
            noncomm_direction = "increasing_short"
        elif noncomm_net > noncomm_net_prev:
            noncomm_direction = "increasing_long"
        else:
            noncomm_direction = "flat"
    else:
        noncomm_direction = "flat"

    # Compute extreme_reading: is commercial_net in top/bottom 20% of last 52 weeks?
    # This requires the full 52-week history from the points.
    # All commercial_net values across all rows (not just latest)
    all_commercial_nets: list[float] = []
    for point in points:
        symbol = str(point["symbol"])
        if symbol.endswith("commercial_net") and "prev" not in symbol:
            try:
                all_commercial_nets.append(float(point["value"]))
            except (TypeError, ValueError):
                pass

    extreme_reading = False
    if len(all_commercial_nets) >= 5:
        sorted_nets = sorted(all_commercial_nets)
        percentile_20 = sorted_nets[int(len(sorted_nets) * 0.2)]
        percentile_80 = sorted_nets[int(len(sorted_nets) * 0.8)]
        extreme_reading = (
            commercial_net <= percentile_20 or commercial_net >= percentile_80
        )

    as_of = by_symbol.get("COT_GOLD_commercial_net", {}).get("date", "")
    as_of = str(as_of) if as_of else ""

    return PositioningSnapshot(
        status="available",
        as_of=as_of,
        commercial_net=round(commercial_net, 6),
        noncomm_net=round(noncomm_net, 6),
        commercial_net_prev=round(commercial_net_prev, 6) if commercial_net_prev is not None else None,
        noncomm_net_prev=round(noncomm_net_prev, 6) if noncomm_net_prev is not None else None,
        commercial_direction=commercial_direction,
        noncomm_direction=noncomm_direction,
        extreme_reading=extreme_reading,
        total_oi=round(total_oi, 6) if total_oi is not None else 0.0,
        source_refs=refs,
    )
