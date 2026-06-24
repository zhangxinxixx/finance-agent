"""Structured analysis summary for Jin10 report assets."""

from __future__ import annotations

from typing import Any

from apps.analysis.jin10.daily_report import build_daily_report_analysis_snapshot
from apps.analysis.jin10.visual_report import build_jin10_daily_analysis_report
from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import SourceAssetRef, SourceDocument
from apps.extractors.report_fact_extractor import extract_report_facts


def build_analysis_index(parsed_index: dict[str, Any]) -> dict[str, Any]:
    reports = []
    for report in parsed_index["reports"]:
        source_document = _source_document_from_parsed(report, parsed_index["source_refs"])
        parsed_document = build_parsed_document(source_document)
        facts = extract_report_facts(parsed_document)
        snapshot = build_daily_report_analysis_snapshot(parsed_document, facts)
        visual = build_jin10_daily_analysis_report(snapshot)
        reports.append(
            {
                "article_id": report["article_id"],
                "date": report["date"],
                "title": report["title"],
                "category": report["category"],
                "category_code": report["category_code"],
                "source_url": report["source_url"],
                "summary_status": "ready" if facts else "evidence_insufficient",
                "summary": snapshot.core_conclusion,
                "page_count": report["page_count"],
                "market_prices": snapshot.market_prices,
                "watch_variables": snapshot.watch_variables,
                "report_family": visual.family,
            }
        )
    return {
        "schema_version": 1,
        "source": parsed_index["source"],
        "as_of": parsed_index["as_of"],
        "reports": reports,
        "source_refs": parsed_index["source_refs"],
        "unavailable_symbols": parsed_index["unavailable_symbols"],
    }


def _source_document_from_parsed(report: dict[str, Any], source_refs: list[dict[str, Any]]) -> SourceDocument:
    markdown_path = report["report_path"]
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
        external_report_dir="",
        retrieved_at="",
        markdown_asset=_asset("report_md", report["report_path"]),
        meta_asset=_asset("meta_json", report["meta_path"]),
        image_assets=[_asset("image", image["path"]) for image in report["images"]],
        report_text=report_text,
        source_refs=[ref for ref in source_refs if ref.get("article_id") == report["article_id"]],
    )


def _asset(asset_type: str, path: str) -> SourceAssetRef:
    return SourceAssetRef(asset_type=asset_type, path=path, sha256="", size_bytes=0)
