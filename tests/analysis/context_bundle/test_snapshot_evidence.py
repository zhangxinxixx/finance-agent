from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from apps.analysis.context_bundle import build_state_shadow_input, project_snapshot_evidence
from apps.analysis.context_bundle.snapshot_evidence import SNAPSHOT_PASSPORT_METADATA_KEY
from apps.analysis.evidence_delta import adapt_context_evidence
from apps.worker.composite_state_shadow import prepare_composite_state_shadow
from database.models.analysis import AnalysisSnapshot


PREVIOUS_AT = datetime(2026, 7, 27, 9, tzinfo=UTC)
CURRENT_AT = datetime(2026, 7, 28, 9, tzinfo=UTC)


def _payload(
    *,
    snapshot_id: str,
    run_id: str,
    snapshot_time: datetime,
    dxy: float,
    price: float,
    gamma_zero: float,
    include_new_event: bool,
) -> dict:
    events = [
        {
            "title": "US consumer confidence",
            "pub_time": "2026-07-27T08:00:00+00:00",
            "star": 2,
        }
    ]
    if include_new_event:
        events.append(
            {
                "title": "Federal Reserve policy decision",
                "pub_time": "2026-07-28T08:00:00+00:00",
                "star": 5,
            }
        )
    refs = [
        {
            "source": "fred",
            "symbol": "DXY",
            "source_url": "https://fred.stlouisfed.org/series/DTWEXBGS",
            "raw_path": f"raw/macro/{snapshot_id}/DXY.json",
        },
        {
            "source": "jin10_quote",
            "symbol": "XAUUSD",
            "source_url": "https://mcp.jin10.com/mcp",
            "raw_path": f"raw/market/{snapshot_id}/XAUUSD.json",
        },
        {
            "source": "cme_daily_bulletin",
            "report_date": snapshot_time.date().isoformat(),
            "raw_path": f"raw/cme/{snapshot_id}/bulletin.pdf",
            "sha256": "a" * 64,
        },
        {
            "source": "jin10_mcp",
            "trade_date": snapshot_time.date().isoformat(),
            "raw_path": f"raw/news/{snapshot_id}/events.json",
        },
    ]
    return {
        "version": "1.0",
        "snapshot_id": snapshot_id,
        "asset": "XAUUSD",
        "trade_date": snapshot_time.date().isoformat(),
        "snapshot_time": snapshot_time.isoformat(),
        "run_id": run_id,
        "input_snapshot_ids": {
            "macro": f"macro:{run_id}",
            "options": f"options:{run_id}",
            "options_detail": {"raw_file_sha256": f"sha256:{run_id}"},
        },
        "source_refs": refs,
        "macro": {
            "status": "available",
            "data": {
                "as_of": snapshot_time.date().isoformat(),
                "indicators": {
                    "DXY": {
                        "value": dxy,
                        "date": snapshot_time.date().isoformat(),
                        "unit": "index",
                    }
                },
            },
        },
        "technical": {
            "status": "available",
            "data": {"price": price, "source_refs": [refs[1]]},
        },
        "options": {
            "status": "available",
            "data": {
                "trade_date": snapshot_time.date().isoformat(),
                "data_source": {
                    "status": "FINAL",
                    "input_snapshot_ids": {"raw_file_sha256": "a" * 64},
                },
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": gamma_zero}}
                },
            },
        },
        "news": {
            "status": "available",
            "data": {
                "as_of": snapshot_time.isoformat(),
                "recent_events": events,
                "source_refs": [refs[3]],
            },
        },
    }


def _snapshot(payload: dict, *, created_at: datetime) -> AnalysisSnapshot:
    return AnalysisSnapshot(
        id=(
            "00000000-0000-0000-0000-000000000027"
            if payload["run_id"] == "run-previous"
            else "00000000-0000-0000-0000-000000000028"
        ),
        snapshot_id=payload["snapshot_id"],
        asset=payload["asset"],
        trade_date=datetime.fromisoformat(payload["trade_date"]).date(),
        run_id=payload["run_id"],
        snapshot_time=datetime.fromisoformat(payload["snapshot_time"]),
        status="success",
        input_snapshot_ids=dict(payload["input_snapshot_ids"]),
        source_refs=list(payload["source_refs"]),
        macro=payload["macro"],
        options=payload["options"],
        positioning=None,
        news=payload["news"],
        technical=payload["technical"],
        payload=payload,
        payload_sha256="b" * 64,
        artifact_path=f"features/{payload['snapshot_id']}.json",
        created_at=created_at,
        updated_at=created_at,
    )


def _canonical_state() -> dict:
    return {
        "id": "00000000-0000-0000-0000-000000000080",
        "payload": {
            "schema_version": "1.1",
            "state_scope": "daily_close",
            "state_machine_version": "analysis_state.v1.1",
            "session": "daily_close",
            "trade_date": "2026-07-27",
            "asset": "XAUUSD",
            "as_of": "2026-07-27T09:00:00+00:00",
            "market_stage": "direction_decision",
            "core_thesis": "Gold is testing resistance.",
            "net_bias": "mixed_bullish",
            "dominant_drivers": [],
            "key_levels": [
                {
                    "value": 4000.0,
                    "role": "resistance",
                    "source": "jin10_quote",
                    "meaning": "daily breakout threshold",
                }
            ],
            "scenario_states": [],
            "unresolved_items": [],
            "invalidation_conditions": [],
            "evidence_cursors": {},
            "input_snapshot_ids": {
                "analysis_snapshot": "XAUUSD:2026-07-27:run-previous",
                "macro": "macro:run-previous",
                "options": "options:run-previous",
            },
            "source_refs": [],
        },
    }


def _snapshots() -> tuple[AnalysisSnapshot, AnalysisSnapshot]:
    previous = _payload(
        snapshot_id="XAUUSD:2026-07-27:run-previous",
        run_id="run-previous",
        snapshot_time=PREVIOUS_AT,
        dxy=100.0,
        price=3990.0,
        gamma_zero=3980.0,
        include_new_event=False,
    )
    current = _payload(
        snapshot_id="XAUUSD:2026-07-28:run-current",
        run_id="run-current",
        snapshot_time=CURRENT_AT,
        dxy=101.0,
        price=4010.0,
        gamma_zero=4020.0,
        include_new_event=True,
    )
    return _snapshot(previous, created_at=PREVIOUS_AT), _snapshot(current, created_at=CURRENT_AT)


def test_real_analysis_snapshots_project_all_supported_evidence_types() -> None:
    previous, current = _snapshots()

    evidence = project_snapshot_evidence(
        previous_snapshot=previous,
        current_snapshot=current,
        canonical_state=_canonical_state(),
    )

    adapted = [adapt_context_evidence(item) for item in evidence]
    assert {item.evidence_type for item in adapted} == {
        "macro_metric",
        "key_level_event",
        "options_regime",
        "material_event",
    }
    by_type = {item.evidence_type: item for item in adapted}
    assert by_type["macro_metric"].metric == "dxy"
    assert by_type["macro_metric"].previous_value == 100.0
    assert by_type["macro_metric"].current_value == 101.0
    assert by_type["key_level_event"].event == "confirmed_break"
    assert by_type["options_regime"].confirmation_status.value == "confirmed"
    assert by_type["material_event"].claim == "Federal Reserve policy decision"
    assert all(item.source_ref["previous_snapshot_id"] == previous.snapshot_id for item in evidence)
    assert all(item.source_ref["current_snapshot_id"] == current.snapshot_id for item in evidence)
    assert all(item.ingested_at == CURRENT_AT for item in evidence)
    expected_passport = {
        "analysis_snapshot": current.snapshot_id,
        "analysis_snapshot_db_id": current.id,
        "macro": "macro:run-current",
        "options": "options:run-current",
        "options_detail.raw_file_sha256": "sha256:run-current",
    }
    assert all(
        item.payload["metadata"][SNAPSHOT_PASSPORT_METADATA_KEY] == expected_passport
        for item in evidence
    )


def test_state_shadow_input_is_deterministic_and_runtime_complete(tmp_path) -> None:
    previous, current = _snapshots()
    before_previous = copy.deepcopy(previous.payload)
    before_current = copy.deepcopy(current.payload)

    first = build_state_shadow_input(
        previous_snapshot=previous,
        current_snapshot=current,
        canonical_state=_canonical_state(),
    )
    second = build_state_shadow_input(
        previous_snapshot=previous,
        current_snapshot=current,
        canonical_state=_canonical_state(),
    )

    assert first == second
    assert previous.payload == before_previous
    assert current.payload == before_current
    assert first["canonical_state_id"] == _canonical_state()["id"]
    assert first["state_scope"] == "daily_close"
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id=current.run_id,
        created_at=CURRENT_AT,
        shadow_input=first,
    )
    assert runtime.bundle.canonical_state_id == first["canonical_state_id"]
    assert len(runtime.bundle.evidence_delta_decision["evaluated_items"]) == 4


def test_missing_or_untraceable_snapshot_fields_do_not_create_evidence() -> None:
    previous, current = _snapshots()
    previous_payload = copy.deepcopy(previous.payload)
    current_payload = copy.deepcopy(current.payload)
    current_payload["source_refs"] = []
    current_payload["macro"]["data"].pop("indicators")
    current_payload["technical"] = {"status": "unavailable", "reason": "missing"}
    current_payload["options"] = {"status": "unavailable", "reason": "missing"}
    current_payload["news"] = {"status": "unavailable", "reason": "missing"}

    shadow_input = build_state_shadow_input(
        previous_snapshot=previous_payload,
        current_snapshot=current_payload,
        canonical_state=_canonical_state(),
    )

    assert shadow_input["evidence"] == []


def test_cnbc_market_quote_is_projected_as_primary_evidence() -> None:
    previous, current = _snapshots()
    previous.payload["source_refs"][0]["source"] = "cnbc"
    current.payload["source_refs"][0]["source"] = "cnbc"
    previous.source_refs[0]["source"] = "cnbc"
    current.source_refs[0]["source"] = "cnbc"

    evidence = project_snapshot_evidence(
        previous_snapshot=previous,
        current_snapshot=current,
        canonical_state=_canonical_state(),
    )

    dxy = next(item for item in evidence if item.payload.get("metric") == "dxy")
    assert dxy.payload["source_quality"] == "primary"


def test_projection_rejects_cross_asset_or_non_consecutive_identity() -> None:
    previous, current = _snapshots()
    current.payload["asset"] = "GC"
    current.asset = "GC"
    with pytest.raises(ValueError, match="assets must match"):
        build_state_shadow_input(
            previous_snapshot=previous,
            current_snapshot=current,
            canonical_state=_canonical_state(),
        )
