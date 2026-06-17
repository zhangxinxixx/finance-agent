from __future__ import annotations

from apps.features.macro.snapshot import MACRO_INDICATOR_SPECS, MacroIndicator, MacroSnapshot


def render_macro_snapshot_markdown(snapshot: MacroSnapshot) -> str:
    lines = [
        f"# Macro Snapshot {snapshot.as_of}",
        "",
        "指标 | 最新日期 | 最新值 | 1周变化 | 1月变化 | 方向解读",
        "--- | --- | --- | --- | --- | ---",
    ]
    for spec in MACRO_INDICATOR_SPECS:
        indicator = snapshot.indicators.get(spec.symbol)
        if indicator is None:
            lines.append(f"{spec.label} | 明确缺失 | 明确缺失 | 明确缺失 | 明确缺失 | 明确缺失")
            continue
        lines.append(
            f"{indicator.label or spec.label} | {indicator.date} | {_format_value(indicator)} | "
            f"{_format_change(indicator, indicator.weekly_change)} | "
            f"{_format_change(indicator, indicator.monthly_change)} | {indicator.direction_note or '暂无可用方向解读'}"
        )

    lines.extend(["", "## Unavailable Symbols"])
    if snapshot.unavailable_symbols:
        lines.extend(f"- {symbol}" for symbol in snapshot.unavailable_symbols)
    else:
        lines.append("- None")

    lines.extend(["", "## Source Refs"])
    if snapshot.source_refs:
        for symbol, ref in snapshot.source_refs.items():
            lines.append(f"- {symbol}: {ref.get('source_url', '')} ({ref.get('raw_path', '')})")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _format_value(indicator: MacroIndicator) -> str:
    if indicator.unit == "%":
        return f"{indicator.value:.2f}%"
    if indicator.unit == "B":
        return _format_balance_value(indicator.value)
    if indicator.unit:
        return f"{indicator.value:.2f} {indicator.unit}"
    return f"{indicator.value:.2f}"


def _format_change(indicator: MacroIndicator, value: float | None) -> str:
    if value is None:
        return "明确缺失"
    if indicator.unit == "%":
        return f"{round(value * 100):+d}bp"
    if indicator.unit == "B":
        return _format_balance_value(value)
    return f"{value:+.2f}"


def _format_balance_value(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value / 1000:.2f}T"
    return f"{value:.1f}B"
