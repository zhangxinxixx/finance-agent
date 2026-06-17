#!/usr/bin/env python3
"""Publish finance-agent docs to Feishu Docx with Mermaid board widgets.

The built-in Markdown import creates fenced Mermaid as plain code blocks. This
script uses the Docx block API for text and the Board PlantUML API with Mermaid
syntax for diagrams.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FEISHU_OPENAPI_BASE_URL = "https://open.feishu.cn/open-apis"
LARK_OPENAPI_BASE_URL = "https://open.larksuite.com/open-apis"

TEXT_BLOCK = 2
HEADING_1_BLOCK = 3
HEADING_2_BLOCK = 4
HEADING_3_BLOCK = 5
HEADING_4_BLOCK = 6
HEADING_5_BLOCK = 7
HEADING_6_BLOCK = 8
BOARD_BLOCK = 43
TABLE_BLOCK = 31
TABLE_PLAN_KEY = "_markdown_table"
MAX_TABLE_ROWS = 8
TABLE_TOTAL_WIDTH = 940
TABLE_MIN_COLUMN_WIDTH = 120
TABLE_MAX_COLUMN_WIDTH = 460

MERMAID_SYNTAX_TYPE = 2
FLOWCHART_DIAGRAM_TYPE = 0
DEFAULT_STYLE_TYPE = 1


@dataclass(frozen=True)
class PublishDocumentSpec:
    title: str
    markdown_paths: tuple[Path, ...]
    diagram_paths: tuple[Path, ...] = ()
    document_id: str | None = None


@dataclass(frozen=True)
class PublishResult:
    title: str
    document_id: str | None
    url: str | None
    action: str
    markdown_files: list[str]
    diagrams: list[str]
    text_block_count: int
    table_count: int
    board_count: int
    cleared_block_count: int
    dry_run: bool


PROJECT_DOCS_PRESET: tuple[PublishDocumentSpec, ...] = (
    PublishDocumentSpec(
        title="finance-agent 项目现状审计",
        markdown_paths=(
            Path("docs/audit/CURRENT_PROJECT_AUDIT.md"),
            Path("docs/audit/DOCS_SELF_REVIEW.md"),
        ),
    ),
    PublishDocumentSpec(
        title="finance-agent 架构与流程图",
        markdown_paths=(
            Path("docs/README.md"),
            Path("docs/00_PROJECT_OVERVIEW.md"),
            Path("docs/01_ARCHITECTURE.md"),
            Path("docs/02_BACKEND_PIPELINE.md"),
            Path("docs/03_FRONTEND_PAGES.md"),
            Path("docs/04_DATA_MODEL_AND_STORAGE.md"),
            Path("docs/05_AGENT_ARCHITECTURE.md"),
            Path("docs/06_REPORT_SYSTEM.md"),
            Path("docs/07_SOURCE_TRACE_AND_RUN.md"),
            Path("docs/10_API_MAP.md"),
            Path("docs/11_PAGE_RESPONSIBILITY_MATRIX.md"),
            Path("docs/12_RISKS_AND_TODO.md"),
            Path("docs/13_NEWS_DATA_PIPELINE.md"),
            Path("docs/diagrams/DIAGRAMS_INDEX.md"),
        ),
        diagram_paths=(
            Path("docs/diagrams/system-architecture.mmd"),
            Path("docs/diagrams/data-flow.mmd"),
            Path("docs/diagrams/backend-pipeline.mmd"),
            Path("docs/diagrams/frontend-page-map.mmd"),
            Path("docs/diagrams/report-artifacts-flow.mmd"),
            Path("docs/diagrams/agent-flow.mmd"),
            Path("docs/diagrams/source-trace-flow.mmd"),
            Path("docs/diagrams/news-pipeline-flow.mmd"),
        ),
    ),
    PublishDocumentSpec(
        title="finance-agent 改造规划",
        markdown_paths=(
            Path("docs/08_BACKEND_ROADMAP.md"),
            Path("docs/09_FRONTEND_ROADMAP.md"),
        ),
    ),
)

PROJECT_DOCS_EXISTING_DOCUMENT_IDS: dict[str, str] = {
    "finance-agent 项目现状审计": "S3JMdA5uPoSpdkxRwDUchbUkn3d",
    "finance-agent 架构与流程图": "Qijfd0pJsoQtjjxwJSycMthyn0b",
}


class FeishuAPIError(RuntimeError):
    """Raised when Feishu OpenAPI returns an error response."""


class FeishuOpenAPIClient:
    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = FEISHU_OPENAPI_BASE_URL,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        token = access_token.strip()
        if not token:
            raise ValueError("access_token cannot be empty")
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response: httpx.Response | None = None
        for attempt in range(5):
            try:
                response = self._client.request(method, url, headers=self._headers, json=json_body, params=params)
            except httpx.HTTPError as exc:
                raise FeishuAPIError(f"{method} {path} failed: {exc}") from exc
            if response.status_code != 429:
                break
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            time.sleep(retry_after if retry_after is not None else 1.5 * (attempt + 1))

        assert response is not None

        try:
            payload = response.json()
        except ValueError as exc:
            raise FeishuAPIError(f"{method} {path} returned non-JSON HTTP {response.status_code}") from exc

        code = payload.get("code")
        if not (200 <= response.status_code < 300 and code in (0, None)):
            msg = payload.get("msg") or payload.get("message") or response.text
            raise FeishuAPIError(f"{method} {path} returned code={code} http={response.status_code}: {msg}")
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else {}

    def create_document(self, *, title: str, folder_token: str) -> str:
        data = self.request(
            "POST",
            "/docx/v1/documents",
            json_body={"title": title, "folder_token": folder_token},
        )
        document_id = _first_string_by_key(data, ("document_id", "token"))
        if not document_id:
            raise FeishuAPIError(f"create document response does not contain document_id: {data}")
        return document_id

    def create_child_blocks(
        self,
        *,
        document_id: str,
        parent_block_id: str,
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not blocks:
            return []
        data = self.request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children",
            json_body={"children": blocks},
        )
        children = data.get("children")
        return children if isinstance(children, list) else []

    def list_child_blocks(
        self,
        *,
        document_id: str,
        parent_block_id: str,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": page_size, "document_revision_id": -1}
            if page_token:
                params["page_token"] = page_token
            data = self.request(
                "GET",
                f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children",
                params=params,
            )
            items = data.get("items")
            if isinstance(items, list):
                blocks.extend(item for item in items if isinstance(item, dict))
            page_token = data.get("page_token") if isinstance(data.get("page_token"), str) else None
            if not data.get("has_more") or not page_token:
                return blocks

    def delete_child_blocks(
        self,
        *,
        document_id: str,
        parent_block_id: str,
        start_index: int,
        end_index: int,
    ) -> None:
        if end_index <= start_index:
            return
        self.request(
            "DELETE",
            f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children/batch_delete",
            params={"document_revision_id": -1},
            json_body={"start_index": start_index, "end_index": end_index},
        )

    def clear_document(self, *, document_id: str) -> int:
        children = self.list_child_blocks(document_id=document_id, parent_block_id=document_id)
        if children:
            self.delete_child_blocks(
                document_id=document_id,
                parent_block_id=document_id,
                start_index=0,
                end_index=len(children),
            )
        return len(children)

    def list_blocks(self, *, document_id: str, page_size: int = 500) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            data = self.request("GET", f"/docx/v1/documents/{document_id}/blocks", params=params)
            items = data.get("items")
            if isinstance(items, list):
                blocks.extend(item for item in items if isinstance(item, dict))
            page_token = data.get("page_token") if isinstance(data.get("page_token"), str) else None
            if not data.get("has_more") or not page_token:
                return blocks

    def create_mermaid_node(self, *, whiteboard_id: str, mermaid_code: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/board/v1/whiteboards/{whiteboard_id}/nodes/plantuml",
            json_body=build_mermaid_node_payload(mermaid_code),
        )

    def create_table(self, *, document_id: str, parent_block_id: str, rows: list[list[str]]) -> dict[str, Any]:
        normalized = normalize_table_rows(rows)
        row_size = len(normalized)
        column_size = len(normalized[0]) if normalized else 1
        created_blocks = self.create_child_blocks(
            document_id=document_id,
            parent_block_id=parent_block_id,
            blocks=[
                build_table_block(
                    row_size=row_size,
                    column_size=column_size,
                    column_widths=calculate_table_column_widths(normalized),
                )
            ],
        )
        table_block = created_blocks[0] if created_blocks else {}
        cell_ids = extract_table_cell_ids(table_block)
        if len(cell_ids) < row_size * column_size:
            raise FeishuAPIError(f"table response did not contain enough cell ids: {table_block}")

        for row_index, row in enumerate(normalized):
            for col_index, cell_text in enumerate(row):
                if not cell_text:
                    continue
                cell_id = cell_ids[row_index * column_size + col_index]
                self.create_child_blocks(
                    document_id=document_id,
                    parent_block_id=cell_id,
                    blocks=[build_text_block(TEXT_BLOCK, cell_text)],
                )
        return table_block


class LarkCliFeishuOpenAPIClient(FeishuOpenAPIClient):
    """OpenAPI client backed by lark-cli's local OAuth token store."""

    def __init__(self) -> None:
        self.base_url = LARK_OPENAPI_BASE_URL

    def close(self) -> None:
        return None

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


def resolve_access_token(args: argparse.Namespace) -> str:
    direct_token = _get_first_env(args.access_token_env)
    if direct_token:
        return direct_token

    app_id = _get_first_env(args.app_id_env)
    app_secret = _get_first_env(args.app_secret_env)
    if not app_id or not app_secret:
        raise ValueError(
            "Set FEISHU_ACCESS_TOKEN/LARK_ACCESS_TOKEN or app credentials in "
            "LARK_APP_ID/LARK_APP_SECRET or FEISHU_APP_ID/FEISHU_APP_SECRET."
        )

    base_url = args.base_url.rstrip("/")
    response = httpx.post(
        f"{base_url}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=args.timeout_seconds,
    )
    payload = response.json()
    if response.status_code != 200 or payload.get("code") != 0:
        raise FeishuAPIError(f"tenant_access_token request failed: {payload}")
    token = str(payload.get("tenant_access_token") or "").strip()
    if not token:
        raise FeishuAPIError("tenant_access_token response did not contain a token")
    return token


def collect_document_specs(args: argparse.Namespace) -> tuple[PublishDocumentSpec, ...]:
    if args.preset == "project-docs-baseline":
        if args.create_new:
            return PROJECT_DOCS_PRESET
        return attach_existing_document_ids(PROJECT_DOCS_PRESET)

    markdown_paths = tuple(Path(value) for value in args.doc_file)
    diagram_paths = tuple(Path(value) for value in args.diagram)
    if not args.title:
        raise ValueError("--title is required when --preset custom is used")
    if not markdown_paths and not diagram_paths:
        raise ValueError("custom publish requires at least one --doc-file or --diagram")
    return (
        PublishDocumentSpec(
            title=args.title,
            markdown_paths=markdown_paths,
            diagram_paths=diagram_paths,
            document_id=args.document_id,
        ),
    )


def attach_existing_document_ids(specs: tuple[PublishDocumentSpec, ...]) -> tuple[PublishDocumentSpec, ...]:
    bound: list[PublishDocumentSpec] = []
    for spec in specs:
        bound.append(
            PublishDocumentSpec(
                title=spec.title,
                markdown_paths=spec.markdown_paths,
                diagram_paths=spec.diagram_paths,
                document_id=PROJECT_DOCS_EXISTING_DOCUMENT_IDS.get(spec.title),
            )
        )
    return tuple(bound)


def publish_spec(
    *,
    spec: PublishDocumentSpec,
    folder_token: str | None,
    dry_run: bool,
    client: FeishuOpenAPIClient | None,
    base_url: str,
    max_blocks_per_request: int,
    confirm_overwrite: bool,
) -> PublishResult:
    document_id: str | None = spec.document_id
    cleared_blocks = 0
    if not dry_run:
        if client is None:
            raise ValueError("client is required unless dry_run=True")
        if document_id:
            if not confirm_overwrite:
                raise ValueError(
                    f"{spec.title} targets existing document {document_id}; pass --confirm-overwrite to clear and rewrite it."
                )
            cleared_blocks = client.clear_document(document_id=document_id)
        elif not folder_token:
            raise ValueError("folder_token is required unless dry_run=True")
        else:
            document_id = client.create_document(title=spec.title, folder_token=folder_token)

    markdown_files: list[str] = []
    planned_blocks: list[dict[str, Any]] = []
    for relative_path in spec.markdown_paths:
        path = _resolve_repo_path(relative_path)
        markdown_files.append(path.relative_to(PROJECT_ROOT).as_posix())
        planned_blocks.extend(markdown_file_to_blocks(path))

    text_block_count = sum(1 for block in planned_blocks if not is_table_plan(block))
    table_count = sum(1 for block in planned_blocks if is_table_plan(block))

    if dry_run:
        return PublishResult(
            title=spec.title,
            document_id=document_id,
            url=f"{_tenant_doc_base_url(base_url)}/docx/{document_id}" if document_id else None,
            action="update" if document_id else "create",
            markdown_files=markdown_files,
            diagrams=[_resolve_repo_path(path).relative_to(PROJECT_ROOT).as_posix() for path in spec.diagram_paths],
            text_block_count=text_block_count,
            table_count=table_count,
            board_count=len(spec.diagram_paths),
            cleared_block_count=0,
            dry_run=True,
        )

    assert client is not None
    assert document_id is not None
    parent_block_id = document_id
    append_planned_blocks(
        client=client,
        document_id=document_id,
        parent_block_id=parent_block_id,
        planned_blocks=planned_blocks,
        max_blocks_per_request=max_blocks_per_request,
    )

    for diagram_path in spec.diagram_paths:
        path = _resolve_repo_path(diagram_path)
        diagram_title = path.stem
        title_blocks = [
            build_text_block(HEADING_2_BLOCK, diagram_title),
            build_text_block(TEXT_BLOCK, f"Mermaid 图文件：{path.relative_to(PROJECT_ROOT).as_posix()}"),
        ]
        client.create_child_blocks(document_id=document_id, parent_block_id=parent_block_id, blocks=title_blocks)
        created_blocks = client.create_child_blocks(
            document_id=document_id,
            parent_block_id=parent_block_id,
            blocks=[build_board_block()],
        )
        whiteboard_id = _extract_whiteboard_id(created_blocks)
        if not whiteboard_id:
            board_block_id = _first_string_by_key(created_blocks, ("block_id",))
            whiteboard_id = find_board_token(client.list_blocks(document_id=document_id), block_id=board_block_id)
        if not whiteboard_id:
            raise FeishuAPIError(f"cannot find whiteboard id from board block response: {created_blocks}")
        client.create_mermaid_node(whiteboard_id=whiteboard_id, mermaid_code=path.read_text(encoding="utf-8").strip())

    url = f"{_tenant_doc_base_url(base_url)}/docx/{document_id}"
    return PublishResult(
        title=spec.title,
        document_id=document_id,
        url=url,
        action="update" if spec.document_id else "create",
        markdown_files=markdown_files,
        diagrams=[_resolve_repo_path(path).relative_to(PROJECT_ROOT).as_posix() for path in spec.diagram_paths],
        text_block_count=text_block_count,
        table_count=table_count,
        board_count=len(spec.diagram_paths),
        cleared_block_count=cleared_blocks,
        dry_run=False,
    )


def markdown_file_to_blocks(path: Path) -> list[dict[str, Any]]:
    blocks = [build_text_block(HEADING_1_BLOCK, path.relative_to(PROJECT_ROOT).as_posix())]
    blocks.extend(markdown_to_lark_blocks(path.read_text(encoding="utf-8")))
    return blocks


def markdown_to_lark_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    code_buffer: list[str] | None = None
    table_buffer: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(build_text_block(TEXT_BLOCK, _clean_inline_markdown(" ".join(part.strip() for part in paragraph).strip())))
            paragraph.clear()

    def flush_code_buffer() -> None:
        nonlocal code_buffer
        if code_buffer is not None:
            code = "\n".join(code_buffer).strip()
            if code:
                blocks.append(build_text_block(TEXT_BLOCK, f"```\n{code}\n```"))
            code_buffer = None

    def flush_table_buffer() -> None:
        if table_buffer:
            blocks.extend(markdown_table_to_blocks(table_buffer))
            table_buffer.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            if code_buffer is None:
                flush_paragraph()
                flush_table_buffer()
                code_buffer = []
            else:
                flush_code_buffer()
            continue
        if code_buffer is not None:
            code_buffer.append(line)
            continue

        if _is_markdown_table_line(line):
            flush_paragraph()
            table_buffer.append(line)
            continue

        flush_table_buffer()

        if not line.strip():
            flush_paragraph()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            flush_paragraph()
            block_type = min(HEADING_1_BLOCK + len(heading.group(1)) - 1, HEADING_6_BLOCK)
            blocks.append(build_text_block(block_type, _clean_inline_markdown(heading.group(2))))
            continue

        list_item = re.match(r"^\s*((?:[-*+])|\d+\.)\s+(.+?)\s*$", line)
        if list_item:
            flush_paragraph()
            marker = "•" if list_item.group(1) in {"-", "*", "+"} else list_item.group(1)
            blocks.append(build_text_block(TEXT_BLOCK, f"{marker} {_clean_inline_markdown(list_item.group(2))}"))
            continue

        paragraph.append(line)

    flush_code_buffer()
    flush_table_buffer()
    flush_paragraph()
    return [block for block in blocks if is_table_plan(block) or _block_text_content(block)]


def markdown_table_to_blocks(lines: list[str]) -> list[dict[str, Any]]:
    rows = [_split_markdown_table_row(line) for line in lines if _is_markdown_table_line(line)]
    if not rows:
        return []

    header = [_clean_inline_markdown(cell) for cell in rows[0]]
    body = rows[1:]
    if body and _is_markdown_table_separator(body[0]):
        body = body[1:]

    cleaned_body = [[_clean_inline_markdown(cell) for cell in row] for row in body]
    if not cleaned_body:
        return [build_table_plan([header])]

    blocks: list[dict[str, Any]] = []
    chunk_size = max(1, MAX_TABLE_ROWS - 1)
    for index in range(0, len(cleaned_body), chunk_size):
        blocks.append(build_table_plan([header, *cleaned_body[index : index + chunk_size]]))
    return blocks


def append_planned_blocks(
    *,
    client: FeishuOpenAPIClient,
    document_id: str,
    parent_block_id: str,
    planned_blocks: list[dict[str, Any]],
    max_blocks_per_request: int,
) -> None:
    pending: list[dict[str, Any]] = []

    def flush_pending() -> None:
        if pending:
            client.create_child_blocks(
                document_id=document_id,
                parent_block_id=parent_block_id,
                blocks=list(pending),
            )
            pending.clear()

    for block in planned_blocks:
        if is_table_plan(block):
            flush_pending()
            client.create_table(
                document_id=document_id,
                parent_block_id=parent_block_id,
                rows=table_plan_rows(block),
            )
            continue
        pending.append(block)
        if len(pending) >= max_blocks_per_request:
            flush_pending()

    flush_pending()


def build_table_plan(rows: list[list[str]]) -> dict[str, Any]:
    normalized = normalize_table_rows(rows)
    return {TABLE_PLAN_KEY: {"rows": normalized}}


def is_table_plan(block: dict[str, Any]) -> bool:
    return TABLE_PLAN_KEY in block


def table_plan_rows(block: dict[str, Any]) -> list[list[str]]:
    payload = block.get(TABLE_PLAN_KEY)
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    return [[str(cell) for cell in row] for row in rows if isinstance(row, list)]


def normalize_table_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned_rows = [[str(cell).strip() for cell in row] for row in rows if row]
    if not cleaned_rows:
        return [[""]]
    column_size = max(len(row) for row in cleaned_rows)
    return [row + [""] * (column_size - len(row)) for row in cleaned_rows]


def _is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_markdown_table_separator(row: list[str]) -> bool:
    return bool(row) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)


def _clean_inline_markdown(text: str) -> str:
    cleaned = re.sub(
        r"!\[([^\]]*)\]\([^)]+\)",
        lambda match: f"图片：{match.group(1).strip()}" if match.group(1).strip() else "图片",
        text,
    )
    cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda match: match.group(1).strip(), cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    return cleaned.strip()


def build_text_block(block_type: int, content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise ValueError("text block content cannot be empty")
    field_name = _text_field_name(block_type)
    return {
        "block_type": block_type,
        field_name: {
            "elements": [
                {
                    "text_run": {
                        "content": text,
                        "text_element_style": {},
                    }
                }
            ],
            "style": {},
        },
    }


def build_board_block() -> dict[str, Any]:
    return {"block_type": BOARD_BLOCK, "board": {}}


def build_table_block(
    *,
    row_size: int,
    column_size: int,
    column_widths: list[int] | None = None,
) -> dict[str, Any]:
    if row_size <= 0 or column_size <= 0:
        raise ValueError("table row_size and column_size must be positive")
    property_payload: dict[str, Any] = {
        "row_size": row_size,
        "column_size": column_size,
    }
    if column_widths:
        property_payload["column_width"] = column_widths[:column_size]
    return {
        "block_type": TABLE_BLOCK,
        "table": {
            "property": property_payload
        },
    }


def calculate_table_column_widths(rows: list[list[str]]) -> list[int]:
    normalized = normalize_table_rows(rows)
    column_size = len(normalized[0]) if normalized else 1
    weights: list[int] = []
    for col_index in range(column_size):
        max_len = max(_display_width(row[col_index]) for row in normalized)
        weights.append(max(8, max_len))

    raw_widths = [
        min(TABLE_MAX_COLUMN_WIDTH, max(TABLE_MIN_COLUMN_WIDTH, 72 + weight * 8))
        for weight in weights
    ]
    total = sum(raw_widths)
    if total <= TABLE_TOTAL_WIDTH:
        return raw_widths

    scalable_total = sum(width - TABLE_MIN_COLUMN_WIDTH for width in raw_widths)
    if scalable_total <= 0:
        return raw_widths
    overflow = total - TABLE_TOTAL_WIDTH
    scaled: list[int] = []
    for width in raw_widths:
        reducible = width - TABLE_MIN_COLUMN_WIDTH
        reduction = int(round(overflow * (reducible / scalable_total)))
        scaled.append(max(TABLE_MIN_COLUMN_WIDTH, width - reduction))
    return scaled


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def extract_table_cell_ids(table_block: dict[str, Any]) -> list[str]:
    cells = table_block.get("table", {}).get("cells")
    if isinstance(cells, list):
        return [cell for cell in cells if isinstance(cell, str) and cell.strip()]
    return _strings_by_key(table_block, ("cell_id", "block_id"))


def build_mermaid_node_payload(mermaid_code: str) -> dict[str, Any]:
    code = mermaid_code.strip()
    if not code:
        raise ValueError("mermaid_code cannot be empty")
    return {
        "syntax_type": MERMAID_SYNTAX_TYPE,
        "diagram_type": FLOWCHART_DIAGRAM_TYPE,
        "style_type": DEFAULT_STYLE_TYPE,
        "plant_uml_code": code,
    }


def _text_field_name(block_type: int) -> str:
    if block_type == TEXT_BLOCK:
        return "text"
    if HEADING_1_BLOCK <= block_type <= HEADING_6_BLOCK:
        return f"heading{block_type - HEADING_1_BLOCK + 1}"
    raise ValueError(f"unsupported text block_type: {block_type}")


def _block_text_content(block: dict[str, Any]) -> str:
    field_name = _text_field_name(int(block["block_type"]))
    elements = block.get(field_name, {}).get("elements", [])
    if not elements:
        return ""
    return str(elements[0].get("text_run", {}).get("content") or "")


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


def _get_first_env(names: Iterable[str]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return min(parsed, 15.0)


def _chunked(values: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for index in range(0, len(values), size):
        yield values[index : index + size]


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


def _strings_by_key(value: Any, keys: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key in keys:
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                found.append(item.strip())
        for item in value.values():
            found.extend(_strings_by_key(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_strings_by_key(item, keys))
    return found


def _extract_whiteboard_id(created_blocks: list[dict[str, Any]]) -> str | None:
    return _first_string_by_key(
        created_blocks,
        (
            "token",
            "whiteboard_id",
            "whiteboard_token",
            "board_id",
            "board_token",
        ),
    )


def find_board_token(blocks: list[dict[str, Any]], *, block_id: str | None) -> str | None:
    for block in blocks:
        if int(block.get("block_type") or 0) != BOARD_BLOCK:
            continue
        if block_id and block.get("block_id") != block_id:
            continue
        token = block.get("token")
        if isinstance(token, str) and token.strip():
            return token.strip()
    return None


def _tenant_doc_base_url(openapi_base_url: str) -> str:
    if "larksuite.com" in openapi_base_url:
        return "https://larksuite.com"
    return "https://my.feishu.cn"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish docs to Feishu Docx with Mermaid board widgets.")
    parser.add_argument("--preset", choices=["project-docs-baseline", "custom"], default="project-docs-baseline")
    parser.add_argument("--title", help="Custom document title. Required for --preset custom.")
    parser.add_argument("--doc-file", action="append", default=[], help="Markdown file for --preset custom.")
    parser.add_argument("--diagram", action="append", default=[], help="Mermaid .mmd file for --preset custom.")
    parser.add_argument("--document-id", help="Existing Feishu docx document_id for --preset custom update mode.")
    parser.add_argument(
        "--create-new",
        action="store_true",
        help="Create new documents instead of updating the fixed project-docs-baseline document IDs.",
    )
    parser.add_argument(
        "--confirm-overwrite",
        action="store_true",
        help="Required for non-dry-run updates of existing document IDs; clears and rewrites document content.",
    )
    parser.add_argument("--folder-token", default=os.getenv("FEISHU_DOCS_FOLDER_TOKEN") or os.getenv("LARK_DOCS_FOLDER_TOKEN"))
    parser.add_argument("--base-url", default=os.getenv("FEISHU_OPENAPI_BASE_URL") or FEISHU_OPENAPI_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-blocks-per-request", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true", help="Print planned docs without calling Feishu OpenAPI.")
    parser.add_argument(
        "--auth-mode",
        choices=["env", "lark-cli"],
        default="env",
        help="Use env access token/app credentials or lark-cli local OAuth token store for real OpenAPI calls.",
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

    try:
        specs = collect_document_specs(args)
        client: FeishuOpenAPIClient | None = None
        if not args.dry_run:
            if not args.folder_token and any(spec.document_id is None for spec in specs):
                parser.error("--folder-token is required when FEISHU_DOCS_FOLDER_TOKEN/LARK_DOCS_FOLDER_TOKEN is not set")
            if args.auth_mode == "lark-cli":
                client = LarkCliFeishuOpenAPIClient()
            else:
                token = resolve_access_token(args)
                client = FeishuOpenAPIClient(
                    access_token=token,
                    base_url=args.base_url,
                    timeout_seconds=args.timeout_seconds,
                )

        results: list[PublishResult] = []
        try:
            for spec in specs:
                results.append(
                    publish_spec(
                        spec=spec,
                        folder_token=args.folder_token,
                        dry_run=args.dry_run,
                        client=client,
                        base_url=args.base_url,
                        max_blocks_per_request=args.max_blocks_per_request,
                        confirm_overwrite=args.confirm_overwrite,
                    )
                )
        finally:
            if client is not None:
                client.close()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = [dataclasses.asdict(result) for result in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
