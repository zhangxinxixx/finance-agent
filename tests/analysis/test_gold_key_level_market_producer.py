from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput
from apps.analysis.gold_policy.key_level_controls import KeyLevelControlsInput
from apps.analysis.gold_policy.key_level_market_producer import (
    produce_gold_key_level_market_events,
)
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelQualificationReceiptInput,
    _build_key_level_qualification_receipt,
    build_key_level_event,
)
from apps.analysis.gold_policy.runtime_controls import build_gold_daily_close_runtime_controls
from tests.analysis.test_gold_key_level_policy import _direct_state, _spec
from tests.analysis.test_gold_runtime_hard_invalidation import (
    _predecessor_case,
    _same_session_case,
    _transition_with_evidence_as_of,
)
from tests.analysis.test_gold_strategy_policy import _policy_input


CUTOFF = datetime(2026, 7, 30, 1, tzinfo=UTC)
WINDOW_END = CUTOFF - timedelta(hours=1)


def _state(*, role: str = "support", lifecycle: str = "holding", expires_at=None):
    spec = _spec(
        role=role,
        reference_price="4500",
        effective_from=CUTOFF - timedelta(days=30),
        expires_at=expires_at or CUTOFF + timedelta(days=30),
        origin_key=f"producer:{role}:{lifecycle}",
    )
    return _direct_state(lifecycle, spec=spec, as_of=WINDOW_END - timedelta(days=3))


def _rows(*, end: datetime = WINDOW_END, close: float = 4490.0):
    rows = []
    for offset in (1, 0):
        close_time = end - timedelta(days=offset)
        rows.append(
            {
                "asset": "XAUUSD",
                "timeframe": "1d",
                "open_time": (close_time - timedelta(days=1)).isoformat(),
                "close_time": close_time.isoformat(),
                "open": close,
                "high": close + 5,
                "low": close - 5,
                "close": close,
                "source": "fixture_xauusd_primary_1d",
                "raw_path": f"fixtures/market/{close_time.date()}.json",
                "source_ref": {
                    "provider_symbol": "XAUUSD",
                    "instrument_type": "otc_spot_quote_proxy",
                    "source_role": "market_primary",
                    "quality_status": "accepted",
                    "reference": f"fixture://market/{close_time.date()}",
                    "retrieved_at": close_time.isoformat(),
                    "sha256": f"{offset + 1:064x}",
                },
            }
        )
    return rows


@pytest.mark.parametrize(("role", "close"), [("support", 4490.0), ("resistance", 4510.0)])
def test_produces_deterministic_break_with_actual_window_and_full_lineage(role: str, close: float) -> None:
    state = _state(role=role)
    rows = _rows(close=close)
    frozen = deepcopy(rows)

    first = produce_gold_key_level_market_events(
        previous_states=(state,), candidates=rows, decision_as_of=CUTOFF
    )
    repeated = produce_gold_key_level_market_events(
        previous_states=(state,), candidates=reversed(rows), decision_as_of=CUTOFF
    )

    assert first == repeated
    assert rows == frozen
    assert first.reason_codes == ("KEY_LEVEL_BREAK_EVENTS_PRODUCED",)
    assert first.controls_input.previous_states == (state,)
    event = first.controls_input.ordered_events[0]
    assert event.event_type.value == "break_confirmed"
    assert event.evidence.timeframe.value == "1d"
    assert event.evidence.window_end == WINDOW_END < event.evidence.as_of == CUTOFF
    assert event.evidence.price_fact.window_closes == (close, close)
    sources = {ref.source for ref in event.evidence.source_refs}
    assert {
        "input_snapshot",
        "raw_market_artifact",
        "market_source_qualification",
        "canonical_xauusd_d1_window",
        "qualification_receipt",
        "fixture_xauusd_primary_1d",
    } <= sources


def test_raw_reference_distinguishes_row_digest_from_declared_raw_digest() -> None:
    rows = _rows()
    declared = produce_gold_key_level_market_events(
        previous_states=(_state(),), candidates=rows, decision_as_of=CUTOFF
    )

    declared_refs = sorted(
        ref.reference
        for ref in declared.controls_input.ordered_events[0].evidence.source_refs
        if ref.source == "raw_market_artifact"
    )
    assert declared_refs == sorted(
        f"{row['raw_path']}#sha256={row['source_ref']['sha256']}" for row in rows
    )
    snapshot_refs = {
        ref.reference
        for ref in declared.controls_input.ordered_events[0].evidence.source_refs
        if ref.source == "input_snapshot"
    }
    assert len(snapshot_refs) == 2
    assert all(reference.startswith("market_candle.v1:") for reference in snapshot_refs)

    without_declared_sha = _rows()
    for row in without_declared_sha:
        row["source_ref"].pop("sha256")
    path_only = produce_gold_key_level_market_events(
        previous_states=(_state(),), candidates=without_declared_sha, decision_as_of=CUTOFF
    )
    path_only_refs = sorted(
        ref.reference
        for ref in path_only.controls_input.ordered_events[0].evidence.source_refs
        if ref.source == "raw_market_artifact"
    )
    assert path_only_refs == sorted(row["raw_path"] for row in without_declared_sha)


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("wrong_timeframe", "D1_MARKET_TIMEFRAME_INVALID"),
        ("gc", "D1_MARKET_ASSET_NOT_CANONICAL_XAUUSD"),
        ("fallback", "D1_MARKET_SOURCE_UNQUALIFIED"),
        ("staging", "D1_MARKET_SOURCE_UNQUALIFIED"),
        ("provider_ambiguity", "D1_MARKET_PROVIDER_AMBIGUOUS"),
        ("incomplete", "D1_MARKET_WINDOW_INCOMPLETE"),
        ("duplicate", "D1_MARKET_WINDOW_DUPLICATE_OR_CONFLICTING"),
        ("conflict", "D1_MARKET_WINDOW_DUPLICATE_OR_CONFLICTING"),
        ("gap", "D1_MARKET_WINDOW_GAPPED"),
        ("wrong_duration", "D1_MARKET_BAR_DURATION_INVALID"),
        ("missing_retrieval", "D1_MARKET_RETRIEVAL_TIME_MISSING"),
        ("early_retrieval", "D1_MARKET_RETRIEVED_BEFORE_CLOSE"),
        ("future_retrieval", "D1_MARKET_FUTURE_SOURCE_REF"),
        ("unclosed", "D1_MARKET_BAR_UNCLOSED_AT_CUTOFF"),
        ("nonpositive", "D1_MARKET_OHLC_INVALID"),
        ("nan", "D1_MARKET_OHLC_INVALID"),
        ("expired_window", "D1_MARKET_WINDOW_EXPIRED"),
        ("observe_quality", "D1_MARKET_QUALITY_NOT_ACCEPTED"),
        ("missing_raw", "D1_MARKET_RAW_LINEAGE_MISSING"),
        ("bad_raw_hash", "D1_MARKET_RAW_HASH_INVALID"),
    ],
)
def test_market_completeness_provenance_and_quality_fail_closed(case: str, expected_reason: str) -> None:
    rows = _rows()
    if case == "wrong_timeframe":
        rows = [{**row, "timeframe": "5m"} for row in rows]
    elif case == "gc":
        rows = [{**row, "asset": "GC"} for row in rows]
    elif case == "fallback":
        rows = [
            {
                **row,
                "source": "fixture_xauusd_primary_1d",
                "source_ref": {**row["source_ref"], "source_role": "fallback"},
            }
            for row in rows
        ]
    elif case == "staging":
        rows = [
            {
                **row,
                "source_ref": {**row["source_ref"], "source_role": "staging_primary"},
            }
            for row in rows
        ]
    elif case == "provider_ambiguity":
        rows[0]["source"] = "alternate_primary"
    elif case == "incomplete":
        rows = rows[:1]
    elif case == "duplicate":
        rows[1] = deepcopy(rows[0])
    elif case == "conflict":
        rows.append({**deepcopy(rows[-1]), "close": 4491.0})
    elif case == "gap":
        rows[1]["open_time"] = (WINDOW_END - timedelta(hours=23)).isoformat()
        rows[1]["close_time"] = (WINDOW_END + timedelta(hours=1)).isoformat()
        rows[1]["source_ref"]["retrieved_at"] = rows[1]["close_time"]
        cutoff = CUTOFF + timedelta(hours=2)
        result = produce_gold_key_level_market_events(
            previous_states=(_state(),), candidates=rows, decision_as_of=cutoff
        )
        assert not result.controls_input.ordered_events
        assert expected_reason in result.reason_codes
        return
    elif case == "wrong_duration":
        rows[0]["open_time"] = (WINDOW_END - timedelta(days=2, hours=1)).isoformat()
    elif case == "missing_retrieval":
        rows[0]["source_ref"].pop("retrieved_at")
    elif case == "early_retrieval":
        rows[-1]["source_ref"]["retrieved_at"] = (
            WINDOW_END - timedelta(seconds=1)
        ).isoformat()
    elif case == "future_retrieval":
        rows[-1]["source_ref"]["retrieved_at"] = (CUTOFF + timedelta(seconds=1)).isoformat()
    elif case == "unclosed":
        rows[-1]["open_time"] = (CUTOFF - timedelta(hours=23)).isoformat()
        rows[-1]["close_time"] = (CUTOFF + timedelta(hours=1)).isoformat()
    elif case == "nonpositive":
        rows[0]["low"] = 0
    elif case == "nan":
        rows[0]["close"] = float("nan")
    elif case == "expired_window":
        rows = _rows(end=CUTOFF - timedelta(days=1))
    elif case == "observe_quality":
        rows[0]["source_ref"]["quality_status"] = "observe"
    elif case == "missing_raw":
        rows[0]["raw_path"] = ""
    elif case == "bad_raw_hash":
        rows[0]["source_ref"]["sha256"] = "not-a-sha256"

    result = produce_gold_key_level_market_events(
        previous_states=(_state(),), candidates=rows, decision_as_of=CUTOFF
    )

    assert not result.controls_input.ordered_events
    assert result.controls_input.previous_states == (_state(),)
    assert expected_reason in result.reason_codes


@pytest.mark.parametrize("location", ["row", "source_ref"])
@pytest.mark.parametrize(
    ("field_name", "accepted", "degraded", "expected_reason"),
    [
        ("quality_status", "accepted", "observe", "D1_MARKET_QUALITY_NOT_ACCEPTED"),
        ("freshness_status", "fresh", "stale", "D1_MARKET_FRESHNESS_NOT_FRESH"),
        ("alignment_status", "aligned", "misaligned", "D1_MARKET_ALIGNMENT_NOT_ALIGNED"),
    ],
)
def test_either_quality_declaration_rejects_when_the_other_is_accepted(
    location: str,
    field_name: str,
    accepted: str,
    degraded: str,
    expected_reason: str,
) -> None:
    rows = _rows()
    for row in rows:
        row[field_name] = accepted
        row["source_ref"][field_name] = accepted
    target = rows[0] if location == "row" else rows[0]["source_ref"]
    target[field_name] = degraded

    result = produce_gold_key_level_market_events(
        previous_states=(_state(),), candidates=rows, decision_as_of=CUTOFF
    )

    assert result.controls_input.ordered_events == ()
    assert expected_reason in result.reason_codes


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (_state(lifecycle="candidate"), "KEY_LEVEL_STATE_NOT_CANONICAL_LIVE"),
        (_state(lifecycle="broken"), "KEY_LEVEL_STATE_NOT_CANONICAL_LIVE"),
        (_state(expires_at=CUTOFF), "KEY_LEVEL_STATE_EXPIRED_OR_NOT_EFFECTIVE"),
    ],
)
def test_unqualified_or_expired_state_is_preserved_without_inventing_events(state, reason: str) -> None:
    result = produce_gold_key_level_market_events(
        previous_states=(state,), candidates=_rows(), decision_as_of=CUTOFF
    )

    assert result.controls_input.previous_states == (state,)
    assert result.controls_input.ordered_events == ()
    assert reason in result.reason_codes


def test_non_breaking_window_preserves_state_with_explicit_missingness() -> None:
    state = _state(role="support")
    result = produce_gold_key_level_market_events(
        previous_states=(state,), candidates=_rows(close=4510), decision_as_of=CUTOFF
    )

    assert result.controls_input.previous_states == (state,)
    assert result.controls_input.ordered_events == ()
    assert result.reason_codes == ("KEY_LEVEL_BREAK_NOT_CONFIRMED",)


def test_missing_market_input_and_window_not_newer_than_state_are_explicit() -> None:
    state = _state()
    missing = produce_gold_key_level_market_events(
        previous_states=(state,), candidates=(), decision_as_of=CUTOFF
    )
    current_state = _direct_state("holding", spec=state.spec, as_of=WINDOW_END)
    replayed = produce_gold_key_level_market_events(
        previous_states=(current_state,), candidates=_rows(), decision_as_of=CUTOFF
    )

    assert missing.controls_input.previous_states == (state,)
    assert missing.reason_codes == ("D1_MARKET_CANDIDATES_MISSING",)
    assert replayed.controls_input.previous_states == (current_state,)
    assert replayed.controls_input.ordered_events == ()
    assert replayed.reason_codes == ("D1_MARKET_WINDOW_NOT_NEWER_THAN_STATE",)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_actual_market_window_reaches_runtime_and_typed_loop_invalidation(version: str) -> None:
    predecessor, previous, current = _predecessor_case(version)
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    end = current.as_of
    state = _direct_state(
        "holding",
        spec=_spec(
            reference_price="4500",
            effective_from=end - timedelta(days=30),
            expires_at=end + timedelta(days=30),
            origin_key=f"producer-runtime:{version}",
        ),
        as_of=end - timedelta(days=3),
    )
    production = produce_gold_key_level_market_events(
        previous_states=(state,), candidates=_rows(end=end), decision_as_of=support.decision_as_of
    )
    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=production.controls_input,
    )

    assert controls.transition_evidence.delta_kind.value == "hard_invalidation"
    loop = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=previous,
        previous_policy_input=predecessor.strategy_policy_input,
        previous_state=predecessor.analysis_state,
        previous_strategy=predecessor.candidate_strategy,
        previous_transition=predecessor.transition_decision,
        transition_evidence=controls.transition_evidence,
        options_regime=controls.options_regime,
        event_risk=controls.event_risk,
        key_levels=controls.key_levels,
        key_level_decisions=controls.key_level_decisions,
        key_level_proof=controls.key_level_proof,
    )
    assert evaluate_gold_daily_close_loop(loop).transition_decision.action.value == "invalidate"


def _event_with_window_end(event, *, window_end: datetime):
    receipt_payload = event.evidence.qualification_receipt.model_dump(
        mode="python", exclude={"receipt_id", "receipt_hash"}
    )
    receipt_payload.update(
        current_snapshot_as_of=window_end,
        previous_snapshot_as_of=window_end - timedelta(days=1),
    )
    receipt = _build_key_level_qualification_receipt(
        KeyLevelQualificationReceiptInput.model_validate(receipt_payload)
    )
    evidence = event.evidence.model_dump(mode="python")
    evidence.update(
        evidence_id=f"reissued-window:{window_end.isoformat()}",
        window_start=window_end - timedelta(days=2),
        window_end=window_end,
        qualification_receipt=receipt,
    )
    evidence["price_fact"].update(
        window_start=evidence["window_start"],
        window_end=window_end,
    )
    evidence["source_refs"] = [
        {**source_ref, "reference": receipt.receipt_id}
        if source_ref["source"] == "qualification_receipt"
        else source_ref
        for source_ref in evidence["source_refs"]
    ]
    return build_key_level_event(
        {"event_type": "break_confirmed", "spec": event.spec, "evidence": evidence}
    )


def _runtime_controls_for_window_age(*, age: timedelta):
    predecessor, previous, current = _predecessor_case("v1")
    support = _policy_input(feature=current, attribution=attribute_gold_price(current, previous))
    decision_as_of = support.decision_as_of
    state = _direct_state(
        "holding",
        spec=_spec(
            reference_price="4500",
            effective_from=decision_as_of - timedelta(days=30),
            expires_at=decision_as_of + timedelta(days=30),
            origin_key=f"producer-runtime-age:{age.total_seconds()}",
        ),
        as_of=decision_as_of - timedelta(days=3),
    )
    production = produce_gold_key_level_market_events(
        previous_states=(state,), candidates=_rows(end=current.as_of), decision_as_of=decision_as_of
    )
    event = production.controls_input.ordered_events[0]
    window_end = decision_as_of - age
    assert window_end > predecessor.transition_decision.evidence.as_of
    reissued_event = _event_with_window_end(event, window_end=window_end)
    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=predecessor.transition_decision,
        decision_as_of=decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=KeyLevelControlsInput(
            decision_as_of=decision_as_of,
            scope="daily_close",
            previous_states=(state,),
            ordered_events=(reissued_event,),
        ),
    )
    return controls


def test_runtime_rejects_window_at_exact_24_hour_freshness_boundary() -> None:
    controls = _runtime_controls_for_window_age(age=timedelta(days=1))

    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert "HARD_INVALIDATION_BREAK_PROOF_INVALID" in controls.reason_codes


def test_runtime_rejects_old_window_reissued_with_fresh_decision_cutoff() -> None:
    controls = _runtime_controls_for_window_age(age=timedelta(days=2))

    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert "HARD_INVALIDATION_BREAK_PROOF_INVALID" in controls.reason_codes


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_archived_window_cannot_be_reissued_at_new_decision_cutoff(version: str) -> None:
    predecessor, previous, current, support = _same_session_case(version)
    transition = _transition_with_evidence_as_of(predecessor.transition_decision, current.as_of)
    state = _direct_state(
        "holding",
        spec=_spec(
            reference_price="4500",
            effective_from=current.as_of - timedelta(days=30),
            expires_at=current.as_of + timedelta(days=30),
            origin_key=f"producer-reissue:{version}",
        ),
        as_of=current.as_of - timedelta(days=3),
    )
    production = produce_gold_key_level_market_events(
        previous_states=(state,),
        candidates=_rows(end=current.as_of),
        decision_as_of=support.decision_as_of,
    )
    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=previous,
        previous_transition=transition,
        decision_as_of=support.decision_as_of,
        options_regime_snapshot=support.options_regime,
        key_level_controls_input=production.controls_input,
    )

    assert production.controls_input.ordered_events[0].evidence.window_end == transition.evidence.as_of
    assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
    assert "HARD_INVALIDATION_BREAK_PROOF_INVALID" in controls.reason_codes
