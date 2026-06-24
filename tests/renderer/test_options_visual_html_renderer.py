from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.options.snapshot import build_options_snapshot
from apps.analysis.options.visual_report import build_options_visual_report_vm
from apps.renderer.html.options_visual import render_options_visual_html

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "options"
SAMPLE_ROWS_PATH = FIXTURES / "sample_option_rows.json"


def _load_sample_rows() -> list[dict]:
    return json.loads(SAMPLE_ROWS_PATH.read_text())


def test_render_options_visual_html_uses_vm_data_without_template_constants() -> None:
    result = build_options_snapshot(
        _load_sample_rows(),
        trade_date="2026-05-06",
        p0=4200.0,
        data_source_status="PRELIM",
    )
    vm = build_options_visual_report_vm(result)

    html = render_options_visual_html(vm)

    assert "2026-05-06" in html
    assert "Gamma Zero" in html
    assert vm.hero_title in html
    assert "WallScore" in html
    assert "const gd=" not in html
    assert "const callOI=" not in html
    assert "2026-05-19" not in html
