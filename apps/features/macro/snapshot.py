from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta


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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MacroSnapshot:
    as_of: str
    indicators: dict[str, MacroIndicator]
    unavailable_symbols: list[str]
    source_refs: dict[str, dict[str, str]]

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "indicators": {symbol: indicator.to_dict() for symbol, indicator in self.indicators.items()},
            "unavailable_symbols": self.unavailable_symbols,
            "source_refs": self.source_refs,
        }


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
    _MacroIndicatorSpec("RESERVES", "Reserve Balances", ("WRESBAL",), "balance", "B"),
    _MacroIndicatorSpec("SOFR", "SOFR", ("SOFR",), "rate", "%"),
    _MacroIndicatorSpec("EFFR", "EFFR", ("EFFR",), "rate", "%"),
    _MacroIndicatorSpec("IORB", "IORB", ("IORB",), "rate", "%"),
    _MacroIndicatorSpec("US02Y", "US02Y", ("DGS2",), "rate", "%"),
    _MacroIndicatorSpec("US10Y", "US10Y", ("DGS10",), "rate", "%"),
    _MacroIndicatorSpec("BREAKEVEN_10Y", "10Y Breakeven", ("T10YIE",), "rate", "%"),
    _MacroIndicatorSpec("REAL_10Y", "10Y 实际利率（10Y TIPS）", ("DFII10",), "rate", "%"),
    _MacroIndicatorSpec("YIELD_SPREAD_10Y_2Y", "10Y-2Y 利差", ("DGS10", "DGS2"), "spread", "%"),
    _MacroIndicatorSpec("DXY", "DXY", ("DXY",), "index", "index"),
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
        refs_by_symbol[symbol] = {
            "source": str(point["source"]),
            "source_url": str(point["source_url"]),
            "raw_path": str(point["raw_path"]),
        }

    for series in by_symbol.values():
        series.sort(key=lambda item: str(item["date"]))

    unavailable = set(unavailable_symbols or [])
    indicators: dict[str, MacroIndicator] = {}

    for spec in MACRO_INDICATOR_SPECS:
        series = _build_indicator_series(spec=spec, by_symbol=by_symbol)
        if not series:
            unavailable.update(_missing_symbols_for_spec(spec, by_symbol))
            continue

        current = _latest_on_or_before(series, as_of)
        if current is None:
            unavailable.add(spec.symbol)
            unavailable.update(_missing_symbols_for_spec(spec, by_symbol))
            continue

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
        )

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
        return [
            {
                "date": str(point["date"]),
                "value": float(point["value"]),
            }
            for point in by_symbol.get(source_symbol, [])
        ]

    first_symbol, second_symbol = spec.source_symbols[:2]
    first_by_date = {str(point["date"]): point for point in by_symbol.get(first_symbol, [])}
    second_by_date = {str(point["date"]): point for point in by_symbol.get(second_symbol, [])}
    common_dates = sorted(set(first_by_date) & set(second_by_date))
    return [
        {
            "date": date_value,
            "value": float(first_by_date[date_value]["value"]) - float(second_by_date[date_value]["value"]),
        }
        for date_value in common_dates
    ]


def _missing_symbols_for_spec(
    spec: _MacroIndicatorSpec,
    by_symbol: dict[str, list[dict[str, object]]],
) -> list[str]:
    if spec.kind == "placeholder":
        return [spec.symbol]
    return [symbol for symbol in spec.source_symbols if not by_symbol.get(symbol)]


def _latest_on_or_before(series: list[dict[str, object]], target_date: str) -> dict[str, object] | None:
    candidates = [point for point in series if str(point["date"]) <= target_date]
    return candidates[-1] if candidates else None


def _previous_before(series: list[dict[str, object]], target_date: str) -> dict[str, object] | None:
    candidates = [point for point in series if str(point["date"]) < target_date]
    return candidates[-1] if candidates else None


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
        if negative and not positive:
            return "美元指数转弱，对黄金形成顺风"
        if positive and not negative:
            return "美元指数走强，对黄金形成压力"
        return "美元方向混杂，仍需后续数据确认"

    return "暂无可用方向解读"


def _diff_from(current: dict[str, object], previous: dict[str, object] | None) -> float | None:
    if previous is None:
        return None
    return _normalize_zero(round(float(current["value"]) - float(previous["value"]), 6))


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value
