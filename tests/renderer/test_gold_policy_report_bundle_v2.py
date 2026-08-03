from __future__ import annotations

import json

import pytest

from apps.analysis.gold_policy.report_context import build_gold_report_context
from apps.renderer.gold_policy_report import (
    build_gold_policy_report_render,
    build_gold_policy_report_render_v1,
)
from apps.renderer.gold_policy_report_bundle import (
    _visual_html_v2,
    build_gold_policy_report_bundle,
)
from tests.analysis.test_gold_daily_close_store import _bootstrap_v2_pair


def _projection():
    loop_input, result = _bootstrap_v2_pair()
    context = build_gold_report_context(loop_input, result, run_id="bundle-v2-test")
    return context, build_gold_policy_report_render(context)


def _by_name(items):
    return {item.path.as_posix(): item for item in items}


def _json(item):
    return json.loads(item.content.decode("utf-8"))


def test_v2_bundle_uses_typed_sections_for_all_report_views() -> None:
    context, render = _projection()

    first = build_gold_policy_report_bundle(context, render)
    second = build_gold_policy_report_bundle(context, render)
    items = _by_name(first)
    structured = _json(items["report_structured.json"])
    quality = _json(items["data_quality.json"])
    manifest = _json(items["report_manifest.json"])
    html = items["visual.html"].content.decode("utf-8")

    assert tuple(item.content for item in first) == tuple(item.content for item in second)
    assert structured["schema_version"] == "gold_policy_report_structured.v2"
    assert manifest["schema_version"] == "gold_policy_report_manifest.v2"
    assert quality["schema_version"] == "gold_policy_report_data_quality.v2"
    assert structured["domain_statuses"] == [item.model_dump(mode="json") for item in render.domain_statuses]
    assert structured["publication_status"] == render.report_status
    assert structured["domain_status"] == {item.domain: item.readiness for item in render.domain_statuses}
    assert [section["section_id"] for section in structured["sections"]] == [
        section.section_id for section in render.sections
    ]
    assert [[fact["fact_id"] for fact in section["facts"]] for section in structured["sections"]] == [
        [fact.fact_id for fact in section.facts] for section in render.sections
    ]
    assert {item["domain"] for item in quality["domain_statuses"]} == {
        "analysis",
        "strategy",
        "options",
        "events",
        "key_levels",
    }
    assert manifest["domain_statuses"] == structured["domain_statuses"]
    assert manifest["publication_status"] == render.report_status
    assert quality["domain_status"] == structured["domain_status"]
    assert manifest["input_snapshot_ids"] == context.input_snapshot_ids.model_dump(mode="json")

    assert "<main>" in html
    assert '<figure id="domain-readiness">' in html
    assert "<table>" in html
    assert '<section id="price_attribution"' in html
    assert '<section id="state_transition"' in html
    assert '<section id="key_level_map"' in html
    assert '<section id="scenarios"' in html
    assert '<section id="major_events"' in html
    assert '<section id="traceability"' in html
    assert "<dl>" in html
    assert "<ol>" in html
    assert "scenario.canonical" in html
    assert "events.classification_limit" in html
    assert "未提供（unavailable）" in html
    assert "Content-Security-Policy" in html
    assert "<pre" not in html
    assert "<script" not in html
    assert "<link" not in html


def test_v2_visual_escapes_every_typed_fact_value() -> None:
    _, render = _projection()
    fact = render.sections[0].facts[0].model_copy(update={"value": '<img src=x onerror="alert(1)">&'})
    section = render.sections[0].model_copy(update={"facts": (fact, *render.sections[0].facts[1:])})
    changed = render.model_copy(update={"sections": (section, *render.sections[1:])})

    html = _visual_html_v2(changed)

    assert '<img src=x onerror="alert(1)">' not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;" in html


def test_v1_bundle_keeps_historical_schema_and_visual_contract() -> None:
    context, _ = _projection()
    render = build_gold_policy_report_render_v1(context)

    items = _by_name(build_gold_policy_report_bundle(context, render))

    assert _json(items["report_structured.json"])["schema_version"] == ("gold_policy_report_structured.v1")
    assert _json(items["report_manifest.json"])["schema_version"] == ("gold_policy_report_manifest.v1")
    assert "<body><pre>" in items["visual.html"].content.decode("utf-8")


def test_bundle_rejects_unknown_render_contract_without_fallback() -> None:
    context, _ = _projection()

    with pytest.raises(TypeError, match="unsupported Gold report render contract"):
        build_gold_policy_report_bundle(context, object())  # type: ignore[arg-type]
