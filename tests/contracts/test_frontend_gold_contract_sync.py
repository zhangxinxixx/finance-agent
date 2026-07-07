from __future__ import annotations

import re
from pathlib import Path

from apps.gold_mainline_contract import (
    GOLD_MAINLINE_IDS,
    GOLD_TRANSMISSION_CHAIN_IDS,
    GOLD_TRANSMISSION_PATH_IDS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_GOLD_TYPES = PROJECT_ROOT / "apps/frontend-web/src/types/gold-mainlines.ts"


def _extract_ts_union_literals(type_name: str) -> set[str]:
    source = FRONTEND_GOLD_TYPES.read_text(encoding="utf-8")
    match = re.search(rf"export type {re.escape(type_name)}\s*=\s*(.*?);", source, flags=re.DOTALL)
    assert match is not None, f"Missing frontend type union: {type_name}"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_frontend_gold_mainline_union_matches_backend_contract() -> None:
    assert _extract_ts_union_literals("GoldMainline") == set(GOLD_MAINLINE_IDS)


def test_frontend_transmission_chain_union_matches_backend_contract() -> None:
    assert _extract_ts_union_literals("TransmissionChain") == set(GOLD_TRANSMISSION_CHAIN_IDS)


def test_frontend_transmission_path_union_matches_backend_contract() -> None:
    assert _extract_ts_union_literals("TransmissionPath") == set(GOLD_TRANSMISSION_PATH_IDS)
