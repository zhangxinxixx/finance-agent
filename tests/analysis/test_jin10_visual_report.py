from __future__ import annotations

from apps.analysis.jin10.daily_report import build_daily_report_analysis_snapshot
from apps.analysis.jin10.visual_report import build_jin10_daily_analysis_report
from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import SourceAssetRef, SourceDocument
from apps.extractors.report_fact_extractor import extract_report_facts

def test_build_jin10_visual_report_sets_family_and_run_id():
    report_text = """# 测试日报

1、行情回顾：现货黄金最高触及4586.61美元/盎司，报4557.55美元/盎司；现货白银报72.83美元/盎司。

2、关键指标：美国非制造业PMI维持在50荣枯线上方，10年期美债收益率持稳。

3、观点分享：分析师A表示高油价将继续打压国际现货黄金；分析师B认为长期配置机会仍在。
"""
    document = SourceDocument(
        document_id="jin10-2026-05-06-218330",
        source="jin10_external",
        trade_date="2026-05-06",
        title="测试标题",
        category="报告",
        category_code="270",
        source_url="https://xnews.jin10.com/details/218330",
        article_id="218330",
        external_report_dir="/tmp/jin10",
        retrieved_at="2026-05-06T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path="/tmp/report.md", sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path="/tmp/meta.json", sha256="", size_bytes=0),
        image_assets=[],
        report_text=report_text,
        source_refs=[],
    )
    parsed = build_parsed_document(document)
    facts = extract_report_facts(parsed)
    snapshot = build_daily_report_analysis_snapshot(parsed, facts)

    report = build_jin10_daily_analysis_report(snapshot)

    assert report.family == "jin10_daily_visual"
    assert report.run_id == "218330"
    assert report.asset == "XAUUSD"
