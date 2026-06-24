"""CME options analysis renderer — JSON snapshot + Chinese Markdown report."""

from apps.analysis.options.report import render_options_report_markdown
from apps.analysis.options.snapshot import OptionsAnalysisResult, build_options_snapshot
from apps.analysis.options.visual_report import (
    OptionsVisualReportVM,
    build_options_visual_report_vm,
)

__all__ = [
    "OptionsAnalysisResult",
    "OptionsVisualReportVM",
    "build_options_snapshot",
    "build_options_visual_report_vm",
    "render_options_report_markdown",
]
