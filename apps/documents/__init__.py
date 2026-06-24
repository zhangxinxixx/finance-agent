"""Shared document models for source-backed report ingestion."""

from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import (
    DailyReportAnalysisSnapshot,
    Jin10DailyAnalysisReport,
    ParsedBlock,
    ParsedDocument,
    ReportFact,
    SourceAssetRef,
    SourceDocument,
)

__all__ = [
    "SourceAssetRef",
    "SourceDocument",
    "ParsedBlock",
    "ParsedDocument",
    "ReportFact",
    "DailyReportAnalysisSnapshot",
    "Jin10DailyAnalysisReport",
    "build_parsed_document",
]
