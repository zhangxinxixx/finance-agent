from __future__ import annotations

from apps.analysis.jin10.multimodal import build_multimodal_user_content


def _raw_report() -> dict:
    return {
        "article_id": "224307",
        "article_markdown": (
            "# 日报\n\n前文解释。\n\n"
            "![黄金关键位](figures/fig_p12_001.png)\n\n"
            "后文结论。"
        ),
        "source_refs": [{"source": "jin10_external", "article_id": "224307"}],
        "charts": [
            {
                "figure_id": "fig_p12_001",
                "page_no": 12,
                "bbox": [241, 2307, 1559, 3007],
                "title": "黄金关键位",
                "recognized_text": "4100 CPI",
                "summary": "黄金跳空下破4100",
                "image_path": "figures/fig_p12_001.png",
            }
        ],
    }


def test_multimodal_content_interleaves_metadata_and_real_image_in_article_order() -> None:
    raw = _raw_report()
    prompt = f"规则开始\n{raw['article_markdown']}\n规则结束"

    plan = build_multimodal_user_content(
        prompt,
        raw,
        image_loader=lambda chart: "data:image/png;base64,ZmFrZQ==",
    )

    assert plan.status == "success"
    assert plan.submitted_image_count == 1
    assert [block["type"] for block in plan.content] == ["text", "text", "image_url", "text"]
    assert "前文解释" in plan.content[0]["text"]
    assert "figure_id=fig_p12_001" in plan.content[1]["text"]
    assert "page_no=12" in plan.content[1]["text"]
    assert "bbox=[241, 2307, 1559, 3007]" in plan.content[1]["text"]
    assert "source_ref=" in plan.content[1]["text"]
    assert plan.content[2]["image_url"]["url"].startswith("data:image/png;base64,")
    assert plan.content[2]["image_url"]["detail"] == "original"
    assert "后文结论" in plan.content[3]["text"]
    assert plan.figure_results[0]["status"] == "submitted"


def test_multimodal_content_marks_missing_image_degraded() -> None:
    raw = _raw_report()

    plan = build_multimodal_user_content(
        raw["article_markdown"],
        raw,
        image_loader=lambda chart: None,
    )

    assert plan.status == "degraded"
    assert plan.submitted_image_count == 0
    assert plan.degraded_reasons == ["image_unavailable:fig_p12_001"]
    assert plan.figure_results[0]["status"] == "unavailable"
    assert all(block["type"] != "image_url" for block in plan.content)


def test_multimodal_content_marks_input_limit_degraded_without_reordering() -> None:
    raw = _raw_report()
    second = dict(raw["charts"][0])
    second.update(
        {
            "figure_id": "fig_p13_001",
            "page_no": 13,
            "image_path": "figures/fig_p13_001.png",
        }
    )
    raw["charts"].append(second)
    raw["article_markdown"] += "\n\n![第二张](figures/fig_p13_001.png)"

    plan = build_multimodal_user_content(
        raw["article_markdown"],
        raw,
        image_loader=lambda chart: f"data:image/png;base64,{chart['figure_id']}",
        max_images=1,
    )

    assert plan.status == "degraded"
    assert plan.submitted_image_count == 1
    assert plan.degraded_reasons == ["image_limit_exceeded:fig_p13_001"]
    assert [item["figure_id"] for item in plan.figure_results] == ["fig_p12_001", "fig_p13_001"]
    assert [item["status"] for item in plan.figure_results] == ["submitted", "omitted_limit"]
