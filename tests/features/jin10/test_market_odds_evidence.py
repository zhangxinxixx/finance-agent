from __future__ import annotations

import json

from apps.features.jin10.market_odds_evidence import (
    SUPPLEMENTAL_INFLUENCE_POLICY,
    build_jin10_market_odds_evidence,
    to_daily_market_observation,
    write_market_odds_evidence,
)


GOLDEN_TEXT = """美元日元：7月底赔率\n向上触及165 68%\n向下触及150 44%\n
霍尔木兹：7月31日前\n恢复正常运行概率26%\n
美联储：2026年内\n加息概率47%\n
WTI：7月底\n向下触及65美元 64%\n向下触及60美元 22%\n向上触及80美元 16%\n
黄金：7月底\n向上触及4200美元 94%\n向上触及4300美元 65%\n向上触及4400美元 35%\n向上触及4600美元 5%\n
白银：7月底\n向上触及64美元 78%\n向上触及66美元 63%\n向下触及56美元 54%\n向下触及54美元 36%"""


def _feature():
    return build_jin10_market_odds_evidence(
        article_id="223555",
        published_at="2026-07-03T14:00:00+08:00",
        parser_version="jin10-vlm-parser-v0.2",
        figures=[{
            "figure_id": "fig_p1_001",
            "page_no": 1,
            "bbox": [0, 0, 1080, 6120],
            "recognized_text": GOLDEN_TEXT,
        }],
        source_refs=[{"source_ref": "jin10:223555", "url": "https://svip.jin10.com/news/223555"}],
        generated_at="2026-07-16T00:00:00+00:00",
    )


def test_223555_golden_contract_has_six_anchored_panels() -> None:
    feature = _feature()
    assert feature.extraction_status == "accepted"
    assert feature.panel_count == 6
    assert len(feature.items) == 15
    assert all(0 <= item.probability <= 1 for item in feature.items)
    assert len({item.item_id for item in feature.items}) == len(feature.items)
    assert all(item.page_no == 1 and item.figure_id == "fig_p1_001" for item in feature.items)
    assert all(item.bbox == [0, 0, 1080, 6120] and item.ocr_text for item in feature.items)
    gold = next(item for item in feature.items if item.asset == "XAUUSD" and item.target_value == 4200)
    assert gold.predicate == "touch_above"
    assert gold.probability_semantics == "ever_touch_before_horizon"


def test_unanchored_markdown_requires_review_and_cannot_create_items() -> None:
    feature = build_jin10_market_odds_evidence(
        article_id="223555",
        published_at="2026-07-03T14:00:00+08:00",
        parser_version="v1",
        figures=[],
        markdown_context=GOLDEN_TEXT,
    )
    assert feature.extraction_status == "needs_review"
    assert feature.panel_count == 0
    assert feature.items == []


def test_artifact_writer_and_daily_brief_adapter_preserve_supplemental_guard(tmp_path) -> None:
    feature = _feature()
    target = write_market_odds_evidence(feature, output_dir=tmp_path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert target.name == "market_odds_evidence.json"
    assert payload["source_kind"] == "jin10_external_market_odds"
    observation = to_daily_market_observation(payload)
    assert observation["observation_type"] == "external_market_odds"
    assert observation["influence_policy"] == SUPPLEMENTAL_INFLUENCE_POLICY
    assert observation["influence_policy"]["can_change_macro_regime"] is False
    assert observation["influence_policy"]["can_set_strategy_direction"] is False
    assert observation["influence_policy"]["can_block_readiness"] is False


def test_layout_panel_uses_matching_markdown_paragraph_only_for_asset_context() -> None:
    context = """美联储2026年内加息概率47%。\n\nWTI向下触及65美元概率达到64%，向上触及80美元16%。\n\n黄金7月触及4200美元的概率升至94%。\n\n白银向上触及64美元概率升至78%。"""
    feature = build_jin10_market_odds_evidence(
        article_id="223555",
        published_at="2026-07-03T14:00:00+08:00",
        parser_version="v1",
        figures=[
            {"figure_id": "fig_p1_001", "page_no": 1, "bbox": [0, 0, 10, 10], "title": "向下触及65美元 64%"},
            {"figure_id": "fig_p1_002", "page_no": 1, "bbox": [0, 10, 10, 20], "title": "向上触及4200美元 94%"},
            {"figure_id": "fig_p1_003", "page_no": 1, "bbox": [0, 20, 10, 30], "title": "向上触及64美元 78%"},
        ],
        markdown_context=context,
    )
    assert [item.asset for item in feature.items] == ["WTI", "XAUUSD", "XAGUSD"]
    assert feature.items[0].extraction_status == "needs_review"
    assert feature.items[1].horizon_end == "2026-07-31"


def test_conflicting_probabilities_for_same_standard_event_require_review() -> None:
    feature = build_jin10_market_odds_evidence(
        article_id="223555",
        published_at="2026-07-03T14:00:00+08:00",
        parser_version="v1",
        figures=[{
            "figure_id": "fig_p1_001",
            "page_no": 1,
            "bbox": [0, 0, 100, 100],
            "recognized_text": "黄金：7月底\n向上触及4200美元 94%\n向上触及4200美元 65%",
        }],
    )

    assert len(feature.items) == 2
    assert len({item.item_id for item in feature.items}) == 2
    assert feature.extraction_status == "needs_review"
    assert all(item.extraction_status == "needs_review" for item in feature.items)
    assert all(
        "duplicate_event_conflicting_probability" in item.validation_flags
        for item in feature.items
    )


def test_item_id_includes_panel_identity() -> None:
    feature = _feature()
    assert all(item.panel_id in item.item_id for item in feature.items)
