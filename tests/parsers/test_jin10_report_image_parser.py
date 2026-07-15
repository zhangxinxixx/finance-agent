from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2
import numpy as np

from apps.parsers.jin10.report import _parser_report_type
from apps.parsers.jin10.report_image_parser import (
    PARSER_VERSION,
    _aggregate_parse_status,
    _detect_white_chart_panels,
    _normalize_vision_markdown_payload,
    figure_analysis_image_data_url,
    figure_image_data_url,
    parse_report_images,
    render_vision_markdown,
    write_parse_artifacts,
)
from apps.parsers.jin10.vision_recognition_agent.agent import (
    VisionMarkdownClient,
    _build_page_unified_prompt,
    _image_to_data_url,
    _normalize_chart_bbox,
    _normalize_layout_blocks,
    normalize_page_markdown,
    recognize_pages_as_markdown,
    recognize_pages_layout,
    recognize_pages_unified,
)


def test_aggregate_parse_status_does_not_treat_page_presence_as_success() -> None:
    result = _aggregate_parse_status(
        page_payloads=[{"page_no": 1}, {"page_no": 2}],
        report_type="positioning",
        vision_markdown={"pages": [{"page_no": 1, "status": "failed", "markdown": ""}]},
        vision_markdown_status="failed",
        vision_layout_status="failed",
        body_markdown="",
    )

    assert result["status"] == "failed"
    assert result["valid_recognized_page_count"] == 0
    assert result["empty_page_ratio"] == 1.0


def test_aggregate_parse_status_reports_partial_when_only_some_pages_are_substantive() -> None:
    result = _aggregate_parse_status(
        page_payloads=[{"page_no": 1}, {"page_no": 2}],
        report_type="positioning",
        vision_markdown={
            "pages": [
                {"page_no": 1, "status": "success", "markdown": "# 黄金\n\n实际利率仍是主要变量。"},
                {"page_no": 2, "status": "empty", "markdown": ""},
            ]
        },
        vision_markdown_status="partial",
        vision_layout_status="partial",
        body_markdown="# 黄金\n\n实际利率仍是主要变量。",
    )

    assert result["status"] == "partial"
    assert result["valid_recognized_page_count"] == 1
    assert result["empty_page_ratio"] == 0.5


def test_figure_image_data_url_crops_from_in_memory_page_artifacts(tmp_path: Path) -> None:
    image_path = tmp_path / "page.png"
    _write_page_image(image_path, include_chart=True)
    artifacts = {
        "page_images": {
            "pages": [
                {
                    "page_no": 2,
                    "image_path": str(image_path),
                }
            ]
        }
    }
    chart = {
        "figure_id": "fig_p2_001",
        "page_no": 2,
        "bbox": [80, 180, 920, 720],
    }

    encoded = figure_image_data_url(artifacts, chart)

    assert encoded.startswith("data:image/png;base64,")


def test_figure_analysis_image_data_url_bounds_size_and_uses_jpeg(tmp_path: Path) -> None:
    image_path = tmp_path / "page.png"
    image = np.full((2400, 1800, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (100, 100), (1700, 2300), (0, 0, 0), 8)
    cv2.imwrite(str(image_path), image)
    artifacts = {"page_images": {"pages": [{"page_no": 2, "image_path": str(image_path)}]}}
    chart = {"figure_id": "fig_p2_001", "page_no": 2, "bbox": [0, 0, 1800, 2400]}

    encoded = figure_analysis_image_data_url(artifacts, chart, max_long_edge=1200, jpeg_quality=90)
    payload = base64.b64decode(encoded.split(",", 1)[1])
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert encoded.startswith("data:image/jpeg;base64,")
    assert decoded is not None
    assert max(decoded.shape[:2]) == 1200


def test_cover_unified_prompt_preserves_formal_report_classification() -> None:
    prompt = _build_page_unified_prompt(
        page_no=1,
        page_width=2160,
        page_height=3839,
        original_page_width=2160,
        original_page_height=3839,
        prompt_profile="default",
        preserve_cover_identity=True,
    )

    assert "正式报告分类" in prompt
    assert "黄金投资者周报" in prompt
    assert "周末·大师复盘" in prompt
    assert "页面底部" in prompt
    assert "本期主题" in prompt


def test_unified_prompt_only_requests_recognition_and_complete_crop_regions() -> None:
    prompt = _build_page_unified_prompt(
        page_no=2,
        page_width=2160,
        page_height=3839,
        original_page_width=2160,
        original_page_height=3839,
        prompt_profile="default",
    )

    assert "唯一任务是 OCR 和 bbox 定位" in prompt
    assert "禁止总结、解释、改写、推断" in prompt
    assert "不得只框内部绘图区" in prompt
    assert "面板内标题、图例、坐标轴、刻度标签、数据来源" in prompt
    assert "不需要解释图中曲线" in prompt
    assert "只写面板标题" in prompt
    assert "不得进入 markdown 或 blocks" in prompt


def test_market_odds_unified_prompt_treats_whole_page_as_primary_evidence() -> None:
    prompt = _build_page_unified_prompt(
        page_no=1,
        page_width=1200,
        page_height=1800,
        original_page_width=1200,
        original_page_height=1800,
        prompt_profile="market_odds",
    )

    assert "市场赔率数据表" in prompt
    assert "整页" in prompt
    assert "触及概率" in prompt


def test_market_observation_metadata_routes_odds_table_to_internal_parser_profile() -> None:
    assert (
        _parser_report_type(
            {
                "report_type": "market_observation",
                "series": "market_odds",
                "subcategory": "market_odds",
                "title": "加息跌破半数，黄金赔率变脸｜市场赔率数据表",
            }
        )
        == "market_odds"
    )
    assert (
        _parser_report_type(
            {
                "report_type": "market_observation",
                "title": "VIP每日市场观察：黄金等待确认",
            }
        )
        == "market_observation"
    )


def test_parse_market_odds_single_page_as_anchored_primary_figure(tmp_path: Path) -> None:
    image_path = tmp_path / "market-odds.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="223555",
        title="加息跌破半数，黄金赔率变脸｜市场赔率数据表",
        published_at=None,
        image_entries=[{"seq": 1, "file": image_path.name, "path": str(image_path)}],
        report_type="market_odds",
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 1,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {
                            "id": "table_001",
                            "type": "table",
                            "text": "市场赔率数据表",
                            "bbox": [0, 0, 1000, 1600],
                        },
                        {
                            "id": "text_001",
                            "type": "text",
                            "text": "黄金触及4200美元概率94%，4300美元概率65%。",
                            "bbox": [80, 200, 920, 360],
                        },
                    ],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["status"] == "success"
    assert artifacts["parse_status"]["figures_total"] == 1
    assert artifacts["figures"]["figures"][0]["page_no"] == 1
    assert artifacts["figures"]["figures"][0]["bbox"] == [0, 0, 1000, 1600]
    assert "黄金触及4200美元概率94%" in artifacts["body_markdown"]


def test_vision_client_preserves_explicit_cockpit_luna_provider() -> None:
    client = VisionMarkdownClient(provider="cockpit", model="gpt-5.6-luna")

    assert client.provider == "cockpit"
    assert client.model == "gpt-5.6-luna"


def test_vision_client_uses_formal_luna_high_defaults(monkeypatch) -> None:
    for name in (
        "JIN10_VISION_PROVIDER",
        "JIN10_VISION_MODEL",
        "JIN10_MIMO_VL_MODEL",
        "JIN10_VISION_REASONING_EFFORT",
        "JIN10_VISION_TIMEOUT",
        "JIN10_VISION_MAX_RETRIES",
    ):
        monkeypatch.delenv(name, raising=False)

    client = VisionMarkdownClient()

    assert client.provider == "cockpit"
    assert client.model == "gpt-5.6-luna"
    assert client.reasoning_effort == "high"
    assert client.request_timeout == 120.0
    assert client.max_retries == 0


def test_vision_client_invalid_runtime_values_fall_back_to_safe_defaults(monkeypatch) -> None:
    monkeypatch.setenv("JIN10_VISION_TIMEOUT", "invalid")
    monkeypatch.setenv("JIN10_VISION_MAX_RETRIES", "invalid")
    monkeypatch.setenv("JIN10_VISION_REASONING_EFFORT", "")
    monkeypatch.setenv("JIN10_VISION_MAX_LONG_EDGE", "0")
    monkeypatch.setenv("JIN10_VISION_JPEG_QUALITY", "999")

    client = VisionMarkdownClient()

    assert client.request_timeout == 120.0
    assert client.max_retries == 0
    assert client.reasoning_effort == "high"
    assert client.max_image_long_edge > 0
    assert client.image_jpeg_quality == 100


def test_vision_client_can_disable_gateway_retries_for_benchmark(monkeypatch) -> None:
    captured = {}

    class Response:
        content = "{}"

    def fake_chat_sync(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("apps.parsers.jin10.vision_recognition_agent.agent.chat_sync", fake_chat_sync)
    client = VisionMarkdownClient(provider="cockpit", model="gpt-5.6-luna", max_retries=0)

    client._chat_with_image(image_data_url="data:image/png;base64,ZmFrZQ==", text_prompt="识别")

    assert captured["max_retries"] == 0


def test_vision_client_passes_explicit_low_reasoning_effort(monkeypatch) -> None:
    captured = {}

    class Response:
        content = "{}"

    def fake_chat_sync(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("apps.parsers.jin10.vision_recognition_agent.agent.chat_sync", fake_chat_sync)
    client = VisionMarkdownClient(
        provider="cockpit",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        timeout=360,
    )

    client._chat_with_image(image_data_url="data:image/png;base64,ZmFrZQ==", text_prompt="识别")

    assert captured["reasoning_effort"] == "low"
    assert captured["request_timeout"] == 360
    image_block = captured["messages"][0]["content"][0]
    assert image_block["image_url"]["detail"] == "original"


def test_parse_report_images_emits_vlm_schema_and_writes_artifacts(monkeypatch, tmp_path: Path):
    report_dir = tmp_path / "2026-05-22" / "金银报告" / "219948"
    images_dir = report_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    page_one = images_dir / "01.png"
    page_two = images_dir / "02.png"
    _write_page_image(page_one, include_chart=True)
    _write_page_image(page_two, include_chart=True)

    image_entries = [
        {"seq": 1, "file": "01.png", "path": str(page_one)},
        {"seq": 2, "file": "02.png", "path": str(page_two)},
    ]

    def fake_vision(pages, figures):
        assert [page["page_no"] for page in pages] == [1, 2]
        assert all("image_path" in page for page in pages)
        assert figures
        return {
            "provider": "mimo",
            "model": "mimo-v2.5",
            "pages": [
                {"page_no": 1, "status": "success", "markdown": "# 每日金银报告\n\n## 目录\n\nVIP专属报告系列"},
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 美国初请人数维持下行趋势\n\n"
                        "![图表](figures/fig_p2_001.png)\n\n"
                        "美国至5月16日当周初请失业金人数录得20.9万人。"
                    ),
                },
            ],
        }

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at="2026-05-22 10:00",
        image_entries=image_entries,
        vision_markdown_runner=fake_vision,
    )

    assert artifacts["page_images"]["article_id"] == "219948"
    assert artifacts["page_images"]["parser_version"] == PARSER_VERSION
    assert artifacts["parse_status"]["recognition_mode"] == "vlm"
    assert artifacts["parse_status"]["pages_total"] == 2
    assert artifacts["parse_status"]["cover_page_count"] == 1
    assert artifacts["parse_status"]["figures_total"] == 0
    assert artifacts["parse_status"]["vision_markdown_status"] == "failed"
    assert artifacts["body_markdown"].strip() == "# 测试报告\n\n- 发布时间: 2026-05-22 10:00"


    monkeypatch.setenv("JIN10_WRITE_DEBUG_IMAGES", "1")

    output_dir = tmp_path / "storage" / "parsed" / "jin10" / "2026-05-22" / "219948"
    written = write_parse_artifacts(artifacts, output_dir)

    assert Path(written["page_images"]).exists()
    assert Path(written["figures"]).exists()
    assert Path(written["report_structured"]).exists()
    assert Path(written["parse_status"]).exists()

    assert (output_dir / "debug" / "page_001_original.png").exists()
    assert (output_dir / "debug" / "page_001_enhanced.png").exists()

    page_images = json.loads((output_dir / "page_images.json").read_text(encoding="utf-8"))
    figures = json.loads((output_dir / "figures.json").read_text(encoding="utf-8"))
    status = json.loads((output_dir / "parse_status.json").read_text(encoding="utf-8"))

    assert page_images["pages"][0]["page_no"] == 1
    assert "debug/page_001_original.png" == page_images["pages"][0]["debug_images"]["original"]
    assert figures["figures"] == []
    assert status["recognition_mode"] == "vlm"


def test_write_parse_artifacts_skips_debug_images_by_default(tmp_path: Path):
    report_dir = tmp_path / "2026-05-22" / "金银报告" / "219948"
    images_dir = report_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    page_one = images_dir / "01.png"
    _write_page_image(page_one, include_chart=True)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at="2026-05-22 10:00",
        image_entries=[{"seq": 1, "file": "01.png", "path": str(page_one)}],
        vision_markdown_runner=lambda pages, figures: {"provider": "mimo", "model": "mimo-v2.5", "pages": []},
    )

    output_dir = tmp_path / "storage" / "parsed" / "jin10" / "2026-05-22" / "219948"
    write_parse_artifacts(artifacts, output_dir)

    page_images = json.loads((output_dir / "page_images.json").read_text(encoding="utf-8"))
    assert not (output_dir / "debug").exists()
    assert "debug_images" not in page_images["pages"][0]


def test_render_vision_markdown_skips_cover_page_chunk():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at="2026-05-22 10:00",
        vision_markdown={
            "pages": [
                {
                    "page_no": 1,
                    "status": "success",
                    "markdown": "# 每日金银报告\n\n## 目录\n\nVIP专属报告系列",
                },
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": "# 行情回顾\n\n美元走软和美债收益率下降支撑了金价。",
                },
            ]
        },
    )

    assert "# 每日金银报告" not in markdown
    assert "VIP专属报告系列" not in markdown
    assert "# 行情回顾" in markdown


def test_render_vision_markdown_filters_directory_vip_and_brand_footer_noise():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at="2026-05-22 10:00",
        vision_markdown={
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 行情回顾\n\n"
                        "黄金在美债收益率回落后出现修复。\n\n"
                        "## 目录\n\n"
                        "VIP专属报告系列\n\n"
                        "金十数据 Research\n\n"
                        "每日 金银报告"
                    ),
                }
            ]
        },
    )

    assert "黄金在美债收益率回落后出现修复。" in markdown
    assert "## 目录" not in markdown
    assert "VIP专属报告系列" not in markdown
    assert "金十数据 Research" not in markdown
    assert "每日 金银报告" not in markdown


def test_render_vision_markdown_filters_model_request_noise():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at=None,
        vision_markdown={
            "pages": [
                {
                    "page_no": 15,
                    "status": "success",
                    "markdown": "## 白银机构动向\n\n无变化",
                },
                {
                    "page_no": 16,
                    "status": "success",
                    "markdown": "请提供第 16 页的图片，我才能为您进行转录。",
                },
            ]
        },
    )

    assert "## 白银机构动向\n\n无变化" in markdown
    assert "请提供第 16 页的图片" not in markdown


def test_render_vision_markdown_keeps_summary_body_but_strips_cover_shell_noise():
    markdown = render_vision_markdown(
        title="CPI与沃什首秀构成夏季行情核心，鹰派预期进入再定价窗口",
        published_at="2026-06-10",
        vision_markdown={
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 每日金银报告\n\n"
                        "2026年06月10日\n\n"
                        "CPI与沃什首秀构成夏季行情核心，鹰派预期进入再定价窗口\n\n"
                        "加息预期持续累积，本次CPI将决定鹰派定价深化还是反转。"
                        "通胀前景和下周美联储决议的政策倾向或将定调夏季行情走向。\n\n"
                        "联系方式\n\n"
                        "bianjibu@jin10.com\n\n"
                        "VIP Team\n\n"
                        "## 目录\n\n"
                        "01 隔夜要闻\n\n"
                        "02 今日黄金市场聚焦\n\n"
                        "03 市场分析\n\n"
                        "04 关键图表\n\n"
                        "05 金银机构动向\n\n"
                        "06 技术指标\n\n"
                        "VIP专属报告系列\n\n"
                        "本材料中的信息来自其撰写者的观点。"
                    ),
                }
            ]
        },
    )

    assert "加息预期持续累积，本次CPI将决定鹰派定价深化还是反转。" in markdown
    assert "每日金银报告" not in markdown
    assert "2026年06月10日" not in markdown
    assert "CPI与沃什首秀构成夏季行情核心，鹰派预期进入再定价窗口\n\n加息预期" not in markdown
    assert "01 隔夜要闻" not in markdown
    assert "02 今日黄金市场聚焦" not in markdown
    assert "VIP Team" not in markdown
    assert "bianjibu@jin10.com" not in markdown
    assert "本材料中的信息来自其撰写者的观点" not in markdown


def test_render_vision_markdown_stitches_cross_page_broken_lines():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at=None,
        vision_markdown={
            "pages": [
                {
                    "page_no": 9,
                    "status": "success",
                    "markdown": "周四收盘后，由于原油价格下跌和美债收益率走低抵消了",
                },
                {
                    "page_no": 10,
                    "status": "success",
                    "markdown": "美元走强的影响，现货黄金价格几近持平。",
                },
                {
                    "page_no": 12,
                    "status": "success",
                    "markdown": "只有和平协议落地或美联储政策预期明",
                },
                {
                    "page_no": 13,
                    "status": "success",
                    "markdown": "确转向，金价才可能走出方向性行情。",
                },
            ]
        },
    )

    assert "抵消了美元走强的影响" in markdown
    assert "预期明确转向" in markdown


def test_render_vision_markdown_promotes_analyst_label_to_heading():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at=None,
        vision_markdown={
            "pages": [
                {
                    "page_no": 4,
                    "status": "success",
                    "markdown": "分析师Neils Christensen\n\n实际收益率上升已成为贵金属市场最明显的威胁。",
                }
            ]
        },
    )

    assert "## 分析师Neils Christensen" in markdown
    assert "实际收益率上升已成为贵金属市场最明显的威胁。" in markdown


def test_render_vision_markdown_ignores_market_insight_noise_before_continuation():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at=None,
        vision_markdown={
            "pages": [
                {
                    "page_no": 6,
                    "status": "success",
                    "markdown": "随着油价飙升和通胀担忧充斥债券市场，名义利率大幅飙",
                },
                {
                    "page_no": 7,
                    "status": "success",
                    "markdown": (
                        "# 即时市场洞察\n\n"
                        "# 每日金银报告\n\n"
                        "升。确实，黄金最初在实际收益率上升时表现良好。"
                    ),
                },
            ]
        },
    )

    assert "名义利率大幅飙升。确实" in markdown
    assert "即时市场洞察" not in markdown


def test_render_vision_markdown_promotes_plain_heading_on_next_page():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at=None,
        vision_markdown={
            "pages": [
                {
                    "page_no": 14,
                    "status": "success",
                    "markdown": "## 黄金机构动向\n\n无变化",
                },
                {
                    "page_no": 15,
                    "status": "success",
                    "markdown": "白银机构动向\n\n无变化",
                },
            ]
        },
    )

    assert "## 黄金机构动向\n\n无变化\n\n## 白银机构动向\n\n无变化" in markdown
    assert "无变化白银机构动向" not in markdown


def test_parse_report_images_attaches_nearby_text_without_footer_noise(tmp_path: Path):
    image_path = tmp_path / "page.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": "page.png", "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 关键图表\n\n"
                        "![图表](figures/fig_p2_001.png)\n\n"
                        "收益率回落为黄金修复打开窗口，但价格仍未完成日线确认。\n\n"
                        "金十数据 Research\n"
                    ),
                }
            ]
        },
    )

    assert artifacts["figures"]["figures"][0]["nearby_text"] == "收益率回落为黄金修复打开窗口，但价格仍未完成日线确认。"


def test_parse_report_images_surfaces_vision_failure_reason_in_parse_status(tmp_path: Path):
    image_path = tmp_path / "page.png"
    _write_page_image(image_path, include_chart=True)

    def failing_runner(pages, figures):
        raise RuntimeError("vision request timed out")

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": "page.png", "path": str(image_path)}],
        vision_markdown_runner=failing_runner,
    )

    warnings = artifacts["parse_status"]["warnings"]
    assert any("vision_markdown_failed:RuntimeError" in item for item in warnings)
    assert any("vision request timed out" in item for item in warnings)


def test_parse_report_images_vlm_visual_detection_keeps_upper_chart(tmp_path: Path):
    image_path = tmp_path / "upper-chart.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 14, "file": "upper-chart.png", "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 14,
                    "status": "success",
                    "markdown": (
                        "# 黄金机构动向\n\n"
                        "![图表](https://example.com/chart-placeholder.png)\n\n"
                        "黄金ETF最新一日小幅回补。"
                    ),
                }
            ]
        },
    )

    assert artifacts["parse_status"]["recognition_mode"] == "vlm"
    assert any(figure["page_no"] == 14 for figure in artifacts["figures"]["figures"])
    assert "figures/fig_p14_001.png" in artifacts["body_markdown"]
    assert "example.com/chart-placeholder.png" not in artifacts["body_markdown"]


def test_parse_report_images_vlm_processes_all_pages_by_default(tmp_path: Path):
    image_entries = []
    for seq in range(1, 15):
        image_path = tmp_path / f"{seq:02d}.png"
        _write_page_image(image_path, include_chart=False)
        image_entries.append({"seq": seq, "file": image_path.name, "path": str(image_path)})

    seen_pages: list[int] = []

    def fake_runner(pages, figures):
        seen_pages.extend(int(page["page_no"]) for page in pages)
        return {"pages": []}

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=image_entries,
        vision_markdown_runner=fake_runner,
    )

    assert seen_pages == list(range(2, 15))
    assert not any("vision_page_limit_applied:" in item for item in artifacts["parse_status"]["warnings"])


def test_parse_report_images_vlm_can_distribute_pages_when_limit_is_set(monkeypatch, tmp_path: Path):
    image_entries = []
    for seq in range(1, 37):
        image_path = tmp_path / f"{seq:02d}.png"
        _write_page_image(image_path, include_chart=False)
        image_entries.append({"seq": seq, "file": image_path.name, "path": str(image_path)})

    seen_pages: list[int] = []

    def fake_runner(pages, figures):
        seen_pages.extend(int(page["page_no"]) for page in pages)
        return {"pages": []}

    monkeypatch.setenv("JIN10_VISION_PAGE_LIMIT", "12")

    artifacts = parse_report_images(
        article_id="219948",
        title="长报告测试",
        published_at=None,
        image_entries=image_entries,
        vision_markdown_runner=fake_runner,
    )

    assert seen_pages == [2, 3, 4, 8, 11, 15, 18, 22, 25, 29, 32, 36]
    assert "vision_page_limit_applied:12/35" in artifacts["parse_status"]["warnings"]


def test_parse_report_images_vlm_page_limit_can_be_disabled(monkeypatch, tmp_path: Path):
    image_entries = []
    for seq in range(1, 9):
        image_path = tmp_path / f"{seq:02d}.png"
        _write_page_image(image_path, include_chart=False)
        image_entries.append({"seq": seq, "file": image_path.name, "path": str(image_path)})

    seen_pages: list[int] = []

    def fake_runner(pages, figures):
        seen_pages.extend(int(page["page_no"]) for page in pages)
        return {"pages": []}

    monkeypatch.setenv("JIN10_VISION_PAGE_LIMIT", "0")

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=image_entries,
        vision_markdown_runner=fake_runner,
    )

    assert seen_pages == [2, 3, 4, 5, 6, 7, 8]
    assert not any("vision_page_limit_applied:" in item for item in artifacts["parse_status"]["warnings"])


def test_parse_report_images_vlm_page_selection_can_use_head_only(monkeypatch, tmp_path: Path):
    image_entries = []
    for seq in range(1, 15):
        image_path = tmp_path / f"{seq:02d}.png"
        _write_page_image(image_path, include_chart=False)
        image_entries.append({"seq": seq, "file": image_path.name, "path": str(image_path)})

    seen_pages: list[int] = []

    def fake_runner(pages, figures):
        seen_pages.extend(int(page["page_no"]) for page in pages)
        return {"pages": []}

    monkeypatch.setenv("JIN10_VISION_PAGE_LIMIT", "12")
    monkeypatch.setenv("JIN10_VISION_PAGE_SELECTION", "head")

    parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=image_entries,
        vision_markdown_runner=fake_runner,
    )

    assert seen_pages == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]


def test_parse_report_images_skips_remote_images_without_marking_unreadable():
    seen_pages: list[int] = []

    def fake_runner(pages, figures):
        seen_pages.extend(int(page["page_no"]) for page in pages)
        assert figures == []
        return {"pages": []}

    artifacts = parse_report_images(
        article_id="220511",
        title="远程图片测试",
        published_at=None,
        image_entries=[
            {"seq": 1, "file": "body-1.jpg", "path": "https://img.jin10.com/news/26/05/body-1.jpg", "width": 1200, "height": 1800},
            {"seq": 2, "file": "body-2.jpg", "path": "https://img.jin10.com/news/26/05/body-2.jpg", "width": 1200, "height": 1800},
        ],
        vision_markdown_runner=fake_runner,
    )

    assert seen_pages == [2]
    assert artifacts["page_images"]["pages"][0]["image_path"].startswith("https://img.jin10.com/")
    assert "page_001 remote_image_skipped" in artifacts["parse_status"]["warnings"]
    assert not any("image_unreadable" in item for item in artifacts["parse_status"]["warnings"])
    assert artifacts["parse_status"]["empty_page_count"] == 0


def test_parse_report_images_does_not_replace_web_markdown_with_title_only_vision_result():
    artifacts = parse_report_images(
        article_id="220511",
        title="远程网页报告",
        published_at="2026-05-28 08:00",
        image_entries=[
            {"seq": 1, "file": "body-1.jpg", "path": "https://img.jin10.com/news/26/05/body-1.jpg", "width": 1200, "height": 1800},
            {"seq": 2, "file": "body-2.jpg", "path": "https://img.jin10.com/news/26/05/body-2.jpg", "width": 1200, "height": 1800},
        ],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {"page_no": 1, "status": "success", "markdown": ""},
                {"page_no": 2, "status": "success", "markdown": ""},
            ]
        },
    )

    assert artifacts["body_markdown"] == "# 远程网页报告\n\n- 发布时间: 2026-05-28 08:00\n"


def test_parse_report_images_vlm_skips_cover_page_figures(tmp_path: Path):
    cover_path = tmp_path / "01.png"
    body_path = tmp_path / "02.png"
    _write_page_image(cover_path, include_chart=True)
    _write_page_image(body_path, include_chart=True)
    layout_pages_seen: list[int] = []

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[
            {"seq": 1, "file": cover_path.name, "path": str(cover_path)},
            {"seq": 2, "file": body_path.name, "path": str(body_path)},
        ],
        vision_markdown_runner=lambda pages, figures: {"pages": []},
        vision_layout_runner=lambda pages: (
            layout_pages_seen.extend(int(page["page_no"]) for page in pages)
            or {"pages": []}
        ),
    )

    assert artifacts["parse_status"]["cover_page_count"] == 1
    assert layout_pages_seen == [2]
    assert all(figure["page_no"] != 1 for figure in artifacts["figures"]["figures"])


def test_parse_report_images_positioning_does_not_skip_first_page(tmp_path: Path):
    first_path = tmp_path / "01.png"
    second_path = tmp_path / "02.png"
    _write_page_image(first_path, include_chart=True)
    _write_page_image(second_path, include_chart=True)
    layout_pages_seen: list[int] = []

    artifacts = parse_report_images(
        article_id="223032",
        title="黄金持仓报告",
        published_at=None,
        image_entries=[
            {"seq": 1, "file": first_path.name, "path": str(first_path)},
            {"seq": 2, "file": second_path.name, "path": str(second_path)},
        ],
        report_type="positioning",
        vision_markdown_runner=lambda pages, figures: {"pages": []},
        vision_layout_runner=lambda pages: (
            layout_pages_seen.extend(int(page["page_no"]) for page in pages)
            or {"pages": []}
        ),
    )

    assert artifacts["parse_status"]["cover_page_count"] == 0
    assert layout_pages_seen == [1, 2]


def test_parse_report_images_vlm_detects_second_lower_chart(tmp_path: Path):
    image_path = tmp_path / "double-chart.png"
    _write_double_chart_page_image(image_path)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {"pages": []},
    )

    assert artifacts["parse_status"]["figures_total"] == 2
    assert [figure["page_no"] for figure in artifacts["figures"]["figures"]] == [2, 2]


def test_render_vision_markdown_skips_technical_indicator_pages():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at=None,
        vision_markdown={
            "pages": [
                {"page_no": 15, "status": "success", "markdown": "# 白银机构动向\n\n白银ETF已形成连续两日净流出。"},
                {
                    "page_no": 16,
                    "status": "success",
                    "markdown": "# 技术指标\n\n## 国际现货黄金\n\n### 恐惧贪婪指标（1小时）",
                },
                {
                    "page_no": 17,
                    "status": "success",
                    "markdown": "# 技术指标\n\n## 国际现货白银\n\n### 恐惧贪婪指标（1小时）",
                },
            ]
        },
    )

    assert "白银机构动向" in markdown
    assert "国际现货黄金" not in markdown
    assert "国际现货白银" not in markdown


def test_render_vision_markdown_keeps_mixed_indicator_page_when_body_exists():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at=None,
        vision_markdown={
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "markdown": (
                        "# 技术指标\n\n"
                        "## 国际现货黄金\n\n"
                        "### 恐惧贪婪指标（1小时）\n\n"
                        "不过，从更长周期看，收益率回落仍可能给黄金修复提供条件。"
                    ),
                }
            ]
        },
    )

    assert "收益率回落仍可能给黄金修复提供条件" in markdown
    assert "恐惧贪婪指标" not in markdown


def test_parse_report_images_vlm_injects_missing_second_figure_under_later_heading(tmp_path: Path):
    image_path = tmp_path / "double-chart.png"
    _write_double_chart_page_image(image_path)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 第一张图\n\n"
                        "![图表 2-1](figures/fig_p2_001.png)\n\n"
                        "说明文字。\n\n"
                        "## 第二张图"
                    ),
                }
            ]
        },
    )

    assert "figures/fig_p2_001.png" in artifacts["body_markdown"]
    assert "## 第二张图" in artifacts["body_markdown"]


def test_parse_report_images_layout_fallback_does_not_add_opencv_extra_when_markdown_has_image(tmp_path: Path):
    image_path = tmp_path / "layout-fallback.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 美国5月标普全球制造业PMI超预期上涨\n\n"
                        "![图表 2-1](figures/fig_p2_001.png)\n\n"
                        "说明文字。\n\n"
                        "## 美国5月标普全球服务业PMI陷于萎缩边缘"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "charts": [
                        {"title": "美国5月标普全球服务业PMI陷于萎缩边缘", "bbox": [80, 980, 920, 1450]},
                    ],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["figures_total"] == 1
    assert artifacts["parse_status"]["vision_layout_status"] == "success"
    assert "figures/fig_p2_001.png" in artifacts["body_markdown"]


def test_parse_report_images_layout_blocks_drive_body_markdown_and_figure_bbox(tmp_path: Path):
    image_path = tmp_path / "layout-blocks-fallback.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 美国5月标普全球制造业PMI超预期上涨\n\n"
                        "![图表 2-1](figures/fig_p2_001.png)\n\n"
                        "说明文字。\n\n"
                        "## 美国5月标普全球服务业PMI陷于萎缩边缘"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "美国5月标普全球服务业PMI陷于萎缩边缘", "bbox": [60, 900, 960, 970]},
                        {"id": "chart_001", "type": "chart", "text": "美国5月标普全球服务业PMI陷于萎缩边缘", "bbox": [80, 980, 920, 1450]},
                    ],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["figures_total"] == 1
    assert artifacts["parse_status"]["vision_layout_status"] == "success"
    assert "美国5月标普全球服务业PMI陷于萎缩边缘" in artifacts["body_markdown"]
    assert "figures/fig_p2_001.png" in artifacts["body_markdown"]


def test_parse_report_images_prefers_layout_blocks_for_text_and_charts_without_markdown_fallback(tmp_path: Path):
    image_path = tmp_path / "layout-primary.png"
    _write_page_image(image_path, include_chart=True)

    def fail_markdown_runner(*args, **kwargs):
        raise AssertionError("markdown fallback should not run when layout markdown is substantive")

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=fail_markdown_runner,
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "关键图表", "bbox": [60, 120, 900, 180]},
                        {"id": "chart_001", "type": "chart", "text": "黄金CFTC非商业持仓", "bbox": [80, 260, 920, 720]},
                        {"id": "text_001", "type": "text", "text": "价格在修复后仍需确认收盘有效性。", "bbox": [80, 760, 930, 860]},
                    ],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["vision_layout_status"] == "success"
    assert artifacts["parse_status"]["figures_total"] == 1
    assert "关键图表" in artifacts["body_markdown"]
    assert "黄金CFTC非商业持仓" in artifacts["body_markdown"]
    assert "价格在修复后仍需确认收盘有效性。" in artifacts["body_markdown"]


def test_parse_report_images_prefers_layout_blocks_before_opencv_fallback(tmp_path: Path):
    image_path = tmp_path / "layout-first.png"
    _write_page_image(image_path, include_chart=False)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": "## 关键图表\n\n## 黄金CFTC非商业持仓",
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "blocks": [
                        {"id": "chart_001", "type": "chart", "text": "黄金CFTC非商业持仓", "bbox": [80, 220, 900, 980]},
                    ],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["figures_total"] == 1
    assert artifacts["figures"]["figures"][0]["title"] in {"黄金CFTC非商业持仓", "图表 2-1"}
    assert "figures/fig_p2_001.png" in artifacts["body_markdown"]


def test_parse_report_images_does_not_keep_full_page_provisional_figure_when_layout_chart_exists(tmp_path: Path):
    image_path = tmp_path / "layout-replaces-full-page.png"
    _write_page_image(image_path, include_chart=False)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": "## 关键图表\n\n## 黄金CFTC非商业持仓",
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "chart_001", "type": "chart", "text": "黄金CFTC非商业持仓", "bbox": [80, 220, 900, 980]},
                    ],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["figures_total"] == 1
    assert artifacts["figures"]["figures"][0]["bbox"] == [80, 220, 900, 980]


def test_parse_report_images_ignores_layout_full_page_bbox_and_falls_back_to_provisional(tmp_path: Path):
    image_path = tmp_path / "layout-full-page-box.png"
    _write_page_image(image_path, include_chart=False)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": "## 关键图表\n\n## 黄金CFTC非商业持仓",
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "chart_001", "type": "chart", "text": "黄金CFTC非商业持仓", "bbox": [0, 0, 1000, 1600]},
                    ],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["figures_total"] == 1
    assert artifacts["figures"]["figures"][0]["bbox"] == [0, 0, 1000, 1600]


def test_parse_report_images_drops_full_page_provisional_when_opencv_finds_local_figures(tmp_path: Path):
    image_path = tmp_path / "opencv-replaces-full-page.png"
    _write_double_chart_page_image(image_path)

    artifacts = parse_report_images(
        article_id="220100",
        title="真实日报退化测试",
        published_at=None,
        image_entries=[{"seq": 2, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 黄金行情反复风险并未消除\n\n"
                        "![图表 2-1](figures/fig_p2_001.png)\n\n"
                        "短期反弹仍需确认。\n\n"
                        "![图表 2-2](https://example.com/chart-placeholder.png)"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "empty",
                    "image_size": {"width": 1000, "height": 2000},
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "黄金行情反复风险并未消除", "bbox": [80, 80, 900, 180]},
                    ],
                    "charts": [],
                }
            ]
        },
    )

    figures = artifacts["figures"]["figures"]
    assert artifacts["parse_status"]["figures_total"] == 1
    assert all(figure["bbox"] != [0, 0, 1000, 2000] for figure in figures)
    assert len({figure["figure_id"] for figure in figures}) == len(figures)
    assert "figures/fig_p2_001.png" in artifacts["body_markdown"]
    assert "黄金行情反复风险并未消除" in artifacts["body_markdown"]


def test_parse_report_images_ocr_fallback_replaces_empty_layout_pages(tmp_path: Path):
    page_one = tmp_path / "page-1.png"
    page_two = tmp_path / "page-2.png"
    page_three = tmp_path / "page-3.png"
    _write_page_image(page_one, include_chart=False)
    _write_page_image(page_two, include_chart=False)
    _write_page_image(page_three, include_chart=False)

    markdown_calls: list[list[int]] = []

    def fake_markdown_runner(pages, figures):
        markdown_calls.append([int(page["page_no"]) for page in pages])
        return {
            "provider": "mimo",
            "model": "mimo-v2.5",
            "pages": [
                {
                    "page_no": 3,
                    "status": "success",
                    "markdown": "## 隔夜要闻\n\n美国消费者信心回落，黄金ETF持仓变化继续影响市场定价。",
                }
            ],
        }

    artifacts = parse_report_images(
        article_id="220100",
        title="真实日报空页补 OCR 测试",
        published_at=None,
        image_entries=[
            {"seq": 1, "file": page_one.name, "path": str(page_one)},
            {"seq": 2, "file": page_two.name, "path": str(page_two)},
            {"seq": 3, "file": page_three.name, "path": str(page_three)},
        ],
        vision_markdown_runner=fake_markdown_runner,
        vision_layout_runner=lambda pages: {
            "provider": "mimo",
            "model": "mimo-v2.5",
            "pages": [
                {
                    "page_no": 1,
                    "status": "success",
                    "blocks": [{"id": "title_001", "type": "title", "text": "目录", "bbox": [1, 1, 100, 50]}],
                },
                {
                    "page_no": 2,
                    "status": "success",
                    "blocks": [{"id": "text_001", "type": "text", "text": "黄金行情反复风险并未消除。", "bbox": [1, 1, 100, 50]}],
                },
                {"page_no": 3, "status": "empty", "blocks": []},
            ],
        },
    )

    assert markdown_calls == [[2, 3]]
    assert "黄金行情反复风险并未消除" in artifacts["body_markdown"]
    assert "美国消费者信心回落" in artifacts["body_markdown"]
    assert artifacts["parse_status"]["vision_markdown_status"] == "success"
    assert "vision_markdown_full_page_ocr_primary" in artifacts["parse_status"]["warnings"]


def test_parse_report_images_layout_fallback_uses_markdown_image_count(tmp_path: Path):
    image_path = tmp_path / "layout-from-image-count.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 18, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 18,
                    "status": "success",
                    "markdown": (
                        "![图表 18-1](figures/fig_p18_001.png)\n\n"
                        "说明文字。\n\n"
                        "![图表 18-2](https://example.com/chart-placeholder.png)"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 18,
                    "status": "success",
                    "charts": [
                        {"title": "图表 18-2", "bbox": [80, 980, 920, 1450]},
                    ],
                }
            ]
        },
        vision_title_runner=lambda bands: [],
    )

    assert artifacts["parse_status"]["figures_total"] == 1
    assert "figures/fig_p18_001.png" in artifacts["body_markdown"]


def test_white_panel_detection_drops_nested_panels() -> None:
    image = np.zeros((1800, 1000, 3), dtype=np.uint8)
    image[:] = (16, 16, 24)
    cv2.rectangle(image, (100, 300), (900, 1500), (245, 245, 245), thickness=-1)
    cv2.rectangle(image, (260, 980), (760, 1220), (255, 255, 255), thickness=-1)

    panels = _detect_white_chart_panels(image)

    assert panels == [[100, 300, 901, 1501]]


def test_parse_report_images_snaps_vlm_layout_bbox_to_white_chart_panel(tmp_path: Path):
    image_path = tmp_path / "three-panel-page.png"
    _write_three_white_panel_page_image(image_path)

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 12, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 12,
                    "status": "success",
                    "markdown": (
                        "![图表 12-1](figures/fig_p12_001.png)\n\n"
                        "![图表 12-2](figures/fig_p12_002.png)\n\n"
                        "![图表 12-3](figures/fig_p12_003.png)"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 12,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 2000},
                    "blocks": [
                        {"id": "chart_001", "type": "chart", "text": "图表 12-1", "bbox": [100, 260, 900, 500]},
                        {"id": "chart_002", "type": "chart", "text": "图表 12-2", "bbox": [100, 820, 900, 1060]},
                        {"id": "table_001", "type": "table", "text": "图表 12-3", "bbox": [100, 1260, 900, 1650]},
                    ],
                }
            ]
        },
    )

    figures = artifacts["figures"]["figures"]
    assert [figure["figure_id"] for figure in figures] == ["fig_p12_001", "fig_p12_002", "fig_p12_003"]
    assert figures[2]["bbox"] == [100, 1340, 901, 1880]


def test_parse_report_images_outputs_chart_title_as_text_before_image(tmp_path: Path):
    image_path = tmp_path / "chart-title-page.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 16, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {"pages": []},
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "黄金机构动向", "bbox": [80, 160, 920, 220]},
                        {"id": "chart_001", "type": "chart", "text": "", "bbox": [80, 260, 920, 720]},
                        {"id": "text_001", "type": "text", "text": "黄金ETF最新一日转为减持。", "bbox": [80, 760, 920, 860]},
                    ],
                }
            ]
        },
    )

    assert "## 黄金机构动向\n\n![黄金机构动向](figures/fig_p16_001.png)" in artifacts["body_markdown"]


def test_parse_report_images_prefers_markdown_ocr_text_over_layout_text(tmp_path: Path):
    image_path = tmp_path / "chart-with-ocr-body-page.png"
    _write_page_image(image_path, include_chart=True)
    markdown_calls: list[list[int]] = []

    def fake_markdown_runner(pages, figures):
        markdown_calls.append([int(page["page_no"]) for page in pages])
        return {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "markdown": (
                        "## 黄金机构动向\n\n"
                        "![黄金机构动向](figures/fig_p16_001.png)\n\n"
                        "OCR识别到的图后正文应作为主来源，layout正文只作为兜底。"
                    ),
                }
            ]
        }

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 16, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=fake_markdown_runner,
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "黄金机构动向", "bbox": [80, 160, 920, 220]},
                        {"id": "chart_001", "type": "chart", "text": "", "bbox": [80, 260, 920, 720]},
                        {"id": "text_001", "type": "text", "text": "layout误识别正文。", "bbox": [80, 760, 920, 860]},
                    ],
                }
            ]
        },
    )

    assert markdown_calls == [[16]]
    assert "OCR识别到的图后正文应作为主来源" in artifacts["body_markdown"]
    assert "layout误识别正文" not in artifacts["body_markdown"]


def test_parse_report_images_default_remote_path_uses_unified_page_recognition(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "unified-page.png"
    _write_page_image(image_path, include_chart=True)
    unified_calls: list[list[int]] = []

    def fake_unified_runner(pages):
        unified_calls.append([int(page["page_no"]) for page in pages])
        return {
            "provider": "mimo",
            "model": "mimo-v2.5",
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "markdown": (
                        "## 黄金机构动向\n\n"
                        "![黄金机构动向](figures/fig_p16_001.png)\n\n"
                        "统一识别一次返回图后正文。"
                    ),
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "黄金机构动向", "bbox": [80, 160, 920, 220]},
                        {"id": "chart_001", "type": "chart", "text": "黄金机构动向", "bbox": [80, 260, 920, 720]},
                    ],
                }
            ],
        }

    monkeypatch.setattr("apps.parsers.jin10.report_image_parser.recognize_pages_unified", fake_unified_runner)

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 16, "file": image_path.name, "path": str(image_path)}],
    )

    assert unified_calls == [[16]]
    assert artifacts["figures"]["figures"][0]["bbox"] == [80, 260, 920, 720]
    assert "统一识别一次返回图后正文" in artifacts["body_markdown"]
    assert "vision_unified_page_recognition_primary" in artifacts["parse_status"]["warnings"]


def test_parse_report_images_fills_generic_titles_from_title_band_runner(tmp_path: Path):
    image_path = tmp_path / "three-panel-page.png"
    _write_three_white_panel_page_image(image_path)

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 12, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {"pages": []},
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 12,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 2000},
                    "blocks": [
                        {"id": "chart_001", "type": "chart", "text": "", "bbox": [100, 260, 900, 500]},
                        {"id": "chart_002", "type": "chart", "text": "", "bbox": [100, 820, 900, 1060]},
                        {"id": "table_001", "type": "table", "text": "", "bbox": [260, 1510, 760, 1650]},
                    ],
                }
            ]
        },
        vision_title_runner=lambda bands: [
            {"figure_id": "fig_p12_001", "title": "美国5月消费者信心指数"},
            {"figure_id": "fig_p12_002", "title": "美国1年期通胀预期"},
            {"figure_id": "fig_p12_003", "title": "市场对美联储加息的预期提前至今年12月"},
        ],
    )

    assert artifacts["figures"]["figures"][0]["title"] == "美国5月消费者信心指数"
    assert artifacts["figures"]["figures"][1]["title"] == "美国1年期通胀预期"
    assert artifacts["figures"]["figures"][2]["title"] == "市场对美联储加息的预期提前至今年12月"
    assert "## 美国5月消费者信心指数" in artifacts["body_markdown"]
    assert "图表 12-1" not in artifacts["body_markdown"]


def test_parse_report_images_chart_only_layout_page_runs_markdown_ocr_fallback(tmp_path: Path):
    image_path = tmp_path / "generic-chart-only-page.png"
    _write_page_image(image_path, include_chart=True)
    markdown_calls: list[list[int]] = []

    def fake_markdown_runner(pages, figures):
        markdown_calls.append([int(page["page_no"]) for page in pages])
        return {
            "pages": [
                {
                    "page_no": 17,
                    "status": "success",
                    "markdown": "白银机构动向\n\n![图表 17-1](figures/fig_p17_001.png)",
                }
            ]
        }

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 17, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=fake_markdown_runner,
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 17,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "chart_001", "type": "chart", "text": "", "bbox": [80, 260, 920, 720]},
                    ],
                }
            ]
        },
        vision_title_runner=lambda bands: [
            {"figure_id": "fig_p17_001", "title": "白银机构动向"},
        ],
    )

    assert markdown_calls == [[17]]
    assert "## 白银机构动向\n\n![白银机构动向](figures/fig_p17_001.png)" in artifacts["body_markdown"]
    assert artifacts["figures"]["figures"][0]["title"] == "白银机构动向"


def test_parse_report_images_chart_only_layout_page_merges_ocr_body_text(tmp_path: Path):
    image_path = tmp_path / "chart-only-with-body-page.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 16, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "markdown": (
                        "黄金机构动向\n\n"
                        "![图表 16-1](figures/fig_p16_001.png)\n\n"
                        "全球最大黄金ETF最新一日转为减持，说明短线资金回流仍不稳定。"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "黄金机构动向", "bbox": [80, 160, 920, 220]},
                        {"id": "chart_001", "type": "chart", "text": "", "bbox": [80, 260, 920, 720]},
                    ],
                }
            ]
        },
        vision_title_runner=lambda bands: [
            {"figure_id": "fig_p16_001", "title": "黄金机构动向"},
        ],
    )

    assert "## 黄金机构动向\n\n![黄金机构动向](figures/fig_p16_001.png)" in artifacts["body_markdown"]
    assert "全球最大黄金ETF最新一日转为减持" in artifacts["body_markdown"]


def test_parse_report_images_recovers_missing_local_figure_when_layout_payload_has_no_chart(tmp_path: Path):
    image_path = tmp_path / "etf-chart-page.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 16, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "markdown": (
                        "黄金机构动向\n\n"
                        "![黄金机构动向图表](https://example.com/placeholder.png)\n\n"
                        "黄金ETF最新一日转为减持。"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["figures_total"] == 1
    assert "figures/fig_p16_001.png" in artifacts["body_markdown"]
    assert "黄金ETF最新一日转为减持。" in artifacts["body_markdown"]


def test_parse_report_images_rewrites_generic_chart_title_alt_from_heading(tmp_path: Path):
    image_path = tmp_path / "generic-alt-page.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 16, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "markdown": (
                        "## 黄金机构动向\n\n"
                        "![图表标题](figures/fig_p16_001.png)\n\n"
                        "黄金ETF最新一日转为减持。"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 16,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "黄金机构动向", "bbox": [80, 160, 920, 220]},
                        {"id": "chart_001", "type": "chart", "text": "", "bbox": [80, 260, 920, 720]},
                    ],
                }
            ]
        },
    )

    assert "![黄金机构动向](figures/fig_p16_001.png)" in artifacts["body_markdown"]
    assert "![图表标题](figures/fig_p16_001.png)" not in artifacts["body_markdown"]


def test_parse_report_images_rebuilds_multi_chart_gallery_order_and_titles(tmp_path: Path):
    image_path = tmp_path / "three-panel-page.png"
    _write_three_white_panel_page_image(image_path)

    artifacts = parse_report_images(
        article_id="220100",
        title="真实日报退化测试",
        published_at=None,
        image_entries=[{"seq": 12, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {
            "pages": [
                {
                    "page_no": 12,
                    "status": "success",
                    "markdown": (
                        "## 关键图表\n\n"
                        "![图表标题](figures/fig_p12_003.png)\n\n"
                        "美国密歇根大学消费者信心指数终值再创新低\n\n"
                        "![图表标题](figures/fig_p12_001.png)\n\n"
                        "美国5月1年期通胀预期终值上升\n\n"
                        "![图表标题](figures/fig_p12_002.png)\n\n"
                        "市场对美联储加息的预期提前至今年12月上周五公布的美国5月密歇根大学消费者信心指数终值录得44.8。"
                    ),
                }
            ]
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 12,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 2000},
                    "blocks": [
                        {"id": "title_001", "type": "title", "text": "关键图表", "bbox": [60, 120, 900, 180]},
                        {"id": "chart_001", "type": "chart", "text": "美国密歇根大学消费者信心指数终值再创新低", "bbox": [100, 260, 900, 500]},
                        {"id": "chart_002", "type": "chart", "text": "美国5月1年期通胀预期终值上升", "bbox": [100, 820, 900, 1060]},
                        {"id": "table_001", "type": "table", "text": "市场对美联储加息的预期提前至今年12月", "bbox": [260, 1510, 760, 1650]},
                    ],
                }
            ]
        },
    )

    markdown = artifacts["body_markdown"]

    assert "![图表标题]" not in markdown
    assert "市场对美联储加息的预期提前至今年12月上周五公布" not in markdown
    assert markdown.index("## 美国密歇根大学消费者信心指数终值再创新低") < markdown.index("![美国密歇根大学消费者信心指数终值再创新低](figures/fig_p12_001.png)")
    assert markdown.index("## 美国5月1年期通胀预期终值上升") < markdown.index("![美国5月1年期通胀预期终值上升](figures/fig_p12_002.png)")
    assert markdown.index("## 市场对美联储加息的预期提前至今年12月") < markdown.index("![市场对美联储加息的预期提前至今年12月](figures/fig_p12_003.png)")
    assert markdown.index("figures/fig_p12_001.png") < markdown.index("figures/fig_p12_002.png") < markdown.index("figures/fig_p12_003.png")
    assert "上周五公布的美国5月密歇根大学消费者信心指数终值录得44.8。" in markdown


def test_render_vision_markdown_strips_jin10_vip_suffix_from_title():
    markdown = render_vision_markdown(
        title="黄金行情反复风险并未消除，不可将反弹视为反攻信号-金十数据VIP",
        published_at=None,
        vision_markdown={
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": "## 行情回顾\n\n测试正文。",
                }
            ]
        },
    )

    assert markdown.startswith("# 黄金行情反复风险并未消除，不可将反弹视为反攻信号\n\n")
    assert "-金十数据VIP" not in markdown


def test_normalize_vision_markdown_payload_drops_chart_date_heading_and_prefers_specific_heading():
    normalized = _normalize_vision_markdown_payload(
        {
            "pages": [
                {
                    "page_no": 15,
                    "status": "success",
                    "markdown": (
                        "## 白银CFTC投机性净多仓反弹终端\n\n"
                        "### 20260519\n\n"
                        "![CFTC商品类净/空/多头仓位](figures/fig_p15_001.png)\n"
                    ),
                }
            ]
        },
        [
            {
                "figure_id": "fig_p15_001",
                "page_no": 15,
                "bbox": [0, 0, 10, 10],
                "chart_image_path": "figures/fig_p15_001.png",
                "title": "白银CFTC投机性净多仓反弹终端",
            }
        ],
    )

    page_markdown = normalized["pages"][0]["markdown"]

    assert "20260519" not in page_markdown
    assert "![白银CFTC投机性净多仓反弹终端](figures/fig_p15_001.png)" in page_markdown
    assert "![CFTC商品类净/空/多头仓位](figures/fig_p15_001.png)" not in page_markdown


def test_render_vision_markdown_normalizes_nested_hash_heading_prefix():
    markdown = render_vision_markdown(
        title="测试报告",
        published_at=None,
        vision_markdown={
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": "## # Phoenix Futures总裁Kevin Grady\n\n测试正文。",
                }
            ]
        },
    )

    assert "## Phoenix Futures总裁Kevin Grady" in markdown
    assert "## # Phoenix Futures总裁Kevin Grady" not in markdown


def test_normalize_vision_markdown_payload_uses_section_heading_for_late_generic_chart_alt():
    normalized = _normalize_vision_markdown_payload(
        {
            "pages": [
                {
                    "page_no": 14,
                    "status": "success",
                    "markdown": (
                        "## 黄金CFTC投机性头多减持\n\n"
                        "截至5月19日当周，黄金投机性净多头仓位下降。\n\n"
                        "![图表标题](figures/fig_p14_001.png)\n"
                    ),
                }
            ]
        },
        [
            {
                "figure_id": "fig_p14_001",
                "page_no": 14,
                "bbox": [0, 0, 10, 10],
                "chart_image_path": "figures/fig_p14_001.png",
                "title": "图表标题",
            }
        ],
    )

    page_markdown = normalized["pages"][0]["markdown"]

    assert "![黄金CFTC投机性头多减持](figures/fig_p14_001.png)" in page_markdown
    assert "![图表标题](figures/fig_p14_001.png)" not in page_markdown


def test_parse_report_images_filters_fear_greed_indicator_layout_page(tmp_path: Path):
    image_path = tmp_path / "fear-greed-page.png"
    _write_page_image(image_path, include_chart=True)

    artifacts = parse_report_images(
        article_id="220100",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 19, "file": image_path.name, "path": str(image_path)}],
        vision_markdown_runner=lambda pages, figures: {"pages": []},
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 19,
                    "status": "success",
                    "image_size": {"width": 1000, "height": 1600},
                    "blocks": [
                        {"id": "chart_001", "type": "chart", "text": "恐惧贪婪指标（1小时）", "bbox": [120, 260, 880, 720]},
                        {"id": "chart_002", "type": "chart", "text": "恐惧贪婪指标（1日）", "bbox": [120, 800, 880, 1240]},
                        {
                            "id": "text_001",
                            "type": "text",
                            "text": "说明：50为中性，数值越高说明市场越贪婪，超过70后需小心下跌风险；数值越低则表明市场越恐惧，低于30则需小心反弹风险。",
                            "bbox": [80, 1300, 920, 1440],
                        },
                    ],
                }
            ]
        },
    )

    assert artifacts["parse_status"]["figures_total"] == 0
    assert "恐惧贪婪" not in artifacts["body_markdown"]


def test_normalize_layout_blocks_supports_block_schema():
    blocks = _normalize_layout_blocks(
        {
            "image_size": {"width": 1227, "height": 741},
            "blocks": [
                {"id": "title_001", "type": "title", "text": "关键图表", "bbox": [40, 20, 500, 120]},
                {"id": "chart_001", "type": "chart", "text": "黄金CFTC非商业持仓", "bbox": [50, 150, 1100, 620]},
                {"id": "unknown_001", "type": "weird", "text": "", "bbox": [20, 650, 200, 720]},
            ],
        },
        page_width=1227,
        page_height=741,
    )

    assert [block["type"] for block in blocks] == ["title", "chart"]
    assert blocks[1]["text"] == "黄金CFTC非商业持仓"


def test_normalize_layout_blocks_scales_payload_coordinate_space_to_page_size():
    blocks = _normalize_layout_blocks(
        {
            "image_size": {"width": 1000, "height": 500},
            "blocks": [
                {"id": "chart_001", "type": "chart", "text": "缩放图表", "bbox": [100, 50, 900, 450]},
            ],
        },
        page_width=2000,
        page_height=1000,
    )

    assert blocks[0]["bbox"] == [200, 100, 1800, 900]


def test_normalize_layout_blocks_infers_normalized_1000_coordinate_space():
    blocks = _normalize_layout_blocks(
        {
            "image_size": {"width": 2160, "height": 3839},
            "blocks": [
                {"id": "chart_001", "type": "chart", "text": "黄金机构动向", "bbox": [72, 132, 932, 389]},
            ],
        },
        page_width=2160,
        page_height=3839,
    )

    assert blocks[0]["bbox"] == [156, 507, 2013, 1493]


def test_normalize_layout_blocks_backfills_from_legacy_charts_schema():
    blocks = _normalize_layout_blocks(
        {
            "charts": [
                {"chart_id": "chart_001", "title": "黄金净多头", "bbox": [50, 100, 500, 400]},
            ]
        },
        page_width=1000,
        page_height=800,
    )

    assert len(blocks) == 1
    assert blocks[0]["id"] == "chart_001"
    assert blocks[0]["type"] == "chart"
    assert blocks[0]["text"] == "黄金净多头"


def test_normalize_page_markdown_strips_visual_noise_lines():
    markdown = normalize_page_markdown(
        "即时市场展望\n\n每日市场观察\n\n图12\n\n正文第一段。",
        [],
    )

    assert "即时市场展望" not in markdown
    assert "每日市场观察" not in markdown
    assert "图12" not in markdown
    assert "正文第一段。" in markdown


def test_normalize_page_markdown_dedupes_duplicate_figure_lines():
    markdown = normalize_page_markdown(
        "![图表 3-2](figures/fig_p3_002.png)\n\n![图表 3-2 - 图表 3-1](figures/fig_p3_002.png)\n\n正文说明。",
        [{"chart_image_path": "figures/fig_p3_002.png", "title": "图表 3-2"}],
    )

    assert markdown.count("figures/fig_p3_002.png") == 1
    assert "正文说明。" in markdown


def test_normalize_page_markdown_adds_blank_line_after_figure():
    markdown = normalize_page_markdown(
        "![图表 1](figures/fig_p1_001.png)\n正文说明。",
        [{"chart_image_path": "figures/fig_p1_001.png", "title": "图表 1"}],
    )

    assert "![图表 1](figures/fig_p1_001.png)\n\n正文说明。" in markdown


def test_image_to_data_url_reencodes_local_image_as_png(tmp_path: Path):
    image_path = tmp_path / "sample.jpg"
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[:] = (30, 120, 220)
    assert cv2.imwrite(str(image_path), image)

    encoded = _image_to_data_url(image_path)

    assert encoded.data_url.startswith("data:image/png;base64,")
    assert (encoded.width, encoded.height) == (64, 64)


def test_image_to_data_url_resizes_vlm_page_and_uses_high_quality_jpeg(tmp_path: Path):
    image_path = tmp_path / "report-page.jpg"
    image = np.random.randint(0, 255, (2000, 1000, 3), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image)

    encoded = _image_to_data_url(image_path, max_long_edge=1000, jpeg_quality=92)

    assert encoded.data_url.startswith("data:image/jpeg;base64,")
    assert (encoded.width, encoded.height) == (500, 1000)


def test_image_to_data_url_reuses_vlm_ready_jpeg_bytes(tmp_path: Path):
    image_path = tmp_path / "page-001.jpg"
    image = np.full((120, 200, 3), (30, 120, 220), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    original = image_path.read_bytes()

    encoded = _image_to_data_url(image_path, max_long_edge=2800, jpeg_quality=92)

    payload = encoded.data_url.split(",", 1)[1]
    assert base64.b64decode(payload) == original
    assert (encoded.width, encoded.height) == (200, 120)


def test_image_to_data_url_falls_back_to_jpeg_when_png_data_url_is_too_large(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "noise.png"
    image = np.random.randint(0, 255, (512, 512, 3), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image)

    monkeypatch.setattr("apps.parsers.jin10.vision_recognition_agent.agent.MAX_IMAGE_DATA_URL_CHARS", 200_000)

    encoded = _image_to_data_url(image_path)

    assert encoded.data_url.startswith("data:image/jpeg;base64,")
    assert len(encoded.data_url) <= 200_000
    assert encoded.width > 0
    assert encoded.height > 0


def test_image_to_data_url_rejects_oversized_raw_image_payload(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "broken.png"
    image_path.write_bytes(b"not a real png" * 10_000)
    monkeypatch.setattr("apps.parsers.jin10.vision_recognition_agent.agent.MAX_IMAGE_DATA_URL_CHARS", 2_000)

    try:
        _image_to_data_url(image_path)
    except ValueError as exc:
        assert str(exc) == "encoded_image_exceeds_data_uri_limit"
    else:
        raise AssertionError("expected oversized raw image payload to be rejected")


def test_image_to_data_url_rejects_unsupported_raw_image_format(tmp_path: Path):
    image_path = tmp_path / "page.bin"
    image_path.write_bytes(b"not an image")

    try:
        _image_to_data_url(image_path)
    except ValueError as exc:
        assert str(exc) == "image_not_decodable_or_unsupported_format"
    else:
        raise AssertionError("expected unsupported raw image payload to be rejected")


def test_recognize_page_layout_returns_unavailable_on_image_encoding_failure(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "page.bin"
    image_path.write_bytes(b"not an image")
    client = VisionMarkdownClient(provider="mimo", model="mimo-v2.5")
    monkeypatch.setattr("apps.parsers.jin10.vision_recognition_agent.agent.MAX_IMAGE_DATA_URL_CHARS", 2_000)

    result = client.recognize_page_layout(
        image_path=image_path,
        page_no=1,
        page_width=1000,
        page_height=1400,
    )

    assert result["status"] == "unavailable"
    assert result["reason"] == "image_not_decodable_or_unsupported_format"
    assert result["blocks"] == []


def test_recognize_pages_as_markdown_uses_page_cache(monkeypatch, tmp_path: Path):
    cache_dir = tmp_path / "vision-cache"
    image_path = tmp_path / "page.png"
    _write_page_image(image_path, include_chart=True)
    monkeypatch.setenv("JIN10_VISION_CACHE_DIR", str(cache_dir))
    client = _FakeVisionClient()
    pages = [{"page_no": 1, "image_path": str(image_path)}]
    figures = [{"page_no": 1, "chart_image_path": "figures/fig_p1_001.png", "title": "黄金持仓"}]

    first = recognize_pages_as_markdown(pages, figures, client=client)
    second = recognize_pages_as_markdown(pages, figures, client=client)

    assert client.markdown_calls == 1
    assert first == second
    assert first["provider"] == client.provider
    assert first["pages"][0]["markdown"] == "## 第1页\n\n缓存测试"
    assert list((cache_dir / "markdown" / "mimo-v2.5").glob("page_001_*.json"))


def test_recognize_pages_layout_uses_page_cache(monkeypatch, tmp_path: Path):
    cache_dir = tmp_path / "vision-cache"
    image_path = tmp_path / "page.png"
    _write_page_image(image_path, include_chart=True)
    monkeypatch.setenv("JIN10_VISION_CACHE_DIR", str(cache_dir))
    client = _FakeVisionClient()
    pages = [
        {
            "page_no": 1,
            "image_path": str(image_path),
            "width": 1000,
            "height": 1400,
            "expected_chart_count": 1,
            "hint_titles": ["黄金持仓"],
        }
    ]

    first = recognize_pages_layout(pages, client=client)
    second = recognize_pages_layout(pages, client=client)

    assert client.layout_calls == 1
    assert first == second
    assert first["provider"] == client.provider
    assert first["pages"][0]["blocks"][0]["type"] == "chart"
    assert first["pages"][0]["charts"][0]["bbox"] == [80, 260, 920, 720]
    assert list((cache_dir / "layout" / "mimo-v2.5").glob("page_001_*.json"))


def test_recognize_pages_unified_uses_page_cache(monkeypatch, tmp_path: Path):
    cache_dir = tmp_path / "vision-cache"
    image_path = tmp_path / "page.png"
    _write_page_image(image_path, include_chart=True)
    monkeypatch.setenv("JIN10_VISION_CACHE_DIR", str(cache_dir))
    client = _FakeVisionClient()
    pages = [{"page_no": 1, "image_path": str(image_path), "width": 1000, "height": 1400}]

    first = recognize_pages_unified(pages, client=client)
    second = recognize_pages_unified(pages, client=client)

    assert client.unified_calls == 1
    assert first == second
    assert first["provider"] == client.provider
    assert first["pages"][0]["markdown"] == "## 黄金持仓\n\n![黄金持仓](figures/fig_p1_001.png)\n\n统一识别正文"
    assert first["pages"][0]["blocks"][0]["type"] == "chart"
    assert list((cache_dir / "unified" / "mimo-v2.5").glob("page_001_*.json"))


def test_recognize_pages_unified_cache_is_scoped_by_report_type(monkeypatch, tmp_path: Path):
    cache_dir = tmp_path / "vision-cache"
    image_path = tmp_path / "page.png"
    _write_page_image(image_path, include_chart=True)
    monkeypatch.setenv("JIN10_VISION_CACHE_DIR", str(cache_dir))
    client = _FakeVisionClient()
    pages = [{"page_no": 1, "image_path": str(image_path), "width": 1000, "height": 1400}]

    recognize_pages_unified(pages, client=client, report_type="positioning")
    recognize_pages_unified(pages, client=client, report_type="positioning")
    recognize_pages_unified(pages, client=client, report_type="technical_levels")

    assert client.unified_calls == 2
    assert client.unified_report_types == ["positioning", "technical_levels"]
    assert len(list((cache_dir / "unified" / "mimo-v2.5").glob("page_001_*.json"))) == 2


def test_normalize_chart_bbox_accepts_short_white_chart_on_tall_page():
    bbox = _normalize_chart_bbox(
        [72, 183, 932, 444],
        page_width=2160,
        page_height=3839,
    )

    assert bbox == [72, 183, 932, 444]


def test_parse_report_images_can_run_with_vlm_only(tmp_path: Path):
    image_path = tmp_path / "vlm-page.png"
    _write_page_image(image_path, include_chart=True)

    def fake_vision(pages, figures):
        assert len(pages) == 1
        assert figures
        return {
            "provider": "mimo",
            "model": "mimo-v2.5",
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": (
                        "## 美国初请人数维持下行趋势\n\n"
                        "![图表](figures/fig_p2_001.png)\n\n"
                        "美国至5月16日当周初请失业金人数录得20.9万人。"
                    ),
                }
            ],
        }

    artifacts = parse_report_images(
        article_id="219948",
        title="测试报告",
        published_at=None,
        image_entries=[{"seq": 2, "file": "vlm-page.png", "path": str(image_path)}],
        vision_markdown_runner=fake_vision,
    )

    assert artifacts["parse_status"]["recognition_mode"] == "vlm"
    assert artifacts["parse_status"]["figures_total"] == 0
    assert artifacts["parse_status"]["vision_markdown_status"] == "failed"
    assert artifacts["body_markdown"].strip() == "# 测试报告"



class _FakeVisionClient:
    provider = "mimo"
    model = "mimo-v2.5"

    def __init__(self) -> None:
        self.markdown_calls = 0
        self.layout_calls = 0
        self.unified_calls = 0
        self.markdown_report_types: list[str | None] = []
        self.unified_report_types: list[str | None] = []

    def recognize_page_markdown(
        self,
        *,
        image_path: Path,
        page_no: int,
        figures: list[dict],
        report_type: str | None = None,
    ) -> dict:
        self.markdown_calls += 1
        self.markdown_report_types.append(report_type)
        assert image_path.is_file()
        assert figures
        return {
            "page_no": page_no,
            "status": "success",
            "markdown": f"## 第{page_no}页\n\n缓存测试",
            "model": self.model,
        }

    def recognize_page_layout(
        self,
        *,
        image_path: Path,
        page_no: int,
        page_width: int,
        page_height: int,
        expected_chart_count: int = 0,
        hint_titles: list[str] | None = None,
    ) -> dict:
        self.layout_calls += 1
        assert image_path.is_file()
        assert page_width == 1000
        assert page_height == 1400
        assert expected_chart_count == 1
        assert hint_titles == ["黄金持仓"]
        return {
            "page_no": page_no,
            "status": "success",
            "image_size": {"width": page_width, "height": page_height},
            "blocks": [{"id": "chart_001", "type": "chart", "text": "黄金持仓", "bbox": [80, 260, 920, 720]}],
            "charts": [{"chart_id": "vlm_p1_001", "title": "黄金持仓", "bbox": [80, 260, 920, 720]}],
            "model": self.model,
        }

    def recognize_page_unified(
        self,
        *,
        image_path: Path,
        page_no: int,
        page_width: int,
        page_height: int,
        report_type: str | None = None,
    ) -> dict:
        self.unified_calls += 1
        self.unified_report_types.append(report_type)
        assert image_path.is_file()
        assert page_width == 1000
        assert page_height == 1400
        return {
            "page_no": page_no,
            "status": "success",
            "image_size": {"width": page_width, "height": page_height},
            "markdown": "## 黄金持仓\n\n![黄金持仓](figures/fig_p1_001.png)\n\n统一识别正文",
            "blocks": [{"id": "chart_001", "type": "chart", "text": "黄金持仓", "bbox": [80, 260, 920, 720]}],
            "charts": [{"chart_id": "vlm_p1_001", "title": "黄金持仓", "bbox": [80, 260, 920, 720]}],
            "model": self.model,
        }


def _write_page_image(path: Path, *, include_chart: bool) -> None:
    image = np.zeros((1600, 1000, 3), dtype=np.uint8)
    image[:] = (16, 16, 24)
    cv2.rectangle(image, (0, 0), (999, 120), (28, 28, 36), thickness=-1)
    if include_chart:
        cv2.rectangle(image, (60, 260), (940, 720), (34, 34, 42), thickness=2)
        cv2.line(image, (90, 680), (900, 320), (240, 240, 240), thickness=3)
        cv2.line(image, (90, 620), (900, 500), (200, 200, 200), thickness=3)
    cv2.imwrite(str(path), image)


def _write_double_chart_page_image(path: Path) -> None:
    image = np.zeros((2000, 1000, 3), dtype=np.uint8)
    image[:] = (16, 16, 24)
    cv2.rectangle(image, (0, 0), (999, 120), (28, 28, 36), thickness=-1)
    cv2.rectangle(image, (60, 220), (940, 760), (245, 245, 245), thickness=-1)
    cv2.rectangle(image, (60, 1240), (940, 1780), (245, 245, 245), thickness=-1)
    cv2.putText(image, "chart1", (120, 520), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (80, 80, 80), 4)
    cv2.putText(image, "chart2", (120, 1540), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (80, 80, 80), 4)
    cv2.imwrite(str(path), image)


def _write_three_white_panel_page_image(path: Path) -> None:
    image = np.zeros((2000, 1000, 3), dtype=np.uint8)
    image[:] = (16, 16, 24)
    cv2.putText(image, "chart title 1", (100, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (190, 190, 190), 3)
    cv2.rectangle(image, (100, 220), (900, 620), (245, 245, 245), thickness=-1)
    cv2.putText(image, "chart title 2", (100, 740), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (190, 190, 190), 3)
    cv2.rectangle(image, (100, 780), (900, 1180), (245, 245, 245), thickness=-1)
    cv2.putText(image, "chart title 3", (100, 1300), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (190, 190, 190), 3)
    cv2.rectangle(image, (100, 1340), (900, 1880), (245, 245, 245), thickness=-1)
    cv2.imwrite(str(path), image)


def _rect_points(left: int, top: int, right: int, bottom: int) -> list[list[float]]:
    return [
        [float(left), float(top)],
        [float(right), float(top)],
        [float(right), float(bottom)],
        [float(left), float(bottom)],
    ]


def _scaled_rect_points(left: int, top: int, right: int, bottom: int, scale: float = 1.5) -> list[list[float]]:
    return _rect_points(
        int(left * scale),
        int(top * scale),
        int(right * scale),
        int(bottom * scale),
    )


def test_parse_report_images_preserves_cover_identity_without_rendering_it_into_body(tmp_path: Path):
    cover_path = tmp_path / "cover.png"
    body_path = tmp_path / "body.png"
    _write_page_image(cover_path, include_chart=False)
    _write_page_image(body_path, include_chart=False)

    def recognize_cover(pages, *, preserve_cover_identity=False):
        assert preserve_cover_identity is True
        return {
            "provider": "fixture",
            "model": "fixture-vl",
            "pages": [
                {
                    "page_no": 1,
                    "status": "success",
                    "markdown": (
                        "黄金 投资者周报\n\n"
                        "黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成"
                    ),
                    "blocks": [
                        {"id": "title", "type": "title", "text": "黄金 投资者周报", "bbox": [0, 0, 100, 20]},
                        {"id": "theme", "type": "text", "text": "黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成", "bbox": [0, 20, 100, 40]},
                    ],
                }
            ],
        }

    artifacts = parse_report_images(
        article_id="224284",
        title="黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成",
        published_at="2026-07-11T00:00:00+00:00",
        report_type="weekly",
        image_entries=[
            {"seq": 1, "file": cover_path.name, "path": str(cover_path)},
            {"seq": 2, "file": body_path.name, "path": str(body_path)},
        ],
        vision_cover_runner=recognize_cover,
        vision_markdown_runner=lambda pages, figures: {
            "provider": "fixture",
            "model": "fixture-vl",
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "markdown": "## 周度判断\n\n周度区间仍待突破。",
                }
            ],
        },
        vision_layout_runner=lambda pages: {
            "pages": [
                {
                    "page_no": 2,
                    "status": "success",
                    "blocks": [
                        {"id": "body", "type": "text", "text": "周度区间仍待突破。", "bbox": [0, 0, 100, 20]},
                    ],
                }
            ]
        },
    )

    assert artifacts["cover_page"]["page_no"] == 1
    assert "黄金 投资者周报" in artifacts["cover_page"]["recognized_text"]
    assert "期权暗示阶段性底部形成" in artifacts["cover_page"]["recognized_text"]
    assert "周度区间仍待突破" in artifacts["body_markdown"]
    assert "黄金 投资者周报" not in artifacts["body_markdown"]

    written = write_parse_artifacts(artifacts, tmp_path / "parsed")
    assert json.loads(Path(written["cover_page"]).read_text(encoding="utf-8"))["page_no"] == 1
