from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.publish_feishu_workspace_v2 import (
    PROJECT_ROOT,
    build_api_map_table,
    build_bitable_specs,
    build_data_model_storage_table,
    build_lark_cli_api_command,
    build_module_status_table,
    build_page_matrix_table,
    build_risks_todo_table,
    build_roadmap_table,
    extract_roadmap_records,
    parse_markdown_tables,
)


def test_parse_markdown_tables_keeps_section_names():
    tables = parse_markdown_tables(Path("docs/10_API_MAP.md"))

    assert tables
    assert tables[0].section == "Core"
    assert tables[0].header == ["Method", "Path", "用途"]
    assert tables[0].rows[0] == ["GET", "/health", "健康检查"]


def test_build_api_map_table_normalizes_records():
    table = build_api_map_table()

    assert table.name == "API_MAP"
    assert table.fields == ["分组", "Method", "Path", "页面/用途", "来源文件"]
    assert any(record["Path"] == "/api/runs" and record["分组"] == "Tasks / Runs" for record in table.records)
    assert all(record["来源文件"] == "docs/10_API_MAP.md" for record in table.records)


def test_build_page_matrix_table_uses_markdown_header():
    table = build_page_matrix_table()

    assert table.name == "PAGE_MATRIX"
    assert "页面" in table.fields
    assert "验收标准" in table.fields
    assert table.records[0]["页面"] == "Dashboard"
    assert table.records[0]["来源文件"] == "docs/11_PAGE_RESPONSIBILITY_MATRIX.md"


def test_extract_roadmap_records_from_backend_and_frontend():
    backend = extract_roadmap_records(Path("docs/08_BACKEND_ROADMAP.md"), area="后端")
    frontend = extract_roadmap_records(Path("docs/09_FRONTEND_ROADMAP.md"), area="前端")

    assert any(record["阶段/任务"].startswith("Phase 1") for record in backend)
    assert any(record["阶段/任务"].startswith("1. 统一 contracts/types") for record in frontend)
    assert all(record["状态"] == "待规划" for record in [*backend, *frontend])


def test_build_bitable_specs_contains_three_tables():
    specs = build_bitable_specs()

    assert [spec.name for spec in specs] == [
        "API_MAP",
        "PAGE_MATRIX",
        "ROADMAP",
        "RISKS_TODO",
        "DATA_MODEL_STORAGE",
        "MODULE_STATUS",
    ]
    assert all(spec.records for spec in specs)
    roadmap = build_roadmap_table()
    assert any(record["领域"] == "后端" for record in roadmap.records)
    assert any(record["领域"] == "前端" for record in roadmap.records)


def test_build_additional_v2_tables():
    risks = build_risks_todo_table()
    data_model = build_data_model_storage_table()
    module_status = build_module_status_table()

    assert risks.records[0]["优先级"] == "高优先级"
    assert "Step" in risks.records[0]["事项"]
    assert any(record["分组"] == "TaskRun / TaskStep" and record["类型"] == "表" for record in data_model.records)
    assert any(record["对象"] == "FastAPI 应用" and record["状态"] == "已实现" for record in module_status.records)


def test_cli_dry_run_outputs_v2_summary():
    result = subprocess.run(
        [sys.executable, "scripts/publish_feishu_workspace_v2.py", "--dry-run"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["title"] == "finance-agent 工程文档中台 V2"
    assert payload["architecture_doc_url"] is None
    assert payload["bitable_record_counts"]["API_MAP"] > 20
    assert payload["bitable_record_counts"]["PAGE_MATRIX"] >= 10
    assert payload["bitable_record_counts"]["RISKS_TODO"] == 10
    assert payload["bitable_created_tables"] == [
        "API_MAP",
        "PAGE_MATRIX",
        "ROADMAP",
        "RISKS_TODO",
        "DATA_MODEL_STORAGE",
        "MODULE_STATUS",
    ]


def test_cli_update_existing_dry_run_uses_manifest():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/publish_feishu_workspace_v2.py",
            "--dry-run",
            "--update-existing",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["bitable_url"] == "https://my.feishu.cn/base/XwQgbvxOvakyq5sxqnscjLPpnbf"
    assert payload["bitable_skipped_tables"] == [
        "API_MAP",
        "PAGE_MATRIX",
        "ROADMAP",
        "RISKS_TODO",
        "DATA_MODEL_STORAGE",
        "MODULE_STATUS",
    ]
    assert payload["bitable_created_tables"] == []


def test_build_lark_cli_api_command_uses_openapi_path_and_user_identity():
    command = build_lark_cli_api_command(
        method="POST",
        path="/bitable/v1/apps/app_token/tables",
        json_body={"table": {"name": "Demo"}},
        params={"page_size": 1},
    )

    assert command[:6] == [
        "lark-cli",
        "api",
        "POST",
        "/open-apis/bitable/v1/apps/app_token/tables",
        "--as",
        "user",
    ]
    assert "--params" in command
    assert "--data" in command
