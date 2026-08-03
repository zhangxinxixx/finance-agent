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


def _v2(snapshot, **changes):
    payload = snapshot.model_dump(mode="json", exclude={"data_quality", "payload_hash", "snapshot_id"})
    direct = payload.pop("real10y")
    direct["market_role"] = "real_yield_direct"
    payload.update(schema_version="feature_snapshot.v2", real10y_direct=direct)
    for dotted_key, value in changes.items():
        target = payload
        path = dotted_key.split(".")
        for part in path[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        if isinstance(target, list):
            target[int(path[-1])] = value
        else:
            target[path[-1]] = value
    _clamp_source_ref_times(payload, payload["as_of"])
    return build_feature_snapshot(payload)


def _clamp_source_ref_times(value, cutoff: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_refs", "reaction_source_refs"} and isinstance(child, list):
                for reference in child:
                    if isinstance(reference, dict):
                        reference["retrieved_at"] = cutoff
            else:
                _clamp_source_ref_times(child, cutoff)
    elif isinstance(value, list):
        for child in value:
            _clamp_source_ref_times(child, cutoff)


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


def test_v2_attribution_uses_estimated_real_yield_not_direct_cross_check() -> None:
    previous = _v2(_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"))
    current = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        **{
            "as_of": "2025-01-21T21:00:00Z",
            "xauusd_spot.value": 2720.0,
            "us10y.value": 4.55,
            "real10y_direct.value": 1.00,
        },
    )
    changed_direct = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        **{
            "as_of": "2025-01-21T21:00:00Z",
            "xauusd_spot.value": 2720.0,
            "us10y.value": 4.55,
            "real10y_direct.value": 3.00,
        },
    )

    result = attribute_gold_price(current, previous)
    direct_only = attribute_gold_price(changed_direct, previous)

    result_drivers = (*result.primary_drivers, *result.secondary_drivers, *result.counter_drivers)
    direct_drivers = (*direct_only.primary_drivers, *direct_only.secondary_drivers, *direct_only.counter_drivers)
    assert [(driver.factor, driver.direction, driver.delta) for driver in result_drivers] == [
        (driver.factor, driver.direction, driver.delta) for driver in direct_drivers
    ]
    real_driver = next(driver for driver in result_drivers if driver.factor == "real_yield")
    assert real_driver.previous_value == previous.real10y_estimated.value
    assert real_driver.current_value == current.real10y_estimated.value


def test_v2_estimated_change_is_attributable_when_direct_is_missing() -> None:
    previous = _v2(_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"))
    current = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        **{
            "as_of": "2025-01-21T21:00:00Z",
            "xauusd_spot.value": 2720.0,
            "us10y.value": 4.55,
            "real10y_direct.value": None,
            "real10y_direct.freshness_status": "missing",
            "real10y_direct.quality_status": "blocked",
            "real10y_direct.alignment_status": "unknown",
        },
    )

    result = attribute_gold_price(current, previous)

    real_driver = next(
        driver
        for driver in (*result.primary_drivers, *result.secondary_drivers, *result.counter_drivers)
        if driver.factor == "real_yield"
    )
    assert real_driver.current_value == current.real10y_estimated.value


def test_mixed_feature_snapshot_versions_do_not_create_real_yield_attribution_delta() -> None:
    v1_previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    v2_current = _v2(
        v1_previous,
        **{
            "as_of": "2025-01-21T21:00:00Z",
            "xauusd_spot.value": 2720.0,
            "us10y.value": 4.55,
            "broad_dollar.value": 120.60,
        },
    )

    result = attribute_gold_price(v2_current, v1_previous)
    reverse = attribute_gold_price(v1_previous, _v2(v1_previous))
    drivers = (*result.primary_drivers, *result.secondary_drivers, *result.counter_drivers)
    reverse_drivers = (
        *reverse.primary_drivers,
        *reverse.secondary_drivers,
        *reverse.counter_drivers,
    )

    assert result.reason_codes == ("REAL10Y_SCHEMA_TRANSITION_NO_DELTA",)
    assert all(driver.factor != "real_yield" for driver in drivers)
    assert any(driver.factor == "broad_dollar" for driver in drivers)
    assert reverse.reason_codes == ("REAL10Y_SCHEMA_TRANSITION_NO_DELTA",)
    assert all(driver.factor != "real_yield" for driver in reverse_drivers)


def test_v2_official_event_driver_requires_ready_event_attribution_domain() -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    base = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    changes = {
        "xauusd_spot.value": 2720.0,
        "official_events.events.0.reaction_status": "confirmed",
        "official_events.events.0.reaction_return_pct": 0.62,
        "official_events.events.0.reaction_source_refs": [
            {
                "source": "fixture",
                "reference": "contract://event-ready/xauusd-reaction-window",
                "retrieved_at": "2025-01-29T21:00:00Z",
            }
        ],
    }
    ready = _v2(base, **changes)
    observe = _v2(base, **changes, **{"official_events.quality_status": "observe"})
    blocked = _v2(base, **changes, **{"official_events.quality_status": "blocked"})

    assert ready.data_quality.event_attribution_readiness == "ready"
    assert observe.data_quality.event_attribution_readiness == "observe"
    assert blocked.data_quality.event_attribution_readiness == "blocked"

    ready_result = attribute_gold_price(ready, previous)
    observe_result = attribute_gold_price(observe, previous)
    blocked_result = attribute_gold_price(blocked, previous)

    assert any(driver.factor == "official_event" for driver in ready_result.primary_drivers)
    assert all(driver.factor != "official_event" for driver in observe_result.primary_drivers)
    assert all(driver.factor != "official_event" for driver in blocked_result.primary_drivers)
    assert "EVENT_ATTRIBUTION_READINESS_OBSERVE" in observe_result.reason_codes
    assert "EVENT_ATTRIBUTION_READINESS_BLOCKED" in blocked_result.reason_codes


def test_forged_v2_event_readiness_cannot_bypass_attribution_gate() -> None:
    previous = _v2(_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"))
    current = _v2(_snapshot("feature_snapshot_v1_event_flat_2025-01-29.json"))
    forged_quality = current.data_quality.model_copy(
        update={"event_attribution_readiness": "ready"}
    )
    forged = current.model_copy(update={"data_quality": forged_quality})

    result = attribute_gold_price(forged, previous)

    assert result.attribution_status == "unconfirmed"
    assert result.primary_drivers == ()
    assert result.reason_codes == ("FEATURE_SNAPSHOT_DERIVATION_INVALID",)
