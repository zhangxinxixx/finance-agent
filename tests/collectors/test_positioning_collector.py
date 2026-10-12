from __future__ import annotations

import csv
import json
import zipfile
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

from apps.collectors.positioning.collector import collect_positioning_cot
from apps.features.positioning.formal_snapshot import build_cot_positioning_snapshot
from apps.features.positioning.snapshot import build_positioning_snapshot


FIELDNAMES = [
    "Report_Date_as_YYYY-MM-DD",
    "Market_and_Exchange_Names",
    "CFTC_Contract_Market_Code",
    "Open_Interest_All",
    "Prod_Merc_Positions_Long_All",
    "Prod_Merc_Positions_Short_All",
    "Swap_Positions_Long_All",
    "Swap__Positions_Short_All",
    "M_Money_Positions_Long_All",
    "M_Money_Positions_Short_All",
    "Other_Rept_Positions_Long_All",
    "Other_Rept_Positions_Short_All",
    "FutOnly_or_Combined",
]


def _row(
    report_date: str,
    *,
    market: str = "GOLD - COMMODITY EXCHANGE INC.",
    contract_code: str = "088691",
    open_interest: int,
    producer_net: int,
    swap_net: int,
    managed_money_net: int,
) -> dict[str, str]:
    return {
        "Report_Date_as_YYYY-MM-DD": report_date,
        "Market_and_Exchange_Names": market,
        "CFTC_Contract_Market_Code": contract_code,
        "Open_Interest_All": str(open_interest),
        "Prod_Merc_Positions_Long_All": str(max(producer_net, 0)),
        "Prod_Merc_Positions_Short_All": str(max(-producer_net, 0)),
        "Swap_Positions_Long_All": str(max(swap_net, 0)),
        "Swap__Positions_Short_All": str(max(-swap_net, 0)),
        "M_Money_Positions_Long_All": str(max(managed_money_net, 0)),
        "M_Money_Positions_Short_All": str(max(-managed_money_net, 0)),
        "Other_Rept_Positions_Long_All": "1000",
        "Other_Rept_Positions_Short_All": "900",
    }


def _cot_zip(rows: list[dict[str, str]]) -> bytes:
    csv_buffer = StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("f_year.txt", csv_buffer.getvalue())
    return zip_buffer.getvalue()


def test_collect_positioning_uses_standard_gold_contract_and_point_in_time_boundary(
    tmp_path: Path,
) -> None:
    payload = _cot_zip(
        [
            _row(
                "2026-07-07",
                open_interest=360_000,
                producer_net=-18_000,
                swap_net=-190_000,
                managed_money_net=110_000,
            ),
            _row(
                "2026-07-14",
                market="MICRO GOLD - COMMODITY EXCHANGE INC.",
                contract_code="088695",
                open_interest=70_778,
                producer_net=7_000,
                swap_net=144,
                managed_money_net=309,
            ),
            _row(
                "2026-07-14",
                open_interest=371_776,
                producer_net=-20_986,
                swap_net=-201_296,
                managed_money_net=116_161,
            ),
            _row(
                "2026-07-16",
                open_interest=999_999,
                producer_net=50_000,
                swap_net=50_000,
                managed_money_net=-50_000,
            ),
        ]
    )
    response = httpx.Response(
        200,
        content=payload,
        request=httpx.Request("GET", "https://example.test/cot.zip"),
    )

    with patch("httpx.Client.get", return_value=response):
        result = collect_positioning_cot(
            retrieved_date="2026-07-14",
            storage_root=tmp_path,
        )

    points = {point.symbol: point for point in result.points}
    assert result.unavailable_symbols == []
    assert points["COT_GOLD_open_interest"].value == 371_776
    assert points["COT_GOLD_producer_net"].value == -20_986
    assert points["COT_GOLD_swap_net"].value == -201_296
    assert points["COT_GOLD_commercial_net"].value == -222_282
    assert points["COT_GOLD_noncomm_net"].value == 116_161
    assert points["COT_GOLD_producer_net_prev"].date == "2026-07-07"
    assert points["COT_GOLD_producer_net_prev"].value == -18_000
    assert points["COT_GOLD_swap_net_prev"].value == -190_000

    archived_rows = json.loads(
        (tmp_path / result.source_refs[0]["raw_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert {row["CFTC_Contract_Market_Code"] for row in archived_rows} == {"088691"}
    assert max(row["Report_Date_as_YYYY-MM-DD"] for row in archived_rows) == "2026-07-14"

    snapshot = build_positioning_snapshot(
        [point.to_dict() for point in result.points],
        source_refs=result.source_refs,
    )
    assert snapshot.producer_net == -20_986
    assert snapshot.swap_net == -201_296
    assert snapshot.producer_net_prev == -18_000
    assert snapshot.swap_net_prev == -190_000
    assert snapshot.commercial_net == -222_282


def test_collect_positioning_combined_exposes_explicit_report_type_and_real_deltas(
    tmp_path: Path,
) -> None:
    payload = _cot_zip(
        [
            _row(
                "2026-08-25",
                open_interest=644_992,
                producer_net=-21_000,
                swap_net=-200_000,
                managed_money_net=130_000,
            ),
            _row(
                "2026-09-01",
                open_interest=578_926,
                producer_net=-25_000,
                swap_net=-205_000,
                managed_money_net=140_811,
            ),
            _row(
                "2026-09-08",
                open_interest=600_000,
                producer_net=-30_000,
                swap_net=-210_000,
                managed_money_net=150_000,
            ),
        ]
    )
    response = httpx.Response(
        200,
        content=payload,
        request=httpx.Request("GET", "https://example.test/cot.zip"),
    )

    with (
        patch("httpx.Client.get", return_value=response) as get,
        patch("apps.collectors.positioning.collector.utc_now_iso", return_value="2026-09-05T12:00:00Z"),
    ):
        result = collect_positioning_cot(
            retrieved_date="2026-09-05",
            storage_root=tmp_path,
            report_type="combined",
        )

    get.assert_called_once_with(
        "https://www.cftc.gov/files/dea/history/com_disagg_txt_2026.zip"
    )
    points = {point.symbol: point for point in result.points}
    assert result.unavailable_symbols == []
    assert points["COT_GOLD_combined_mm_long"].value == 140_811
    assert points["COT_GOLD_combined_mm_short"].value == 0
    assert points["COT_GOLD_combined_mm_net"].value == 140_811
    assert points["COT_GOLD_combined_mm_net_prev"].value == 130_000
    assert points["COT_GOLD_combined_mm_net_delta"].value == 10_811
    assert points["COT_GOLD_combined_open_interest_delta"].value == -66_066
    ref = result.source_refs[0]
    assert ref["report_type"] == "combined"
    assert ref["report_date"] == "2026-09-01"
    assert ref["previous_report_date"] == "2026-08-25"
    assert ref["raw_path"].startswith("raw/positioning/2026-09-05/")
    assert ref["raw_path"].endswith("/cot_gold_combined.json")
    assert ref["raw_archive_path"].endswith("/cftc_disagg_combined_2026.zip")
    assert (tmp_path / ref["raw_archive_path"]).read_bytes() == payload

    snapshot = build_cot_positioning_snapshot(
        candidates=[point.to_dict() for point in result.points],
        source_refs=result.source_refs,
        report_type="combined",
        as_of=datetime.fromisoformat(result.source_refs[0]["retrieved_at"].replace("Z", "+00:00")),
    )
    assert snapshot.readiness == "ready"
    assert snapshot.report_type == "combined"
    assert snapshot.report_date.isoformat() == "2026-09-01"
    assert snapshot.previous_report_date.isoformat() == "2026-08-25"
    assert snapshot.managed_money.latest.net == 140_811
    assert snapshot.managed_money.previous.net == 130_000
    assert snapshot.managed_money.delta.net == 10_811
    assert snapshot.open_interest.value == 578_926
    assert snapshot.open_interest.previous == 644_992
    assert snapshot.open_interest.delta == -66_066


def test_cftc_row_level_report_type_cannot_be_relabelled_by_the_caller(tmp_path: Path) -> None:
    combined_row = _row(
        "2026-09-01",
        open_interest=578_926,
        producer_net=-25_000,
        swap_net=-205_000,
        managed_money_net=140_811,
    )
    previous_row = _row(
        "2026-08-25",
        open_interest=644_992,
        producer_net=-21_000,
        swap_net=-200_000,
        managed_money_net=130_000,
    )
    combined_row["FutOnly_or_Combined"] = "Combined"
    previous_row["FutOnly_or_Combined"] = "Combined"
    payload = _cot_zip([previous_row, combined_row])
    response = httpx.Response(
        200,
        content=payload,
        request=httpx.Request("GET", "https://example.test/cot.zip"),
    )

    with patch("httpx.Client.get", return_value=response):
        result = collect_positioning_cot(
            retrieved_date="2026-09-05",
            storage_root=tmp_path,
            report_type="futures_only",
        )

    assert result.points == []
    assert result.unavailable_symbols == ["COT_GOLD"]
    assert "No standard GOLD" in result.source_refs[0]["reason"]


def test_repeated_cftc_collect_preserves_original_raw_and_flows_reach_analysis(tmp_path):
    from apps.analysis.agents.positioning import analyze_positioning

    payload = _cot_zip([_row('2026-08-25',open_interest=644992,producer_net=-21000,swap_net=-200000,managed_money_net=150000), _row('2026-09-01',open_interest=578926,producer_net=-25000,swap_net=-205000,managed_money_net=140811)])
    response = httpx.Response(200,content=payload,request=httpx.Request('GET','https://www.cftc.gov/cot.zip'))
    as_of = datetime(2026, 9, 5, 12, tzinfo=UTC)
    with (
        patch('httpx.Client.get',return_value=response),
        patch('apps.collectors.positioning.collector.utc_now_iso', return_value=as_of.isoformat()),
    ):
        first = collect_positioning_cot(retrieved_date='2026-09-05',storage_root=tmp_path,report_type='combined')
        original = {key:(tmp_path/first.source_refs[0][key]).read_bytes() for key in ('raw_path','raw_archive_path')}
        second = collect_positioning_cot(retrieved_date='2026-09-05',storage_root=tmp_path,report_type='combined')
    for key, content in original.items():
        assert first.source_refs[0][key] != second.source_refs[0][key]
        assert (tmp_path/first.source_refs[0][key]).read_bytes() == content
    report = build_cot_positioning_snapshot(candidates=[point.to_dict() for point in second.points],source_refs=second.source_refs,report_type='combined',as_of=as_of).model_dump(mode='json')
    snapshot = {'snapshot_id':'source-to-analysis', 'macro':{'data':{'cot_reports':{'combined':report},'official_etf':{'status':'available','shares_delta':100000,'gold_holdings_tonnes_delta':1}}},'source_refs':second.source_refs}
    output = analyze_positioning(snapshot)
    assert output.bias.value == 'mixed'
    assert any('净仓变化 -9189' in finding for finding in output.key_findings)
    assert any('GLD' in risk for risk in output.risk_points)
