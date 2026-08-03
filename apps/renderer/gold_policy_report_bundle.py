"""Atomic daily-close report package derived from typed Gold Policy artifacts."""

from __future__ import annotations

from html import escape

from apps.analysis.gold_policy.report_context import GoldReportContext
from apps.renderer.gold_policy_report import GoldReportRender
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
    context: GoldReportContext,
    render: GoldReportRender,
) -> tuple[ImmutableArtifactItem, ...]:
    """Build the complete report package without clocks, LLMs, or legacy prose."""

    source_markdown = _source_markdown(context)
    strategy_payload = _strategy_payload(context)
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
            {
                "schema_version": "gold_policy_report_evidence.v1",
                "authority_result_id": context.authority_result_id,
                "source_refs": [ref.model_dump(mode="json") for ref in context.source_refs],
                "typed_artifact_ids": {
                    "feature_snapshot": context.current_feature_id,
                    "analysis_policy_version": context.analysis_decision.policy_version,
                    "attribution_policy_version": context.price_attribution.policy_version,
                    "transition_decision": context.transition_decision.decision_hash,
                },
            },
        ),
        immutable_json_item(
            "data_quality.json",
            {
                "schema_version": "gold_policy_report_data_quality.v1",
                "authority_result_id": context.authority_result_id,
                "analysis_readiness": context.analysis_readiness,
                "report_status": render.report_status,
                "strategy_status": strategy_payload["status"],
                "no_trade_reason_code": strategy_payload["no_trade_reason_code"],
                "language_generation": "not_invoked",
            },
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


def _source_markdown(context: GoldReportContext) -> str:
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
    lines.extend(
        f"- {ref.source}: {ref.reference} ({ref.retrieved_at.isoformat()})"
        for ref in context.source_refs
    )
    return "\n".join(lines) + "\n"


def _visual_html(render: GoldReportRender) -> str:
    return (
        "<!doctype html>\n"
        "<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<title>XAUUSD Gold Policy Daily Report</title></head>"
        f"<body><pre>{escape(render.markdown)}</pre></body></html>\n"
    )


def _strategy_payload(context: GoldReportContext) -> dict[str, object]:
    strategy = context.selected_strategy
    return {
        "schema_version": "gold_policy_strategy_card.v1",
        "authority_result_id": context.authority_result_id,
        "analysis_state_id": context.selected_state.state_id if context.selected_state else None,
        "candidate_strategy_id": context.candidate_strategy.decision_id if context.candidate_strategy else None,
        "selected_strategy_id": strategy.decision_id if strategy else None,
        "status": strategy.status.value if strategy else "NO_TRADE",
        "direction": strategy.direction.value if strategy else "none",
        "no_trade_reason_code": strategy.no_trade_reason_code.value if strategy and strategy.no_trade_reason_code else "ANALYSIS_STATE_UNAVAILABLE",
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
