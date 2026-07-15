from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.runtime.immutable_artifact import (
    ImmutableArtifactConflictError,
    immutable_json_item,
    immutable_text_item,
    write_immutable_artifact_bundle,
)


def test_bundle_is_idempotent_and_fills_missing_files(tmp_path: Path) -> None:
    report = tmp_path / "outputs" / "report.md"
    payload = tmp_path / "outputs" / "report.json"
    items = [
        immutable_text_item(report, "# report\n"),
        immutable_json_item(payload, {"status": "limited"}),
    ]

    first = write_immutable_artifact_bundle(items, storage_root=tmp_path)
    payload.unlink()
    second = write_immutable_artifact_bundle(items, storage_root=tmp_path)
    third = write_immutable_artifact_bundle(items, storage_root=tmp_path)

    assert [item.written for item in first] == [True, True]
    assert [item.written for item in second] == [False, True]
    assert [item.written for item in third] == [False, False]
    assert json.loads(payload.read_text(encoding="utf-8")) == {"status": "limited"}


def test_bundle_conflict_does_not_write_other_missing_files(tmp_path: Path) -> None:
    existing = tmp_path / "existing.json"
    missing = tmp_path / "missing.md"
    existing.write_text('{"status":"old"}\n', encoding="utf-8")

    with pytest.raises(ImmutableArtifactConflictError, match="different content"):
        write_immutable_artifact_bundle(
            [
                immutable_json_item(existing, {"status": "new"}),
                immutable_text_item(missing, "new\n"),
            ],
            storage_root=tmp_path,
        )

    assert not missing.exists()


def test_bundle_rejects_path_outside_storage_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside storage_root"):
        write_immutable_artifact_bundle(
            [immutable_text_item(tmp_path / "outside.md", "x")],
            storage_root=tmp_path / "storage",
        )
