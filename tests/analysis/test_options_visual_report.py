from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.options.snapshot import build_options_snapshot
from apps.analysis.options.visual_report import build_options_visual_report_vm

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "options"
SAMPLE_ROWS_PATH = FIXTURES / "sample_option_rows.json"


def _load_sample_rows() -> list[dict]:
    return json.loads(SAMPLE_ROWS_PATH.read_text())


def test_build_options_visual_report_vm_maps_core_fields() -> None:
    result = build_options_snapshot(
        _load_sample_rows(),
        trade_date="2026-05-06",
        p0=4200.0,
        data_source_status="PRELIM",
    )

    vm = build_options_visual_report_vm(result)

    assert vm.trade_date == "2026-05-06"
    assert vm.product == "OG"
    assert vm.data_source_status == "PRELIM"
    assert vm.generated_at == result.generated_at
    assert vm.hero_title
    assert vm.hero_subtitle
    assert vm.core_conclusion
    assert vm.tags
    assert vm.model_parameters
    assert vm.key_metrics
    assert vm.gex_top_walls
    assert vm.wall_scores
    assert vm.support_levels
    assert vm.resistance_levels
    assert len(vm.scenarios) == 3
    assert {scenario.title for scenario in vm.scenarios} == {
        "主路径 · 修复震荡",
        "转强路径 · Proxy Gamma Flip 确认",
        "转弱路径 · 地板失守",
    }
    assert all("目标" in scenario.detail or "暂不激活" in scenario.detail for scenario in vm.scenarios)
    assert vm.source_refs

    greeks = {card.label: card for card in vm.greeks}
    expected_net_gex = sum(
        summary["net_gex"] for summary in result.gex_summary_by_expiry.values()
    )
    assert greeks["OI-Signed GEX Proxy"].value == f"{expected_net_gex:+,.2f}"
    assert "gex_summary_by_expiry" in greeks["OI-Signed GEX Proxy"].note
    expected_net_dex = sum(
        summary["net_dex"] for summary in result.exposure_summary_by_expiry.values()
    )
    assert greeks["Net DEX"].value == f"{expected_net_dex:+,.2f}"
    assert greeks["Net DEX"].value != "unavailable"
    assert greeks["Vega"].value != "unavailable"
    assert greeks["Theta"].value != "unavailable"
    assert greeks["Net DEX"].unit == "USD delta-dollar"
    assert "delta-dollar" in greeks["Net DEX"].note
    assert greeks["Vega"].unit == "USD per 1 vol-point"
    assert greeks["Theta"].unit == "USD/day"
    assert "by-strike Top 10" in greeks["Vega"].note
    assert "by-strike Top 10" in greeks["Theta"].note
    assert "full-chain total unavailable" in greeks["Vega"].note
    assert "full-chain total unavailable" in greeks["Theta"].note
    assert all(greeks[label].note for label in ("Net DEX", "Vega", "Theta"))


def test_build_options_visual_report_vm_preserves_missing_greek_reasons() -> None:
    result = build_options_snapshot(
        [],
        trade_date="2026-05-06",
        p0=4200.0,
        data_source_status="MISSING",
    )

    vm = build_options_visual_report_vm(result)
    greeks = {card.label: card for card in vm.greeks}

    assert greeks["Net DEX"].value == "unavailable"
    assert "missing:" in greeks["Net DEX"].note
    assert greeks["Net DEX"].unit == "USD delta-dollar"
    assert greeks["OI-Signed GEX Proxy"].value == "unavailable"
    assert "gex_summary_by_expiry" in greeks["OI-Signed GEX Proxy"].note
    assert greeks["Vega"].value == "unavailable"
    assert "missing:" in greeks["Vega"].note
    assert greeks["Theta"].value == "unavailable"
    assert "missing:" in greeks["Theta"].note


def test_build_options_visual_report_vm_handles_missing_calibration() -> None:
    result = build_options_snapshot(
        _load_sample_rows(),
        trade_date="2026-05-06",
        p0=4200.0,
    )

    vm = build_options_visual_report_vm(result)

    assert any("calibration" in note.lower() for note in vm.data_quality_notes)
