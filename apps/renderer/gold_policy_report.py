"""Deterministic report rendering from ``GoldReportContext`` only."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from apps.analysis.gold_policy.report_context import GoldReportContextContract
from apps.analysis.gold_policy.schemas import SourceReference


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldReportSection(_FrozenContract):
    section_id: Literal[
        "macro",
        "attribution",
        "state",
        "strategy",
        "options",
        "key_levels",
        "data_quality",
    ]
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


GoldReportSectionIdV2 = Literal[
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
]

_V2_SECTION_ORDER: tuple[str, ...] = (
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


class GoldReportFactV2(_FrozenContract):
    """One renderer-owned presentation fact projected from typed context only."""

    fact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)
    fact_kind: Literal[
        "status",
        "metric",
        "reason",
        "condition",
        "risk",
        "lineage",
        "limitation",
    ]
    source_refs: tuple[SourceReference, ...] = ()


class GoldReportSectionV2(_FrozenContract):
    section_id: GoldReportSectionIdV2
    title: str = Field(min_length=1)
    facts: tuple[GoldReportFactV2, ...] = Field(min_length=1)
    source_refs: tuple[SourceReference, ...] = ()

    @model_validator(mode="after")
    def _validate_unique_facts(self) -> "GoldReportSectionV2":
        fact_ids = tuple(fact.fact_id for fact in self.facts)
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("report section fact ids must be unique")
        return self


class GoldReportDomainStatusV2(_FrozenContract):
    domain: Literal["analysis", "strategy", "options", "events", "key_levels"]
    readiness: Literal["ready", "observe", "blocked", "unavailable"]
    missing_inputs: tuple[str, ...] = ()
    prohibited_outputs: tuple[str, ...] = ()


class GoldReportRenderV2(_FrozenContract):
    schema_version: Literal["gold_policy_report_render.v2"] = "gold_policy_report_render.v2"
    context_id: str
    authority_result_id: str
    report_status: Literal["accepted", "observe", "degraded"]
    domain_statuses: tuple[GoldReportDomainStatusV2, ...]
    sections: tuple[GoldReportSectionV2, ...]
    markdown: str
    language_generation: Literal["not_invoked"] = "not_invoked"
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_id: str = Field(pattern=r"^gold_policy_report_render\.v2:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "GoldReportRenderV2":
        if tuple(section.section_id for section in self.sections) != _V2_SECTION_ORDER:
            raise ValueError("v2 report sections must use the canonical eleven-section order")
        if tuple(item.domain for item in self.domain_statuses) != (
            "analysis",
            "strategy",
            "options",
            "events",
            "key_levels",
        ):
            raise ValueError("v2 report domain statuses must use canonical order")
        expected_markdown = render_gold_policy_report_markdown_v2(
            self.authority_result_id,
            self.report_status,
            self.domain_statuses,
            self.sections,
        )
        if self.markdown != expected_markdown:
            raise ValueError("v2 report markdown does not match typed sections")
        digest = _digest_v2(self)
        if self.payload_hash != digest or self.render_id != f"gold_policy_report_render.v2:{digest}":
            raise ValueError("v2 report render identity does not match canonical payload")
        return self


GoldReportRenderContract = GoldReportRender | GoldReportRenderV2


def build_gold_policy_report_render_v1(context: GoldReportContextContract) -> GoldReportRender:
    """Render a report without Agent prose, Jin10 context, LLMs, or clocks."""

    state = context.selected_state
    strategy = context.selected_strategy
    analysis = context.analysis_decision
    attribution = context.price_attribution
    state_lines = ("状态：unavailable",) if state is None else _state_lines(state)
    strategy_lines = (
        ("策略：NO_TRADE", "原因：no canonical strategy") if strategy is None else _strategy_lines(strategy)
    )
    formal_options = getattr(context, "cme_options_snapshot", None)
    options_sections = (
        (
            GoldReportSection(
                section_id="options",
                title="CME 期权结构",
                lines=_options_lines(formal_options),
                source_refs=formal_options.source_refs or context.source_refs,
            ),
        )
        if formal_options is not None
        else ()
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
        *options_sections,
        GoldReportSection(
            section_id="key_levels",
            title="关键位",
            lines=(
                _key_level_lines(context)
                if formal_options is not None
                else (
                    f"正式关键位：{len(context.key_levels)}",
                    f"生命周期决策：{len(context.key_level_decisions)}",
                )
            ),
            source_refs=context.source_refs,
        ),
        GoldReportSection(
            section_id="data_quality",
            title="数据与证据溯源",
            lines=(
                _quality_lines(context)
                if formal_options is not None
                else (
                    f"分析就绪度：{context.analysis_readiness}",
                    f"证据引用：{len(context.source_refs)}",
                )
            ),
            source_refs=context.source_refs,
        ),
    )
    status: Literal["accepted", "observe", "degraded"]
    if context.analysis_readiness == "blocked":
        status = "degraded"
    elif context.analysis_readiness == "observe":
        status = "observe"
    elif context.selected_state is None:
        status = "degraded"
    elif formal_options is not None and any(
        getattr(context, field) != "ready"
        for field in (
            "analysis_readiness",
            "strategy_readiness",
            "options_readiness",
            "event_attribution_readiness",
        )
    ):
        status = "observe"
    else:
        status = "accepted"
    markdown = render_gold_policy_report_markdown(context.authority_result_id, status, sections)
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


def build_gold_policy_report_render_v2(context: GoldReportContextContract) -> GoldReportRenderV2:
    """Build the fixed eleven-section report exclusively from typed context facts."""

    status = _report_status(context)
    domains = _domain_statuses_v2(context)
    sections = _sections_v2(context, status)
    markdown = render_gold_policy_report_markdown_v2(
        context.authority_result_id,
        status,
        domains,
        sections,
    )
    payload = {
        "schema_version": "gold_policy_report_render.v2",
        "context_id": context.context_id,
        "authority_result_id": context.authority_result_id,
        "report_status": status,
        "domain_statuses": domains,
        "sections": sections,
        "markdown": markdown,
        "language_generation": "not_invoked",
    }
    digest = _digest_payload(payload)
    return GoldReportRenderV2(
        **payload,
        payload_hash=digest,
        render_id=f"gold_policy_report_render.v2:{digest}",
    )


def rebuild_gold_policy_report_render(
    context: GoldReportContextContract,
    schema_version: Literal["gold_policy_report_render.v1", "gold_policy_report_render.v2"],
) -> GoldReportRenderContract:
    """Deterministically rebuild a render according to its persisted schema."""

    if schema_version == "gold_policy_report_render.v1":
        return build_gold_policy_report_render_v1(context)
    if schema_version == "gold_policy_report_render.v2":
        return build_gold_policy_report_render_v2(context)
    raise ValueError("unsupported gold report render schema")


def build_gold_policy_report_render(context: GoldReportContextContract) -> GoldReportRenderContract:
    """Build v2 for the current context while preserving legacy context compatibility."""

    if context.schema_version == "gold_report_context.v1":
        return build_gold_policy_report_render_v1(context)
    return build_gold_policy_report_render_v2(context)


def render_gold_policy_report_markdown(
    authority_result_id: str,
    report_status: str,
    sections: tuple[GoldReportSection, ...],
) -> str:
    lines = [
        "# XAUUSD Gold Policy Daily Report",
        "",
        f"- Authority Result: {authority_result_id}",
        f"- Report Status: {report_status}",
    ]
    for section in sections:
        lines.extend(("", f"## {section.title}", *[f"- {line}" for line in section.lines]))
    return "\n".join(lines) + "\n"


def render_gold_policy_report_markdown_v2(
    authority_result_id: str,
    report_status: str,
    domain_statuses: tuple[GoldReportDomainStatusV2, ...],
    sections: tuple[GoldReportSectionV2, ...],
) -> str:
    """Render markdown solely from the typed V2 section tree."""

    lines = [
        "# XAUUSD Gold Policy Daily Report",
        "",
        f"- Authority Result: {authority_result_id}",
        f"- Report Status: {report_status}",
        "- Domain Status: " + ", ".join(f"{item.domain}={item.readiness}" for item in domain_statuses),
    ]
    for section in sections:
        lines.extend(
            (
                "",
                f"## {section.title}",
                *(f"- {fact.label}：{fact.value}" for fact in section.facts),
            )
        )
    return "\n".join(lines) + "\n"


def _sections_v2(
    context: GoldReportContextContract,
    status: Literal["accepted", "observe", "degraded"],
) -> tuple[GoldReportSectionV2, ...]:
    refs = context.source_refs
    analysis = context.analysis_decision
    attribution = context.price_attribution
    transition = context.transition_decision
    state = context.selected_state or context.candidate_state
    strategy = context.selected_strategy or context.candidate_strategy
    formal_options = getattr(context, "cme_options_snapshot", None)
    analysis_refs = (
        _merge_source_refs(
            *(item.source_refs for item in getattr(analysis, "factor_contributions", ())),
            *(item.source_refs for item in analysis.dominant_drivers),
            *(item.source_refs for item in analysis.counter_drivers),
        )
        or refs
    )
    transition_refs = _merge_source_refs(getattr(transition.evidence, "source_refs", ())) or refs
    strategy_refs = _merge_source_refs(getattr(strategy, "source_refs", ())) or refs
    key_level_refs = _merge_source_refs(
        *(level.source_refs for level in context.key_levels),
        formal_options.source_refs if formal_options is not None else (),
    )
    event_refs = _merge_source_refs(
        *(event.source_refs for event in getattr(context, "major_events", ())),
        *(event.reaction_source_refs for event in getattr(context, "major_events", ())),
    )
    executive_refs = _merge_source_refs(analysis_refs, attribution.source_refs, strategy_refs)

    conclusion = (
        f"XAUUSD {attribution.price_move}（{attribution.return_pct}%），宏观方向为 "
        f"{analysis.direction}/{analysis.direction_tilt}，状态动作为 {transition.action}，"
        f"当前策略为 {_text(getattr(strategy, 'status', 'unavailable'))}，报告状态为 {status}。"
    )

    executive = (
        _fact("executive.conclusion", "结论", conclusion, "status", executive_refs),
        _fact("executive.report_status", "发布状态", status, "status"),
        _fact("executive.direction", "宏观方向", analysis.direction, "status", analysis_refs),
        _fact("executive.direction_tilt", "方向倾向", analysis.direction_tilt, "status", analysis_refs),
        _fact("executive.confidence", "置信度", analysis.confidence, "metric", analysis_refs),
        _fact(
            "executive.strategy",
            "策略状态",
            getattr(strategy, "status", "unavailable"),
            "status",
            strategy_refs,
        ),
    )

    macro_facts = [
        _fact(
            "macro.comparison_scope",
            "背景比较口径",
            "previous_to_current_snapshot",
            "lineage",
            refs,
        ),
        _fact("macro.previous_snapshot", "前序快照", context.previous_feature_id or "missing", "lineage"),
        _fact("macro.current_snapshot", "当前快照", context.current_feature_id, "lineage"),
        _fact("macro.regime", "宏观状态", analysis.macro_regime, "status", analysis_refs),
    ]
    contributions = getattr(analysis, "factor_contributions", ())
    if contributions:
        for index, contribution in enumerate(contributions):
            macro_facts.append(
                _fact(
                    f"macro.contribution.{index}",
                    f"因子贡献 {contribution.factor}",
                    (
                        f"previous={contribution.previous_value}; current={contribution.current_value}; "
                        f"delta={contribution.delta}; contribution={contribution.contribution}; "
                        f"materiality={contribution.materiality_bucket}"
                    ),
                    "metric",
                    contribution.source_refs,
                )
            )
    else:
        for role, drivers in (
            ("dominant", analysis.dominant_drivers),
            ("counter", analysis.counter_drivers),
        ):
            macro_facts.append(
                _fact(
                    f"macro.{role}",
                    f"{role} drivers",
                    _driver_names(drivers),
                    "reason",
                    analysis_refs,
                )
            )

    attribution_facts = [
        _fact("attribution.price_move", "价格变动", attribution.price_move, "metric", attribution.source_refs),
        _fact("attribution.return_pct", "收益率", attribution.return_pct, "metric", attribution.source_refs),
        _fact(
            "attribution.status",
            "归因状态",
            attribution.attribution_status,
            "status",
            attribution.source_refs,
        ),
    ]
    for fact_id, label, value in (
        ("attribution.support_contribution", "支持贡献", getattr(attribution, "support_contribution", None)),
        ("attribution.counter_contribution", "反向贡献", getattr(attribution, "counter_contribution", None)),
        ("attribution.explained_ratio", "已解释占比", getattr(attribution, "explained_ratio", None)),
        ("attribution.unexplained_component", "未解释占比", getattr(attribution, "unexplained_component", None)),
        ("attribution.evidence_coverage", "证据覆盖率", getattr(attribution, "evidence_coverage_ratio", None)),
    ):
        if value is not None:
            attribution_facts.append(_fact(fact_id, label, value, "metric", attribution.source_refs))
    for role in ("primary", "secondary", "counter", "filtered"):
        for index, driver in enumerate(getattr(attribution, f"{role}_drivers", ())):
            attribution_facts.append(
                _fact(
                    f"attribution.{role}.{index}",
                    f"{role} driver",
                    _attribution_driver_value(driver),
                    "reason",
                    driver.source_refs,
                )
            )
        if not getattr(attribution, f"{role}_drivers", ()):
            attribution_facts.append(_fact(f"attribution.{role}.none", f"{role} drivers", "none", "status"))

    changed_dimensions = tuple(getattr(transition, "changed_dimensions", ()))
    if not changed_dimensions and getattr(transition, "advance", False):
        changed_dimensions = ("stage",)
    state_facts = (
        _fact("transition.from", "From State", transition.from_state_id or "none", "lineage", transition_refs),
        _fact(
            "transition.from_projection",
            "变化前状态",
            _transition_projection(transition, "from"),
            "status",
            transition_refs,
        ),
        _fact("transition.to", "To State", transition.to_state_id or "none", "lineage", transition_refs),
        _fact(
            "transition.to_projection",
            "候选变化后状态",
            _transition_projection(transition, "to"),
            "status",
            transition_refs,
        ),
        _fact("transition.action", "Action", transition.action, "status", transition_refs),
        _fact(
            "transition.changed_dimensions",
            "Changed Dimensions",
            _join(changed_dimensions),
            "status",
            transition_refs,
        ),
        _fact(
            "transition.selected_state",
            "正式选中状态",
            _state_projection(state),
            "status",
            transition_refs,
        ),
        _fact(
            "transition.reasons",
            "状态变化原因",
            _join(transition.reasons),
            "reason",
            transition_refs,
        ),
        _fact(
            "transition.canonical_selection",
            "Canonical 选择",
            (
                "candidate_selected"
                if context.selected_state is not None
                and context.candidate_state is not None
                and context.selected_state.state_id == context.candidate_state.state_id
                else "previous_or_unavailable"
            ),
            "status",
            transition_refs,
        ),
    )

    strategy_reasons = tuple(getattr(context, "strategy_reason_codes", ())) or tuple(
        getattr(strategy, "reason_codes", ())
    )
    release_conditions = tuple(getattr(context, "strategy_release_conditions", ())) or tuple(
        getattr(strategy, "release_conditions", ())
    )
    review_triggers = tuple(getattr(context, "strategy_review_triggers", ())) or tuple(
        getattr(strategy, "review_triggers", ())
    )
    invalidation_ids = tuple(getattr(context, "strategy_invalidation_level_ids", ())) or tuple(
        getattr(strategy, "invalidation_level_ids", ())
    )
    strategy_facts = [
        _fact("strategy.status", "策略状态", getattr(strategy, "status", "unavailable"), "status", strategy_refs),
        _fact("strategy.direction", "策略方向", getattr(strategy, "direction", "none"), "status", strategy_refs),
        _fact("strategy.reasons", "策略原因", _join(strategy_reasons), "reason", strategy_refs),
        _fact("strategy.release", "释放条件", _join(release_conditions), "condition", strategy_refs),
        _fact("strategy.review", "复核触发", _join(review_triggers), "condition", strategy_refs),
        _fact("strategy.invalidation", "失效条件", _join(invalidation_ids), "condition", strategy_refs),
    ]
    if formal_options is None:
        strategy_facts.append(_fact("options.status", "CME 期权结构", "unavailable", "limitation"))
    else:
        options_refs = formal_options.source_refs
        expiry_scope = tuple(f"{item.expiry}(DTE {item.dte})" for item in formal_options.expiry_scope)
        skew = tuple(f"{item.expiry}:{_display(item.skew_25d)}" for item in formal_options.skew)
        disclosure = formal_options.model_disclosure
        strategy_facts.extend(
            (
                _fact("options.settlement", "期权结算状态", formal_options.settlement_status, "status", options_refs),
                _fact("options.regime", "期权结构状态", formal_options.regime, "status", options_refs),
                _fact(
                    "options.directional_bias", "期权方向确认", formal_options.directional_bias, "status", options_refs
                ),
                _fact("options.expiry_scope", "到期范围", _join(expiry_scope), "lineage", options_refs),
                _fact("options.net_gex", "Net GEX", formal_options.net_gex, "metric", options_refs),
                _fact("options.skew", "25D Skew", _join(skew), "metric", options_refs),
                _fact(
                    "options.quality",
                    "期权质量",
                    (
                        f"{formal_options.quality_status}/{formal_options.freshness_status}/"
                        f"{formal_options.alignment_status}"
                    ),
                    "status",
                    options_refs,
                ),
                _fact(
                    "options.model_disclosure",
                    "模型与代理口径",
                    (
                        f"model={disclosure.model or 'unavailable'}; real_gex={disclosure.used_real_gex}; "
                        f"proxy_share={_display(disclosure.proxy_gex_share)}; not_real_dealer_inventory"
                    ),
                    "limitation",
                    options_refs,
                ),
                _fact("options.reasons", "期权限制原因", _join(formal_options.reason_codes), "reason", options_refs),
            )
        )

    key_level_facts = [
        _fact("key_levels.count", "正式关键位数量", len(context.key_levels), "metric", key_level_refs),
        _fact(
            "key_levels.lifecycle_decisions",
            "生命周期决策数量",
            len(context.key_level_decisions),
            "metric",
            key_level_refs,
        ),
    ]
    for index, level in enumerate(context.key_levels):
        key_level_facts.append(
            _fact(
                f"key_levels.level.{index}",
                f"{level.spec.role.value} level",
                (
                    f"price={_spec_price(level.spec)}; comparator={level.spec.comparator.value}; "
                    f"lifecycle={level.lifecycle.value}; authority={level.authority_status.value}"
                ),
                "condition",
                level.source_refs,
            )
        )
    if not context.key_levels:
        key_level_facts.append(_fact("key_levels.unavailable", "关键位状态", "unavailable", "limitation"))
    trigger_values = tuple(
        _spec_price(level.spec) for level in context.key_levels if level.spec.role.value == "trigger"
    )
    confirmed_values = tuple(
        _spec_price(level.spec) for level in context.key_levels if level.lifecycle.value in {"confirmed", "holding"}
    )
    invalidation_values = tuple(
        _spec_price(level.spec) for level in context.key_levels if level.spec.role.value == "invalidation"
    )
    key_level_facts.extend(
        (
            _fact(
                "key_levels.trigger_values",
                "触发位",
                _join(trigger_values) if context.key_levels else "unavailable",
                "condition",
                key_level_refs,
            ),
            _fact(
                "key_levels.confirmed_values",
                "生命周期确认位",
                _join(confirmed_values) if context.key_levels else "unavailable",
                "condition",
                key_level_refs,
            ),
            _fact(
                "key_levels.invalidation_values",
                "失效位",
                _join(invalidation_values) if context.key_levels else "unavailable",
                "condition",
                key_level_refs,
            ),
        )
    )
    if formal_options is not None:
        options_refs = formal_options.source_refs
        key_level_facts.extend(
            (
                _fact(
                    "cme_reference.gamma_flip",
                    "CME GC Gamma Flip 参考",
                    _display(formal_options.gamma_flip),
                    "metric",
                    options_refs,
                ),
                _fact(
                    "cme_reference.pin",
                    "CME GC Pin 参考",
                    _level_price(formal_options.pin),
                    "metric",
                    options_refs,
                ),
                _fact(
                    "cme_reference.call_wall",
                    "CME GC Call Wall 参考",
                    _level_price(formal_options.call_wall),
                    "metric",
                    options_refs,
                ),
                _fact(
                    "cme_reference.put_wall",
                    "CME GC Put Wall 参考",
                    _level_price(formal_options.put_wall),
                    "metric",
                    options_refs,
                ),
                _fact(
                    "cme_reference.authority_limit",
                    "CME 参考位权限",
                    "reference_only_not_xauusd_canonical_level",
                    "limitation",
                    options_refs,
                ),
            )
        )

    scenario_facts = (
        _fact(
            "scenario.canonical",
            "Canonical Path",
            (f"state={_state_projection(state)}; strategy={_text(getattr(strategy, 'status', 'unavailable'))}"),
            "status",
            _merge_source_refs(transition_refs, strategy_refs),
        ),
        _fact(
            "scenario.release",
            "Release Path",
            _join(release_conditions) if release_conditions else "unavailable",
            "condition",
            strategy_refs,
        ),
        _fact(
            "scenario.invalidation_review",
            "Invalidation / Review Path",
            (
                f"invalidation={_join(invalidation_ids) if invalidation_ids else 'unavailable'}; "
                f"review={_join(review_triggers) if review_triggers else 'unavailable'}"
            ),
            "condition",
            strategy_refs,
        ),
    )

    event_facts = [
        _fact(
            "events.classification_limit",
            "事件等级限制",
            "major_classification_not_performed",
            "limitation",
        )
    ]
    for index, event in enumerate(getattr(context, "major_events", ())):
        event_facts.append(
            _fact(
                f"events.event.{index}",
                event.title,
                (
                    f"event_id={event.event_id}; occurred_at={event.occurred_at.isoformat()}; "
                    f"reaction_status={event.reaction_status}; "
                    f"reaction_return_pct={_display(event.reaction_return_pct)}; "
                    f"reaction_summary={event.reaction_summary or 'unavailable'}"
                ),
                "status",
                event.source_refs,
            )
        )
    if len(event_facts) == 1:
        event_facts.append(_fact("events.none", "正式事件", "none", "status"))

    fundamental_facts = (
        _fact("fundamental.status", "中长期基本面变化", "unavailable", "status"),
        _fact(
            "fundamental.reason",
            "原因",
            "NO_TYPED_FUNDAMENTAL_CHANGE_INPUT",
            "limitation",
        ),
    )

    risks = [
        *(
            _fact(
                f"risks.readiness.{item.domain}",
                f"{item.domain} readiness",
                item.readiness,
                "risk" if item.readiness != "ready" else "status",
            )
            for item in _domain_statuses_v2(context)
        ),
        _fact(
            "risks.missing_required",
            "缺失必需输入",
            _join(getattr(context, "missing_required_inputs", ())),
            "risk",
        ),
        _fact(
            "risks.missing_confirmatory",
            "缺失确认型输入",
            _join(getattr(context, "missing_confirmatory_inputs", ())),
            "risk",
        ),
        _fact(
            "risks.prohibited",
            "禁止输出",
            _join(getattr(context, "prohibited_outputs", ())),
            "risk",
        ),
        _fact(
            "risks.unresolved",
            "未解决项",
            _join(tuple(f"{item.kind}:{item.code}" for item in getattr(context, "unresolved_items", ()))),
            "risk",
        ),
        _fact("risks.conflicts", "冲突证据", _join(analysis.conflicts), "risk", refs),
        _fact(
            "risks.unexplained",
            "未解释占比",
            attribution.unexplained_component,
            "risk",
            attribution.source_refs,
        ),
    ]
    if formal_options is not None:
        risks.append(
            _fact(
                "risks.options",
                "期权未确认项",
                _join(formal_options.reason_codes),
                "risk",
                formal_options.source_refs,
            )
        )
    consistency = getattr(context, "consistency_decision", None)
    if consistency is not None:
        risks.extend(
            (
                _fact("risks.consistency_status", "一致性状态", consistency.status, "status", consistency.source_refs),
                _fact(
                    "risks.consistency_reasons",
                    "一致性原因",
                    _join(consistency.reason_codes),
                    "risk",
                    consistency.source_refs,
                ),
            )
        )

    trace_facts = [
        _fact("trace.run", "Run ID", getattr(context, "run_id", "legacy"), "lineage"),
        _fact("trace.snapshot", "Snapshot ID", context.current_feature_id, "lineage"),
        _fact("trace.authority", "Authority Result", context.authority_result_id, "lineage"),
    ]
    input_ids = getattr(context, "input_snapshot_ids", None)
    if input_ids is not None:
        for name, value in sorted(input_ids.model_dump(mode="json").items()):
            trace_facts.append(_fact(f"trace.input.{name}", f"Input Snapshot {name}", value, "lineage"))
    for index, artifact in enumerate(getattr(context, "artifact_refs", ())):
        trace_facts.append(
            _fact(
                f"trace.artifact.{index}",
                f"Artifact {artifact.artifact_type}",
                f"{artifact.identity_kind}:{artifact.identity}",
                "lineage",
            )
        )
    policies = tuple(
        dict.fromkeys(
            _text(value)
            for value in (
                getattr(analysis, "policy_version", None),
                getattr(attribution, "policy_version", None),
                getattr(strategy, "policy_version", None),
                getattr(context, "readiness_policy_version", None),
            )
            if value is not None
        )
    )
    trace_facts.append(_fact("trace.policies", "Policy Versions", _join(policies), "lineage"))
    for index, ref in enumerate(refs):
        trace_facts.append(
            _fact(
                f"trace.source.{index}",
                f"Source {index + 1}",
                f"{ref.source}:{ref.reference}@{ref.retrieved_at.isoformat()}",
                "lineage",
                (ref,),
            )
        )

    return (
        GoldReportSectionV2(
            section_id="executive_summary",
            title="一句话结论",
            facts=executive,
            source_refs=executive_refs,
        ),
        GoldReportSectionV2(
            section_id="macro_background",
            title="近几日宏观背景",
            facts=tuple(macro_facts),
            source_refs=analysis_refs,
        ),
        GoldReportSectionV2(
            section_id="price_attribution",
            title="今日涨跌归因",
            facts=tuple(attribution_facts),
            source_refs=attribution.source_refs,
        ),
        GoldReportSectionV2(
            section_id="state_transition",
            title="状态变化",
            facts=state_facts,
            source_refs=transition_refs,
        ),
        GoldReportSectionV2(
            section_id="strategy",
            title="策略与原因",
            facts=tuple(strategy_facts),
            source_refs=strategy_refs,
        ),
        GoldReportSectionV2(
            section_id="key_level_map",
            title="关键位地图",
            facts=tuple(key_level_facts),
            source_refs=key_level_refs,
        ),
        GoldReportSectionV2(
            section_id="scenarios",
            title="三路径",
            facts=scenario_facts,
            source_refs=_merge_source_refs(transition_refs, strategy_refs),
        ),
        GoldReportSectionV2(
            section_id="major_events",
            title="重大事件",
            facts=tuple(event_facts),
            source_refs=event_refs,
        ),
        GoldReportSectionV2(section_id="fundamental_change", title="中长期基本面变化", facts=fundamental_facts),
        GoldReportSectionV2(section_id="risks", title="风险与未确认项", facts=tuple(risks), source_refs=refs),
        GoldReportSectionV2(section_id="traceability", title="分析溯源", facts=tuple(trace_facts), source_refs=refs),
    )


def _domain_statuses_v2(
    context: GoldReportContextContract,
) -> tuple[GoldReportDomainStatusV2, ...]:
    missing_required = tuple(getattr(context, "missing_required_inputs", ()))
    missing_confirmatory = tuple(getattr(context, "missing_confirmatory_inputs", ()))
    prohibited = tuple(_text(item) for item in getattr(context, "prohibited_outputs", ()))

    def outputs(*tokens: str) -> tuple[str, ...]:
        return tuple(item for item in prohibited if any(token in item for token in tokens))

    key_readiness: Literal["ready", "unavailable"] = "ready" if context.key_levels else "unavailable"
    return (
        GoldReportDomainStatusV2(
            domain="analysis",
            readiness=context.analysis_readiness,
            missing_inputs=missing_required,
            prohibited_outputs=outputs("ANALYSIS"),
        ),
        GoldReportDomainStatusV2(
            domain="strategy",
            readiness=getattr(context, "strategy_readiness", context.analysis_readiness),
            missing_inputs=missing_confirmatory,
            prohibited_outputs=outputs("STRATEGY"),
        ),
        GoldReportDomainStatusV2(
            domain="options",
            readiness=getattr(context, "options_readiness", "unavailable"),
            prohibited_outputs=outputs("OPTIONS"),
        ),
        GoldReportDomainStatusV2(
            domain="events",
            readiness=getattr(context, "event_attribution_readiness", "unavailable"),
            prohibited_outputs=outputs("EVENT"),
        ),
        GoldReportDomainStatusV2(domain="key_levels", readiness=key_readiness),
    )


def _report_status(
    context: GoldReportContextContract,
) -> Literal["accepted", "observe", "degraded"]:
    if context.analysis_readiness == "blocked":
        return "degraded"
    if context.analysis_readiness == "observe":
        return "observe"
    if context.selected_state is None:
        return "degraded"
    if any(item.readiness != "ready" for item in _domain_statuses_v2(context)):
        return "observe"
    return "accepted"


def _fact(
    fact_id: str,
    label: str,
    value: object,
    fact_kind: Literal[
        "status",
        "metric",
        "reason",
        "condition",
        "risk",
        "lineage",
        "limitation",
    ],
    source_refs: tuple[SourceReference, ...] = (),
) -> GoldReportFactV2:
    return GoldReportFactV2(
        fact_id=fact_id,
        label=label,
        value=_text(value),
        fact_kind=fact_kind,
        source_refs=source_refs,
    )


def _text(value: object) -> str:
    if value is None:
        return "unavailable"
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value)


def _join(values: tuple[object, ...]) -> str:
    return ", ".join(_text(value) for value in values) or "none"


def _merge_source_refs(
    *groups: tuple[SourceReference, ...],
) -> tuple[SourceReference, ...]:
    unique = {(ref.source, ref.reference, ref.retrieved_at): ref for group in groups for ref in group}
    return tuple(unique[key] for key in sorted(unique))


def _driver_names(drivers: tuple[object, ...]) -> str:
    return _join(tuple(getattr(item, "factor", getattr(item, "name", item)) for item in drivers))


def _attribution_driver_value(driver: object) -> str:
    components = (
        f"factor={_text(getattr(driver, 'factor', 'unavailable'))}",
        f"direction={_text(getattr(driver, 'direction', 'unavailable'))}",
        f"rule={_text(getattr(driver, 'rule_code', 'unavailable'))}",
    )
    contribution = getattr(driver, "contribution", None)
    return "; ".join((*components, *((f"contribution={contribution}",) if contribution is not None else ())))


def _state_projection(state: object | None) -> str:
    if state is None:
        return "unavailable"
    if getattr(state, "schema_version", "") == "analysis_state.v2":
        return (
            f"direction={state.direction}; tilt={state.direction_tilt}; "
            f"regime={state.market_regime}; maturity={state.trend_maturity}"
        )
    return f"direction={state.directional_bias}; stage={state.stage}"


def _transition_projection(transition: object, side: Literal["from", "to"]) -> str:
    if getattr(transition, "schema_version", "") == "analysis_state_transition.v2":
        values = (
            getattr(transition, f"{side}_direction"),
            getattr(transition, f"{side}_direction_tilt"),
            getattr(transition, f"{side}_market_regime"),
            getattr(transition, f"{side}_trend_maturity"),
        )
        if all(value is None for value in values):
            return "unavailable"
        return (
            f"direction={_text(values[0])}; tilt={_text(values[1])}; "
            f"regime={_text(values[2])}; maturity={_text(values[3])}"
        )
    stage = getattr(transition, f"{side}_stage", None)
    return "unavailable" if stage is None else f"stage={_text(stage)}"


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


def _options_lines(options: object) -> tuple[str, ...]:
    expiries = ", ".join(f"{item.expiry}(DTE {item.dte})" for item in options.expiry_scope) or "unavailable"
    skew = ", ".join(f"{item.expiry}:{_display(item.skew_25d)}" for item in options.skew) or "unavailable"
    disclosure = options.model_disclosure
    return (
        f"结算状态：{options.settlement_status}",
        f"结构状态：{options.regime.value}",
        f"方向确认：{options.directional_bias}",
        f"标的价格：{_display(options.underlying_price)}",
        f"到期范围：{expiries}",
        f"Net GEX：{_display(options.net_gex)}",
        f"Gamma Flip：{_display(options.gamma_flip)}",
        f"Pin：{_level_price(options.pin)}",
        f"Call Wall：{_level_price(options.call_wall)}",
        f"Put Wall：{_level_price(options.put_wall)}",
        f"25D Skew：{skew}",
        f"质量：{options.quality_status}/{options.freshness_status}/{options.alignment_status}",
        (
            "模型披露："
            f"{disclosure.model or 'unavailable'}; real_gex={disclosure.used_real_gex}; "
            f"proxy_share={_display(disclosure.proxy_gex_share)}; 非真实 dealer inventory"
        ),
        f"限制原因：{', '.join(options.reason_codes)}",
    )


def _key_level_lines(context: object) -> tuple[str, ...]:
    lines = [
        f"正式关键位：{len(context.key_levels)}",
        f"生命周期决策：{len(context.key_level_decisions)}",
    ]
    for level in context.key_levels:
        lines.append(
            " / ".join(
                (
                    f"{level.spec.role.value}:{_spec_price(level.spec)}",
                    f"comparator={level.spec.comparator.value}",
                    f"lifecycle={level.lifecycle.value}",
                    f"authority={level.authority_status.value}",
                )
            )
        )
    trigger_values = [_spec_price(level.spec) for level in context.key_levels if level.spec.role.value == "trigger"]
    confirmation_values = [
        _spec_price(level.spec) for level in context.key_levels if level.lifecycle.value in {"confirmed", "holding"}
    ]
    invalidation_values = [
        _spec_price(level.spec) for level in context.key_levels if level.spec.role.value == "invalidation"
    ]
    lines.extend(
        (
            f"触发位：{', '.join(trigger_values) or 'unavailable'}",
            f"确认位：{', '.join(confirmation_values) or 'unavailable'}",
            f"失效位：{', '.join(invalidation_values) or 'unavailable'}",
        )
    )
    return tuple(lines)


def _quality_lines(context: object) -> tuple[str, ...]:
    prohibited = ", ".join(item.value if hasattr(item, "value") else str(item) for item in context.prohibited_outputs)
    return (
        f"分析就绪度：{context.analysis_readiness}",
        f"策略就绪度：{context.strategy_readiness}",
        f"期权就绪度：{context.options_readiness}",
        f"事件归因就绪度：{context.event_attribution_readiness}",
        f"禁止输出：{prohibited or 'none'}",
        f"证据引用：{len(context.source_refs)}",
    )


def _level_price(level: object | None) -> str:
    return "unavailable" if level is None else _display(level.strike)


def _spec_price(spec: object) -> str:
    if spec.reference_price is not None:
        return str(spec.reference_price)
    return f"{spec.band_lower}-{spec.band_upper}"


def _display(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


def _digest(render: GoldReportRender) -> str:
    return _digest_payload(render.model_dump(mode="json", exclude={"payload_hash", "render_id"}))


def _digest_v2(render: GoldReportRenderV2) -> str:
    return _digest_payload(render.model_dump(mode="json", exclude={"payload_hash", "render_id"}))


def _digest_payload(payload: object) -> str:
    canonical = json.dumps(
        to_jsonable_python(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
