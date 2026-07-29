from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from apps.collectors.jin10.adapter import collect_raw_index
from apps.collectors.jin10.reportory import (
    Jin10ReportoryDailyGoldPage,
    _normalize_daily_gold_published_at,
    _validate_daily_gold_report_data,
    parse_reportory_daily_gold_entries,
    parse_reportory_market_odds_entries,
    render_reportory_daily_gold_markdown,
    reportory_daily_gold_report_date,
    reportory_daily_gold_report_id,
    reportory_report_id,
    write_reportory_daily_gold_report,
)


def test_parse_reportory_market_odds_entries_extracts_structured_link_and_time() -> None:
    html = """
    <div class="jin10vip-c-news-item-flex-body">
      <div class="jin10vip-category-title">
        <a href="https://reportory.jin10.com/jin10-report-hub/v2/market-report/market-odds-report/2026/07/22/20260722T062313Z-a706a018.html">
          加息尾部升温压过宽松预期｜市场赔率数据表
        </a>
      </div>
      <div class="jin10vip-c-news-item-flex-introduction">贵金属上沿修复。</div>
      <span data-time="2026-07-22 14:25:56"></span>
    </div>
    """

    entries = parse_reportory_market_odds_entries(html)

    assert len(entries) == 1
    assert entries[0].article_id == "20260722T062313Z-a706a018"
    assert entries[0].published_at == "2026-07-22 14:25:56"
    assert entries[0].title == "加息尾部升温压过宽松预期｜市场赔率数据表"
    assert entries[0].summary == "贵金属上沿修复。"


def test_reportory_report_id_rejects_non_jin10_or_non_odds_urls() -> None:
    with pytest.raises(ValueError, match="url_invalid"):
        reportory_report_id("https://example.com/market-odds-report/unsafe.html")
    with pytest.raises(ValueError, match="url_invalid"):
        reportory_report_id("https://reportory.jin10.com/other/report.html")


def test_parse_reportory_daily_gold_entries_ignores_sibling_report_series() -> None:
    html = """
    <div class="jin10vip-c-news-item-flex-body">
      <a href="https://reportory.jin10.com/jin10-report-hub/v2/market-report/vip-gold-headlines/2026/07/28/20260728T033809Z-ca7f8a26.html">
        黄金头条
      </a>
      <span data-time="2026-07-28 11:40:00"></span>
    </div>
    <div class="jin10vip-c-news-item-flex-body">
      <a href="https://reportory.jin10.com/jin10-report-hub/v2/market-report/daily-gold-silver-report/2026/07/28/20260728T025217Z-9958b921.html">
        黄金上涨“体验卡”到期——新版发布
      </a>
      <div class="jin10vip-c-news-item-flex-introduction">每日金银报告摘要。</div>
      <span data-time="2026-07-28 10:54:01"></span>
    </div>
    """

    entries = parse_reportory_daily_gold_entries(html)

    assert len(entries) == 1
    assert entries[0].article_id == "20260728T025217Z-9958b921"
    assert entries[0].published_at == "2026-07-28 10:54:01"
    assert entries[0].summary == "每日金银报告摘要。"
    assert reportory_daily_gold_report_id(entries[0].source_url) == entries[0].article_id
    assert reportory_daily_gold_report_date(entries[0].source_url) == "2026-07-28"


def test_daily_gold_contract_fails_closed_on_date_or_page_mismatch() -> None:
    url = (
        "https://reportory.jin10.com/jin10-report-hub/v2/market-report/"
        "daily-gold-silver-report/2026/07/28/20260728T025217Z-9958b921.html"
    )
    payload = {
        "schema_version": 3,
        "task_id": "daily-gold-silver-report",
        "report_date": "2026-07-29",
    }

    with pytest.raises(RuntimeError, match="date_mismatch"):
        _validate_daily_gold_report_data(
            report_data=payload,
            render_state={"ready": True, "pageCount": 1},
            page_count=1,
            source_url=url,
        )

    payload["report_date"] = "2026-07-28"
    with pytest.raises(RuntimeError, match="page_count_mismatch"):
        _validate_daily_gold_report_data(
            report_data=payload,
            render_state={"ready": True, "pageCount": 2},
            page_count=1,
            source_url=url,
        )


def test_daily_gold_published_at_normalizes_listing_time_and_rejects_relative_time() -> None:
    report_id = "20260728T025217Z-9958b921"

    assert _normalize_daily_gold_published_at(
        "07-28 10:54",
        report_date="2026-07-28",
        report_id=report_id,
    ) == "2026-07-28T10:54:00+08:00"
    assert _normalize_daily_gold_published_at(
        "7小时前",
        report_date="2026-07-28",
        report_id=report_id,
    ) == "2026-07-28T10:52:17+08:00"


def test_write_daily_gold_report_preserves_structured_data_and_page_evidence(tmp_path) -> None:
    image = np.zeros((24, 32, 3), dtype=np.uint8)
    image[:, :] = (80, 40, 20)
    encoded, buffer = cv2.imencode(".jpg", image)
    assert encoded
    payload = {
        "schema_version": 3,
        "task_id": "daily-gold-silver-report",
        "report_date": "2026-07-28",
        "title": "每日金银报告｜测试报告",
        "lead": "测试导语",
        "market_review": [{"metal": "黄金", "instrument": "XAUUSD", "close": 4076.61, "summary": "黄金收涨。"}],
        "overnight_news": [{"title": "隔夜事件", "summary": "事件摘要。"}],
        "today_focus": [{"beijing_time": "20:30", "event": "美国数据"}],
        "analyses": [{"source_name": "分析师", "viewpoint": "条件性看多。", "paragraphs": ["关注确认信号。"]}],
        "etf_tracking": [{"fund": "GLD", "trust": 900, "change": 0}],
        "sentiment_gauges": [{"metal": "黄金", "score": 55, "label": "中性"}],
        "charts": [{"title": "测试图表", "description": "图表说明", "image": "data:image/png;base64,do-not-copy"}],
        "quality_status": "attention_required",
    }
    report = Jin10ReportoryDailyGoldPage(
        report_id="20260728T025217Z-9958b921",
        report_date="2026-07-28",
        title=payload["title"],
        published_at="2026-07-28 10:54:01",
        source_url=(
            "https://reportory.jin10.com/jin10-report-hub/v2/market-report/"
            "daily-gold-silver-report/2026/07/28/20260728T025217Z-9958b921.html"
        ),
        raw_html="<html><body>rendered report</body></html>",
        report_data=payload,
        page_images=(buffer.tobytes(), buffer.tobytes()),
    )

    markdown = render_reportory_daily_gold_markdown(report)
    report_dir = write_reportory_daily_gold_report(report, external_root=tmp_path)

    assert "## 行情回顾" in markdown
    assert "## 原始报告逐页快照" in markdown
    assert "data:image/png" not in markdown
    assert [line for line in markdown.splitlines() if line.startswith("![原始报告第")] == [
        "![原始报告第 1 页](images/page-001.jpg)",
        "![原始报告第 2 页](images/page-002.jpg)",
    ]
    assert (report_dir / "detail.html").is_file()
    assert (report_dir / "report_data.json").is_file()
    assert (report_dir / "images/page-001.jpg").is_file()
    assert (report_dir / "images/page-002.jpg").is_file()
    meta = json.loads((report_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["report_type"] == "daily"
    assert meta["source_format"] == "reportory_daily_gold_silver_v3"
    assert meta["images"][0]["url"].endswith("#page-1")
    assert len(meta["images"]) == 2
    assert meta["images"][0]["path"] == str(report_dir / "images/page-001.jpg")
    raw_index = collect_raw_index(tmp_path, "2026-07-28", "270")
    assert raw_index["reports"][0]["article_id"] == "20260728T025217Z-9958b921"
    assert raw_index["reports"][0]["report_type"] == "daily"

    with pytest.raises(FileExistsError, match="artifact_exists"):
        write_reportory_daily_gold_report(report, external_root=tmp_path)


def test_write_daily_gold_report_cleans_staging_after_failure_and_allows_retry(tmp_path, monkeypatch) -> None:
    report = Jin10ReportoryDailyGoldPage(
        report_id="20260728T025217Z-9958b921",
        report_date="2026-07-28",
        title="每日金银报告",
        published_at="2026-07-28T10:54:01+08:00",
        source_url=(
            "https://reportory.jin10.com/jin10-report-hub/v2/market-report/"
            "daily-gold-silver-report/2026/07/28/20260728T025217Z-9958b921.html"
        ),
        raw_html="<html></html>",
        report_data={},
        page_images=(),
    )
    report_dir = tmp_path / "2026-07-28" / "daily" / report.report_id

    monkeypatch.setattr(
        "apps.collectors.jin10.reportory._write_card_images",
        lambda **_: (_ for _ in ()).throw(RuntimeError("write failed")),
    )
    with pytest.raises(RuntimeError, match="write failed"):
        write_reportory_daily_gold_report(report, external_root=tmp_path)

    assert not report_dir.exists()
    assert not list(report_dir.parent.glob(f".{report.report_id}.*"))

    monkeypatch.undo()
    assert write_reportory_daily_gold_report(report, external_root=tmp_path) == report_dir
    assert report_dir.is_dir()


def test_write_daily_gold_report_rejects_non_directory_external_root(tmp_path) -> None:
    external_root = tmp_path / "not-a-directory"
    external_root.write_text("not a directory", encoding="utf-8")
    report = Jin10ReportoryDailyGoldPage(
        report_id="20260728T025217Z-9958b921",
        report_date="2026-07-28",
        title="每日金银报告",
        published_at="2026-07-28T10:54:01+08:00",
        source_url=(
            "https://reportory.jin10.com/jin10-report-hub/v2/market-report/"
            "daily-gold-silver-report/2026/07/28/20260728T025217Z-9958b921.html"
        ),
        raw_html="<html></html>",
        report_data={},
        page_images=(),
    )

    with pytest.raises(ValueError, match="external_root_not_directory"):
        write_reportory_daily_gold_report(report, external_root=external_root)
