from __future__ import annotations

import json
import subprocess
import sys

import pytest

from scripts.publish_feishu_docs import PROJECT_ROOT, build_text_block
from scripts.publish_feishu_section import (
    extract_block_text,
    find_section_range,
    marker_text,
)


def test_marker_text_validates_anchor_and_kind():
    assert marker_text("news-pipeline", "start") == "[[finance-agent-section:start:news-pipeline]]"
    assert marker_text("news-pipeline", "end") == "[[finance-agent-section:end:news-pipeline]]"
    with pytest.raises(ValueError, match="anchor"):
        marker_text("", "start")
    with pytest.raises(ValueError, match="kind"):
        marker_text("news-pipeline", "middle")


def test_find_section_range_finds_marker_block_indices():
    children = [
        build_text_block(2, "before"),
        build_text_block(5, marker_text("news-pipeline", "start")),
        build_text_block(2, "body"),
        build_text_block(5, marker_text("news-pipeline", "end")),
        build_text_block(2, "after"),
    ]

    assert find_section_range(children, anchor="news-pipeline") == (1, 4)
    assert extract_block_text(children[2]) == "body"


def test_find_section_range_rejects_partial_markers():
    children = [
        build_text_block(5, marker_text("news-pipeline", "start")),
        build_text_block(2, "body"),
    ]

    with pytest.raises(ValueError, match="partial"):
        find_section_range(children, anchor="news-pipeline")


def test_cli_dry_run_news_section_outputs_bounded_summary():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/publish_feishu_section.py",
            "--document-id",
            "doc_test",
            "--anchor",
            "news-pipeline",
            "--doc-file",
            "docs/13_NEWS_DATA_PIPELINE.md",
            "--diagram",
            "docs/diagrams/news-pipeline-flow.mmd",
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["document_id"] == "doc_test"
    assert payload["anchor"] == "news-pipeline"
    assert payload["action"] == "append"
    assert payload["board_count"] == 1
    assert payload["markdown_files"] == ["docs/13_NEWS_DATA_PIPELINE.md"]
    assert payload["diagrams"] == ["docs/diagrams/news-pipeline-flow.mmd"]
