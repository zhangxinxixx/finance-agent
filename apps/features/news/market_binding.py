from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WINDOW_MINUTES: dict[str, int] = {
    "5m": 5,
    "30m": 30,
    "2h": 120,
}

CORE_MARKET_SNAPSHOT_ASSETS: tuple[str, ...] = ("XAUUSD", "DXY", "US10Y", "WTI", "USDJPY")

PRICE_THRESHOLDS: dict[str, dict[str, float]] = {
    "XAUUSD": {"5m": 0.15, "30m": 0.30, "2h": 0.50},
    "DXY": {"5m": 0.05, "30m": 0.10, "2h": 0.20},
    "WTI": {"5m": 0.30, "30m": 0.60, "2h": 1.00},
    "USDJPY": {"5m": 0.08, "30m": 0.16, "2h": 0.30},
}

YIELD_THRESHOLDS_BP: dict[str, dict[str, float]] = {
    "US10Y": {"5m": 2.0, "30m": 4.0, "2h": 7.0},
    "US02Y": {"5m": 2.0, "30m": 4.0, "2h": 7.0},
    "US30Y": {"5m": 2.0, "30m": 4.0, "2h": 7.0},
}


@dataclass(frozen=True)
class MarketReaction:
    event_id: str
    status: str
    baseline_time: str | None
    windows: dict[str, dict[str, dict[str, Any]]]
    market_snapshot: dict[str, Any]
    pricing_status: str
    confirmation_summary: dict[str, int]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_market_reaction(
    event: dict[str, Any],
    impact_assessment: dict[str, Any],
    candles_by_asset: dict[str, list[Any]],
    *,
    windows: tuple[str, ...] = ("5m", "30m", "2h"),
) -> MarketReaction:
    event_id = str(event.get("event_id") or impact_assessment.get("event_id") or "")
    event_time = _parse_time(event.get("event_time"))
    expected = _expected_directions(impact_assessment)
    tracked_assets = market_snapshot_assets_for_event(event, impact_assessment)
    empty_snapshot = _empty_market_snapshot(event_time=event_time, requested_assets=tracked_assets, windows=windows, expected=expected)
    if not event_time or not tracked_assets:
        return MarketReaction(
            event_id=event_id,
            status="unavailable",
            baseline_time=None,
            windows={},
            market_snapshot=empty_snapshot,
            pricing_status="unknown",
            confirmation_summary={"confirmed_count": 0, "contradicted_count": 0, "observed_count": 0},
            warnings=["No event time or tracked assets available."],
        )

    window_results: dict[str, dict[str, dict[str, Any]]] = {}
    warnings: list[str] = []
    baseline_times: list[str] = []
    confirmed_count = 0
    contradicted_count = 0
    observed_count = 0

    for window in windows:
        window_assets: dict[str, dict[str, Any]] = {}
        target_time = event_time + timedelta(minutes=WINDOW_MINUTES.get(window, 30))
        for asset in tracked_assets:
            candles = sorted((_candle_dict(candle) for candle in candles_by_asset.get(asset, [])), key=lambda row: row["open_time"] or datetime.min.replace(tzinfo=timezone.utc))
            baseline = _baseline_candle(candles, event_time=event_time)
            after = _after_candle(candles, event_time=event_time, target_time=target_time)
            if baseline is None or after is None:
                if candles_by_asset.get(asset):
                    warnings.append(f"{asset} has insufficient candles for {window}.")
                continue
            baseline_times.append(_iso(baseline["open_time"]))
            result = _asset_reaction(asset=asset, window=window, baseline=baseline, after=after, expected_direction=expected.get(asset))
            if result["expected_direction"] and result["threshold_hit"]:
                if result["confirms_expected_direction"]:
                    confirmed_count += 1
                elif result["contradicts_expected_direction"]:
                    contradicted_count += 1
            observed_count += 1
            window_assets[asset] = result
        if window_assets:
            window_results[window] = window_assets

    if not window_results:
        return MarketReaction(
            event_id=event_id,
            status="unavailable",
            baseline_time=None,
            windows={},
            market_snapshot=empty_snapshot,
            pricing_status="unknown",
            confirmation_summary={"confirmed_count": 0, "contradicted_count": 0, "observed_count": 0},
            warnings=["No market candles available for event assets."],
        )

    status = "partial" if warnings else "available"
    market_snapshot = _build_market_snapshot(
        event_time=event_time,
        tracked_assets=tracked_assets,
        expected=expected,
        window_results=window_results,
        windows=windows,
    )
    return MarketReaction(
        event_id=event_id,
        status=status,
        baseline_time=min(baseline_times) if baseline_times else None,
        windows=window_results,
        market_snapshot=market_snapshot,
        pricing_status=_pricing_status(confirmed_count=confirmed_count, contradicted_count=contradicted_count),
        confirmation_summary={
            "confirmed_count": confirmed_count,
            "contradicted_count": contradicted_count,
            "observed_count": observed_count,
        },
        warnings=sorted(set(warnings)),
    )


def archive_market_reactions(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    reactions: list[MarketReaction],
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "market_reactions.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retrieved_date": retrieved_date,
        "run_id": run_id,
        "market_reactions": [reaction.to_dict() for reaction in reactions],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def market_snapshot_assets_for_event(
    event: dict[str, Any],
    impact_assessment: dict[str, Any] | None = None,
) -> list[str]:
    event_assets = [str(asset) for asset in event.get("asset_tags", []) if str(asset or "").strip()]
    expected = _expected_directions(impact_assessment or {})
    ordered: list[str] = []
    for asset in [*CORE_MARKET_SNAPSHOT_ASSETS, *event_assets, *expected.keys()]:
        normalized = str(asset or "").strip()
        if not normalized or normalized in ordered:
            continue
        ordered.append(normalized)
    return ordered


def _candle_dict(candle: Any) -> dict[str, Any]:
    if isinstance(candle, dict):
        raw = candle
    else:
        raw = {
            "asset": getattr(candle, "asset", None),
            "timeframe": getattr(candle, "timeframe", None),
            "open_time": getattr(candle, "open_time", None),
            "open": getattr(candle, "open", None),
            "high": getattr(candle, "high", None),
            "low": getattr(candle, "low", None),
            "close": getattr(candle, "close", None),
            "source": getattr(candle, "source", None),
        }
    return {
        "asset": str(raw.get("asset") or ""),
        "timeframe": str(raw.get("timeframe") or ""),
        "open_time": _parse_time(raw.get("open_time")),
        "close": float(raw.get("close")),
        "source": raw.get("source"),
    }


def _baseline_candle(candles: list[dict[str, Any]], *, event_time: datetime) -> dict[str, Any] | None:
    eligible = [candle for candle in candles if candle["open_time"] and candle["open_time"] <= event_time]
    return eligible[-1] if eligible else None


def _after_candle(candles: list[dict[str, Any]], *, event_time: datetime, target_time: datetime) -> dict[str, Any] | None:
    eligible = [candle for candle in candles if candle["open_time"] and event_time < candle["open_time"] <= target_time]
    if eligible:
        return eligible[-1]
    later = [candle for candle in candles if candle["open_time"] and candle["open_time"] > event_time]
    return later[0] if later else None


def _asset_reaction(
    *,
    asset: str,
    window: str,
    baseline: dict[str, Any],
    after: dict[str, Any],
    expected_direction: str | None,
) -> dict[str, Any]:
    baseline_close = float(baseline["close"])
    after_close = float(after["close"])
    abs_change = after_close - baseline_close
    direction = "up" if abs_change > 0 else "down" if abs_change < 0 else "flat"
    if asset in YIELD_THRESHOLDS_BP:
        change_bp = round(abs_change * 100, 2)
        threshold = YIELD_THRESHOLDS_BP[asset].get(window, 4.0)
        threshold_hit = abs(change_bp) >= threshold
        pct_change = None
        threshold_unit = "bp"
    else:
        pct_change = round((abs_change / baseline_close) * 100, 2) if baseline_close else None
        threshold = PRICE_THRESHOLDS.get(asset, {"5m": 0.10, "30m": 0.20, "2h": 0.40}).get(window, 0.20)
        threshold_hit = pct_change is not None and abs(pct_change) >= threshold
        change_bp = None
        threshold_unit = "pct"
    confirms = bool(expected_direction and direction == expected_direction)
    contradicts = bool(expected_direction and direction in {"up", "down"} and direction != expected_direction)
    return {
        "baseline_time": _iso(baseline["open_time"]),
        "after_time": _iso(after["open_time"]),
        "baseline_close": baseline_close,
        "after_close": after_close,
        "abs_change": round(abs_change, 6),
        "pct_change": pct_change,
        "change_bp": change_bp,
        "direction": direction,
        "expected_direction": expected_direction,
        "confirms_expected_direction": confirms,
        "contradicts_expected_direction": contradicts,
        "threshold": threshold,
        "threshold_unit": threshold_unit,
        "threshold_hit": threshold_hit,
    }


def _expected_directions(impact: dict[str, Any]) -> dict[str, str]:
    expected: dict[str, str] = {}
    if impact.get("gold_impact") == "bullish":
        expected["XAUUSD"] = "up"
    elif impact.get("gold_impact") == "bearish":
        expected["XAUUSD"] = "down"
    if impact.get("oil_impact") == "oil_up":
        expected["WTI"] = "up"
        expected["Brent"] = "up"
    elif impact.get("oil_impact") == "oil_down":
        expected["WTI"] = "down"
        expected["Brent"] = "down"
    if impact.get("dollar_impact") == "dollar_strength":
        expected["DXY"] = "up"
    elif impact.get("dollar_impact") == "dollar_weakness":
        expected["DXY"] = "down"
    if impact.get("yield_impact") == "yield_up":
        expected["US10Y"] = "up"
        expected["US02Y"] = "up"
    elif impact.get("yield_impact") == "yield_down":
        expected["US10Y"] = "down"
        expected["US02Y"] = "down"
    return expected


def _pricing_status(*, confirmed_count: int, contradicted_count: int) -> str:
    if confirmed_count > 0 and contradicted_count == 0:
        return "partially_priced"
    if contradicted_count > 0 and confirmed_count == 0:
        return "contradicted_by_market"
    if confirmed_count > 0 and contradicted_count > 0:
        return "mixed"
    return "unpriced"


def _empty_market_snapshot(
    *,
    event_time: datetime | None,
    requested_assets: list[str],
    windows: tuple[str, ...],
    expected: dict[str, str],
) -> dict[str, Any]:
    return {
        "event_time": _iso(event_time),
        "requested_assets": requested_assets,
        "observed_assets": [],
        "missing_assets": requested_assets,
        "primary_window": windows[0] if windows else None,
        "assets": [
            {
                "asset": asset,
                "status": "missing",
                "expected_direction": expected.get(asset),
                "baseline_time": None,
                "baseline_close": None,
                "latest_window": None,
                "latest_observed_time": None,
                "latest_direction": None,
                "latest_pct_change": None,
                "latest_change_bp": None,
                "any_threshold_hit": False,
                "confirmed_in_any_window": False,
                "contradicted_in_any_window": False,
                "observed_window_count": 0,
            }
            for asset in requested_assets
        ],
    }


def _build_market_snapshot(
    *,
    event_time: datetime,
    tracked_assets: list[str],
    expected: dict[str, str],
    window_results: dict[str, dict[str, dict[str, Any]]],
    windows: tuple[str, ...],
) -> dict[str, Any]:
    ordered_windows = [window for window in windows if window in window_results]
    primary_window = ordered_windows[0] if ordered_windows else (windows[0] if windows else None)
    assets: list[dict[str, Any]] = []
    observed_assets: list[str] = []
    missing_assets: list[str] = []

    for asset in tracked_assets:
        per_window = [
            (window, window_results[window][asset])
            for window in ordered_windows
            if asset in window_results.get(window, {})
        ]
        if not per_window:
            missing_assets.append(asset)
            assets.append(
                {
                    "asset": asset,
                    "status": "missing",
                    "expected_direction": expected.get(asset),
                    "baseline_time": None,
                    "baseline_close": None,
                    "latest_window": None,
                    "latest_observed_time": None,
                    "latest_direction": None,
                    "latest_pct_change": None,
                    "latest_change_bp": None,
                    "any_threshold_hit": False,
                    "confirmed_in_any_window": False,
                    "contradicted_in_any_window": False,
                    "observed_window_count": 0,
                }
            )
            continue

        observed_assets.append(asset)
        latest_window, latest_result = per_window[-1]
        assets.append(
            {
                "asset": asset,
                "status": "observed",
                "expected_direction": expected.get(asset),
                "baseline_time": per_window[0][1].get("baseline_time"),
                "baseline_close": per_window[0][1].get("baseline_close"),
                "latest_window": latest_window,
                "latest_observed_time": latest_result.get("after_time"),
                "latest_direction": latest_result.get("direction"),
                "latest_pct_change": latest_result.get("pct_change"),
                "latest_change_bp": latest_result.get("change_bp"),
                "any_threshold_hit": any(bool(result.get("threshold_hit")) for _, result in per_window),
                "confirmed_in_any_window": any(bool(result.get("confirms_expected_direction")) for _, result in per_window),
                "contradicted_in_any_window": any(bool(result.get("contradicts_expected_direction")) for _, result in per_window),
                "observed_window_count": len(per_window),
            }
        )

    return {
        "event_time": _iso(event_time),
        "requested_assets": tracked_assets,
        "observed_assets": observed_assets,
        "missing_assets": missing_assets,
        "primary_window": primary_window,
        "assets": assets,
    }


def _parse_time(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None
