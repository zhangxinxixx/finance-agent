#!/usr/bin/env python3
"""Full coordinator regression after data unwrap fix."""
# ruff: noqa: E402

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.analysis.agents.cme_options import analyze_cme_options
from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
from apps.analysis.agents.risk import analyze_risk
from apps.analysis.agents.technical import analyze_technical
from apps.analysis.agents.positioning import analyze_positioning
from apps.analysis.agents.news import analyze_news
from apps.analysis.agents.market_odds import analyze_market_odds
from apps.analysis.agents.coordinator import coordinate_agent_outputs

p = ROOT / "storage/features/snapshots/XAUUSD/2026-06-08/e102d8cd-e0ef-4be0-8ace-88be91a33702/premarket_snapshot.json"
if not p.exists():
    pytest.skip("local snapshot fixture is not committed", allow_module_level=True)

with open(p) as f:
    snap = json.load(f)

cme = analyze_cme_options(snap)
macro = analyze_macro_liquidity(snap)
risk = analyze_risk(snap, macro_output=macro, options_output=cme)
tech = analyze_technical(snap)
pos = analyze_positioning(snap)
news = analyze_news(snap)
odds = analyze_market_odds(snap)
coord = coordinate_agent_outputs(snap, macro_output=macro, options_output=cme, risk_output=risk,
                                  technical_output=tech, positioning_output=pos, news_output=news,
                                  market_odds_output=odds)

print(f"coordinator: bias={coord.bias.value} confidence={coord.confidence:.2f} status={coord.status.value}")
print(f"summary: {coord.summary}")
print(f"findings ({len(coord.key_findings)}):")
for f_ in coord.key_findings:
    print(f"  - {f_}")
