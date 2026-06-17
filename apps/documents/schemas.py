from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceAssetRef:
    asset_type: str
    path: str
    sha256: str
    size_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["metadata"]:
            payload.pop("metadata")
        return payload


@dataclass(slots=True)
class SourceDocument:
    document_id: str
    source: str
    trade_date: str
    title: str
    category: str
    category_code: str | None
    source_url: str
    article_id: str
    external_report_dir: str
    retrieved_at: str
    markdown_asset: SourceAssetRef
    meta_asset: SourceAssetRef
    image_assets: list[SourceAssetRef]
    report_text: str
    source_refs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source": self.source,
            "trade_date": self.trade_date,
            "title": self.title,
            "category": self.category,
            "category_code": self.category_code,
            "source_url": self.source_url,
            "article_id": self.article_id,
            "external_report_dir": self.external_report_dir,
            "retrieved_at": self.retrieved_at,
            "markdown_asset": self.markdown_asset.to_dict(),
            "meta_asset": self.meta_asset.to_dict(),
            "image_assets": [asset.to_dict() for asset in self.image_assets],
            "report_text": self.report_text,
            "source_refs": self.source_refs,
        }


@dataclass(slots=True)
class ParsedBlock:
    block_id: str
    block_type: str
    text: str
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["metadata"]:
            payload.pop("metadata")
        if payload["page"] is None:
            payload.pop("page")
        return payload


@dataclass(slots=True)
class ParsedDocument:
    document_id: str
    trade_date: str
    title: str
    source_url: str
    article_id: str
    category: str
    category_code: str | None
    blocks: list[ParsedBlock]
    source_refs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "trade_date": self.trade_date,
            "title": self.title,
            "source_url": self.source_url,
            "article_id": self.article_id,
            "category": self.category,
            "category_code": self.category_code,
            "blocks": [block.to_dict() for block in self.blocks],
            "source_refs": self.source_refs,
        }


@dataclass(slots=True)
class ReportFact:
    fact_id: str
    fact_type: str
    label: str
    value: Any
    source_block_id: str
    source_page: int | None
    evidence_text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["metadata"]:
            payload.pop("metadata")
        return payload


@dataclass(slots=True)
class DailyReportAnalysisSnapshot:
    document_id: str
    trade_date: str
    article_id: str
    title: str
    core_conclusion: str
    market_prices: list[dict[str, Any]]
    logic_chains: list[dict[str, Any]]
    watch_variables: list[dict[str, Any]]
    key_levels: list[dict[str, Any]]
    scenario_matrix: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    facts: list[ReportFact]
    source_refs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "trade_date": self.trade_date,
            "article_id": self.article_id,
            "title": self.title,
            "core_conclusion": self.core_conclusion,
            "market_prices": self.market_prices,
            "logic_chains": self.logic_chains,
            "watch_variables": self.watch_variables,
            "key_levels": self.key_levels,
            "scenario_matrix": self.scenario_matrix,
            "risks": self.risks,
            "facts": [fact.to_dict() for fact in self.facts],
            "source_refs": self.source_refs,
        }


@dataclass(slots=True)
class Jin10DailyAnalysisReport:
    document_id: str
    trade_date: str
    run_id: str
    article_id: str
    title: str
    family: str
    asset: str
    core_conclusion: str
    market_prices: list[dict[str, Any]]
    logic_chains: list[dict[str, Any]]
    watch_variables: list[dict[str, Any]]
    key_levels: list[dict[str, Any]]
    scenario_matrix: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    source_refs: list[dict[str, Any]]
    generated_from: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "trade_date": self.trade_date,
            "run_id": self.run_id,
            "article_id": self.article_id,
            "title": self.title,
            "family": self.family,
            "asset": self.asset,
            "core_conclusion": self.core_conclusion,
            "market_prices": self.market_prices,
            "logic_chains": self.logic_chains,
            "watch_variables": self.watch_variables,
            "key_levels": self.key_levels,
            "scenario_matrix": self.scenario_matrix,
            "risks": self.risks,
            "source_refs": self.source_refs,
            "generated_from": self.generated_from,
        }


@dataclass(slots=True)
class Jin10AgentAnalysisReport:
    document_id: str
    trade_date: str
    run_id: str
    article_id: str
    title: str
    family: str
    asset: str
    source_report_family: str
    source_artifact_refs: list[str]
    one_line_conclusion: str
    provenance: list[str]
    evidence_basis: dict[str, Any]
    market_stage: dict[str, Any]
    logic_chain: list[str]
    key_variables: list[dict[str, Any]]
    gold_analysis: str
    silver_analysis: str
    cross_asset_analysis: dict[str, str]
    key_levels: list[dict[str, Any]]
    scenario_paths: list[dict[str, Any]]
    trading_implications: list[dict[str, Any]]
    risk_points: list[str]
    final_summary: str
    unresolved_items: list[str]
    source_refs: list[dict[str, Any]]
    generated_from: dict[str, Any]
    data_category: str = "external_opinion"

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "trade_date": self.trade_date,
            "run_id": self.run_id,
            "article_id": self.article_id,
            "title": self.title,
            "family": self.family,
            "asset": self.asset,
            "source_report_family": self.source_report_family,
            "source_artifact_refs": self.source_artifact_refs,
            "one_line_conclusion": self.one_line_conclusion,
            "provenance": self.provenance,
            "evidence_basis": self.evidence_basis,
            "market_stage": self.market_stage,
            "logic_chain": self.logic_chain,
            "key_variables": self.key_variables,
            "gold_analysis": self.gold_analysis,
            "silver_analysis": self.silver_analysis,
            "cross_asset_analysis": self.cross_asset_analysis,
            "key_levels": self.key_levels,
            "scenario_paths": self.scenario_paths,
            "trading_implications": self.trading_implications,
            "risk_points": self.risk_points,
            "final_summary": self.final_summary,
            "unresolved_items": self.unresolved_items,
            "source_refs": self.source_refs,
            "generated_from": self.generated_from,
            "data_category": self.data_category,
        }


@dataclass(slots=True)
class Jin10RawArticleReport:
    document_id: str
    trade_date: str
    run_id: str
    article_id: str
    title: str
    family: str
    source_url: str
    article_markdown: str
    charts: list[dict[str, Any]]
    source_refs: list[dict[str, Any]]
    generated_from: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "trade_date": self.trade_date,
            "run_id": self.run_id,
            "article_id": self.article_id,
            "title": self.title,
            "family": self.family,
            "source_url": self.source_url,
            "article_markdown": self.article_markdown,
            "charts": self.charts,
            "source_refs": self.source_refs,
            "generated_from": self.generated_from,
        }
