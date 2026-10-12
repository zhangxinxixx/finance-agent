from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_runtime import execute_gold_daily_close_runtime
from apps.analysis.gold_policy.daily_close_store import (
    persist_gold_daily_close_run,
    verify_gold_daily_close_bundle,
)
from apps.analysis.gold_policy.key_level_controls import KeyLevelControlsBuilder
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelEventType,
    KeyLevelLifecycle,
    KeyLevelTransitionAction,
)
from apps.analysis.gold_policy.runtime_controls import build_gold_daily_close_runtime_controls
from apps.runtime.premarket_snapshot_authority import PremarketSnapshotAuthority
from database.models.analysis import MarketCandle, ensure_analysis_tables
from database.models.report import ensure_report_tables
from scripts import gold_key_level_market_inputs as market_inputs
from scripts import run_daily_macro_close as macro_close
from scripts import run_gold_daily_report as gold_report
from tests.analysis.test_gold_daily_close_store import _bootstrap_pair
from tests.analysis.test_gold_key_level_policy import _direct_state, _spec
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


def _persisted_predecessor(
    root: Path,
    *,
    lifecycle: str,
    role: str,
    state_as_of=None,
):
    base, _ = _bootstrap_pair()
    state_time = state_as_of or base.decision_as_of - timedelta(days=1)
    state = _direct_state(
        lifecycle,
        role=role,
        spec=_spec(
            role=role,
            reference_price="4500",
            effective_from=base.decision_as_of - timedelta(days=30),
            expires_at=base.decision_as_of + timedelta(days=180),
            origin_key=f"loader-lifecycle:{role}:{lifecycle}:{state_time.isoformat()}",
        ),
        as_of=state_time,
    )
    loop_input = base.model_copy(update={"key_levels": (state,)})
    write = persist_gold_daily_close_run(
        storage_root=root,
        run_id=f"predecessor-{role}-{lifecycle}",
        loop_input=loop_input,
        result=evaluate_gold_daily_close_loop(loop_input),
    )
    verified = verify_gold_daily_close_bundle(storage_root=root, bundle_path=write.bundle_path)
    assert verified.status == "valid"
    assert verified.head is not None
    assert verified.head.strategy_policy_input.key_levels == (state,)
    return verified.head, state


def _market_session(root: Path, *, window_end, close: float = 4500.0):
    engine = create_engine(f"sqlite:///{root / 'market-test.sqlite'}")
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    rows: list[MarketCandle] = []
    for offset in (1, 0):
        close_time = window_end - timedelta(days=offset)
        open_time = close_time - timedelta(days=1)
        raw_path = Path("raw/market/lifecycle") / f"{open_time.isoformat()}.json"
        archive_path = root / raw_path
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive = {
            "asset": "XAUUSD",
            "timeframe": "1d",
            "source": "fixture_xauusd_primary_1d",
            "open_time": open_time.isoformat(),
            "close_time": close_time.isoformat(),
            "open": close,
            "high": close + 5,
            "low": close - 5,
            "close": close,
            "source_ref": {
                "instrument_type": "otc_spot_quote_proxy",
                "quality_status": "accepted",
                "freshness_status": "fresh",
                "alignment_status": "aligned",
            },
        }
        raw = json.dumps(archive, sort_keys=True).encode()
        archive_path.write_bytes(raw)
        row = MarketCandle(
            asset="XAUUSD",
            timeframe="1d",
            open_time=open_time,
            open=close,
            high=close + 5,
            low=close - 5,
            close=close,
            source="fixture_xauusd_primary_1d",
            source_ref={
                "provider_symbol": "XAUUSD",
                "instrument_type": "otc_spot_quote_proxy",
                "source_role": "market_primary",
                "quality_status": "accepted",
                "freshness_status": "fresh",
                "alignment_status": "aligned",
                "retrieved_at": close_time.isoformat(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            raw_path=raw_path.as_posix(),
        )
        session.add(row)
        rows.append(row)
    session.commit()
    return engine, session, rows


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _write_premarket_snapshot(root: Path, current, *, decision_as_of) -> Path:
    path = (
        root
        / "features/snapshots/XAUUSD"
        / current.as_of.date().isoformat()
        / "premarket/premarket_snapshot.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "trade_date": current.as_of.date().isoformat(),
                "snapshot_time": decision_as_of.isoformat(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("role", ["support", "resistance"])
@pytest.mark.parametrize(
    ("lifecycle", "event_type", "action", "result_lifecycle", "eligible"),
    [
        ("candidate", KeyLevelEventType.CONFIRM, KeyLevelTransitionAction.CONFIRM, KeyLevelLifecycle.CONFIRMED, False),
        ("confirmed", KeyLevelEventType.ACTIVATE, KeyLevelTransitionAction.ACTIVATE, KeyLevelLifecycle.ACTIVE, True),
    ],
)
def test_verified_canonical_predecessor_and_archived_sql_roundtrip_lifecycle_proof(
    tmp_path: Path,
    role: str,
    lifecycle: str,
    event_type: KeyLevelEventType,
    action: KeyLevelTransitionAction,
    result_lifecycle: KeyLevelLifecycle,
    eligible: bool,
) -> None:
    head, state = _persisted_predecessor(tmp_path, lifecycle=lifecycle, role=role)
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    cutoff = current.as_of + timedelta(minutes=5)
    engine, session, _ = _market_session(tmp_path, window_end=current.as_of)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    before = _tree_digest(tmp_path)

    original_commit, original_flush, original_close = session.commit, session.flush, session.close
    session.commit = lambda: pytest.fail("readonly loader must not commit a supplied Session")
    session.flush = lambda *args, **kwargs: pytest.fail("readonly loader must not flush a supplied Session")
    session.close = lambda: pytest.fail("readonly loader must not close a supplied Session")
    try:
        loaded = market_inputs.load_gold_key_level_market_inputs(
            head=head,
            db=session,
            storage_root=tmp_path,
            decision_as_of=cutoff,
        )
        assert session.scalar(select(1)) == 1
    finally:
        session.commit, session.flush, session.close = original_commit, original_flush, original_close

    assert state.strategy_eligible is False
    assert loaded.summary.model_dump(mode="json") == {
        "schema_version": "formal_key_level_market_summary.v1",
        "status": "ready",
        "previous_key_level_count": 1,
        "queried_row_count": 2,
        "verified_row_count": 2,
        "produced_event_count": 1,
        "reason_codes": ["KEY_LEVEL_LIFECYCLE_EVENTS_PRODUCED"],
    }
    assert loaded.controls_input is not None
    assert loaded.controls_input.previous_states == (state,)
    assert len(loaded.controls_input.ordered_events) == 1
    produced = loaded.controls_input.ordered_events[0]
    assert produced.event_type is event_type
    assert produced.evidence.price_fact is not None
    assert produced.evidence.price_fact.rule_code == "price_structure"
    assert produced.evidence.quality_status == "accepted"
    assert produced.evidence.freshness_status == "fresh"
    assert produced.evidence.alignment_status == "aligned"
    assert {ref.source for ref in produced.evidence.source_refs} >= {
        "input_snapshot",
        "raw_market_artifact",
        "market_source_qualification",
        "qualification_receipt",
    }

    controls = KeyLevelControlsBuilder().build(loaded.controls_input)
    assert len(controls.key_level_proof) == 1
    proof = controls.key_level_proof[0]
    assert proof.action is action
    assert proof.transition_allowed is True
    assert proof.advance is True
    assert proof.to_lifecycle is result_lifecycle
    assert proof.to_strategy_eligible is eligible
    assert controls.key_levels[0].lifecycle is result_lifecycle
    assert controls.key_levels[0].strategy_eligible is eligible

    runtime = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=head.feature_snapshot,
        previous_transition=head.transition_decision,
        decision_as_of=cutoff,
        key_level_controls_input=loaded.controls_input,
    )
    assert runtime.key_level_proof == controls.key_level_proof
    assert runtime.key_levels == controls.key_levels
    assert runtime.transition_evidence.delta_kind.value != "hard_invalidation"
    assert not any("HARD_INVALIDATION" in code for code in runtime.reason_codes)
    assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert _tree_digest(tmp_path) == before
    session.close()
    engine.dispose()


@pytest.mark.parametrize(
    "case",
    [
        "degraded",
        "missing_raw",
        "row_mismatch",
        "hash_mismatch",
        "symlink",
        "identity_conflict",
        "pending_db",
        "stale_window",
        "previous_window",
    ],
)
def test_ineligible_archive_or_database_never_creates_lifecycle_authority(
    tmp_path: Path,
    case: str,
) -> None:
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    cutoff = current.as_of + timedelta(minutes=5)
    state_time = current.as_of - timedelta(days=4)
    market_end = current.as_of
    if case == "stale_window":
        market_end = cutoff - timedelta(days=1)
    elif case == "previous_window":
        market_end = current.as_of - timedelta(days=3)
        state_time = market_end - timedelta(days=1)
    head, state = _persisted_predecessor(
        tmp_path,
        lifecycle="candidate",
        role="support",
        state_as_of=state_time,
    )
    engine, session, rows = _market_session(tmp_path, window_end=market_end)
    target = rows[-1]

    if case == "degraded":
        target.source_ref = {**target.source_ref, "quality_status": "observe"}
        session.commit()
    elif case == "missing_raw":
        (tmp_path / target.raw_path).unlink()
    elif case in {"row_mismatch", "hash_mismatch"}:
        path = tmp_path / target.raw_path
        payload = json.loads(path.read_bytes())
        payload["close"] = 4499.0
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        if case == "row_mismatch":
            target.source_ref = {**target.source_ref, "sha256": hashlib.sha256(raw).hexdigest()}
            session.commit()
    elif case == "symlink":
        path = tmp_path / target.raw_path
        referent = path.with_name("referent.json")
        path.rename(referent)
        path.symlink_to(referent)
    elif case == "identity_conflict":
        target.source_ref = {**target.source_ref, "raw_path": "raw/market/lifecycle/conflict.json"}
        session.commit()
    elif case == "pending_db":
        session.add(
            MarketCandle(
                asset="XAUUSD",
                timeframe="1d",
                open_time=current.as_of,
                open=4500,
                high=4505,
                low=4495,
                close=4500,
                source="fixture_xauusd_primary_1d",
                source_ref={},
            )
        )

    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    before = _tree_digest(tmp_path)
    loaded = market_inputs.load_gold_key_level_market_inputs(
        head=head,
        db=session,
        storage_root=tmp_path,
        decision_as_of=cutoff,
    )

    assert loaded.summary.status == "missing"
    assert loaded.summary.produced_event_count == 0
    assert loaded.controls_input is not None
    assert loaded.controls_input.previous_states == (state,)
    assert loaded.controls_input.ordered_events == ()
    retained = KeyLevelControlsBuilder().build(loaded.controls_input)
    assert retained.key_levels == (state,)
    assert retained.key_level_proof == ()
    assert retained.key_levels[0].authority_status == state.authority_status
    assert retained.key_levels[0].strategy_eligible is False
    assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements)
    if case == "pending_db":
        assert statements == []
    assert _tree_digest(tmp_path) == before
    session.rollback()
    session.close()
    engine.dispose()


def test_no_head_no_levels_and_missing_database_keep_legacy_short_circuits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        market_inputs,
        "list_completed_market_candles",
        lambda *args, **kwargs: pytest.fail("no predecessor level must not query"),
    )
    no_head = market_inputs.load_gold_key_level_market_inputs(
        head=None,
        db=None,
        storage_root=tmp_path,
        decision_as_of=_snapshot("feature_snapshot_v1_mixed_2025-01-24.json").as_of,
    )
    no_levels = market_inputs.load_gold_key_level_market_inputs(
        head=SimpleNamespace(strategy_policy_input=SimpleNamespace(key_levels=())),
        db=None,
        storage_root=tmp_path,
        decision_as_of=_snapshot("feature_snapshot_v1_mixed_2025-01-24.json").as_of,
    )
    assert no_head == no_levels
    assert no_head.controls_input is None
    assert no_head.summary.status == "not_applicable"

    head, state = _persisted_predecessor(tmp_path, lifecycle="candidate", role="support")
    missing_db = market_inputs.load_gold_key_level_market_inputs(
        head=head,
        db=None,
        storage_root=tmp_path,
        decision_as_of=head.feature_snapshot.as_of + timedelta(minutes=5),
    )
    assert missing_db.summary.reason_codes == ("D1_MARKET_DATABASE_UNAVAILABLE",)
    assert missing_db.controls_input is not None
    assert missing_db.controls_input.previous_states == (state,)
    assert missing_db.controls_input.ordered_events == ()


def test_gold_report_runner_persists_verified_confirm_proof_without_hard_invalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _persisted_predecessor(tmp_path, lifecycle="candidate", role="support")
    current = _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")
    decision_as_of = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, _bootstrap_pair()[0].current_feature),
    ).decision_as_of
    snapshot_path = _write_premarket_snapshot(tmp_path, current, decision_as_of=decision_as_of)
    engine, session, _ = _market_session(tmp_path, window_end=current.as_of)
    monkeypatch.setattr(gold_report, "prepare_gold_policy_current_feature", lambda **kwargs: current)
    monkeypatch.setattr(
        gold_report,
        "resolve_gold_daily_report_premarket_snapshot",
        lambda *args, **kwargs: PremarketSnapshotAuthority(
            status="found",
            reason_code="test_authority",
            snapshot_path=snapshot_path,
            run_id="verified-premarket",
            snapshot_id=current.snapshot_id,
            file_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        ),
    )

    result = gold_report.run_gold_daily_report(
        trade_date=current.as_of.date().isoformat(),
        storage_root=tmp_path,
        run_id="report-candidate-confirm",
        db=session,
    )

    assert result["status"] == "completed", result
    bundle = Path(result["report_paths"][0]).parent
    verified = verify_gold_daily_close_bundle(storage_root=tmp_path, bundle_path=bundle)
    assert verified.status == "valid"
    loop_input = json.loads((bundle / "gold_daily_close_loop_input.v1.json").read_text(encoding="utf-8"))
    assert [item["event"]["event_type"] for item in loop_input["key_level_proof"]] == ["confirm"]
    assert loop_input["key_level_proof"][0]["transition_allowed"] is True
    assert loop_input["key_level_proof"][0]["to_lifecycle"] == "confirmed"
    assert loop_input["key_level_proof"][0]["to_strategy_eligible"] is False
    assert loop_input["transition_evidence"]["delta_kind"] != "hard_invalidation"
    session.rollback()
    session.close()
    engine.dispose()


def test_macro_helper_and_runner_persist_verified_activation_and_idempotently_short_circuit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _persisted_predecessor(tmp_path, lifecycle="confirmed", role="resistance")
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    decision_as_of = current.as_of + timedelta(minutes=5)
    _write_premarket_snapshot(tmp_path, current, decision_as_of=decision_as_of)
    engine, session, _ = _market_session(tmp_path, window_end=current.as_of)
    monkeypatch.setattr(
        "apps.analysis.gold_policy.runtime_inputs.prepare_gold_policy_runtime_inputs",
        lambda **kwargs: SimpleNamespace(
            current=current,
            previous=None,
            lookup=SimpleNamespace(summary=lambda: {}),
        ),
    )
    monkeypatch.setattr(
        macro_close,
        "build_daily_analysis_context",
        lambda **kwargs: {"status": "fixture", "source_refs": []},
    )
    actual_loader = macro_close.load_gold_key_level_market_inputs
    loader_sessions: list[object] = []

    def tracked_loader(**kwargs):
        loader_sessions.append(kwargs["db"])
        return actual_loader(**kwargs)

    executions = []

    def typed_runtime_pipeline(**kwargs):
        execution = execute_gold_daily_close_runtime(
            storage_root=kwargs["storage_root"],
            run_id=kwargs["run_id"],
            current_feature=kwargs["gold_feature_snapshot_prebuilt"],
            controls=kwargs["gold_daily_close_controls_prebuilt"],
            bootstrap_previous_feature=kwargs.get("previous_gold_feature_snapshot_prebuilt"),
        )
        executions.append(execution)
        return {}, {"gold_daily_close_execution": execution}

    monkeypatch.setattr(macro_close, "load_gold_key_level_market_inputs", tracked_loader)
    monkeypatch.setattr(macro_close, "run_composite_analysis_pipeline", typed_runtime_pipeline)
    result = macro_close.run_daily_macro_close(
        trade_date=current.as_of.date().isoformat(),
        storage_root=tmp_path,
        run_id="macro-confirmed-activate",
        db=session,
    )

    assert result["status"] == "completed", result
    assert loader_sessions == [session]
    assert len(executions) == 1
    proof = executions[0].loop_input.key_level_proof
    assert len(proof) == 1
    assert proof[0].event.event_type is KeyLevelEventType.ACTIVATE
    assert proof[0].action is KeyLevelTransitionAction.ACTIVATE
    assert proof[0].to_lifecycle is KeyLevelLifecycle.ACTIVE
    assert proof[0].to_strategy_eligible is True
    assert executions[0].loop_input.transition_evidence.delta_kind.value != "hard_invalidation"
    verified = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=executions[0].write_result.bundle_path,
    )
    assert verified.status == "valid"

    frozen = _tree_digest(tmp_path)
    second = macro_close.run_daily_macro_close(
        trade_date=current.as_of.date().isoformat(),
        storage_root=tmp_path,
        run_id="macro-confirmed-activate",
        db=session,
    )
    assert second["status"] == "complete"
    assert loader_sessions == [session]
    assert len(executions) == 1
    assert _tree_digest(tmp_path) == frozen
    assert session.scalar(select(1)) == 1
    session.close()
    engine.dispose()
