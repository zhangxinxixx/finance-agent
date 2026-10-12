"""Topic reading must preserve the registered research's identity and limitations."""
from copy import deepcopy

import pytest

from apps.analysis.agents.research_input import DETAILED_REASONING_FIELDS, DETAILED_TOPICS
from apps.api.services.gold_research_topics import project_research_topics, verified_report_topics

IDENTITY = {"report_id": "engineering-report", "run_id": "engineering-run", "snapshot_id": "engineering-snapshot",
            "trade_date": "2026-10-07", "as_of": "2026-10-07T09:00:00Z"}
BODY = "## 一句话结论\n\n工程样例：结构和宏观条件尚未确认，原证据必须独立核验。"


def synthesis():
    modules = {}
    for key in DETAILED_TOPICS:
        row = {field: f"工程主题{key}的{field}：原证据只能支持条件观点，仍须核验对应时点与价格响应。"
               for field in DETAILED_REASONING_FIELDS}
        row.update(evidence_ids=["detailed:" + key], pending=["工程缺口：事件时间与结构尚未核验。"])
        if key == "scenarios":
            row["paths"] = {name: {field: "工程路径：等待各自证据与价格条件共同核验。"
                                   for field in ("macro", "funds", "price", "region", "trigger", "invalidation", "window")}
                            for name in ("main", "up", "down")}
        if key == "observation":
            row["cards"] = {name: {field: "工程结构：尚未确认，仅保留观察与失效条件。"
                                   for field in ("4H", "1H", "15m", "invalidation")}
                            for name in ("flat", "long", "short")}
        modules[key] = row
    return {"status": "success", "report_profile_version": "gold_reader.v4",
            "prompt_input_snapshot_id": IDENTITY["snapshot_id"],
            "evidence_catalog_ids": ["detailed:" + key for key in DETAILED_TOPICS],
            "analysis": {"reader_narrative": BODY, "report_sections": modules}}


def research(status="historical"):
    return {**IDENTITY, "status": status, "narrative": BODY}


def test_complete_reasoning_pending_and_identity_are_copied_without_mutation():
    source = synthesis()
    before = deepcopy(source)
    verified = verified_report_topics(synthesis=source, narrative="前言\n" + BODY + "\n尾部局限", identity=IDENTITY)
    assert verified is not None
    result = project_research_topics(research(), verified)
    assert len(result) == 20 and {row["key"] for row in result} == set(DETAILED_TOPICS)
    assert all(row["status"] == "historical" and row["basis"] == "verified_report_topics" for row in result)
    for row in result:
        assert all(row[k] == IDENTITY[k] for k in IDENTITY)
        assert all(row[f] == source["analysis"]["report_sections"][row["key"]][f] for f in DETAILED_REASONING_FIELDS)
        assert row["pending"] == ["工程缺口：事件时间与结构尚未核验。"]
    result[0]["pending"].append("仅改投影")
    verified["modules"]["labor"]["judgment"] = "仅改投影"
    assert source == before


@pytest.mark.parametrize("change", ["fallback", "wrong_profile", "wrong_snapshot", "wrong_reader", "unknown_evidence", "missing_reasoning", "missing_path"])
def test_unverified_or_incomplete_coordinator_never_opens_the_topic_projection(change):
    source = synthesis()
    if change == "fallback":
        source["status"] = "rule_fallback"
    elif change == "wrong_profile":
        source["report_profile_version"] = "gold_reader.v3"
    elif change == "wrong_snapshot":
        source["prompt_input_snapshot_id"] = "other-snapshot"
    elif change == "wrong_reader":
        source["analysis"]["reader_narrative"] = "另一份报告"
    elif change == "unknown_evidence":
        source["analysis"]["report_sections"]["dollar"]["evidence_ids"].append("unverified-id")
    elif change == "missing_reasoning":
        del source["analysis"]["report_sections"]["flows"]["alternatives"]
    elif change == "missing_path":
        del source["analysis"]["report_sections"]["scenarios"]["paths"]["down"]
    assert verified_report_topics(synthesis=source, narrative=BODY, identity=IDENTITY) is None


@pytest.mark.parametrize("field", list(IDENTITY))
def test_mismatched_report_identity_cannot_copy_topic_judgments(field):
    verified = verified_report_topics(synthesis=synthesis(), narrative=BODY, identity=IDENTITY)
    verified[field] = "other-identity"
    rows = project_research_topics(research(), verified)
    assert all(row["basis"] == "unavailable" and row["judgment"] == "" for row in rows)


def test_unavailable_research_does_not_leak_reasoning_or_missing_evidence():
    verified = verified_report_topics(synthesis=synthesis(), narrative=BODY, identity=IDENTITY)
    rows = project_research_topics(research("unavailable"), verified)
    assert len(rows) == 20
    assert all(row["status"] == "unavailable" and not row["facts"] and not row["pending"] for row in rows)


def test_older_report_retains_full_original_passage_and_ignores_fake_code_headings():
    value = research()
    value["narrative"] = "## 美元与计价压力\n\n工程判断。\n\n工程详细反证与条件。\n\n```md\n## 流动性\n伪标题\n```\n\n## 其他\n\n尾部内容。"
    rows = project_research_topics(value, None)
    dollar = next(row for row in rows if row["key"] == "dollar")
    assert dollar["basis"] == "report_excerpt" and "工程详细反证与条件" in dollar["sections"][0]["content"]
    assert not dollar["facts"] and not dollar["transmission"]
    assert next(row for row in rows if row["key"] == "liquidity")["status"] == "unavailable"
