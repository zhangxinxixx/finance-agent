"""Tests for Jin10 web flash parser (fixture-first)."""

from __future__ import annotations

from apps.parsers.jin10.web_flash import parse_jin10_web_flash_html


# ---------------------------------------------------------------------------
# Inline HTML fixtures
# ---------------------------------------------------------------------------

IMPORTANT_FLASH_HTML = """
<div class="jin-flash-item flash is-important" data-id="123456">
  <div class="flash-important-icon"></div>
  <div class="flash-content">
    <a href="https://flash-api.jin10.com/get?id=123456" class="flash-item-title">
      美联储宣布加息25个基点
    </a>
    <div class="flash-item-summary">美联储将联邦基金利率目标区间上调至5.25%-5.50%</div>
    <div class="flash-item-time">2026-06-20 20:30</div>
    <div class="flash-item-labels">
      <span class="color-label__item">央行</span>
      <span class="color-label__item">利率</span>
    </div>
  </div>
</div>
"""

VIP_FLASH_HTML = """
<div class="jin-flash-item flash is-vip" data-id="789012">
  <div class="flash-vip-icon"></div>
  <div class="flash-content">
    <div class="flash-item-title">非农数据大幅不及预期</div>
    <div class="flash-item-summary">美国6月非农就业人口增加15万，预期22万</div>
    <div class="flash-item-time">2026-06-20 20:30</div>
    <div class="flash-item-labels">
      <span class="color-label__item">就业</span>
    </div>
  </div>
</div>
"""

VIP_GOLD_FLASH_HTML = """
<div class="jin-flash-item flash is-vip" data-id="789013">
  <div class="flash-content">
    <div class="flash-item-title">现货黄金关键支撑位守住后反弹</div>
    <div class="flash-item-summary">金价围绕4000美元关口反复测试，白银同步走高。</div>
    <div class="flash-item-time">2026-06-20 21:10</div>
    <div class="flash-item-labels">
      <span class="color-label__item">黄金</span>
    </div>
  </div>
</div>
"""

VIP_LINKED_REPORT_HTML = """
<div class="jin-flash-item flash is-vip" data-id="789014">
  <div class="flash-content">
    <div class="flash-item-title">投资经理认为，黄金大部分下行空间已被市场定价</div>
    <div class="flash-item-summary">预计4000美元大关也将会失守，但资金将开始逐步买入黄金。</div>
    <a href="https://www.tradinghero.com/?symbol=XAUUSD.GOODS">查看行情图表</a>
    <div class="flash-item-time">2026-06-20 21:20</div>
  </div>
</div>
"""

IMAGE_REPORT_FLASH_HTML = """
<div class="jin-flash-item flash is-important" data-id="456791">
  <div class="flash-content">
    <div class="flash-item-title">金十图示：2026年06月24日黄金ETF持仓报告</div>
    <img src="https://img.jin10.com/mp/26/06/example.jpg/pcover">
    <div class="flash-item-time">2026-06-20 22:10</div>
  </div>
</div>
"""

LINKED_REPORT_FLASH_HTML = """
<div class="jin-flash-item flash" data-id="456792">
  <div class="flash-content">
    <div class="flash-item-title">每日人工智能动态汇总</div>
    <a href="https://xnews.jin10.com/topic/397">查看专题全文</a>
    <div class="flash-item-time">2026-06-20 22:20</div>
  </div>
</div>
"""

DATA_TEXT_CATEGORY_FLASH_HTML = """
<div class="jin-flash-item flash is-important" data-id="456793">
  <div class="right-content">
    <div class="right-content_title">
      <span class="jin-tag"><span data-text="地缘热点">地缘热点</span></span>
      <span>市场消息更新</span>
    </div>
    <div class="right-content_intro">油价和避险资产等待中东局势进一步确认。</div>
  </div>
</div>
"""

VIP_DATA_TEXT_TITLE_HTML = """
<div class="jin-flash-item flash is-vip" data-id="789015">
  <div class="right-vip">
    <span class="jin-tag is-vip"><span data-text="VIP">VIP</span></span>
    <b class="right-vip-title">全球央行购金规模持续增加中...</b>
  </div>
  <div class="right-content">
    <div class="flash-text">央行购金需求继续托底黄金价格。</div>
  </div>
</div>
"""

RECOMMEND_ARTICLE_HTML = """
<div class="recommend-article-item">
  <div class="item-bg" style="background-image: url(&quot;https://gimg.jin10.com/gallary/26/04/example.png/ncover&quot;);"></div>
  <div class="item-title">
    <span class="jin-tag"><span data-text="地缘热点">地缘热点</span></span>
    <span class="text">美国不让打、国内逼着打——以军在黎巴嫩陷入政治“夹缝”</span>
  </div>
  <div class="item-time">06-24 12:48</div>
</div>
"""

RIGHT_RAIL_ARTICLE_HTML = """
<a href="//xnews.jin10.com/details/224056" target="_blank" class="article-item">
  <div class="article-item__cover">
    <img src="https://gimg.jin10.com/gallary/26/05/gold.png/ncover" class="article-item__image">
  </div>
  <div class="article-item__info">
    <div title="加息阴影笼罩，美银砍金价预期14%但重申5000美元目标" class="article-item__title">
      加息阴影笼罩，美银砍金价预期14%但重申50...
    </div>
  </div>
</a>
"""

TOP_LIST_HTML = """
<div class="flash-top-list">
  <a class="flash-top-list__item" href="https://www.jin10.com/flash_newest.html#id=345678" data-id="345678">
    <span class="flash-top-list__title">欧洲央行维持利率不变</span>
    <span class="flash-top-list__time">2026-06-20 19:45</span>
  </a>
</div>
"""

LIVE_TOP_LIST_HTML = """
<div class="flash-top-list__items lengh-4">
  <div class="flash-top-list__item">
    <div class="flash-top-list__item-number">01</div>
    <div title="瑞银驳斥市场激进加息预期，三大硬性条件一个都没达标" class="flash-top-list__item-content">
      瑞银驳斥市场激进加息预期，三大硬性条件一个都没达标
    </div>
  </div>
</div>
"""

LIVE_IMPORTANT_FLASH_HTML = """
<div id="flash20260624110502433800" class="jin-flash-item-container is-normal">
  <div class="jin-flash-item flash is-important">
    <a href="https://flash.jin10.com/detail/20260624110502433800" target="_blank">
      <span>详情</span>
    </a>
    <div class="item-time has-title">11:05:02</div>
    <div class="item-right is-common">
      <div class="right-common"><b class="right-common-title">期货热点追踪</b></div>
      <div class="right-content">
        <div class="collapse-container is-normal">
          <div class="collapse-content">
            <div><div class="flash-text">铁矿石从数月低点反弹，日内涨幅超1%，几内亚雨季遇上开采高峰，西芒杜产能释放弹性有多大？</div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
"""

UNRELATED_HTML = """
<html>
<body>
  <div class="some-random-content">
    <p>Nothing related to jin10 flash</p>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportantFlash:
    """Parse `.jin-flash-item.flash.is-important` items."""

    def test_extracts_important_flash_with_all_fields(self):
        result = parse_jin10_web_flash_html(
            IMPORTANT_FLASH_HTML,
            fetched_at="2026-06-20T20:31:00+00:00",
            raw_artifact_path="/data/raw/jin10_web_20260620.html",
        )

        assert result["status"] == "ok"
        assert result["fetchedAt"] == "2026-06-20T20:31:00+00:00"
        assert len(result["items"]) == 1

        item = result["items"][0]
        assert item["itemId"] == "jin10_flash_123456"
        assert item["sourceKey"] == "jin10_web_important_flash"
        assert item["contentFamily"] == "web_important_flash.macro_policy_flash"
        assert "美联储宣布加息25个基点" in item["title"]
        assert "联邦基金利率" in item["summary"]
        assert item["publishedAt"] is not None
        assert item["url"] == "https://flash.jin10.com/detail/123456"
        assert item["importanceSource"] == "jin10_home_important_marker"
        assert item["verificationStatus"] == "single_source"
        assert item["accessStatus"] == "readable"
        assert "央行" in item["tags"]
        assert "利率" in item["tags"]

    def test_includes_source_refs_and_artifact_refs(self):
        result = parse_jin10_web_flash_html(
            IMPORTANT_FLASH_HTML,
            fetched_at="2026-06-20T20:31:00+00:00",
            raw_artifact_path="/data/raw/jin10_web_20260620.html",
        )
        item = result["items"][0]

        assert item["sourceRefs"][0]["fetchedAt"] == "2026-06-20T20:31:00+00:00"
        assert item["sourceRefs"][0]["rawArtifactPath"] == "/data/raw/jin10_web_20260620.html"
        assert item["artifactRefs"][0]["rawArtifactPath"] == "/data/raw/jin10_web_20260620.html"


class TestVipFlash:
    """Parse `.jin-flash-item.flash.is-vip` items."""

    def test_extracts_vip_flash_with_correct_family(self):
        result = parse_jin10_web_flash_html(
            VIP_FLASH_HTML,
            fetched_at="2026-06-20T20:31:00+00:00",
        )

        assert result["status"] == "ok"
        assert len(result["items"]) == 1

        item = result["items"][0]
        assert item["sourceKey"] == "jin10_web_vip_flash"
        assert item["contentFamily"] == "web_vip_flash.vip_macro_flash"
        assert "非农数据" in item["title"]
        assert "15万" in item["summary"]
        assert item["importanceSource"] == "jin10_vip_marker"
        assert item["verificationStatus"] == "report_derived"
        assert item["accessStatus"] == "readable"
        assert "就业" in item["tags"]
        assert item["url"] == "https://flash.jin10.com/detail/789012"

    def test_classifies_vip_gold_silver_flash(self):
        result = parse_jin10_web_flash_html(
            VIP_GOLD_FLASH_HTML,
            fetched_at="2026-06-20T21:11:00+00:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["sourceKey"] == "jin10_web_vip_flash"
        assert item["contentFamily"] == "web_vip_flash.vip_gold_silver_flash"
        assert item["verificationStatus"] == "report_derived"
        assert "黄金" in item["tags"]

    def test_classifies_linked_vip_flash_as_report_article(self):
        result = parse_jin10_web_flash_html(
            VIP_LINKED_REPORT_HTML,
            fetched_at="2026-06-20T21:21:00+00:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["sourceKey"] == "jin10_web_vip_flash"
        assert item["contentFamily"] == "web_vip_flash.vip_report_article"
        assert item["linkedUrls"] == ["https://www.tradinghero.com/?symbol=XAUUSD.GOODS"]
        assert item["imageUrls"] == []


class TestTopListFlash:
    """Parse `.flash-top-list__item` items."""

    def test_extracts_top_list_item(self):
        result = parse_jin10_web_flash_html(
            TOP_LIST_HTML,
            fetched_at="2026-06-20T20:00:00+00:00",
        )

        assert result["status"] == "ok"
        assert len(result["items"]) == 1

        item = result["items"][0]
        assert item["sourceKey"] == "jin10_web_important_flash"
        assert item["contentFamily"] == "web_important_flash.important_news_top"
        assert "欧洲央行" in item["title"]
        assert item["importanceSource"] == "jin10_home_top_list"
        assert item["verificationStatus"] == "single_source"
        assert item["url"] == "https://flash.jin10.com/detail/345678"

    def test_extracts_live_div_top_list_item(self):
        result = parse_jin10_web_flash_html(
            LIVE_TOP_LIST_HTML,
            fetched_at="2026-06-24T11:40:00+08:00",
        )

        assert result["status"] == "ok"
        assert len(result["items"]) == 1

        item = result["items"][0]
        assert item["sourceKey"] == "jin10_web_important_flash"
        assert item["contentFamily"] == "web_important_flash.important_news_top"
        assert "瑞银驳斥" in item["title"]
        assert item["importanceSource"] == "jin10_home_top_list"


class TestLiveHomepageFlash:
    """Parse rendered Jin10 homepage DOM captured from browser-profile smoke."""

    def test_extracts_live_important_flash_item(self):
        result = parse_jin10_web_flash_html(
            LIVE_IMPORTANT_FLASH_HTML,
            fetched_at="2026-06-24T11:40:00+08:00",
        )

        assert result["status"] == "ok"
        assert len(result["items"]) == 1

        item = result["items"][0]
        assert item["itemId"] == "jin10_flash_20260624110502433800"
        assert item["sourceKey"] == "jin10_web_important_flash"
        assert item["contentFamily"] == "web_important_flash.market_move_flash"
        assert "铁矿石从数月低点反弹" in item["title"]
        assert item["publishedAt"] == "11:05:02"
        assert item["url"] == "https://flash.jin10.com/detail/20260624110502433800"
        assert "期货热点追踪" in item["tags"]

    def test_classifies_geo_risk_important_flash(self):
        html = """
        <div class="jin-flash-item flash is-important" data-id="456789">
          <div class="flash-content">
            <div class="flash-item-title">伊朗称将回应以色列袭击，红海航运风险升温</div>
            <div class="flash-item-time">2026-06-20 22:00</div>
          </div>
        </div>
        """
        result = parse_jin10_web_flash_html(html, fetched_at="2026-06-20T22:01:00+00:00")

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["contentFamily"] == "web_important_flash.geo_risk_flash"

    def test_classifies_macro_policy_important_flash(self):
        result = parse_jin10_web_flash_html(
            IMPORTANT_FLASH_HTML,
            fetched_at="2026-06-20T20:31:00+00:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["contentFamily"] == "web_important_flash.macro_policy_flash"

    def test_classifies_from_labels_when_title_is_generic(self):
        html = """
        <div class="jin-flash-item flash is-important" data-id="456790">
          <div class="flash-content">
            <div class="flash-item-title">相关市场消息更新</div>
            <div class="flash-item-labels">
              <span class="color-label__item">期货热点追踪</span>
            </div>
          </div>
        </div>
        """
        result = parse_jin10_web_flash_html(html, fetched_at="2026-06-20T22:02:00+00:00")

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["contentFamily"] == "web_important_flash.market_move_flash"

    def test_classifies_image_flash_as_report_article(self):
        result = parse_jin10_web_flash_html(
            IMAGE_REPORT_FLASH_HTML,
            fetched_at="2026-06-20T22:11:00+00:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["contentFamily"] == "web_important_flash.report_article_flash"
        assert item["imageUrls"] == ["https://img.jin10.com/mp/26/06/example.jpg/pcover"]
        assert item["linkedUrls"] == []

    def test_classifies_linked_normal_flash_as_report_article(self):
        result = parse_jin10_web_flash_html(
            LINKED_REPORT_FLASH_HTML,
            fetched_at="2026-06-20T22:21:00+00:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["contentFamily"] == "web_important_flash.report_article_flash"
        assert item["linkedUrls"] == ["https://xnews.jin10.com/topic/397"]
        assert item["imageUrls"] == []

    def test_extracts_data_text_category_before_title(self):
        result = parse_jin10_web_flash_html(
            DATA_TEXT_CATEGORY_FLASH_HTML,
            fetched_at="2026-06-20T22:31:00+00:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["title"] == "市场消息更新"
        assert item["summary"] == "油价和避险资产等待中东局势进一步确认。"
        assert "地缘热点" in item["tags"]
        assert item["contentFamily"] == "web_important_flash.geo_risk_flash"

    def test_extracts_vip_data_text_category_without_polluting_title(self):
        result = parse_jin10_web_flash_html(
            VIP_DATA_TEXT_TITLE_HTML,
            fetched_at="2026-06-20T22:32:00+00:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["title"] == "全球央行购金规模持续增加中..."
        assert item["summary"] == "央行购金需求继续托底黄金价格。"
        assert "VIP" in item["tags"]
        assert item["contentFamily"] == "web_vip_flash.vip_gold_silver_flash"

    def test_extracts_homepage_recommend_article_cards(self):
        result = parse_jin10_web_flash_html(
            RECOMMEND_ARTICLE_HTML,
            fetched_at="2026-06-20T22:33:00+00:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["sourceKey"] == "jin10_web_important_flash"
        assert item["contentFamily"] == "web_important_flash.report_article_flash"
        assert item["importanceSource"] == "jin10_home_recommend_article"
        assert item["title"] == "美国不让打、国内逼着打——以军在黎巴嫩陷入政治“夹缝”"
        assert item["publishedAt"] == "06-24 12:48"
        assert "地缘热点" in item["tags"]
        assert item["imageUrls"] == ["https://gimg.jin10.com/gallary/26/04/example.png/ncover"]

    def test_extracts_right_rail_article_card_url_and_image(self):
        result = parse_jin10_web_flash_html(
            RIGHT_RAIL_ARTICLE_HTML,
            fetched_at="2026-07-09T10:05:00+08:00",
        )

        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["sourceKey"] == "jin10_web_important_flash"
        assert item["contentFamily"] == "web_important_flash.report_article_flash"
        assert item["url"] == "https://xnews.jin10.com/details/224056"
        assert item["title"] == "加息阴影笼罩，美银砍金价预期14%但重申5000美元目标"
        assert item["imageUrls"] == ["https://gimg.jin10.com/gallary/26/05/gold.png/ncover"]


class TestDedupe:
    """Same detail URL / flash id should appear once."""

    def test_keeps_distinct_items_from_same_homepage(self):
        html = IMPORTANT_FLASH_HTML + VIP_FLASH_HTML + TOP_LIST_HTML
        result = parse_jin10_web_flash_html(html, fetched_at="2026-06-20T20:31:00+00:00")

        assert result["status"] == "ok"
        assert [item["itemId"] for item in result["items"]] == [
            "jin10_flash_123456",
            "jin10_flash_789012",
            "jin10_flash_345678",
        ]
        assert [item["sourceKey"] for item in result["items"]] == [
            "jin10_web_important_flash",
            "jin10_web_vip_flash",
            "jin10_web_important_flash",
        ]

    def test_deduplicates_by_flash_id(self):
        html = IMPORTANT_FLASH_HTML + IMPORTANT_FLASH_HTML
        result = parse_jin10_web_flash_html(html, fetched_at="2026-06-20T20:31:00+00:00")

        assert result["status"] == "ok"
        assert len(result["items"]) == 1


class TestSchemaDrift:
    """Unrelated HTML returns schema_changed with no items."""

    def test_returns_schema_changed_for_unrelated_html(self):
        result = parse_jin10_web_flash_html(
            UNRELATED_HTML,
            fetched_at="2026-06-20T20:31:00+00:00",
        )

        assert result["status"] == "schema_changed"
        assert result["items"] == []
        assert result["qualityFlags"]["schema_changed"] is True

    def test_returns_schema_changed_for_empty_html(self):
        result = parse_jin10_web_flash_html("", fetched_at="2026-06-20T20:31:00+00:00")

        assert result["status"] == "schema_changed"
        assert result["items"] == []
        assert result["qualityFlags"]["schema_changed"] is True
