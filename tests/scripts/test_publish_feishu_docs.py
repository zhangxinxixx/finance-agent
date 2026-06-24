from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.publish_feishu_docs import (
    BOARD_BLOCK,
    HEADING_1_BLOCK,
    MERMAID_SYNTAX_TYPE,
    PROJECT_DOCS_EXISTING_DOCUMENT_IDS,
    PROJECT_ROOT,
    TABLE_BLOCK,
    TEXT_BLOCK,
    PublishDocumentSpec,
    attach_existing_document_ids,
    build_lark_cli_api_command,
    build_board_block,
    build_mermaid_node_payload,
    build_table_block,
    calculate_table_column_widths,
    collect_document_specs,
    extract_table_cell_ids,
    find_board_token,
    is_table_plan,
    markdown_to_lark_blocks,
    publish_spec,
    table_plan_rows,
)


def _block_text(block: dict) -> str:
    block_type = block["block_type"]
    field_name = "text" if block_type == TEXT_BLOCK else f"heading{block_type - HEADING_1_BLOCK + 1}"
    return block[field_name]["elements"][0]["text_run"]["content"]


def test_markdown_to_lark_blocks_preserves_headings_paragraphs_and_code():
    blocks = markdown_to_lark_blocks(
        """# Title

Paragraph line one
line two

## Section

```text
api -> worker
```
"""
    )

    assert [block["block_type"] for block in blocks] == [HEADING_1_BLOCK, TEXT_BLOCK, HEADING_1_BLOCK + 1, TEXT_BLOCK]
    assert _block_text(blocks[0]) == "Title"
    assert _block_text(blocks[1]) == "Paragraph line one line two"
    assert _block_text(blocks[3]) == "```\napi -> worker\n```"


def test_markdown_to_lark_blocks_keeps_list_items_separate_and_strips_links():
    blocks = markdown_to_lark_blocks(
        """## 快速入口

- [00_PROJECT_OVERVIEW.md](00_PROJECT_OVERVIEW.md)：项目定位和当前状态
- [01_ARCHITECTURE.md](01_ARCHITECTURE.md)：总体架构
"""
    )

    texts = [_block_text(block) for block in blocks]
    assert texts == [
        "快速入口",
        "• 00_PROJECT_OVERVIEW.md：项目定位和当前状态",
        "• 01_ARCHITECTURE.md：总体架构",
    ]


def test_markdown_to_lark_blocks_renders_tables_as_readable_rows():
    blocks = markdown_to_lark_blocks(
        """| 文件 | 用途 |
| --- | --- |
| `docs/README.md` | 文档入口 |
| `docs/diagrams` | 流程图 |
"""
    )

    assert len(blocks) == 1
    assert is_table_plan(blocks[0])
    assert table_plan_rows(blocks[0]) == [
        ["文件", "用途"],
        ["`docs/README.md`", "文档入口"],
        ["`docs/diagrams`", "流程图"],
    ]


def test_build_table_block_and_extract_cell_ids():
    block = build_table_block(row_size=2, column_size=2, column_widths=[160, 320])
    response = {"table": {"cells": ["cell-1", "cell-2", "cell-3", "cell-4"]}}

    assert block == {
        "block_type": TABLE_BLOCK,
        "table": {"property": {"row_size": 2, "column_size": 2, "column_width": [160, 320]}},
    }
    assert extract_table_cell_ids(response) == ["cell-1", "cell-2", "cell-3", "cell-4"]


def test_calculate_table_column_widths_expands_long_columns():
    widths = calculate_table_column_widths(
        [
            ["文件", "说明"],
            ["short.py", "这是一个很长的中文说明，用于验证较长列会获得更多宽度"],
        ]
    )

    assert len(widths) == 2
    assert widths[1] > widths[0]
    assert sum(widths) <= 940


def test_large_markdown_table_is_split_into_multiple_native_tables():
    rows = ["| A | B |", "| --- | --- |"]
    rows.extend(f"| a{i} | b{i} |" for i in range(12))

    blocks = markdown_to_lark_blocks("\n".join(rows))

    assert len(blocks) == 2
    assert all(is_table_plan(block) for block in blocks)
    assert len(table_plan_rows(blocks[0])) == 8
    assert len(table_plan_rows(blocks[1])) == 6
    assert table_plan_rows(blocks[1])[0] == ["A", "B"]


def test_build_board_and_mermaid_payload():
    board = build_board_block()
    payload = build_mermaid_node_payload("flowchart LR\n  A --> B")

    assert board == {"block_type": BOARD_BLOCK, "board": {}}
    assert payload["syntax_type"] == MERMAID_SYNTAX_TYPE
    assert payload["plant_uml_code"].startswith("flowchart LR")


def test_build_lark_cli_api_command_normalizes_openapi_path():
    command = build_lark_cli_api_command(
        method="post",
        path="/docx/v1/documents/doc/blocks/block/children",
        json_body={"children": []},
        params={"document_revision_id": -1},
    )

    assert command[:5] == [
        "lark-cli",
        "api",
        "POST",
        "/open-apis/docx/v1/documents/doc/blocks/block/children",
        "--as",
    ]
    assert "user" in command
    assert "--params" in command
    assert "--data" in command


def test_find_board_token_uses_board_block_token_not_block_id():
    token = find_board_token(
        [
            {"block_id": "doxcn_block", "block_type": BOARD_BLOCK, "token": "whiteboard_token"},
            {"block_id": "text_block", "block_type": TEXT_BLOCK, "token": "not_board"},
        ],
        block_id="doxcn_block",
    )

    assert token == "whiteboard_token"


def test_collect_project_docs_preset_uses_real_docs():
    args = type(
        "Args",
        (),
        {
            "preset": "project-docs-baseline",
                "title": None,
                "doc_file": [],
                "diagram": [],
                "create_new": False,
            },
        )()

    specs = collect_document_specs(args)

    assert len(specs) == 2
    assert PROJECT_DOCS_EXISTING_DOCUMENT_IDS == {}
    assert specs[0].document_id is None
    assert any(path.as_posix() == "docs/diagrams/system-architecture.mmd" for path in specs[0].diagram_paths)
    for spec in specs:
        for relative_path in [*spec.markdown_paths, *spec.diagram_paths]:
            assert (PROJECT_ROOT / relative_path).exists(), relative_path


def test_attach_existing_document_ids_binds_known_project_docs():
    specs = attach_existing_document_ids(
        (PublishDocumentSpec(title="finance-agent 页面规格", markdown_paths=(Path("docs/frontend/page-specs/dashboard.md"),)),)
    )

    assert specs[0].document_id is None


def test_custom_preset_requires_title():
    args = type(
        "Args",
        (),
        {
            "preset": "custom",
            "title": None,
            "doc_file": ["docs/README.md"],
            "diagram": [],
            "create_new": False,
            "document_id": None,
        },
    )()

    with pytest.raises(ValueError, match="--title"):
        collect_document_specs(args)


def test_cli_dry_run_custom_doc_with_mermaid(tmp_path: Path):
    doc_path = tmp_path / "doc.md"
    diagram_path = tmp_path / "diagram.mmd"
    doc_path.write_text("# Demo\n\nBody", encoding="utf-8")
    diagram_path.write_text("flowchart LR\n  A --> B", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/publish_feishu_docs.py",
            "--preset",
            "custom",
            "--title",
            "Demo",
            "--doc-file",
            str(doc_path),
            "--diagram",
            str(diagram_path),
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "path must stay inside project root" in result.stderr


def test_cli_dry_run_project_preset_outputs_summary():
    result = subprocess.run(
        [sys.executable, "scripts/publish_feishu_docs.py", "--dry-run"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload) == 2
    assert payload[0]["action"] == "create"
    assert payload[0]["document_id"] is None
    assert payload[0]["board_count"] == 8
    assert payload[0]["table_count"] > 0
    assert "docs/diagrams/system-architecture.mmd" in payload[0]["diagrams"]
    assert "docs/diagrams/news-pipeline-flow.mmd" in payload[0]["diagrams"]
    assert payload[1]["action"] == "create"
    assert payload[1]["document_id"] is None


def test_publish_existing_document_requires_confirm_overwrite():
    spec = PublishDocumentSpec(
        title="existing",
        markdown_paths=(Path("docs/README.md"),),
        document_id="doc_existing",
    )

    with pytest.raises(ValueError, match="confirm-overwrite"):
        publish_spec(
            spec=spec,
            folder_token=None,
            dry_run=False,
            client=object(),  # type: ignore[arg-type]
            base_url="https://open.feishu.cn/open-apis",
            max_blocks_per_request=50,
            confirm_overwrite=False,
        )
