"""Shared Gold mainline identifiers used by backend read models."""

from __future__ import annotations

GOLD_MAINLINE_IDS = (
    "fed_policy_path",
    "real_rates_usd",
    "oil_prices",
    "geopolitical_war_risk",
    "etf_flows",
    "institutional_sentiment",
    "central_bank_gold",
    "china_asia_demand",
    "gold_technical_levels",
)

MAINLINE_ALIAS_MAP = {
    "real_rates_dollar": "real_rates_usd",
    "oil_price": "oil_prices",
    "geopolitical_war": "geopolitical_war_risk",
    "technical_structure": "gold_technical_levels",
    "cme_options_positioning": "institutional_sentiment",
    "etf_flow": "etf_flows",
    "inflation_growth": "fed_policy_path",
    "liquidity_credit": "real_rates_usd",
    "comex_options_institutional_sentiment": "institutional_sentiment",
    "central_bank_monetary_credit": "central_bank_gold",
    "gold_technical_phase": "gold_technical_levels",
}


def normalize_gold_mainline_id(value: object) -> str:
    mainline_id = str(value or "").strip()
    return MAINLINE_ALIAS_MAP.get(mainline_id, mainline_id)
