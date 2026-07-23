from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.analysis.context_bundle import assemble_context_bundle
from apps.analysis.context_bundle.schemas import (
    AnalysisContextBundle,
    compute_bundle_content_hash,
)
from apps.output.context_bundle import (
    ContextBundleLoadError,
    load_context_bundle,
    write_context_bundle,
)


NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)
V3_FIELDS = {
    "evidence_delta_decision",
    "deferred_queue",
    "processed_above_frontier",
    "selection_decisions",
    "selection_trace",
    "freshness_sla_seconds",
    "default_freshness_sla_seconds",
}


def _bundle(state_scope="daily_close"):
    return assemble_context_bundle(
        run_id="run-67",
        asset="XAUUSD",
        state_scope=state_scope,
        canonical_state_id="state-66",
        canonical_state={
            "asset": "XAUUSD",
            "state_scope": state_scope,
            "core_thesis": "等待突破",
        },
        evidence=[
            {
                "source": "market",
                "evidence_id": "market-2",
                "business_time": NOW,
                "ingested_at": NOW + timedelta(minutes=1),
                "payload": {
                    "evidence_type": "macro_metric",
                    "asset": "XAUUSD",
                    "source_quality": "official",
                    "metric": "dxy",
                    "current_value": 99.8,
                    "previous_value": 100.0,
                    "unit": "index",
                },
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
        f"outputs/context_bundles/XAUUSD/daily_close/run-67/{bundle.bundle_id}.json"
    )
    assert first.registry_artifact["artifact_type"] == "structured_json"
    assert first.registry_artifact["metadata"]["artifact_family"] == (
        "analysis_context_bundle"
    )
    assert first.registry_artifact["metadata"]["state_scope"] == "daily_close"
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


def test_loader_reads_legacy_v1_as_daily_close_but_writer_rejects_it(tmp_path) -> None:
    payload = _bundle().model_dump(mode="json")
    payload["schema_version"] = "analysis_context_bundle.v1"
    payload.pop("state_scope")
    for field in V3_FIELDS:
        payload.pop(field)
    payload["content_hash"] = compute_bundle_content_hash(payload)
    payload["bundle_id"] = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"finance-agent:context-bundle:{payload['content_hash']}",
        )
    )
    legacy = AnalysisContextBundle.model_validate(payload)
    path = (
        tmp_path
        / "outputs"
        / "context_bundles"
        / "XAUUSD"
        / "run-67"
        / f"{legacy.bundle_id}.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_context_bundle(
        storage_root=tmp_path,
        storage_relative_path=path.relative_to(tmp_path).as_posix(),
    )

    assert loaded.schema_version == "analysis_context_bundle.v1"
    assert loaded.state_scope is None
    with pytest.raises(ValueError, match="only persists scoped v3"):
        write_context_bundle(storage_root=tmp_path, bundle=loaded)


def test_loader_preserves_scoped_v2_identity_but_writer_rejects_it(tmp_path) -> None:
    payload = _bundle().model_dump(mode="json")
    payload["schema_version"] = "analysis_context_bundle.v2"
    for field in V3_FIELDS:
        payload.pop(field)
    payload["content_hash"] = compute_bundle_content_hash(payload)
    payload["bundle_id"] = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"finance-agent:context-bundle:{payload['content_hash']}",
        )
    )
    path = (
        tmp_path
        / "outputs"
        / "context_bundles"
        / "XAUUSD"
        / "daily_close"
        / "run-67"
        / f"{payload['bundle_id']}.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_context_bundle(
        storage_root=tmp_path,
        storage_relative_path=path.relative_to(tmp_path).as_posix(),
    )

    assert loaded.schema_version == "analysis_context_bundle.v2"
    assert loaded.content_hash == payload["content_hash"]
    assert loaded.bundle_id == payload["bundle_id"]
    with pytest.raises(ValueError, match="only persists scoped v3"):
        write_context_bundle(storage_root=tmp_path, bundle=loaded)


def test_v2_rejects_unhashed_v3_selection_payload() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["schema_version"] = "analysis_context_bundle.v2"
    payload["content_hash"] = compute_bundle_content_hash(payload)
    payload["bundle_id"] = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"finance-agent:context-bundle:{payload['content_hash']}",
        )
    )

    with pytest.raises(ValidationError, match="must not carry v3 selection fields"):
        AnalysisContextBundle.model_validate(payload)


def test_writer_path_isolated_by_scope_for_same_asset_and_run(tmp_path) -> None:
    daily = write_context_bundle(storage_root=tmp_path, bundle=_bundle("daily_close"))
    intraday = write_context_bundle(storage_root=tmp_path, bundle=_bundle("intraday"))

    assert "/daily_close/" in daily.storage_relative_path
    assert "/intraday/" in intraday.storage_relative_path
    assert daily.storage_relative_path != intraday.storage_relative_path
    assert daily.content_hash != intraday.content_hash
