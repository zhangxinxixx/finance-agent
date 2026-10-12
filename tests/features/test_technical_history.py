from apps.features.technical.snapshot import build_technical_snapshot
from apps.analysis.agents.technical import analyze_technical


def test_atr_includes_gap_and_does_not_substitute_daily_range():
    closes = [100.0] * 14 + [111.0]
    result = build_technical_snapshot(close=111, closes=closes, highs=[101.0]*14+[112], lows=[99.0]*14+[110])
    assert result.atr14 == round((13*2+12)/14, 6)
    single = build_technical_snapshot(close=111, high=112, low=110)
    assert single.atr14 is None
    assert single.daily_range == 2


def test_flat_history_rsi_neutral_and_exact_fields_reach_agent():
    result = build_technical_snapshot(close=100, closes=[100.0]*50, highs=[101.0]*50, lows=[99.0]*50)
    assert result.ma20 == result.ma50 == 100
    assert result.rsi14 == 50
    output = analyze_technical({'snapshot_id':'s', 'technical':{'status':'available','data':result.to_dict()}})
    assert any('RSI(14) = 50.0' in finding for finding in output.key_findings)
    assert not any('MA20/MA50 approximations unavailable' in reason for reason in output.invalid_conditions)
    assert not any('Perf.1M' in finding for finding in output.key_findings)
