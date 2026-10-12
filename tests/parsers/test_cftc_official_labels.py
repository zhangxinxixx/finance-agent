from datetime import date
from pathlib import Path

from apps.parsers.positioning.cftc import parse_cftc_disaggregated_text


def test_actual_official_futonly_label_and_combined_isolation():
    # Public CFTC fut_disagg_txt_2026.zip, standard GOLD rows 2026-09-01/08-25.
    raw = (Path(__file__).parents[1] / 'fixtures/positioning/cftc_futonly_20260901.csv').read_text()
    report = parse_cftc_disaggregated_text(raw, report_type='futures_only', cutoff_date=date(2026, 9, 5))
    latest, previous = report.latest_pair()
    assert latest.managed_money_net == 136771
    assert latest.open_interest == 415196
    assert previous.managed_money_net == 144747
    assert previous.open_interest == 427957
    assert not parse_cftc_disaggregated_text(raw, report_type='combined', cutoff_date=date(2026, 9, 5)).rows
