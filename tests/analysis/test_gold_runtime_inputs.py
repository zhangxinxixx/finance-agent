from __future__ import annotations

import pytest


def test_current_feature_adapter_does_not_resolve_previous_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.analysis.gold_policy import runtime_inputs

    current = object()
    monkeypatch.setattr(
        runtime_inputs,
        "build_feature_snapshot_from_analysis_snapshot",
        lambda _: current,
    )

    def fail_lookup(**kwargs):
        pytest.fail("current-only adapter must not resolve a previous snapshot")

    monkeypatch.setattr(runtime_inputs, "load_previous_feature_snapshot", fail_lookup)

    assert runtime_inputs.prepare_gold_policy_current_feature(snapshot={"asset": "XAUUSD"}) is current
