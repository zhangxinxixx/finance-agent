"""Deterministic source-role eligibility for formal market observations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from database.market_identity import is_xauusd_spot_identity


QualityStatus = Literal["accepted", "observe", "blocked"]

_GC_YAHOO_SOURCES = frozenset({"yahoo_finance_gc_f"})
_VALIDATION_ROLES = frozenset({"validation", "fallback", "validation_and_fallback"})


class SourceEligibility(BaseModel):
    """Immutable formal eligibility outcome for one market source reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quality_status: QualityStatus
    reason_code: str
    normalized_role: str


def qualify_market_source(
    *, asset: str, source: str, source_ref: Mapping[str, Any]
) -> SourceEligibility:
    """Classify a market observation without catalog, network, or LLM access."""

    normalized_asset = str(asset).strip().upper()
    normalized_source = str(source).strip().lower()
    ref = dict(source_ref)
    role = _normalized_role(ref, normalized_source)
    instrument_type = str(ref.get("instrument_type") or "").strip().lower()
    provider_symbol = str(
        ref.get("provider_symbol") or ref.get("symbol") or ref.get("ticker") or ""
    ).strip().upper()

    if normalized_asset == "GC":
        return _qualify_gc(
            source=normalized_source,
            provider_symbol=provider_symbol,
            instrument_type=instrument_type,
            role=role,
        )

    if normalized_asset == "XAUUSD":
        if instrument_type.startswith("futures") or provider_symbol == "GC=F":
            return _blocked("futures_instrument_blocked", role)
        if not is_xauusd_spot_identity(asset=normalized_asset, source=source, source_ref=ref):
            return _blocked("xauusd_spot_identity_rejected", role)
        if normalized_source.startswith("twelvedata"):
            if role == "validation_fallback":
                return _observe("twelvedata_validation_or_fallback", role)
            return _blocked("twelvedata_cannot_be_market_primary", role)
        if role == "market_primary":
            return _accepted("market_primary", role)
        if role == "validation_fallback":
            return _observe("validation_or_fallback", role)
        return _blocked(f"xauusd_{role}_not_eligible", role)

    if normalized_asset in {"WTI", "BRENT"}:
        if role in {"oil_primary", "market_primary"}:
            return _accepted("oil_or_market_primary", role)
        if role == "validation_fallback":
            return _observe("oil_validation_or_fallback", role)
        return _blocked(f"oil_{role}_not_eligible", role)

    return _blocked("unsupported_market_asset", role)


def _qualify_gc(
    *, source: str, provider_symbol: str, instrument_type: str, role: str
) -> SourceEligibility:
    if (
        source in _GC_YAHOO_SOURCES
        and provider_symbol == "GC=F"
        and instrument_type == "futures_continuous_proxy"
    ):
        return _accepted("gc_yahoo_futures_continuous_proxy", "futures_continuous_proxy")
    return _blocked("gc_identity_or_source_rejected", role)


def _normalized_role(source_ref: Mapping[str, Any], source: str) -> str:
    role = str(source_ref.get("source_role") or source_ref.get("provider_role") or "").strip().lower()
    if "news" in role or "news" in source:
        return "news"
    if role in {"market_primary", "oil_primary"}:
        return role
    if role in _VALIDATION_ROLES:
        return "validation_fallback"
    if role.startswith("staging"):
        return "staging"
    if role in {"supplemental", "supplemental_source"}:
        return "supplemental"
    return "unknown"


def _accepted(reason_code: str, normalized_role: str) -> SourceEligibility:
    return SourceEligibility(
        quality_status="accepted", reason_code=reason_code, normalized_role=normalized_role
    )


def _observe(reason_code: str, normalized_role: str) -> SourceEligibility:
    return SourceEligibility(
        quality_status="observe", reason_code=reason_code, normalized_role=normalized_role
    )


def _blocked(reason_code: str, normalized_role: str) -> SourceEligibility:
    return SourceEligibility(
        quality_status="blocked", reason_code=reason_code, normalized_role=normalized_role
    )
