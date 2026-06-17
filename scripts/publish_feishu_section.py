#!/usr/bin/env python3
"""Publish a bounded section into an existing Feishu Docx document.

Unlike ``publish_feishu_docs.py``, this script does not clear the whole
document. It maintains a section delimited by stable marker blocks:

    [[finance-agent-section:start:<anchor>]]
    ... generated blocks and Mermaid boards ...
    [[finance-agent-section:end:<anchor>]]

If the section exists, only that marker range is deleted and appended again.
If the section does not exist, it is appended to the end of the document.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.publish_feishu_docs import (  # noqa: E402
    FEISHU_OPENAPI_BASE_URL,
    HEADING_2_BLOCK,
    LarkCliFeishuOpenAPIClient,
    FeishuAPIError,
    FeishuOpenAPIClient,
    append_planned_blocks,
    build_board_block,
    build_text_block,
    find_board_token,
    markdown_file_to_blocks,
    resolve_access_token,
    _extract_whiteboard_id,
    _first_string_by_key,
    _resolve_repo_path,
    _tenant_doc_base_url,
)


@dataclass(frozen=True)
class SectionPublishResult:
    document_id: str
    url: str
    anchor: str
    action: str
    markdown_files: list[str]
    diagrams: list[str]
    text_block_count: int
    table_count: int
    board_count: int
    replaced_block_count: int
    dry_run: bool

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def marker_text(anchor: str, kind: str) -> str:
    clean_anchor = anchor.strip()
    if not clean_anchor:
        raise ValueError("anchor cannot be empty")
    if kind not in {"start", "end"}:
        raise ValueError("kind must be start or end")
    return f"[[finance-agent-section:{kind}:{clean_anchor}]]"


def find_section_range(children: list[dict[str, Any]], *, anchor: str) -> tuple[int, int] | None:
    start_marker = marker_text(anchor, "start")
    end_marker = marker_text(anchor, "end")
    start_index: int | None = None
    end_index: int | None = None
    for index, block in enumerate(children):
        text = extract_block_text(block)
        if text == start_marker:
            start_index = index
        elif text == end_marker and start_index is not None:
            end_index = index
            break
    if start_index is None and end_index is None:
        return None
    if start_index is None or end_index is None or end_index <= start_index:
        raise ValueError(f"partial or invalid section markers for anchor={anchor}")
    return (start_index, end_index + 1)


def extract_block_text(block: dict[str, Any]) -> str:
    block_type = int(block.get("block_type") or 0)
    field_name = "text" if block_type == 2 else f"heading{block_type - 2}"
    field = block.get(field_name)
    elements = field.get("elements") if isinstance(field, dict) else None
    if not isinstance(elements, list):
        return ""
    parts: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        text_run = element.get("text_run")
        if isinstance(text_run, dict):
            content = text_run.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "".join(parts).strip()


def build_section_blocks(*, anchor: str, markdown_paths: tuple[Path, ...]) -> tuple[list[dict[str, Any]], list[str]]:
    blocks = [build_text_block(HEADING_2_BLOCK, marker_text(anchor, "start"))]
    markdown_files: list[str] = []
    for relative_path in markdown_paths:
        path = _resolve_repo_path(relative_path)
        markdown_files.append(path.relative_to(PROJECT_ROOT).as_posix())
        blocks.extend(markdown_file_to_blocks(path))
    blocks.append(build_text_block(HEADING_2_BLOCK, marker_text(anchor, "end")))
    return blocks, markdown_files


def publish_section(
    *,
    document_id: str,
    anchor: str,
    markdown_paths: tuple[Path, ...],
    diagram_paths: tuple[Path, ...],
    dry_run: bool,
    client: FeishuOpenAPIClient | None,
    base_url: str,
    max_blocks_per_request: int,
) -> SectionPublishResult:
    section_blocks, markdown_files = build_section_blocks(anchor=anchor, markdown_paths=markdown_paths)
    diagram_files = [_resolve_repo_path(path).relative_to(PROJECT_ROOT).as_posix() for path in diagram_paths]
    text_block_count = sum(1 for block in section_blocks if "_markdown_table" not in block)
    table_count = sum(1 for block in section_blocks if "_markdown_table" in block)
    replaced_block_count = 0
    action = "append"

    if not dry_run:
        if client is None:
            raise ValueError("client is required unless dry_run=True")
        children = client.list_child_blocks(document_id=document_id, parent_block_id=document_id)
        section_range = find_section_range(children, anchor=anchor)
        if section_range is not None:
            start_index, end_index = section_range
            client.delete_child_blocks(
                document_id=document_id,
                parent_block_id=document_id,
                start_index=start_index,
                end_index=end_index,
            )
            replaced_block_count = end_index - start_index
            action = "replace"

        append_planned_blocks(
            client=client,
            document_id=document_id,
            parent_block_id=document_id,
            planned_blocks=section_blocks[:-1],
            max_blocks_per_request=max_blocks_per_request,
        )
        append_diagrams(
            client=client,
            document_id=document_id,
            diagram_paths=diagram_paths,
        )
        append_planned_blocks(
            client=client,
            document_id=document_id,
            parent_block_id=document_id,
            planned_blocks=section_blocks[-1:],
            max_blocks_per_request=max_blocks_per_request,
        )

    return SectionPublishResult(
        document_id=document_id,
        url=f"{_tenant_doc_base_url(base_url)}/docx/{document_id}",
        anchor=anchor,
        action=action,
        markdown_files=markdown_files,
        diagrams=diagram_files,
        text_block_count=text_block_count,
        table_count=table_count,
        board_count=len(diagram_paths),
        replaced_block_count=replaced_block_count,
        dry_run=dry_run,
    )


def append_diagrams(
    *,
    client: FeishuOpenAPIClient,
    document_id: str,
    diagram_paths: tuple[Path, ...],
) -> None:
    for diagram_path in diagram_paths:
        path = _resolve_repo_path(diagram_path)
        diagram_title = path.stem
        client.create_child_blocks(
            document_id=document_id,
            parent_block_id=document_id,
            blocks=[
                build_text_block(HEADING_2_BLOCK, diagram_title),
                build_text_block(2, f"Mermaid 图文件：{path.relative_to(PROJECT_ROOT).as_posix()}"),
            ],
        )
        created_blocks = client.create_child_blocks(
            document_id=document_id,
            parent_block_id=document_id,
            blocks=[build_board_block()],
        )
        whiteboard_id = _extract_whiteboard_id(created_blocks)
        if not whiteboard_id:
            board_block_id = _first_string_by_key(created_blocks, ("block_id",))
            whiteboard_id = find_board_token(client.list_blocks(document_id=document_id), block_id=board_block_id)
        if not whiteboard_id:
            raise FeishuAPIError(f"cannot find whiteboard id from board block response: {created_blocks}")
        client.create_mermaid_node(whiteboard_id=whiteboard_id, mermaid_code=path.read_text(encoding="utf-8").strip())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish one bounded section into an existing Feishu Docx document.")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--anchor", required=True)
    parser.add_argument("--doc-file", action="append", default=[], help="Markdown file to publish inside the section.")
    parser.add_argument("--diagram", action="append", default=[], help="Mermaid .mmd file to append after the section.")
    parser.add_argument("--base-url", default=os.getenv("FEISHU_OPENAPI_BASE_URL") or FEISHU_OPENAPI_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-blocks-per-request", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--auth-mode",
        choices=["env", "lark-cli"],
        default="env",
        help="Use env access token/app credentials or lark-cli local OAuth token store for real OpenAPI calls.",
    )
    parser.add_argument("--access-token-env", nargs="+", default=["FEISHU_ACCESS_TOKEN", "LARK_ACCESS_TOKEN"])
    parser.add_argument("--app-id-env", nargs="+", default=["LARK_APP_ID", "FEISHU_APP_ID"])
    parser.add_argument("--app-secret-env", nargs="+", default=["LARK_APP_SECRET", "FEISHU_APP_SECRET"])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if not args.doc_file and not args.diagram:
        parser.error("at least one --doc-file or --diagram is required")

    client: FeishuOpenAPIClient | None = None
    try:
        if not args.dry_run:
            if args.auth_mode == "lark-cli":
                client = LarkCliFeishuOpenAPIClient()
            else:
                token = resolve_access_token(args)
                client = FeishuOpenAPIClient(
                    access_token=token,
                    base_url=args.base_url,
                    timeout_seconds=args.timeout_seconds,
                )
        result = publish_section(
            document_id=args.document_id,
            anchor=args.anchor,
            markdown_paths=tuple(Path(value) for value in args.doc_file),
            diagram_paths=tuple(Path(value) for value in args.diagram),
            dry_run=args.dry_run,
            client=client,
            base_url=args.base_url,
            max_blocks_per_request=args.max_blocks_per_request,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
