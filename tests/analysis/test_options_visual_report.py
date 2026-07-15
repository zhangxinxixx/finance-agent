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
        "转强路径 · Gamma 接受",
        "转弱路径 · 地板失守",
    }
    assert all("目标" in scenario.detail or "暂不激活" in scenario.detail for scenario in vm.scenarios)
    assert vm.source_refs


def test_build_options_visual_report_vm_handles_missing_calibration() -> None:
    result = build_options_snapshot(
        _load_sample_rows(),
        trade_date="2026-05-06",
        p0=4200.0,
    )

    vm = build_options_visual_report_vm(result)

    assert any("calibration" in note.lower() for note in vm.data_quality_notes)
