"""Canonical Jin10 image normalization and retention helpers."""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import cv2
import numpy as np


DEFAULT_JIN10_IMAGE_MAX_LONG_EDGE = 2800
DEFAULT_JIN10_IMAGE_JPEG_QUALITY = 92
DEFAULT_JIN10_IMAGE_MAX_BYTES = 7_000_000
DEFAULT_JIN10_IMAGE_RETENTION_DAYS = 30


@dataclass(frozen=True, slots=True)
class NormalizedJpeg:
    data: bytes
    width: int
    height: int
    sha256: str


def normalize_image_bytes_to_jpeg(
    data: bytes,
    *,
    max_long_edge: int | None = None,
    jpeg_quality: int | None = None,
    max_bytes: int = DEFAULT_JIN10_IMAGE_MAX_BYTES,
) -> NormalizedJpeg:
    """Decode an image and persist the exact JPEG shape used by the VLM."""

    if not data:
        raise ValueError("image_payload_empty")
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("image_decode_failed")

    image = _to_bgr_on_white(image)
    max_edge = _positive_int(
        max_long_edge,
        env_name="JIN10_VISION_MAX_LONG_EDGE",
        default=DEFAULT_JIN10_IMAGE_MAX_LONG_EDGE,
    )
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest > max_edge:
        scale = max_edge / longest
        image = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )

    quality = max(
        70,
        min(
            100,
            _positive_int(
                jpeg_quality,
                env_name="JIN10_VISION_JPEG_QUALITY",
                default=DEFAULT_JIN10_IMAGE_JPEG_QUALITY,
            ),
        ),
    )
    normalized, normalized_image = _encode_jpeg_with_limit(
        image,
        jpeg_quality=quality,
        max_bytes=max_bytes,
    )
    normalized_height, normalized_width = normalized_image.shape[:2]
    return NormalizedJpeg(
        data=normalized,
        width=normalized_width,
        height=normalized_height,
        sha256=hashlib.sha256(normalized).hexdigest(),
    )


def prune_jin10_image_assets(
    *,
    external_root: Path | str,
    storage_root: Path | str,
    reference_date: date | None = None,
    retention_days: int | None = None,
) -> dict[str, int | str]:
    """Prune only disposable VLM cache files and output-layer image copies.

    External page JPEGs and parsed figures are canonical source evidence and are
    never deleted by automatic retention, including during historical replay.
    """

    keep_days = _positive_int(
        retention_days,
        env_name="JIN10_IMAGE_RETENTION_DAYS",
        default=DEFAULT_JIN10_IMAGE_RETENTION_DAYS,
    )
    as_of = reference_date or date.today()
    cutoff = as_of - timedelta(days=keep_days)
    summary = {
        "reference_date": as_of.isoformat(),
        "cutoff_date": cutoff.isoformat(),
        "retention_days": keep_days,
        "deleted_files": 0,
        "deleted_bytes": 0,
        "deleted_directories": 0,
        "output_copy_files": 0,
        "output_copy_bytes": 0,
        "vlm_cache_files": 0,
        "vlm_cache_bytes": 0,
        "canonical_evidence_policy": "preserved",
    }

    # Resolve for API compatibility while deliberately preserving this tree.
    _canonical_external_root = Path(external_root).expanduser()
    storage = Path(storage_root).expanduser()
    _prune_vlm_cache_files(
        storage / "parsed" / "jin10" / "vision_cache",
        cutoff=cutoff,
        summary=summary,
    )

    outputs_root = storage / "outputs" / "jin10"
    if outputs_root.is_dir():
        for asset_dir in (*outputs_root.glob("*/*/figures"), *outputs_root.glob("*/*/images")):
            _delete_image_directory(asset_dir, summary=summary, output_copy=True)

    return summary


def _prune_vlm_cache_files(
    cache_root: Path,
    *,
    cutoff: date,
    summary: dict[str, int | str],
) -> None:
    if not cache_root.is_dir():
        return
    cutoff_timestamp = datetime.combine(cutoff, time.min).timestamp()
    for item in cache_root.rglob("*"):
        if not (item.is_file() or item.is_symlink()):
            continue
        stat = item.stat()
        if stat.st_mtime >= cutoff_timestamp:
            continue
        byte_count = stat.st_size if item.is_file() else 0
        item.unlink()
        summary["deleted_files"] = int(summary["deleted_files"]) + 1
        summary["deleted_bytes"] = int(summary["deleted_bytes"]) + byte_count
        summary["vlm_cache_files"] = int(summary["vlm_cache_files"]) + 1
        summary["vlm_cache_bytes"] = int(summary["vlm_cache_bytes"]) + byte_count
    for directory in sorted((path for path in cache_root.rglob("*") if path.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
            summary["deleted_directories"] = int(summary["deleted_directories"]) + 1


def _to_bgr_on_white(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim != 3:
        raise ValueError("image_shape_unsupported")
    channels = image.shape[2]
    if channels == 3:
        return image
    if channels != 4:
        raise ValueError("image_channels_unsupported")
    color = image[:, :, :3].astype(np.float32)
    alpha = image[:, :, 3:4].astype(np.float32) / 255.0
    composited = color * alpha + 255.0 * (1.0 - alpha)
    return np.clip(composited, 0, 255).astype(np.uint8)


def _encode_jpeg_with_limit(
    image: np.ndarray,
    *,
    jpeg_quality: int,
    max_bytes: int,
) -> tuple[bytes, np.ndarray]:
    if max_bytes <= 0:
        raise ValueError("jpeg_max_bytes_must_be_positive")
    qualities = tuple(dict.fromkeys((jpeg_quality, 90, 85, 80, 70)))
    for scale in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
        current = image
        if scale < 1.0:
            current = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_AREA,
            )
        for quality in qualities:
            ok, buffer = cv2.imencode(
                ".jpg",
                current,
                [int(cv2.IMWRITE_JPEG_QUALITY), quality],
            )
            if not ok:
                continue
            encoded = buffer.tobytes()
            if len(encoded) <= max_bytes:
                return encoded, current
    raise ValueError("jpeg_exceeds_vlm_payload_limit")


def _positive_int(value: int | None, *, env_name: str, default: int) -> int:
    resolved = value if value is not None else int(os.getenv(env_name, default))
    if int(resolved) <= 0:
        raise ValueError(f"{env_name.lower()}_must_be_positive")
    return int(resolved)


def _dated_directories(root: Path, *, before: date) -> list[Path]:
    if not root.is_dir():
        return []
    dated: list[Path] = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            artifact_date = date.fromisoformat(path.name)
        except ValueError:
            continue
        if artifact_date < before:
            dated.append(path)
    return dated


def _delete_image_directory(
    path: Path,
    *,
    summary: dict[str, int | str],
    output_copy: bool,
) -> None:
    if not path.is_dir():
        return
    files = [item for item in path.rglob("*") if item.is_file() or item.is_symlink()]
    byte_count = sum(item.stat().st_size for item in files if item.is_file())
    file_count = len(files)
    shutil.rmtree(path)
    summary["deleted_files"] = int(summary["deleted_files"]) + file_count
    summary["deleted_bytes"] = int(summary["deleted_bytes"]) + byte_count
    summary["deleted_directories"] = int(summary["deleted_directories"]) + 1
    if output_copy:
        summary["output_copy_files"] = int(summary["output_copy_files"]) + file_count
        summary["output_copy_bytes"] = int(summary["output_copy_bytes"]) + byte_count
