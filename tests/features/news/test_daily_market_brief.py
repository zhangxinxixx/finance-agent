from __future__ import annotations

from pathlib import Path

from apps.collectors.news.base import RawNewsItem
from apps.features.news.daily_market_brief import archive_daily_market_brief, build_daily_market_brief
from apps.features.news.event_candidates import build_event_candidates
from apps.features.news.impact_classifier import build_impact_assessments


def _item(
    *,
    source_key: str,
    source_type: str,
    title: str,
    event_type: str,
    published_at: str,
    verification_status: str = "single_source",
) -> RawNewsItem:
    return RawNewsItem(
        source_key=source_key,
        source_name=source_key,
        source_type=source_type,
        feed_key="fixture",
        title=title,
        url=f"https://example.com/{source_key}/{event_type}",
        domain=f"{source_key}.example.com",
        published_at=published_at,
        fetched_at="2026-06-10T01:00:00+00:00",
        summary=title,
        source_country="US",
        source_language="en",
        event_type=event_type,
        verification_status=verification_status,
        duplicate_key=f"news:{source_key}:{event_type}:{published_at}",
    )


def _market_reaction(event_id: str) -> dict[str, object]:
    return {
        "event_id": event_id,
        "status": "available",
        "baseline_time": "2026-06-10T08:14:00+00:00",
        "market_snapshot": {
            "event_time": "2026-06-10T08:15:00+00:00",
            "requested_assets": ["XAUUSD", "DXY", "US10Y", "WTI", "USDJPY"],
            "observed_assets": ["DXY", "WTI"],
            "missing_assets": ["XAUUSD", "US10Y", "USDJPY"],
            "primary_window": "30m",
            "assets": [],
        },
        "pricing_status": "partially_priced",
        "confirmation_summary": {"confirmed_count": 2, "contradicted_count": 0, "observed_count": 3},
        "warnings": [],
        "windows": {
            "30m": {
                "WTI": {
                    "pct_change": 0.88,
                    "change_bp": None,
                    "direction": "up",
                    "threshold_hit": True,
                    "expected_direction": "up",
                },
                "DXY": {
                    "pct_change": 0.14,
                    "change_bp": None,
                    "direction": "up",
                    "threshold_hit": True,
                    "expected_direction": "up",
                },
            }
        },
    }


def test_daily_market_brief_separates_confirmed_calendar_from_candidate_risks() -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="bls_calendar",
                source_type="official",
                title="Consumer Price Index",
                event_type="inflation_release",
                published_at="2026-06-11T12:30:00+00:00",
                verification_status="official_confirmed",
            ),
            _item(
                source_key="gdelt_news",
                source_type="aggregator",
                title="Iran warns over Strait of Hormuz shipping",
                event_type="hormuz_risk",
                published_at="2026-06-10T08:15:00+00:00",
            ),
            _item(
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
                title="Iran warns over Strait of Hormuz shipping",
                event_type="middle_east_escalation",
                published_at="2026-06-10T08:15:00+00:00",
            ),
            _item(
                source_key="jin10_report_events",
                source_type="supplemental",
                title="Jin10 report says gold ETF money is waiting for catalysts",
                event_type="gold_fund_flow",
                published_at="2026-06-10T00:00:00+00:00",
            ),
        ],
        as_of="2026-06-10T01:00:00+00:00",
    )
    assessments = build_impact_assessments(bundle.event_candidates, as_of="2026-06-10T01:00:00+00:00")
    hormuz_event = next(event for event in bundle.event_candidates if event.event_type == "hormuz_risk")

    brief = build_daily_market_brief(
        event_bundle=bundle,
        impact_assessments=assessments,
        market_reactions=[_market_reaction(hormuz_event.event_id)],
        as_of="2026-06-10T01:00:00+00:00",
    )
    data = brief.to_dict()

    assert data["next_7d_calendar"][0]["event_name"] == "Consumer Price Index"
    assert data["next_7d_calendar"][0]["expected_impact_path"] == "scheduled_macro_release_to_rates"
    assert data["confirmed_events"][0]["verification_status"] == "official_confirmed"
    assert data["confirmed_events"][0]["source_status"] == "official_confirmed"

    assert any(event["event_type"] == "hormuz_risk" for event in data["candidate_events"])
    assert any(risk["event_id"] == hormuz_event.event_id for risk in data["unconfirmed_risks"])
    assert all(event["verification_status"] != "official_confirmed" for event in data["candidate_events"])
    assert any(event["source_status"] == "multi_source_unofficial" for event in data["candidate_events"] if event["event_type"] == "hormuz_risk")
    assert any(event["source_status"] == "needs_verification" for event in data["candidate_events"] if event["event_type"] == "gold_fund_flow")

    watchlist_ids = {item["event_id"] for item in data["report_inputs"]["watchlist"]}
    jin10_event = next(event for event in bundle.event_candidates if event.event_type == "gold_fund_flow")
    assert jin10_event.event_id in watchlist_ids
    assert jin10_event.event_id not in {event["event_id"] for event in data["confirmed_events"]}

    assert data["asset_reactions"][0]["asset"] == "WTI"
    assert data["asset_reactions"][0]["pricing_status"] == "partially_priced"
    hormuz_brief = next(item for item in data["candidate_events"] if item["event_id"] == hormuz_event.event_id)
    assert hormuz_brief["market_validation"]["market_snapshot"]["requested_assets"] == [
        "XAUUSD",
        "DXY",
        "US10Y",
        "WTI",
        "USDJPY",
    ]
    assert any(item["event_id"] == hormuz_event.event_id for item in data["report_inputs"]["news_highlights"])
    assert data["data_quality"]["event_candidate_count"] == len(bundle.event_candidates)


def test_archive_daily_market_brief_writes_feature_artifact(tmp_path: Path) -> None:
    bundle = build_event_candidates(
        [
            _item(
                source_key="bls_calendar",
                source_type="official",
                title="Consumer Price Index",
                event_type="inflation_release",
                published_at="2026-06-11T12:30:00+00:00",
                verification_status="official_confirmed",
            )
        ],
        as_of="2026-06-10T01:00:00+00:00",
    )
    brief = build_daily_market_brief(
        event_bundle=bundle,
        impact_assessments=build_impact_assessments(bundle.event_candidates, as_of="2026-06-10T01:00:00+00:00"),
        market_reactions=[],
        as_of="2026-06-10T01:00:00+00:00",
    )

    artifact_path = archive_daily_market_brief(
        storage_root=tmp_path,
        retrieved_date="2026-06-10",
        run_id="run-001",
        brief=brief,
    )

    assert artifact_path == "features/news/2026-06-10/run-001/daily_market_brief.json"
    assert (tmp_path / artifact_path).exists()
    assert '"daily_market_brief"' in (tmp_path / artifact_path).read_text(encoding="utf-8")
