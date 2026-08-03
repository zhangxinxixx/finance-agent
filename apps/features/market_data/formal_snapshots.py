"""Pure, fail-closed formal market snapshots for the Gold policy seam."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.features.market_data.canonical_candles import (
    is_xauusd_compatible_row,
    select_canonical_xauusd_rows,
)
from apps.features.market_data.source_role_policy import qualify_market_source


QualityStatus = Literal["accepted", "observe", "blocked"]
FreshnessStatus = Literal["fresh", "stale", "missing"]
AlignmentStatus = Literal["aligned", "misaligned", "unknown"]

_FRESH_5M = timedelta(minutes=10)
_OBSERVE_5M = timedelta(hours=2)
_FRESH_DAILY = timedelta(days=3)  # accommodates a normal weekend close gap
_OBSERVE_DAILY = timedelta(days=6)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalSourceReference(_Frozen):
    source: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    raw_path: str | None = None
    retrieved_at: datetime
    qualification_reason: str
    normalized_role: str

    @model_validator(mode="after")
    def _require_aware_retrieval_time(self) -> "FormalSourceReference":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("source reference retrieved_at must be timezone-aware")
        return self


class FormalMarketObservation(_Frozen):
    series_id: str
    asset: str
    market_role: Literal["spot", "futures", "oil", "index", "volatility_index"]
    timeframe: Literal["5m", "1d"]
    value: float | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    bar_open_time: datetime | None
    bar_close_time: datetime | None
    expected_frequency: str
    freshness_status: FreshnessStatus
    quality_status: QualityStatus
    alignment_status: AlignmentStatus
    source_refs: tuple[FormalSourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _missing_requires_empty_bar(self) -> "FormalMarketObservation":
        values = (self.value, self.open, self.high, self.low, self.close, self.bar_open_time, self.bar_close_time)
        if self.freshness_status == "missing" and any(value is not None for value in values):
            raise ValueError("missing observations must not contain a market bar")
        if self.freshness_status != "missing":
            if any(value is None for value in values):
                raise ValueError("present observations require complete OHLC and bar times")
            if self.value != self.close:
                raise ValueError("formal market observation value must equal close")
            if not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
                raise ValueError("OHLC values must satisfy low <= open/close <= high")
            if not self.low <= self.high:
                raise ValueError("OHLC values must satisfy low <= high")
            if any(
                value.tzinfo is None or value.utcoffset() is None
                for value in (self.bar_open_time, self.bar_close_time)
            ):
                raise ValueError("market bar times must be timezone-aware")
        return self


class _Snapshot(_Frozen):
    as_of: datetime
    readiness: Literal["ready", "observe", "blocked"]

    @model_validator(mode="after")
    def _require_aware_as_of(self) -> "_Snapshot":
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("snapshot as_of must be timezone-aware")
        return self


class MarketPriceSnapshot(_Snapshot):
    schema_version: Literal["market_price_snapshot.v1"] = "market_price_snapshot.v1"
    xauusd_spot: FormalMarketObservation
    gc_futures: FormalMarketObservation

    @model_validator(mode="after")
    def _market_contract(self) -> "MarketPriceSnapshot":
        _require_identity(self.xauusd_spot, "XAUUSD_SPOT", "XAUUSD", "spot", "5m")
        _require_identity(self.gc_futures, "GC_FUTURES", "GC", "futures", "1d")
        _require_readiness(self.readiness, self.xauusd_spot, self.gc_futures)
        return self


class OilSnapshot(_Snapshot):
    schema_version: Literal["oil_snapshot.v1"] = "oil_snapshot.v1"
    wti: FormalMarketObservation
    brent: FormalMarketObservation

    @model_validator(mode="after")
    def _oil_contract(self) -> "OilSnapshot":
        _require_identity(self.wti, "WTI", "WTI", "oil", "1d")
        _require_identity(self.brent, "BRENT", "BRENT", "oil", "1d")
        _require_readiness(self.readiness, self.wti, self.brent)
        return self


class MarketContextSnapshot(_Snapshot):
    """Supplemental cross-market context, isolated from the Gold input contract."""

    schema_version: Literal["market_context_snapshot.v1"] = "market_context_snapshot.v1"
    xagusd_spot: FormalMarketObservation
    dxy: FormalMarketObservation
    vix: FormalMarketObservation

    @model_validator(mode="after")
    def _market_context_contract(self) -> "MarketContextSnapshot":
        _require_identity(self.xagusd_spot, "XAGUSD_SPOT", "XAGUSD", "spot", "1d")
        _require_identity(self.dxy, "DXY", "DXY", "index", "1d")
        _require_identity(self.vix, "VIX", "VIX", "volatility_index", "1d")
        _require_market_context_readiness(self.readiness, self.xagusd_spot, self.dxy, self.vix)
        return self


def build_market_price_snapshot(*, candidates: Iterable[Mapping[str, Any]], as_of: datetime) -> MarketPriceSnapshot:
    """Build canonical XAUUSD spot and distinct GC futures observations."""

    point_in_time = _aware_utc(as_of)
    rows = tuple(dict(row) for row in candidates)
    spot = _select(rows, asset="XAUUSD", series_id="XAUUSD_SPOT", role="spot", timeframe="5m", as_of=point_in_time)
    futures = _select(rows, asset="GC", series_id="GC_FUTURES", role="futures", timeframe="1d", as_of=point_in_time)
    return MarketPriceSnapshot(as_of=point_in_time, readiness=_readiness(spot, futures), xauusd_spot=spot, gc_futures=futures)


def build_oil_snapshot(*, candidates: Iterable[Mapping[str, Any]], as_of: datetime) -> OilSnapshot:
    """Build WTI and Brent snapshots only from explicit structured daily bars."""

    point_in_time = _aware_utc(as_of)
    rows = tuple(dict(row) for row in candidates)
    wti = _select(rows, asset="WTI", series_id="WTI", role="oil", timeframe="1d", as_of=point_in_time)
    brent = _select(rows, asset="BRENT", series_id="BRENT", role="oil", timeframe="1d", as_of=point_in_time)
    return OilSnapshot(as_of=point_in_time, readiness=_readiness(wti, brent), wti=wti, brent=brent)


def build_market_context_snapshot(*, candidates: Iterable[Mapping[str, Any]], as_of: datetime) -> MarketContextSnapshot:
    """Build explicit XAGUSD, DXY, and VIX context without changing Gold inputs."""

    point_in_time = _aware_utc(as_of)
    rows = tuple(dict(row) for row in candidates)
    xagusd = _select(rows, asset="XAGUSD", series_id="XAGUSD_SPOT", role="spot", timeframe="1d", as_of=point_in_time)
    dxy = _select(rows, asset="DXY", series_id="DXY", role="index", timeframe="1d", as_of=point_in_time)
    vix = _select(rows, asset="VIX", series_id="VIX", role="volatility_index", timeframe="1d", as_of=point_in_time)
    return MarketContextSnapshot(
        as_of=point_in_time,
        readiness=_market_context_readiness(xagusd, dxy, vix),
        xagusd_spot=xagusd,
        dxy=dxy,
        vix=vix,
    )


def _select(rows: tuple[dict[str, Any], ...], *, asset: str, series_id: str, role: Literal["spot", "futures", "oil", "index", "volatility_index"], timeframe: Literal["5m", "1d"], as_of: datetime) -> FormalMarketObservation:
    matching = [row for row in rows if str(row.get("asset") or "").upper() == asset and row.get("timeframe") == timeframe]
    if asset == "XAUUSD":
        matching = [row for row in matching if is_xauusd_compatible_row(row)]
        matching = [dict(row) for row in select_canonical_xauusd_rows(matching)]
    checked = [_checked_row(row, asset=asset, timeframe=timeframe, as_of=as_of) for row in matching]
    completed = [item for item in checked if item["eligible"]]
    if not completed:
        reason = "no_candidate" if not matching else _no_completed_reason(checked)
        alignment: AlignmentStatus = "misaligned" if reason == "future_or_incomplete_bar" else "unknown"
        return _missing(series_id, asset, role, timeframe, as_of, reason, checked, alignment=alignment)
    latest_close = max(item["bar_close_time"] for item in completed)
    latest = [item for item in completed if item["bar_close_time"] == latest_close]
    providers = {item["source"] for item in latest}
    if len(latest) != 1 or len(providers) != 1:
        return _missing(series_id, asset, role, timeframe, as_of, "ambiguous_provider", latest, alignment="misaligned")
    selected = latest[0]
    freshness, expired = _freshness(as_of - selected["bar_close_time"], timeframe)
    quality = selected["qualification"].quality_status
    if expired:
        quality = "blocked"
    elif freshness == "stale" and quality == "accepted":
        quality = "observe"
    return FormalMarketObservation(
        series_id=series_id, asset=asset, market_role=role, timeframe=timeframe,
        value=selected["close"], open=selected["open"], high=selected["high"], low=selected["low"], close=selected["close"],
        bar_open_time=selected["bar_open_time"], bar_close_time=selected["bar_close_time"],
        expected_frequency=timeframe, freshness_status=freshness, quality_status=quality, alignment_status="aligned",
        source_refs=(selected["source_ref"],),
    )


def _checked_row(row: dict[str, Any], *, asset: str, timeframe: str, as_of: datetime) -> dict[str, Any]:
    source = str(row.get("source") or "")
    source_ref = row.get("source_ref") if isinstance(row.get("source_ref"), Mapping) else {}
    qualification = qualify_market_source(asset=asset, source=source, source_ref=source_ref)
    retrieved_at = _retrieval_time(row, source_ref)
    ref = _source_ref(row, qualification_reason=qualification.reason_code, normalized_role=qualification.normalized_role, retrieved_at=retrieved_at)
    open_time = _parse_time(row.get("open_time"))
    close_time = _parse_time(row.get("close_time"))
    expected_duration = timedelta(minutes=5) if timeframe == "5m" else timedelta(days=1)
    if close_time is None and open_time is not None:
        close_time = open_time + expected_duration
    retrieval_after_as_of = retrieved_at is not None and retrieved_at > as_of
    future_or_incomplete = (close_time is not None and close_time > as_of) or retrieval_after_as_of
    ohlc = tuple(_number(row.get(name)) for name in ("open", "high", "low", "close"))
    reason = "eligible"
    eligible = qualification.quality_status != "blocked"
    if not source:
        eligible, reason = False, "source_missing"
    elif retrieved_at is None:
        eligible, reason = False, "retrieval_time_missing"
    elif retrieval_after_as_of:
        eligible, reason = False, "retrieval_time_after_as_of"
    elif any(value is None for value in ohlc):
        eligible, reason = False, "ohlc_missing"
    elif open_time is None or close_time is None:
        eligible, reason = False, "bar_time_missing"
    elif future_or_incomplete:
        eligible, reason = False, "future_or_incomplete_bar"
    elif close_time <= open_time:
        eligible, reason = False, "bar_time_invalid"
    elif close_time - open_time != expected_duration:
        eligible, reason = False, "bar_duration_mismatch"
    elif not _valid_ohlc(ohlc):
        eligible, reason = False, "ohlc_invalid"
    elif qualification.quality_status == "blocked":
        reason = qualification.reason_code
    if ref is not None and not eligible:
        ref = ref.model_copy(update={"qualification_reason": reason})
    return {"eligible": eligible, "reason": reason, "future_or_incomplete": future_or_incomplete, "source": source, "source_ref": ref or _query_ref(asset, timeframe, as_of, reason), "qualification": qualification, "bar_open_time": open_time, "bar_close_time": close_time, "open": ohlc[0], "high": ohlc[1], "low": ohlc[2], "close": ohlc[3]}


def _missing(series_id: str, asset: str, role: Literal["spot", "futures", "oil", "index", "volatility_index"], timeframe: Literal["5m", "1d"], as_of: datetime, reason: str, checked: list[dict[str, Any]], *, alignment: AlignmentStatus = "unknown") -> FormalMarketObservation:
    refs = tuple(item["source_ref"] for item in checked) or (_query_ref(asset, timeframe, as_of, reason),)
    return FormalMarketObservation(series_id=series_id, asset=asset, market_role=role, timeframe=timeframe, value=None, open=None, high=None, low=None, close=None, bar_open_time=None, bar_close_time=None, expected_frequency=timeframe, freshness_status="missing", quality_status="blocked", alignment_status=alignment, source_refs=refs)


def _source_ref(row: Mapping[str, Any], *, qualification_reason: str, normalized_role: str, retrieved_at: datetime | None) -> FormalSourceReference | None:
    if retrieved_at is None:
        return None
    raw = row.get("source_ref") if isinstance(row.get("source_ref"), Mapping) else {}
    raw_path = row.get("raw_path") or raw.get("raw_path")
    reference = raw.get("source_url") or raw.get("reference") or raw_path or str(row.get("source") or "market_candidate")
    return FormalSourceReference(source=str(row.get("source") or "market_candidate"), reference=str(reference), raw_path=str(raw_path) if raw_path else None, retrieved_at=retrieved_at, qualification_reason=qualification_reason, normalized_role=normalized_role)


def _query_ref(asset: str, timeframe: str, as_of: datetime, reason: str) -> FormalSourceReference:
    return FormalSourceReference(source="formal_market_snapshot_query", reference=f"query://{asset}/{timeframe}", retrieved_at=as_of, qualification_reason=reason, normalized_role="query")


def _freshness(age: timedelta, timeframe: str) -> tuple[FreshnessStatus, bool]:
    threshold = _FRESH_5M if timeframe == "5m" else _FRESH_DAILY
    observe = _OBSERVE_5M if timeframe == "5m" else _OBSERVE_DAILY
    return ("fresh", False) if age <= threshold else ("stale", False) if age <= observe else ("stale", True)


def _readiness(*observations: FormalMarketObservation) -> Literal["ready", "observe", "blocked"]:
    if any(item.quality_status == "blocked" or item.alignment_status == "misaligned" for item in observations):
        return "blocked"
    if any(item.quality_status == "observe" or item.freshness_status == "stale" or item.alignment_status == "unknown" for item in observations):
        return "observe"
    return "ready"


def _market_context_readiness(
    *observations: FormalMarketObservation,
) -> Literal["ready", "observe", "blocked"]:
    usable = [
        item
        for item in observations
        if item.value is not None and item.quality_status != "blocked" and item.alignment_status != "misaligned"
    ]
    if not usable:
        return "blocked"
    if len(usable) != len(observations) or any(
        item.quality_status == "observe" or item.freshness_status == "stale" or item.alignment_status == "unknown"
        for item in usable
    ):
        return "observe"
    return "ready"


def _no_completed_reason(rows: list[dict[str, Any]]) -> str:
    if any(row["future_or_incomplete"] for row in rows):
        return "future_or_incomplete_bar"
    return sorted(str(row["reason"]) for row in rows)[0] if rows else "no_candidate"


def _require_identity(observation: FormalMarketObservation, series_id: str, asset: str, role: str, timeframe: str) -> None:
    if (observation.series_id, observation.asset, observation.market_role, observation.timeframe) != (series_id, asset, role, timeframe):
        raise ValueError(f"observation must be {series_id}/{asset}/{role}/{timeframe}")


def _require_readiness(
    actual: str, *observations: FormalMarketObservation
) -> None:
    expected = _readiness(*observations)
    if actual != expected:
        raise ValueError(f"snapshot readiness must be {expected}")


def _require_market_context_readiness(actual: str, *observations: FormalMarketObservation) -> None:
    expected = _market_context_readiness(*observations)
    if actual != expected:
        raise ValueError(f"snapshot readiness must be {expected}")


def _retrieval_time(row: Mapping[str, Any], source_ref: Mapping[str, Any]) -> datetime | None:
    for value in (row.get("retrieved_at"), source_ref.get("retrieved_at"), row.get("updated_at"), source_ref.get("updated_at"), row.get("created_at"), source_ref.get("created_at")):
        if (parsed := _parse_time(value)) is not None:
            return parsed
    return None


def _valid_ohlc(values: tuple[float | None, ...]) -> bool:
    open_value, high, low, close = values
    return all(value is not None for value in values) and low <= open_value <= high and low <= close <= high


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _aware_utc(value)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware_utc(parsed) if parsed.tzinfo is not None else None


def _number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None
