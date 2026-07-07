from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

from apps.collectors.news import jin10_detail_fetcher
from apps.collectors.news.jin10_detail_fetcher import RenderedDetailPage, fetch_jin10_detail_page


class FakeDetailClient:
    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append(url)
        response = self.responses[url]
        if response.request is None:
            response.request = httpx.Request("GET", url)
        return response


def _html_response(url: str, html: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=html,
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", url),
    )


def _image_response(url: str, *, width: int, height: int) -> httpx.Response:
    rng = np.random.default_rng(seed=width * 1000 + height)
    image = rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return httpx.Response(
        200,
        content=encoded.tobytes(),
        headers={"content-type": "image/png"},
        request=httpx.Request("GET", url),
    )


def test_fetch_jin10_detail_page_extracts_text_and_archives_html(tmp_path: Path) -> None:
    url = "https://xnews.jin10.com/details/221682?j=test"
    image_url = "https://cdn.jin10.com/chart.png"
    html = f"""
    <html>
      <head><title>霍尔木兹海峡一旦重开-金十数据</title></head>
      <body>
        <h1>霍尔木兹海峡一旦重开</h1>
        <p>若霍尔木兹海峡全面复航，海湾各国可能增加出口。</p>
        <img src="{image_url}" />
      </body>
    </html>
    """
    client = FakeDetailClient({
        url: _html_response(url, html),
        image_url: _image_response(image_url, width=900, height=500),
    })

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
        run_vlm=False,
    )

    assert result.status == "fetched"
    assert result.access_status == "readable"
    assert result.source_key == "jin10_xnews_public"
    assert result.access_method == "http_document"
    assert result.title == "霍尔木兹海峡一旦重开-金十数据"
    assert "全面复航" in result.raw_text
    assert result.raw_html_path and (tmp_path / result.raw_html_path).exists()
    assert result.parsed_path and (tmp_path / result.parsed_path).exists()
    assert len(result.image_assets) == 1
    assert result.image_assets[0]["vlm_eligible"] is True
    assert result.image_assets[0]["width"] == 900
    assert result.image_assets[0]["height"] == 500


def test_fetch_jin10_detail_page_prefers_xnews_article_body_over_page_chrome(tmp_path: Path) -> None:
    url = "https://xnews.jin10.com/details/221760"
    html = """
    <html>
      <head><title>单线逻辑失效！为何这轮通胀没救起金价？</title></head>
      <body>
        <div class="jin10-layout-vip-user">金十数据 首页 头条 VIP专区 日历 视频 用户ID：4087042</div>
        <div class="jin10-news-cdetails-content is-vip">
          第一部分：信息概览 栏目：周末·大师复盘。
          第二部分：语音及文稿。美国通胀冲上三年高位，金价多头节节败退。
          观点分享：油价冲击可能抬高通胀预期，限制金价的上行空间。
        </div>
        <div class="j-comments__list">全部评论 习惯了</div>
      </body>
    </html>
    """
    client = FakeDetailClient({url: _html_response(url, html)})

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
    )

    assert result.status == "fetched"
    assert result.access_status == "readable"
    assert result.raw_text.startswith("第一部分：信息概览")
    assert "金十数据 首页" not in result.raw_text
    assert "全部评论" not in result.raw_text


def test_fetch_jin10_detail_page_prefers_vip_column_course_body_over_shell_and_trial_list(tmp_path: Path) -> None:
    url = "https://cdn.jin10.com/vip_column/index.html#/detail?id=850550"
    html = """
    <html>
      <title>CME突改周末规则，推动黄金更易反转？</title>
      <body>
        <div class="desktop-layout is-pc-mode is-better-news">
          金十数据 首页 头条 VIP专区 用户ID：4087042 用户中心 退出登录
          <div class="course-detail-tab-panel">
            CME突改周末规则，推动黄金更易反转？ 06-12 20:08:49 00:00 02:00 1X
            ——边听边想，一条新闻拆到透——
            你好，这里是Better News认知成长计划第一季。
            在市场情绪最崩的时候，CME宣布开放黄金期货的周末交易，背后究竟有何深意？
            今年的黄金行情出现多次V型反转，期权和流动性需要重新评估。
          </div>
          <div class="trial-home is-better-news">
            专属客服 试读内容 免费读全文 霍尔木兹封锁的第75天，油价为何涨不起来了？
          </div>
        </div>
      </body>
    </html>
    """
    client = FakeDetailClient({url: _html_response(url, html)})

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
    )

    assert result.status == "fetched"
    assert result.access_status == "readable"
    assert result.raw_text.startswith("CME突改周末规则")
    assert "金十数据 首页" not in result.raw_text
    assert "专属客服" not in result.raw_text
    assert "00:00 02:00 1X" not in result.raw_text


def test_fetch_jin10_detail_page_does_not_send_small_images_to_vlm(tmp_path: Path) -> None:
    url = "https://flash.jin10.com/detail/1"
    image_url = "https://cdn.jin10.com/avatar.png"
    html = f"<html><title>金十快讯</title><body><p>伊朗消息。</p><img src='{image_url}' /></body></html>"
    client = FakeDetailClient({
        url: _html_response(url, html),
        image_url: _image_response(image_url, width=200, height=200),
    })
    calls: list[dict[str, Any]] = []

    def vlm_runner(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        calls.extend(images)
        return [{"status": "ok", "summary": "should not happen"} for _ in images]

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
        run_vlm=True,
        vlm_runner=vlm_runner,
    )

    assert result.status == "fetched"
    assert result.access_status == "readable"
    assert calls == []
    assert result.image_assets[0]["vlm_eligible"] is False
    assert result.image_assets[0]["vlm_skip_reason"] == "image_too_small_for_vlm"
    assert result.image_insights == []


def test_fetch_jin10_detail_page_runs_vlm_for_large_images(tmp_path: Path) -> None:
    url = "https://xnews.jin10.com/details/large"
    image_url = "https://cdn.jin10.com/large-chart.png"
    html = f"<html><title>黄金图表</title><body><p>黄金技术位。</p><img src='{image_url}' /></body></html>"
    client = FakeDetailClient({
        url: _html_response(url, html),
        image_url: _image_response(image_url, width=1200, height=700),
    })

    def vlm_runner(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "seq": image["seq"],
                "file": image["file"],
                "path": image["path"],
                "status": "ok",
                "summary": "黄金图表显示关键支撑位。",
            }
            for image in images
        ]

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
        run_vlm=True,
        vlm_runner=vlm_runner,
    )

    assert result.status == "fetched"
    assert result.access_status == "readable"
    assert len(result.image_insights) == 1
    assert result.image_insights[0]["summary"] == "黄金图表显示关键支撑位。"


def test_fetch_jin10_detail_page_marks_javascript_shell(tmp_path: Path) -> None:
    url = "https://cdn.jin10.com/vip_column/index.html#/detail?id=1"
    html = (
        "<html><title>投资者心理学</title><body>"
        "We're sorry but 投资者心理学 doesn't work properly without JavaScript enabled. "
        "Please enable it to continue."
        "</body></html>"
    )
    client = FakeDetailClient({url: _html_response(url, html)})

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
    )

    assert result.status == "fetched"
    assert result.access_status == "javascript_required"


def test_fetch_jin10_detail_page_keeps_rendered_vip_column_readable_despite_vue_shell_text(tmp_path: Path) -> None:
    url = "https://cdn.jin10.com/vip_column/index.html#/detail?id=850550"
    long_body = " ".join(["黄金V型走势与CME周末交易规则变化需要结合期权和流动性观察。"] * 80)
    html = (
        "<html><title>CME突改周末规则，推动黄金更易反转？</title><body>"
        "We're sorry but 投资者心理学 doesn't work properly without JavaScript enabled. "
        "Please enable it to continue. 用户ID：4087042 用户中心 退出登录 "
        f"{long_body}"
        "</body></html>"
    )
    client = FakeDetailClient({url: _html_response(url, html)})

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
    )

    assert result.status == "fetched"
    assert result.access_status == "readable"
    assert "CME周末交易规则" in result.raw_text


def test_fetch_jin10_detail_page_marks_vip_locked_text(tmp_path: Path) -> None:
    url = "https://xnews.jin10.com/details/221681"
    html = """
    <html>
      <title>DeepTalk-金十数据</title>
      <body>
        <h1>DeepTalk</h1>
        <p>钻石VIP专享文章</p>
        <p>风险提示及免责条款：市场有风险，投资需谨慎。</p>
        <button>解锁文章</button>
      </body>
    </html>
    """
    client = FakeDetailClient({url: _html_response(url, html)})

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
    )

    assert result.status == "fetched"
    assert result.access_status == "vip_locked"


def test_fetch_jin10_detail_page_marks_disclaimer_only_page_as_limited(tmp_path: Path) -> None:
    url = "https://xnews.jin10.com/details/221760"
    html = """
    <html>
      <title>单线逻辑失效！为何这轮通胀没救起金价？</title>
      <body>
        <div class="jin10-news-cdetails-content is-vip">
          风险提示及免责条款：市场有风险，投资需谨慎。本文不构成个人投资建议，
          也未考虑到个别用户特殊的投资目标、财务状况或需要。据此投资，责任自负。
        </div>
      </body>
    </html>
    """
    client = FakeDetailClient({url: _html_response(url, html)})

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
    )

    assert result.status == "fetched"
    assert result.access_status == "vip_locked"


def test_fetch_jin10_detail_page_marks_logged_in_vip_report_as_readable(tmp_path: Path) -> None:
    url = "https://xnews.jin10.com/details/221732"
    html = """
    <html>
      <title>冲突再次接近终点，但黄金的上行空间可能已不及战前-市场参考-金十数据</title>
      <body>
        用户ID：4087042 用户中心 退出登录 订阅 已订阅 钻石VIP专享文章
        1、行情回顾：现货黄金开盘后一度跌至4024美元，随后陷入震荡，美盘时段急速拉升，
        最终收涨。现货白银同步上涨，贵金属波动显著放大。
        2、关键指标：美国最新初请与续请失业金人数双双反弹，就业市场出现边际降温迹象。
        近期经济与通胀数据表现仍超预期，支持高利率预期。
        3、观点分享：高企的原油价格可能加速通胀，并导致利率在更长时间内维持高位，
        这将限制金价的上行空间。风险提示及免责条款：市场有风险。
        解锁文章
      </body>
    </html>
    """
    client = FakeDetailClient({url: _html_response(url, html)})

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
    )

    assert result.status == "fetched"
    assert result.access_status == "readable"
    assert "行情回顾" in result.raw_text


def test_fetch_jin10_detail_page_uses_browser_profile_fallback_for_vip_locked(tmp_path: Path) -> None:
    url = "https://xnews.jin10.com/details/221681"
    preview_html = """
    <html>
      <title>DeepTalk-金十数据</title>
      <body>钻石VIP专享文章 解锁文章</body>
    </html>
    """
    rendered_html = """
    <html>
      <title>DeepTalk-金十数据</title>
      <body>
        <h1>DeepTalk</h1>
        <p>完整正文：美伊冲突缓和压低油价，但强劲美国数据仍限制降息空间。</p>
        <p>黄金短线受美元和美债收益率压制，需观察关键支撑。</p>
      </body>
    </html>
    """
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    client = FakeDetailClient({url: _html_response(url, preview_html)})
    browser_calls: list[dict[str, Any]] = []

    def fake_browser_fetcher(**kwargs: Any) -> RenderedDetailPage:
        browser_calls.append(kwargs)
        return RenderedDetailPage(final_url=url, html=rendered_html)

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
        run_browser_fallback=True,
        browser_profile=profile_dir,
        browser_html_fetcher=fake_browser_fetcher,
    )

    assert browser_calls == [{"url": url, "user_data_dir": profile_dir, "executable_path": None}]
    assert result.status == "fetched"
    assert result.fetch_method == "browser_profile"
    assert result.browser_fallback_attempted is True
    assert result.browser_fallback_status == "success"
    assert result.access_status == "readable"
    assert "完整正文" in result.raw_text
    assert result.raw_html_path and result.raw_html_path.endswith(".html")
    assert "-browser-profile" in result.raw_html_path
    assert result.parsed_path and "-browser-profile" in result.parsed_path


def test_browser_profile_copy_omits_singleton_locks(tmp_path: Path) -> None:
    source = tmp_path / "source-profile"
    target = tmp_path / "target-profile"
    source.mkdir()
    (source / "Cookies").write_text("cookie-data", encoding="utf-8")
    (source / "SingletonLock").write_text("locked", encoding="utf-8")
    (source / "SingletonCookie").write_text("cookie-lock", encoding="utf-8")

    jin10_detail_fetcher._copy_browser_profile_for_readonly_launch(source, target)

    assert (target / "Cookies").read_text(encoding="utf-8") == "cookie-data"
    assert not (target / "SingletonLock").exists()
    assert not (target / "SingletonCookie").exists()


def test_fetch_jin10_detail_page_keeps_preview_when_browser_profile_fallback_fails(tmp_path: Path) -> None:
    url = "https://cdn.jin10.com/vip_column/index.html#/detail?id=1"
    html = (
        "<html><title>投资者心理学</title><body>"
        "We're sorry but 投资者心理学 doesn't work properly without JavaScript enabled. "
        "Please enable it to continue."
        "</body></html>"
    )
    profile_dir = tmp_path / "missing-profile"
    client = FakeDetailClient({url: _html_response(url, html)})

    def fake_browser_fetcher(**kwargs: Any) -> RenderedDetailPage:
        raise RuntimeError("profile expired")

    result = fetch_jin10_detail_page(
        url=url,
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        client=client,
        run_browser_fallback=True,
        browser_profile=profile_dir,
        browser_html_fetcher=fake_browser_fetcher,
    )

    assert result.status == "fetched"
    assert result.fetch_method == "http"
    assert result.access_status == "javascript_required"
    assert result.browser_fallback_attempted is True
    assert result.browser_fallback_status == "failed"
    assert "profile expired" in str(result.browser_fallback_error)
