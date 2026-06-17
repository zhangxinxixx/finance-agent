from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NewsRelevanceDecision:
    decision: str
    score: float
    reasons: list[str]
    event_type_hint: str | None
    asset_tags: list[str]
    topic_tags: list[str]
    need_detail_fetch: bool
    need_verification: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_news_relevance(
    text: str,
    *,
    links: list[str] | None = None,
    source_marker: str | None = None,
) -> NewsRelevanceDecision:
    normalized = text.lower()
    links = links or []
    score = 0.0
    reasons: list[str] = []
    event_scores: dict[str, float] = {}
    assets: list[str] = []
    topics: list[str] = []

    def add(
        *,
        reason: str,
        weight: float,
        event_type: str,
        asset_tags: list[str],
        topic_tags: list[str],
    ) -> None:
        nonlocal score
        if reason not in reasons:
            reasons.append(reason)
        score += weight
        event_scores[event_type] = event_scores.get(event_type, 0.0) + weight
        assets.extend(asset_tags)
        topics.extend(topic_tags)

    if _contains_any(normalized, ["霍尔木兹", "伊朗", "以色列", "中东", "停火", "红海", "胡塞", "hormuz", "iran", "israel"]):
        add(
            reason="geo_risk",
            weight=0.45,
            event_type="hormuz_risk",
            asset_tags=["XAUUSD", "WTI", "Brent", "DXY"],
            topic_tags=["geopolitics", "energy", "safe_haven"],
        )
    if _contains_any(normalized, ["原油", "油价", "布油", "wti", "brent", "opec", "欧佩克", "航运", "油轮"]):
        add(
            reason="oil_inflation_path",
            weight=0.25,
            event_type="oil_supply_shock",
            asset_tags=["WTI", "Brent", "XAUUSD", "DXY"],
            topic_tags=["energy", "inflation"],
        )
    if _contains_any(normalized, ["美联储", "鲍威尔", "fomc", "fed", "利率", "通胀", "cpi", "pce", "非农"]):
        add(
            reason="rates_macro_path",
            weight=0.42,
            event_type="fed_hawkish",
            asset_tags=["XAUUSD", "DXY", "US02Y", "US10Y"],
            topic_tags=["rates", "macro"],
        )
    if _contains_any(normalized, ["降息", "鸽派", "dovish", "rate cut"]):
        add(
            reason="rate_cut_expectation",
            weight=0.16,
            event_type="fed_dovish",
            asset_tags=["XAUUSD", "DXY", "US02Y", "US10Y"],
            topic_tags=["rates", "macro"],
        )
    if _contains_any(normalized, ["黄金", "金价", "现货黄金", "xau", "comex gold"]):
        add(
            reason="gold_direct",
            weight=0.20,
            event_type="gold_market_narrative",
            asset_tags=["XAUUSD"],
            topic_tags=["gold"],
        )
    if _contains_any(normalized, ["白银", "银价", "现货白银", "xag", "silver"]):
        add(
            reason="silver_direct",
            weight=0.20,
            event_type="silver_industrial_demand",
            asset_tags=["XAGUSD"],
            topic_tags=["silver"],
        )
    if _contains_any(normalized, ["美元", "dxy", "usdjpy", "日元", "日本", "干预", "boj", "植田"]):
        add(
            reason="fx_transmission",
            weight=0.20,
            event_type="yen_intervention_risk",
            asset_tags=["DXY", "XAUUSD"],
            topic_tags=["fx"],
        )

    if source_marker:
        score += 0.12
        reasons.append("jin10_source_marker")
    if links:
        score += 0.10
        reasons.append("detail_link_present")

    score = min(round(score, 2), 1.0)
    if score >= 0.75:
        decision = "high_value"
    elif score >= 0.35:
        decision = "candidate"
    elif score >= 0.10:
        decision = "archive_only"
    else:
        decision = "reject"

    return NewsRelevanceDecision(
        decision=decision,
        score=score,
        reasons=_dedupe(reasons),
        event_type_hint=_select_event_type(event_scores),
        asset_tags=_dedupe(assets),
        topic_tags=_dedupe(topics),
        need_detail_fetch=decision in {"candidate", "high_value"} and bool(links),
        need_verification=decision != "reject",
    )


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


def _select_event_type(event_scores: dict[str, float]) -> str | None:
    if not event_scores:
        return None
    priority = {
        "hormuz_risk": 100,
        "oil_supply_shock": 80,
        "fed_hawkish": 78,
        "fed_dovish": 78,
        "yen_intervention_risk": 70,
        "gold_market_narrative": 65,
        "silver_industrial_demand": 62,
    }
    return sorted(event_scores, key=lambda key: (event_scores[key], priority.get(key, 0)), reverse=True)[0]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
