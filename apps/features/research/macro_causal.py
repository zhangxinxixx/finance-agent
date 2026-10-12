"""L0-L6 evidence graph consumed by the existing research coordinator."""

from copy import deepcopy

from apps.features.macro.policy_path import build_policy_path
from apps.features.macro.treasury_causal import build_treasury


QUESTIONS = [
    ("growth", "经济现在是什么状态？"),
    ("inflation", "通胀是什么性质、动能如何？"),
    ("reaction", "Fed为何可能改变政策？"),
    ("policy", "市场如何定价下一次会议及整条路径？"),
    ("treasury", "国债变化来自实际利率、BE、政策路径还是期限溢价？"),
    ("oil", "原油通过成本通胀还是避险通道影响黄金？"),
    ("response", "黄金价格是否符合宏观传导？"),
    ("residual", "若偏离，哪些需求解释有证据、哪些仍未知？"),
]


def build_macro_causal(snapshot):
    from apps.features.research.market_session import resolve_market_session

    session = resolve_market_session(snapshot["snapshot_time"])
    macro = snapshot.get("macro", {}).get("data", {})
    daily = snapshot.get("daily_research", {})
    rows = daily.get("passport", [])
    treasury = build_treasury(rows)
    policy_source = macro.get("policy_distribution", {})
    documents = snapshot.get("adaptive_research", {}).get("documents", [])
    public_policy = next((d for d in reversed(documents) if d.get('key') == 'FEDWATCH'), None)
    if not policy_source and public_policy:
        policy_source = public_policy.get('policy_distribution', {})
    policy = build_policy_path(policy_source, as_of=snapshot["snapshot_time"],
                               target_reference=macro.get('policy_target_reference'),
                               sep=macro.get('fed_sep'))
    if not policy_source and public_policy:
        policy.update(reason=public_policy.get('reason') or 'public_policy_distribution_unavailable',
                      source_refs=public_policy.get('source_refs', []))
        for row in policy['policy_path']['rows']:
            row.update(reason=policy['reason'], source_refs=deepcopy(policy['source_refs']))
    if macro.get('fedwatch'):
        from apps.features.macro.fedwatch_policy import project_fedwatch_policy, daily_confirmation_context
        policy = project_fedwatch_policy(macro['fedwatch'], as_of=snapshot['snapshot_time'], sep=macro.get('fed_sep'))
        policy['confirmation'] = daily_confirmation_context(rows, as_of=snapshot['snapshot_time'])
    inflation = deepcopy(
        macro.get("inflation", {"status": "unavailable", "reason": "inflation_features_not_collected", "series": {}})
    )
    inflation['value_semantics'] = {
        'mom_yoy_saar': 'system_calculated_from_sourced_index_levels',
        'published_release_values': 'separate_source_required_do_not_label_rounded_calculation_as_official',
        'presentation_note': '指数推算的精确变化率须标为系统计算；官方发布值只有独立发布来源时才单列。',
    }
    by = {r["symbol"]: r for r in rows}
    technical = snapshot.get("technical", {}).get("data", {})
    real_window = treasury["windows"].get("1d", {})
    expected = "UNAVAILABLE"
    if real_window.get("status") == "available":
        delta = real_window["real_bp"]
        expected = "BEARISH" if delta > 0 else "BULLISH" if delta < 0 else "NEUTRAL"
    aligned = bool(real_window.get("status") == "available"
                   and technical.get("as_of") == real_window.get("to")
                   and technical.get("previous_date") == real_window.get("from")
                   and technical.get("source_refs")
                   and isinstance(technical.get("daily_change"), (int, float)))
    actual = "UNAVAILABLE"
    if aligned:
        actual = "BULLISH" if technical["daily_change"] > 0 else "BEARISH" if technical["daily_change"] < 0 else "NEUTRAL"
    response_check = {"expected_direction": expected, "actual_direction": actual,
                      "scope": "real_rate_channel_only_not_complete_gold_return_model",
                      "window_aligned": aligned,
                      "divergence": "MACRO_PRICE_DIVERGENCE" if (expected, actual) in {("BULLISH", "BEARISH"), ("BEARISH", "BULLISH")} else "NOT_CONFIRMED",
                      "expected_return_pct": None, "residual_return_pct": None,
                      "source_refs": deepcopy(technical.get("source_refs", [])) + deepcopy(real_window.get("source_refs", []))}

    def facts(symbols):
        return [deepcopy(by[s]) for s in symbols if s in by]

    growth = {
        "facts": facts(["GDP_NOW", "ISM_MANUFACTURING", "ISM_SERVICES", "ISM_SERVICES_NEW_ORDERS"]),
        "official_details": deepcopy(macro.get("growth", {})),
        "surprise": "unavailable_without_consensus",
    }
    labor = {"official_details": deepcopy(macro.get("employment", {})), "facts": facts(["JOLTS", "INITIAL_CLAIMS"])}
    reaction = {
        "status": "hypothesis_not_Fed_commitment",
        "inputs": {
            "inflation": ["inflation.series.core_pce", "inflation.series.core_cpi"],
            "labor": "labor",
            "growth": "growth",
            "financial_conditions": ["HY_OAS", "VIX", "DXY", "US10Y"],
            "supply_persistence": "oil",
        },
        "alternatives": [
            "sticky_inflation_and_resilient_growth_allow_restriction",
            "supply_shock_and_cooling_labor_can_limit_tightening",
            "financial_stress_can_change_policy_tradeoff",
        ],
        "rule": "weigh evidence and counterevidence; no unconditional CPI-to-hike rule",
    }
    chains = [
        {
            "id": "policy_real_rate",
            "family": "rates",
            "path": [
                "growth/inflation/labor",
                "Fed reaction hypothesis",
                "market policy distribution",
                "real yield",
                "USD",
                "gold",
            ],
            "observed": treasury["windows"],
            "missing_links": [] if policy["status"] == "available" else ["market_policy_distribution"],
            "falsifier": "actual rates/dollar or gold move contradict proposed transmission",
        },
        {
            "id": "oil_dual_channel",
            "family": "rates_or_non_rate_hedge",
            "path": ["energy/supply event", "cost inflation vs hedge demand", "policy/real yield vs gold"],
            "missing_links": ["synchronous event study and verified physical losses"],
            "falsifier": "oil/BE/real yields fail to confirm inflation channel; hedge assets fail to confirm hedge channel",
        },
        {
            "id": "fiscal_duration",
            "family": "fiscal",
            "path": ["issuance/auction demand", "term premium", "long yield", "gold credibility hedge"],
            "missing_links": ["vintage-matched term premium", "issuance/auction/WI evidence"],
            "falsifier": "long-end move explained by policy path without independent fiscal evidence",
        },
    ]
    validation = {
        "role": "test_macro_hypotheses_not_replace_them",
        "domains": ["ETF", "CFTC", "CME_OI_signed_proxy", "PA_4h_1h_15m"],
        "cme_rule": "age weighted; unknown dealer signs; no unsourced spot basis",
        "pa_rule": "closed normal-session bars only; weekend bars cannot create fresh execution signals",
    }
    residual = {
        "status": "unavailable",
        "reason": "no_frozen_fitted_model_out_of_sample_history",
        "interpretation": "unexplained return is not identified central-bank/OTC buying",
        "research_question": "if gold contradicts rates, test USD, hedging, funds and positioning alternatives",
    }
    evidence = {
        "growth": growth,
        "inflation": inflation,
        "reaction": reaction,
        "policy": policy,
        "treasury": treasury,
        "oil": {
            "facts": facts(["BRENT_SPOT", "WTI_SPOT", "DIESEL_GULF_SPOT", "GASOLINE_GULF_SPOT"]),
            "type": "two_channel_hypothesis",
        },
        "response": {
            "channel_check": response_check,
            "rates": treasury["windows"],
            "gold": deepcopy(daily.get("spot_anchor", {})),
            "condition": "compare same observed trading window; qualitative consistency is not a fitted expected return",
        },
        "residual": residual,
    }
    return {
        "schema_version": "gold_macro_causal.v4",
        "snapshot_id": snapshot["snapshot_id"],
        "as_of": snapshot["snapshot_time"],
        "input_snapshot_ids": deepcopy(snapshot.get("input_snapshot_ids", {})),
        "source_refs": deepcopy(snapshot.get("source_refs", [])),
        "status": "partial",
        "layers": {
            "L0": "dated raw facts",
            "L1": "inflation momentum/yield identities",
            "L2": "policy distributions",
            "L3": "conditional Fed reaction",
            "L4": "transmission and falsifiers",
            "L5": "model narrative",
            "L6": "gold response and independent verification",
        },
        "market_session": session,
        "engines": evidence,
        "labor": labor,
        "liquidity_credit": facts(["SOFR_MINUS_IORB", "EFFR_MINUS_IORB", "RESERVES", "TGA", "HY_OAS"]),
        "dollar": {
            "facts": facts(["DXY", "BROAD_DOLLAR"]),
            "missing": ["matched foreign rate differentials and FX attribution"],
        },
        "transmission_chains": chains,
        "validation_layer": validation,
        "questions": [
            {
                "id": k,
                "question": q,
                "evidence_path": "engines." + k,
                "answer_owner": "coordinator_model",
                "requirement": "answer with evidence, alternatives and missing links; unavailable is a valid answer",
            }
            for k, q in QUESTIONS
        ],
        "deduplication": {
            "policy_expectation": ["FedWatch", "2Y", "SOFR futures", "fed funds futures", "OIS"],
            "rates": "policy path and real yields are linked stages, not independent votes",
            "credit": "HY OAS counted once across liquidity/conditions",
        },
        "causal_status": "observational_hypotheses_not_identified_causal_effects",
    }
