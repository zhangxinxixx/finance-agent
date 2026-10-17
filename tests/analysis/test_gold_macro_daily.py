from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from apps.analysis.agents import research_synthesis as synthesis
from apps.analysis.agents.research_input import RESEARCH_PRESENTATION_VERSION
from apps.analysis.snapshots.input_validation import prepare_analysis_inputs
from apps.analysis.snapshots.report_continuity import attach_prior_report_contexts
from apps.output.final_report import write_final_report
from apps.renderer.markdown.gold_reader import reader_audit_details, reader_sections, render_reader_report
from apps.worker.adaptive_research import plan_research
from tests.analysis.test_gold_detailed_report import response as detailed_response
from tests.analysis.test_gold_detailed_report import snapshot as detailed_snapshot
from tests.analysis.test_input_validation import valid_snapshot
from tests.worker.test_adaptive_research import snapshot as planner_snapshot


def context_payload(current=None, *, daily_body="# 日报\n旧假设。", weekly_body="# 周报\n旧分歧。"):
    def item(cadence, body, day, generated):
        digest = sha256(body.encode()).hexdigest()
        return {
            "status": "verified",
            "asset": "XAUUSD",
            "cadence": cadence,
            "report_id": f"{cadence}-report",
            "run_id": f"{cadence}-run",
            "snapshot_id": f"{cadence}-snapshot",
            "trade_date": day,
            "actual_cutoff": generated,
            "generated_at": generated,
            "available_at": generated,
            "availability_basis": "report_and_artifact_registry_revision",
            "family": f"gold_macro_{cadence}_markdown",
            "report_type": f"gold_macro_{cadence}",
            "body": body,
            "body_utf8_bytes": len(body.encode()),
            "verified_body_sha256": digest,
            "artifact_ref": f"reports/{cadence}/main.md",
            "source_refs": [{"source": "verified_prior_report_context", "source_ref": f"{cadence}-report",
                             "artifact_ref": f"reports/{cadence}/main.md", "sha256": digest,
                             "snapshot_id": f"{cadence}-snapshot", "status": "verified"}],
            "input_snapshot_ids": {"analysis_snapshot": f"{cadence}-snapshot"},
            "model_input_status": "included_full_body",
            "data_category": "historical_opinion",
            "formal_state_authority": False,
            "accepted_authority": False,
        }
    return {
        "schema_version": "gold_report_context.v1",
        "status": "verified",
        "asset": "XAUUSD",
        "current_snapshot_id": (current or {}).get("snapshot_id", "current"),
        "cutoff": "2026-10-07T01:30:00+00:00",
        "contexts": {
            "daily": item("daily", daily_body, "2026-10-06", "2026-10-06T12:00:00+00:00"),
            "weekly": item("weekly", weekly_body, "2026-10-02", "2026-10-02T12:00:00+00:00"),
        },
    }


def new_daily_payload():
    data = detailed_snapshot()
    data["gold_workflow"]["reader_presentation"] = RESEARCH_PRESENTATION_VERSION
    return synthesis._build_prompt_payload(data, __import__(
        "tests.analysis.test_research_synthesis", fromlist=["_output"]
    )._output())


def test_actual_message_chain_loads_daily_before_weekly_and_keeps_payload():
    payload = new_daily_payload()
    before = deepcopy(payload)

    messages = synthesis._build_messages(payload)

    assert len(messages) == 4
    assert "黄金宏观日报研究与表达方法" in messages[1]["content"]
    assert "黄金宏观周报可复用研究模板" in messages[2]["content"]
    assert json.loads(messages[3]["content"].split("\n", 1)[1]) == before
    assert payload == before


def test_new_daily_parser_requires_full_narrative_and_preserves_old_v4():
    payload = new_daily_payload()
    answer = detailed_response()
    with pytest.raises(ValueError, match="complete narrative"):
        synthesis._parse_and_validate(json.dumps(answer, ensure_ascii=False), payload)
    answer["reader_narrative"] = "## 一句话结论\n\n当前矛盾仍需用新事实重验。\n\n## 主线\n\n本次正文完整保留。"
    parsed = synthesis._parse_and_validate(json.dumps(answer, ensure_ascii=False), payload)
    assert parsed["reader_narrative"] == answer["reader_narrative"]

    legacy = detailed_snapshot()
    legacy_payload = synthesis._build_prompt_payload(legacy, __import__(
        "tests.analysis.test_research_synthesis", fromlist=["_output"]
    )._output())
    assert synthesis._parse_and_validate(
        json.dumps(detailed_response(), ensure_ascii=False), legacy_payload
    )["report_sections"]


def test_new_daily_without_conclusion_lead_enters_format_repair_contract():
    answer = detailed_response()
    answer["reader_narrative"] = "## 当天主线\n\n完整正文但缺少开头判断。"
    with pytest.raises(ValueError, match="open with 一句话结论"):
        synthesis._parse_and_validate(json.dumps(answer, ensure_ascii=False), new_daily_payload())


def test_planner_receives_both_full_verified_historical_bodies():
    data = planner_snapshot()
    data["asset"] = "XAUUSD"
    data["snapshot_time"] = "2026-10-07T01:30:00+00:00"
    data["trade_date"] = "2026-10-07"
    data = attach_prior_report_contexts(data, context_payload(data))

    def gateway(**kwargs):
        packed = json.loads(kwargs["messages"][1]["content"])
        contexts = packed["prior_report_contexts"]["contexts"]
        assert contexts["daily"]["body"] == "# 日报\n旧假设。"
        assert contexts["weekly"]["body"] == "# 周报\n旧分歧。"
        assert contexts["daily"]["model_input_status"] == "included_full_body"
        assert packed["prior_report_contexts"]["authority_boundary"].startswith("Historical reports")
        return SimpleNamespace(content=json.dumps({
            "action": "finish",
            "question": "当前主导矛盾是什么？",
            "hypothesis": "旧假设需要当前证据重验。",
            "driver_assessment": "当前证据尚不能把旧观点升级为事实。",
            "competing_hypotheses": ["另一宏观渠道"],
            "falsifier": "新事实与当前判断相反。",
            "why_these_requests": "现有证据足以结束本轮补采。",
            "evidence_assessment": "已读取两份历史正文并以当前事实重验。",
            "data_requests": [],
            "unavailable_data_needs": [],
            "finish_reason": "evidence_sufficient",
        }), audit_id="planner-audit", model="fixture")

    assert plan_research(data, gateway)["action"] == "finish"


def test_final_synthesis_input_receives_same_verified_daily_and_weekly_bodies():
    data = detailed_snapshot()
    data["asset"] = "XAUUSD"
    data["run_id"] = "current-run"
    data["gold_workflow"]["reader_presentation"] = RESEARCH_PRESENTATION_VERSION
    contexts = context_payload(data)
    contexts["contexts"]["daily"].update({
        "trade_date": "2026-10-03",
        "actual_cutoff": "2026-10-03T06:00:00+00:00",
        "generated_at": "2026-10-03T06:00:00+00:00",
        "available_at": "2026-10-03T06:00:00+00:00",
    })
    contexts["contexts"]["weekly"].update({
        "trade_date": "2026-09-27",
        "actual_cutoff": "2026-09-27T06:00:00+00:00",
        "generated_at": "2026-09-27T06:00:00+00:00",
        "available_at": "2026-09-27T06:00:00+00:00",
    })
    data = attach_prior_report_contexts(data, contexts)

    payload = synthesis._build_prompt_payload(data, __import__(
        "tests.analysis.test_research_synthesis", fromlist=["_output"]
    )._output())

    assert payload["prior_report_contexts"]["contexts"]["daily"]["body"] == "# 日报\n旧假设。"
    assert payload["prior_report_contexts"]["contexts"]["weekly"]["body"] == "# 周报\n旧分歧。"
    assert payload["prior_report_contexts"]["contexts"]["daily"]["data_category"] == "historical_opinion"


def test_prepare_inputs_preserves_new_presentation_and_revalidates_context():
    data = valid_snapshot()
    data["snapshot_time"] = "2026-10-07T01:30:00+00:00"
    data["trade_date"] = "2026-10-07"
    data["gold_workflow"]["reader_report_version"] = "gold_reader.v4"
    data["gold_workflow"]["reader_presentation"] = RESEARCH_PRESENTATION_VERSION
    attached = attach_prior_report_contexts(data, context_payload(data))
    before = deepcopy(attached)

    prepared = prepare_analysis_inputs(attached)

    assert attached == before
    assert prepared["gold_workflow"]["reader_presentation"] == RESEARCH_PRESENTATION_VERSION
    assert prepared["prior_report_contexts"]["status"] == "verified"
    prepared["prior_report_contexts"]["contexts"]["daily"]["body"] += "tamper"
    rejected = prepare_analysis_inputs(prepared)
    assert rejected["prior_report_contexts"]["contexts"]["daily"]["reason_code"] == "attached_body_sha256_mismatch"
    assert "prior_report_daily" not in rejected["input_snapshot_ids"]


def test_new_reader_uses_same_full_body_for_markdown_and_structured_content(tmp_path):
    data = detailed_snapshot()
    data["gold_workflow"]["reader_presentation"] = RESEARCH_PRESENTATION_VERSION
    data["gold_workflow"]["price_anchor"].update({
        "status": "verified",
        "price": 4200.5,
        "price_time": "2026-10-04T07:00:00+00:00",
        "source_refs": [{"source": "spot_provider", "source_url": "https://example.test/spot"}],
    })
    data["input_validation"] = {"status": "partial", "domains": {"options": {"status": "unavailable"}}}
    answer = detailed_response()
    narrative = "## 一句话结论\n\n**阶段与矛盾已经重验。**\n\n## 当天主线\n\n这是完整正文，不应被截断或机械改写。"
    answer["reader_narrative"] = narrative
    synthesis_payload = {
        "status": "success",
        "analysis": answer,
        "evidence_ids": answer["evidence_ids"],
        "evidence_catalog_ids": [f"detailed:{key}" for key in answer["report_sections"]],
        "macro_review": {"status": "pass"},
    }
    outputs = {"coordinator": SimpleNamespace(input_payload={"research_synthesis": synthesis_payload})}

    sections = reader_sections(data, outputs, {})
    assert [section["section_id"] for section in sections] == ["model_research", "research_scope"]
    assert sections[0]["body"] == narrative
    markdown = render_reader_report(data, sections)
    assert narrative in markdown
    assert "## 完整研判" not in markdown
    assert "2026年10月04日 15:00" in markdown
    assert "spot_provider" in markdown
    assert "GC期货" not in markdown.split("完整研判", 1)[0]
    structured = {"sections": sections}
    result = write_final_report(
        storage_root=tmp_path,
        trade_date=data["trade_date"],
        run_id="new-daily-reader",
        markdown=markdown,
        audit_markdown="# 审计\n" + reader_audit_details(data, outputs),
        structured_report=structured,
    )
    paths = {path.rsplit("/", 1)[-1]: path for path in result["paths"]}
    assert open(paths["final_report.md"], encoding="utf-8").read() == markdown
    saved = json.load(open(paths["structured_report.json"], encoding="utf-8"))
    assert saved["sections"][0]["body"] == narrative
    assert narrative not in open(paths["audit_report.md"], encoding="utf-8").read()


@pytest.mark.parametrize("damage", ["future", "futures", "nonfinite"])
def test_reference_spot_rejects_invalid_price_or_clock(damage):
    from apps.renderer.markdown.gold_reader import _reference_spot_line
    data = detailed_snapshot()
    anchor = data["gold_workflow"]["price_anchor"]
    anchor.update(status="verified", price=4200.5, price_time="2026-10-04T07:00:00+00:00",
                  source_refs=[{"source": "fixture"}])
    if damage == "future":
        anchor["price_time"] = "2026-10-05T07:00:00+00:00"
    elif damage == "futures":
        anchor["instrument"] = "GC"
    else:
        anchor["price"] = float("nan")
    assert "不可用" in _reference_spot_line(data)


def test_rejected_context_is_explicitly_not_claimed_as_read():
    data = planner_snapshot()
    data["asset"] = "XAUUSD"
    payload = context_payload(data)
    payload["contexts"]["weekly"] = {
        "status": "unavailable", "cadence": "weekly", "reason_code": "body_oversized",
        "model_input_status": "not_included", "formal_state_authority": False,
    }
    attached = attach_prior_report_contexts(data, payload)
    from apps.analysis.snapshots.report_continuity import prior_report_context_model_input
    model_input = prior_report_context_model_input(attached)
    assert model_input["contexts"]["weekly"] == {
        "status": "unavailable", "cadence": "weekly", "reason_code": "body_oversized",
        "model_input_status": "not_included", "formal_state_authority": False,
        "failure_category": "body_unavailable", "failure_category_counts": {"body_unavailable": 1},
    }
    assert "body" not in model_input["contexts"]["weekly"]
