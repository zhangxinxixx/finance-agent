from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.services import prompt_evolution_service


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_validation(
    storage_root: Path,
    *,
    candidate_prompt_version_id: str = "pv-candidate",
    agent_name: str = "gold_macro_overview_agent",
    validation_status: str = "pass",
    regression_count: int = 0,
) -> str:
    artifact = "governance/prompt_evolution/2026-07-08/prompt_ab_validation_result.json"
    _write_json(
        storage_root / artifact,
        {
            "trade_date": "2026-07-08",
            "validation": {
                "agent_name": agent_name,
                "validation_status": validation_status,
                "regression_count": regression_count,
                "candidate_prompt_result": {"id": candidate_prompt_version_id, "version": "v2"},
            },
        },
    )
    return artifact


def test_prompt_evolution_latest_reads_cases_validation_and_release_records(tmp_path) -> None:
    assert hasattr(prompt_evolution_service, "get_prompt_evolution_latest")
    get_prompt_evolution_latest = prompt_evolution_service.get_prompt_evolution_latest
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "prompt_evolution" / "2026-07-08"
    _write_json(
        base / "prompt_evaluation_cases.json",
        {
            "trade_date": "2026-07-08",
            "count": 1,
            "cases": [{"case_id": "case-1", "case_type": "mixed_decomposition"}],
        },
    )
    _write_json(
        base / "prompt_ab_validation_result.json",
        {
            "trade_date": "2026-07-08",
            "validation": {
                "validation_status": "pass",
                "improvement_count": 1,
                "regression_count": 0,
                "proposal_only": True,
                "activated_prompt": False,
            },
        },
    )
    _write_json(
        base / "prompt_release_records.json",
        {
            "trade_date": "2026-07-08",
            "count": 2,
            "records": [
                {"action": "release_approved", "agent_name": "gold_macro_overview_agent"},
                {"action": "rolled_back", "rollback_reason": "regression"},
            ],
        },
    )

    payload = get_prompt_evolution_latest(storage_root=storage_root, date="2026-07-08")

    assert payload["trade_date"] == "2026-07-08"
    assert payload["cases"]["count"] == 1
    assert payload["cases"]["items"][0]["case_id"] == "case-1"
    assert payload["validation"]["validation_status"] == "pass"
    assert payload["validation"]["activated_prompt"] is False
    assert payload["release_records"]["count"] == 2
    assert payload["release_records"]["items"][1]["rollback_reason"] == "regression"
    assert payload["release_readiness"] == {
        "status": "rolled_back",
        "can_request_release_approval": False,
        "can_activate_after_review": False,
        "can_record_rollback": False,
        "blocking_reasons": ["latest_release_rolled_back"],
        "latest_release_action": "rolled_back",
        "latest_rollback_reason": "regression",
    }
    assert payload["artifacts"] == {
        "prompt_evaluation_cases": "governance/prompt_evolution/2026-07-08/prompt_evaluation_cases.json",
        "prompt_ab_validation_result": "governance/prompt_evolution/2026-07-08/prompt_ab_validation_result.json",
        "prompt_release_records": "governance/prompt_evolution/2026-07-08/prompt_release_records.json",
    }


def test_prompt_evolution_latest_missing_storage_returns_empty_shape(tmp_path) -> None:
    assert hasattr(prompt_evolution_service, "get_prompt_evolution_latest")
    get_prompt_evolution_latest = prompt_evolution_service.get_prompt_evolution_latest
    payload = get_prompt_evolution_latest(storage_root=tmp_path / "storage", date="2026-07-08")

    assert payload["trade_date"] == "2026-07-08"
    assert payload["cases"] == {"count": 0, "items": []}
    assert payload["validation"] == {}
    assert payload["release_records"] == {"count": 0, "items": []}
    assert payload["release_readiness"] == {
        "status": "blocked",
        "can_request_release_approval": False,
        "can_activate_after_review": False,
        "can_record_rollback": False,
        "blocking_reasons": ["missing_ab_validation"],
        "latest_release_action": None,
        "latest_rollback_reason": None,
    }


def test_prompt_evolution_release_readiness_allows_approval_request_after_passing_validation(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "prompt_evolution" / "2026-07-08"
    _write_json(
        base / "prompt_ab_validation_result.json",
        {
            "trade_date": "2026-07-08",
            "validation": {
                "validation_status": "pass",
                "improvement_count": 2,
                "regression_count": 0,
                "proposal_only": True,
                "activated_prompt": False,
            },
        },
    )

    payload = prompt_evolution_service.get_prompt_evolution_latest(storage_root=storage_root, date="2026-07-08")

    assert payload["release_readiness"] == {
        "status": "awaiting_review_approval",
        "can_request_release_approval": True,
        "can_activate_after_review": False,
        "can_record_rollback": False,
        "blocking_reasons": [],
        "latest_release_action": None,
        "latest_rollback_reason": None,
    }


def test_prompt_evolution_release_readiness_requires_explicit_zero_regressions(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "prompt_evolution" / "2026-07-08"
    _write_json(
        base / "prompt_ab_validation_result.json",
        {
            "trade_date": "2026-07-08",
            "validation": {
                "validation_status": "pass",
                "proposal_only": True,
                "activated_prompt": False,
            },
        },
    )

    payload = prompt_evolution_service.get_prompt_evolution_latest(storage_root=storage_root, date="2026-07-08")

    assert payload["release_readiness"]["status"] == "blocked"
    assert payload["release_readiness"]["blocking_reasons"] == ["validation_regression_count_missing"]


def test_record_prompt_release_action_persists_review_approval_without_activation(tmp_path) -> None:
    assert hasattr(prompt_evolution_service, "record_prompt_release_action")
    storage_root = tmp_path / "storage"
    validation_artifact = _write_validation(storage_root)

    result = prompt_evolution_service.record_prompt_release_action(
        {
            "agent_name": "gold_macro_overview_agent",
            "action": "release_approved",
            "active_prompt_version_id": "pv-active",
            "candidate_prompt_version_id": "pv-candidate",
            "validation_artifact": validation_artifact,
            "review_approved_by": "review-center",
            "test_result": "prompt ab validation pass",
            "trade_date": "2026-07-08",
        },
        storage_root=storage_root,
    )

    assert result["status"] == "recorded"
    assert result["record"]["action"] == "release_approved"
    assert result["record"]["activated_prompt"] is False
    assert result["activated_prompt"] is False
    assert result["writes"] == ["governance/prompt_evolution/2026-07-08/prompt_release_records.json"]
    payload = prompt_evolution_service.get_prompt_evolution_latest(storage_root=storage_root, date="2026-07-08")
    assert payload["release_records"]["count"] == 1
    assert payload["release_records"]["items"][0]["review_approved_by"] == "review-center"


def test_has_prompt_release_approval_matches_candidate_and_agent(tmp_path) -> None:
    assert hasattr(prompt_evolution_service, "has_prompt_release_approval")
    storage_root = tmp_path / "storage"
    artifact = "governance/prompt_evolution/2026-07-08/prompt_release_records.json"
    validation_artifact = _write_validation(storage_root)

    prompt_evolution_service.record_prompt_release_action(
        {
            "agent_name": "gold_macro_overview_agent",
            "action": "release_approved",
            "candidate_prompt_version_id": "pv-candidate",
            "validation_artifact": validation_artifact,
            "review_approved_by": "review-center",
            "trade_date": "2026-07-08",
        },
        storage_root=storage_root,
    )

    assert prompt_evolution_service.has_prompt_release_approval(
        agent_name="gold_macro_overview_agent",
        candidate_prompt_version_id="pv-candidate",
        storage_root=storage_root,
        release_approval_artifact=artifact,
    )
    assert not prompt_evolution_service.has_prompt_release_approval(
        agent_name="gold_macro_overview_agent",
        candidate_prompt_version_id="pv-other",
        storage_root=storage_root,
        release_approval_artifact=artifact,
    )
    assert not prompt_evolution_service.has_prompt_release_approval(
        agent_name="other_agent",
        candidate_prompt_version_id="pv-candidate",
        storage_root=storage_root,
        release_approval_artifact=artifact,
    )


def test_prompt_activation_readiness_rejects_rollback_after_approval(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    validation_artifact = _write_validation(storage_root)
    release_artifact = "governance/prompt_evolution/2026-07-08/prompt_release_records.json"
    prompt_evolution_service.record_prompt_release_action(
        {
            "agent_name": "gold_macro_overview_agent",
            "action": "release_approved",
            "candidate_prompt_version_id": "pv-candidate",
            "validation_artifact": validation_artifact,
            "review_approved_by": "review-center",
            "trade_date": "2026-07-08",
        },
        storage_root=storage_root,
    )
    prompt_evolution_service.record_prompt_release_action(
        {
            "agent_name": "gold_macro_overview_agent",
            "action": "rolled_back",
            "active_prompt_version_id": "pv-candidate",
            "candidate_prompt_version_id": "pv-active",
            "rollback_reason": "regression after release",
            "trade_date": "2026-07-08",
        },
        storage_root=storage_root,
    )

    decision = prompt_evolution_service.evaluate_prompt_activation_readiness(
        agent_name="gold_macro_overview_agent",
        candidate_prompt_version_id="pv-candidate",
        storage_root=storage_root,
        release_approval_artifact=release_artifact,
    )

    assert decision.ready is False
    assert decision.blocking_reasons == ("candidate_rolled_back",)
    assert not prompt_evolution_service.has_prompt_release_approval(
        agent_name="gold_macro_overview_agent",
        candidate_prompt_version_id="pv-candidate",
        storage_root=storage_root,
        release_approval_artifact=release_artifact,
    )


def test_prompt_activation_readiness_cannot_hide_newer_rollback_with_old_artifact(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    validation_artifact = _write_validation(storage_root)
    old_release_artifact = "governance/prompt_evolution/2026-07-08/prompt_release_records.json"
    prompt_evolution_service.record_prompt_release_action(
        {
            "agent_name": "gold_macro_overview_agent",
            "action": "release_approved",
            "candidate_prompt_version_id": "pv-candidate",
            "validation_artifact": validation_artifact,
            "review_approved_by": "review-center",
            "trade_date": "2026-07-08",
        },
        storage_root=storage_root,
    )
    prompt_evolution_service.record_prompt_release_action(
        {
            "agent_name": "gold_macro_overview_agent",
            "action": "rolled_back",
            "active_prompt_version_id": "pv-candidate",
            "candidate_prompt_version_id": "pv-active",
            "rollback_reason": "newer regression",
            "trade_date": "2026-07-09",
        },
        storage_root=storage_root,
    )

    decision = prompt_evolution_service.evaluate_prompt_activation_readiness(
        agent_name="gold_macro_overview_agent",
        candidate_prompt_version_id="pv-candidate",
        storage_root=storage_root,
        release_approval_artifact=old_release_artifact,
    )

    assert decision.ready is False
    assert decision.blocking_reasons == ("candidate_rolled_back",)


def test_prompt_activation_readiness_orders_governance_by_recorded_at(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    validation_artifact = _write_validation(storage_root)
    release_artifact = "governance/prompt_evolution/2026-07-09/prompt_release_records.json"
    _write_json(
        storage_root / release_artifact,
        {
            "records": [
                {
                    "agent_name": "gold_macro_overview_agent",
                    "action": "release_approved",
                    "candidate_prompt_version_id": "pv-candidate",
                    "validation_artifact": validation_artifact,
                    "recorded_at": "2026-07-08T09:00:00+00:00",
                }
            ]
        },
    )
    _write_json(
        storage_root / "governance/prompt_evolution/2026-07-08/prompt_release_records.json",
        {
            "records": [
                {
                    "agent_name": "gold_macro_overview_agent",
                    "action": "rolled_back",
                    "active_prompt_version_id": "pv-candidate",
                    "rolled_back_from": "pv-candidate",
                    "rollback_reason": "backfilled newer rollback",
                    "recorded_at": "2026-07-10T09:00:00+00:00",
                }
            ]
        },
    )

    decision = prompt_evolution_service.evaluate_prompt_activation_readiness(
        agent_name="gold_macro_overview_agent",
        candidate_prompt_version_id="pv-candidate",
        storage_root=storage_root,
        release_approval_artifact=release_artifact,
    )

    assert decision.ready is False
    assert decision.blocking_reasons == ("candidate_rolled_back",)


@pytest.mark.parametrize(
    ("validation_status", "regression_count", "candidate_id", "expected_reason"),
    [
        ("fail", 0, "pv-candidate", "validation_status:fail"),
        ("pass", 1, "pv-candidate", "validation_has_regressions"),
        ("pass", 0.5, "pv-candidate", "validation_has_regressions"),
        ("pass", 0, "pv-other", "validation_candidate_mismatch"),
    ],
)
def test_record_prompt_release_action_rejects_invalid_validation(
    tmp_path,
    validation_status,
    regression_count,
    candidate_id,
    expected_reason,
) -> None:
    storage_root = tmp_path / "storage"
    validation_artifact = _write_validation(
        storage_root,
        candidate_prompt_version_id=candidate_id,
        validation_status=validation_status,
        regression_count=regression_count,
    )

    with pytest.raises(ValueError, match=expected_reason):
        prompt_evolution_service.record_prompt_release_action(
            {
                "agent_name": "gold_macro_overview_agent",
                "action": "release_approved",
                "candidate_prompt_version_id": "pv-candidate",
                "validation_artifact": validation_artifact,
                "review_approved_by": "review-center",
                "trade_date": "2026-07-08",
            },
            storage_root=storage_root,
        )


def test_record_prompt_release_action_rejects_validation_outside_storage(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    outside = tmp_path / "prompt_ab_validation_result.json"
    _write_json(outside, {"validation": {"validation_status": "pass", "regression_count": 0}})

    with pytest.raises(ValueError, match="validation_artifact_not_allowed"):
        prompt_evolution_service.record_prompt_release_action(
            {
                "agent_name": "gold_macro_overview_agent",
                "action": "release_approved",
                "candidate_prompt_version_id": "pv-candidate",
                "validation_artifact": str(outside),
                "review_approved_by": "review-center",
                "trade_date": "2026-07-08",
            },
            storage_root=storage_root,
        )


def test_record_prompt_release_action_requires_review_approval_for_release(tmp_path) -> None:
    assert hasattr(prompt_evolution_service, "record_prompt_release_action")

    try:
        prompt_evolution_service.record_prompt_release_action(
            {
                "agent_name": "gold_macro_overview_agent",
                "action": "release_approved",
                "candidate_prompt_version_id": "pv-candidate",
                "trade_date": "2026-07-08",
            },
            storage_root=tmp_path / "storage",
        )
    except ValueError as exc:
        assert "review_approved_by" in str(exc)
    else:
        raise AssertionError("Expected review_approved_by validation error")


def test_record_prompt_release_action_requires_rollback_reason(tmp_path) -> None:
    assert hasattr(prompt_evolution_service, "record_prompt_release_action")

    try:
        prompt_evolution_service.record_prompt_release_action(
            {
                "agent_name": "gold_macro_overview_agent",
                "action": "rolled_back",
                "active_prompt_version_id": "pv-candidate",
                "candidate_prompt_version_id": "pv-active",
                "trade_date": "2026-07-08",
            },
            storage_root=tmp_path / "storage",
        )
    except ValueError as exc:
        assert "rollback_reason" in str(exc)
    else:
        raise AssertionError("Expected rollback_reason validation error")
