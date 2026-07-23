from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from apps.analysis.context_bundle.schemas import EvidenceItem
from apps.analysis.evidence_delta import (
    ConfirmationStatus,
    FigureFactEvidence,
    KeyLevelEvidence,
    MacroMetricEvidence,
    MaterialEventEvidence,
    OptionsRegimeEvidence,
    RecommendedAction,
    SourceQuality,
    adapt_context_evidence,
    adapt_figure_fact,
    evaluate_evidence_delta,
    semantic_hash,
    semantic_identity,
)
from apps.analysis.evidence_delta.schemas import EvidenceDeltaDecision
from apps.analysis.figure_facts import FigureFact


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)


def _macro(
    *,
    evidence_id: str = "dxy-1",
    source: str = "fred",
    metric: str = "dxy",
    current: float = 100.6,
    previous: float = 100.0,
    unit: str | None = None,
    source_quality: SourceQuality = SourceQuality.PRIMARY,
) -> MacroMetricEvidence:
    resolved_unit = unit or {"dxy": "index", "oil": "usd"}.get(metric, "percent")
    return MacroMetricEvidence(
        source=source,
        evidence_id=evidence_id,
        asset="XAUUSD",
        observed_at=NOW,
        source_quality=source_quality,
        source_ref={"series": metric},
        metadata={"retrieved_at": "transport-only"},
        metric=metric,
        current_value=current,
        previous_value=previous,
        unit=resolved_unit,
    )


def _key_level(
    *,
    evidence_id: str = "level-1",
    event: str = "confirmed_break",
    confirmation: ConfirmationStatus = ConfirmationStatus.CONFIRMED,
) -> KeyLevelEvidence:
    return KeyLevelEvidence(
        source="xauusd_5m",
        evidence_id=evidence_id,
        asset="XAUUSD",
        observed_at=NOW,
        source_quality=SourceQuality.VALIDATED,
        level_id="daily_support_3300",
        level_role="support",
        level_value=3300.0,
        observed_value=3294.0,
        event=event,
        confirmation_status=confirmation,
    )


def _options(
    *,
    evidence_id: str = "options-1",
    change_pct: float = 0.8,
    confirmation: ConfirmationStatus = ConfirmationStatus.CONFIRMED,
) -> OptionsRegimeEvidence:
    return OptionsRegimeEvidence(
        source="cme",
        evidence_id=evidence_id,
        asset="XAUUSD",
        observed_at=NOW,
        source_quality=SourceQuality.EXCHANGE,
        regime_id="front_month_gamma_zero",
        event="gamma_zero_migration",
        change_pct=change_pct,
        confirmation_status=confirmation,
    )


def _event(
    *,
    evidence_id: str = "event-1",
    source: str = "federal_reserve",
    claim: str = "Federal Reserve changes its policy stance",
    score: float = 85.0,
    eligible: bool = True,
    confirmation: ConfirmationStatus = ConfirmationStatus.CONFIRMED,
) -> MaterialEventEvidence:
    return MaterialEventEvidence(
        source=source,
        evidence_id=evidence_id,
        asset="XAUUSD",
        observed_at=NOW,
        source_quality=SourceQuality.OFFICIAL,
        event_id=evidence_id,
        cluster_key="fomc-policy-change",
        event_type="fomc_statement",
        claim=claim,
        materiality_score=score,
        risk_level="high",
        recompute_eligible=eligible,
        confirmation_status=confirmation,
    )


def _evaluate(*items, previous_semantic_hashes=None):
    return evaluate_evidence_delta(
        asset="XAUUSD",
        state_scope="daily_close",
        canonical_state_id="state-001",
        evidence=list(items),
        previous_semantic_hashes=previous_semantic_hashes,
    )


def _figure(*, quality_status: str = "accepted") -> FigureFact:
    return FigureFact.build(
        figure_id="figure-1",
        report_id="report-1",
        page_no=1,
        bbox=(0, 0, 100, 100),
        asset="XAUUSD",
        observations=["Gamma zero moved higher"] if quality_status == "accepted" else [],
        numeric_values=[],
        derived_claims=[],
        interpretation_limits=[] if quality_status == "accepted" else ["manual review required"],
        source_ref={
            "figure_id": "figure-1",
            "report_id": "report-1",
            "page_no": 1,
            "bbox": [0, 0, 100, 100],
        },
        quality_status=quality_status,
        image_content_hash="a" * 64 if quality_status == "accepted" else None,
        created_by_run_id="run-1",
    )


def test_empty_evidence_is_stable_no_op() -> None:
    first = _evaluate()
    second = _evaluate()

    assert first == second
    assert first.has_relevant_delta is False
    assert first.recommended_action is RecommendedAction.NO_OP
    assert first.trigger_reasons == ["no_evidence"]
    assert first.decision_id == f"evidence_delta_{first.content_hash[:24]}"


def test_input_order_does_not_change_decision_identity() -> None:
    first = _evaluate(_macro(), _options())
    second = _evaluate(_options(), _macro())

    assert first == second
    assert first.recommended_action is RecommendedAction.RUN_TRANSITION_ANALYSIS


def test_duplicate_news_from_different_sources_is_clustered_with_source_aware_refs() -> None:
    first = _event(source="federal_reserve", evidence_id="official-1")
    second = _event(source="reuters", evidence_id="wire-9")
    second = second.model_copy(update={"source_quality": SourceQuality.VALIDATED})

    decision = _evaluate(second, first)

    assert len(decision.evaluated_items) == 1
    assert [(ref.source, ref.evidence_id) for ref in decision.evaluated_items[0].evidence_refs] == [
        ("federal_reserve", "official-1"),
        ("reuters", "wire-9"),
    ]
    assert decision.recommended_action is RecommendedAction.RUN_TRANSITION_ANALYSIS


def test_same_evidence_id_from_different_sources_is_not_collapsed() -> None:
    first = _event(source="federal_reserve", evidence_id="shared-id")
    second = _event(source="reuters", evidence_id="shared-id")
    second = second.model_copy(update={"source_quality": SourceQuality.VALIDATED})

    item = _evaluate(first, second).evaluated_items[0]

    assert len(item.evidence_refs) == 2


def test_previous_semantic_hash_makes_metadata_only_update_no_op() -> None:
    original = _macro()
    replay = original.model_copy(
        update={
            "evidence_id": "dxy-new-delivery",
            "source_ref": {"series": "dxy", "path": "new-path"},
            "metadata": {"retrieved_at": "later"},
        }
    )
    key = semantic_identity(original)

    decision = _evaluate(replay, previous_semantic_hashes={key: semantic_hash(original)})

    assert decision.recommended_action is RecommendedAction.NO_OP
    assert decision.evaluated_items[0].outcome == "duplicate"
    assert decision.evaluated_items[0].reasons == ["semantic_content_unchanged"]


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (100.1, RecommendedAction.NO_OP),
        (100.3, RecommendedAction.UPDATE_CONTEXT_ONLY),
        (100.6, RecommendedAction.RUN_TRANSITION_ANALYSIS),
    ],
)
def test_macro_threshold_bands_are_deterministic(current: float, expected: RecommendedAction) -> None:
    assert _evaluate(_macro(current=current)).recommended_action is expected


def test_large_untrusted_macro_move_goes_to_manual_review_not_model() -> None:
    decision = _evaluate(
        _macro(current=101.0, source_quality=SourceQuality.UNVERIFIED, source="unknown_feed")
    )

    assert decision.recommended_action is RecommendedAction.MANUAL_REVIEW
    assert "untrusted_material_move" in decision.trigger_reasons[0]


@pytest.mark.parametrize(
    ("metric", "bad_unit", "expected_unit"),
    [
        ("dxy", "percent", "index"),
        ("us10y", "index", "percent"),
        ("real10y", "usd", "percent"),
        ("oil", "index", "usd"),
    ],
)
def test_metric_unit_mismatch_fails_closed(metric: str, bad_unit: str, expected_unit: str) -> None:
    with pytest.raises(ValidationError, match=f"requires unit={expected_unit}"):
        _macro(metric=metric, unit=bad_unit)


def test_confirmed_key_level_break_triggers_transition() -> None:
    decision = _evaluate(_key_level())

    assert decision.recommended_action is RecommendedAction.RUN_TRANSITION_ANALYSIS
    assert decision.materiality == "critical"
    assert decision.affected_state_fields == [
        "invalidation_conditions",
        "key_levels",
        "scenario_states",
    ]


def test_unconfirmed_key_level_break_requires_manual_review() -> None:
    decision = _evaluate(_key_level(confirmation=ConfirmationStatus.UNCONFIRMED))

    assert decision.recommended_action is RecommendedAction.MANUAL_REVIEW
    assert "confirmation_required" in decision.trigger_reasons[0]


def test_options_regime_only_triggers_for_confirmed_exchange_change() -> None:
    assert _evaluate(_options(change_pct=0.49)).recommended_action is RecommendedAction.NO_OP
    assert _evaluate(_options(change_pct=0.8)).recommended_action is RecommendedAction.RUN_TRANSITION_ANALYSIS
    assert (
        _evaluate(_options(change_pct=0.8, confirmation=ConfirmationStatus.UNCONFIRMED)).recommended_action
        is RecommendedAction.MANUAL_REVIEW
    )


def test_confirmed_material_event_triggers_and_unconfirmed_high_risk_stays_manual() -> None:
    assert _evaluate(_event()).recommended_action is RecommendedAction.RUN_TRANSITION_ANALYSIS
    assert (
        _evaluate(_event(eligible=False, confirmation=ConfirmationStatus.UNCONFIRMED)).recommended_action
        is RecommendedAction.MANUAL_REVIEW
    )


def test_same_semantic_identity_with_conflicting_payloads_fails_closed() -> None:
    first = _macro(evidence_id="dxy-1", current=100.6)
    decision = _evaluate(
        first,
        _macro(evidence_id="dxy-2", current=101.0),
        previous_semantic_hashes={semantic_identity(first): semantic_hash(first)},
    )

    assert decision.recommended_action is RecommendedAction.MANUAL_REVIEW
    assert decision.semantic_hashes == {}
    assert all(item.reasons == ["semantic_identity:conflicting_payload"] for item in decision.evaluated_items)


def test_same_authoritative_source_key_with_different_payloads_fails_closed() -> None:
    first = _macro(evidence_id="same-key", current=100.6)
    second = _event(evidence_id="same-key", source="fred")

    decision = _evaluate(first, second)

    assert decision.recommended_action is RecommendedAction.MANUAL_REVIEW
    assert decision.semantic_hashes == {}
    assert all(
        item.reasons == ["authoritative_evidence_key:conflicting_payload"]
        for item in decision.evaluated_items
    )


def test_accepted_figure_fact_is_context_only_and_nonaccepted_fact_is_ignored() -> None:
    accepted = adapt_figure_fact(_figure(), observed_at=NOW)
    needs_review = adapt_figure_fact(_figure(quality_status="needs_review"), observed_at=NOW)

    assert _evaluate(accepted).recommended_action is RecommendedAction.UPDATE_CONTEXT_ONLY
    assert _evaluate(needs_review).recommended_action is RecommendedAction.NO_OP


@pytest.mark.parametrize(
    ("source_quality", "has_direct_evidence", "message"),
    [
        (SourceQuality.VALIDATED, False, "has_direct_evidence"),
        (SourceQuality.OFFICIAL, True, "validated source quality"),
        (SourceQuality.EXCHANGE, True, "validated source quality"),
        (SourceQuality.PRIMARY, True, "validated source quality"),
        (SourceQuality.SUPPLEMENTAL, True, "validated source quality"),
        (SourceQuality.UNVERIFIED, True, "validated source quality"),
    ],
)
def test_figure_evidence_acceptance_requires_direct_validated_fact(
    source_quality: SourceQuality, has_direct_evidence: bool, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        FigureFactEvidence(
            source="figure_fact",
            evidence_id="fact-1",
            asset="XAUUSD",
            observed_at=NOW,
            source_quality=source_quality,
            figure_fact_id="fact-1",
            figure_id="figure-1",
            report_id="report-1",
            figure_content_hash="a" * 64,
            quality_status="accepted",
            has_direct_evidence=has_direct_evidence,
        )


def test_context_adapter_requires_explicit_known_kind_quality_asset_and_unit() -> None:
    base = EvidenceItem(
        source="fred",
        evidence_id="dxy-1",
        business_time=NOW,
        ingested_at=NOW,
        payload={
            "evidence_type": "macro_metric",
            "asset": "XAUUSD",
            "source_quality": "primary",
            "metric": "dxy",
            "current_value": 100.6,
            "previous_value": 100.0,
            "unit": "index",
        },
    )
    adapted = adapt_context_evidence(base)
    assert isinstance(adapted, MacroMetricEvidence)

    for payload, message in [
        ({**base.payload, "evidence_type": "unknown"}, "Input tag"),
        ({key: value for key, value in base.payload.items() if key != "source_quality"}, "source_quality"),
        ({key: value for key, value in base.payload.items() if key != "unit"}, "unit"),
    ]:
        item = base.model_copy(update={"payload": payload})
        with pytest.raises((ValueError, ValidationError), match=message):
            adapt_context_evidence(item)


def test_asset_mismatch_fails_closed_before_decision() -> None:
    with pytest.raises(ValueError, match="evidence asset mismatch"):
        evaluate_evidence_delta(
            asset="GC",
            state_scope="daily_close",
            canonical_state_id="state-1",
            evidence=[_macro()],
        )


def test_decision_hash_rejects_tampering_and_contains_no_state_patch() -> None:
    decision = _evaluate(_macro())
    payload = decision.model_dump(mode="json")
    assert "core_thesis" not in payload
    assert "net_bias" not in payload
    assert "state_patch" not in payload
    payload["affected_state_fields"] = ["core_thesis"]

    with pytest.raises(ValidationError, match="literal|content_hash"):
        EvidenceDeltaDecision.model_validate(payload)
