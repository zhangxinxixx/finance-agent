from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot


FIXTURES = Path(__file__).parents[1] / "fixtures" / "gold_policy"


def _snapshot(name: str):
    return build_feature_snapshot(json.loads((FIXTURES / name).read_text()))


def _changed(snapshot, **changes):
    payload = snapshot.model_dump(mode="json")
    payload.pop("data_quality")
    payload.pop("payload_hash")
    payload.pop("snapshot_id")
    for dotted_key, value in changes.items():
        target = payload
        path = dotted_key.split(".")
        for part in path[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        if isinstance(target, list):
            target[int(path[-1])] = value
        else:
            target[path[-1]] = value
    return build_feature_snapshot(payload)


def test_up_cross_asset_consistent_and_reproducible() -> None:
    previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    current = _changed(
        previous,
        **{
            "as_of": "2025-01-22T21:00:00Z",
            "xauusd_spot.value": 2700.0,
            "broad_dollar.value": 121.4,
            "real10y.value": 2.15,
        },
    )
    results = [attribute_gold_price(current, previous) for _ in range(100)]
    result = results[0]
    assert all(item == result for item in results)
    assert result.price_move == "up"
    assert result.current_snapshot_id == current.snapshot_id
    assert result.previous_snapshot_id == previous.snapshot_id
    assert result.attribution_status == "cross_asset_consistent"
    assert result.explained_ratio + result.unexplained_component == 1
    assert all(driver.source_refs for driver in result.primary_drivers)


def test_down_cross_asset_consistent() -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _changed(
        previous,
        **{
            "as_of": "2025-01-21T21:00:00Z",
            "xauusd_spot.value": 2670.0,
            "broad_dollar.value": 122.0,
            "real10y.value": 2.24,
        },
    )
    result = attribute_gold_price(current, previous)
    assert result.price_move == "down"
    assert result.attribution_status == "cross_asset_consistent"


def test_flat_is_unconfirmed_even_with_formal_event() -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    current = _changed(current, **{"xauusd_spot.value": previous.xauusd_spot.value + 0.1})
    result = attribute_gold_price(current, previous)
    assert result.price_move == "flat"
    assert result.attribution_status == "unconfirmed"
    assert result.explained_ratio == 0


def test_conflict_is_retained_and_unconfirmed() -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _changed(
        previous,
        **{
            "as_of": "2025-01-21T21:00:00Z",
            "xauusd_spot.value": 2720.0,
            "broad_dollar.value": 122.0,
            "real10y.value": 2.10,
        },
    )
    result = attribute_gold_price(current, previous)
    assert result.attribution_status == "unconfirmed"
    assert {driver.factor for driver in result.counter_drivers} == {"broad_dollar"}


def test_confirmed_official_event_requires_complete_timely_window() -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    current = _changed(
        current,
        **{
            "xauusd_spot.value": 2720.0,
            "official_events.events.0.reaction_status": "confirmed",
            "official_events.events.0.reaction_return_pct": 0.62,
            "official_events.events.0.reaction_source_refs": [
                {
                    "source": "fixture",
                    "reference": "contract://event-flat/xauusd-reaction-window",
                    "retrieved_at": "2025-01-29T21:00:00Z",
                }
            ],
        },
    )
    result = attribute_gold_price(current, previous)
    assert result.attribution_status == "confirmed_event"
    assert result.primary_drivers[0].factor == "official_event"

    observe_only = _changed(
        current,
        **{"official_events.quality_status": "observe"},
    )
    observe_result = attribute_gold_price(observe_only, previous)
    assert observe_result.attribution_status != "confirmed_event"
    assert all(driver.factor != "official_event" for driver in observe_result.primary_drivers)

    late_payload = current.model_dump(mode="json")
    for field in ("data_quality", "payload_hash", "snapshot_id"):
        late_payload.pop(field)
    late_payload["official_events"]["events"][0]["reaction_window_end"] = "2025-01-30T21:00:00Z"
    late = build_feature_snapshot(late_payload)
    late_result = attribute_gold_price(late, previous)
    assert late_result.attribution_status != "confirmed_event"


def test_event_without_structured_confirmed_reaction_is_not_confirmed() -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    current = _changed(current, **{"xauusd_spot.value": 2720.0})

    assert attribute_gold_price(current, previous).attribution_status != "confirmed_event"


def test_oil_path_requires_both_benchmarks_to_move_together() -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _changed(
        previous,
        **{
            "xauusd_spot.value": 2720.0,
            "wti.value": 79.0,
        },
    )

    result = attribute_gold_price(current, previous)
    assert all(
        driver.factor != "oil_inflation_path"
        for driver in result.primary_drivers + result.secondary_drivers + result.counter_drivers
    )


def test_blocked_data_fails_closed() -> None:
    blocked = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    result = attribute_gold_price(blocked, previous)
    assert result.attribution_status == "unconfirmed"
    assert result.explained_ratio == 0
    assert result.unexplained_component == 1


def test_missing_previous_snapshot_is_explicitly_unavailable() -> None:
    current = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    result = attribute_gold_price(current, None)

    assert result.price_move == "unavailable"
    assert result.attribution_status == "unconfirmed"
    assert result.previous_snapshot_id == "missing"
    assert result.reason_codes == ("PREVIOUS_FEATURE_SNAPSHOT_MISSING",)


def test_future_previous_snapshot_is_explicitly_unavailable() -> None:
    current = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    future_previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    result = attribute_gold_price(current, future_previous)

    assert result.price_move == "unavailable"
    assert result.attribution_status == "unconfirmed"
    assert result.reason_codes == ("PREVIOUS_SNAPSHOT_AFTER_CURRENT",)
