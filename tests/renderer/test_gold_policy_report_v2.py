from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.report_context import build_gold_report_context, build_gold_report_context_v1
from apps.renderer.gold_policy_report import (
    GoldReportRenderV2,
    build_gold_policy_report_render,
    build_gold_policy_report_render_v1,
    rebuild_gold_policy_report_render,
)
from tests.analysis.test_gold_daily_close_store import _bootstrap_v2_pair
from tests.analysis.test_gold_report_context_v1_1 import _event_blackout_pair


_SECTION_ORDER = (
    "executive_summary",
    "macro_background",
    "price_attribution",
    "state_transition",
    "strategy",
    "key_level_map",
    "scenarios",
    "major_events",
    "fundamental_change",
    "risks",
    "traceability",
)


def _facts(render: GoldReportRenderV2, section_id: str):
    section = next(section for section in render.sections if section.section_id == section_id)
    return {fact.fact_id: fact for fact in section.facts}


def test_v1_builder_remains_byte_and_identity_stable() -> None:
    loop_input, result = _bootstrap_v2_pair()
    context = build_gold_report_context(loop_input, result, run_id="renderer-smoke")

    render = build_gold_policy_report_render_v1(context)

    assert render.render_id == (
        "gold_policy_report_render.v1:6995046a2d629cb82a5dde825beea90fbe8bfe71687411cfcbaa0450acf9a882"
    )
    assert tuple(section.section_id for section in render.sections) == (
        "macro",
        "attribution",
        "state",
        "strategy",
        "key_levels",
        "data_quality",
    )
    assert rebuild_gold_policy_report_render(context, render.schema_version) == render

    legacy_context = build_gold_report_context_v1(loop_input, result)
    assert build_gold_policy_report_render(legacy_context).schema_version == "gold_policy_report_render.v1"


def test_v2_is_default_and_rebuilds_from_canonical_typed_sections() -> None:
    loop_input, result = _bootstrap_v2_pair()
    context = build_gold_report_context(loop_input, result, run_id="renderer-v2")

    render = build_gold_policy_report_render(context)

    assert render.schema_version == "gold_policy_report_render.v2"
    assert tuple(section.section_id for section in render.sections) == _SECTION_ORDER
    assert rebuild_gold_policy_report_render(context, render.schema_version) == render
    assert render.language_generation == "not_invoked"

    payload = render.model_dump(mode="python")
    payload["markdown"] += "invented prose"
    with pytest.raises(ValidationError, match="typed sections"):
        GoldReportRenderV2.model_validate(payload)

    with pytest.raises(ValueError, match="unsupported gold report render schema"):
        rebuild_gold_policy_report_render(context, "gold_policy_report_render.v999")  # type: ignore[arg-type]


def test_v2_projects_required_roles_transitions_scenarios_and_risks() -> None:
    loop_input, result = _bootstrap_v2_pair()
    context = build_gold_report_context(loop_input, result, run_id="renderer-facts")
    render = build_gold_policy_report_render(context)

    macro = _facts(render, "macro_background")
    attribution = _facts(render, "price_attribution")
    transition = _facts(render, "state_transition")
    strategy = _facts(render, "strategy")
    scenarios = _facts(render, "scenarios")
    risks = _facts(render, "risks")
    trace = _facts(render, "traceability")
    executive = _facts(render, "executive_summary")

    assert executive["executive.conclusion"].value.endswith("。")
    assert macro["macro.comparison_scope"].value == "previous_to_current_snapshot"
    assert {
        "attribution.primary.none",
        "attribution.secondary.none",
        "attribution.counter.none",
        "attribution.filtered.none",
    } <= set(attribution) or {fact_id.split(".")[1] for fact_id in attribution if fact_id.count(".") >= 2} >= {
        "primary",
        "secondary",
        "counter",
        "filtered",
    }
    assert {
        "transition.from",
        "transition.to",
        "transition.action",
        "transition.changed_dimensions",
        "transition.from_projection",
        "transition.to_projection",
        "transition.reasons",
        "transition.canonical_selection",
    } <= set(transition)
    assert {
        "strategy.reasons",
        "strategy.release",
        "strategy.review",
        "strategy.invalidation",
    } <= set(strategy)
    assert {
        "scenario.canonical",
        "scenario.release",
        "scenario.invalidation_review",
    } == set(scenarios)
    assert {
        "risks.missing_required",
        "risks.missing_confirmatory",
        "risks.prohibited",
        "risks.unresolved",
        "risks.conflicts",
        "risks.unexplained",
    } <= set(risks)
    assert {"trace.run", "trace.snapshot", "trace.authority", "trace.policies"} <= set(trace)
    assert any(fact_id.startswith("trace.input.") for fact_id in trace)


def test_events_fundamentals_and_key_levels_are_explicitly_fail_closed() -> None:
    loop_input, result = _event_blackout_pair()
    context = build_gold_report_context(loop_input, result, run_id="renderer-event")

    assert context.cme_options_snapshot is None
    render = build_gold_policy_report_render(context)
    events = _facts(render, "major_events")
    fundamental = _facts(render, "fundamental_change")
    key_levels = _facts(render, "key_level_map")

    assert events["events.classification_limit"].value == "major_classification_not_performed"
    assert any(fact_id.startswith("events.event.") for fact_id in events)
    assert fundamental["fundamental.status"].value == "unavailable"
    assert fundamental["fundamental.reason"].value == "NO_TYPED_FUNDAMENTAL_CHANGE_INPUT"
    assert "key_levels.count" in key_levels
    assert "key_levels.lifecycle_decisions" in key_levels
