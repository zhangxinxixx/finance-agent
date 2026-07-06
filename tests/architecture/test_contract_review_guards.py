from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from apps.analysis.agents import source_health
from apps.analysis.agents.gold_v3_prompts import GOLD_V3_MAINLINES
from apps.analysis.agents.registry import get_agent_registry
from apps.api.services import event_flow_service, report_service
from apps.api.services import gold_mainline_service
from apps.features.news.gold_event_mainlines import MAINLINE_ORDER
from apps.gold_mainline_contract import GOLD_MAINLINE_IDS, MAINLINE_ALIAS_MAP
from apps.gold_runtime_orchestration import (
    build_gold_runtime_orchestration_contract,
    build_gold_runtime_summary_preview,
    get_gold_runtime_mode_contracts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _quoted_strings(value: str) -> list[str]:
    return re.findall(r'"([^"]+)"', value)


def _frontend_gold_mainline_type_ids() -> set[str]:
    path = PROJECT_ROOT / "apps/frontend-web/src/types/gold-mainlines.ts"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"export type GoldMainline =(?P<body>.*?);", text, re.S)
    assert match is not None
    return set(_quoted_strings(match.group("body")))


def _frontend_gold_mainline_order_ids() -> list[str]:
    path = PROJECT_ROOT / "apps/frontend-web/src/components/shared/goldMainlineFormat.ts"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"export const GOLD_MAINLINE_ORDER: GoldMainline\[] = \[(?P<body>.*?)\];", text, re.S)
    assert match is not None
    return _quoted_strings(match.group("body"))


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            strings.extend(_walk_strings(key))
            strings.extend(_walk_strings(item))
        return strings
    if isinstance(value, (list, tuple, set)):
        strings = []
        for item in value:
            strings.extend(_walk_strings(item))
        return strings
    return []


def test_gold_mainline_ids_are_canonical_across_backend_runtime_prompt_source_health_and_frontend() -> None:
    canonical = list(GOLD_MAINLINE_IDS)

    assert MAINLINE_ORDER == canonical
    assert GOLD_V3_MAINLINES == canonical
    assert list(source_health.MAINLINE_REQUIRED_SOURCES) == canonical
    assert _frontend_gold_mainline_order_ids() == canonical
    assert _frontend_gold_mainline_type_ids() == set(canonical)


def test_gold_runtime_contract_and_prompt_payloads_do_not_emit_legacy_mainline_ids() -> None:
    legacy_ids = set(MAINLINE_ALIAS_MAP)
    payloads: list[Any] = [
        build_gold_runtime_orchestration_contract(),
        *(build_gold_runtime_summary_preview(run_mode=contract.run_mode) for contract in get_gold_runtime_mode_contracts()),
        GOLD_V3_MAINLINES,
    ]

    emitted_legacy_ids = {
        value
        for payload in payloads
        for value in _walk_strings(payload)
        if value in legacy_ids
    }

    assert emitted_legacy_ids == set()
    assert set(MAINLINE_ALIAS_MAP.values()).issubset(set(GOLD_MAINLINE_IDS))


def test_runtime_preview_uses_planned_agent_fields_and_never_claims_execution() -> None:
    contract_payload = build_gold_runtime_orchestration_contract()
    for mode_payload in contract_payload["run_modes"]:
        assert "agents_executed" not in mode_payload
        assert "agents_skipped" not in mode_payload
        assert "planned_agents_executed" in mode_payload
        assert "planned_agents_skipped" in mode_payload
        assert mode_payload["runtime_contract_only"] is True

    for contract in get_gold_runtime_mode_contracts():
        summary = build_gold_runtime_summary_preview(run_mode=contract.run_mode)
        assert "agents_executed" not in summary
        assert "agents_skipped" not in summary
        assert "planned_agents_executed" in summary
        assert "planned_agents_skipped" in summary
        assert summary["runtime_contract_only"] is True
        assert summary["writes"] == []


def test_runtime_agent_ids_resolve_in_registry_and_executed_skipped_sets_do_not_overlap() -> None:
    for contract in get_gold_runtime_mode_contracts():
        executed = set(contract.agents_executed)
        skipped = set(contract.agents_skipped)

        assert executed.isdisjoint(skipped), contract.run_mode
        for agent_id in sorted(executed | skipped):
            assert get_agent_registry(agent_id) is not None, f"{contract.run_mode}: {agent_id}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "available"),
        ("status", "success"),
        ("health_state", "success"),
        ("readiness_state", "enabled"),
        ("readiness_state", "active"),
        ("readiness_state", "configured"),
        ("health_state", "connected"),
    ],
)
def test_source_health_common_available_status_values_are_ready(field: str, value: str) -> None:
    row = {
        "source_key": "xauusd_price",
        "status": "",
        "health_state": "",
        "readiness_state": "",
        "latest_health_at": "2026-07-06T09:30:00+00:00",
        "source_refs": [{"source_ref": "storage/xauusd_price.json"}],
    }
    row[field] = value

    assert source_health._source_status(row) == "ready"


def test_gold_mainline_read_time_source_health_is_overlay_and_does_not_mutate_artifact_status(monkeypatch: pytest.MonkeyPatch) -> None:
    overview = {
        "status": "partial",
        "review_status": "pass",
        "phase": "strong_uptrend",
        "one_line_conclusion": "strong bullish breakout",
        "as_of": "2026-07-06T09:30:00+00:00",
    }
    original = deepcopy(overview)

    class BlockingSnapshot:
        def to_dict(self) -> dict[str, Any]:
            return {
                "overall_status": "blocked",
                "as_of": "2026-07-06T09:30:00+00:00",
                "p0_missing": ["xauusd_price"],
                "p1_missing": [],
                "p2_missing": [],
                "stale_sources": [],
                "fresh_sources": [],
                "source_freshness": {},
                "mainline_impact": {},
                "can_build_gold_macro_overview": False,
                "can_emit_strong_conclusion": False,
                "blocked_mainlines": ["gold_technical_levels"],
                "degraded_mainlines": [],
                "blocking_reasons": ["P0 source gap conflicts with strong GoldMacroOverview conclusion"],
                "warnings": [],
            }

    monkeypatch.setattr(gold_mainline_service, "get_data_source_statuses", lambda: {"sources": []})
    monkeypatch.setattr(gold_mainline_service, "build_gold_v3_source_health", lambda *_, **__: BlockingSnapshot())

    read_time_source_health, read_time_warnings = gold_mainline_service._build_read_time_source_health(
        overview=overview
    )

    assert overview == original
    assert read_time_source_health["overall_status"] == "blocked"
    assert "read_time_source_health would block strong GoldMacroOverview conclusion" in read_time_warnings


def test_event_flow_report_input_title_inference_is_group_scoped() -> None:
    news_item = {
        "summary": "Fed repricing",
        "price": 3378.5,
        "range": "3370-3385",
    }
    technical_item = {
        "symbol": "XAUUSD",
        "level_type": "VAH",
        "price": 3378.5,
    }
    positioning_item = {
        "asset": "XAUUSD",
        "strike_or_level": "3350",
        "position_change": "increase",
    }

    assert event_flow_service._report_input_title(news_item, group_key="news_highlights") == "Fed repricing"
    assert event_flow_service._report_input_title(technical_item, group_key="technical_levels") == "XAUUSD / VAH / 3378.5"
    assert event_flow_service._report_input_title(positioning_item, group_key="positioning") == "XAUUSD / 3350 / increase"


def test_event_flow_report_input_verification_status_prefers_data_quality_contract() -> None:
    assert (
        event_flow_service._report_input_verification_status(
            {
                "verification_status": "unverified",
                "data_quality": {"verification_status": "single_source"},
            }
        )
        == "single_source"
    )
    assert event_flow_service._report_input_verification_status({"verification_status": "multi_source"}) == "multi_source"


def test_jin10_asset_audit_normalizes_equivalent_image_references() -> None:
    refs = {
        "./figures/fig_p1_001.png",
        "figures/fig_p1_001.png?raw=1",
        "/api/reports/223609/asset/fig_p1_001.png?raw=1",
        r"figures\fig_p1_001.png",
    }

    assert {report_service._normalize_jin10_image_ref(ref) for ref in refs} == {"figures/fig_p1_001.png"}


def test_jin10_chart_text_audit_does_not_flag_dense_chart_text_by_length_only() -> None:
    dense_chart_text = "A" * 121
    article_like_text = "黄金价格继续震荡。" * 24

    assert report_service._jin10_chart_text_issues([{"figure_id": "dense", "recognized_text": dense_chart_text}]) == []
    issues = report_service._jin10_chart_text_issues(
        [{"figure_id": "article", "recognized_text": article_like_text}]
    )
    assert issues[0]["figure_id"] == "article"
