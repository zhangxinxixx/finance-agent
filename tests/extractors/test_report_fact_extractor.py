from __future__ import annotations

from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import SourceAssetRef, SourceDocument
from apps.extractors.report_fact_extractor import extract_report_facts


def test_extract_report_facts_reads_prices_macro_and_views():
    report_text = """# 测试日报

1、行情回顾：现货黄金先涨后跌，最高触及4586.61美元/盎司，最终收涨0.74%，报4557.55美元/盎司；现货白银收涨0.14%，报72.83美元/盎司。

2、关键指标：美国非制造业PMI维持在50荣枯线上方，10年期美债收益率持稳，当前数据削弱了降息的紧迫性。

3、观点分享：分析师A表示高油价将继续打压国际现货黄金；分析师B认为情绪指标极端悲观，长期配置机会仍在。

风险提示及免责条款：市场有风险，投资需谨慎。
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

    labels = {fact.label for fact in facts}
    assert "黄金收盘价" in labels
    assert "白银收盘价" in labels
    assert "非制造业PMI" in labels
    assert any(fact.fact_type == "author_view" for fact in facts)


def test_extract_report_facts_reads_weekly_natural_language_views():
    report_text = """# 黄金日线底部确认，上涨窗口锁定6月至7月

从6月开始并持续到7月，两个反复出现的支撑/阻力区将发生交叉，涵盖5000至5200美元区间。

由于10年期美债价格已达到周期低点，收益率因子现在将成为一股顺风，推动金价走高而非走低。

黄金一个潜在的降息周期（RCP）周期高点预计在2026年第四季度至2027年第一季度，目标区间为6500至7000美元。
"""
    document = SourceDocument(
        document_id="jin10-2026-05-31-220787",
        source="jin10_external",
        trade_date="2026-05-31",
        title="黄金日线底部确认，上涨窗口锁定6月至7月",
        category="黄金周报",
        category_code="536",
        source_url="https://svip.jin10.com/news/220787",
        article_id="220787",
        external_report_dir="/tmp/jin10",
        retrieved_at="2026-05-31T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path="/tmp/report.md", sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path="/tmp/meta.json", sha256="", size_bytes=0),
        image_assets=[],
        report_text=report_text,
        source_refs=[],
    )
    parsed = build_parsed_document(document)

    facts = extract_report_facts(parsed)

    labels = {fact.label for fact in facts}
    assert "周报方向判断" in labels
    assert "收益率因子" in labels
    assert any(fact.fact_type == "price" and fact.metadata.get("field") == "gold_target_range" for fact in facts)
