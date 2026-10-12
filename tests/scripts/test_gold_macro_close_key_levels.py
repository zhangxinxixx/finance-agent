from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_runtime import execute_gold_daily_close_runtime
from apps.analysis.gold_policy.daily_close_store import (
    load_gold_daily_close_head,
    persist_gold_daily_close_run,
    verify_gold_daily_close_bundle,
)
from database.models.analysis import MarketCandle
from scripts import run_daily_macro_close as close
from tests.analysis.test_gold_daily_close_store import _bootstrap_pair
from tests.analysis.test_gold_key_level_policy import _direct_state, _spec
from tests.analysis.test_gold_strategy_policy import _snapshot


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _verified_predecessor(root: Path):
    bootstrap, _ = _bootstrap_pair()
    holding = _direct_state(
        "holding",
        spec=_spec(
            reference_price="4500.00",
            effective_from=bootstrap.decision_as_of - timedelta(days=3),
        ),
        as_of=bootstrap.decision_as_of - timedelta(days=2),
    )
    prior_input = type(bootstrap).model_validate({**bootstrap.model_dump(mode="python"), "key_levels": (holding,)})
    persist_gold_daily_close_run(
        storage_root=root,
        run_id="macro-key-level-predecessor",
        loop_input=prior_input,
        result=evaluate_gold_daily_close_loop(prior_input),
    )
    lookup = load_gold_daily_close_head(storage_root=root)
    assert lookup.status == "found"
    assert lookup.head is not None
    return lookup.head, _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")


def _market_session(root: Path, *, current, variant: str = "complete"):
    engine = create_engine("sqlite://")
    MarketCandle.__table__.create(engine)
    session = Session(engine)
    rows: list[MarketCandle] = []
    if variant != "missing":
        for offset in (1, 0):
            close_time = current.as_of - timedelta(days=offset)
            open_time = close_time - timedelta(days=1)
            source = "fixture_xauusd_primary_1d"
            raw_path = Path("raw/market") / f"{offset}.json"
            archive_path = root / raw_path
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "asset": "XAUUSD",
                "timeframe": "1d",
                "source": source,
                "open_time": open_time.isoformat(),
                "close_time": close_time.isoformat(),
                "open": 4490.0,
                "high": 4495.0,
                "low": 4485.0,
                "close": 4490.0,
                "source_ref": {
                    "instrument_type": "otc_spot_quote_proxy",
                    "quality_status": "accepted",
                    "freshness_status": "fresh",
                    "alignment_status": "aligned",
                },
            }
            if variant == "invalid" and offset == 0:
                payload["interval"] = "5m"
            if variant == "degraded" and offset == 0:
                payload["source_ref"]["quality_status"] = "observe"
            raw_bytes = json.dumps(payload, sort_keys=True).encode()
            archive_path.write_bytes(raw_bytes)
            row = MarketCandle(
                asset="XAUUSD",
                timeframe="1d",
                open_time=open_time,
                open=4490.0,
                high=4495.0,
                low=4485.0,
                close=4490.0,
                source=source,
                source_ref={
                    "provider_symbol": "XAUUSD",
                    "instrument_type": "otc_spot_quote_proxy",
                    "source_role": "market_primary",
                    "quality_status": "accepted",
                    "freshness_status": "fresh",
                    "alignment_status": "aligned",
                    "retrieved_at": close_time.isoformat(),
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                },
                raw_path=raw_path.as_posix(),
            )
            session.add(row)
            rows.append(row)
        session.commit()
        if variant == "tampered":
            (root / rows[-1].raw_path).write_text('{"tampered": true}', encoding="utf-8")
        elif variant == "pending":
            rows[-1].close = 4491.0
    return engine, session


def _prepare_current(monkeypatch: pytest.MonkeyPatch, current) -> None:
    monkeypatch.setattr(
        "apps.analysis.gold_policy.runtime_inputs.prepare_gold_policy_runtime_inputs",
        lambda **kwargs: SimpleNamespace(
            current=current,
            previous=None,
            lookup=SimpleNamespace(summary=lambda: {}),
        ),
    )


def test_verified_archived_d1_builds_actual_hard_invalidation_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, current = _verified_predecessor(tmp_path)
    engine, session = _market_session(tmp_path, current=current)
    _prepare_current(monkeypatch, current)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    before = _tree_digest(tmp_path)

    try:
        runtime_kwargs, summary = close._gold_policy_runtime_kwargs(
            storage_root=tmp_path,
            snapshot={},
            decision_as_of=current.as_of + timedelta(minutes=5),
            run_id="macro-key-level-positive",
            db=session,
        )

        controls = runtime_kwargs["gold_daily_close_controls_prebuilt"]
        assert summary["status"] == "ready"
        assert summary["formal_key_levels"]["status"] == "ready"
        assert summary["formal_key_levels"]["produced_event_count"] == 1
        assert summary["formal_key_level_reasons"] == ["KEY_LEVEL_BREAK_EVENTS_PRODUCED"]
        assert controls.transition_evidence.delta_kind.value == "hard_invalidation"
        assert controls.key_level_proof[0].event.evidence.window_end == current.as_of
        assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        assert _tree_digest(tmp_path) == before
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("variant", ["invalid", "missing", "degraded", "tampered", "pending"])
def test_ineligible_d1_never_manufactures_hard_proof_or_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    _, current = _verified_predecessor(tmp_path)
    engine, session = _market_session(tmp_path, current=current, variant=variant)
    _prepare_current(monkeypatch, current)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    before = _tree_digest(tmp_path)

    try:
        runtime_kwargs, summary = close._gold_policy_runtime_kwargs(
            storage_root=tmp_path,
            snapshot={},
            decision_as_of=current.as_of + timedelta(minutes=5),
            run_id=f"macro-key-level-{variant}",
            db=session,
        )

        controls = runtime_kwargs["gold_daily_close_controls_prebuilt"]
        assert summary["status"] == "ready"
        assert summary["formal_key_levels"]["status"] == "missing"
        assert summary["formal_key_levels"]["produced_event_count"] == 0
        assert controls.transition_evidence.delta_kind.value != "hard_invalidation"
        assert controls.key_level_proof == ()
        assert not any(
            statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements
        )
        if variant == "pending":
            assert statements == []
        else:
            assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        assert _tree_digest(tmp_path) == before
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def test_none_db_preserves_levels_and_no_head_keeps_legacy_empty_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, current = _verified_predecessor(tmp_path)
    _prepare_current(monkeypatch, current)

    with_levels, missing_summary = close._gold_policy_runtime_kwargs(
        storage_root=tmp_path,
        snapshot={},
        decision_as_of=current.as_of + timedelta(minutes=5),
        run_id="macro-key-level-no-db",
        db=None,
    )
    assert missing_summary["formal_key_level_reasons"] == ["D1_MARKET_DATABASE_UNAVAILABLE"]
    assert len(with_levels["gold_daily_close_controls_prebuilt"].key_levels) == 1
    assert with_levels["gold_daily_close_controls_prebuilt"].key_level_proof == ()

    no_head_root = tmp_path / "no-head"
    engine, session = _market_session(no_head_root, current=current)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    try:
        without_levels, no_head_summary = close._gold_policy_runtime_kwargs(
            storage_root=no_head_root,
            snapshot={},
            decision_as_of=current.as_of + timedelta(minutes=5),
            run_id="macro-key-level-no-head",
            db=session,
        )
        assert no_head_summary["formal_key_levels"]["status"] == "not_applicable"
        assert no_head_summary["formal_key_level_reasons"] == ["NO_PREVIOUS_KEY_LEVEL_STATES"]
        controls = without_levels["gold_daily_close_controls_prebuilt"]
        assert controls.key_levels == ()
        assert controls.key_level_proof == ()
        assert statements == []
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("runner_status", "expected_code"),
    [("completed", 0), ("blocked", 2)],
)
def test_main_owns_and_closes_input_session_without_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_status: str,
    expected_code: int,
) -> None:
    class OwnedSession:
        entered = False
        exited = False

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.exited = True

        def commit(self):
            raise AssertionError("Macro close input session must never commit")

    owned = OwnedSession()
    captured: dict[str, object] = {}
    args = SimpleNamespace(date="2025-01-24", storage_root=str(tmp_path), asset="XAUUSD", run_id="owned")
    monkeypatch.setattr(close, "SessionLocal", lambda: owned)
    monkeypatch.setattr(close, "_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(
        close,
        "run_daily_macro_close",
        lambda **kwargs: captured.update(kwargs) or {"status": runner_status},
    )

    assert close.main() == expected_code
    assert captured["db"] is owned
    assert owned.entered and owned.exited


def test_outer_runner_forwards_exact_session_to_loader_and_real_runtime_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, current = _verified_predecessor(tmp_path)
    engine, session = _market_session(tmp_path, current=current)
    _prepare_current(monkeypatch, current)
    snapshot_path = (
        tmp_path / "features/snapshots/XAUUSD" / current.as_of.date().isoformat() / "premarket/premarket_snapshot.json"
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "trade_date": current.as_of.date().isoformat(),
                "snapshot_time": (current.as_of + timedelta(minutes=5)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        close,
        "build_daily_analysis_context",
        lambda **kwargs: {"status": "fixture", "source_refs": []},
    )
    actual_loader = close.load_gold_key_level_market_inputs
    loader_sessions: list[object] = []

    def tracked_loader(**kwargs):
        loader_sessions.append(kwargs["db"])
        return actual_loader(**kwargs)

    pipeline_calls: list[dict] = []

    def typed_runtime_pipeline(**kwargs):
        assert "db" not in kwargs
        pipeline_calls.append(kwargs)
        execution = execute_gold_daily_close_runtime(
            storage_root=kwargs["storage_root"],
            run_id=kwargs["run_id"],
            current_feature=kwargs["gold_feature_snapshot_prebuilt"],
            controls=kwargs["gold_daily_close_controls_prebuilt"],
            bootstrap_previous_feature=kwargs.get("previous_gold_feature_snapshot_prebuilt"),
        )
        return {}, {"gold_daily_close_execution": execution}

    monkeypatch.setattr(close, "load_gold_key_level_market_inputs", tracked_loader)
    monkeypatch.setattr(close, "run_composite_analysis_pipeline", typed_runtime_pipeline)
    monkeypatch.setattr(session, "commit", lambda: pytest.fail("caller-supplied session must not commit"))

    try:
        first = close.run_daily_macro_close(
            trade_date=current.as_of.date().isoformat(),
            storage_root=tmp_path,
            run_id="macro-key-level-real-runtime",
            db=session,
        )
        assert first["status"] == "completed"
        assert loader_sessions == [session]
        assert len(pipeline_calls) == 1
        controls = pipeline_calls[0]["gold_daily_close_controls_prebuilt"]
        assert controls.transition_evidence.delta_kind.value == "hard_invalidation"
        assert first["gold_policy_runtime"]["formal_key_levels"]["produced_event_count"] == 1
        bundle = (
            tmp_path
            / "analysis/gold_mainlines"
            / current.as_of.date().isoformat()
            / "macro-key-level-real-runtime/daily_close"
        )
        verified = verify_gold_daily_close_bundle(storage_root=tmp_path, bundle_path=bundle)
        assert verified.status == "valid"
        transition = json.loads((bundle / "state_transition_policy_decision.v1.json").read_text())
        assert transition["action"] == "invalidate"
        assert session.scalar(select(1)) == 1

        frozen = _tree_digest(tmp_path)
        statements: list[str] = []
        event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
        second = close.run_daily_macro_close(
            trade_date=current.as_of.date().isoformat(),
            storage_root=tmp_path,
            run_id="macro-key-level-real-runtime",
            db=session,
        )
        assert second["status"] == "complete"
        assert loader_sessions == [session]
        assert len(pipeline_calls) == 1
        assert statements == []
        assert _tree_digest(tmp_path) == frozen
        assert session.scalar(select(1)) == 1
    finally:
        session.close()
        engine.dispose()
