from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import apps.governance as governance
import pytest
from apps.analysis.agents.prompt_evolution import build_prompt_evaluation_cases, run_prompt_ab_validation


def test_persist_prompt_evaluation_cases_writes_governance_artifact_only(tmp_path) -> None:
    assert hasattr(governance, "persist_prompt_evaluation_cases")
    storage_root = tmp_path / "storage"
    cases = build_prompt_evaluation_cases(
        agent_name="gold_macro_overview_agent",
        failures=[
            {
                "code": "mixed_without_driver_decomposition",
                "description": "Mixed output did not decompose bullish and bearish drivers.",
                "source_refs": [{"artifact_type": "system_evolution", "file_path": "findings.json"}],
            }
        ],
        created_from="system_evolution",
    )

    result = governance.persist_prompt_evaluation_cases(
        cases=cases,
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert result["artifacts"] == {
        "prompt_evaluation_cases": "governance/prompt_evolution/2026-07-08/prompt_evaluation_cases.json"
    }
    payload = json.loads((storage_root / result["artifacts"]["prompt_evaluation_cases"]).read_text(encoding="utf-8"))
    assert payload["trade_date"] == "2026-07-08"
    assert payload["count"] == 1
    assert payload["cases"][0]["case_type"] == "mixed_decomposition"
    assert payload["cases"][0]["created_from"] == "system_evolution"

    assert not (storage_root / "raw").exists()
    assert not (storage_root / "parsed").exists()
    assert not (storage_root / "features").exists()


def test_persist_prompt_ab_validation_result_writes_governance_artifact_only(tmp_path) -> None:
    assert hasattr(governance, "persist_prompt_ab_validation_result")
    storage_root = tmp_path / "storage"
    cases = build_prompt_evaluation_cases(
        agent_name="gold_macro_overview_agent",
        failures=[
            {
                "code": "mixed_without_driver_decomposition",
                "description": "Mixed output did not decompose bullish and bearish drivers.",
                "source_refs": [{"artifact_type": "system_evolution", "file_path": "findings.json"}],
            }
        ],
        created_from="system_evolution",
    )
    validation = run_prompt_ab_validation(
        agent_name="gold_macro_overview_agent",
        active_prompt_version={"version": "v1", "prompt_sha256": "active"},
        candidate_prompt_version={"version": "v2", "prompt_sha256": "candidate"},
        cases=cases,
        active_results={cases[0].case_id: {"failed_assertions": ["mixed_must_be_decomposed"]}},
        candidate_results={cases[0].case_id: {"failed_assertions": []}},
    )

    result = governance.persist_prompt_ab_validation_result(
        validation=validation,
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 13, 0, tzinfo=timezone.utc),
    )

    assert result["artifacts"] == {
        "prompt_ab_validation_result": "governance/prompt_evolution/2026-07-08/prompt_ab_validation_result.json"
    }
    payload = json.loads((storage_root / result["artifacts"]["prompt_ab_validation_result"]).read_text(encoding="utf-8"))
    assert payload["trade_date"] == "2026-07-08"
    assert payload["validation"]["validation_status"] == "pass"
    assert payload["validation"]["proposal_only"] is True
    assert payload["validation"]["activated_prompt"] is False
    assert payload["validation"]["case_results"][0]["status"] == "improved"

    assert not (storage_root / "raw").exists()
    assert not (storage_root / "parsed").exists()
    assert not (storage_root / "features").exists()


def test_persist_prompt_release_record_appends_release_and_rollback_audit(tmp_path) -> None:
    assert hasattr(governance, "persist_prompt_release_record")
    storage_root = tmp_path / "storage"

    release = governance.persist_prompt_release_record(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 14, 0, tzinfo=timezone.utc),
        agent_name="gold_macro_overview_agent",
        action="release_approved",
        active_prompt_version_id="pv-active",
        candidate_prompt_version_id="pv-candidate",
        validation_artifact="governance/prompt_evolution/2026-07-08/prompt_ab_validation_result.json",
        review_approved_by="review_center",
        test_result="prompt ab validation pass",
    )
    rollback = governance.persist_prompt_release_record(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 15, 0, tzinfo=timezone.utc),
        agent_name="gold_macro_overview_agent",
        action="rolled_back",
        active_prompt_version_id="pv-candidate",
        candidate_prompt_version_id="pv-active",
        rollback_reason="candidate caused a regression after release",
        test_result="rollback smoke pass",
    )

    assert release["artifacts"] == {
        "prompt_release_records": "governance/prompt_evolution/2026-07-08/prompt_release_records.json"
    }
    assert rollback["record_count"] == 2
    payload = json.loads((storage_root / release["artifacts"]["prompt_release_records"]).read_text(encoding="utf-8"))
    assert payload["trade_date"] == "2026-07-08"
    assert [item["action"] for item in payload["records"]] == ["release_approved", "rolled_back"]
    assert payload["records"][0]["review_approved_by"] == "review_center"
    assert payload["records"][0]["activated_prompt"] is False
    assert payload["records"][1]["rollback_reason"] == "candidate caused a regression after release"
    assert payload["records"][1]["rolled_back_from"] == "pv-candidate"
    assert payload["records"][1]["rolled_back_to"] == "pv-active"
    assert payload["records"][1]["affected_agents"] == ["gold_macro_overview_agent"]
    assert payload["records"][1]["test_result"] == "rollback smoke pass"

    assert not (storage_root / "raw").exists()
    assert not (storage_root / "parsed").exists()
    assert not (storage_root / "features").exists()


def test_persist_prompt_release_record_concurrent_appends_do_not_lose_updates(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    workers = 8

    def record(index: int) -> None:
        governance.persist_prompt_release_record(
            storage_root=storage_root,
            trade_date="2026-07-08",
            observed_at=datetime(2026, 7, 8, 14, index, tzinfo=timezone.utc),
            agent_name=f"agent-{index}",
            action="rolled_back",
            rollback_reason=f"rollback-{index}",
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(record, range(workers)))

    path = storage_root / "governance" / "prompt_evolution" / "2026-07-08" / "prompt_release_records.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["count"] == workers
    assert {item["agent_name"] for item in payload["records"]} == {f"agent-{index}" for index in range(workers)}


def test_prompt_evolution_artifacts_reject_unsafe_trade_date(tmp_path) -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        governance.persist_prompt_release_record(
            storage_root=tmp_path / "storage",
            trade_date="../../../raw",
            agent_name="gold_macro_overview_agent",
            action="rolled_back",
            rollback_reason="test path confinement",
        )

    assert not (tmp_path / "storage" / "raw").exists()
