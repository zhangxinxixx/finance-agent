from __future__ import annotations

from apps.parsers.jin10.report_image_parser import _normalize_positioning_paired_panel_titles


def test_positioning_pair_titles_bind_asset_and_call_put_panels() -> None:
    figures = [
        {"figure_id": "fig_p9_001", "page_no": 9, "bbox": [18, 210, 481, 1584], "title": "黄金持仓报告"},
        {"figure_id": "fig_p9_002", "page_no": 9, "bbox": [481, 210, 941, 1584], "title": "图例"},
    ]
    layout = {
        "pages": [
            {
                "page_no": 9,
                "markdown": "# 黄金持仓报告\n\n![看涨期权](figures/fig_p9_001.png)\n\n![看跌期权](figures/fig_p9_002.png)",
                "charts": [
                    {"title": "看涨期权", "bbox": [18, 210, 481, 1584]},
                    {"title": "看跌期权", "bbox": [481, 210, 941, 1584]},
                ],
            }
        ]
    }

    result = _normalize_positioning_paired_panel_titles(
        figures=figures,
        layout_payload=layout,
        report_type="positioning",
    )

    assert [item["title"] for item in result] == [
        "黄金持仓报告 · 看涨期权",
        "黄金持仓报告 · 看跌期权",
    ]
