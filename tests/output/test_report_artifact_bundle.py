from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.output.report_artifacts import STANDARD_REPORT_ARTIFACTS, write_standard_report_artifacts


def test_write_standard_report_artifacts_creates_four_artifact_manifest(tmp_path: Path) -> None:
    result = write_standard_report_artifacts(
        storage_root=tmp_path,
        family="macro",
        report_id="report-std-001",
        trade_date="2026-05-26",
        run_id="run-std-001",
        source_markdown="# Source\n\nInput evidence",
        analysis_markdown="# Analysis\n\nResearch view",
        structured_payload={"report_id": "report-std-001", "sections": []},
        visual_html="<html><body>visual</body></html>",
    )

    assert result["artifact_type"] == "standard_report"
    assert result["report_id"] == "report-std-001"
    assert result["artifact_dir"].endswith("outputs/reports/2026-05-26/report-std-001")
    assert [item["artifact_type"] for item in result["artifacts"]] == [
        "source_md",
        "analysis_md",
        "visual_html",
        "structured_json",
    ]
    assert [item["content_type"] for item in result["artifacts"]] == [
        "text/markdown",
        "text/markdown",
        "text/html",
        "application/json",
    ]
    assert [item["is_primary"] for item in result["artifacts"]] == [True, False, False, False]
    assert {item["filename"] for item in STANDARD_REPORT_ARTIFACTS} == {
        "source.md",
        "analysis.md",
        "visual.html",
        "report_structured.json",
    }

    source_path = Path(result["artifacts"][0]["path"])
    analysis_path = Path(result["artifacts"][1]["path"])
    visual_path = Path(result["artifacts"][2]["path"])
    structured_path = Path(result["artifacts"][3]["path"])
    assert source_path.read_text(encoding="utf-8").startswith("# Source")
    assert analysis_path.read_text(encoding="utf-8").startswith("# Analysis")
    assert visual_path.read_text(encoding="utf-8").startswith("<html>")
    assert json.loads(structured_path.read_text(encoding="utf-8"))["report_id"] == "report-std-001"


def test_write_standard_report_artifacts_default_no_overwrite(tmp_path: Path) -> None:
    kwargs = {
        "storage_root": tmp_path,
        "family": "macro",
        "report_id": "report-std-001",
        "trade_date": "2026-05-26",
        "run_id": "run-std-001",
        "source_markdown": "# Source",
        "analysis_markdown": "# Analysis",
        "structured_payload": {"sections": []},
        "visual_html": "<html></html>",
    }
    write_standard_report_artifacts(**kwargs)

    with pytest.raises(FileExistsError, match="standard report artifacts already exist"):
        write_standard_report_artifacts(**kwargs)


def test_write_standard_report_artifacts_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="report_id"):
        write_standard_report_artifacts(
            storage_root=tmp_path,
            family="macro",
            report_id="../escape",
            trade_date="2026-05-26",
            run_id="run-std-001",
            source_markdown="# Source",
            analysis_markdown="# Analysis",
            structured_payload={"sections": []},
            visual_html=None,
        )
