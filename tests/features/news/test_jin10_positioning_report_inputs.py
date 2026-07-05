from __future__ import annotations

from importlib import import_module
from pathlib import Path


def _extract(*, report_text: str = "", vlm_markdown: str = "", source_refs: list[dict] | None = None) -> dict:
    module = import_module("apps.features.news.jin10_positioning_report_inputs")
    return module.extract_jin10_positioning_report_inputs(
        report_text=report_text,
        vlm_markdown=vlm_markdown,
        source_refs=source_refs or [{"source_key": "jin10_category_274", "article_id": "223700"}],
    )


def test_extracts_positioning_inputs_from_report_text_without_trade_conclusion_fields() -> None:
    payload = _extract(
        report_text=(
            "黄金期权持仓报告显示，XAUUSD 在 3350 上方看涨期权新增 1,240 手，"
            "多头增仓明显；3330 一线看跌期权减少 510 手。该报告仅为持仓观察。"
        ),
        source_refs=[{"source_key": "jin10_category_274", "article_id": "223700", "artifact": "report_text"}],
    )

    assert payload["report_type"] == "positioning"
    assert payload["provider_role"] == "supplemental_source"
    assert payload["verification_status"] == "single_source"
    assert payload["source_refs"] == [
        {"source_key": "jin10_category_274", "article_id": "223700", "artifact": "report_text"}
    ]

    assert payload["inputs"] == [
        {
            "asset": "XAUUSD",
            "direction": "bullish",
            "strike_or_level": "3350",
            "position_change": "increase",
            "confidence": 0.72,
            "source_refs": [
                {"source_key": "jin10_category_274", "article_id": "223700", "artifact": "report_text"}
            ],
            "verification_status": "single_source",
            "provider_role": "supplemental_source",
            "evidence_text": "XAUUSD 在 3350 上方看涨期权新增 1,240 手",
        },
        {
            "asset": "XAUUSD",
            "direction": "bearish",
            "strike_or_level": "3330",
            "position_change": "decrease",
            "confidence": 0.72,
            "source_refs": [
                {"source_key": "jin10_category_274", "article_id": "223700", "artifact": "report_text"}
            ],
            "verification_status": "single_source",
            "provider_role": "supplemental_source",
            "evidence_text": "3330 一线看跌期权减少 510 手",
        },
    ]
    forbidden_keys = {"trade_direction", "trade_signal", "entry", "stop_loss", "take_profit", "recommendation"}
    assert forbidden_keys.isdisjoint(payload)
    assert all(forbidden_keys.isdisjoint(item) for item in payload["inputs"])


def test_extracts_positioning_inputs_from_vlm_markdown_table() -> None:
    payload = _extract(
        vlm_markdown=(
            "| 标的 | 行权价/关键位 | 方向 | 持仓变化 |\n"
            "| --- | --- | --- | --- |\n"
            "| 黄金 | 3400 | 看涨 | 增持 880 手 |\n"
            "| 黄金 | 3300 | 看跌 | 减持 410 手 |\n"
        ),
        source_refs=[{"source_key": "jin10_category_274", "article_id": "223701", "artifact": "vision_markdown"}],
    )

    assert payload["input_count"] == 2
    assert payload["inputs"][0]["asset"] == "XAUUSD"
    assert payload["inputs"][0]["direction"] == "bullish"
    assert payload["inputs"][0]["strike_or_level"] == "3400"
    assert payload["inputs"][0]["position_change"] == "increase"
    assert payload["inputs"][0]["confidence"] == 0.72
    assert payload["inputs"][1]["direction"] == "bearish"
    assert payload["inputs"][1]["position_change"] == "decrease"


def test_archive_positioning_report_inputs_writes_feature_artifact(tmp_path: Path) -> None:
    module = import_module("apps.features.news.jin10_positioning_report_inputs")
    payload = module.extract_jin10_positioning_report_inputs(
        report_text="黄金期权持仓报告显示，XAUUSD 在 3350 上方看涨期权新增 1,240 手。",
        source_refs=[{"source_key": "jin10_category_274", "article_id": "223700"}],
    )

    artifact_path = module.archive_jin10_positioning_report_inputs(
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        run_id="274",
        extraction=payload,
    )

    assert artifact_path == "features/news/2026-06-11/274/positioning.json"
    assert (tmp_path / artifact_path).exists()
    assert '"positioning"' in (tmp_path / artifact_path).read_text(encoding="utf-8")
