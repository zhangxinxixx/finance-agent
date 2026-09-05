"""Identity boundaries: canonical bundles, retained heads, and registry mismatch."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from apps.analysis.strategy.gold_baseline_adapter import resolve_verified_gold_baseline
from apps.api.services.gold_result_identity import (
    build_live_result_identity,
    build_mainline_result_identity,
    build_report_result_identity,
)
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_store import persist_gold_daily_close_run
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from tests.analysis.test_gold_daily_close_store import _persist_bootstrap, _next_pair
from tests.analysis.test_gold_key_level_policy import _event, _spec


def _report_args(root, write):
    manifest = json.loads((write.bundle_path / "report_manifest.json").read_text())
    return {
        "storage_root": root,
        "run_id": "run-bootstrap",
        "trade_date": write.bundle_path.parent.parent.name,
        "report_family": "gold_policy_daily_report",
        "report_snapshot_id": manifest["snapshot_id"],
        "report_identity": {"canonical_receipt_id": write.receipt_id},
    }


def test_verified_report_and_live_share_effective_identity(tmp_path):
    _, _, write, head = _persist_bootstrap(tmp_path)
    report = build_report_result_identity(**_report_args(tmp_path, write))
    baseline = resolve_verified_gold_baseline(storage_root=tmp_path, now=datetime.now(timezone.utc))
    live = build_live_result_identity(storage_root=tmp_path, baseline=baseline)
    assert report["subject"]["verification_status"] == "verified"
    assert report["relationship"]["status"] == "same_effective_head"
    assert live["relationship"]["status"] == "same_effective_head"
    for field in ("result_id", "feature_snapshot_id", "state_id", "strategy_id"):
        assert report["subject"][field] == live["subject"][field]
    assert live["subject"]["strategy_id"] == head.strategy_decision.decision_id
    mainlines = build_mainline_result_identity(storage_root=tmp_path, run_id="run-bootstrap")
    assert mainlines["relationship"]["status"] != "same_effective_head"


@pytest.mark.parametrize("field,value", [
    ("report_snapshot_id", "wrong-snapshot"),
    ("report_identity", {"canonical_receipt_id": "wrong-receipt"}),
    ("run_id", "../run-bootstrap"),
    ("trade_date", "../../outside"),
])
def test_untrusted_report_identity_never_becomes_verified(tmp_path, field, value):
    _, _, write, _ = _persist_bootstrap(tmp_path)
    kwargs = _report_args(tmp_path, write)
    kwargs[field] = value
    result = build_report_result_identity(**kwargs)
    assert result["subject"]["verification_status"] != "verified"
    assert result["relationship"]["status"] != "same_effective_head"


def test_live_identity_uses_already_resolved_head_without_reselection(tmp_path, monkeypatch):
    _, _, _, _ = _persist_bootstrap(tmp_path)
    baseline = resolve_verified_gold_baseline(storage_root=tmp_path, now=datetime.now(timezone.utc))
    original = dict(baseline)
    baseline["gold_head_held"] = True
    baseline["status"] = "held"
    baseline["reason_code"] = "gold_daily_close_head_held"

    def reselect(**kwargs):
        raise AssertionError("A live response must not select a second head")

    monkeypatch.setattr("apps.api.services.gold_result_identity.resolve_verified_gold_baseline", reselect)
    identity = build_live_result_identity(storage_root=tmp_path, baseline=baseline)
    assert identity["effective_baseline"]["held"] is True
    for field in ("result_id", "feature_snapshot_id", "state_id", "strategy_id"):
        assert identity["subject"][field] == original[field]
        assert identity["effective_baseline"][field] == original[field]


def test_real_hold_report_keeps_current_receipt_separate_from_predecessor(tmp_path):
    _, _, original_write, head = _persist_bootstrap(tmp_path)
    loop_input, _ = _next_pair(head)
    when = loop_input.decision_as_of
    level = evaluate_key_level_lifecycle(None, _event(
        "discover",
        spec=_spec(effective_from=when - timedelta(days=1), expires_at=when + timedelta(days=30)),
        source_role="jin10_supplemental", factors=("level_proposal",), as_of=when,
    )).decision
    loop_input = loop_input.model_copy(update={"key_level_decisions": (level,)})
    result = evaluate_gold_daily_close_loop(loop_input)
    assert result.canonical_action.value == "hold"
    write = persist_gold_daily_close_run(
        storage_root=tmp_path, run_id="run-held", loop_input=loop_input, result=result,
    )
    kwargs = _report_args(tmp_path, write)
    kwargs["run_id"] = "run-held"
    report = build_report_result_identity(**kwargs)
    assert report["subject"]["verification_status"] == "verified"
    assert report["subject"]["result_id"] == result.result_id
    assert report["subject"]["receipt_id"] == write.receipt_id
    assert report["effective_baseline"]["held"] is True
    assert report["effective_baseline"]["run_id"] == "run-bootstrap"
    assert report["effective_baseline"]["receipt_id"] == write.receipt_id
    assert report["effective_baseline"]["result_id"] == head.loop_result.result_id
    assert report["effective_baseline"]["strategy_id"] == head.strategy_decision.decision_id
    assert report["relationship"]["status"] == "different_result"
    historical = build_report_result_identity(**_report_args(tmp_path, original_write))
    assert historical["relationship"]["status"] == "same_effective_head"


def test_api_identity_does_not_change_frozen_internal_strategy(tmp_path, monkeypatch):
    from apps.api.services import live_strategy_service as service
    from apps.analysis.strategy.live_schemas import LiveStrategyOutput
    from apps.api.schemas.strategy import LiveStrategyLatestResponse

    monkeypatch.setattr(service, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "get_strategy_card_read_model_latest", lambda **_: None)
    monkeypatch.setattr(service, "get_market_candles", lambda **_: {"status": "unavailable", "candles": []})
    monkeypatch.setattr(service, "get_options_decision", lambda **_: {})
    now = datetime.now(timezone.utc)
    internal = service.get_live_strategy_latest(now=now)
    response = service.get_live_strategy_latest(now=now, include_result_identity=True)
    LiveStrategyOutput.model_validate(internal)
    LiveStrategyLatestResponse.model_validate(response)
    assert "result_identity" not in internal
    assert {k: v for k, v in response.items() if k != "result_identity"} == internal


@pytest.mark.parametrize("revision", [1.9, True, "1"])
def test_registry_revision_requires_an_exact_integer(tmp_path, revision):
    _, _, write, _ = _persist_bootstrap(tmp_path)
    args = _report_args(tmp_path, write)
    args["report_identity"]["canonical_receipt_revision_no"] = revision
    identity = build_report_result_identity(**args)
    assert identity["subject"]["verification_status"] != "verified"
