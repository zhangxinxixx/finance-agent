from __future__ import annotations

import json
from pathlib import Path

from apps.renderer.markdown.daily_brief import (
    archive_daily_brief,
    render_daily_brief_markdown,
    render_daily_brief_payload,
)


def _snapshot(*, report_mode: str = "hybrid", should_generate: bool = True) -> dict[str, object]:
    return {
        "date": "2026-06-12",
        "run_id": "run-news",
        "report_mode": report_mode,
        "should_generate": should_generate,
        "one_line_inputs": [
            "中东风险推动油价和通胀预期变化",
            "能源推升通胀数据，美联储已难兑现宽松。黄金动量仍为负。",
        ]
        if should_generate
        else [],
        "core_events": [
            {
                "event_id": "evt-hormuz",
                "event_type": "hormuz_risk",
                "what_happened": "中东风险推动油价和通胀预期变化",
                "source_confidence": "single_source",
                "risk_level": "high",
                "impact_path": "oil_to_inflation_to_rates",
                "gold_impact": "bearish",
                "pricing_status": "partially_priced",
                "asset_tags": ["XAUUSD", "WTI", "US10Y"],
            }
        ]
        if should_generate
        else [],
        "key_articles": [
            {
                "headline": "能源推升通胀数据，美联储已难兑现宽松",
                "article_class": "gold_macro_market_reference",
                "source_confidence": "report_derived",
                "source_url": "https://xnews.jin10.com/details/221688",
                "access_status": "readable",
                "key_points": ["黄金乐观情绪被清除", "收复4500是第一道槛"],
                "analysis_summary": "这是一条黄金主线重点分析。",
                "detail_artifacts": {"image_asset_count": 2, "vlm_insight_count": 1},
            }
        ]
        if should_generate
        else [],
        "market_reactions": [
            {
                "event_id": "evt-hormuz",
                "window": "30m",
                "asset": "WTI",
                "direction": "up",
                "pct_change": 1.2,
                "threshold_hit": True,
                "pricing_status": "partially_priced",
            }
        ]
        if should_generate
        else [],
        "key_levels": {"mentioned_levels": [4500]},
        "scenario_inputs": [{"type": "risk_point", "text": "若油价反弹，通胀压力重新压制黄金。"}]
        if should_generate
        else [],
        "risk_flags": ["high_risk_event", "verification_risk"] if should_generate else [],
        "source_refs": [
            {"source": "reuters", "source_ref": "wire:1", "url": "https://example.com/wire"},
            {"source": "jin10_feishu", "source_ref": "msg:1"},
        ],
        "quality_flags": ["single_source_verification_required"] if should_generate else ["no_actionable_inputs"],
    }


def test_render_daily_brief_markdown_contains_fixed_sections_and_lineage() -> None:
    markdown = render_daily_brief_markdown(_snapshot())

    assert markdown.startswith("# 每日市场快讯")
    for section in [
        "## 一句话结论",
        "## 分析溯源 / 数据来源",
        "## 今日市场状态总览",
        "## 今日为什么变动",
        "## 为什么还不能确认趋势",
        "## 阶段判断更新",
        "## 关键位",
        "## 三条路径推演",
        "## 操作层理解",
        "## 最终综合判断",
    ]:
        assert section in markdown
    assert "report_mode: hybrid" in markdown
    assert "source_confidence: single_source" in markdown
    assert "source_confidence: report_derived" in markdown
    assert "single_source_verification_required" in markdown
    assert "4500" in markdown
    assert "source: reuters" in markdown
    assert "source_ref: msg:1" in markdown
    assert "黄金影响评估为利空" in markdown
    assert "市场处于部分定价状态" in markdown
    assert "已获行情阈值确认" in markdown


def test_render_daily_brief_payload_preserves_snapshot_and_markdown() -> None:
    snapshot = _snapshot()
    markdown = render_daily_brief_markdown(snapshot)
    payload = render_daily_brief_payload(snapshot, markdown=markdown)

    assert payload["status"] == "partial"
    assert payload["date"] == "2026-06-12"
    assert payload["run_id"] == "run-news"
    assert payload["report_mode"] == "hybrid"
    assert payload["markdown"] == markdown
    assert payload["structured"]["core_event_count"] == 1
    assert payload["structured"]["key_article_count"] == 1
    assert payload["source_refs"] == snapshot["source_refs"]
    assert payload["quality_flags"] == ["single_source_verification_required"]


def test_render_daily_brief_markdown_degrades_empty_snapshot_to_short_flash() -> None:
    markdown = render_daily_brief_markdown(_snapshot(report_mode="empty", should_generate=False))
    payload = render_daily_brief_payload(_snapshot(report_mode="empty", should_generate=False), markdown=markdown)

    assert "小快讯" in markdown
    assert "暂无足够输入生成完整日报" in markdown
    assert "## 三条路径推演" not in markdown
    assert payload["status"] == "empty"
    assert payload["structured"]["core_event_count"] == 0


def test_archive_daily_brief_writes_markdown_and_json_artifacts(tmp_path: Path) -> None:
    paths = archive_daily_brief(
        storage_root=tmp_path,
        retrieved_date="2026-06-12",
        run_id="run-news",
        snapshot=_snapshot(),
    )

    assert paths == {
        "markdown": "outputs/daily_brief/2026-06-12/run-news/daily_brief.md",
        "json": "outputs/daily_brief/2026-06-12/run-news/daily_brief.json",
    }
    assert (tmp_path / paths["markdown"]).read_text(encoding="utf-8").startswith("# 每日市场快讯")
    payload = json.loads((tmp_path / paths["json"]).read_text(encoding="utf-8"))
    assert payload["status"] == "partial"
    assert payload["artifact_path"] == paths["markdown"]
    assert payload["input_snapshot_path"] == "features/news/2026-06-12/run-news/daily_brief_input_snapshot.json"
