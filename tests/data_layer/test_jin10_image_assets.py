from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import cv2
import numpy as np

from apps.data_layer.jin10_image_assets import (
    normalize_image_bytes_to_jpeg,
    prune_jin10_image_assets,
)


def _encoded_image(ext: str, image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(ext, image)
    assert ok
    return buffer.tobytes()


def test_normalize_image_bytes_to_jpeg_resizes_and_flattens_alpha() -> None:
    image = np.zeros((120, 300, 4), dtype=np.uint8)
    image[:, :, :3] = (0, 0, 255)
    image[:, :, 3] = 128

    normalized = normalize_image_bytes_to_jpeg(
        _encoded_image(".png", image),
        max_long_edge=150,
        jpeg_quality=90,
    )

    decoded = cv2.imdecode(np.frombuffer(normalized.data, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert normalized.width == 150
    assert normalized.height == 60
    assert normalized.data.startswith(b"\xff\xd8")
    assert decoded is not None
    assert decoded.shape[:2] == (60, 150)
    assert int(decoded[0, 0, 2]) > 200
    assert int(decoded[0, 0, 1]) > 100
    assert int(decoded[0, 0, 0]) > 100


def test_normalize_image_bytes_to_jpeg_enforces_vlm_payload_limit() -> None:
    rng = np.random.default_rng(42)
    image = rng.integers(0, 256, size=(600, 600, 3), dtype=np.uint8)

    normalized = normalize_image_bytes_to_jpeg(
        _encoded_image(".png", image),
        max_long_edge=600,
        jpeg_quality=92,
        max_bytes=60_000,
    )

    assert len(normalized.data) <= 60_000
    assert normalized.width < 600
    assert normalized.height < 600


def test_prune_jin10_image_assets_preserves_canonical_evidence_and_removes_only_disposable_assets(
    tmp_path: Path,
) -> None:
    external_root = tmp_path / "external"
    storage_root = tmp_path / "storage"

    old_external = external_root / "2026-06-13" / "daily" / "1" / "images"
    old_parsed = storage_root / "parsed" / "jin10" / "2026-06-13" / "1" / "figures"
    old_cache = storage_root / "parsed" / "jin10" / "vision_cache" / "layout" / "old.json"
    recent_cache = storage_root / "parsed" / "jin10" / "vision_cache" / "layout" / "recent.json"
    output_figures = storage_root / "outputs" / "jin10" / "2026-07-14" / "3" / "figures"
    output_images = storage_root / "outputs" / "jin10" / "2026-07-14" / "3" / "images"
    for directory in (old_external, old_parsed, output_figures, output_images):
        directory.mkdir(parents=True)
        (directory / "asset.jpg").write_bytes(b"image")
    old_cache.parent.mkdir(parents=True)
    old_cache.write_text("{}", encoding="utf-8")
    recent_cache.write_text("{}", encoding="utf-8")
    old_timestamp = date(2026, 6, 1).strftime("%s")
    os.utime(old_cache, (int(old_timestamp), int(old_timestamp)))
    recent_timestamp = date(2026, 7, 1).strftime("%s")
    os.utime(recent_cache, (int(recent_timestamp), int(recent_timestamp)))
    (old_external.parent / "report.md").write_text("keep", encoding="utf-8")
    output_report = output_figures.parent / "raw_article_report.json"
    output_report.write_text("{}", encoding="utf-8")

    summary = prune_jin10_image_assets(
        external_root=external_root,
        storage_root=storage_root,
        reference_date=date(2026, 7, 14),
        retention_days=30,
    )

    assert summary["cutoff_date"] == "2026-06-14"
    assert summary["canonical_evidence_policy"] == "preserved"
    assert summary["deleted_files"] == 3
    assert summary["output_copy_files"] == 2
    assert summary["vlm_cache_files"] == 1
    assert old_external.is_dir()
    assert old_parsed.is_dir()
    assert not old_cache.exists()
    assert recent_cache.exists()
    assert not output_figures.exists()
    assert not output_images.exists()
    assert (old_external.parent / "report.md").read_text(encoding="utf-8") == "keep"
    assert output_report.read_text(encoding="utf-8") == "{}"
