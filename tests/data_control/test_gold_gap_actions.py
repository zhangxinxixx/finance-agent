from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from apps.data_control.gold_gap_actions import build_gold_gap_actions
from apps.data_control.gold_processing_context import GoldProcessingContext
from apps.data_control.task_dispatcher import build_dispatch_plan


CUTOFF = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)


def _context(
    *,
    missing_required: tuple[str, ...] = (),
    missing_confirmatory: tuple[str, ...] = (),
    reason_codes: tuple[str, ...] = (),
    options_readiness: str = "ready",
    authority_snapshot_id: str = "XAUUSD:2026-08-11:run",
    feature_snapshot_id: str = "feature_snapshot.v2:feature",
    feature_payload_hash: str = "feature-hash",
    artifact_path: Path = Path("storage/features/snapshots/XAUUSD/2026-08-11/run/premarket_snapshot.json"),
    artifact_sha256: str = "artifact-hash",
    cutoff: datetime = CUTOFF,
    found: bool = True,
) -> GoldProcessingContext:
    return GoldProcessingContext(
        authority_status="found" if found else "unavailable",
        authority_reason_code="authoritative_premarket_snapshot_found" if found else "authority_database_unavailable",
        authority_snapshot_id=authority_snapshot_id if found else None,
        authority_run_id="run" if found else None,
        artifact_path=artifact_path if found else None,
        artifact_sha256=artifact_sha256 if found else None,
        cutoff=cutoff if found else None,
        feature_snapshot_id=feature_snapshot_id if found else None,
        feature_payload_hash=feature_payload_hash if found else None,
        readiness={
            "analysis_readiness": "blocked" if missing_required else "ready",
            "strategy_readiness": "blocked" if missing_required else "ready",
            "options_readiness": options_readiness,
            "event_attribution_readiness": "ready",
            "missing_required_inputs": list(missing_required),
            "missing_confirmatory_inputs": list(missing_confirmatory),
            "prohibited_outputs": [],
            "reason_codes": list(reason_codes),
        },
        gold_source_ref=(
            {
                "source": "analysis_snapshot",
                "source_ref": authority_snapshot_id,
                "data_date": "2026-08-11",
                "retrieved_at": cutoff.isoformat(),
                "artifact_path": "storage/features/snapshots/XAUUSD/2026-08-11/run/premarket_snapshot.json",
                "sha256": artifact_sha256,
            }
            if found
            else {}
        ),
    )


def test_macro_gaps_merge_and_keep_gold_lineage() -> None:
    context = _context(
        missing_required=("US10Y", "T10YIE", "BROAD_DOLLAR"),
        reason_codes=(
            "REQUIRED_INPUT_UNUSABLE:US10Y",
            "REQUIRED_INPUT_DEGRADED:T10YIE",
            "REQUIRED_INPUT_UNUSABLE:BROAD_DOLLAR",
        ),
    )

    actions = build_gold_gap_actions(context)
    action = actions[0]

    assert len(actions) == 1
    assert action["gap_group"] == "macro"
    assert action["producer"] == "macro_collect"
    assert action["handler"] == "apps.worker.pipelines.macro.run_macro_step"
    assert action["steps"] == ["macro_collect", "macro_feature"]
    assert "report_render" not in action["steps"]
    assert action["pipeline_reference"][-1] == "report_render"
    assert action["status"] == "manual_required"
    assert action["dispatchable"] is False
    assert action["auto_execute"] is False
    assert action["lineage"]["authority"]["snapshot_id"] == context.authority_snapshot_id
    assert action["lineage"]["feature"]["snapshot_id"] == context.feature_snapshot_id
    assert action["lineage"]["artifact"]["sha256"] == context.artifact_sha256
    assert action["lineage"]["cutoff"] == CUTOFF.isoformat()
    assert "authority_snapshot_id" not in action
    assert "feature_snapshot_id" not in action
    assert "artifact_sha256" not in action
    assert action["source_reason_codes"] == list(context.reason_codes)
    assert build_gold_gap_actions(context) == actions


def test_real10y_gap_is_a_derivation_diagnostic() -> None:
    actions = build_gold_gap_actions(
        _context(
            missing_required=("REAL10Y_ESTIMATED",),
            reason_codes=(
                "REQUIRED_INPUT_UNUSABLE:REAL10Y_ESTIMATED",
                "REAL10Y_ESTIMATED_CORE_INPUT_UNUSABLE",
            ),
        )
    )

    assert len(actions) == 1
    assert actions[0]["gap_group"] == "unsupported"
    assert actions[0]["producer"] is None
    assert actions[0]["steps"] == []
    assert actions[0]["status"] == "unsupported"
    assert actions[0]["action_reason_code"] == "real10y_derivation_or_alignment_required"
    assert "derived" in actions[0]["limitations"][0]


def test_cme_suggestion_requires_options_reason_and_stays_manual() -> None:
    context = _context(
        options_readiness="blocked",
        reason_codes=("OPTIONS_INPUT_UNUSABLE",),
    )
    actions = build_gold_gap_actions(context)

    assert len(actions) == 1
    action = actions[0]
    assert action["gap_group"] == "cme"
    assert action["producer"] == "cme_download"
    assert action["steps"] == ["cme_download", "cme_parse", "cme_ingest", "option_wall"]
    assert action["status"] == "manual_required"
    assert action["dispatchable"] is False
    assert action["window"]["precise"] is False

    dispatch = build_dispatch_plan(
        collection_plan={
            "trade_date": "2026-08-11",
            "hour": "08",
            "observed_at": CUTOFF.isoformat(),
            "actions": [],
            "status": "normal",
        },
        processing_plan={
            "status": "ready",
            "ready_steps": [],
            "blocked_steps": [],
            "gold_processing_actions": actions,
        },
    )
    request = dispatch["requests"][0]
    assert request["source_key"] == "gold_processing"
    assert request["task_key"] == "cme_download"
    assert request["status"] == "manual_required"
    assert request["dispatch_mode"] == "manual_review"
    assert request["auto_execute"] is False
    assert dispatch["summary"]["request_count"] == 1


def test_xau_suggestion_describes_supported_scheduler_intervals() -> None:
    action = build_gold_gap_actions(
        _context(reason_codes=("REQUIRED_INPUT_DEGRADED:XAUUSD",))
    )[0]

    assert action["gap_group"] == "xauusd"
    assert action["producer"] == "twelvedata_xauusd_dispatch"
    assert action["steps"] == ["twelvedata_xauusd_dispatch"]
    assert action["window"]["supported_intervals"] == ["5min", "15min", "1h", "4h"]
    assert action["provider_identity"] == "twelvedata_xauusd"
    assert "due_intervals" not in action["window"]
    assert "fallback_identity" not in action
    assert action["status"] == "manual_required"


def test_unknown_gaps_are_one_unsupported_diagnostic() -> None:
    actions = build_gold_gap_actions(
        _context(
            missing_confirmatory=("ETF", "COT"),
            reason_codes=(
                "CONFIRMATORY_INPUT_UNUSABLE:ETF",
                "CONFIRMATORY_INPUT_UNUSABLE:COT",
            ),
        )
    )

    assert len(actions) == 1
    assert actions[0]["gap_group"] == "unsupported"
    assert actions[0]["producer"] is None
    assert actions[0]["task_keys"] == []
    assert actions[0]["status"] == "unsupported"
    assert actions[0]["dispatchable"] is False


def test_no_gap_does_not_follow_prohibited_outputs() -> None:
    context = _context()
    context = GoldProcessingContext(
        **{
            **context.__dict__,
            "readiness": {
                **context.readiness,
                "prohibited_outputs": ["TRIGGERED_STRATEGY"],
                "reason_codes": ["NO_MATERIAL_OFFICIAL_EVENT"],
            },
        }
    )

    assert build_gold_gap_actions(context) == []


def test_missing_authority_never_guesses_a_producer() -> None:
    actions = build_gold_gap_actions(_context(found=False))

    assert len(actions) == 1
    assert actions[0]["gap_group"] == "authority"
    assert actions[0]["producer"] is None
    assert actions[0]["handler"] is None
    assert actions[0]["status"] == "unsupported"
    assert actions[0]["dispatchable"] is False


def test_gold_action_dispatcher_forces_forged_ready_action_to_manual_review() -> None:
    dispatch = build_dispatch_plan(
        collection_plan={
            "trade_date": "2026-08-11",
            "hour": "08",
            "observed_at": CUTOFF.isoformat(),
            "actions": [],
            "status": "normal",
        },
        processing_plan={
            "status": "ready",
            "ready_steps": [],
            "blocked_steps": [],
            "gold_processing_actions": [
                {
                    "request_id": "gold-gap:forged",
                    "status": "ready",
                    "dispatchable": True,
                    "auto_execute": True,
                    "task_keys": ["macro_collect", "macro_feature"],
                    "gap_labels": ["US10Y"],
                    "lineage": {"source_refs": [{"source": "gold", "source_ref": "snapshot"}]},
                }
            ],
        },
    )

    request = dispatch["requests"][0]
    assert request["owner"] == "manual_review"
    assert request["dispatch_mode"] == "manual_review"
    assert request["status"] == "manual_required"
    assert request["dispatchable"] is False
    assert request["auto_execute"] is False
    assert request["gold_gap_action"]["status"] == "manual_required"
    assert request["gold_gap_action"]["dispatchable"] is False
    assert request["gold_gap_action"]["auto_execute"] is False


def test_gold_labels_use_exact_whitelist_and_keep_dfii10_separate() -> None:
    xau_actions = build_gold_gap_actions(
        _context(missing_required=("MY_XAUUSD",), reason_codes=("REQUIRED_INPUT_UNUSABLE:MY_XAUUSD",))
    )
    dfii_actions = build_gold_gap_actions(
        _context(missing_required=("DFII10",), reason_codes=("REQUIRED_INPUT_UNUSABLE:DFII10",))
    )
    estimated_actions = build_gold_gap_actions(
        _context(
            missing_required=("REAL10Y_ESTIMATED",),
            reason_codes=("REQUIRED_INPUT_UNUSABLE:REAL10Y_ESTIMATED",),
        )
    )
    jin10_actions = build_gold_gap_actions(
        _context(missing_required=("JIN10_QUOTES",), reason_codes=("REQUIRED_INPUT_UNUSABLE:JIN10_QUOTES",))
    )

    assert xau_actions[0]["gap_group"] == "unsupported"
    assert xau_actions[0]["producer"] is None
    assert dfii_actions[0]["gap_group"] == "unsupported"
    assert dfii_actions[0]["action_reason_code"] == "gold_gap_unsupported"
    assert estimated_actions[0]["action_reason_code"] == "real10y_derivation_or_alignment_required"
    assert jin10_actions[0]["gap_group"] == "unsupported"


def test_gold_request_id_ignores_artifact_identity_but_tracks_feature_identity() -> None:
    base = _context(
        missing_required=("US10Y",),
        reason_codes=("REQUIRED_INPUT_UNUSABLE:US10Y",),
    )
    artifact_changed = _context(
        missing_required=("US10Y",),
        reason_codes=("REQUIRED_INPUT_UNUSABLE:US10Y",),
        artifact_path=Path("storage/other/path.json"),
        artifact_sha256="different-bytes",
    )
    feature_changed = _context(
        missing_required=("US10Y",),
        reason_codes=("REQUIRED_INPUT_UNUSABLE:US10Y",),
        feature_snapshot_id="feature_snapshot.v2:other",
    )
    feature_hash_changed = _context(
        missing_required=("US10Y",),
        reason_codes=("REQUIRED_INPUT_UNUSABLE:US10Y",),
        feature_payload_hash="different-feature-bytes",
    )

    base_id = build_gold_gap_actions(base)[0]["request_id"]
    assert build_gold_gap_actions(artifact_changed)[0]["request_id"] == base_id
    assert build_gold_gap_actions(feature_changed)[0]["request_id"] != base_id
    assert build_gold_gap_actions(feature_hash_changed)[0]["request_id"] != base_id

    dispatch_kwargs = {
        "collection_plan": {
            "trade_date": "2026-08-11",
            "hour": "08",
            "observed_at": CUTOFF.isoformat(),
            "actions": [],
            "status": "normal",
        },
        "processing_plan": {
            "status": "ready",
            "ready_steps": [],
            "blocked_steps": [],
            "gold_processing_actions": build_gold_gap_actions(base),
        },
    }
    first = build_dispatch_plan(**dispatch_kwargs)
    dispatch_kwargs["collection_plan"] = {**dispatch_kwargs["collection_plan"], "hour": "09"}
    second = build_dispatch_plan(**dispatch_kwargs)
    assert first["requests"][0]["request_id"] == second["requests"][0]["request_id"]
