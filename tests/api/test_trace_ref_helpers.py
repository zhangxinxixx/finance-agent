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


def test_parse_source_refs_supports_report_date_and_source_url_aliases() -> None:
    parsed = parse_source_refs(
        [
            {
                "source_id": "src-review-001",
                "source_name": "CME",
                "source_type": "pdf",
                "report_date": "2026-05-06",
                "source_url": "https://example.test/cme.pdf",
            }
        ]
    )

    assert parsed[0].data_date == "2026-05-06"
    assert parsed[0].url == "https://example.test/cme.pdf"


def test_artifact_ref_from_path_supports_report_alias_filenames() -> None:
    source_ref = artifact_ref_from_path(
        "storage/outputs/jin10/2026-05-31/220787/raw_article_report.md",
        artifact_id="report:source",
    )
    analysis_ref = artifact_ref_from_path(
        "storage/outputs/final_report/XAUUSD/2026-05-26/run-001/final_report.md",
        artifact_id="report:analysis",
    )
    options_ref = artifact_ref_from_path(
        "storage/outputs/cme/2026-05-26/run-001/options_analysis_agent_report.md",
        artifact_id="report:options",
    )
    visual_ref = artifact_ref_from_path(
        "storage/outputs/jin10/2026-05-31/220787/daily_analysis.html",
        artifact_id="report:visual",
    )

    assert source_ref.artifact_type == ArtifactType.source_md
    assert analysis_ref.artifact_type == ArtifactType.analysis_md
    assert options_ref.artifact_type == ArtifactType.analysis_md
    assert visual_ref.artifact_type == ArtifactType.visual_html
