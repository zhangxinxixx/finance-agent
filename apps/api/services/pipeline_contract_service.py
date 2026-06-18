"""Read-only contract service for canonical premarket step topology."""

from __future__ import annotations

from typing import Any

from apps.premarket import get_premarket_pipeline_contract, get_premarket_step_contract


def build_premarket_pipeline_contract() -> dict[str, Any]:
    """Return the canonical premarket DAG contract as an API-friendly payload."""
    return get_premarket_pipeline_contract()


def get_premarket_step_contract_view(step_name: str) -> dict[str, Any] | None:
    """Return one canonical premarket step contract as a plain dict."""
    contract = get_premarket_step_contract(step_name)
    return None if contract is None else contract.to_dict()
