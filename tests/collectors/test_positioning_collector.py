from __future__ import annotations

import csv
import json
import zipfile
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

from apps.collectors.positioning.collector import collect_positioning_cot
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
        (tmp_path / "raw/positioning/2026-07-14/cot_gold.json").read_text(
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
