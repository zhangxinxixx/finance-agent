from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from apps.api.schemas.common import ArtifactType
from apps.api.schemas.source_trace import ArtifactRef, SourceRef


def parse_source_refs(raw: Any) -> list[SourceRef]:
    payload = _normalize_payload(raw)
    if not isinstance(payload, list):
        return []

    refs: list[SourceRef] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source_name") or item.get("source") or item.get("source_id") or f"source-{index}")
        source_id = str(item.get("source_id") or f"{source_name}:{index}")
        source_type = str(item.get("source_type") or item.get("type") or "unknown")
        refs.append(
            SourceRef(
                source_id=source_id,
                source_name=source_name,
                source_type=source_type,
                data_date=item.get("data_date"),
                endpoint=item.get("endpoint"),
                captured_at=item.get("captured_at"),
                file_path=item.get("file_path"),
                sha256=item.get("sha256"),
                url=item.get("url"),
                status=item.get("status"),
            )
        )
    return refs


def parse_artifact_refs(raw: Any) -> list[ArtifactRef]:
    payload = _normalize_payload(raw)
    if not isinstance(payload, list):
        return []

    artifacts: list[ArtifactRef] = []
    for index, item in enumerate(payload):
        if isinstance(item, dict):
            file_path = item.get("file_path")
            if not file_path:
                continue
            artifacts.append(
                ArtifactRef(
                    artifact_id=str(item.get("artifact_id") or f"{file_path}:{index}"),
                    artifact_type=coerce_artifact_type(item.get("artifact_type"), str(file_path)),
                    file_path=str(file_path),
                    version=item.get("version"),
                    generated_at=item.get("generated_at"),
                    sha256=item.get("sha256"),
                )
            )
        elif isinstance(item, str):
            artifacts.append(artifact_ref_from_path(item, artifact_id=f"{item}:{index}"))
    return artifacts


def artifact_ref_from_path(path: str, *, artifact_id: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type=coerce_artifact_type(None, path),
        file_path=path,
    )


def dedupe_artifact_refs(artifacts: Iterable[ArtifactRef]) -> list[ArtifactRef]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ArtifactRef] = []
    for artifact in artifacts:
        key = (artifact.file_path, artifact.artifact_type.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def dedupe_source_refs(sources: Iterable[SourceRef]) -> list[SourceRef]:
    seen: set[tuple[str, str]] = set()
    deduped: list[SourceRef] = []
    for source in sources:
        key = (source.source_id, source.source_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def coerce_artifact_type(raw_type: str | None, file_path: str) -> ArtifactType:
    if raw_type:
        try:
            return ArtifactType(raw_type)
        except ValueError:
            pass

    normalized = file_path.lower()
    if normalized.endswith("source.md") or normalized.endswith("raw_article_report.md"):
        return ArtifactType.source_md
    if (
        normalized.endswith("analysis.md")
        or normalized.endswith("final_report.md")
        or normalized.endswith("agent_analysis_report.md")
    ):
        return ArtifactType.analysis_md
    if (
        normalized.endswith("visual.html")
        or normalized.endswith("daily_analysis.html")
        or normalized.endswith("options_visual_report.html")
    ):
        return ArtifactType.visual_html
    if normalized.endswith("report_structured.json"):
        return ArtifactType.structured_json
    if "/raw/" in normalized:
        return ArtifactType.raw_file
    if "/parsed/" in normalized:
        return ArtifactType.parsed_file
    if "/features/" in normalized:
        return ArtifactType.feature_json
    if normalized.endswith(".png") or normalized.endswith(".jpg") or normalized.endswith(".jpeg"):
        return ArtifactType.chart_snapshot
    return ArtifactType.structured_json


def _normalize_payload(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw
