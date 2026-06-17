"""Normalize Jin10 raw asset refs into parsed report metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import SourceAssetRef, SourceDocument
from apps.parsers.jin10.report_image_parser import parse_report_images

def build_parsed_index(raw_index: dict[str, Any]) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, Any]] = {}
    for report in raw_index["reports"]:
        parsed_report, report_artifacts = _parse_report(report)
        reports.append(parsed_report)
        artifacts[report["article_id"]] = report_artifacts
    return {
        "schema_version": 1,
        "source": raw_index["source"],
        "as_of": raw_index["as_of"],
        "reports": reports,
        "source_refs": raw_index["source_refs"],
        "unavailable_symbols": raw_index["unavailable_symbols"],
        "artifacts": artifacts,
    }


def _parse_report(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    meta_path = report["meta_json"]["path"]
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    markdown_text = Path(report["report_md"]["path"]).read_text(encoding="utf-8")
    artifacts = parse_report_images(
        article_id=report["article_id"],
        title=report["title"],
        published_at=meta.get("published_at"),
        image_entries=report["images"],
    )
    parse_status = artifacts["parse_status"]
    parsed_body_markdown = str(artifacts.get("body_markdown") or "").strip()
    use_structured_markdown = bool(
        parse_status.get("recognition_mode") == "vlm" and parsed_body_markdown
    ) or bool(artifacts["report_structured"]["sections"])
    source_document = _build_source_document(
        report,
        report_text=parsed_body_markdown if use_structured_markdown else markdown_text,
    )
    parsed_document = build_parsed_document(source_document)
    images = [
        {
            "file": image["file"],
            "seq": image.get("seq"),
            "path": image["path"],
            "size_bytes": image["size_bytes"],
            "sha256": image["sha256"],
            "width": image.get("width"),
            "height": image.get("height"),
        }
        for image in report["images"]
    ]
    return {
        "article_id": report["article_id"],
        "date": report["date"],
        "title": report["title"],
        "category": report["category"],
        "category_code": report["category_code"],
        "source_url": report["source_url"],
        "page_count": len(images),
        "parser_version": artifacts["parse_status"]["parser_version"],
        "parser_run_id": artifacts["parse_status"]["parser_run_id"],
        "parse_status": artifacts["parse_status"]["status"],
        "vlm_status": artifacts["parse_status"].get("vision_markdown_status"),
        "section_count": artifacts["parse_status"]["section_count"],
        "figure_count": artifacts["parse_status"]["figures_total"],
        "meta_path": report["meta_json"]["path"],
        "report_path": report["report_md"]["path"],
        "images": images,
        "sections": artifacts["report_structured"]["sections"],
        "figures": artifacts["figures"]["figures"],
        "artifacts": {
            "vision_markdown": artifacts.get("vision_markdown"),
            "vision_layout": artifacts.get("vision_layout"),
        },
        "blocks": [block.to_dict() for block in parsed_document.blocks],
        "body_text": source_document.report_text,
    }, artifacts


def _build_source_document(report: dict[str, Any], *, report_text: str | None = None) -> SourceDocument:
    if report_text is None:
        markdown_path = report["report_md"]["path"]
        with open(markdown_path, encoding="utf-8") as handle:
            report_text = handle.read()
    return SourceDocument(
        document_id=f"jin10-{report['date']}-{report['article_id']}",
        source="jin10_external",
        trade_date=report["date"],
        title=report["title"],
        category=report["category"],
        category_code=report["category_code"],
        source_url=report["source_url"],
        article_id=report["article_id"],
        external_report_dir=report["external_report_dir"],
        retrieved_at=report["retrieved_at"],
        markdown_asset=_asset_from_raw(report["report_md"]),
        meta_asset=_asset_from_raw(report["meta_json"]),
        image_assets=[_asset_from_raw(image) for image in report["images"]],
        report_text=report_text,
        source_refs=[],
    )

def _asset_from_raw(raw: dict[str, Any]) -> SourceAssetRef:
    metadata = {key: raw[key] for key in ("file", "seq", "width", "height") if key in raw and raw[key] is not None}
    return SourceAssetRef(
        asset_type=raw["asset_type"],
        path=raw["path"],
        sha256=raw["sha256"],
        size_bytes=raw["size_bytes"],
        metadata=metadata,
    )
