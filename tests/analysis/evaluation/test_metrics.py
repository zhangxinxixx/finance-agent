from __future__ import annotations

import pytest

from apps.analysis.evaluation.metrics import aggregate_outcome_metrics


def _outcome(
    evaluation_id: str,
    horizon: str,
    *,
    status: str = "scored",
    classification: str = "correct",
    direction_accuracy: str = "correct",
    mfe: float | None = 2.0,
    mae: float | None = 0.5,
    lifecycle_status: str | None = None,
) -> dict[str, object]:
    return {
        "evaluation_id": evaluation_id,
        "horizon": horizon,
        "status": status,
        "classification": classification,
        "direction_accuracy": direction_accuracy,
        "mfe": mfe,
        "mae": mae,
        **({"lifecycle_status": lifecycle_status} if lifecycle_status is not None else {}),
    }


def test_mixed_statuses_keep_accuracy_denominator_explicit() -> None:
    result = aggregate_outcome_metrics(
        [
            _outcome("a", "1h", lifecycle_status="triggered"),
            _outcome(
                "b", "1h", classification="incorrect", direction_accuracy="incorrect", lifecycle_status="triggered"
            ),
            _outcome("c", "1h", classification="neutral", direction_accuracy="neutral", lifecycle_status="triggered"),
            _outcome(
                "d",
                "1h",
                status="blocked",
                classification="blocked",
                direction_accuracy="not_applicable",
                mfe=None,
                mae=None,
                lifecycle_status="blocked",
            ),
            _outcome(
                "e",
                "1h",
                status="unscorable",
                classification="unscorable",
                direction_accuracy="not_applicable",
                mfe=None,
                mae=None,
                lifecycle_status="insufficient_market_path",
            ),
        ]
    )

    assert result["total_count"] == 5
    assert result["approved_count"] == 3
    assert result["verified_scored_count"] == 3
    assert result["legacy_unverified_count"] == 0
    assert result["blocked_count"] == 1
    assert result["unscorable_count"] == 1
    assert result["directional_count"] == 2
    assert result["correct_count"] == 1
    assert result["incorrect_count"] == 1
    assert result["accuracy"] == pytest.approx(0.5)
    assert result["classification_counts"]["neutral"] == 1
    assert result["by_horizon"]["1h"]["total_count"] == 5


def test_empty_and_non_scoreable_inputs_return_none_metrics() -> None:
    result = aggregate_outcome_metrics([])
    blocked = aggregate_outcome_metrics(
        [
            _outcome(
                "x",
                "4h",
                status="blocked",
                classification="blocked",
                direction_accuracy="not_applicable",
                mfe=None,
                mae=None,
            )
        ]
    )

    for value in (result, blocked):
        assert value["accuracy"] is None
        assert value["mfe_avg"] is None
        assert value["mae_avg"] is None
    assert result["total_count"] == 0
    assert result["by_horizon"] == {}


def test_blocked_mfe_and_mae_do_not_enter_approved_averages() -> None:
    result = aggregate_outcome_metrics(
        [
            _outcome("a", "1h", mfe=4.0, mae=2.0, lifecycle_status="triggered"),
            _outcome(
                "b",
                "1h",
                status="blocked",
                classification="blocked",
                direction_accuracy="not_applicable",
                mfe=100.0,
                mae=100.0,
                lifecycle_status="blocked",
            ),
        ]
    )

    assert result["mfe_avg"] == pytest.approx(4.0)
    assert result["mae_avg"] == pytest.approx(2.0)


def test_lifecycle_counts_distinguish_no_entry_and_ordered_stop_events() -> None:
    result = aggregate_outcome_metrics(
        [
            _outcome(
                "a",
                "1h",
                classification="hold",
                direction_accuracy="not_applicable",
                mfe=None,
                mae=None,
                lifecycle_status="never_triggered",
            ),
            _outcome(
                "b",
                "1h",
                classification="invalidated",
                direction_accuracy="not_applicable",
                mfe=None,
                mae=None,
                lifecycle_status="invalidated_before_entry",
            ),
            _outcome(
                "c",
                "1h",
                classification="invalidated",
                direction_accuracy="incorrect",
                lifecycle_status="triggered_then_invalidated",
            ),
            _outcome(
                "d",
                "1h",
                status="unscorable",
                classification="unscorable",
                direction_accuracy="not_applicable",
                mfe=None,
                mae=None,
                lifecycle_status="same_bar_ambiguous",
            ),
        ]
    )

    assert result["lifecycle_counts"]["never_triggered"] == 1
    assert result["lifecycle_counts"]["invalidated_before_entry"] == 1
    assert result["lifecycle_counts"]["triggered_then_invalidated"] == 1
    assert result["lifecycle_counts"]["same_bar_ambiguous"] == 1
    assert result["directional_count"] == 1


def test_horizon_filter_and_mapping_payload_are_supported() -> None:
    result = aggregate_outcome_metrics(
        [_outcome("a", "1h", lifecycle_status="triggered"), _outcome("b", "4h", lifecycle_status="triggered")],
        horizon="4h",
    )

    assert result["horizon"] == "4h"
    assert result["total_count"] == 1
    assert list(result["by_horizon"]) == ["4h"]


def test_duplicate_same_payload_is_ignored_and_conflict_is_rejected() -> None:
    first = _outcome("a", "1h", lifecycle_status="triggered")
    assert aggregate_outcome_metrics([first, dict(first)])["total_count"] == 1
    conflict = dict(first)
    conflict["mfe"] = 99.0
    with pytest.raises(ValueError, match="conflicting duplicate"):
        aggregate_outcome_metrics([first, conflict])


@pytest.mark.parametrize("bad_horizon", ["2h", "daily"])
def test_unknown_horizon_is_rejected(bad_horizon: str) -> None:
    with pytest.raises(ValueError, match="unsupported horizon"):
        aggregate_outcome_metrics([_outcome("a", bad_horizon, lifecycle_status="triggered")])


def test_legacy_outcome_is_visible_but_excluded_from_trusted_metrics() -> None:
    result = aggregate_outcome_metrics(
        [
            _outcome("legacy", "1h", classification="hold", direction_accuracy="correct", mfe=99.0, mae=88.0),
            _outcome("current", "1h", lifecycle_status="target_reached", mfe=3.0, mae=1.0),
        ]
    )

    assert result["scored_count"] == 2
    assert result["verified_scored_count"] == 1
    assert result["legacy_unverified_count"] == 1
    assert result["lifecycle_counts"]["legacy_unverified"] == 1
    assert result["lifecycle_counts"]["never_triggered"] == 0
    assert result["directional_count"] == 1
    assert result["accuracy"] == pytest.approx(1.0)
    assert result["mfe_avg"] == pytest.approx(3.0)
    assert result["mae_avg"] == pytest.approx(1.0)
