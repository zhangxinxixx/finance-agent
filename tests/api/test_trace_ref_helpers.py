from __future__ import annotations

import json

from apps.api.schemas.common import ArtifactType
from apps.api.services._trace_refs import (
    artifact_ref_from_path,
    dedupe_artifact_refs,
    dedupe_source_refs,
    parse_artifact_refs,
    parse_source_refs,
)


def test_parse_artifact_refs_and_dedupe_support_json_strings_and_path_refs() -> None:
    parsed = parse_artifact_refs(
        json.dumps(
            [
                {
                    "artifact_id": "art-001",
                    "artifact_type": "parsed_file",
                    "file_path": "storage/parsed/macro/output.json",
                },
                "storage/parsed/macro/output.json",
                {
                    "artifact_id": "art-visual-001",
                    "artifact_type": "visual_html",
                    "file_path": "storage/outputs/reports/2026-05-26/run-001/visual.html",
                },
            ]
        )
    )

    deduped = dedupe_artifact_refs(
        [
            *parsed,
            artifact_ref_from_path(
                "storage/parsed/macro/output.json",
                artifact_id="step-001:output_ref",
            ),
        ]
    )

    assert [item.artifact_type for item in deduped] == [
        ArtifactType.parsed_file,
        ArtifactType.visual_html,
    ]
    assert deduped[0].artifact_id == "art-001"


def test_parse_source_refs_and_dedupe_support_json_and_python_lists() -> None:
    from_json = parse_source_refs(
        json.dumps(
            [
                {"source_id": "src-001", "source_name": "FRED", "source_type": "api"},
                {"source_id": "src-001", "source_name": "FRED", "source_type": "api"},
            ]
        )
    )
    from_list = parse_source_refs(
        [
            {"source_id": "src-002", "source_name": "CME", "source_type": "pdf"},
        ]
    )

    deduped = dedupe_source_refs([*from_json, *from_list])

    assert [item.source_id for item in deduped] == ["src-001", "src-002"]

