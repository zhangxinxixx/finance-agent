from __future__ import annotations

from apps.analysis.strategy.schemas import StrategyCardOutput
from apps.decision.schemas import StrategyDecision


def build_strategy_card_from_decision(decision: StrategyDecision) -> StrategyCardOutput:
    """Render a research-only StrategyCardOutput from a StrategyDecision."""

    return StrategyCardOutput(
        version=decision.version,
        asset=decision.asset,
        trade_date=decision.trade_date,
        run_id=decision.run_id,
        bias=decision.bias,
        confidence=decision.confidence,
        scenario_summary=(
            f"StrategyDecision research view is {decision.bias.value}; "
            f"feasibility={decision.feasibility_label}, confidence={decision.confidence:.2f}."
        ),
        key_levels_from_options=[],
        risk_points=[
            f"feasibility={decision.feasibility_label}: {reason}"
            for reason in decision.feasibility_reasons
        ],
        invalid_conditions=list(decision.invalidation_conditions),
        watchlist=list(decision.required_confirmations),
        source_refs=list(decision.source_refs),
        input_snapshot_ids={
            "analysis_snapshot": decision.snapshot_id,
            "coordinator": decision.snapshot_id,
            "strategy_decision": decision.snapshot_id,
        },
        created_at=decision.created_at,
        is_trade_instruction=False,
        market_regime=decision.regime_context,
        evidence_refs=list(decision.evidence_items),
        data_quality=[],
        data_category_summary={},
        confidence_kernel=decision.confidence_kernel.model_dump(mode="json"),
    )
