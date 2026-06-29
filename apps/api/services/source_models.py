from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SourceTier(str, Enum):
    OFFICIAL_PRIMARY = "official_primary"
    MARKET_PRIMARY = "market_primary"
    SUPPLEMENTAL = "supplemental"
    CANDIDATE = "candidate"
    INFERENCE = "inference"


@dataclass(frozen=True)
class SourceDefinition:
    source_key: str
    source_name: str
    source_group: str
    source_type: str
    access_method: str
    metadata: dict[str, Any]
    source_tier: SourceTier

    @property
    def provider_role(self) -> str:
        return str(self.metadata.get("provider_role") or "derived")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "SourceDefinition":
        metadata = dict(payload.get("metadata") or {})
        return cls(
            source_key=str(payload.get("source_key") or ""),
            source_name=str(payload.get("source_name") or payload.get("source_key") or ""),
            source_group=str(payload.get("source_group") or "unknown"),
            source_type=str(payload.get("source_type") or "unknown"),
            access_method=str(payload.get("access_method") or "unknown"),
            metadata=metadata,
            source_tier=source_tier_from_definition(payload, metadata),
        )

    def governance_metadata(self) -> dict[str, Any]:
        metadata = dict(self.metadata)
        metadata["provider_role"] = self.provider_role
        metadata["source_tier"] = self.source_tier.value
        return metadata


@dataclass(frozen=True)
class SourceHealth:
    source_key: str
    source_tier: SourceTier
    freshness_score: float
    staleness_seconds: int | None
    quality_score: float
    readiness_state: str
    last_success_at: str | None
    last_failure_at: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_tier": self.source_tier.value,
            "freshness_score": self.freshness_score,
            "staleness_seconds": self.staleness_seconds,
            "quality_score": self.quality_score,
            "readiness_state": self.readiness_state,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
        }


def source_tier_from_definition(payload: dict[str, Any], metadata: dict[str, Any]) -> SourceTier:
    source_key = str(payload.get("source_key") or "")
    provider_role = str(metadata.get("provider_role") or "").strip().lower()
    event_layer = str(metadata.get("event_layer") or "").strip().lower()

    if source_key == "dxy":
        return SourceTier.MARKET_PRIMARY
    if provider_role == "official_primary":
        return SourceTier.OFFICIAL_PRIMARY
    if provider_role in {"aggregator", "wire_public_candidate", "candidate"} or event_layer == "candidate_event_radar":
        return SourceTier.CANDIDATE
    if provider_role in {"derived", "inference"}:
        return SourceTier.INFERENCE
    return SourceTier.SUPPLEMENTAL
