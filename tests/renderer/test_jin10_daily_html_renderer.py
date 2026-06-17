from __future__ import annotations

from apps.documents.schemas import Jin10DailyAnalysisReport
from apps.renderer.html.jin10_daily import render_jin10_daily_html


def test_render_jin10_daily_html_contains_core_sections():
    report = Jin10DailyAnalysisReport(
        document_id="doc-1",
        trade_date="2026-05-06",
        run_id="218330",
        article_id="218330",
        title="测试日报",
        family="jin10_daily_visual",
        asset="XAUUSD",
        core_conclusion="鹰派预期施压，但情绪极端悲观提供长期支撑。",
        market_prices=[{"label": "黄金收盘价", "value": 4557.55}],
        logic_chains=[{"label": "非制造业PMI", "summary": "服务业仍在扩张。"}],
        watch_variables=[{"label": "10年期美债收益率", "status": "watch"}],
        key_levels=[{"label": "黄金最高价", "value": 4586.61}],
        scenario_matrix=[{"scenario": "偏空", "confidence": "medium", "summary": "高利率继续压制金价。"}],
        risks=[{"label": "风险提示", "summary": "市场有风险，投资需谨慎。"}],
        source_refs=[],
        generated_from={"source": "jin10_external"},
    )

    html = render_jin10_daily_html(report)

    assert "<!doctype html>" in html.lower()
    assert "Jin10 黄金每日报告" in html
    assert "黄金收盘价" in html
    assert "偏空" in html
