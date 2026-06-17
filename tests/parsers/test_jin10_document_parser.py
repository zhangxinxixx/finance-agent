from __future__ import annotations

from pathlib import Path

from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import SourceAssetRef, SourceDocument


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "jin10" / "2026-05-06" / "报告" / "218330"


def test_build_parsed_document_extracts_paragraph_and_image_blocks():
    report_text = (FIXTURE_ROOT / "report.md").read_text(encoding="utf-8")
    document = SourceDocument(
        document_id="jin10-2026-05-06-218330",
        source="jin10_external",
        trade_date="2026-05-06",
        title="测试标题",
        category="报告",
        category_code="270",
        source_url="https://xnews.jin10.com/details/218330",
        article_id="218330",
        external_report_dir=str(FIXTURE_ROOT),
        retrieved_at="2026-05-06T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path=str(FIXTURE_ROOT / "report.md"), sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path=str(FIXTURE_ROOT / "meta.json"), sha256="", size_bytes=0),
        image_assets=[],
        report_text=report_text,
        source_refs=[],
    )

    parsed = build_parsed_document(document)

    assert parsed.blocks[0].block_type == "paragraph"
    assert "鹰派预期" in parsed.blocks[0].text
    assert any("正文" in block.text for block in parsed.blocks if block.block_type == "paragraph")
    assert any(block.block_type == "image" for block in parsed.blocks)
