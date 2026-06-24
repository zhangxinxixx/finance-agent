from __future__ import annotations

from apps.features.news.snapshot import build_news_snapshot


def test_build_news_snapshot_deduplicates_flash_and_scores_high_risk():
    snapshot = build_news_snapshot(
        [
            {"symbol": "NEWS_EVENT:美国CPI", "date": "2026-05-16T08:30:00+00:00", "value": 5},
            {"symbol": "NEWS_EVENT:FOMC纪要", "date": "2026-05-15T18:00:00+00:00", "value": 4},
            {"symbol": "NEWS_FLASH", "date": "2026-05-16T09:00:00+00:00", "source_url": "美联储-利率"},
            {"symbol": "NEWS_FLASH", "date": "2026-05-16T09:00:00+00:00", "source_url": "美联储-利率"},
        ],
        as_of="2026-05-16T12:00:00+00:00",
        source_refs=[{"source": "jin10_mcp", "method": "list_calendar"}],
    )

    data = snapshot.to_dict()
    assert data["risk_level"] == "HIGH"
    assert data["high_star_count_7d"] == 2
    assert len(data["recent_events"]) == 2
    assert len(data["recent_flashes"]) == 1
    assert data["source_refs"] == [{"source": "jin10_mcp", "method": "list_calendar"}]
