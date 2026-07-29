from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from apps.features.news.formal_events import build_official_event_snapshot
from apps.features.news.market_binding import build_market_reaction


AS_OF = datetime(2026, 7, 29, 12, 31, tzinfo=UTC)
EVENT_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _ref(
    *,
    source_type: str | None,
    source: str = "fed",
    retrieved_at: datetime = EVENT_TIME,
    raw_path: bool = True,
) -> dict[str, str]:
    ref = {
        "source": source,
        "reference": f"https://example.test/{source_type or 'market'}/{source}",
        "retrieved_at": retrieved_at.isoformat(),
    }
    if source_type is not None:
        ref["source_type"] = source_type
    if raw_path:
        ref["raw_path"] = f"raw/{source_type or 'market'}/{source}.json"
    return ref


def _candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "event_id": "fed-20260729",
        "title": "Federal Reserve release",
        "event_time": EVENT_TIME.isoformat(),
        "event_status": "released",
        "verification_status": "official_confirmed",
        "source_refs": [_ref(source_type="official")],
    }
    candidate.update(overrides)
    return candidate


def _candle_ref(
    *,
    role: str,
    open_time: datetime,
    retrieved_at: datetime = AS_OF,
) -> dict[str, str]:
    return {
        "role": role,
        "asset": "XAUUSD",
        "timeframe": "1m",
        "open_time": open_time.isoformat(),
        "source": f"xauusd-{role}",
        "reference": f"market://xauusd/{role}",
        "retrieved_at": retrieved_at.isoformat(),
        "retrieval_basis": "source_ref.retrieved_at",
    }


def _reaction(**overrides: object) -> dict[str, object]:
    baseline_time = EVENT_TIME - timedelta(minutes=1)
    after_time = EVENT_TIME + timedelta(minutes=30)
    reaction: dict[str, object] = {
        "event_id": "fed-20260729",
        "status": "available",
        "windows": {
            "30m": {
                "XAUUSD": {
                    "baseline_time": baseline_time.isoformat(),
                    "after_time": after_time.isoformat(),
                    "pct_change": 0.42,
                    "threshold_hit": True,
                    "baseline_candle_refs": [
                        _candle_ref(role="baseline", open_time=baseline_time)
                    ],
                    "after_candle_refs": [
                        _candle_ref(role="after", open_time=after_time)
                    ],
                }
            }
        },
    }
    reaction.update(overrides)
    return reaction


def test_confirmed_official_event_requires_exact_structured_xauusd_window() -> None:
    snapshot = build_official_event_snapshot(candidates=[_candidate()], reactions=[_reaction()], as_of=AS_OF)

    assert (snapshot.schema_version, snapshot.readiness) == ("official_event_snapshot.v1", "ready")
    assert (snapshot.freshness_status, snapshot.quality_status, snapshot.alignment_status) == ("fresh", "accepted", "aligned")
    event = snapshot.events[0]
    assert (event.reaction_status, event.reaction_asset, event.reaction_return_pct) == ("confirmed", "XAUUSD", 0.42)
    assert event.reaction_summary == "XAUUSD 30m reaction +0.4200%"
    assert event.reaction_baseline_time == EVENT_TIME - timedelta(minutes=1)
    assert event.reaction_after_time == EVENT_TIME + timedelta(minutes=30)
    assert event.reaction_window_end == EVENT_TIME + timedelta(minutes=30)
    assert len(event.reaction_source_refs) == 2
    assert {ref.source_type for ref in snapshot.source_refs} == {"official", None}


def test_real_market_reaction_lineage_contract_can_confirm() -> None:
    candidate = _candidate(asset_tags=["XAUUSD"])
    source_ref = {
        "source": "twelve_data",
        "reference": "market://xauusd",
        "raw_path": "raw/market/xauusd.json",
        "retrieved_at": AS_OF.isoformat(),
    }
    reaction = build_market_reaction(
        candidate,
        {"event_id": candidate["event_id"], "gold_impact": "bullish"},
        {
            "XAUUSD": [
                {
                    "asset": "XAUUSD",
                    "timeframe": "1m",
                    "open_time": (EVENT_TIME - timedelta(minutes=1)).isoformat(),
                    "close": 2300.0,
                    "source": "twelve_data",
                    "source_ref": source_ref,
                },
                {
                    "asset": "XAUUSD",
                    "timeframe": "1m",
                    "open_time": (EVENT_TIME + timedelta(minutes=30)).isoformat(),
                    "close": 2310.0,
                    "source": "twelve_data",
                    "source_ref": source_ref,
                },
            ]
        },
        windows=("30m",),
    )

    snapshot = build_official_event_snapshot(
        candidates=[candidate],
        reactions=[reaction.to_dict()],
        as_of=AS_OF,
    )

    assert snapshot.events[0].reaction_status == "confirmed"
    assert {ref.role for ref in snapshot.events[0].reaction_source_refs} == {
        "baseline",
        "after",
    }


@pytest.mark.parametrize("change", ["missing_refs", "partial", "late_after"])
def test_partial_or_incomplete_reactions_never_become_confirmed(change: str) -> None:
    reaction = _reaction()
    window = reaction["windows"]["30m"]["XAUUSD"]  # type: ignore[index]
    if change == "missing_refs":
        window.pop("after_candle_refs")  # type: ignore[union-attr]
    elif change == "partial":
        reaction["status"] = "partial"
    else:
        window["after_time"] = (EVENT_TIME + timedelta(minutes=31)).isoformat()  # type: ignore[index]

    snapshot = build_official_event_snapshot(candidates=[_candidate()], reactions=[reaction], as_of=AS_OF)
    assert snapshot.readiness == "observe"
    assert snapshot.events[0].reaction_status == "observe"
    assert snapshot.events[0].reaction_asset is None


def test_late_official_event_cannot_explain_an_earlier_market_move() -> None:
    reaction = _reaction()
    window = reaction["windows"]["30m"]["XAUUSD"]  # type: ignore[index]
    window["baseline_time"] = (EVENT_TIME - timedelta(minutes=10)).isoformat()  # type: ignore[index]
    window["after_time"] = (EVENT_TIME - timedelta(minutes=5)).isoformat()  # type: ignore[index]
    snapshot = build_official_event_snapshot(candidates=[_candidate()], reactions=[reaction], as_of=AS_OF)

    assert snapshot.events[0].reaction_status == "observe"
    assert snapshot.events[0].reaction_return_pct is None


def test_empty_normal_event_scan_is_observe_not_missing_or_blocked() -> None:
    snapshot = build_official_event_snapshot(
        candidates=[{"event_id": "wire", "verification_status": "single_source", "event_status": "released"}],
        reactions=[],
        as_of=AS_OF,
    )

    assert snapshot.events == ()
    assert (snapshot.freshness_status, snapshot.quality_status, snapshot.alignment_status, snapshot.readiness) == ("fresh", "observe", "aligned", "observe")
    assert snapshot.source_refs[0].source == "official_event_snapshot_query"


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(event_time=(AS_OF + timedelta(minutes=1)).isoformat()),
        _candidate(source_refs=[_ref(source_type="wire")]),
        {"event_id": "multi", "verification_status": "multi_source", "event_status": "released", "source_refs": []},
    ],
)
def test_pit_or_pseudo_official_candidates_are_blocked_and_not_included(candidate: dict[str, object]) -> None:
    snapshot = build_official_event_snapshot(candidates=[candidate], reactions=[], as_of=AS_OF)

    assert snapshot.events == ()
    assert (snapshot.quality_status, snapshot.alignment_status, snapshot.readiness) == ("blocked", "misaligned", "blocked")


def test_valid_future_scheduled_release_is_observe_not_blocked() -> None:
    snapshot = build_official_event_snapshot(
        candidates=[
            _candidate(
                event_status="scheduled",
                event_time=(AS_OF + timedelta(days=1)).isoformat(),
            )
        ],
        reactions=[],
        as_of=AS_OF,
    )

    assert snapshot.events == ()
    assert (snapshot.quality_status, snapshot.alignment_status, snapshot.readiness) == (
        "observe",
        "aligned",
        "observe",
    )


def test_future_reaction_is_point_in_time_blocked() -> None:
    reaction = _reaction()
    window = reaction["windows"]["30m"]["XAUUSD"]  # type: ignore[index]
    window["after_time"] = (AS_OF + timedelta(minutes=1)).isoformat()  # type: ignore[index]
    snapshot = build_official_event_snapshot(candidates=[_candidate()], reactions=[reaction], as_of=AS_OF)

    assert snapshot.events[0].reaction_status == "observe"
    assert snapshot.readiness == "blocked"
    assert snapshot.reason_codes == ("REACTION_WINDOW_AFTER_AS_OF",)


def test_future_reaction_source_reference_is_point_in_time_blocked() -> None:
    reaction = _reaction()
    window = reaction["windows"]["30m"]["XAUUSD"]  # type: ignore[index]
    window["after_candle_refs"] = [
        _candle_ref(
            role="after",
            open_time=EVENT_TIME + timedelta(minutes=30),
            retrieved_at=AS_OF + timedelta(minutes=1),
        )
    ]

    snapshot = build_official_event_snapshot(
        candidates=[_candidate()],
        reactions=[reaction],
        as_of=AS_OF,
    )

    assert snapshot.events[0].reaction_status == "observe"
    assert snapshot.readiness == "blocked"
    assert snapshot.reason_codes == ("REACTION_CANDLE_RETRIEVED_AFTER_AS_OF",)
    assert snapshot.rejected_source_refs[0].source == "xauusd-after"
    assert snapshot.rejected_source_refs[0].retrieved_at == AS_OF + timedelta(minutes=1)


def test_blocked_batch_demotes_confirmed_events_and_keeps_audit_lineage() -> None:
    future = _candidate(
        event_id="future-official",
        event_time=(AS_OF + timedelta(minutes=1)).isoformat(),
        source_refs=[
            _ref(source_type="official", source="future-official")
        ],
    )

    snapshot = build_official_event_snapshot(
        candidates=[_candidate(), future],
        reactions=[_reaction()],
        as_of=AS_OF,
    )

    assert snapshot.readiness == "blocked"
    assert snapshot.events[0].reaction_status == "observe"
    assert snapshot.events[0].reaction_source_refs == ()
    assert snapshot.reason_codes == ("OFFICIAL_EVENT_AFTER_AS_OF",)
    assert any(ref.source == "future-official" for ref in snapshot.source_refs)


def test_candle_refs_must_match_role_asset_timeframe_and_open_time() -> None:
    reaction = _reaction()
    after_ref = reaction["windows"]["30m"]["XAUUSD"]["after_candle_refs"][0]  # type: ignore[index]
    after_ref["role"] = "baseline"  # type: ignore[index]

    snapshot = build_official_event_snapshot(
        candidates=[_candidate()],
        reactions=[reaction],
        as_of=AS_OF,
    )

    assert snapshot.events[0].reaction_status == "observe"


def test_snapshot_is_stable_and_does_not_mutate_input() -> None:
    candidates = [_candidate(source_refs=[_ref(source_type="official"), _ref(source_type="official")])]
    reactions = [_reaction()]
    original = deepcopy((candidates, reactions))
    outputs = [build_official_event_snapshot(candidates=candidates, reactions=reactions, as_of=AS_OF).model_dump(mode="json") for _ in range(100)]

    assert all(output == outputs[0] for output in outputs)
    assert (candidates, reactions) == original
    assert len(outputs[0]["source_refs"]) == 3
