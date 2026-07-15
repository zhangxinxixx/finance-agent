from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.analysis.context_bundle import assemble_context_bundle
from apps.output.context_bundle import (
    ContextBundleLoadError,
    load_context_bundle,
    write_context_bundle,
)


NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)


def _bundle():
    return assemble_context_bundle(
        run_id="run-67",
        asset="XAUUSD",
        canonical_state_id="state-66",
        canonical_state={"core_thesis": "等待突破"},
        evidence=[
            {
                "source": "market",
                "evidence_id": "market-2",
                "business_time": NOW,
                "ingested_at": NOW + timedelta(minutes=1),
                "payload": {"price": 4050},
                "source_ref": {"snapshot_id": "market-2"},
            }
        ],
        evidence_cursors={},
        cutoff_at=NOW + timedelta(minutes=2),
        assembled_at=NOW + timedelta(minutes=3),
    )


def test_writer_is_storage_relative_idempotent_and_run_artifact_ready(tmp_path) -> None:
    bundle = _bundle()
    first = write_context_bundle(storage_root=tmp_path, bundle=bundle)
    replay = write_context_bundle(storage_root=tmp_path, bundle=bundle)

    assert first.written is True
    assert replay.written is False
    assert first.storage_relative_path == (
        f"outputs/context_bundles/XAUUSD/run-67/{bundle.bundle_id}.json"
    )
    assert first.registry_artifact["artifact_type"] == "structured_json"
    assert first.registry_artifact["metadata"]["artifact_family"] == (
        "analysis_context_bundle"
    )
    assert load_context_bundle(
        storage_root=tmp_path,
        storage_relative_path=first.storage_relative_path,
    ) == bundle


def test_loader_rejects_tampered_hash_or_unsafe_path(tmp_path) -> None:
    result = write_context_bundle(storage_root=tmp_path, bundle=_bundle())
    path = tmp_path / result.storage_relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["asset"] = "GC"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContextBundleLoadError, match="schema/hash"):
        load_context_bundle(
            storage_root=tmp_path,
            storage_relative_path=result.storage_relative_path,
        )
    with pytest.raises(ContextBundleLoadError):
        load_context_bundle(
            storage_root=tmp_path,
            storage_relative_path="outputs/context_bundles/../../secret.json",
        )


def test_writer_revalidates_nested_mutation_before_persisting(tmp_path) -> None:
    bundle = _bundle()
    bundle.blocks[0].payload["core_thesis"] = "篡改"

    with pytest.raises(ValidationError, match="utf8_bytes"):
        write_context_bundle(storage_root=tmp_path, bundle=bundle)
    assert not (tmp_path / "outputs").exists()
