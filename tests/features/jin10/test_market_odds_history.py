import json

import pytest

from apps.features.jin10.market_odds_history import build_comparable_market_odds_trends, write_rebuild_bundle
from apps.features.jin10.schemas.market_odds import Jin10MarketOddsEvidence
from tests.api.test_report_market_odds_service import _payload


def _feature(article_id: str, published_at: str, probability: float, **item_updates):
    payload = _payload()
    payload["article_id"] = article_id
    payload["report_id"] = f"jin10:{article_id}"
    payload["feature_id"] = f"jin10-market-odds:{article_id}:{published_at}"
    payload["published_at"] = published_at
    payload["items"][0]["item_id"] = f"{article_id}:gold:4200"
    payload["items"][0]["probability"] = probability
    payload["items"][0].update(item_updates)
    return Jin10MarketOddsEvidence.model_validate(payload)


def test_trend_only_contains_identical_accepted_event_definitions() -> None:
    first = _feature("1", "2026-07-01T14:00:00+08:00", 0.80)
    second = _feature("2", "2026-07-02T14:00:00+08:00", 0.90)
    changed_target = _feature("3", "2026-07-03T14:00:00+08:00", 0.70, target_value=4300)
    needs_review = _feature("4", "2026-07-04T14:00:00+08:00", 0.95, extraction_status="needs_review", horizon_end="")
    trends = build_comparable_market_odds_trends([changed_target, second, needs_review, first])
    assert len(trends) == 1
    assert [point["article_id"] for point in trends[0]["points"]] == ["1", "2"]
    assert trends[0]["probability_change"] == 0.1


def test_rebuild_bundle_is_versioned_idempotency_guarded_and_preserves_history(tmp_path) -> None:
    canonical = tmp_path / "features" / "jin10" / "2026-07-01" / "1" / "market_odds_evidence.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("old", encoding="utf-8")
    manifest = write_rebuild_bundle(
        [_feature("1", "2026-07-01T14:00:00+08:00", 0.80)],
        storage_root=tmp_path,
        rebuild_id="issue-58-fixture",
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["canonical_history_overwritten"] is False
    assert canonical.read_text(encoding="utf-8") == "old"
    with pytest.raises(FileExistsError):
        write_rebuild_bundle([], storage_root=tmp_path, rebuild_id="issue-58-fixture")
