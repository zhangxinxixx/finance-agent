from __future__ import annotations

from pathlib import Path

from apps.collectors.news.base import RawNewsItem
from apps.features.news.event_candidates import build_event_candidates
from apps.features.news.impact_classifier import archive_impact_assessments, build_impact_assessments


def _item(
    *,
    event_type: str,
    title: str,
    source_key: str = "gdelt_news",
    source_type: str = "aggregator",
    verification_status: str = "single_source",
    published_at: str = "2026-06-10T08:15:00+00:00",
) -> RawNewsItem:
    return RawNewsItem(
        source_key=source_key,
        source_name=source_key,
        source_type=source_type,
        feed_key="fixture",
        title=title,
        url=f"https://example.com/{event_type}/{source_key}",
        domain=f"{source_key}.example.com",
        published_at=published_at,
        fetched_at="2026-06-10T08:20:00+00:00",
        summary="Short evidence summary",
        source_country="US",
        source_language="en",
        event_type=event_type,
        verification_status=verification_status,
        duplicate_key=f"news:{source_key}:{event_type}",
    )


def test_hormuz_risk_assessment_uses_oil_inflation_path() -> None:
    bundle = build_event_candidates(
        [
            _item(event_type="hormuz_risk", title="Iran warns over Strait of Hormuz shipping", source_key="gdelt_news"),
            _item(
                event_type="middle_east_escalation",
                title="Iran warns over Strait of Hormuz shipping",
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
            ),
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    assessments = build_impact_assessments(bundle.event_candidates, as_of="2026-06-10T08:30:00+00:00")

    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment.impact_path == "geo_risk_to_oil_to_inflation"
    assert assessment.gold_impact == "mixed"
    assert assessment.silver_impact == "mixed"
    assert assessment.dollar_impact == "dollar_strength"
    assert assessment.yield_impact == "yield_up"
    assert assessment.oil_impact == "oil_up"
    assert assessment.risk_level == "high"
    assert assessment.pricing_status == "unpriced"
    assert assessment.rule_version == "news-impact-rules-v1"
    assert assessment.confidence >= 0.6


def test_official_scheduled_inflation_release_is_scheduled_with_unknown_direction() -> None:
    bundle = build_event_candidates(
        [
            _item(
                event_type="inflation_release",
                title="Consumer Price Index",
                source_key="bls_calendar",
                source_type="official",
                verification_status="official_confirmed",
                published_at="2026-06-11T12:30:00+00:00",
            )
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    assessments = build_impact_assessments(bundle.event_candidates, as_of="2026-06-10T08:30:00+00:00")

    assessment = assessments[0]
    assert assessment.impact_path == "scheduled_macro_release_to_rates"
    assert assessment.gold_impact == "unknown"
    assert assessment.dollar_impact == "unknown"
    assert assessment.yield_impact == "unknown"
    assert assessment.pricing_status == "scheduled"
    assert assessment.risk_level == "medium"
    assert assessment.confidence == 0.95


def test_fed_dovish_assessment_maps_to_rate_cut_gold_support() -> None:
    bundle = build_event_candidates(
        [
            _item(
                event_type="fed_dovish",
                title="Fed officials signal rate cut could come sooner",
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
            ),
            _item(
                event_type="fed_dovish",
                title="Fed officials signal rate cut could come sooner",
                source_key="google_news_rss",
                source_type="aggregator",
            ),
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    assessments = build_impact_assessments(bundle.event_candidates, as_of="2026-06-10T08:30:00+00:00")

    assessment = assessments[0]
    assert assessment.impact_path == "weak_data_to_rate_cut"
    assert assessment.gold_impact == "bullish"
    assert assessment.dollar_impact == "dollar_weakness"
    assert assessment.yield_impact == "yield_down"
    assert assessment.oil_impact == "unknown"


def test_gold_fund_flow_assessment_stays_external_report_watchlist() -> None:
    bundle = build_event_candidates(
        [
            _item(
                event_type="gold_fund_flow",
                title="Jin10 report says gold ETF money is waiting for catalysts",
                source_key="jin10_report_events",
                source_type="supplemental",
            )
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    assessments = build_impact_assessments(bundle.event_candidates, as_of="2026-06-10T08:30:00+00:00")

    assessment = assessments[0]
    assert assessment.impact_path == "gold_etf_flow_watchlist"
    assert assessment.gold_impact == "neutral"
    assert assessment.pricing_status == "unknown"
    assert assessment.source_event["verification_status"] == "single_source"


def test_archive_impact_assessments_writes_feature_artifact(tmp_path: Path) -> None:
    bundle = build_event_candidates(
        [_item(event_type="hormuz_risk", title="Iran warns over Strait of Hormuz shipping")],
        as_of="2026-06-10T08:30:00+00:00",
    )
    assessments = build_impact_assessments(bundle.event_candidates, as_of="2026-06-10T08:30:00+00:00")

    artifact_path = archive_impact_assessments(
        storage_root=tmp_path,
        retrieved_date="2026-06-10",
        run_id="run-001",
        assessments=assessments,
    )

    assert artifact_path == "features/news/2026-06-10/run-001/impact_assessments.json"
    assert (tmp_path / artifact_path).exists()
    assert '"impact_assessments"' in (tmp_path / artifact_path).read_text(encoding="utf-8")


def test_assessment_confidence_orders_official_above_multi_above_single() -> None:
    official_bundle = build_event_candidates(
        [
            _item(
                event_type="fed_hawkish",
                title="Federal Reserve keeps hawkish rates guidance",
                source_key="fed_rss",
                source_type="official",
                verification_status="official_confirmed",
            )
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )
    multi_bundle = build_event_candidates(
        [
            _item(
                event_type="fed_hawkish",
                title="Federal Reserve keeps hawkish rates guidance",
                source_key="reuters_public_news",
                source_type="wire_public_candidate",
            ),
            _item(
                event_type="fed_hawkish",
                title="Federal Reserve keeps hawkish rates guidance",
                source_key="google_news_rss",
                source_type="aggregator",
            ),
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )
    single_bundle = build_event_candidates(
        [
            _item(
                event_type="fed_hawkish",
                title="Federal Reserve keeps hawkish rates guidance",
                source_key="google_news_rss",
                source_type="aggregator",
            )
        ],
        as_of="2026-06-10T08:30:00+00:00",
    )

    official_confidence = build_impact_assessments(official_bundle.event_candidates, as_of="2026-06-10T08:30:00+00:00")[0].confidence
    multi_confidence = build_impact_assessments(multi_bundle.event_candidates, as_of="2026-06-10T08:30:00+00:00")[0].confidence
    single_confidence = build_impact_assessments(single_bundle.event_candidates, as_of="2026-06-10T08:30:00+00:00")[0].confidence

    assert official_confidence > multi_confidence > single_confidence
