from __future__ import annotations

from pathlib import Path

import httpx

from apps.collectors.news.fed_rss import collect_fed_rss


FED_RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Federal Reserve Monetary Policy</title>
    <item>
      <title>Minutes of the Federal Open Market Committee, May 5-6, 2026</title>
      <link>https://www.federalreserve.gov/monetarypolicy/fomcminutes20260506.htm</link>
      <description><![CDATA[The Federal Reserve released FOMC minutes.]]></description>
      <pubDate>Wed, 10 Jun 2026 18:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


class FakeFeedClient:
    def __init__(self, responses: dict[str, httpx.Response | Exception]) -> None:
        self.responses = responses

    def get(self, url: str) -> httpx.Response:
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def _response(url: str, body: str) -> httpx.Response:
    return httpx.Response(200, content=body.encode("utf-8"), request=httpx.Request("GET", url))


def test_fed_rss_maps_items_to_raw_news_items(tmp_path: Path) -> None:
    feeds = {"monetary_policy": "https://fed.test/monetary.xml"}
    client = FakeFeedClient({"https://fed.test/monetary.xml": _response("https://fed.test/monetary.xml", FED_RSS_FIXTURE)})

    result = collect_fed_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        feeds=feeds,
        client=client,
    )

    assert result.status == "success"
    assert result.unavailable_feeds == []
    assert len(result.items) == 1

    item = result.items[0]
    assert item.source_key == "fed_rss"
    assert item.source_type == "official"
    assert item.feed_key == "monetary_policy"
    assert item.title == "Minutes of the Federal Open Market Committee, May 5-6, 2026"
    assert item.url == "https://www.federalreserve.gov/monetarypolicy/fomcminutes20260506.htm"
    assert item.domain == "federalreserve.gov"
    assert item.published_at == "2026-06-10T18:00:00+00:00"
    assert item.event_type == "fomc_minutes"
    assert item.verification_status == "official_confirmed"
    assert item.duplicate_key.startswith("news:fed_rss:")
    assert item.raw_path.startswith("raw/news/fed_rss/2026-06-10/monetary_policy-")
    assert item.parsed_path.startswith("parsed/news/fed_rss/2026-06-10/monetary_policy-")
    assert (tmp_path / item.raw_path).exists()
    assert (tmp_path / item.parsed_path).exists()


def test_fed_rss_partial_failure_keeps_successful_feeds(tmp_path: Path) -> None:
    feeds = {
        "monetary_policy": "https://fed.test/monetary.xml",
        "speeches_testimony": "https://fed.test/speeches.xml",
    }
    client = FakeFeedClient(
        {
            "https://fed.test/monetary.xml": _response("https://fed.test/monetary.xml", FED_RSS_FIXTURE),
            "https://fed.test/speeches.xml": httpx.ConnectError("connection refused"),
        }
    )

    result = collect_fed_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        feeds=feeds,
        client=client,
    )

    assert result.status == "partial"
    assert [item.feed_key for item in result.items] == ["monetary_policy"]
    assert result.unavailable_feeds == ["speeches_testimony"]
    assert result.source_refs[-1]["status"] == "failed"
