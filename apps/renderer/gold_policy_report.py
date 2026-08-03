"""Deterministic report rendering from ``GoldReportContext`` only."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from apps.analysis.gold_policy.report_context import GoldReportContext
from apps.analysis.gold_policy.schemas import SourceReference


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldReportSection(_FrozenContract):
    section_id: Literal["macro", "attribution", "state", "strategy", "key_levels", "data_quality"]
    title: str
    lines: tuple[str, ...]
    source_refs: tuple[SourceReference, ...]


class GoldReportRender(_FrozenContract):
    schema_version: Literal["gold_policy_report_render.v1"] = "gold_policy_report_render.v1"
    context_id: str
    authority_result_id: str
    report_status: Literal["accepted", "observe", "degraded"]
    sections: tuple[GoldReportSection, ...]
    markdown: str
    language_generation: Literal["not_invoked"] = "not_invoked"
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_id: str = Field(pattern=r"^gold_policy_report_render\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "GoldReportRender":
        expected_markdown = render_gold_policy_report_markdown(
            self.authority_result_id, self.report_status, self.sections
        )
        if self.markdown != expected_markdown:
            raise ValueError("report markdown does not match the deterministic sections")
        digest = _digest(self)
        if self.payload_hash != digest or self.render_id != f"gold_policy_report_render.v1:{digest}":
            raise ValueError("report render identity does not match canonical payload")
        return self


def build_gold_policy_report_render(context: GoldReportContext) -> GoldReportRender:
    """Render a report without Agent prose, Jin10 context, LLMs, or clocks."""

    state = context.selected_state
    strategy = context.selected_strategy
    analysis = context.analysis_decision
    attribution = context.price_attribution
    state_lines = ("状态：unavailable",) if state is None else _state_lines(state)
    strategy_lines = (
        ("策略：NO_TRADE", "原因：no canonical strategy")
        if strategy is None
        else _strategy_lines(strategy)
    )
    sections = (
        GoldReportSection(
            section_id="macro",
            title="宏观背景",
            lines=(
                f"方向：{analysis.direction}",
                f"方向倾向：{analysis.direction_tilt}",
                f"置信度：{analysis.confidence}",
                f"质量：{analysis.quality_status}",
            ),
            source_refs=context.source_refs,
        ),
        GoldReportSection(
            section_id="attribution",
            title="今日涨跌归因",
            lines=(
                f"价格变动：{attribution.price_move}",
                f"归因状态：{attribution.attribution_status}",
                f"收益率：{attribution.return_pct}",
            ),
            source_refs=attribution.source_refs,
        ),
        GoldReportSection(
            section_id="state",
            title="状态变化",
            lines=state_lines,
            source_refs=context.source_refs,
        ),
        GoldReportSection(
            section_id="strategy",
            title="当前策略",
            lines=strategy_lines,
            source_refs=context.source_refs,
        ),
        GoldReportSection(
            section_id="key_levels",
            title="关键位",
            lines=(
                f"正式关键位：{len(context.key_levels)}",
                f"生命周期决策：{len(context.key_level_decisions)}",
            ),
            source_refs=context.source_refs,
        ),
        GoldReportSection(
            section_id="data_quality",
            title="数据与证据溯源",
            lines=(
                f"分析就绪度：{context.analysis_readiness}",
                f"证据引用：{len(context.source_refs)}",
            ),
            source_refs=context.source_refs,
        ),
    )
    status: Literal["accepted", "observe", "degraded"] = (
        "degraded"
        if context.analysis_readiness == "blocked"
        else "observe"
        if context.analysis_readiness == "observe"
        else "degraded"
        if context.selected_state is None
        else "accepted"
    )
    markdown = render_gold_policy_report_markdown(
        context.authority_result_id, status, sections
    )
    payload = {
        "schema_version": "gold_policy_report_render.v1",
        "context_id": context.context_id,
        "authority_result_id": context.authority_result_id,
        "report_status": status,
        "sections": sections,
        "markdown": markdown,
        "language_generation": "not_invoked",
    }
    digest = _digest_payload(payload)
    return GoldReportRender(
        **payload,
        payload_hash=digest,
        render_id=f"gold_policy_report_render.v1:{digest}",
    )


def render_gold_policy_report_markdown(
    authority_result_id: str,
    report_status: str,
    sections: tuple[GoldReportSection, ...],
) -> str:
    lines = ["# XAUUSD Gold Policy Daily Report", "", f"- Authority Result: {authority_result_id}", f"- Report Status: {report_status}"]
    for section in sections:
        lines.extend(("", f"## {section.title}", *[f"- {line}" for line in section.lines]))
    return "\n".join(lines) + "\n"


def _state_lines(state: object) -> tuple[str, ...]:
    if getattr(state, "schema_version", "") == "analysis_state.v2":
        return (
            f"方向：{state.direction}",
            f"方向倾向：{state.direction_tilt}",
            f"Regime：{state.market_regime}",
            f"趋势成熟度：{state.trend_maturity}",
        )
    return (f"方向：{state.directional_bias}", f"阶段：{state.stage}")


def _strategy_lines(strategy: object) -> tuple[str, ...]:
    lines = [f"策略：{strategy.status}", f"方向：{strategy.direction}"]
    no_trade = getattr(strategy, "no_trade_reason_code", None)
    if no_trade is not None:
        lines.append(f"NO_TRADE 原因：{no_trade}")
    return tuple(lines)


def _digest(render: GoldReportRender) -> str:
    return _digest_payload(render.model_dump(mode="json", exclude={"payload_hash", "render_id"}))


def _digest_payload(payload: object) -> str:
    canonical = json.dumps(
        to_jsonable_python(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
