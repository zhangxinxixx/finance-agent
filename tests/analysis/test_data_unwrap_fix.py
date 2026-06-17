#!/usr/bin/env python3
"""Smoke test: verify CME options data unwrap and ON RRP key mapping fixes.

Runs CME options and macro liquidity agents against the real June 8 snapshot
and checks that previously-broken fields are now detected.
"""
# ruff: noqa: E402

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.agents.cme_options import analyze_cme_options
from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity

SNAPSHOT_PATH = (
    PROJECT_ROOT
    / "storage/features/snapshots/XAUUSD/2026-06-08"
    / "e102d8cd-e0ef-4be0-8ace-88be91a33702/premarket_snapshot.json"
)


def main() -> int:
    if not SNAPSHOT_PATH.exists():
        print(f"SKIP: snapshot not found at {SNAPSHOT_PATH}", file=sys.stderr)
        return 0

    with open(SNAPSHOT_PATH) as f:
        snapshot = json.load(f)

    errors = 0

    # ── CME Options Agent ───────────────────────────────────────────────
    print("=== CME Options Agent ===")
    cme = analyze_cme_options(snapshot)
    print(f"  status: {cme.status.value}")
    print(f"  bias: {cme.bias.value}")
    print(f"  confidence: {cme.confidence:.2f}")
    print(f"  key_findings ({len(cme.key_findings)}):")
    for f_ in cme.key_findings[:5]:
        print(f"    - {f_}")
    print(f"  risk_points ({len(cme.risk_points)}):")
    for r in cme.risk_points[:3]:
        print(f"    - {r}")

    # Check that previously-missing fields are now detected
    has_numeric = any(
        "strike" in f_.lower() or "support" in f_.lower() or "resistance" in f_.lower()
        or "block" in f_.lower() or "gex" in f_.lower()
        for f_ in cme.key_findings
    )
    if has_numeric:
        print("  ✅ CME options: numeric strike/wall data detected")
    else:
        print("  ❌ CME options: still no numeric strike/wall data")
        errors += 1

    if cme.confidence > 0.15:
        print(f"  ✅ CME confidence > 0.15 ({cme.confidence:.2f})")
    else:
        print(f"  ❌ CME confidence still low ({cme.confidence:.2f})")
        errors += 1

    # ── Macro Liquidity Agent ───────────────────────────────────────────
    print("\n=== Macro Liquidity Agent ===")
    macro = analyze_macro_liquidity(snapshot)
    print(f"  status: {macro.status.value}")
    print(f"  bias: {macro.bias.value}")
    print(f"  confidence: {macro.confidence:.2f}")
    print(f"  key_findings ({len(macro.key_findings)}):")
    for f_ in macro.key_findings[:5]:
        print(f"    - {f_}")
    print(f"  risk_points ({len(macro.risk_points)}):")
    for r in macro.risk_points[:5]:
        print(f"    - {r}")

    # Check ON RRP is no longer reported as missing
    on_rrp_missing = any("ON RRP" in r for r in macro.risk_points)
    if on_rrp_missing:
        print("  ❌ Macro: ON RRP still reported as incomplete")
        errors += 1
    else:
        print("  ✅ Macro: ON RRP no longer reported as incomplete")

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    if errors == 0:
        print("✅ ALL CHECKS PASSED")
        return 0
    else:
        print(f"❌ {errors} ERROR(S)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
