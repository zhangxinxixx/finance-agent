from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.agents.gold_artifacts import (
    GoldAgentArtifact,
    GoldArtifactConflictError,
    canonical_gold_agent_artifact_json,
    write_canonical_gold_json,
    write_gold_agent_artifact,
)


def _artifact(**overrides: object) -> GoldAgentArtifact:
    payload: dict[str, object] = {
        "agent_name": "SourceHealthAgent",
        "run_id": "gold-run-001",
        "snapshot_id": "gold-snapshot-001",
        "input_snapshot_ids": {"analysis_snapshot": "gold-snapshot-001"},
        "source_refs": [{"source_id": "dxy", "path": "storage/raw/dxy.json"}],
        "artifact_refs": [
            {"artifact_type": "json", "file_path": "storage/outputs/gold/source_health.json"}
        ],
        "evidence_refs": [{"source_id": "dxy", "field": "close"}],
        "evidence_items": [{"factor": "dxy", "direction": "bearish"}],
        "data_quality": ["fresh"],
        "confidence": 0.8,
        "status": "success",
        "created_at": datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return GoldAgentArtifact.model_validate(payload)


def test_valid_artifact_json_roundtrip() -> None:
    artifact = _artifact()

    restored = GoldAgentArtifact.model_validate_json(artifact.model_dump_json())

    assert restored == artifact
    assert restored.status.value == "success"
    assert restored.input_snapshot_ids == {"analysis_snapshot": "gold-snapshot-001"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "skipped"),
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("agent_name", " "),
        ("run_id", ""),
        ("snapshot_id", "\t"),
    ],
)
def test_artifact_rejects_invalid_contract_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        _artifact(**{field: value})


def test_write_is_atomic_and_returns_traceable_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "storage" / "outputs" / "gold" / "source_health.agent.json"
    replace_calls: list[tuple[Path, Path]] = []

    from apps.runtime import immutable_artifact

    real_replace = immutable_artifact.os.replace

    def capture_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.exists()
        assert source_path.parent == destination_path.parent
        replace_calls.append((source_path, destination_path))
        real_replace(source_path, destination_path)

    monkeypatch.setattr(immutable_artifact.os, "replace", capture_replace)

    result = write_gold_agent_artifact(target, _artifact(), storage_root=tmp_path)

    assert result.written is True
    assert result.target_path == str(target)
    assert result.storage_relative_path == "storage/outputs/gold/source_health.agent.json"
    assert len(result.content_sha256) == 64
    assert replace_calls and replace_calls[0][1] == target
    assert json.loads(target.read_text(encoding="utf-8"))["agent_name"] == "SourceHealthAgent"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_same_canonical_json_is_idempotent_without_rewrite(tmp_path: Path) -> None:
    target = tmp_path / "source_health.agent.json"
    artifact = _artifact()
    target.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, sort_keys=False),
        encoding="utf-8",
    )
    original_stat = target.stat()

    result = write_gold_agent_artifact(target, artifact)

    assert result.written is False
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns


def test_existing_different_content_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "source_health.agent.json"
    first = _artifact(confidence=0.8)
    write_gold_agent_artifact(target, first)
    before = target.read_bytes()

    with pytest.raises(GoldArtifactConflictError, match="different content"):
        write_gold_agent_artifact(target, _artifact(confidence=0.7))

    assert target.read_bytes() == before


def test_canonical_json_has_stable_sorted_structure() -> None:
    encoded_once = canonical_gold_agent_artifact_json(_artifact())
    encoded_twice = canonical_gold_agent_artifact_json(_artifact())
    payload = json.loads(encoded_once)

    assert encoded_once == encoded_twice
    assert encoded_once.endswith("\n")
    assert list(payload) == [
        "agent_name",
        "artifact_refs",
        "confidence",
        "created_at",
        "data_quality",
        "evidence_items",
        "evidence_refs",
        "input_snapshot_ids",
        "run_id",
        "snapshot_id",
        "source_refs",
        "status",
    ]
    assert payload["status"] == "success"


def test_target_outside_storage_root_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "outside" / "artifact.json"
    storage_root = tmp_path / "storage"

    with pytest.raises(ValueError, match="inside storage_root"):
        write_gold_agent_artifact(target, _artifact(), storage_root=storage_root)

    assert not target.exists()


def test_canonical_business_json_is_immutable_and_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "source_health.json"
    payload = {"overall_status": "degraded", "warnings": ["stale"]}

    first = write_canonical_gold_json(target, payload)
    second = write_canonical_gold_json(target, payload)

    assert first.written is True
    assert second.written is False
    with pytest.raises(GoldArtifactConflictError, match="different content"):
        write_canonical_gold_json(target, {"overall_status": "blocked"})
    assert json.loads(target.read_text(encoding="utf-8")) == payload
