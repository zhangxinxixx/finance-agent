"""Select current research evidence; retain articles before theme aggregation."""

import re


def build_research_news_focus(events: list[dict], raw_items: list[dict]) -> list[dict]:
    raw_by_id = {item.get("news_item_id") or item.get("duplicate_key"): item for item in raw_items}
    selected = []
    for event in events:
        refs = event.get("source_refs", [])
        title = next((ref.get("title") for ref in refs if ref.get("title")), event.get("evidence_text") or "")
        raw = raw_by_id.get(event.get("primary_news_item_id"), {})
        payload = raw.get("raw_payload", {})
        paragraphs = payload.get("article_paragraphs", [])
        body = " ".join(paragraphs)
        title_lower = title.lower()
        policy = _policy_message(paragraphs) if raw.get("source_key") == "fed_rss" and payload.get("full_text_available") else None
        if policy:
            topic, importance, implication = "美联储政策条件", 6, policy
        elif re.search(r"\bgold\b|\bxau(?:usd)?\b|\bbullion\b", title_lower):
            topic, importance = "黄金与跨资产反应", 4
            if re.search(r"payroll|\bjobs\b|\bnfp\b", title_lower):
                implication = "这条报道将黄金反应与就业数据联系起来。对照本报告已采集的非农增量、前值上修和利率日变化，检查这一解释是否一致；RSS最初发布时间不能充当文内行情时刻。"
            else:
                implication = "将报道的盘中时点与本报告完整日线分开，对照实际利率、美元与ETF增量，判断涨跌能否持续。"
        elif re.search(r"payroll|\bjobs\b|employment|\bnfp\b", title_lower):
            topic, importance = "就业与政策重定价", 5
            implication = "核对就业数量、工资和前值修订后，再看短端利率是否延续这一交易方向；报道中的预期值仍需独立来源核验。"
        elif re.search(r"iran|hormuz|opec|brent|\boil\b", title_lower):
            topic, importance = "能源与地缘风险", 3
            implication = "先确认供应或航运是否实际受影响，再检验油价、通胀预期与短端利率；同一事件也可能带来避险需求。"
        elif re.search(r"federal reserve|waller|warsh|rate hike|rate cut|inflation", title_lower):
            topic, importance = "政策与通胀线索", 3
            implication = "区分官员的条件判断、媒体解读和市场定价，等待后续通胀与利率变化验证。"
        else:
            continue
        full_text = bool(body) and raw.get("source_type") == "official" and payload.get("full_text_available") is True
        domain = str(raw.get("domain") or "").lower().removeprefix("www.")
        publisher_priority = 2 if domain == "reuters.com" else 1
        selected.append({"event_id": event.get("event_id"), "title": title, "event_time": event.get("event_time"),
                         "topic": topic, "importance": importance, "interpretation": implication,
                         "publisher_priority": publisher_priority,
                         "interpretation_kind": "rule_based_inference", "verification_status": event.get("verification_status"),
                         "evidence_scope": "official_full_text" if full_text else "headline_or_snippet_only",
                         "source_refs": refs, "quote": _short_policy_quote(paragraphs) if policy else None})
    selected.sort(key=lambda item: (item["importance"], item["publisher_priority"], item.get("event_time") or ""), reverse=True)
    # Limit repetition within a topic while retaining the official policy
    # counterargument, payroll trigger, gold reaction and energy development.
    result, counts = [], {}
    for item in selected:
        topic = item["topic"]
        if counts.get(topic, 0) >= 2:
            continue
        result.append(item)
        counts[topic] = counts.get(topic, 0) + 1
        if len(result) == 8:
            break
    return result


def _policy_message(paragraphs: list[str]) -> str | None:
    text = " ".join(paragraphs).lower()
    hold = bool(re.search(r"if .{0,300}inclined to support holding", text))
    hike = bool(re.search(r"if .{0,350}appropriate to raise the policy rate", text))
    if hold and hike:
        return "原文同时保留两条路径：通胀改善延续时倾向维持利率，改善未能延续时可能加息。因此这份讲话提供的是数据条件，而不是已经承诺暂停；接下来的通胀数据仍能改变政策选择。"
    if "underlying inflation" in text and "sufficient speed" in text and "work to do" in text:
        return "讲话要求基础通胀以足够速度回到目标，否则政策仍有工作要做。这支持继续关注收紧风险，但原文没有给出无条件的加息承诺或次数。"
    return None


def _short_policy_quote(paragraphs: list[str]) -> str | None:
    for paragraph in paragraphs:
        if "inclined to support holding" in paragraph or "underlying inflation" in paragraph and "sufficient speed" in paragraph:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            sentence = next((sentence for sentence in sentences if "inclined" in sentence or "sufficient speed" in sentence), paragraph)
            return " ".join(sentence.split()[:20]) + (" …" if len(sentence.split()) > 20 else "")
    return None
