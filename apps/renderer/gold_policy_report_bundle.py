"""Atomic daily-close report package derived from typed Gold Policy artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from html import escape

from apps.analysis.gold_policy.report_context import (
    GoldReportContextContract,
    GoldReportContextV1_1,
)
from apps.renderer.gold_policy_report import (
    GoldReportFactV2,
    GoldReportRender,
    GoldReportRenderContract,
    GoldReportRenderV2,
    GoldReportSectionV2,
)
from apps.runtime.immutable_artifact import (
    ImmutableArtifactItem,
    immutable_json_item,
    immutable_text_item,
)


_REPORT_FILENAMES = (
    "source.md",
    "analysis.md",
    "visual.html",
    "report_structured.json",
    "evidence.json",
    "data_quality.json",
    "strategy_card.json",
    "strategy_card.md",
)
_REPORT_MANIFEST = "report_manifest.json"


def build_gold_policy_report_bundle(
    context: GoldReportContextContract,
    render: GoldReportRenderContract,
) -> tuple[ImmutableArtifactItem, ...]:
    """Build the complete report package without clocks, LLMs, or legacy prose."""

    if isinstance(render, GoldReportRenderV2):
        return _build_v2_bundle(context, render)
    if isinstance(render, GoldReportRender):
        return _build_v1_bundle(context, render)
    raise TypeError(f"unsupported Gold report render contract: {type(render).__name__}")


def _build_v1_bundle(
    context: GoldReportContextContract,
    render: GoldReportRender,
) -> tuple[ImmutableArtifactItem, ...]:
    """Preserve the historical v1 artifact bytes exactly."""

    source_markdown = _source_markdown(context)
    strategy_payload = _strategy_payload(context)
    evidence_payload = {
        "schema_version": "gold_policy_report_evidence.v1",
        "authority_result_id": context.authority_result_id,
        "source_refs": [ref.model_dump(mode="json") for ref in context.source_refs],
        "typed_artifact_ids": {
            "feature_snapshot": context.current_feature_id,
            "analysis_policy_version": context.analysis_decision.policy_version,
            "attribution_policy_version": context.price_attribution.policy_version,
            "transition_decision": context.transition_decision.decision_hash,
        },
    }
    data_quality_payload = {
        "schema_version": "gold_policy_report_data_quality.v1",
        "authority_result_id": context.authority_result_id,
        "analysis_readiness": context.analysis_readiness,
        "report_status": render.report_status,
        "strategy_status": strategy_payload["status"],
        "no_trade_reason_code": strategy_payload["no_trade_reason_code"],
        "language_generation": "not_invoked",
    }
    formal_options = getattr(context, "cme_options_snapshot", None)
    if formal_options is not None:
        evidence_payload["typed_artifact_ids"]["cme_options_regime"] = formal_options.snapshot_id
        data_quality_payload.update(
            {
                "domain_status": {
                    "analysis": context.analysis_readiness,
                    "strategy": context.strategy_readiness,
                    "options": context.options_readiness,
                    "events": context.event_attribution_readiness,
                    "key_levels": "ready" if context.key_levels else "unavailable",
                },
                "prohibited_outputs": [
                    item.value if hasattr(item, "value") else str(item) for item in context.prohibited_outputs
                ],
                "options_snapshot_id": formal_options.snapshot_id,
                "options_reason_codes": list(formal_options.reason_codes),
            }
        )
    items = (
        immutable_text_item("source.md", source_markdown),
        immutable_text_item("analysis.md", render.markdown),
        immutable_text_item("visual.html", _visual_html(render)),
        immutable_json_item(
            "report_structured.json",
            {
                "schema_version": "gold_policy_report_structured.v1",
                "context_id": context.context_id,
                "render_id": render.render_id,
                "authority_result_id": context.authority_result_id,
                "report_status": render.report_status,
                "sections": [section.model_dump(mode="json") for section in render.sections],
                "language_generation": "not_invoked",
            },
        ),
        immutable_json_item(
            "evidence.json",
            evidence_payload,
        ),
        immutable_json_item(
            "data_quality.json",
            data_quality_payload,
        ),
        immutable_json_item("strategy_card.json", strategy_payload),
        immutable_text_item("strategy_card.md", _strategy_markdown(strategy_payload)),
    )
    if tuple(item.path.as_posix() for item in items) != _REPORT_FILENAMES:
        raise AssertionError("report package filenames are not stable")
    manifest = immutable_json_item(
        _REPORT_MANIFEST,
        {
            "schema_version": "gold_policy_report_manifest.v1",
            "context_id": context.context_id,
            "render_id": render.render_id,
            "authority_result_id": context.authority_result_id,
            "report_status": render.report_status,
            "artifacts": [
                {
                    "filename": item.path.as_posix(),
                    "encoding": item.encoding,
                    "sha256": _sha256(item.content),
                }
                for item in items
            ],
        },
    )
    return (*items, manifest)


def _build_v2_bundle(
    context: GoldReportContextContract,
    render: GoldReportRenderV2,
) -> tuple[ImmutableArtifactItem, ...]:
    """Build the typed v2 report package without deriving facts from prose."""

    if not isinstance(context, GoldReportContextV1_1):
        raise ValueError("gold_policy_report_render.v2 requires gold_report_context.v1.1")
    if render.context_id != context.context_id:
        raise ValueError("report render and context identities do not match")
    if render.authority_result_id != context.authority_result_id:
        raise ValueError("report render and context authority identities do not match")

    source_markdown = _source_markdown(context)
    strategy_payload = _strategy_payload(context)
    domain_statuses = [item.model_dump(mode="json") for item in render.domain_statuses]
    domain_status = {item.domain: item.readiness for item in render.domain_statuses}
    sections = [section.model_dump(mode="json") for section in render.sections]
    source_refs = _v2_source_refs(context, render)
    evidence_payload = {
        "schema_version": "gold_policy_report_evidence.v2",
        "authority_result_id": context.authority_result_id,
        "source_refs": source_refs,
        "input_snapshot_ids": context.input_snapshot_ids.model_dump(mode="json"),
        "artifact_refs": [item.model_dump(mode="json") for item in context.artifact_refs],
        "typed_artifact_ids": {
            "feature_snapshot": context.current_feature_id,
            "analysis_policy_version": context.analysis_decision.policy_version,
            "attribution_policy_version": context.price_attribution.policy_version,
            "transition_decision": context.transition_decision.decision_hash,
        },
    }
    formal_options = context.cme_options_snapshot
    if formal_options is not None:
        evidence_payload["typed_artifact_ids"]["cme_options_regime"] = formal_options.snapshot_id

    prohibited_outputs = sorted({str(output) for domain in domain_statuses for output in domain["prohibited_outputs"]})
    missing_inputs = sorted({str(missing) for domain in domain_statuses for missing in domain["missing_inputs"]})
    data_quality_payload = {
        "schema_version": "gold_policy_report_data_quality.v2",
        "authority_result_id": context.authority_result_id,
        "report_status": render.report_status,
        "publication_status": render.report_status,
        "domain_statuses": domain_statuses,
        "domain_status": domain_status,
        "missing_inputs": missing_inputs,
        "prohibited_outputs": prohibited_outputs,
        "strategy_status": strategy_payload["status"],
        "no_trade_reason_code": strategy_payload["no_trade_reason_code"],
        "language_generation": "not_invoked",
    }
    items = (
        immutable_text_item("source.md", source_markdown),
        immutable_text_item("analysis.md", render.markdown),
        immutable_text_item("visual.html", _visual_html_v2(render)),
        immutable_json_item(
            "report_structured.json",
            {
                "schema_version": "gold_policy_report_structured.v2",
                "context_id": context.context_id,
                "render_id": render.render_id,
                "authority_result_id": context.authority_result_id,
                "report_status": render.report_status,
                "publication_status": render.report_status,
                "domain_statuses": domain_statuses,
                "domain_status": domain_status,
                "sections": sections,
                "language_generation": "not_invoked",
            },
        ),
        immutable_json_item("evidence.json", evidence_payload),
        immutable_json_item("data_quality.json", data_quality_payload),
        immutable_json_item("strategy_card.json", strategy_payload),
        immutable_text_item("strategy_card.md", _strategy_markdown(strategy_payload)),
    )
    if tuple(item.path.as_posix() for item in items) != _REPORT_FILENAMES:
        raise AssertionError("report package filenames are not stable")
    manifest = immutable_json_item(
        _REPORT_MANIFEST,
        {
            "schema_version": "gold_policy_report_manifest.v2",
            "asset": context.asset,
            "trade_date": context.trade_date.isoformat(),
            "session": context.session,
            "run_id": context.run_id,
            "snapshot_id": context.snapshot_id,
            "context_id": context.context_id,
            "render_id": render.render_id,
            "authority_result_id": context.authority_result_id,
            "report_status": render.report_status,
            "publication_status": render.report_status,
            "input_snapshot_ids": context.input_snapshot_ids.model_dump(mode="json"),
            "artifact_refs": [item.model_dump(mode="json") for item in context.artifact_refs],
            "policy_versions": {
                "analysis": context.analysis_decision.policy_version,
                "attribution": context.price_attribution.policy_version,
                "readiness": context.readiness_policy_version,
            },
            "domain_statuses": domain_statuses,
            "domain_status": domain_status,
            "prohibited_outputs": prohibited_outputs,
            "artifacts": [
                {
                    "filename": item.path.as_posix(),
                    "encoding": item.encoding,
                    "sha256": _sha256(item.content),
                }
                for item in items
            ],
        },
    )
    return (*items, manifest)


def _source_markdown(context: GoldReportContextContract) -> str:
    lines = [
        "# XAUUSD Gold Policy Sources",
        "",
        f"- Authority Result: {context.authority_result_id}",
        f"- Feature Snapshot: {context.current_feature_id}",
        f"- Analysis Policy: {context.analysis_decision.policy_version}",
        f"- Attribution Policy: {context.price_attribution.policy_version}",
        "",
        "## Source References",
    ]
    lines.extend(f"- {ref.source}: {ref.reference} ({ref.retrieved_at.isoformat()})" for ref in context.source_refs)
    return "\n".join(lines) + "\n"


def _visual_html(render: GoldReportRender) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>XAUUSD Gold Policy Daily Report</title></head>"
        f"<body><pre>{escape(render.markdown)}</pre></body></html>\n"
    )


def _visual_html_v2(render: GoldReportRenderV2) -> str:
    """Render a self-contained semantic view from typed v2 facts only."""

    section_html = "".join(_visual_section_v2(section) for section in render.sections)
    domain_rows = "".join(
        (
            "<tr>"
            f'<th scope="row">{escape(_text(domain.domain))}</th>'
            f"<td>{escape(_text(domain.readiness))}</td>"
            f"<td>{escape(_joined(domain.missing_inputs))}</td>"
            f"<td>{escape(_joined(domain.prohibited_outputs))}</td>"
            "</tr>"
        )
        for domain in render.domain_statuses
    )
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "base-uri 'none'; form-action 'none'\">"
        "<title>XAUUSD Gold Policy Daily Report</title>"
        f"<style>{_VISUAL_CSS}</style></head><body>"
        '<header class="report-header">'
        '<p class="eyebrow">XAUUSD · Gold Policy</p>'
        "<h1>黄金宏观投研分析报告</h1>"
        f"<p><strong>报告状态：</strong>{escape(_text(render.report_status))}</p>"
        f'<p class="identity"><strong>Authority：</strong>{escape(render.authority_result_id)}</p>'
        "</header><main>"
        '<figure id="domain-readiness"><figcaption>多域就绪度矩阵</figcaption>'
        '<div class="table-scroll"><table><thead><tr>'
        "<th>域</th><th>就绪度</th><th>缺失输入</th><th>禁止输出</th>"
        f"</tr></thead><tbody>{domain_rows}</tbody></table></div></figure>"
        f"{section_html}"
        "</main><footer><p>Research output only; not investment advice or an executable "
        "trading instruction.</p></footer></body></html>\n"
    )


def _visual_section_v2(section: GoldReportSectionV2) -> str:
    facts = "".join(_visual_fact_v2(fact) for fact in section.facts)
    refs = "".join(
        (
            "<li>"
            f"<strong>{escape(ref.source)}</strong>: "
            f"{escape(ref.reference)} "
            f'<time datetime="{escape(ref.retrieved_at.isoformat(), quote=True)}">'
            f"{escape(ref.retrieved_at.isoformat())}</time>"
            "</li>"
        )
        for ref in section.source_refs
    )
    refs_html = (
        f"<details><summary>本节证据（{len(section.source_refs)}）</summary><ol>{refs}</ol></details>"
        if section.source_refs
        else '<p class="unavailable">证据引用：未提供（unavailable）</p>'
    )
    return (
        f'<section id="{escape(section.section_id, quote=True)}" '
        f'data-section-id="{escape(section.section_id, quote=True)}">'
        f"<h2>{escape(section.title)}</h2><dl>{facts}</dl>{refs_html}</section>"
    )


def _visual_fact_v2(fact: GoldReportFactV2) -> str:
    kind = _text(fact.fact_kind)
    value = _text(fact.value)
    unavailable = kind == "unavailable" or value.strip().lower() in {
        "",
        "none",
        "null",
        "unavailable",
    }
    displayed = "未提供（unavailable）" if unavailable else value
    class_name = "fact unavailable" if unavailable else "fact"
    return (
        f'<div class="{class_name}" id="{escape(fact.fact_id, quote=True)}" '
        f'data-fact-id="{escape(fact.fact_id, quote=True)}">'
        f"<dt>{escape(fact.label)} <code>{escape(fact.fact_id)}</code></dt>"
        f'<dd><span class="fact-kind">{escape(kind)}</span> {escape(displayed)}</dd>'
        "</div>"
    )


def _v2_source_refs(
    context: GoldReportContextV1_1,
    render: GoldReportRenderV2,
) -> list[dict[str, object]]:
    refs = [*context.source_refs]
    for section in render.sections:
        refs.extend(section.source_refs)
        for fact in section.facts:
            refs.extend(fact.source_refs)
    by_identity: dict[tuple[str, str, str], dict[str, object]] = {}
    for ref in refs:
        payload = ref.model_dump(mode="json")
        identity = (ref.source, ref.reference, ref.retrieved_at.isoformat())
        by_identity[identity] = payload
    return [by_identity[key] for key in sorted(by_identity)]


def _text(value: object) -> str:
    raw = value.value if hasattr(value, "value") else value
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if raw is None:
        return "unavailable"
    return str(raw)


def _joined(values: Iterable[object]) -> str:
    rendered = [_text(value) for value in values]
    return ", ".join(rendered) if rendered else "none"


_VISUAL_CSS = """
:root{color-scheme:light;--bg:#f4f1e8;--paper:#fffdf7;--ink:#17201d;--muted:#59645f;
--line:#d8d2c3;--gold:#8a6519;--warn:#8a3e1b}*{box-sizing:border-box}body{margin:0;
background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.report-header,main,footer{width:min(1120px,calc(100% - 32px));margin:auto}.report-header{padding:48px 0 24px}
.eyebrow{color:var(--gold);font-weight:700;letter-spacing:.1em;text-transform:uppercase}h1{font-size:2rem;
margin:.2rem 0}.identity{overflow-wrap:anywhere;color:var(--muted)}main{display:grid;gap:18px;padding-bottom:36px}
section,figure{margin:0;background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:22px}
h2,figcaption{margin:0 0 14px;font-size:1.2rem;font-weight:700}.table-scroll{overflow-x:auto}table{width:100%;
border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
dl{display:grid;gap:10px;margin:0}.fact{display:grid;grid-template-columns:minmax(180px,1fr) 2fr;gap:16px;
padding:10px 0;border-bottom:1px solid var(--line)}dt{font-weight:650}dd{margin:0;overflow-wrap:anywhere}
code,.fact-kind{font-size:.78rem;color:var(--muted)}.fact-kind{display:inline-block;margin-right:8px;padding:1px 6px;
border:1px solid var(--line);border-radius:999px}.unavailable{color:var(--warn);font-weight:650}details{margin-top:16px}
ol{padding-left:22px}footer{padding:0 0 40px;color:var(--muted)}@media(max-width:680px){.fact{grid-template-columns:1fr}}
""".strip()


def _strategy_payload(context: GoldReportContextContract) -> dict[str, object]:
    strategy = context.selected_strategy
    return {
        "schema_version": "gold_policy_strategy_card.v1",
        "authority_result_id": context.authority_result_id,
        "analysis_state_id": context.selected_state.state_id if context.selected_state else None,
        "candidate_strategy_id": context.candidate_strategy.decision_id if context.candidate_strategy else None,
        "selected_strategy_id": strategy.decision_id if strategy else None,
        "status": strategy.status.value if strategy else "NO_TRADE",
        "direction": strategy.direction.value if strategy else "none",
        "no_trade_reason_code": strategy.no_trade_reason_code.value
        if strategy and strategy.no_trade_reason_code
        else "ANALYSIS_STATE_UNAVAILABLE",
        "reason_codes": list(strategy.reason_codes) if strategy else ["ANALYSIS_STATE_UNAVAILABLE"],
        "language_generation": "not_invoked",
    }


def _strategy_markdown(payload: dict[str, object]) -> str:
    return "\n".join(
        (
            "# XAUUSD Gold Policy Strategy Card",
            "",
            f"- Authority Result: {payload['authority_result_id']}",
            f"- Status: {payload['status']}",
            f"- Direction: {payload['direction']}",
            f"- NO_TRADE Reason: {payload['no_trade_reason_code']}",
            "",
            "Research output only; not investment advice or an executable trading instruction.",
            "",
        )
    )


def _sha256(content: bytes) -> str:
    import hashlib

    return hashlib.sha256(content).hexdigest()
