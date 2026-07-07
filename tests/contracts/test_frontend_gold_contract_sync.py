from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from apps.contracts import gold as gold_contract
from apps.gold_mainline_contract import (
    GOLD_MAINLINE_IDS,
    GOLD_TRANSMISSION_CHAIN_IDS,
    GOLD_TRANSMISSION_PATH_IDS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_GOLD_TYPES = PROJECT_ROOT / "apps/frontend-web/src/types/gold-mainlines.ts"
FRONTEND_PROCESSING_TYPES = PROJECT_ROOT / "apps/frontend-web/src/types/processing-monitor.ts"
FRONTEND_GENERATED_GOLD_CONTRACT = PROJECT_ROOT / "apps/frontend-web/src/generated/gold-contract.ts"
GENERATE_FRONTEND_CONTRACTS = PROJECT_ROOT / "scripts/generate_frontend_contracts.py"


def _extract_generated_const_literals(const_name: str) -> list[str]:
    source = FRONTEND_GENERATED_GOLD_CONTRACT.read_text(encoding="utf-8")
    match = re.search(
        rf"export const {re.escape(const_name)}\s*=\s*\[(?P<body>.*?)\]\s*as const;",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, f"Missing generated const: {const_name}"
    return re.findall(r'"([^"]+)"', match.group("body"))


def test_gold_contract_has_canonical_module_and_compatibility_shim() -> None:
    assert gold_contract.GOLD_MAINLINE_IDS is GOLD_MAINLINE_IDS
    assert gold_contract.GOLD_TRANSMISSION_CHAIN_IDS is GOLD_TRANSMISSION_CHAIN_IDS
    assert gold_contract.GOLD_TRANSMISSION_PATH_IDS is GOLD_TRANSMISSION_PATH_IDS


def test_generated_frontend_gold_contract_matches_backend_contract() -> None:
    assert _extract_generated_const_literals("GOLD_MAINLINE_IDS") == list(GOLD_MAINLINE_IDS)
    assert _extract_generated_const_literals("GOLD_TRANSMISSION_CHAIN_IDS") == list(GOLD_TRANSMISSION_CHAIN_IDS)
    assert _extract_generated_const_literals("GOLD_TRANSMISSION_PATH_IDS") == list(GOLD_TRANSMISSION_PATH_IDS)


def test_frontend_gold_types_reexport_generated_contract_types() -> None:
    source = FRONTEND_GOLD_TYPES.read_text(encoding="utf-8")

    assert 'from "@/generated/gold-contract"' in source
    assert "export type { GoldMainline, TransmissionChain, TransmissionPath }" in source
    assert re.search(r"export type GoldMainline\s*=", source) is None
    assert re.search(r"export type TransmissionChain\s*=", source) is None
    assert re.search(r"export type TransmissionPath\s*=", source) is None


def test_frontend_gold_view_model_types_do_not_accept_arbitrary_string_enums() -> None:
    source = FRONTEND_GOLD_TYPES.read_text(encoding="utf-8")

    assert "| string" not in source


def test_processing_monitor_view_model_types_do_not_accept_arbitrary_string_enums() -> None:
    source = FRONTEND_PROCESSING_TYPES.read_text(encoding="utf-8")

    assert "| string" not in source


def test_frontend_gold_contract_generation_is_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATE_FRONTEND_CONTRACTS), "--check"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
