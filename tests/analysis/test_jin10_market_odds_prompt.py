from apps.analysis.jin10.agent_analysis import build_agent_analysis_prompt


def test_market_odds_prompt_orders_structured_items_before_evidence_and_markdown() -> None:
    prompt = build_agent_analysis_prompt(
        {
            "trade_date": "2026-07-03",
            "article_id": "223555",
            "title": "市场赔率数据表",
            "source_url": "https://svip.jin10.com/news/223555",
            "article_markdown": "黄金触及4200美元概率94%。",
            "charts": [],
            "generated_from": {"article_context": {}},
        },
        {"report_type": "market_observation", "summary": "fixture"},
        market_odds_evidence={
            "source_kind": "jin10_external_market_odds",
            "items": [
                {
                    "item_id": "223555:gold:4200",
                    "panel_id": "fig_p1_005:panel_01",
                    "asset": "XAUUSD",
                    "event_type": "price_level",
                    "predicate": "touch_above",
                    "target_value": 4200,
                    "target_unit": "USD_per_oz",
                    "horizon_start": "2026-07-03",
                    "horizon_end": "2026-07-31",
                    "probability": 0.94,
                    "probability_semantics": "ever_touch_before_horizon",
                    "outcome_label": "黄金向上触及4200美元",
                    "extraction_status": "accepted",
                    "page_no": 1,
                    "figure_id": "fig_p1_005",
                    "bbox": [82, 5138, 880, 5649],
                    "ocr_text": "向上触及4200美元 94%",
                    "source_refs": [{"source_ref": "jin10:223555"}],
                    "evidence_refs": [{"figure_id": "fig_p1_005"}],
                }
            ],
        },
    )
    structured_at = prompt.index("结构化 market_odds_evidence items（第一优先级）")
    evidence_at = prompt.index("evidence refs / OCR / figures（第二优先级）")
    markdown_at = prompt.index("raw_report article_markdown（仅作上下文补充）")
    assert structured_at < evidence_at < markdown_at
    assert '"probability_semantics": "ever_touch_before_horizon"' in prompt
    assert '"figure_id": "fig_p1_005"' in prompt
    assert "单源赔率或观察直接升级为交易结论" in prompt
