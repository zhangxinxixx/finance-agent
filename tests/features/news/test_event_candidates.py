from __future__ import annotations

from pathlib import Path

from apps.collectors.news.base import RawNewsItem
from apps.features.news.event_candidates import archive_event_candidates, build_event_candidates


def _item(
    *,
    source_key: str,
    source_type: str,
    title: str,
    url: str,
    domain: str,
    event_type: str,
    published_at: str = "2026-06-10T08:15:00+00:00",
    verification_status: str = "single_source",
    feed_key: str = "middle_east_hormuz",
) -> RawNewsItem:
    return RawNewsItem(
        source_key=source_key,
        source_name=source_key,
        source_type=source_type,
        feed_key=feed_key,
        title=title,
        url=url,
        domain=domain,
        published_at=published_at,
        fetched_at="2026-06-10T08:20:00+00:00",
        summary="Short evidence summary",
        source_country="US",
        source_language="en",
        event_type=event_type,
        verification_status=verification_status,
        duplicate_key=f"news:{source_key}:fixture",
        raw_path=f"raw/news/{source_key}/2026-06-10/feed.json",
        parsed_path=f"parsed/news/{source_key}/2026-06-10/feed.json",
        raw_payload={"query_group": feed_key},
    )


def test_event_candidates_merge_multi_source_candidate_without_official_confirmation() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="gdelt_news",
                source_type="aggregator",
                title="Iran warns over Strait of Hormuz shipping",
                url="https://example-a.com/hormuz",
                domain="example-a.com",
                event_type="hormuz_risk",
            ),
            _item(
                source_key="google_news_rss",
                source_type="aggregator",
                title="Iran warns over Strait of Hormuz shipping",
                url="https://news.google.com/rss/articles/hormuz",
                domain="example-b.com",
                event_type="middle_east_escalation",
            ),
            _item(
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
                title="Iran warns over Strait of Hormuz shipping",
                url="https://news.google.com/rss/articles/reuters-hormuz",
                domain="reuters.com",
                event_type="middle_east_escalation",
            ),
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    data = bundle.to_dict()
    assert len(data["raw_news_items"]) == 3
    assert len(data["event_candidates"]) == 1

    event = data["event_candidates"][0]
    assert event["event_type"] == "hormuz_risk"
    assert event["verification_status"] == "multi_source"
    assert event["need_verification"] is True
    assert event["source_count"] == 3
    assert event["data_quality"]["authorized_wire"] is False
    assert event["data_quality"]["verification_reason"] == "cross_domain_with_authoritative_candidate"
    assert event["data_quality"]["independent_source_count"] == 3
    assert event["data_quality"]["independent_domain_count"] == 3
    assert event["data_quality"]["authoritative_source_count"] == 1
    assert set(event["asset_tags"]) == {"XAUUSD", "WTI", "Brent", "DXY"}
    assert "Middle East" in event["region_tags"]
    assert "Iran" in event["entities"]
    assert event["duplicate_group"].startswith("mainline:hormuz_risk:")
    assert event["data_quality"]["grouping_strategy"] == "mainline"
    assert event["data_quality"]["merged_item_count"] == 3

    assert len(data["top_market_events"]) == 1
    assert data["top_market_events"][0]["verification_status"] == "multi_source"
    assert data["source_mix"] == {
        "official": 0,
        "wire": 0,
        "wire_public_candidate": 1,
        "aggregator": 2,
        "supplemental": 0,
        "other": 0,
    }
    assert data["data_quality"]["unverified_count"] == 0


def test_two_low_trust_cross_domain_candidates_do_not_upgrade_to_multi_source() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="gdelt_news",
                source_type="aggregator",
                title="Oil tanker disruption near Hormuz",
                url="https://example-a.com/oil",
                domain="example-a.com",
                event_type="hormuz_risk",
            ),
            _item(
                source_key="google_news_rss",
                source_type="aggregator",
                title="Oil tanker disruption near Hormuz",
                url="https://example-b.com/oil",
                domain="example-b.com",
                event_type="middle_east_escalation",
            ),
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    event = bundle.to_dict()["event_candidates"][0]
    assert event["verification_status"] == "single_source"
    assert event["need_verification"] is True
    assert event["data_quality"]["verification_reason"] == "cross_domain_but_low_trust_only"
    assert event["data_quality"]["independent_source_count"] == 2
    assert event["data_quality"]["independent_domain_count"] == 2
    assert event["data_quality"]["authoritative_source_count"] == 0


def test_same_domain_reposts_do_not_upgrade_to_multi_source() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="google_news_rss",
                source_type="aggregator",
                title="Reuters says CPI path still matters for gold",
                url="https://news.google.com/rss/articles/reuters-cpi",
                domain="reuters.com",
                event_type="macro_watchlist",
            ),
            _item(
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
                title="Reuters says CPI path still matters for gold",
                url="https://www.reuters.com/world/us/cpi-path",
                domain="reuters.com",
                event_type="macro_watchlist",
            ),
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    event = bundle.to_dict()["event_candidates"][0]
    assert event["verification_status"] == "single_source"
    assert event["data_quality"]["verification_reason"] == "same_domain_reposts"
    assert event["data_quality"]["independent_source_count"] == 2
    assert event["data_quality"]["independent_domain_count"] == 1


def test_single_aggregator_item_stays_candidate_only() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="gdelt_news",
                source_type="aggregator",
                title="Oil tanker disruption near Hormuz",
                url="https://example.com/oil",
                domain="example.com",
                event_type="hormuz_risk",
            )
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    data = bundle.to_dict()
    assert len(data["event_candidates"]) == 1
    event = data["event_candidates"][0]
    assert event["verification_status"] == "single_source"
    assert event["need_verification"] is True
    assert event["source_count"] == 1
    assert event["data_quality"]["verification_reason"] == "single_independent_source"
    assert data["top_market_events"] == []
    assert data["data_quality"]["single_source_count"] == 1
    assert data["data_quality"]["official_confirmed_count"] == 0


def test_ongoing_mainline_items_collapse_into_one_logical_event() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
                title="Iran warns Hormuz shipping could face new disruption",
                url="https://www.reuters.com/world/hormuz-1",
                domain="reuters.com",
                event_type="hormuz_risk",
                published_at="2026-06-10T08:15:00+00:00",
            ),
            _item(
                source_key="google_news_rss",
                source_type="aggregator",
                title="Oil tankers reroute as Strait of Hormuz tension rises",
                url="https://news.google.com/rss/articles/hormuz-2",
                domain="example-news.com",
                event_type="middle_east_escalation",
                published_at="2026-06-10T12:45:00+00:00",
            ),
            _item(
                source_key="jin10_feishu",
                source_type="supplemental",
                title="中东局势继续发酵，市场关注霍尔木兹海峡运输风险",
                url="https://xnews.jin10.com/details/hormuz",
                domain="xnews.jin10.com",
                event_type="hormuz_risk",
                published_at="2026-06-11T01:10:00+00:00",
            ),
        ],
        as_of="2026-06-11T02:00:00+00:00",
    )

    data = bundle.to_dict()
    assert len(data["event_candidates"]) == 1

    event = data["event_candidates"][0]
    assert event["event_type"] == "hormuz_risk"
    assert event["duplicate_group"].startswith("mainline:hormuz_risk:")
    assert event["event_time"] == "2026-06-11T01:10:00+00:00"
    assert event["source_count"] == 3
    assert event["data_quality"]["grouping_strategy"] == "mainline"
    assert event["data_quality"]["merged_item_count"] == 3
    assert event["verification_status"] == "multi_source"


def test_stale_public_news_items_are_filtered_before_event_grouping() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
                title="BOJ comment from old archive mentions Fed inflation",
                url="https://www.reuters.com/markets/archive-fed-boj",
                domain="reuters.com",
                event_type="fed_hawkish",
                published_at="2022-03-16T07:00:00+00:00",
            ),
            _item(
                source_key="google_news_rss",
                source_type="aggregator",
                title="Warsh says Fed inflation path remains restrictive",
                url="https://www.reuters.com/markets/current-fed",
                domain="reuters.com",
                event_type="fed_hawkish",
                published_at="2026-06-20T07:00:00+00:00",
            ),
        ],
        as_of="2026-06-21T00:00:00+00:00",
    )

    data = bundle.to_dict()
    assert len(data["raw_news_items"]) == 1
    assert data["raw_news_items"][0]["title"] == "Warsh says Fed inflation path remains restrictive"
    assert len(data["event_candidates"]) == 1
    assert data["data_quality"]["stale_news_item_count"] == 1
    assert data["warnings"] == ["Filtered 1 stale news items outside the current event window."]


def test_cross_source_exact_same_public_article_is_deduped_before_grouping() -> None:
    shared_url = "https://news.google.com/rss/articles/reuters-shared"
    shared_title = "Brent set for weekly fall as ceasefire lowers risk premium"
    bundle = build_event_candidates(
        [
            _item(
                source_key="google_news_rss",
                source_type="aggregator",
                title=shared_title,
                url=shared_url,
                domain="reuters.com",
                event_type="oil_supply_shock",
                published_at="2026-06-20T07:00:00+00:00",
            ),
            _item(
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
                title=shared_title,
                url=shared_url,
                domain="reuters.com",
                event_type="oil_supply_shock",
                published_at="2026-06-20T07:00:00+00:00",
            ),
        ],
        as_of="2026-06-21T00:00:00+00:00",
    )

    data = bundle.to_dict()
    assert len(data["raw_news_items"]) == 1
    assert data["raw_news_items"][0]["source_key"] == "reuters_public_news"
    assert len(data["event_candidates"]) == 1
    assert data["event_candidates"][0]["data_quality"]["merged_item_count"] == 1


def test_official_release_enters_top_market_events_as_confirmed_scheduled_event() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="bls_calendar",
                source_type="official",
                feed_key="release_calendar",
                title="Consumer Price Index",
                url="https://www.bls.gov/cpi/",
                domain="bls.gov",
                event_type="inflation_release",
                published_at="2026-06-11T12:30:00+00:00",
                verification_status="official_confirmed",
            )
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    data = bundle.to_dict()
    assert len(data["event_candidates"]) == 1
    event = data["event_candidates"][0]
    assert event["verification_status"] == "official_confirmed"
    assert event["need_verification"] is False
    assert event["event_status"] == "scheduled"
    assert event["data_quality"]["verification_reason"] == "official_source_present"
    assert set(event["asset_tags"]) == {"XAUUSD", "DXY", "US02Y", "US10Y"}
    assert "inflation" in event["topic_tags"]
    assert data["top_market_events"][0]["event_id"] == event["event_id"]
    assert data["data_quality"]["official_confirmed_count"] == 1


def test_local_media_only_stays_unverified() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="local_mideast_media",
                source_type="local_media",
                title="Local media claims new shipping threat near Hormuz",
                url="https://local-a.example/hormuz",
                domain="local-a.example",
                event_type="hormuz_risk",
            ),
            _item(
                source_key="regional_wiretap",
                source_type="local_media",
                title="Local media claims new shipping threat near Hormuz",
                url="https://local-b.example/hormuz",
                domain="local-b.example",
                event_type="middle_east_escalation",
            ),
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    event = bundle.to_dict()["event_candidates"][0]
    assert event["verification_status"] == "unverified"
    assert event["need_verification"] is True
    assert event["data_quality"]["verification_reason"] == "local_media_only"
    assert bundle.to_dict()["data_quality"]["unverified_count"] == 1


def test_archive_event_candidates_writes_feature_artifact(tmp_path: Path) -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="gdelt_news",
                source_type="aggregator",
                title="Iran warns over Strait of Hormuz shipping",
                url="https://example.com/hormuz",
                domain="example.com",
                event_type="hormuz_risk",
            )
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    artifact_path = archive_event_candidates(
        storage_root=tmp_path,
        retrieved_date="2026-06-10",
        run_id="run-001",
        bundle=bundle,
    )

    assert artifact_path == "features/news/2026-06-10/run-001/event_candidates.json"
    assert (tmp_path / artifact_path).exists()
    assert '"event_candidates"' in (tmp_path / artifact_path).read_text(encoding="utf-8")
