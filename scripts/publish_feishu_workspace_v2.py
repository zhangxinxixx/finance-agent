#!/usr/bin/env python3
"""Create a Feishu V2 documentation workspace with Docx + Bitable.

This V2 publisher keeps long tables out of Docx. Docx documents stay readable
and visual, while Bitable stores structured API/page/roadmap records.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.publish_feishu_docs import (  # noqa: E402
    FEISHU_OPENAPI_BASE_URL,
    HEADING_1_BLOCK,
    HEADING_2_BLOCK,
    TEXT_BLOCK,
    FeishuAPIError,
    FeishuOpenAPIClient,
    PublishDocumentSpec,
    append_planned_blocks,
    build_board_block,
    build_text_block,
    find_board_token,
    publish_spec,
    resolve_access_token,
)

DEFAULT_MANIFEST_PATH = Path("docs/feishu_publish_manifest.v2.json")

BITABLE_TEXT_FIELD_TYPE = 1

V2_SUITE_TITLE = "finance-agent 工程文档中台 V2"
ENTRY_DOC_TITLE = "finance-agent 云文档入口"
ARCHITECTURE_DOC_TITLE = "finance-agent 工程文档中台 V2 - 架构流程图"
BITABLE_APP_TITLE = "finance-agent 工程台账 V2"

DIAGRAM_PATHS: tuple[Path, ...] = (
    Path("docs/diagrams/system-architecture.mmd"),
    Path("docs/diagrams/data-flow.mmd"),
    Path("docs/diagrams/backend-pipeline.mmd"),
    Path("docs/diagrams/frontend-page-map.mmd"),
    Path("docs/diagrams/report-artifacts-flow.mmd"),
    Path("docs/diagrams/agent-flow.mmd"),
    Path("docs/diagrams/source-trace-flow.mmd"),
)


class LarkCliOpenAPIClient:
    """OpenAPI client backed by lark-cli's local OAuth token store."""

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = subprocess.run(
            build_lark_cli_api_command(method=method, path=path, json_body=json_body, params=params),
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FeishuAPIError(f"lark-cli {method} {path} failed: {result.stderr.strip() or result.stdout.strip()}")
        try:
            payload = json.loads(result.stdout)
        except ValueError as exc:
            raise FeishuAPIError(f"lark-cli {method} {path} returned non-JSON output") from exc
        code = payload.get("code")
        if code not in (0, None):
            msg = payload.get("msg") or payload.get("message") or payload
            raise FeishuAPIError(f"lark-cli {method} {path} returned code={code}: {msg}")
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def close(self) -> None:
        return None


def build_lark_cli_api_command(
    *,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> list[str]:
    api_path = path if path.startswith("/open-apis/") else f"/open-apis/{path.lstrip('/')}"
    command = ["lark-cli", "api", method.upper(), api_path, "--as", "user"]
    if params:
        command.extend(["--params", json.dumps(params, ensure_ascii=False)])
    if json_body is not None:
        command.extend(["--data", json.dumps(json_body, ensure_ascii=False)])
    return command


@dataclass(frozen=True)
class MarkdownTable:
    source_path: str
    section: str
    header: list[str]
    rows: list[list[str]]


@dataclass(frozen=True)
class BitableTableSpec:
    name: str
    fields: list[str]
    records: list[dict[str, str]]


@dataclass(frozen=True)
class BitablePublishResult:
    app_token: str | None
    url: str | None
    table_ids: dict[str, str]
    record_counts: dict[str, int]
    created_tables: list[str]
    skipped_tables: list[str]
    dry_run: bool


@dataclass(frozen=True)
class WorkspacePublishResult:
    title: str
    entry_doc_url: str | None
    architecture_doc_url: str | None
    bitable_url: str | None
    bitable_tables: dict[str, str]
    bitable_record_counts: dict[str, int]
    bitable_created_tables: list[str]
    bitable_skipped_tables: list[str]
    manifest_path: str | None
    dry_run: bool


def parse_markdown_tables(path: Path) -> list[MarkdownTable]:
    resolved = _resolve_repo_path(path)
    tables: list[MarkdownTable] = []
    section = resolved.stem
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        rows = [_split_markdown_table_row(line) for line in buffer if _is_markdown_table_line(line)]
        buffer = []
        if len(rows) < 2:
            return
        header = [_clean_inline_markdown(cell) for cell in rows[0]]
        body = rows[1:]
        if body and _is_markdown_table_separator(body[0]):
            body = body[1:]
        cleaned_body = [[_clean_inline_markdown(cell) for cell in row] for row in body]
        if header and cleaned_body:
            tables.append(
                MarkdownTable(
                    source_path=resolved.relative_to(PROJECT_ROOT).as_posix(),
                    section=section,
                    header=header,
                    rows=cleaned_body,
                )
            )

    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^#{2,4}\s+(.+?)\s*$", line)
        if heading:
            flush()
            section = _clean_inline_markdown(heading.group(1))
            continue
        if _is_markdown_table_line(line):
            buffer.append(line)
            continue
        flush()
    flush()
    return tables


def build_api_map_table() -> BitableTableSpec:
    records: list[dict[str, str]] = []
    for table in parse_markdown_tables(Path("docs/10_API_MAP.md")):
        for row in table.rows:
            if len(row) < 3:
                continue
            records.append(
                {
                    "分组": table.section,
                    "Method": row[0],
                    "Path": row[1],
                    "页面/用途": row[2],
                    "来源文件": table.source_path,
                }
            )
    return BitableTableSpec(
        name="API_MAP",
        fields=["分组", "Method", "Path", "页面/用途", "来源文件"],
        records=records,
    )


def build_page_matrix_table() -> BitableTableSpec:
    tables = parse_markdown_tables(Path("docs/11_PAGE_RESPONSIBILITY_MATRIX.md"))
    if not tables:
        return BitableTableSpec(name="PAGE_MATRIX", fields=["页面", "当前状态", "目标职责", "来源文件"], records=[])
    table = tables[0]
    fields = [*table.header, "来源文件"]
    records = []
    for row in table.rows:
        record = {field: row[index] if index < len(row) else "" for index, field in enumerate(table.header)}
        record["来源文件"] = table.source_path
        records.append(record)
    return BitableTableSpec(name="PAGE_MATRIX", fields=fields, records=records)


def build_roadmap_table() -> BitableTableSpec:
    records = [
        *extract_roadmap_records(Path("docs/08_BACKEND_ROADMAP.md"), area="后端"),
        *extract_roadmap_records(Path("docs/09_FRONTEND_ROADMAP.md"), area="前端"),
    ]
    return BitableTableSpec(
        name="ROADMAP",
        fields=["领域", "阶段/任务", "摘要", "来源文件", "状态"],
        records=records,
    )


def build_risks_todo_table() -> BitableTableSpec:
    records = extract_risk_records(Path("docs/12_RISKS_AND_TODO.md"))
    return BitableTableSpec(
        name="RISKS_TODO",
        fields=["优先级", "事项", "现状", "风险", "待办", "来源文件"],
        records=records,
    )


def build_data_model_storage_table() -> BitableTableSpec:
    records = extract_data_model_records(Path("docs/04_DATA_MODEL_AND_STORAGE.md"))
    return BitableTableSpec(
        name="DATA_MODEL_STORAGE",
        fields=["分组", "类型", "名称", "说明", "来源文件"],
        records=records,
    )


def build_module_status_table() -> BitableTableSpec:
    records: list[dict[str, str]] = []
    for table in parse_markdown_tables(Path("docs/audit/CURRENT_PROJECT_AUDIT.md")):
        header = table.header
        for row in table.rows:
            record = normalize_status_table_row(table=table, header=header, row=row)
            if record:
                records.append(record)
    return BitableTableSpec(
        name="MODULE_STATUS",
        fields=["分组", "对象", "状态", "证据/用途", "来源文件"],
        records=records,
    )


def extract_roadmap_records(path: Path, *, area: str) -> list[dict[str, str]]:
    resolved = _resolve_repo_path(path)
    records: list[dict[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if not current_title:
            return
        summary = _summarize_section(current_lines)
        records.append(
            {
                "领域": area,
                "阶段/任务": current_title,
                "摘要": summary,
                "来源文件": resolved.relative_to(PROJECT_ROOT).as_posix(),
                "状态": "待规划",
            }
        )
        current_title = None
        current_lines = []

    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            flush()
            current_title = _clean_inline_markdown(heading.group(1))
            continue
        if current_title and line:
            current_lines.append(line)
    flush()
    return records


def extract_risk_records(path: Path) -> list[dict[str, str]]:
    resolved = _resolve_repo_path(path)
    records: list[dict[str, str]] = []
    priority = "未分组"
    current: dict[str, str] | None = None

    def flush() -> None:
        nonlocal current
        if current:
            current["来源文件"] = resolved.relative_to(PROJECT_ROOT).as_posix()
            records.append(current)
        current = None

    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            flush()
            priority = _clean_inline_markdown(heading.group(1))
            continue
        item = re.match(r"^\d+\.\s+(.+?)\s*$", line)
        if item:
            flush()
            current = {
                "优先级": priority,
                "事项": _clean_inline_markdown(item.group(1)),
                "现状": "",
                "风险": "",
                "待办": "",
                "来源文件": "",
            }
            continue
        detail = re.match(r"^-\s*(现状|风险|待办)：\s*(.+?)\s*$", line)
        if current and detail:
            current[detail.group(1)] = _clean_inline_markdown(detail.group(2))
    flush()
    return records


def extract_data_model_records(path: Path) -> list[dict[str, str]]:
    resolved = _resolve_repo_path(path)
    records: list[dict[str, str]] = []
    section = "未分组"
    current_label = ""
    source_path = resolved.relative_to(PROJECT_ROOT).as_posix()

    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            section = _clean_inline_markdown(heading.group(1))
            current_label = ""
            continue
        label = re.match(r"^([^：:]+)[：:]\s*$", line)
        if label:
            current_label = _clean_inline_markdown(label.group(1))
            continue
        item = re.match(r"^-\s+(.+?)\s*$", line)
        if item:
            name = _clean_inline_markdown(item.group(1))
            if not name:
                continue
            records.append(
                {
                    "分组": section,
                    "类型": current_label or "条目",
                    "名称": name,
                    "说明": "",
                    "来源文件": source_path,
                }
            )
    return records


def normalize_status_table_row(*, table: MarkdownTable, header: list[str], row: list[str]) -> dict[str, str] | None:
    if not header or not row:
        return None
    by_name = {name: row[index] if index < len(row) else "" for index, name in enumerate(header)}
    object_value = (
        by_name.get("模块")
        or by_name.get("路由族")
        or by_name.get("页面")
        or by_name.get("文件")
        or by_name.get(header[0], "")
    )
    status_value = by_name.get("状态", "")
    evidence_value = (
        by_name.get("证据")
        or by_name.get("主要页面/用途")
        or by_name.get("API/数据源")
        or by_name.get("主要模型")
        or " / ".join(value for key, value in by_name.items() if key not in {header[0], "状态"} and value)
    )
    if not object_value:
        return None
    return {
        "分组": table.section,
        "对象": object_value,
        "状态": status_value,
        "证据/用途": evidence_value,
        "来源文件": table.source_path,
    }


def build_bitable_specs() -> tuple[BitableTableSpec, ...]:
    return (
        build_api_map_table(),
        build_page_matrix_table(),
        build_roadmap_table(),
        build_risks_todo_table(),
        build_data_model_storage_table(),
        build_module_status_table(),
    )


def publish_bitable(
    *,
    client: Any | None,
    folder_token: str | None,
    dry_run: bool,
    base_url: str,
    app_token: str | None = None,
    existing_table_ids: dict[str, str] | None = None,
) -> BitablePublishResult:
    table_specs = build_bitable_specs()
    record_counts = {table.name: len(table.records) for table in table_specs}
    existing_ids = dict(existing_table_ids or {})
    if dry_run:
        return BitablePublishResult(
            app_token=app_token,
            url=f"{_tenant_doc_base_url(base_url)}/base/{app_token}" if app_token else None,
            table_ids={table.name: existing_ids.get(table.name, "") for table in table_specs},
            record_counts=record_counts,
            created_tables=[table.name for table in table_specs if table.name not in existing_ids],
            skipped_tables=[table.name for table in table_specs if table.name in existing_ids],
            dry_run=True,
        )
    if client is None:
        raise ValueError("client is required unless dry_run=True")
    if not app_token and not folder_token:
        raise ValueError("folder_token is required unless dry_run=True")

    actual_app_token = app_token or create_bitable_app(client=client, name=BITABLE_APP_TITLE, folder_token=folder_token or "")
    table_ids: dict[str, str] = dict(existing_ids)
    created_tables: list[str] = []
    skipped_tables: list[str] = []
    for table_spec in table_specs:
        if table_spec.name in table_ids:
            skipped_tables.append(table_spec.name)
            continue
        table_id = create_bitable_table(client=client, app_token=actual_app_token, table=table_spec)
        table_ids[table_spec.name] = table_id
        created_tables.append(table_spec.name)
        for record in table_spec.records:
            create_bitable_record(client=client, app_token=actual_app_token, table_id=table_id, fields=record)

    return BitablePublishResult(
        app_token=actual_app_token,
        url=f"{_tenant_doc_base_url(base_url)}/base/{actual_app_token}",
        table_ids=table_ids,
        record_counts=record_counts,
        created_tables=created_tables,
        skipped_tables=skipped_tables,
        dry_run=False,
    )


def create_bitable_app(*, client: Any, name: str, folder_token: str) -> str:
    data = client.request(
        "POST",
        "/bitable/v1/apps",
        json_body={"name": name, "folder_token": folder_token},
    )
    app_token = _first_string_by_key(data, ("app_token", "token"))
    if not app_token:
        raise FeishuAPIError(f"create bitable app response does not contain app_token: {data}")
    return app_token


def create_bitable_table(*, client: Any, app_token: str, table: BitableTableSpec) -> str:
    data = client.request(
        "POST",
        f"/bitable/v1/apps/{app_token}/tables",
        json_body={
            "table": {
                "name": table.name,
                "default_view_name": "全部",
                "fields": [
                    {
                        "field_name": field,
                        "type": BITABLE_TEXT_FIELD_TYPE,
                        "ui_type": "Text",
                    }
                    for field in table.fields
                ],
            }
        },
    )
    table_id = _first_string_by_key(data, ("table_id",))
    if not table_id:
        raise FeishuAPIError(f"create bitable table response does not contain table_id: {data}")
    return table_id


def create_bitable_record(
    *,
    client: Any,
    app_token: str,
    table_id: str,
    fields: dict[str, str],
) -> str | None:
    data = client.request(
        "POST",
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        json_body={"fields": fields},
    )
    return _first_string_by_key(data, ("record_id",))


def publish_workspace(
    *,
    client: Any | None,
    folder_token: str | None,
    dry_run: bool,
    base_url: str,
    max_blocks_per_request: int,
    manifest_path: Path | None,
    update_existing: bool = False,
) -> WorkspacePublishResult:
    existing_manifest = load_manifest(manifest_path) if update_existing and manifest_path else {}
    existing_bitable_tables = _manifest_table_ids(existing_manifest)
    existing_app_token = _manifest_string(existing_manifest, "bitable_app_token")
    bitable = publish_bitable(
        client=client,
        folder_token=folder_token,
        dry_run=dry_run,
        base_url=base_url,
        app_token=existing_app_token if update_existing else None,
        existing_table_ids=existing_bitable_tables if update_existing else None,
    )

    if update_existing:
        result = WorkspacePublishResult(
            title=V2_SUITE_TITLE,
            entry_doc_url=_manifest_string(existing_manifest, "entry_doc_url"),
            architecture_doc_url=_manifest_string(existing_manifest, "architecture_doc_url"),
            bitable_url=bitable.url or _manifest_string(existing_manifest, "bitable_url"),
            bitable_tables=bitable.table_ids,
            bitable_record_counts=bitable.record_counts,
            bitable_created_tables=bitable.created_tables,
            bitable_skipped_tables=bitable.skipped_tables,
            manifest_path=str(manifest_path) if manifest_path and not dry_run else None,
            dry_run=dry_run,
        )
        if manifest_path and not dry_run:
            write_manifest(
                path=manifest_path,
                result=result,
                entry_doc_id=_manifest_string(existing_manifest, "entry_doc_id"),
                bitable_app_token=bitable.app_token or existing_app_token,
            )
        return result

    architecture_spec = PublishDocumentSpec(
        title=ARCHITECTURE_DOC_TITLE,
        markdown_paths=(Path("docs/diagrams/DIAGRAMS_INDEX.md"),),
        diagram_paths=DIAGRAM_PATHS,
    )
    architecture = publish_spec(
        spec=architecture_spec,
        folder_token=folder_token,
        dry_run=dry_run,
        client=client,
        base_url=base_url,
        max_blocks_per_request=max_blocks_per_request,
        confirm_overwrite=False,
    )

    entry_doc_id: str | None = None
    entry_doc_url: str | None = None
    if dry_run:
        entry_doc_url = None
    else:
        if client is None:
            raise ValueError("client is required unless dry_run=True")
        if not folder_token:
            raise ValueError("folder_token is required unless dry_run=True")
        entry_doc_id = client.create_document(title=ENTRY_DOC_TITLE, folder_token=folder_token)
        entry_doc_url = f"{_tenant_doc_base_url(base_url)}/docx/{entry_doc_id}"
        create_entry_document(
            client=client,
            document_id=entry_doc_id,
            architecture_doc_url=architecture.url,
            bitable_url=bitable.url,
            max_blocks_per_request=max_blocks_per_request,
        )

    result = WorkspacePublishResult(
        title=V2_SUITE_TITLE,
        entry_doc_url=entry_doc_url,
        architecture_doc_url=architecture.url,
        bitable_url=bitable.url,
        bitable_tables=bitable.table_ids,
        bitable_record_counts=bitable.record_counts,
        bitable_created_tables=bitable.created_tables,
        bitable_skipped_tables=bitable.skipped_tables,
        manifest_path=str(manifest_path) if manifest_path and not dry_run else None,
        dry_run=dry_run,
    )
    if manifest_path and not dry_run:
        write_manifest(path=manifest_path, result=result, entry_doc_id=entry_doc_id, bitable_app_token=bitable.app_token)
    return result


def create_entry_document(
    *,
    client: Any,
    document_id: str,
    architecture_doc_url: str | None,
    bitable_url: str | None,
    max_blocks_per_request: int,
) -> None:
    blocks = [
        build_text_block(HEADING_1_BLOCK, "finance-agent 工程文档中台 V2"),
        build_text_block(TEXT_BLOCK, "这是一套飞书阅读优化试点：说明文档保持短、图表用 Mermaid 小组件、长表进入多维表格。"),
        build_text_block(HEADING_2_BLOCK, "怎么取"),
        build_text_block(TEXT_BLOCK, f"• 架构流程图文档：{architecture_doc_url or '创建后生成'}"),
        build_text_block(TEXT_BLOCK, f"• 工程台账多维表格：{bitable_url or '创建后生成'}"),
        build_text_block(HEADING_2_BLOCK, "内容分工"),
        build_text_block(TEXT_BLOCK, "• Docx：项目定位、主链路、架构流程图、阅读入口。"),
        build_text_block(TEXT_BLOCK, "• Bitable：API 映射、页面职责矩阵、后端/前端改造规划。"),
        build_text_block(TEXT_BLOCK, "• 后续可在 Bitable 上增加状态视图、负责人、优先级、验收进度和筛选看板。"),
        build_text_block(HEADING_2_BLOCK, "固定边界"),
        build_text_block(TEXT_BLOCK, "• finance-agent 是本地可运行、可追溯、可复盘的 XAUUSD/GC 金融研究中台，不是自动交易系统。"),
        build_text_block(TEXT_BLOCK, "• 生产主链：api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output。"),
        build_text_block(TEXT_BLOCK, "• 当前主前端：apps/frontend-web；不恢复 legacy apps/frontend，不把 dashboard.html 当新功能入口。"),
        build_text_block(HEADING_2_BLOCK, "总览图"),
    ]
    append_planned_blocks(
        client=client,
        document_id=document_id,
        parent_block_id=document_id,
        planned_blocks=blocks,
        max_blocks_per_request=max_blocks_per_request,
    )
    append_mermaid_diagram(
        client=client,
        document_id=document_id,
        diagram_path=Path("docs/diagrams/system-architecture.mmd"),
    )


def append_mermaid_diagram(*, client: Any, document_id: str, diagram_path: Path) -> None:
    path = _resolve_repo_path(diagram_path)
    created_blocks = client.create_child_blocks(
        document_id=document_id,
        parent_block_id=document_id,
        blocks=[build_board_block()],
    )
    whiteboard_id = _first_string_by_key(
        created_blocks,
        ("token", "whiteboard_id", "whiteboard_token", "board_id", "board_token"),
    )
    if not whiteboard_id:
        board_block_id = _first_string_by_key(created_blocks, ("block_id",))
        whiteboard_id = find_board_token(client.list_blocks(document_id=document_id), block_id=board_block_id)
    if not whiteboard_id:
        raise FeishuAPIError(f"cannot find whiteboard id from board block response: {created_blocks}")
    client.create_mermaid_node(whiteboard_id=whiteboard_id, mermaid_code=path.read_text(encoding="utf-8").strip())


def write_manifest(
    *,
    path: Path,
    result: WorkspacePublishResult,
    entry_doc_id: str | None,
    bitable_app_token: str | None,
) -> None:
    resolved = _resolve_output_path(path)
    payload = {
        "title": result.title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "entry_doc_id": entry_doc_id,
        "entry_doc_url": result.entry_doc_url,
        "architecture_doc_url": result.architecture_doc_url,
        "bitable_app_token": bitable_app_token,
        "bitable_url": result.bitable_url,
        "bitable_tables": result.bitable_tables,
        "bitable_record_counts": result.bitable_record_counts,
    }
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = _resolve_repo_path(path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be a JSON object: {resolved}")
    return payload


def _manifest_table_ids(manifest: dict[str, Any]) -> dict[str, str]:
    tables = manifest.get("bitable_tables")
    if not isinstance(tables, dict):
        return {}
    return {str(key): str(value) for key, value in tables.items() if value}


def _manifest_string(manifest: dict[str, Any], key: str) -> str | None:
    value = manifest.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _summarize_section(lines: list[str], *, max_chars: int = 320) -> str:
    cleaned: list[str] = []
    for line in lines:
        text = _clean_inline_markdown(line).strip("- ")
        if not text or text in {"目标：", "涉及文件：", "API：", "前端影响：", "验收标准：", "风险："}:
            continue
        cleaned.append(text)
        if len("；".join(cleaned)) >= max_chars:
            break
    summary = "；".join(cleaned)
    return summary[:max_chars]


def _clean_inline_markdown(text: str) -> str:
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", lambda match: match.group(1).strip() or "图片", text)
    cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda match: match.group(1).strip(), cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    return cleaned.strip()


def _is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_table_separator(row: list[str]) -> bool:
    return bool(row) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)


def _resolve_repo_path(path: Path) -> Path:
    resolved = (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"path must stay inside project root: {path}") from exc
    if not resolved.exists():
        raise FileNotFoundError(f"path does not exist: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"path is not a file: {resolved}")
    return resolved


def _resolve_output_path(path: Path) -> Path:
    resolved = (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output path must stay inside project root: {path}") from exc
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _tenant_doc_base_url(openapi_base_url: str) -> str:
    if "larksuite.com" in openapi_base_url:
        return "https://larksuite.com"
    return "https://my.feishu.cn"


def _first_string_by_key(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        for item in value.values():
            found = _first_string_by_key(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_string_by_key(item, keys)
            if found:
                return found
    return None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create Feishu V2 workspace with Docx + Bitable.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned suite without calling Feishu OpenAPI.")
    parser.add_argument("--create-new", action="store_true", help="Required for real V2 creation.")
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Read manifest and append missing V2 Bitable tables into the existing base.",
    )
    parser.add_argument("--folder-token", default=os.getenv("FEISHU_DOCS_FOLDER_TOKEN") or os.getenv("LARK_DOCS_FOLDER_TOKEN"))
    parser.add_argument("--base-url", default=os.getenv("FEISHU_OPENAPI_BASE_URL") or FEISHU_OPENAPI_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-blocks-per-request", type=int, default=50)
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument(
        "--auth-mode",
        choices=["env", "lark-cli"],
        default="env",
        help="Use env access token or lark-cli local OAuth token store for real OpenAPI calls.",
    )
    parser.add_argument(
        "--access-token-env",
        nargs="+",
        default=["FEISHU_ACCESS_TOKEN", "LARK_ACCESS_TOKEN"],
        help="Environment variable names checked for an existing access token.",
    )
    parser.add_argument(
        "--app-id-env",
        nargs="+",
        default=["LARK_APP_ID", "FEISHU_APP_ID"],
        help="Environment variable names checked for app_id when fetching tenant_access_token.",
    )
    parser.add_argument(
        "--app-secret-env",
        nargs="+",
        default=["LARK_APP_SECRET", "FEISHU_APP_SECRET"],
        help="Environment variable names checked for app_secret when fetching tenant_access_token.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.create_new and args.update_existing:
        parser.error("--create-new and --update-existing cannot be used together")
    if not args.dry_run and not (args.create_new or args.update_existing):
        parser.error("real V2 publish requires --create-new or --update-existing")
    if not args.dry_run and args.create_new and not args.folder_token:
        parser.error("--folder-token is required when FEISHU_DOCS_FOLDER_TOKEN/LARK_DOCS_FOLDER_TOKEN is not set")

    client: Any | None = None
    try:
        if not args.dry_run:
            if args.auth_mode == "lark-cli":
                client = LarkCliOpenAPIClient()
            else:
                token = resolve_access_token(args)
                client = FeishuOpenAPIClient(
                    access_token=token,
                    base_url=args.base_url,
                    timeout_seconds=args.timeout_seconds,
                )
        result = publish_workspace(
            client=client,
            folder_token=args.folder_token,
            dry_run=args.dry_run,
            base_url=args.base_url,
            max_blocks_per_request=args.max_blocks_per_request,
            manifest_path=Path(args.manifest_path) if args.manifest_path else None,
            update_existing=args.update_existing,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()

    print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
