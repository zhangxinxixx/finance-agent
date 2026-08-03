from __future__ import annotations

import json
import shutil
import hashlib
from datetime import timedelta
from pathlib import Path

import pytest

from apps.analysis.gold_policy import daily_close_store
from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput
from apps.analysis.gold_policy.daily_close_store import (
    DailyCloseHeadConflictError,
    DailyCloseStoreError,
    _feature_artifact_name,
    _rebuild_feature,
    load_gold_daily_close_head,
    persist_gold_daily_close_run,
    verify_gold_daily_close_bundle,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.gold_policy.report_context import (
    build_gold_report_context,
    build_gold_report_context_v1,
)
from apps.renderer.gold_policy_report import (
    build_gold_policy_report_render,
    rebuild_gold_policy_report_render,
)
from apps.analysis.gold_policy.strategy_schemas import build_strategy_decision
from apps.runtime.immutable_artifact import ImmutableArtifactConflictError, immutable_json_item
from tests.analysis.test_gold_daily_close_loop import _evidence, _v2_snapshot
from tests.analysis.test_gold_key_level_policy import _event as _level_event
from tests.analysis.test_gold_key_level_policy import _spec as _level_spec
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


_REPORT_PACKAGE = {
    "source.md",
    "analysis.md",
    "visual.html",
    "report_structured.json",
    "evidence.json",
    "data_quality.json",
    "report_manifest.json",
    "strategy_card.json",
    "strategy_card.md",
}


def _write_canonical_json(path: Path, payload: dict) -> bytes:
    raw = immutable_json_item(path, payload).content
    path.write_bytes(raw)
    return raw


def _replace_manifest_item(
    bundle: Path,
    *,
    old_name: str | None,
    new_name: str,
    raw: bytes,
) -> None:
    manifest_path = bundle / ".bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if old_name is not None:
        manifest["items"] = [item for item in manifest["items"] if item["path"] != old_name]
    manifest["items"].append(
        {
            "path": new_name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "encoding": "json",
        }
    )
    _write_canonical_json(manifest_path, manifest)


def _v2_feature(case_id: str = "aligned"):
    fixture_path = Path(__file__).parents[1] / "fixtures" / "gold_policy" / "real10y_v2_cases.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    case = next(item for item in fixture["cases"] if item["id"] == case_id)
    payload = json.loads(json.dumps(fixture["base_payload"]))
    for field, changes in case["patch"].items():
        payload[field].update(changes)
    return build_feature_snapshot(payload)


def test_v2_feature_rebuild_is_version_preserving_and_rejects_tampered_derivations() -> None:
    feature = _v2_feature()

    assert feature.schema_version == "feature_snapshot.v2"
    assert _feature_artifact_name(feature) == "feature_snapshot.v2.json"
    assert _rebuild_feature(feature) == feature

    with pytest.raises(ValueError, match="derived fields or identity"):
        _rebuild_feature(feature.model_copy(update={"real10y_basis_bp": 999.0}))

    tampered_quality = feature.data_quality.model_copy(update={"strategy_readiness": "ready"})
    with pytest.raises(ValueError, match="derived fields or identity"):
        _rebuild_feature(feature.model_copy(update={"data_quality": tampered_quality}))


def _bootstrap_v2_pair() -> tuple[DailyCloseLoopInput, object]:
    previous_v1 = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    previous = _v2_snapshot(
        previous_v1,
        real10y_direct={"value": previous_v1.us10y.value - previous_v1.t10yie.value},
    )
    current_v1 = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    current = _v2_snapshot(
        current_v1,
        real10y_direct={"value": current_v1.us10y.value - current_v1.t10yie.value},
    )
    support = _policy_input(
        bias="bearish",
        feature=current,
        attribution=attribute_gold_price(current, previous),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=previous,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    return loop_input, evaluate_gold_daily_close_loop(loop_input)


def _bootstrap_pair() -> tuple[DailyCloseLoopInput, object]:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    support = _policy_input(
        bias="bearish",
        feature=current,
        attribution=attribute_gold_price(current, previous),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=previous,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    return loop_input, evaluate_gold_daily_close_loop(loop_input)


def _next_pair(head, *, delta_kind: str = "no_op") -> tuple[DailyCloseLoopInput, object]:
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, head.feature_snapshot),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=head.feature_snapshot,
        previous_policy_input=head.strategy_policy_input,
        previous_state=head.analysis_state,
        previous_transition=head.transition_decision,
        previous_strategy=head.strategy_decision,
        transition_evidence=_evidence(
            support.decision_as_of,
            delta_kind=delta_kind,
        ),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    return loop_input, evaluate_gold_daily_close_loop(loop_input)


def _persist_bootstrap(root: Path):
    loop_input, result = _bootstrap_pair()
    write = persist_gold_daily_close_run(
        storage_root=root,
        run_id="run-bootstrap",
        loop_input=loop_input,
        result=result,
    )
    lookup = load_gold_daily_close_head(storage_root=root)
    assert lookup.status == "found"
    return loop_input, result, write, lookup.head


def test_bootstrap_bundle_is_complete_readable_and_idempotent(tmp_path: Path) -> None:
    loop_input, result, first, head = _persist_bootstrap(tmp_path)
    second = persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-bootstrap",
        loop_input=loop_input,
        result=result,
    )

    assert first.head_updated is True
    assert first.artifact_results
    assert second.artifact_results == ()
    assert second.receipt_id == first.receipt_id
    assert head.loop_result.result_id == result.result_id
    assert head.feature_snapshot == loop_input.current_feature
    assert head.analysis_state == result.analysis_state
    assert head.strategy_decision == result.candidate_strategy
    assert (first.bundle_path / ".bundle-manifest.json").is_file()
    assert {
        "strategy_diff.v1.json",
        "final_report.v1.json",
        "context_bundle.v1.json",
        "token_trace.v1.json",
        "gold_report_context.v1.json",
        "gold_policy_report_render.v2.json",
    } <= {path.name for path in first.bundle_path.iterdir()}
    assert _REPORT_PACKAGE <= {path.name for path in first.bundle_path.iterdir()}
    formal_report = json.loads((first.bundle_path / "final_report.v1.json").read_text(encoding="utf-8"))
    assert formal_report["authority_result_id"] == result.result_id
    assert formal_report["language_generation"] == "not_invoked"
    report_context = json.loads((first.bundle_path / "gold_report_context.v1.json").read_text(encoding="utf-8"))
    assert report_context["run_id"] == first.bundle_path.parent.name


def test_v2_daily_close_store_round_trip_preserves_readiness(tmp_path: Path) -> None:
    loop_input, result = _bootstrap_v2_pair()
    write = persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-v2-readiness",
        loop_input=loop_input,
        result=result,
    )

    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert write.head_updated is True
    assert lookup.status == "found"
    assert lookup.head.feature_snapshot == loop_input.current_feature
    assert lookup.head.feature_snapshot.readiness_policy_version == "gold_readiness_policy.v1"
    assert lookup.head.feature_snapshot.data_quality == loop_input.current_feature.data_quality
    assert lookup.head.feature_snapshot.data_quality.analysis_readiness == "ready"
    assert lookup.head.feature_snapshot.data_quality.strategy_readiness == "ready"
    assert (write.bundle_path / "feature_snapshot.v2.json").is_file()
    assert (write.bundle_path / "gold_analysis_decision.v2.json").is_file()
    assert (write.bundle_path / "gold_price_attribution.v2.json").is_file()
    assert (write.bundle_path / "gold_report_context.v1.json").is_file()
    render_path = write.bundle_path / "gold_policy_report_render.v2.json"
    assert render_path.is_file()
    assert json.loads(render_path.read_text(encoding="utf-8"))["schema_version"] == ("gold_policy_report_render.v2")
    assert not (write.bundle_path / "gold_policy_report_render.v1.json").exists()
    assert _REPORT_PACKAGE <= {path.name for path in write.bundle_path.iterdir()}
    assert not (write.bundle_path / "gold_analysis_decision.v1.json").exists()
    assert not (write.bundle_path / "gold_price_attribution.v1.json").exists()


def test_report_context_and_renderer_are_typed_deterministic_v2_projections() -> None:
    loop_input, result = _bootstrap_v2_pair()

    context = build_gold_report_context(loop_input, result, run_id="run-v2-projection")
    render = build_gold_policy_report_render(context)

    assert context.candidate_state == result.analysis_state
    assert context.selected_state == result.analysis_state
    assert context.candidate_strategy == result.candidate_strategy
    assert context.selected_strategy == result.candidate_strategy
    assert context.transition_decision.to_state_id == context.candidate_state.state_id
    assert render.schema_version == "gold_policy_report_render.v2"
    assert render.report_status == "observe"
    assert render.markdown == build_gold_policy_report_render(context).markdown
    assert "# XAUUSD Gold Policy Daily Report" in render.markdown
    assert "LLM" not in render.markdown


def test_report_package_manifest_hashes_every_non_manifest_report_artifact(
    tmp_path: Path,
) -> None:
    _, _, write, _ = _persist_bootstrap(tmp_path)

    manifest = json.loads((write.bundle_path / "report_manifest.json").read_text(encoding="utf-8"))
    expected_hashes = {item["filename"]: item["sha256"] for item in manifest["artifacts"]}

    assert set(expected_hashes) == _REPORT_PACKAGE - {"report_manifest.json"}
    assert all(
        hashlib.sha256((write.bundle_path / name).read_bytes()).hexdigest() == digest
        for name, digest in expected_hashes.items()
    )


def test_existing_bundle_full_verifier_accepts_exact_valid_bundle(tmp_path: Path) -> None:
    _, result, write, head = _persist_bootstrap(tmp_path)
    next_input, next_result = _next_pair(head)
    next_write = persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-after-bootstrap",
        loop_input=next_input,
        result=next_result,
    )

    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=write.bundle_path,
    )

    assert verification.status == "valid"
    assert verification.reason_code == "daily_close_bundle_verified"
    assert verification.bundle_path == write.bundle_path
    assert verification.receipt is not None
    assert verification.receipt.result_id == result.result_id
    assert verification.receipt.receipt_id != next_write.receipt_id
    assert verification.head is not None
    assert verification.head.loop_result == result


@pytest.mark.parametrize(
    "filename",
    ("analysis.md", "visual.html", "report_structured.json"),
)
def test_existing_bundle_full_verifier_rejects_tampered_report_without_repair(
    tmp_path: Path,
    filename: str,
) -> None:
    _, _, write, _ = _persist_bootstrap(tmp_path)
    report = write.bundle_path / filename
    tampered = report.read_bytes() + b"\nTAMPERED\n"
    report.write_bytes(tampered)

    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=write.bundle_path,
    )

    assert verification.status == "invalid"
    assert verification.reason_code == "daily_close_bundle_verification_failed"
    assert verification.receipt is None
    assert verification.head is None
    assert report.read_bytes() == tampered


def test_bundle_verifier_rejects_multiple_render_versions(tmp_path: Path) -> None:
    loop_input, result, write, _ = _persist_bootstrap(tmp_path)
    context = build_gold_report_context(loop_input, result, run_id="run-bootstrap")
    legacy_render = rebuild_gold_policy_report_render(
        context,
        schema_version="gold_policy_report_render.v1",
    )
    legacy_path = write.bundle_path / "gold_policy_report_render.v1.json"
    raw = _write_canonical_json(legacy_path, legacy_render.model_dump(mode="json"))
    _replace_manifest_item(
        write.bundle_path,
        old_name=None,
        new_name=legacy_path.name,
        raw=raw,
    )

    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=write.bundle_path,
    )

    assert verification.status == "invalid"
    assert verification.reason_code == "daily_close_bundle_verification_failed"


def test_bundle_verifier_rejects_render_filename_schema_mismatch(tmp_path: Path) -> None:
    _, _, write, _ = _persist_bootstrap(tmp_path)
    original = write.bundle_path / "gold_policy_report_render.v2.json"
    mismatched = write.bundle_path / "gold_policy_report_render.v1.json"
    raw = original.read_bytes()
    original.rename(mismatched)
    _replace_manifest_item(
        write.bundle_path,
        old_name=original.name,
        new_name=mismatched.name,
        raw=raw,
    )

    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=write.bundle_path,
    )

    assert verification.status == "invalid"
    assert verification.reason_code == "daily_close_bundle_verification_failed"


def test_bundle_verifier_rejects_self_consistent_manifest_with_invalid_v2_render(
    tmp_path: Path,
) -> None:
    _, _, write, _ = _persist_bootstrap(tmp_path)
    render_path = write.bundle_path / "gold_policy_report_render.v2.json"
    payload = json.loads(render_path.read_text(encoding="utf-8"))
    payload["payload_hash"] = "0" * 64
    raw = _write_canonical_json(render_path, payload)
    _replace_manifest_item(
        write.bundle_path,
        old_name=render_path.name,
        new_name=render_path.name,
        raw=raw,
    )

    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=write.bundle_path,
    )

    assert verification.status == "invalid"
    assert verification.reason_code == "daily_close_bundle_verification_failed"


def test_bundle_verifier_rejects_well_formed_v2_render_for_another_context(
    tmp_path: Path,
) -> None:
    loop_input, result, write, _ = _persist_bootstrap(tmp_path)
    other_context = build_gold_report_context(loop_input, result, run_id="another-run")
    other_render = build_gold_policy_report_render(other_context)
    render_path = write.bundle_path / "gold_policy_report_render.v2.json"
    raw = _write_canonical_json(render_path, other_render.model_dump(mode="json"))
    _replace_manifest_item(
        write.bundle_path,
        old_name=render_path.name,
        new_name=render_path.name,
        raw=raw,
    )

    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=write.bundle_path,
    )

    assert verification.status == "invalid"
    assert verification.reason_code == "daily_close_bundle_verification_failed"


def test_store_reads_frozen_v1_context_and_persists_v1_1_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_input, legacy_result = _bootstrap_pair()

    def _frozen_v1_builder(loop_input, result, *, run_id: str):
        return build_gold_report_context_v1(loop_input, result)

    def _frozen_v1_renderer(context):
        return rebuild_gold_policy_report_render(
            context,
            schema_version="gold_policy_report_render.v1",
        )

    with monkeypatch.context() as legacy_builder:
        legacy_builder.setattr(
            daily_close_store,
            "build_gold_report_context",
            _frozen_v1_builder,
        )
        legacy_builder.setattr(
            daily_close_store,
            "build_gold_policy_report_render",
            _frozen_v1_renderer,
        )
        legacy_write = persist_gold_daily_close_run(
            storage_root=tmp_path,
            run_id="run-frozen-v1",
            loop_input=legacy_input,
            result=legacy_result,
        )

    legacy_context_payload = json.loads(
        (legacy_write.bundle_path / "gold_report_context.v1.json").read_text(encoding="utf-8")
    )
    frozen_context = build_gold_report_context_v1(legacy_input, legacy_result)
    assert legacy_context_payload == frozen_context.model_dump(mode="json")
    assert legacy_context_payload["schema_version"] == "gold_report_context.v1"
    assert legacy_context_payload["context_id"] == frozen_context.context_id
    assert (legacy_write.bundle_path / "gold_policy_report_render.v1.json").is_file()
    assert not (legacy_write.bundle_path / "gold_policy_report_render.v2.json").exists()

    legacy_verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=legacy_write.bundle_path,
    )
    legacy_head = load_gold_daily_close_head(storage_root=tmp_path)
    assert legacy_verification.status == "valid"
    assert legacy_head.status == "found"
    assert legacy_head.head is not None

    child_input, child_result = _next_pair(legacy_head.head)
    child_write = persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-v1-1-child",
        loop_input=child_input,
        result=child_result,
    )
    child_context_payload = json.loads(
        (child_write.bundle_path / "gold_report_context.v1.json").read_text(encoding="utf-8")
    )
    child_verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=child_write.bundle_path,
    )
    child_head = load_gold_daily_close_head(storage_root=tmp_path)

    assert child_context_payload["schema_version"] == "gold_report_context.v1.1"
    assert child_context_payload["run_id"] == child_write.bundle_path.parent.name
    assert (child_write.bundle_path / "gold_policy_report_render.v2.json").is_file()
    assert not (child_write.bundle_path / "gold_policy_report_render.v1.json").exists()
    assert child_verification.status == "valid"
    assert child_verification.head is not None
    assert child_verification.head.loop_result == child_result
    assert child_head.status == "found"
    assert child_head.head is not None
    assert child_head.head.loop_result == child_result


def test_maintain_uses_durable_predecessor_and_updates_strategy_head(tmp_path: Path) -> None:
    _, first_result, _, first_head = _persist_bootstrap(tmp_path)
    loop_input, result = _next_pair(first_head)
    persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-maintain",
        loop_input=loop_input,
        result=result,
    )

    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert result.canonical_action.value == "maintain"
    assert lookup.status == "found"
    assert lookup.head.analysis_state.state_id == first_result.analysis_state.state_id
    assert lookup.head.strategy_decision.decision_id == result.candidate_strategy.decision_id
    assert lookup.head.feature_snapshot == loop_input.current_feature
    assert lookup.latest_receipt.predecessor_receipt_id == first_head.latest_receipt.receipt_id


def test_blocked_session_preserves_state_and_selects_formal_no_trade(tmp_path: Path) -> None:
    _, _, _, head = _persist_bootstrap(tmp_path)
    blocked = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    support = _policy_input(
        bias="bearish",
        feature=blocked,
        attribution=attribute_gold_price(blocked, head.feature_snapshot),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=blocked,
        previous_feature=head.feature_snapshot,
        previous_policy_input=head.strategy_policy_input,
        previous_state=head.analysis_state,
        previous_transition=head.transition_decision,
        previous_strategy=head.strategy_decision,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    result = evaluate_gold_daily_close_loop(loop_input)

    persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-blocked",
        loop_input=loop_input,
        result=result,
    )
    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert result.canonical_action.value == "maintain"
    assert result.analysis_state == head.analysis_state
    assert result.candidate_strategy.status.value == "NO_TRADE"
    assert lookup.status == "found"
    assert lookup.head.analysis_state == head.analysis_state
    assert lookup.head.strategy_decision == result.candidate_strategy


def test_prebootstrap_blocked_hold_is_auditable_but_never_fabricates_head(tmp_path: Path) -> None:
    blocked = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    support = _policy_input(
        feature=blocked,
        attribution=attribute_gold_price(blocked, previous),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=blocked,
        previous_feature=previous,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    result = evaluate_gold_daily_close_loop(loop_input)

    write = persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-prebootstrap-hold",
        loop_input=loop_input,
        result=result,
    )
    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert write.head_updated is False
    assert lookup.status == "missing"
    assert lookup.reason_code == "daily_close_prebootstrap_hold"
    assert lookup.latest_receipt.action.value == "hold"
    assert lookup.latest_receipt.effective_head is None


def test_rejected_hold_is_audited_without_replacing_previous_head(tmp_path: Path) -> None:
    _, _, _, head = _persist_bootstrap(tmp_path)
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, head.feature_snapshot),
    )
    spec = _level_spec(
        effective_from=support.decision_as_of - timedelta(days=1),
        expires_at=support.decision_as_of + timedelta(days=30),
    )
    unmatched = evaluate_key_level_lifecycle(
        None,
        _level_event(
            "discover",
            spec=spec,
            source_role="jin10_supplemental",
            factors=("level_proposal",),
            as_of=support.decision_as_of,
        ),
    ).decision
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=head.feature_snapshot,
        previous_policy_input=head.strategy_policy_input,
        previous_state=head.analysis_state,
        previous_transition=head.transition_decision,
        previous_strategy=head.strategy_decision,
        transition_evidence=_evidence(support.decision_as_of, delta_kind="no_op"),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
        key_level_decisions=(unmatched,),
    )
    result = evaluate_gold_daily_close_loop(loop_input)

    write = persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-rejected-hold",
        loop_input=loop_input,
        result=result,
    )
    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert result.canonical_action.value == "hold"
    assert result.consistency_decision.consistency_passed is False
    assert write.head_updated is False
    assert lookup.status == "found"
    assert lookup.latest_receipt.action.value == "hold"
    assert lookup.head.analysis_state == head.analysis_state
    assert lookup.head.strategy_decision == head.strategy_decision
    assert lookup.head.loop_result == head.loop_result


def test_store_rejects_forged_predecessor_even_when_bundle_is_internally_typed(tmp_path: Path) -> None:
    _, _, _, head = _persist_bootstrap(tmp_path)
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, head.feature_snapshot),
    )
    forged_payload = head.strategy_decision.model_dump(exclude={"decision_hash", "decision_id"})
    forged_payload.update(
        {
            "status": "OBSERVE",
            "direction": "none",
            "reason_codes": ("FORGED_PREDECESSOR",),
            "no_trade_reason_code": None,
            "release_conditions": (),
            "review_triggers": (),
        }
    )
    forged = build_strategy_decision(forged_payload)
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=head.feature_snapshot,
        previous_policy_input=head.strategy_policy_input,
        previous_state=head.analysis_state,
        previous_transition=head.transition_decision,
        previous_strategy=forged,
        transition_evidence=_evidence(support.decision_as_of, delta_kind="no_op"),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    result = evaluate_gold_daily_close_loop(loop_input)

    with pytest.raises(DailyCloseHeadConflictError, match="durable canonical head"):
        persist_gold_daily_close_run(
            storage_root=tmp_path,
            run_id="run-forged",
            loop_input=loop_input,
            result=result,
        )

    assert not (tmp_path / "analysis/gold_mainlines/2025-01-24/run-forged").exists()


def test_same_run_with_different_result_is_an_immutable_conflict(tmp_path: Path) -> None:
    _, _, _, head = _persist_bootstrap(tmp_path)
    first_input, first_result = _next_pair(head, delta_kind="no_op")
    persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-conflict",
        loop_input=first_input,
        result=first_result,
    )
    second_input, second_result = _next_pair(head, delta_kind="ordinary")

    with pytest.raises(ImmutableArtifactConflictError):
        persist_gold_daily_close_run(
            storage_root=tmp_path,
            run_id="run-conflict",
            loop_input=second_input,
            result=second_result,
        )


def test_store_rejects_same_session_revision_without_latest_predecessor(tmp_path: Path) -> None:
    loop_input, result, _, _ = _persist_bootstrap(tmp_path)

    with pytest.raises(DailyCloseHeadConflictError, match="cannot bootstrap"):
        persist_gold_daily_close_run(
            storage_root=tmp_path,
            run_id="run-concurrent-rival",
            loop_input=loop_input,
            result=result,
        )

    assert not (tmp_path / "analysis/gold_mainlines/2025-01-21/run-concurrent-rival/daily_close").exists()


def test_latest_partial_or_corrupt_session_never_falls_back(tmp_path: Path) -> None:
    _persist_bootstrap(tmp_path)
    broken = tmp_path / "analysis/gold_mainlines/2025-01-22/run-broken/daily_close"
    broken.mkdir(parents=True)
    (broken / ".bundle-manifest.json").write_text(
        '{"version":1,"status":"committed","items":[]}',
        encoding="utf-8",
    )

    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert lookup.status == "invalid"
    assert lookup.reason_code == "daily_close_latest_session_invalid"
    assert lookup.head is None


def test_hidden_orphan_staging_directory_is_not_a_head_candidate(tmp_path: Path) -> None:
    _, result, _, _ = _persist_bootstrap(tmp_path)
    staging = tmp_path / "analysis/gold_mainlines/2025-01-22/.orphan.bundle/daily_close"
    staging.mkdir(parents=True)
    (staging / "junk.json").write_text("{}\n", encoding="utf-8")

    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert lookup.status == "found"
    assert lookup.head.loop_result.result_id == result.result_id


def test_latest_visible_commit_attempt_without_bundle_never_falls_back(tmp_path: Path) -> None:
    _persist_bootstrap(tmp_path)
    attempt = tmp_path / "analysis/gold_mainlines/2025-01-22/run-crashed/.daily-close-attempt.json"
    attempt.parent.mkdir(parents=True)
    attempt.write_text(
        json.dumps(
            {
                "schema_version": "gold_daily_close_commit_attempt.v1",
                "session_date": "2025-01-22",
                "run_id": "run-crashed",
                "result_id": "gold_daily_close_loop_result.v1:" + "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert lookup.status == "invalid"
    assert lookup.head is None


def test_tampered_latest_artifact_is_invalid_instead_of_falling_back(tmp_path: Path) -> None:
    _, _, write, _ = _persist_bootstrap(tmp_path)
    feature = write.bundle_path / "feature_snapshot.v1.json"
    payload = json.loads(feature.read_text(encoding="utf-8"))
    payload["xauusd_spot"]["value"] = 1.0
    feature.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert lookup.status == "invalid"
    assert lookup.head is None


def test_self_consistent_manifest_cannot_hide_embedded_artifact_mismatch(
    tmp_path: Path,
) -> None:
    _, _, write, _ = _persist_bootstrap(tmp_path)
    analysis = write.bundle_path / "gold_analysis_decision.v1.json"
    payload = json.loads(analysis.read_text(encoding="utf-8"))
    payload["macro_regime"] = "tampered_but_schema_valid"
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    analysis.write_bytes(raw)
    manifest_path = write.bundle_path / ".bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["items"]:
        if item["path"] == analysis.name:
            item["sha256"] = hashlib.sha256(raw).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert lookup.status == "invalid"
    assert lookup.head is None


@pytest.mark.parametrize("run_id", ["../escape", "/absolute", "bad/name", " space"])
def test_run_id_cannot_escape_storage_root(tmp_path: Path, run_id: str) -> None:
    loop_input, result = _bootstrap_pair()

    with pytest.raises(ValueError, match="unsafe path"):
        persist_gold_daily_close_run(
            storage_root=tmp_path,
            run_id=run_id,
            loop_input=loop_input,
            result=result,
        )


def test_existing_partial_bundle_is_never_repaired(tmp_path: Path) -> None:
    loop_input, result = _bootstrap_pair()
    target = tmp_path / "analysis/gold_mainlines/2025-01-21/run-partial/daily_close"
    target.mkdir(parents=True)
    (target / "feature_snapshot.v1.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(DailyCloseStoreError, match="incomplete or invalid"):
        persist_gold_daily_close_run(
            storage_root=tmp_path,
            run_id="run-partial",
            loop_input=loop_input,
            result=result,
        )

    assert not (target / ".bundle-manifest.json").exists()


def test_same_session_unlinked_revision_heads_are_invalid(tmp_path: Path) -> None:
    _persist_bootstrap(tmp_path)
    alternate_root = tmp_path / "alternate"
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    payload = current.model_dump(
        mode="json",
        exclude={"data_quality", "payload_hash", "snapshot_id"},
    )
    payload["xauusd_spot"]["value"] += 1.0
    alternate = build_feature_snapshot(payload)
    support = _policy_input(
        bias="bearish",
        feature=alternate,
        attribution=attribute_gold_price(alternate, previous),
    )
    alternate_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=alternate,
        previous_feature=previous,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    alternate_result = evaluate_gold_daily_close_loop(alternate_input)
    alternate_write = persist_gold_daily_close_run(
        storage_root=alternate_root,
        run_id="run-alternate",
        loop_input=alternate_input,
        result=alternate_result,
    )
    copied = tmp_path / "analysis/gold_mainlines/2025-01-21/run-alternate/daily_close"
    copied.parent.mkdir(parents=True)
    shutil.copytree(alternate_write.bundle_path, copied)

    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert lookup.status == "invalid"
    assert lookup.reason_code == "daily_close_latest_session_revision_chain_invalid"
    assert lookup.head is None


def test_new_bundle_is_not_visible_when_atomic_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.runtime import immutable_artifact

    loop_input, result = _bootstrap_pair()
    original = immutable_artifact._write_bytes_file
    calls = 0

    def fail_second(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated daily-close bundle crash")
        original(path, content)

    monkeypatch.setattr(immutable_artifact, "_write_bytes_file", fail_second)

    with pytest.raises(OSError, match="bundle crash"):
        persist_gold_daily_close_run(
            storage_root=tmp_path,
            run_id="run-crash",
            loop_input=loop_input,
            result=result,
        )

    assert not (tmp_path / "analysis/gold_mainlines/2025-01-21/run-crash/daily_close").exists()
    assert (tmp_path / "analysis/gold_mainlines/2025-01-21/run-crash/.daily-close-attempt.json").is_file()
    assert load_gold_daily_close_head(storage_root=tmp_path).status == "invalid"


def test_symlinked_bundle_path_cannot_escape_storage_root(tmp_path: Path) -> None:
    loop_input, result = _bootstrap_pair()
    outside = tmp_path / "outside"
    outside.mkdir()
    run_dir = tmp_path / "analysis/gold_mainlines/2025-01-21/run-bootstrap"
    run_dir.mkdir(parents=True)
    (run_dir / "daily_close").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot contain symlinks"):
        persist_gold_daily_close_run(
            storage_root=tmp_path,
            run_id="run-bootstrap",
            loop_input=loop_input,
            result=result,
        )

    assert not any(outside.iterdir())


def test_symlinked_storage_parent_is_rejected_before_external_directory_creation(
    tmp_path: Path,
) -> None:
    loop_input, result = _bootstrap_pair()
    root = tmp_path / "storage"
    outside = tmp_path / "outside-parent"
    root.mkdir()
    outside.mkdir()
    (root / "analysis").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot contain symlinks"):
        persist_gold_daily_close_run(
            storage_root=root,
            run_id="run-bootstrap",
            loop_input=loop_input,
            result=result,
        )

    assert not (outside / "gold_mainlines").exists()
    assert load_gold_daily_close_head(storage_root=root).status == "invalid"
