from apps.collectors.news.base import RawNewsItem
from apps.features.news.daily_market_brief import build_daily_market_brief
from apps.features.news.event_candidates import build_event_candidates
from apps.parsers.news.fed_article import parse_fed_article


def item(title, at, *, event_type="gold_market_narrative", official=False, paragraphs=None):
    return RawNewsItem(source_key="fed_rss" if official else "reuters_public_news", source_name="Fed" if official else "Reuters",
        source_type="official" if official else "wire_public_candidate", feed_key="speeches_testimony", title=title,
        url="https://www.federalreserve.gov/newsevents/speech/example.htm" if official else "https://reuters.com/" + title,
        domain="federalreserve.gov" if official else "reuters.com", published_at=at, fetched_at="2026-09-06T12:00:00+00:00",
        event_type=event_type, verification_status="official_confirmed" if official else "single_source",
        raw_path="raw/news/source.json", parsed_path="parsed/news/source.json",
        raw_payload={"full_text_available": bool(paragraphs), "content_scope": "full_text" if paragraphs else "headline_summary_only", "article_paragraphs": paragraphs or []})


def test_prior_week_official_speech_remains_news_and_opposite_gold_articles_do_not_merge():
    items = [item("A policy speech", "2026-08-28T14:00:00+00:00", event_type="fed_speech", official=True),
             item("Gold jumps after comments", "2026-09-03T15:00:00+00:00"),
             item("Gold slides after payrolls", "2026-09-04T17:00:00+00:00"),
             item("Future headline", "2026-09-06T16:00:00+00:00")]
    bundle = build_event_candidates(items, as_of="2026-09-06T13:00:00+00:00", preserve_articles=True)
    assert len(bundle.event_candidates) == 3
    assert len({event.event_id for event in bundle.event_candidates}) == 3
    assert sum(event.verification_status == "official_confirmed" for event in bundle.event_candidates) == 1
    assert all(event.data_quality["grouping_strategy"] == "title_time" for event in bundle.event_candidates)


def test_full_official_body_enters_focus_with_conditional_counterargument_and_refs():
    paragraph = "If this continues in the data due over the next two weeks, I would be inclined to support holding the target for the federal funds rate at its current setting. If the incoming data show this improvement has been fleeting, then it may be appropriate to raise the policy rate."
    speech = item("Economic outlook", "2026-09-03T12:30:00+00:00", event_type="fed_speech", official=True, paragraphs=[paragraph])
    bundle = build_event_candidates([speech], as_of="2026-09-06T13:00:00+00:00", preserve_articles=True)
    brief = build_daily_market_brief(event_bundle=bundle, impact_assessments=[], market_reactions=[], as_of=bundle.as_of)
    focus = brief.report_inputs["research_focus"]
    assert focus[0]["evidence_scope"] == "official_full_text"
    assert "两条路径" in focus[0]["interpretation"]
    assert focus[0]["source_refs"] and len(focus[0]["quote"].split()) <= 21


def test_fed_article_parser_excludes_navigation_and_footnotes_and_needs_article():
    doc = '<nav>Policy claims in navigation</nav><div id="article"><p>First policy paragraph.</p><p>Second paragraph.</p><p>1. Footnote Return to text</p></div>'
    result = parse_fed_article(doc)
    assert result["paragraphs"] == ["First policy paragraph.", "Second paragraph."]
    assert parse_fed_article('<body>Access denied</body>')["status"] == "unavailable"


def test_payroll_gold_reaction_survives_other_employment_articles_and_unofficial_body_is_not_official():
    news = [item("Gold slides after payrolls", "2026-09-04T12:00:00+00:00", paragraphs=["A newspaper opinion."]),
            item("Yields rise after jobs report", "2026-09-04T16:00:00+00:00"),
            item("Stocks drop after jobs report", "2026-09-04T17:00:00+00:00"),
            item("Employment outlook", "2026-09-05T10:00:00+00:00")]
    bundle = build_event_candidates(news, as_of="2026-09-06T12:00:00+00:00", preserve_articles=True)
    brief = build_daily_market_brief(event_bundle=bundle, impact_assessments=[], market_reactions=[], as_of=bundle.as_of)
    gold = next(entry for entry in brief.report_inputs["research_focus"] if "Gold slides" in entry["title"])
    assert gold["evidence_scope"] == "headline_or_snippet_only"
    assert gold["quote"] is None


def test_goldman_oil_forecast_is_energy_evidence_and_does_not_displace_gold():
    news = [item("Goldman sees oil at $120 after Iran disruption", "2026-09-04T12:00:00+00:00"),
            item("Gold slides after payrolls", "2026-09-04T13:00:00+00:00")]
    bundle = build_event_candidates(news, as_of="2026-09-06T12:00:00+00:00", preserve_articles=True)
    brief = build_daily_market_brief(event_bundle=bundle, impact_assessments=[], market_reactions=[], as_of=bundle.as_of)
    focus = {entry["title"]: entry for entry in brief.report_inputs["research_focus"]}
    assert focus[news[0].title]["topic"] == "能源与地缘风险"
    assert focus[news[1].title]["topic"] == "黄金与跨资产反应"
