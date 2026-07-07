"""Shared Gold mainline identifiers used by backend read models and frontend generation."""

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

GOLD_TRANSMISSION_CHAIN_IDS = (
    "rate_chain",
    "dollar_chain",
    "war_oil_rate_chain",
    "safe_haven_chain",
    "flow_chain",
    "reserve_chain",
    "asia_demand_chain",
    "technical_chain",
)

GOLD_TRANSMISSION_PATH_IDS = (
    "inflation_to_real_rates",
    "usd_pressure",
    "geopolitics_to_oil_to_rates",
    "haven_bid",
    "capital_confirmation",
    "reserve_reallocation",
    "asia_demand",
    "technical_confirmation",
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

TRANSMISSION_CHAIN_ALIAS_MAP = {
    "rate_chain": "rate_chain",
    "rates_chain": "rate_chain",
    "inflation_to_real_rates": "rate_chain",
    "dollar_chain": "dollar_chain",
    "usd_chain": "dollar_chain",
    "usd_pressure": "dollar_chain",
    "war_oil_rate_chain": "war_oil_rate_chain",
    "geopolitics_to_oil_to_rates": "war_oil_rate_chain",
    "geopolitical_oil_rate_chain": "war_oil_rate_chain",
    "safe_haven_chain": "safe_haven_chain",
    "haven_bid": "safe_haven_chain",
    "flow_chain": "flow_chain",
    "capital_confirmation": "flow_chain",
    "reserve_chain": "reserve_chain",
    "reserve_reallocation": "reserve_chain",
    "asia_demand_chain": "asia_demand_chain",
    "asia_demand": "asia_demand_chain",
    "technical_chain": "technical_chain",
    "technical_confirmation": "technical_chain",
}


def normalize_gold_mainline_id(value: object) -> str:
    mainline_id = str(value or "").strip()
    return MAINLINE_ALIAS_MAP.get(mainline_id, mainline_id)


def normalize_gold_transmission_chain_id(value: object) -> str:
    chain_id = str(value or "").strip()
    return TRANSMISSION_CHAIN_ALIAS_MAP.get(chain_id, chain_id)


__all__ = [
    "GOLD_MAINLINE_IDS",
    "GOLD_TRANSMISSION_CHAIN_IDS",
    "GOLD_TRANSMISSION_PATH_IDS",
    "MAINLINE_ALIAS_MAP",
    "TRANSMISSION_CHAIN_ALIAS_MAP",
    "normalize_gold_mainline_id",
    "normalize_gold_transmission_chain_id",
]
