from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class MacroIndicatorComponent:
    source_symbol: str
    date: str
    value: float


@dataclass(frozen=True)
class MacroIndicator:
    symbol: str
    date: str
    value: float
    daily_change: float | None
    weekly_change: float | None
    monthly_change: float | None = None
    label: str = ""
    unit: str = ""
    direction_note: str = ""
    derivation_version: str | None = None
    components: tuple[MacroIndicatorComponent, ...] = ()
    previous_date: str | None = None
    previous_value: float | None = None
    weekly_anchor_date: str | None = None
    weekly_anchor_value: float | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if self.derivation_version is None:
            payload.pop("derivation_version")
        if not self.components:
            payload.pop("components")
        for key in ("previous_date", "previous_value", "weekly_anchor_date", "weekly_anchor_value"):
            if payload[key] is None:
                payload.pop(key)
        return payload


@dataclass(frozen=True)
class MacroSnapshot:
    as_of: str
    indicators: dict[str, MacroIndicator]
    unavailable_symbols: list[str]
    source_refs: dict[str, dict[str, str]]
    # Optional research domains are carried alongside the legacy indicator
    # table. Keeping them optional preserves the original snapshot contract
    # for callers that only collect the core macro series.
    growth: dict[str, Any] | None = None
    collector_health: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "as_of": self.as_of,
            "indicators": {symbol: indicator.to_dict() for symbol, indicator in self.indicators.items()},
            "unavailable_symbols": self.unavailable_symbols,
            "source_refs": self.source_refs,
        }
        if self.growth is not None:
            payload["growth"] = self.growth
        if self.collector_health is not None:
            payload["collector_health"] = self.collector_health
        return payload


@dataclass(frozen=True)
class _MacroIndicatorSpec:
    symbol: str
    label: str
    source_symbols: tuple[str, ...]
    kind: str
    unit: str


MACRO_INDICATOR_SPECS: tuple[_MacroIndicatorSpec, ...] = (
    _MacroIndicatorSpec("ON_RRP_USAGE", "ON RRP 使用量", ("RRPONTSYD",), "balance", "B"),
    _MacroIndicatorSpec("ON_RRP_AWARD_RATE", "ON RRP Award Rate", ("RRPONTSYAWARD",), "rate", "%"),
    _MacroIndicatorSpec("TGA", "TGA", ("TGA",), "balance", "B"),
    _MacroIndicatorSpec("TGA_WEEKLY_AVERAGE", "TGA 周均余额（截至周三）", ("WTREGEN",), "balance", "B"),
    _MacroIndicatorSpec("RESERVES", "Reserve Balances", ("WRESBAL",), "balance", "B"),
    _MacroIndicatorSpec("WALCL", "Fed 总资产（WALCL）", ("WALCL",), "balance", "B"),
    _MacroIndicatorSpec("SOFR", "SOFR", ("SOFR",), "rate", "%"),
    _MacroIndicatorSpec("EFFR", "EFFR", ("EFFR",), "rate", "%"),
    _MacroIndicatorSpec("IORB", "IORB", ("IORB",), "rate", "%"),
    _MacroIndicatorSpec("SOFR_MINUS_IORB", "SOFR-IORB 利差", ("SOFR", "IORB"), "spread", "%"),
    _MacroIndicatorSpec("EFFR_MINUS_IORB", "EFFR-IORB 利差", ("EFFR", "IORB"), "spread", "%"),
    _MacroIndicatorSpec("US03M", "US03M", ("DGS3MO",), "rate", "%"),
    _MacroIndicatorSpec("US02Y", "US02Y", ("DGS2",), "rate", "%"),
    _MacroIndicatorSpec("US05Y", "US05Y", ("DGS5",), "rate", "%"),
    _MacroIndicatorSpec("US10Y", "US10Y", ("DGS10",), "rate", "%"),
    _MacroIndicatorSpec("US30Y", "US30Y", ("DGS30",), "rate", "%"),
    _MacroIndicatorSpec("REAL5Y", "5Y 实际利率（Treasury TIPS / FRED DFII5）", ("DFII5",), "rate", "%"),
    _MacroIndicatorSpec("T10YIE", "10Y Breakeven Inflation", ("T10YIE",), "rate", "%"),
    _MacroIndicatorSpec("REAL10Y", "10Y 实际利率（TIPS / FRED DFII10）", ("DFII10",), "rate", "%"),
    _MacroIndicatorSpec("REAL30Y", "30Y 实际利率（Treasury TIPS / FRED DFII30）", ("DFII30",), "rate", "%"),
    _MacroIndicatorSpec("BROAD_DOLLAR", "Broad Dollar (FRED DTWEXBGS)", ("DTWEXBGS",), "index", "index"),
    _MacroIndicatorSpec("BREAKEVEN_5Y", "5Y Breakeven", ("T5YIE",), "rate", "%"),
    _MacroIndicatorSpec("BREAKEVEN_10Y", "10Y Breakeven", ("T10YIE",), "rate", "%"),
    _MacroIndicatorSpec("FORWARD_5Y5Y", "5Y5Y Forward Inflation Expectation", ("T5YIFR",), "rate", "%"),
    _MacroIndicatorSpec("REAL_10Y", "10Y 实际利率 = US10Y - T10YIE", ("DGS10", "T10YIE"), "rate", "%"),
    _MacroIndicatorSpec("YIELD_SPREAD_10Y_2Y", "10Y-2Y 利差", ("DGS10", "DGS2"), "spread", "%"),
    _MacroIndicatorSpec("YIELD_SPREAD_2Y_3M", "2Y-3M 利差", ("DGS2", "DGS3MO"), "spread", "%"),
    _MacroIndicatorSpec("YIELD_SPREAD_30Y_10Y", "30Y-10Y 利差", ("DGS30", "DGS10"), "spread", "%"),
    _MacroIndicatorSpec("DXY", "DXY", ("DXY",), "index", "index"),
    _MacroIndicatorSpec("HY_OAS", "美国高收益信用利差（ICE BofA OAS）", ("BAMLH0A0HYM2",), "spread", "%"),
    _MacroIndicatorSpec("WTI_SPOT", "WTI 现货（EIA/FRED，非期货结算）", ("DCOILWTICO",), "price", "USD/bbl"),
    _MacroIndicatorSpec("BRENT_SPOT", "Brent 现货（EIA/FRED，非期货结算）", ("DCOILBRENTEU",), "price", "USD/bbl"),
    _MacroIndicatorSpec("DIESEL_GULF_SPOT", "美国湾区超低硫柴油现货", ("DDFUELUSGULF",), "price", "USD/gal"),
    _MacroIndicatorSpec("GASOLINE_GULF_SPOT", "美国湾区普通汽油现货", ("DGASUSGULF",), "price", "USD/gal"),
    _MacroIndicatorSpec("VIX", "VIX 收盘（CBOE/FRED）", ("VIXCLS",), "index", "index"),
    # Dated official macro releases.  They are context rows; freshness is
    # assessed by the research passport and they never become a live quote.
    _MacroIndicatorSpec("CPI", "CPI（FRED CPIAUCSL）", ("CPIAUCSL",), "index", "index"),
    _MacroIndicatorSpec("PPI", "PPI Final Demand（FRED PPIFIS）", ("PPIFIS",), "index", "index"),
    _MacroIndicatorSpec("PPI_ALL_COMMODITIES", "PPI All Commodities（FRED PPIACO）", ("PPIACO",), "index", "index"),
    _MacroIndicatorSpec("PCE", "PCE Price Index（FRED PCEPI）", ("PCEPI",), "index", "index"),
    _MacroIndicatorSpec("JOLTS", "JOLTS Job Openings（FRED JTSJOL）", ("JTSJOL",), "count", "thousands"),
    _MacroIndicatorSpec("INITIAL_CLAIMS", "Initial Claims（FRED ICSA）", ("ICSA",), "count", "claims"),
    # ISM Manufacturing is sourced from the official ISM report collector.
    # The discontinued NAPM FRED mirror remains a historical/legacy input
    # elsewhere but must never masquerade as the current ISM release.
    _MacroIndicatorSpec("ISM_MANUFACTURING", "ISM Manufacturing PMI（官方 ISM）", ("ISM_MANUFACTURING",), "index", "index"),
    # Atlanta Fed GDPNow is not a FRED series.  Its official value is exposed
    # by the optional ``growth`` domain; this legacy indicator slot remains a
    # visible placeholder so callers that only consume the core table retain
    # the same missing-data semantics.
    _MacroIndicatorSpec("GDP_NOW", "Atlanta Fed GDPNow（见 growth 官方采集）", (), "placeholder", "% q/q saar"),
)


def build_macro_snapshot(
    points: list[dict[str, object]],
    *,
    as_of: str,
    unavailable_symbols: list[str] | None = None,
    source_refs: list[dict[str, str]] | None = None,
) -> MacroSnapshot:
    by_symbol: dict[str, list[dict[str, object]]] = {}
    refs_by_symbol: dict[str, dict[str, str]] = {}
    for ref in source_refs or []:
        symbol = ref.get("symbol")
        if symbol:
            refs_by_symbol[str(symbol)] = dict(ref)

    for point in points:
        symbol = str(point["symbol"])
        by_symbol.setdefault(symbol, []).append(point)
        point_ref = {
            "source": str(point["source"]),
            "source_url": str(point["source_url"]),
            "raw_path": str(point["raw_path"]),
        }
        if point.get("retrieved_at") is not None:
            point_ref["retrieved_at"] = str(point["retrieved_at"])
        refs_by_symbol[symbol] = point_ref

    for series in by_symbol.values():
        series.sort(key=lambda item: str(item["date"]))

    unavailable = set(unavailable_symbols or [])
    indicators: dict[str, MacroIndicator] = {}

    for spec in MACRO_INDICATOR_SPECS:
        series = _build_indicator_series(spec=spec, by_symbol=by_symbol)
        if not series:
            unavailable.add(spec.symbol)
            if spec.symbol == "BROAD_DOLLAR":
                # The formal gold-analysis input is the FRED broad-dollar index;
                # DXY is a legacy, separate report field and is not a substitute.
                unavailable.add(spec.symbol)
            unavailable.update(_missing_symbols_for_spec(spec, by_symbol))
            continue

        current = _latest_on_or_before(series, as_of)
        if current is None:
            unavailable.add(spec.symbol)
            unavailable.update(_missing_symbols_for_spec(spec, by_symbol))
            continue

        _bind_single_source_ref(
            refs_by_symbol=refs_by_symbol,
            spec=spec,
            point=current,
        )

        previous = _previous_before(series, str(current["date"]))
        week_anchor = (date.fromisoformat(str(current["date"])) - timedelta(days=7)).isoformat()
        month_anchor = (date.fromisoformat(str(current["date"])) - timedelta(days=30)).isoformat()
        weekly = _latest_on_or_before(series, week_anchor)
        monthly = _latest_on_or_before(series, month_anchor)
        indicators[spec.symbol] = MacroIndicator(
            symbol=spec.symbol,
            date=str(current["date"]),
            value=round(float(current["value"]), 6),
            daily_change=_rounded_diff(current, previous),
            weekly_change=_rounded_diff(current, weekly),
            monthly_change=_rounded_diff(current, monthly),
            label=spec.label,
            unit=spec.unit,
            direction_note=_direction_note(spec=spec, current=current, weekly=weekly, monthly=monthly),
            derivation_version=(
                "real10y_components.v1"
                if spec.symbol == "REAL_10Y"
                else "policy_corridor_components.v1"
                if spec.symbol in {"SOFR_MINUS_IORB", "EFFR_MINUS_IORB"}
                else None
            ),
            components=tuple(current.get("components", ())),
            previous_date=str(previous["date"]) if previous else None,
            previous_value=float(previous["value"]) if previous else None,
            weekly_anchor_date=str(weekly["date"]) if weekly else None,
            weekly_anchor_value=float(weekly["value"]) if weekly else None,
        )

    _apply_short_curve_direction_note(indicators)

    # Retain provider comparison metadata only for the selected DXY payload.
    # Its undated previous close is not a historical MacroPoint.
    dxy_ref = refs_by_symbol.get("DXY", {})
    for ref in source_refs or []:
        if ref.get("symbol") == "DXY" and dxy_ref.get("raw_path") and all(ref.get(key) == dxy_ref.get(key) for key in ("source", "raw_path", "retrieved_at")):
            refs_by_symbol["DXY"] = {**ref, **dxy_ref}
            break

    return MacroSnapshot(
        as_of=as_of,
        indicators=indicators,
        unavailable_symbols=sorted(unavailable),
        source_refs=refs_by_symbol,
    )


def _build_indicator_series(
    *,
    spec: _MacroIndicatorSpec,
    by_symbol: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    if spec.kind == "placeholder":
        return []

    if len(spec.source_symbols) == 1:
        source_symbol = spec.source_symbols[0]
        # Treasury's own daily curve is the preferred observation when the
        # macro worker also collected the same series through FRED.  Keep the
        # fallback points in the raw chain, but do not let merge order decide
        # which source becomes the research/Gold input on a duplicate date.
        by_date: dict[str, dict[str, object]] = {}
        for point in by_symbol.get(source_symbol, []):
            normalized = {
                **point,
                "date": str(point["date"]),
                "value": float(point["value"]),
            }
            date_value = str(normalized["date"])
            previous = by_date.get(date_value)
            if previous is None or _single_point_source_priority(normalized) < _single_point_source_priority(previous):
                by_date[date_value] = normalized
        return [by_date[key] for key in sorted(by_date)]

    first_symbol, second_symbol = spec.source_symbols[:2]
    if spec.symbol in {"REAL_10Y", "SOFR_MINUS_IORB", "EFFR_MINUS_IORB"}:
        point_index = _strict_points_by_date
        if spec.symbol in {"SOFR_MINUS_IORB", "EFFR_MINUS_IORB"}:
            point_index = _same_value_points_by_date
        first_by_date = point_index(by_symbol.get(first_symbol, []))
        second_by_date = point_index(by_symbol.get(second_symbol, []))
        if first_by_date is None or second_by_date is None:
            return []
    else:
        first_by_date = {
            str(point["date"]): point for point in by_symbol.get(first_symbol, [])
        }
        second_by_date = {
            str(point["date"]): point for point in by_symbol.get(second_symbol, [])
        }
    common_dates = sorted(set(first_by_date) & set(second_by_date))
    series: list[dict[str, object]] = []
    for date_value in common_dates:
        point: dict[str, object] = {
            "date": date_value,
            "value": float(first_by_date[date_value]["value"]) - float(second_by_date[date_value]["value"]),
        }
        if spec.symbol in {"REAL_10Y", "SOFR_MINUS_IORB", "EFFR_MINUS_IORB"}:
            point["components"] = (
                MacroIndicatorComponent(
                    source_symbol=first_symbol,
                    date=date_value,
                    value=float(first_by_date[date_value]["value"]),
                ),
                MacroIndicatorComponent(
                    source_symbol=second_symbol,
                    date=date_value,
                    value=float(second_by_date[date_value]["value"]),
                ),
            )
        series.append(point)
    return series


def _strict_points_by_date(
    points: list[dict[str, object]],
) -> dict[str, dict[str, object]] | None:
    by_date: dict[str, dict[str, object]] = {}
    for point in points:
        date_value = str(point["date"])
        previous = by_date.get(date_value)
        if previous is not None and _point_identity(previous) != _point_identity(point):
            return None
        by_date.setdefault(date_value, point)
    return by_date


def _same_value_points_by_date(
    points: list[dict[str, object]],
) -> dict[str, dict[str, object]] | None:
    """Index equivalent duplicate observations without hiding conflicts.

    FRED carries the historical policy series while the Fed PRATES collector
    may also provide the current IORB point.  Equal values are the same fact,
    so retain one explicit source-priority representative; conflicting values
    remain unavailable rather than being selected arbitrarily.
    """
    by_date: dict[str, dict[str, object]] = {}
    for point in points:
        date_value = str(point["date"])
        previous = by_date.get(date_value)
        if previous is None:
            by_date[date_value] = point
            continue
        if float(previous["value"]) != float(point["value"]):
            return None
        if _point_source_priority(point) < _point_source_priority(previous):
            by_date[date_value] = point
    return by_date


def _point_source_priority(point: dict[str, object]) -> tuple[int, str, str]:
    source = str(point.get("source") or "")
    rank = {"fed_prates": 0, "fred": 1}.get(source, 2)
    return rank, source, str(point.get("raw_path") or "")


def _single_point_source_priority(point: dict[str, object]) -> tuple[int, str, str]:
    """Prefer an official Treasury curve over the FRED fallback on a date."""

    source = str(point.get("source") or "")
    rank = {
        "treasury_rates": 0,
        "treasury": 0,
        "fred": 1,
    }.get(source, 2)
    return rank, source, str(point.get("raw_path") or "")


def _point_identity(point: dict[str, object]) -> tuple[object, ...]:
    return tuple(
        point.get(field)
        for field in ("value", "source", "source_url", "raw_path", "retrieved_at")
    )


def _missing_symbols_for_spec(
    spec: _MacroIndicatorSpec,
    by_symbol: dict[str, list[dict[str, object]]],
) -> list[str]:
    if spec.kind == "placeholder":
        return [spec.symbol]
    return [symbol for symbol in spec.source_symbols if not by_symbol.get(symbol)]


def _bind_single_source_ref(
    *,
    refs_by_symbol: dict[str, dict[str, str]],
    spec: _MacroIndicatorSpec,
    point: dict[str, object],
) -> None:
    """Keep a single-source indicator's ref attached to its selected point.

    A symbol may be supplied by multiple collectors.  The snapshot chooses the
    point using the as-of gate, so its lineage must be chosen from that point
    rather than from whichever collector ref happened to be merged last.
    Derived indicators retain the source refs of their individual source
    indicators and do not overwrite them with a potentially different common
    date.
    """
    if len(spec.source_symbols) != 1:
        return
    point_ref = {
        field: str(point[field])
        for field in ("source", "source_url", "raw_path", "retrieved_at")
        if point.get(field) is not None
    }
    if point_ref:
        refs_by_symbol[spec.source_symbols[0]] = point_ref


def _latest_on_or_before(series: list[dict[str, object]], target_date: str) -> dict[str, object] | None:
    candidates = [point for point in series if str(point["date"]) <= target_date]
    return max(candidates, key=lambda point: str(point["date"])) if candidates else None


def _previous_before(series: list[dict[str, object]], target_date: str) -> dict[str, object] | None:
    candidates = [point for point in series if str(point["date"]) < target_date]
    return max(candidates, key=lambda point: str(point["date"])) if candidates else None


def _rounded_diff(current: dict[str, object], previous: dict[str, object] | None) -> float | None:
    if previous is None:
        return None
    return _normalize_zero(round(float(current["value"]) - float(previous["value"]), 6))


def _direction_note(
    *,
    spec: _MacroIndicatorSpec,
    current: dict[str, object],
    weekly: dict[str, object] | None,
    monthly: dict[str, object] | None,
) -> str:
    weekly_change = _diff_from(current, weekly)
    monthly_change = _diff_from(current, monthly)

    observed_changes = [change for change in (weekly_change, monthly_change) if change is not None]
    if not observed_changes:
        return "近期变化有限，方向暂不明确"

    positive = any(change > 0 for change in observed_changes)
    negative = any(change < 0 for change in observed_changes)

    if spec.kind in {"rate", "spread"}:
        if spec.symbol == "US03M":
            if weekly_change is not None and weekly_change < 0:
                return "3M 周度下行，当前政策价格出现转松信号"
            if weekly_change is not None and weekly_change > 0:
                return "3M 周度上行，当前短端价格进一步收紧"
            if monthly_change is not None and monthly_change < 0:
                return "3M 周度持平、月度下行，当前政策价格仅缓慢转松"
            if monthly_change is not None and monthly_change > 0:
                return "3M 周度持平、月度上行，当前政策价格未松"
            return "3M 基本持平，当前政策价格没有新增宽松信号"
        if positive and not negative:
            return "收益率或利差抬升，边际压力略增"
        if negative and not positive:
            return "收益率或利差回落，边际压力略缓"
        return "短期方向混杂，仍需后续数据确认"

    if spec.kind == "balance":
        if spec.symbol == "TGA":
            if weekly_change is not None and weekly_change < 0:
                return "较上周明显回落，财政抽水缓和；但仍需观察月度位置"
            if weekly_change is not None and weekly_change > 0:
                return "较上周回升，财政抽水压力边际增加"
        if spec.symbol == "RESERVES":
            if weekly_change is not None and weekly_change > 0:
                return "准备金周频回升，银行体系缓冲变厚，数量层偏松"
            if weekly_change is not None and weekly_change < 0:
                return "准备金周频回落，银行体系缓冲变薄，数量层偏紧"
        if spec.symbol == "ON_RRP_USAGE" and float(current["value"]) < 50:
            return "仍处极低位，资金未明显回停 Fed 工具，数量层不构成系统性抽水"
        if positive and not negative:
            return "余额上升，流动性占用偏高"
        if negative and not positive:
            return "余额回落，流动性占用有所下降"
        return "短期波动有限，趋势暂不明确"

    if spec.kind == "index":
        if spec.symbol == "DXY" and float(current["value"]) >= 101:
            return "美元指数位于 101 上方，对黄金形成逆风"
        if spec.symbol == "BROAD_DOLLAR":
            if negative and not positive:
                return "广义美元走弱，对黄金形成顺风"
            if positive and not negative:
                return "广义美元走强，对黄金形成压力"
            return "广义美元方向混杂，仍需后续数据确认"
        if negative and not positive:
            return "美元指数转弱，对黄金形成顺风"
        if positive and not negative:
            return "美元指数走强，对黄金形成压力"
        return "美元方向混杂，仍需后续数据确认"

    return "暂无可用方向解读"


def _apply_short_curve_direction_note(indicators: dict[str, MacroIndicator]) -> None:
    spread = indicators.get("YIELD_SPREAD_2Y_3M")
    us02y = indicators.get("US02Y")
    us03m = indicators.get("US03M")
    if spread is None or us02y is None or us03m is None:
        return

    curve_state = "正斜率" if spread.value > 0 else "倒挂" if spread.value < 0 else "持平"
    if spread.weekly_change is None or spread.weekly_change == 0:
        curve_change = "周度基本不变"
    elif spread.value >= 0:
        curve_change = "周度走阔" if spread.weekly_change > 0 else "周度收窄"
    else:
        curve_change = "倒挂收窄" if spread.weekly_change > 0 else "倒挂加深"

    indicators[spread.symbol] = replace(
        spread,
        direction_note=f"{curve_state}、{curve_change}；{_short_curve_leg_note(us02y.weekly_change, us03m.weekly_change)}",
    )


def _short_curve_leg_note(two_change: float | None, three_change: float | None) -> str:
    if two_change is None or three_change is None:
        return "2Y 或 3M 周变化缺失，不能单独解释曲线信号"
    if two_change > 0 and three_change < 0:
        return "2Y 上行、3M 下行，鹰派预期与近期价格转松并存"
    if two_change < 0 and three_change > 0:
        return "2Y 下行、3M 上行，未来预期缓和但当前短端更紧"
    if two_change >= 0 and three_change >= 0:
        if two_change > three_change:
            return "2Y 升幅更大，未来利率溢价偏鹰"
        if three_change > two_change:
            return "3M 升幅更大，当前短端收紧更明显"
        return "2Y 与 3M 同步，曲线未提供新增方向确认"
    if abs(three_change) > abs(two_change):
        return "3M 降幅更大，近期政策价格转松信号较强"
    if abs(two_change) > abs(three_change):
        if three_change == 0:
            return "2Y 下行、3M 未降，未来紧缩溢价缓和但当前短端未松"
        return "2Y 降幅更大，未来紧缩溢价缓和更明显"
    return "2Y 与 3M 同步，曲线未提供新增方向确认"


def _diff_from(current: dict[str, object], previous: dict[str, object] | None) -> float | None:
    if previous is None:
        return None
    return _normalize_zero(round(float(current["value"]) - float(previous["value"]), 6))


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value
