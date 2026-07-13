from __future__ import annotations

from apps.analysis.jin10.daily_report import build_daily_report_analysis_snapshot
from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import SourceAssetRef, SourceDocument
from apps.extractors.report_fact_extractor import extract_report_facts

def _document() -> SourceDocument:
    report_text = """# 鹰派预期将继续施压金价，但情绪指标暗示长期配置机会已到？

1、行情回顾：现货黄金先涨后跌，最高触及4586.61美元/盎司，最终收涨0.74%，报4557.55美元/盎司；现货白银收涨0.14%，报72.83美元/盎司。

2、关键指标：美国非制造业PMI维持在50荣枯线上方，10年期美债收益率持稳，当前数据削弱了降息的紧迫性。

3、观点分享：分析师A表示高油价将继续打压国际现货黄金；分析师B认为情绪指标极端悲观，长期配置机会仍在。

风险提示及免责条款：市场有风险，投资需谨慎。
"""
    return SourceDocument(
        document_id="jin10-2026-05-06-218330",
        source="jin10_external",
        trade_date="2026-05-06",
        title="鹰派预期将继续施压金价，但情绪指标暗示长期配置机会已到？",
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


def test_build_daily_report_analysis_snapshot_outputs_core_sections():
    parsed = build_parsed_document(_document())
    facts = extract_report_facts(parsed)

    snapshot = build_daily_report_analysis_snapshot(parsed, facts)

    assert snapshot.trade_date == "2026-05-06"
    assert snapshot.market_prices
    assert snapshot.logic_chains
    assert snapshot.watch_variables
    assert snapshot.key_levels
    assert snapshot.scenario_matrix
    assert snapshot.risks
    assert "打压" in snapshot.core_conclusion or "配置机会" in snapshot.core_conclusion


def test_build_daily_report_analysis_snapshot_summarizes_weekly_targets():
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

    snapshot = build_daily_report_analysis_snapshot(parsed, facts)

    assert "5000-5200" in {str(row.get("value")) for row in snapshot.key_levels}
    assert "6500-7000" in {str(row.get("value")) for row in snapshot.key_levels}
    assert "证据不足" not in snapshot.core_conclusion
    assert len(snapshot.core_conclusion) <= 360


def test_weekly_conclusion_keeps_report_classification_separate_from_options_theme():
    report_text = """# 黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成

黄金降息周期高点预计在2027年一季度至二季度，目标区间6500—7000美元。

未来数周黄金价格大概率维持区间震荡，金价持续在4065至4235美元区间运行，期权成交比率回落确认阶段低点。

若要推动金价突破区间，10年期美债收益率需持续下行；下一催化剂是CPI与FOMC。

## 交易商持仓报告（COT）

本次持仓报告统计周期为6月23日至7月7日，黄金期货未平仓合约总量增加1.96万手。多头增仓主力为其他可报告交易商，合计增持1.28万手多头合约。

"""
    document = SourceDocument(
        document_id="jin10-2026-07-11-224284",
        source="jin10_external",
        trade_date="2026-07-11",
        title="黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成-金十数据VIP",
        category="黄金周报",
        category_code="536",
        source_url="https://svip.jin10.com/news/224284",
        article_id="224284",
        external_report_dir="/tmp/jin10",
        retrieved_at="2026-07-11T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path="/tmp/report.md", sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path="/tmp/meta.json", sha256="", size_bytes=0),
        image_assets=[],
        report_text=report_text,
        source_refs=[],
    )

    parsed = build_parsed_document(document)
    snapshot = build_daily_report_analysis_snapshot(parsed, extract_report_facts(parsed))

    assert "报告分类：黄金投资者周报" in snapshot.core_conclusion
    assert "本期主题：黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成" in snapshot.core_conclusion
    assert "周度判断：4065-4235" in snapshot.core_conclusion
    assert "利率/催化" in snapshot.core_conclusion
    assert "持仓验证" in snapshot.core_conclusion
    assert "1.96万手" in snapshot.core_conclusion
    assert "中长期目标：6500-7000" in snapshot.core_conclusion
    assert len(snapshot.core_conclusion) <= 420
