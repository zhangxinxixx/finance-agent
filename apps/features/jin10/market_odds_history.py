from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from apps.features.jin10.schemas.market_odds import Jin10MarketOddsEvidence, MarketOddsEvidenceItem

_EVENT_KEY_FIELDS = (
    "asset",
    "event_type",
    "predicate",
    "target_value",
    "target_unit",
    "probability_semantics",
    "horizon_start",
    "horizon_end",
)


def build_comparable_market_odds_trends(features: Iterable[Jin10MarketOddsEvidence]) -> list[dict[str, Any]]:
    """Build trends only for accepted items with identical event definitions."""
    grouped: dict[tuple[Any, ...], list[tuple[Jin10MarketOddsEvidence, MarketOddsEvidenceItem]]] = {}
    for feature in features:
        for item in feature.items:
            if item.extraction_status != "accepted":
                continue
            key = tuple(getattr(item, field) for field in _EVENT_KEY_FIELDS)
            grouped.setdefault(key, []).append((feature, item))
    trends: list[dict[str, Any]] = []
    for key, observations in grouped.items():
        if len(observations) < 2:
            continue
        observations.sort(key=lambda pair: pair[0].published_at)
        points = [
            {
                "article_id": feature.article_id,
                "as_of": feature.published_at,
                "probability": item.probability,
                "item_id": item.item_id,
                "evidence_refs": item.evidence_refs,
            }
            for feature, item in observations
        ]
        trends.append({
            "event_key": dict(zip(_EVENT_KEY_FIELDS, key)),
            "change_type": "probability_change",
            "points": points,
            "probability_change": round(points[-1]["probability"] - points[0]["probability"], 10),
        })
    return trends


def write_rebuild_bundle(
    features: Iterable[Jin10MarketOddsEvidence],
    *,
    storage_root: Path,
    rebuild_id: str,
) -> Path:
    """Write a versioned rebuild bundle without touching canonical history."""
    feature_list = list(features)
    root = storage_root / "rebuilds" / "jin10_market_odds" / rebuild_id
    if root.exists():
        raise FileExistsError(f"rebuild bundle already exists: {root}")
    artifact_rows: list[dict[str, Any]] = []
    for feature in feature_list:
        article_dir = root / feature.article_id
        article_dir.mkdir(parents=True, exist_ok=False)
        artifact = article_dir / "market_odds_evidence.json"
        artifact.write_text(feature.model_dump_json(indent=2) + "\n", encoding="utf-8")
        artifact_rows.append({
            "article_id": feature.article_id,
            "published_at": feature.published_at,
            "schema_version": feature.schema_version,
            "parser_version": feature.parser_version,
            "extraction_status": feature.extraction_status,
            "panel_count": feature.panel_count,
            "item_count": len(feature.items),
            "artifact_path": artifact.relative_to(storage_root).as_posix(),
        })
    trends = build_comparable_market_odds_trends(feature_list)
    trends_path = root / "comparable_trends.json"
    trends_path.write_text(json.dumps(trends, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = root / "rebuild_manifest.json"
    manifest.write_text(json.dumps({
        "rebuild_id": rebuild_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_history_overwritten": False,
        "artifact_count": len(artifact_rows),
        "comparable_trend_count": len(trends),
        "artifacts": artifact_rows,
        "trends_path": trends_path.relative_to(storage_root).as_posix(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
