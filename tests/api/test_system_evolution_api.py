from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from apps.api.services import system_evolution_service
from apps.api.services.system_evolution_service import get_system_evolution_latest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_system_evolution_latest_reads_findings_and_proposals(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "system_evolution" / "2026-07-08"
    _write_json(
        base / "findings.json",
        {
            "trade_date": "2026-07-08",
            "count": 1,
            "findings": [
                {
                    "finding_id": "finding:mixed_without_driver_decomposition",
                    "code": "mixed_without_driver_decomposition",
                    "severity": "critical",
                    "category": "driver_decomposition",
                    "title": "Mixed without driver decomposition",
                    "description": "Missing driver split.",
                    "affected_entities": {},
                    "evidence": {},
                    "source_refs": [],
                    "created_at": "2026-07-08T12:00:00+00:00",
                }
            ],
        },
    )
    _write_json(
        base / "improvement_proposals.json",
        {
            "trade_date": "2026-07-08",
            "count": 1,
            "proposals": [
                {
                    "proposal_id": "proposal:mixed_without_driver_decomposition",
                    "proposal_type": "backend_rule_update",
                    "title": "Require mixed driver decomposition",
                    "rationale": "Mixed output has no driver split.",
                    "proposed_changes": ["Require bullish/bearish drivers."],
                    "expected_impact": "Less silent publication risk.",
                    "risks": ["More manual review."],
                    "rollback_plan": "Disable proposal.",
                    "test_plan": ["Run SystemEvolution tests."],
                    "status": "pending_review",
                    "finding_codes": ["mixed_without_driver_decomposition"],
                    "linked_issue": None,
                    "linked_pr": None,
                }
            ],
        },
    )
    _write_json(
        base / "system_evolution_review.json",
        {
            "trade_date": "2026-07-08",
            "review_status": "blocked",
            "blocked": True,
            "required_followups": ["mixed_without_driver_decomposition"],
        },
    )

    payload = get_system_evolution_latest(storage_root=storage_root, date="2026-07-08")

    assert payload["trade_date"] == "2026-07-08"
    assert payload["review"]["review_status"] == "blocked"
    assert payload["findings"]["count"] == 1
    assert payload["findings"]["items"][0]["code"] == "mixed_without_driver_decomposition"
    assert payload["proposals"]["count"] == 1
    assert payload["proposals"]["items"][0]["status"] == "pending_review"
    assert payload["artifacts"] == {
        "findings": "governance/system_evolution/2026-07-08/findings.json",
        "improvement_proposals": "governance/system_evolution/2026-07-08/improvement_proposals.json",
        "review": "governance/system_evolution/2026-07-08/system_evolution_review.json",
        "proposal_actions": None,
    }


def test_system_evolution_latest_missing_storage_returns_empty_shape(tmp_path) -> None:
    payload = get_system_evolution_latest(storage_root=tmp_path / "storage", date="2026-07-08")

    assert payload["trade_date"] == "2026-07-08"
    assert payload["findings"] == {"count": 0, "items": []}
    assert payload["proposals"] == {"count": 0, "items": []}
    assert payload["review"] == {}


def test_system_evolution_proposal_action_is_recorded_and_merged(tmp_path) -> None:
    assert hasattr(system_evolution_service, "create_system_evolution_proposal_action")
    create_system_evolution_proposal_action = system_evolution_service.create_system_evolution_proposal_action
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "system_evolution" / "2026-07-08"
    _write_json(
        base / "improvement_proposals.json",
        {
            "trade_date": "2026-07-08",
            "count": 1,
            "proposals": [
                {
                    "proposal_id": "proposal:mixed_without_driver_decomposition",
                    "proposal_type": "backend_rule_update",
                    "title": "Require mixed driver decomposition",
                    "rationale": "Mixed output has no driver split.",
                    "proposed_changes": ["Require bullish/bearish drivers."],
                    "expected_impact": "Less silent publication risk.",
                    "risks": ["More manual review."],
                    "rollback_plan": "Disable proposal.",
                    "test_plan": ["Run SystemEvolution tests."],
                    "status": "pending_review",
                    "finding_codes": ["mixed_without_driver_decomposition"],
                    "linked_issue": None,
                    "linked_pr": None,
                }
            ],
        },
    )

    approve = create_system_evolution_proposal_action(
        storage_root=storage_root,
        date="2026-07-08",
        proposal_id="proposal:mixed_without_driver_decomposition",
        action="approve",
        actor="codex",
        note="approved for implementation issue",
    )
    link_issue = create_system_evolution_proposal_action(
        storage_root=storage_root,
        date="2026-07-08",
        proposal_id="proposal:mixed_without_driver_decomposition",
        action="link_issue",
        actor="codex",
        issue_url="https://github.com/zhangxinxixx/finance-agent/issues/51",
    )

    assert approve["status"] == "recorded"
    assert link_issue["action"]["issue_url"] == "https://github.com/zhangxinxixx/finance-agent/issues/51"
    actions_path = base / "proposal_actions.json"
    assert actions_path.is_file()
    actions = json.loads(actions_path.read_text(encoding="utf-8"))
    assert [item["action"] for item in actions["actions"]] == ["approve", "link_issue"]

    payload = get_system_evolution_latest(storage_root=storage_root, date="2026-07-08")
    proposal = payload["proposals"]["items"][0]
    assert proposal["status"] == "approved"
    assert proposal["linked_issue"] == "https://github.com/zhangxinxixx/finance-agent/issues/51"
    assert proposal["review_action_status"] == "approved"
    assert proposal["review_actor"] == "codex"
    assert payload["artifacts"]["proposal_actions"] == "governance/system_evolution/2026-07-08/proposal_actions.json"
    assert payload["proposal_actions"]["count"] == 2


def test_system_evolution_proposal_action_tracks_implemented_and_rolled_back(tmp_path) -> None:
    create_system_evolution_proposal_action = system_evolution_service.create_system_evolution_proposal_action
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "system_evolution" / "2026-07-08"
    _write_json(
        base / "improvement_proposals.json",
        {
            "trade_date": "2026-07-08",
            "count": 1,
            "proposals": [
                {
                    "proposal_id": "proposal:rollback_case",
                    "status": "approved",
                    "linked_issue": "https://github.com/zhangxinxixx/finance-agent/issues/51",
                    "linked_pr": None,
                }
            ],
        },
    )

    implemented = create_system_evolution_proposal_action(
        storage_root=storage_root,
        date="2026-07-08",
        proposal_id="proposal:rollback_case",
        action="mark_implemented",
        actor="codex",
        test_result="pytest tests/api/test_system_evolution_api.py -q -> passed",
        note="implementation completed",
    )
    rolled_back = create_system_evolution_proposal_action(
        storage_root=storage_root,
        date="2026-07-08",
        proposal_id="proposal:rollback_case",
        action="mark_rolled_back",
        actor="codex",
        rollback_reason="regression found after release",
    )

    assert implemented["action"]["test_result"] == "pytest tests/api/test_system_evolution_api.py -q -> passed"
    assert rolled_back["action"]["rollback_reason"] == "regression found after release"
    payload = get_system_evolution_latest(storage_root=storage_root, date="2026-07-08")
    proposal = payload["proposals"]["items"][0]
    assert proposal["status"] == "rolled_back"
    assert proposal["test_result"] == "pytest tests/api/test_system_evolution_api.py -q -> passed"
    assert proposal["rollback_reason"] == "regression found after release"


def test_system_evolution_proposal_action_rejects_unsafe_inputs(tmp_path) -> None:
    create_system_evolution_proposal_action = system_evolution_service.create_system_evolution_proposal_action

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        create_system_evolution_proposal_action(
            storage_root=tmp_path / "storage",
            date="../2026-07-08",
            proposal_id="proposal:1",
            action="approve",
            actor="codex",
        )

    with pytest.raises(ValueError, match="unsupported"):
        create_system_evolution_proposal_action(
            storage_root=tmp_path / "storage",
            date="2026-07-08",
            proposal_id="proposal:1",
            action="delete",
            actor="codex",
        )

    with pytest.raises(ValueError, match="test_result or manual_confirmation"):
        create_system_evolution_proposal_action(
            storage_root=tmp_path / "storage",
            date="2026-07-08",
            proposal_id="proposal:1",
            action="mark_implemented",
            actor="codex",
        )


def test_system_evolution_proposal_action_requires_existing_proposal(tmp_path) -> None:
    with pytest.raises(ValueError, match="proposal not found"):
        system_evolution_service.create_system_evolution_proposal_action(
            storage_root=tmp_path / "storage",
            date="2026-07-08",
            proposal_id="proposal:not-exists",
            action="approve",
            actor="codex",
        )


def test_system_evolution_proposal_action_rejects_invalid_status_transition(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "system_evolution" / "2026-07-08"
    _write_json(
        base / "improvement_proposals.json",
        {
            "trade_date": "2026-07-08",
            "proposals": [{"proposal_id": "proposal:state-machine", "status": "pending_review"}],
        },
    )

    with pytest.raises(ValueError, match="invalid proposal status transition: pending_review -> implemented"):
        system_evolution_service.create_system_evolution_proposal_action(
            storage_root=storage_root,
            date="2026-07-08",
            proposal_id="proposal:state-machine",
            action="mark_implemented",
            actor="codex",
            test_result="pytest passed",
        )

    system_evolution_service.create_system_evolution_proposal_action(
        storage_root=storage_root,
        date="2026-07-08",
        proposal_id="proposal:state-machine",
        action="reject",
        actor="codex",
    )
    with pytest.raises(ValueError, match="invalid proposal status transition: rejected -> approved"):
        system_evolution_service.create_system_evolution_proposal_action(
            storage_root=storage_root,
            date="2026-07-08",
            proposal_id="proposal:state-machine",
            action="approve",
            actor="codex",
        )


def test_system_evolution_proposal_action_concurrent_appends_do_not_lose_updates(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "system_evolution" / "2026-07-08"
    _write_json(
        base / "improvement_proposals.json",
        {
            "trade_date": "2026-07-08",
            "proposals": [{"proposal_id": "proposal:concurrent", "status": "pending_review"}],
        },
    )
    workers = 8
    barrier = threading.Barrier(workers)
    original_read_json = system_evolution_service._read_json

    def synchronized_read(path):
        payload = original_read_json(path)
        if path.name == "proposal_actions.json":
            barrier.wait(timeout=5)
        return payload

    monkeypatch.setattr(system_evolution_service, "_read_json", synchronized_read)

    def link_issue(index: int) -> None:
        system_evolution_service.create_system_evolution_proposal_action(
            storage_root=storage_root,
            date="2026-07-08",
            proposal_id="proposal:concurrent",
            action="link_issue",
            actor=f"actor-{index}",
            issue_url=f"https://example.test/issues/{index}",
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(link_issue, range(workers)))

    payload = json.loads((base / "proposal_actions.json").read_text(encoding="utf-8"))
    assert len(payload["actions"]) == workers
    assert {item["actor"] for item in payload["actions"]} == {f"actor-{index}" for index in range(workers)}


def test_system_evolution_proposal_action_does_not_overwrite_corrupt_audit(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    base = storage_root / "governance" / "system_evolution" / "2026-07-08"
    _write_json(
        base / "improvement_proposals.json",
        {
            "trade_date": "2026-07-08",
            "proposals": [{"proposal_id": "proposal:corrupt-audit", "status": "pending_review"}],
        },
    )
    actions_path = base / "proposal_actions.json"
    actions_path.write_text("{broken-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON"):
        system_evolution_service.create_system_evolution_proposal_action(
            storage_root=storage_root,
            date="2026-07-08",
            proposal_id="proposal:corrupt-audit",
            action="approve",
            actor="codex",
        )

    assert actions_path.read_text(encoding="utf-8") == "{broken-json"
